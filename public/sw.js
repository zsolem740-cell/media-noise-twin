const V = 'mnt-v15';
const LIB = 'mnt-lib-three-160';
const SHELL = [
  './', 'index.html', 'css/main.css', 'manifest.json',
  'js/app.js', 'js/modules/model.js', 'js/modules/learner.js', 'js/modules/store.js', 'js/modules/dataLoader.js',
  'js/modules/filterEngine.js', 'js/modules/globe.js', 'js/modules/uiRenderer.js', 'js/modules/share.js', 'js/modules/globe3d.js', 'js/modules/suggest.js', 'js/modules/land.js', 'js/modules/calibration.js', 'js/modules/diag.js', 'js/modules/audit.js', 'js/modules/blind.js',
  'icons/icon-192.png', 'icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== V && k !== LIB).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname === 'cdn.jsdelivr.net' && url.pathname.includes('/npm/three@')) {   // 3D-könyvtár: egyszer letöltve offline is megvan
    e.respondWith(caches.open(LIB).then(async c => {
      const hit = await c.match(req);
      if (hit) return hit;
      const r = await fetch(req);
      if (r.ok) c.put(req, r.clone());
      return r;
    }));
    return;
  }
  if (url.origin !== location.origin) return;
  const key = url.origin + url.pathname;
  if (url.pathname.endsWith('/atm_history.json')) {
    e.respondWith(
      fetch(req).then(r => { if (r.ok) { const cp = r.clone(); caches.open(V).then(c => c.put(key, cp)); } return r; })
        .catch(() => caches.match(key))
    );
    return;
  }
  e.respondWith(
    caches.match(key).then(hit => {
      const net = fetch(req).then(r => { if (r.ok) { const cp = r.clone(); caches.open(V).then(c => c.put(key, cp)); } return r; });
      return hit || net.catch(() => caches.match(new URL('./', location.href).href));
    })
  );
});
