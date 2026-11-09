// IndexedDB: offline cache, szavazatok, olvasási idő, AI-állapot.
// Minden művelet időkorlátos: ha az adatbázis zárolt (pl. egy régi lap tartja), az alkalmazás akkor is elindul.
let _db;
function open() {
  if (_db) return _db;
  _db = new Promise((res, rej) => {
    const r = indexedDB.open('mnt-twin', 2);
    r.onupgradeneeded = () => {
      const db = r.result;
      const defs = [['cache', {}], ['votes', { keyPath: 'id' }], ['dwell', { autoIncrement: true }], ['ai', {}]];
      defs.forEach(([n, o]) => { if (!db.objectStoreNames.contains(n)) db.createObjectStore(n, o); });
    };
    r.onblocked = () => {};
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  return _db;
}

async function run(name, mode, fn) {
  const db = await open();
  return new Promise((res, rej) => {
    const t = db.transaction(name, mode);
    const rq = fn(t.objectStore(name));
    t.oncomplete = () => res(rq ? rq.result : undefined);
    t.onerror = () => rej(t.error);
    t.onabort = () => rej(t.error);
  });
}

const TIMEOUT_MS = 2500;
const timeout = (ms, fb) => new Promise(r => setTimeout(() => r(fb), ms));
const safe = async (p, fb) => { try { return await Promise.race([p, timeout(TIMEOUT_MS, fb)]); } catch (_) { return fb; } };

export const store = {
  get: (n, k) => safe(run(n, 'readonly', s => s.get(k)), null),
  getAll: n => safe(run(n, 'readonly', s => s.getAll()), []),
  put: (n, k, v) => safe(run(n, 'readwrite', s => (k === null ? s.put(v) : s.put(v, k)))),
  add: (n, v) => safe(run(n, 'readwrite', s => s.add(v))),
  del: (n, k) => safe(run(n, 'readwrite', s => s.delete(k))),
};
