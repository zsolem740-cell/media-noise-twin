/* Média-Zaj Twin v39 – service worker. Héj: gyorsítótárból (közben frissül); adat/konfig: hálózat először; Three.js: külön, tartós gyorsítótár. */
const V = "mnt-v39", LIB = "mnt-lib-three-160";
const SHELL = ["./", "index.html", "css/hud.css", "js/app.js", "js/modules/webglGlobe.js", "js/modules/filterEngine.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("mnt-") && k !== V && k !== LIB).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const r = e.request; if (r.method !== "GET") return;
  const u = new URL(r.url);
  if (u.hostname.endsWith("jsdelivr.net")) {
    e.respondWith(caches.open(LIB).then((c) => c.match(r).then((hit) => hit || fetch(r).then((res) => { if (res.ok) c.put(r, res.clone()); return res; }))));
  } else if (u.origin === location.origin && (u.pathname.includes("/data/") || u.pathname.includes("/config/"))) {
    e.respondWith(fetch(r).then((res) => { if (res.ok) caches.open(V).then((c) => c.put(r, res.clone())); return res; }).catch(() => caches.match(r)));
  } else if (u.origin === location.origin) {
    e.respondWith(caches.match(r).then((hit) => { const net = fetch(r).then((res) => { if (res.ok) caches.open(V).then((c) => c.put(r, res.clone())); return res; }).catch(() => hit); return hit || net; }));
  }
});
