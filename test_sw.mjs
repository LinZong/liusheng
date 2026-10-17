import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function worker(fetch) {
  const handlers = {};
  const entries = new Map();
  const cache = {
    async match(key) { return entries.get(key)?.clone(); },
    async put(key, value) { entries.set(key, value); }
  };
  vm.runInNewContext(readFileSync(new URL('./sw.js', import.meta.url), 'utf8'), {
    self: {
      location: { origin: 'https://voice.lleo.fun' },
      addEventListener(name, callback) { handlers[name] = callback; }
    },
    URL, fetch,
    caches: { async open() { return cache; } }
  });
  return {
    entries,
    dispatch(path, options) {
      let response;
      handlers.fetch({
        request: new Request(new URL(path, 'https://voice.lleo.fun'), options),
        respondWith(value) { response = value; }
      });
      return response;
    }
  };
}

test('APIs and sends bypass service worker caching, including offline', () => {
  const sw = worker(() => { throw new Error('must not intercept'); });
  assert.equal(sw.dispatch('/api/status'), undefined);
  assert.equal(sw.dispatch('/api/send', { method:'POST', body:'hello' }), undefined);
  assert.equal(sw.dispatch('https://example.com/'), undefined);
});

test('offline launch returns cached shell including index alias and query', async () => {
  const sw = worker(async () => { throw new TypeError('offline'); });
  sw.entries.set('/', new Response('cached shell'));
  assert.equal(await (await sw.dispatch('/')).text(), 'cached shell');
  assert.equal(await (await sw.dispatch('/index.html?source=home')).text(), 'cached shell');
});

test('online navigation refreshes cached shell', async () => {
  const sw = worker(async () => new Response('fresh shell'));
  sw.entries.set('/', new Response('old shell'));
  assert.equal(await (await sw.dispatch('/')).text(), 'fresh shell');
  assert.equal(await sw.entries.get('/').text(), 'fresh shell');
});

test('temporary server failure retains usable cached shell', async () => {
  const sw = worker(async () => new Response('unavailable', { status:503 }));
  sw.entries.set('/', new Response('cached shell'));
  assert.equal(await (await sw.dispatch('/')).text(), 'cached shell');
});
