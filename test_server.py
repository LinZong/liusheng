import http.client
import json
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

import server


class DeliveryTests(unittest.TestCase):
    def test_terminal_detection_uses_app_name_boundaries(self):
        for app in ('kitty', 'org.wezfurlong.wezterm', 'gnome-terminal-server', 'org.kde.konsole'):
            self.assertEqual(server.paste_shortcut(app, 'auto'), 'terminal')
        for app in ('jetbrains-studio', 'org.gnome.TextEditor', 'firefox', 'code'):
            self.assertEqual(server.paste_shortcut(app, 'auto'), 'normal')

    def test_background_output_does_not_delay_command(self):
        command = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'])"
        started = time.monotonic()
        server.run_command([sys.executable, '-c', command])
        self.assertLess(time.monotonic() - started, 1.5)

    def test_command_failure_includes_detail(self):
        with self.assertRaisesRegex(RuntimeError, 'probe error'):
            server.run_command([sys.executable, '-c', "import sys; sys.exit('probe error')"])

    def test_invalid_text_rejected_before_clipboard(self):
        for text in ('', 'a' * (server.MAX_TEXT + 1), '\ud800', '\x00'):
            with self.subTest(text=repr(text[:20])):
                with self.assertRaises(ValueError), patch.object(server, 'run_command') as run:
                    server.deliver(text, 'auto', 'auto')
                run.assert_not_called()

    def test_delivery_uses_terminal_shortcut_and_plain_text(self):
        with patch.object(server.shutil, 'which', side_effect=lambda name: '/bin/' + name), \
             patch.object(server, 'focused_window', return_value={'id': 1, 'app_id': 'kitty'}), \
             patch.object(server, 'run_command') as run, \
             patch.object(server, 'emit_paste') as emit:
            result = server.deliver('你好', 'auto', 'auto')
        run.assert_called_once_with(['wl-copy', '--type', 'text/plain;charset=utf-8'], input_data='你好')
        emit.assert_called_once_with('wtype', 'terminal')
        self.assertTrue(result['ok'])

    def test_key_delivery_on_both_backends_without_clipboard(self):
        commands = {
            ('wtype', 'enter'): ['wtype', '-k', 'Return'],
            ('wtype', 'ctrl_enter'): ['wtype', '-M', 'ctrl', '-k', 'Return', '-m', 'ctrl'],
            ('ydotool', 'enter'): ['ydotool', 'key', '28:1', '28:0'],
            ('ydotool', 'ctrl_enter'): ['ydotool', 'key', '29:1', '28:1', '28:0', '29:0'],
        }
        for (backend, key), command in commands.items():
            with self.subTest(backend=backend, key=key), \
                 patch.object(server.shutil, 'which', side_effect=lambda name: '/bin/' + name if name == backend else None), \
                 patch.object(server, 'focused_window', return_value={'id': 1}), \
                 patch.object(server, 'run_command') as run:
                result = server.deliver_key(key, backend)
                self.assertEqual(result['target'], {'id': 1})
                run.assert_called_once_with(command)

    def test_text_is_pasted_before_key_and_failure_stops_submission(self):
        for key in ('enter', 'ctrl_enter'):
            with self.subTest(key=key), \
                 patch.object(server.shutil, 'which', return_value='/bin/tool'), \
                 patch.object(server, 'focused_window', return_value={'id': 1, 'app_id': 'kitty'}), \
                 patch.object(server, 'run_command') as run, \
                 patch.object(server.time, 'sleep'):
                server.deliver_key(key, 'wtype', '你好')
                self.assertEqual(run.call_args_list[0].args[0][0], 'wl-copy')
                self.assertEqual(run.call_args_list[0].kwargs['input_data'], '你好')
                self.assertIn('shift', run.call_args_list[1].args[0])
                self.assertIn('Return', run.call_args_list[2].args[0])
                self.assertEqual(len(run.call_args_list), 3)
                run.reset_mock()
                with patch.object(server, 'emit_paste', side_effect=RuntimeError('paste failed')):
                    with self.assertRaises(RuntimeError):
                        server.deliver_key(key, 'wtype', '你好')
                run.assert_called_once()

    def test_key_validation_and_failures_do_not_send_again(self):
        for key in (None, '', 'tab', [], {}):
            with self.subTest(key=key), patch.object(server, 'run_command') as run:
                with self.assertRaises(ValueError):
                    server.deliver_key(key, 'auto')
                run.assert_not_called()
        with patch.object(server.shutil, 'which', return_value=None):
            with self.assertRaises(RuntimeError):
                server.deliver_key('enter', 'auto')
        with patch.object(server.shutil, 'which', return_value='/bin/tool'), \
             patch.object(server, 'focused_window', return_value=None), \
             patch.object(server, 'run_command', side_effect=RuntimeError('failed')) as run:
            with self.assertRaises(RuntimeError):
                server.deliver_key('ctrl_enter', 'auto')
            run.assert_called_once()

    def test_failed_paste_is_not_retried(self):
        with patch.object(server.shutil, 'which', return_value='/bin/tool'), \
             patch.object(server, 'focused_window', return_value=None), \
             patch.object(server, 'run_command'), \
             patch.object(server, 'emit_paste', side_effect=RuntimeError('failed')) as emit:
            with self.assertRaises(RuntimeError):
                server.deliver('hello', 'auto', 'auto')
        emit.assert_called_once()


class HttpTests(unittest.TestCase):
    def test_routes_and_input_validation(self):
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        httpd.backend = 'auto'
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            conn = http.client.HTTPConnection(*httpd.server_address, timeout=3)
            conn.request('GET', '/')
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn('流声', response.read().decode())
            for path, (filename, content_type) in server.STATIC_FILES.items():
                with self.subTest(path=path):
                    conn.request('GET', path + '?pwa-test=1')
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader('Content-Type'), content_type)
                    self.assertEqual(response.read(), (server.ROOT / filename).read_bytes())
            manifest = json.loads((server.ROOT / 'manifest.webmanifest').read_text())
            self.assertEqual(manifest['display'], 'standalone')
            for icon in manifest['icons']:
                png = (server.ROOT / icon['src'].lstrip('/')).read_bytes()
                self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                dimensions = struct.unpack('>II', png[16:24])
                self.assertEqual('x'.join(map(str, dimensions)), icon['sizes'])
            conn.request('GET', '/api/status')
            response = conn.getresponse()
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            self.assertTrue(json.loads(response.read())['ok'])
            for payload in ({'text': ''}, {'text': '\ud800'}, {'text': '\x00'}, [], {'text': 'hi', 'paste_mode': []}):
                conn.request('POST', '/api/send', json.dumps(payload))
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
            with patch.object(server, 'deliver', return_value={'ok': True}) as deliver:
                conn.request('POST', '/api/send', json.dumps({'text': '你好'}))
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())['ok'])
                deliver.assert_called_once_with('你好', 'auto', 'auto')
            for payload in ({}, {'key': 'tab'}, {'key': []}, {'key': 'enter', 'text': []}, {'key': 'enter', 'text': '\x00'}, []):
                conn.request('POST', '/api/key', json.dumps(payload))
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
            for key in ('enter', 'ctrl_enter'):
                with patch.object(server, 'deliver_key', return_value={'ok': True}) as deliver_key:
                    conn.request('POST', '/api/key', json.dumps({'key': key}))
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())['ok'])
                    deliver_key.assert_called_once_with(key, 'auto', '')
            with patch.object(server, 'deliver_key', return_value={'ok': True}) as deliver_key:
                conn.request('POST', '/api/key', json.dumps({'key': 'enter', 'text': '你好'}))
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                deliver_key.assert_called_once_with('enter', 'auto', '你好')
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
