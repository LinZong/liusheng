#!/usr/bin/env python3
"""Niri Voice Input — phone-to-focused-window text paste, stdlib only."""

import argparse
import json
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/icons/icon.svg": ("icons/icon.svg", "image/svg+xml"),
    "/icons/icon-192.png": ("icons/icon-192.png", "image/png"),
    "/icons/icon-512.png": ("icons/icon-512.png", "image/png"),
    "/icons/icon-maskable-512.png": ("icons/icon-maskable-512.png", "image/png"),
    "/icons/apple-touch-icon.png": ("icons/apple-touch-icon.png", "image/png"),
}
MAX_BODY = 256 * 1024
MAX_TEXT = 64_000
PASTE_LOCK = threading.Lock()
TERMINAL_APP_IDS = (
    "foot", "alacritty", "kitty", "ghostty", "wezterm", "konsole",
    "gnome-terminal", "gnome.console", "org.gnome.console", "xterm",
    "tilix", "terminator", "st", "rio", "com.mitchellh.ghostty",
    "org.wezfurlong.wezterm", "com.raggesilver.blackbox", "io.elementary.terminal",
)


def focused_window():
    if not shutil.which("niri"):
        return None
    try:
        completed = subprocess.run(
            ["niri", "msg", "--json", "focused-window"],
            text=True, capture_output=True, timeout=2, check=True,
        )
        result = json.loads(completed.stdout)
        return result if isinstance(result, dict) and result.get("id") is not None else None
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def get_backend(configured):
    if configured == "auto":
        for item in ("wtype", "ydotool"):
            if shutil.which(item):
                return item
        return None
    return configured if shutil.which(configured) else None


def paste_shortcut(app_id, mode):
    if mode == "normal":
        return "normal"
    if mode == "terminal":
        return "terminal"
    app = (app_id or "").lower()
    is_terminal = any(
        app == part or app.startswith(part + "-") or app.startswith(part + ".")
        or app.endswith("." + part)
        for part in TERMINAL_APP_IDS
    )
    return "terminal" if is_terminal else "normal"


def run_command(args, *, input_data=None):
    try:
        # wl-copy forks a clipboard owner that inherits its output descriptors.
        # Pipes make communicate() wait for that owner and falsely time out.
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output:
            result = subprocess.run(
                args, input=input_data, text=True, stdout=output, stderr=output,
                timeout=4, check=False,
            )
            output.seek(0)
            detail = output.read(4096).strip()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"命令执行超时：{args[0]}") from exc
    except OSError as exc:
        raise RuntimeError(f"无法执行 {args[0]}：{exc}") from exc
    if result.returncode:
        raise RuntimeError(f"{args[0]} 执行失败：{(detail or '未知错误')[:400]}")


def emit_paste(backend, mode):
    if backend == "wtype":
        if mode == "terminal":
            run_command(["wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"])
        else:
            run_command(["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"])
    elif backend == "ydotool":
        if mode == "terminal":
            # Linux key codes: LEFTCTRL=29, LEFTSHIFT=42, V=47
            run_command(["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"])
        else:
            run_command(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])
    else:
        raise RuntimeError("请安装 wtype 或 ydotool")


def deliver(text, paste_mode, configured_backend):
    if not text:
        raise ValueError("不能发送空文本")
    if len(text) > MAX_TEXT:
        raise ValueError(f"文字过长，最多 {MAX_TEXT} 字符")
    if "\x00" in text:
        raise ValueError("文字不能包含空字符")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("文字包含无效的 Unicode 字符") from exc
    if not shutil.which("wl-copy"):
        raise RuntimeError("未安装 wl-copy：请安装 wl-clipboard")

    backend = get_backend(configured_backend)
    if backend is None:
        raise RuntimeError("未安装输入工具：请安装 wtype（或备用 ydotool）")

    with PASTE_LOCK:
        target = focused_window()
        detected = paste_shortcut((target or {}).get("app_id"), paste_mode)
        run_command(["wl-copy", "--type", "text/plain;charset=utf-8"], input_data=text)
        # A failure may follow partial execution; don't risk pasting twice.
        emit_paste(backend, detected)

    return {"ok": True, "backend": backend, "paste_mode": detected,
            "target": target, "message": "已发送粘贴快捷键（无法确认目标应用是否实际插入）"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            raw = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif path == "/api/status":
            self.send_json({
                "ok": True,
                "backend": get_backend(self.server.backend),
                "clipboard": bool(shutil.which("wl-copy")),
                "target": focused_window(),
            })
        else:
            self.send_json({"ok": False, "message": "未找到页面"}, 404)

    def do_POST(self):
        if self.path != "/api/send":
            return self.send_json({"ok": False, "message": "未找到接口"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json({"ok": False, "message": "请求格式错误"}, 400)
        if length < 1 or length > MAX_BODY:
            return self.send_json({"ok": False, "message": "请求大小不合法"}, 413)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
                raise ValueError("缺少文字")
            mode = payload.get("paste_mode", "auto")
            if mode not in ("auto", "normal", "terminal"):
                raise ValueError("无效的粘贴模式")
            result = deliver(payload["text"], mode, self.server.backend)
            self.send_json(result)
        except (ValueError, UnicodeError) as exc:
            self.send_json({"ok": False, "message": str(exc)}, 400)
        except RuntimeError as exc:
            self.send_json({"ok": False, "message": str(exc)}, 503)

    def log_message(self, fmt, *args):
        # No content logging: useful when dictating private notes or source code.
        if not self.path.startswith("/api/status"):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description="Niri Voice Input: phone -> desktop focused input")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--backend", choices=("auto", "wtype", "ydotool"), default="auto")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.backend = args.backend
    print(f"\nNiri Voice Input 已启动： http://127.0.0.1:{args.port}", flush=True)
    print(f"手机访问： http://<Linux局域网IP>:{args.port}", flush=True)
    print("查看本机 IP：hostname -I", flush=True)
    print(f"输入后端：{get_backend(args.backend) or '缺失（请安装 wtype）'}", flush=True)
    print("在 Niri 图形会话内运行；Ctrl+C 停止。\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
