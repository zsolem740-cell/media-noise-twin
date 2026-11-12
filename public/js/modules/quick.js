// Gyorsszavazó mód logikája (csak magyar hírek, vak): értékelő sor (véletlen, soha nem tanít), tanító sor (ahol a szabály és az AI nem ért egyet),
// rejtett ismétlések (az önegyezés folyamatos mérése). A felület és a tárolás az app.js-ben van.
export const TARGET = { eval: 300, bait: 40 };
const hashId = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
export const isShared = id => hashId(String(id)) % 10 === 0;   // a hírek ~10%-a közös: mindkét szavazó megkapja
const REP_KEY = 'mnt-repeats', SKIP_KEY = 'mnt-skip';

export function shuffle(a, rnd = Math.random) {
  const r = a.slice();
  for (let i = r.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [r[i], r[j]] = [r[j], r[i]]; }
  return r;
}

// A még nem szavazott, a szavazó nyelvein íródott hírekből három sor: véletlen (értékelő), a legnagyobb szabály–AI eltérésű 150 (tanító), és a közös hírek (azonosító szerinti, mindkét szavazónál azonos sorrendben).
export function buildPools(rows, ctx, rnd = Math.random) {
  const free = rows.filter(r => r.title && !ctx.voted.has(r.id) && !ctx.skipped.has(r.id) && ctx.langOk(r));
  const train = free.slice().sort((a, b) => Math.abs(b.S - b.sAi) - Math.abs(a.S - a.sAi)).slice(0, 150);
  const shared = free.filter(r => isShared(r.id)).sort((a, b) => hashId(String(a.id)) - hashId(String(b.id)) || String(a.id).localeCompare(String(b.id)));
  return { eval: shuffle(free, rnd), train: shuffle(train, rnd), shared };
}

// Minden harmadik hír a tanító sorból jön, minden ötödik a közös sorból (ha van), a többi az értékelőből; egy hír csak egyszer kerül elő.
// A közös hír értékelő típusú (soha nem tanít), de külön jelölt (shared).
export function takeNext(q) {
  const order = (q.step % 5 === 4) ? ['shared', 'eval', 'train'] : (q.step % 3 === 2) ? ['train', 'eval'] : ['eval', 'train'];
  for (const name of order) {
    const pool = q[name] || [];
    while (pool.length) {
      const it = pool.shift();
      if (!q.used.has(it.id)) { q.used.add(it.id); q.step++; return name === 'shared' ? { it, queue: 'eval', shared: true } : { it, queue: name }; }
    }
  }
  return null;
}

// Rejtett ismétlés: az esetek ~10%-ában egy legalább 48 órája leadott, vak szavazatú hírt kérdez újra (nem derül ki, hogy ismétlés).
export function pickRepeat(votes, repeats, now, rnd = Math.random, p = 0.1, minAgeH = 48) {
  if (rnd() >= p) return null;
  const done = new Set(repeats.map(r => r.id));
  const c = votes.filter(v => v.blind === true && (v.vote === 'fact' || v.vote === 'bait') && v.title && !done.has(v.id)
    && Number.isFinite(v.ts) && now - v.ts >= minAgeH * 3600e3);
  if (!c.length) return null;
  const v = c[Math.floor(rnd() * c.length)];
  return { rep: true, first: v.vote, it: { id: v.id, title: v.title }, queue: 'rep' };
}

export function progress(votes) {
  const e = votes.filter(v => v.blind === true && v.queue === 'eval');
  return { eval: e.length, bait: e.filter(v => v.vote === 'bait').length, train: votes.filter(v => v.blind === true && v.queue === 'train').length };
}

const load = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return v === null ? d : v; } catch (_) { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} };
// A kulcs szavazónkénti (voter megadásával): az ismétlések és a kihagyottak nem keverednek a szavazók között.
const vk = (k, voter) => (voter ? `${k}:${voter}` : k);
export const loadRepeats = voter => load(vk(REP_KEY, voter), []);
export const saveRepeats = (r, voter) => save(vk(REP_KEY, voter), r.slice(-500));
export const loadSkipped = voter => new Set(load(vk(SKIP_KEY, voter), []));
export const saveSkipped = (s, voter) => save(vk(SKIP_KEY, voter), [...s].slice(-2000));
