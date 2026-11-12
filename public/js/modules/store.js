// IndexedDB: offline cache, szavazatok, olvasási idő, AI-állapot.
// Minden művelet időkorlátos: ha az adatbázis zárolt (pl. egy régi lap tartja), az alkalmazás akkor is elindul.
//
// Két adatbázis:
//  - 'mnt-twin' (régi): gyorsítótár, olvasási idő, és a v47.9-ig használt, hírenként egy rekordos szavazattár és AI-állapot. A régi szavazattárat
//    és AI-állapotot az alkalmazás már csak OLVASSA (az áttöltéshez): nem ír bele és nem töröl belőle, így a régi kód visszaállítása után is megvan minden régi adat.
//  - 'mnt-voters' (új): szavazónkénti szavazatok (kulcs: „szavazó|hír”), szavazónkénti AI-állapot, áttöltési napló.
import { recKey } from './voters.js';

function makeDb(name, version, defs) {
  let p;
  const open = () => {
    if (p) return p;
    p = new Promise((res, rej) => {
      const r = indexedDB.open(name, version);
      r.onupgradeneeded = () => {
        const db = r.result;
        defs.forEach(([n, o]) => { if (!db.objectStoreNames.contains(n)) db.createObjectStore(n, o); });
      };
      r.onblocked = () => {};
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    return p;
  };
  return async (store, mode, fn) => {
    const db = await open();
    return new Promise((res, rej) => {
      const t = db.transaction(store, mode);
      const rq = fn(t.objectStore(store));
      t.oncomplete = () => res(rq ? rq.result : undefined);
      t.onerror = () => rej(t.error);
      t.onabort = () => rej(t.error);
    });
  };
}

const run = makeDb('mnt-twin', 2, [['cache', {}], ['votes', { keyPath: 'id' }], ['dwell', { autoIncrement: true }], ['ai', {}]]);
const runV = makeDb('mnt-voters', 1, [['votes', {}], ['ai', {}], ['meta', {}]]);

const TIMEOUT_MS = 2500, STRICT_MS = 15000;
const timeout = (ms, fb) => new Promise(r => setTimeout(() => r(fb), ms));
const safe = async (p, fb) => { try { return await Promise.race([p, timeout(TIMEOUT_MS, fb)]); } catch (_) { return fb; } };
// Szigorú változat az áttöltéshez: hiba vagy időtúllépés esetén kivételt dob (az „üres” és a „nem sikerült olvasni” nem keverhető össze).
const strict = p => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('időtúllépés')), STRICT_MS))]);

export const store = {
  get: (n, k) => safe(run(n, 'readonly', s => s.get(k)), null),
  getAll: n => safe(run(n, 'readonly', s => s.getAll()), []),
  put: (n, k, v) => safe(run(n, 'readwrite', s => (k === null ? s.put(v) : s.put(v, k)))),
  add: (n, v) => safe(run(n, 'readwrite', s => s.add(v))),
  del: (n, k) => safe(run(n, 'readwrite', s => s.delete(k))),
  getStrict: (n, k) => strict(run(n, 'readonly', s => s.get(k))),
  getAllStrict: n => strict(run(n, 'readonly', s => s.getAll())),
};

// Szavazónkénti tároló. A szavazat-rekordban mindig van `voter`; a kulcs ebből és a hír azonosítójából áll.
export const vstore = {
  allVotes: () => safe(runV('votes', 'readonly', s => s.getAll()), []),
  putVote: rec => safe(runV('votes', 'readwrite', s => s.put(rec, recKey(rec.voter, rec.id)))),
  putVotes: recs => safe(runV('votes', 'readwrite', s => { recs.forEach(r => s.put(r, recKey(r.voter, r.id))); })),
  delVote: (voter, id) => safe(runV('votes', 'readwrite', s => s.delete(recKey(voter, id)))),
  getAi: voter => safe(runV('ai', 'readonly', s => s.get(voter)), null),
  putAi: (voter, state) => safe(runV('ai', 'readwrite', s => s.put(state, voter))),
  // az áttöltéshez (szigorú: hiba esetén kivétel)
  keysStrict: () => strict(runV('votes', 'readonly', s => s.getAllKeys())),
  putEntriesStrict: entries => strict(runV('votes', 'readwrite', s => { entries.forEach(e => s.put(e.value, e.key)); })),
  getAiStrict: voter => strict(runV('ai', 'readonly', s => s.get(voter))),
  putAiStrict: (voter, state) => strict(runV('ai', 'readwrite', s => s.put(state, voter))),
  getMetaStrict: k => strict(runV('meta', 'readonly', s => s.get(k))),
  putMetaStrict: (k, v) => strict(runV('meta', 'readwrite', s => s.put(v, k))),
};
