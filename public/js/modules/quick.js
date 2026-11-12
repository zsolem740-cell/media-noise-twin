// Gyorsszavazó mód logikája (csak magyar hírek, vak): értékelő sor (véletlen, soha nem tanít), tanító sor (ahol a szabály és az AI nem ért egyet),
// rejtett ismétlések (az önegyezés folyamatos mérése). A felület és a tárolás az app.js-ben van.
export const TARGET = { eval: 300, bait: 40 };
const REP_KEY = 'mnt-repeats', SKIP_KEY = 'mnt-skip';

export function shuffle(a, rnd = Math.random) {
  const r = a.slice();
  for (let i = r.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [r[i], r[j]] = [r[j], r[i]]; }
  return r;
}

// A még nem szavazott, magyar nyelvű hírekből két sor: véletlen (értékelő) és a legnagyobb szabály–AI eltérésű 150 (tanító).
export function buildPools(rows, ctx, rnd = Math.random) {
  const free = rows.filter(r => r.title && !ctx.voted.has(r.id) && !ctx.skipped.has(r.id) && ctx.langOf(r) === 'hu');
  const train = free.slice().sort((a, b) => Math.abs(b.S - b.sAi) - Math.abs(a.S - a.sAi)).slice(0, 150);
  return { eval: shuffle(free, rnd), train: shuffle(train, rnd) };
}

// Minden harmadik hír a tanító sorból jön, a többi az értékelőből; egy hír csak egyszer kerül elő.
export function takeNext(q) {
  const order = (q.step % 3 === 2) ? ['train', 'eval'] : ['eval', 'train'];
  for (const name of order) {
    while (q[name].length) {
      const it = q[name].shift();
      if (!q.used.has(it.id)) { q.used.add(it.id); q.step++; return { it, queue: name }; }
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
export const loadRepeats = () => load(REP_KEY, []);
export const saveRepeats = r => save(REP_KEY, r.slice(-500));
export const loadSkipped = () => new Set(load(SKIP_KEY, []));
export const saveSkipped = s => save(SKIP_KEY, [...s].slice(-2000));
