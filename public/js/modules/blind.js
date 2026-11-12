// Vak újracímkézés: régebbi szavazatok címe számok és forrás nélkül; a válaszok külön (localStorage) tárolódnak, a tanulót és a szavazatokat nem módosítják.
import { aucRank } from './audit.js';
import { detectLangCode } from './lang.js';
const codeOf = v => (v.lang && v.lang !== 'other' && v.lang !== '?' ? v.lang : detectLangCode(v.title, v.domain));

const KEY = 'mnt-blind';
const vk = voter => (voter ? `${KEY}:${voter}` : KEY);   // szavazónkénti kulcs: a vak minta nem keveredik a szavazók között
export function loadBlind(voter) { try { return JSON.parse(localStorage.getItem(vk(voter)) || 'null'); } catch (_) { return null; } }
export function saveBlind(b, voter) { try { localStorage.setItem(vk(voter), JSON.stringify(b)); } catch (_) {} }
export function clearBlind(voter) { try { localStorage.removeItem(vk(voter)); } catch (_) {} }

function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const shuffle = (arr, R) => { const a = arr.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

// Mintavétel: legalább minAgeH órával régebbi szavazatok; a clickbait-jelöltekből túlmintázunk (40%), hogy mindkét osztályból legyen elég.
export function pickSample(votes, n = 100, now = Date.now(), minAgeH = 24, seed = 5, exclude = null, langs = new Set(['hu'])) {
  const R = rng(seed);
  // csak magyar nyelvű címek (a nem magyar nyelvűt a szavazó nem tudja értékelni), és a korábbi mintában szereplők kimaradnak
  const ok = votes.filter(v => v.title && Number.isFinite(v.sRule) && Number.isFinite(v.sAi) && (!Number.isFinite(v.ts) || now - v.ts >= minAgeH * 3600e3)
    && langs.has(codeOf(v)) && !(exclude && exclude.has(v.id)));
  const bait = shuffle(ok.filter(v => v.vote === 'bait'), R), fact = shuffle(ok.filter(v => v.vote !== 'bait'), R);
  const nb = Math.min(bait.length, Math.round(n * 0.4)), nf = Math.min(fact.length, n - nb);
  return shuffle([...bait.slice(0, nb), ...fact.slice(0, nf)], R).map(v => ({ id: v.id, title: v.title, orig: v.vote === 'bait' ? 1 : 0, sRule: v.sRule, sAi: v.sAi }));
}

export const nextItem = b => (b ? b.items.find(i => b.answers[i.id] === undefined) || null : null);
export const answeredCount = b => (b ? b.items.filter(i => b.answers[i.id] === 0 || b.answers[i.id] === 1).length : 0);

// Statisztika: egyezés, Cohen-féle kappa, osztályonkénti egyezés, AUC a vak és a régi címkékkel (a szavazatnál elmentett, tanulás előtti becslésekkel).
export function blindStats(b, lam = 0.3) {
  if (!b) return { ok: false, n: 0 };
  const it = b.items.filter(i => b.answers[i.id] === 0 || b.answers[i.id] === 1);
  if (it.length < 20) return { ok: false, n: it.length };
  const o = it.map(i => i.orig), z = it.map(i => b.answers[i.id]), n = it.length;
  const agree = o.filter((x, k) => x === z[k]).length / n;
  const po1 = o.reduce((a, x) => a + x, 0) / n, pb1 = z.reduce((a, x) => a + x, 0) / n;
  const pe = po1 * pb1 + (1 - po1) * (1 - pb1);
  const kappa = pe < 1 ? (agree - pe) / (1 - pe) : NaN;
  const n1 = o.filter(x => x === 1).length, n0 = n - n1;
  const bait2bait = n1 ? o.filter((x, k) => x === 1 && z[k] === 1).length / n1 : NaN;
  const fact2fact = n0 ? o.filter((x, k) => x === 0 && z[k] === 0).length / n0 : NaN;
  const blend = it.map(i => (1 - lam) * i.sRule + lam * i.sAi);
  const sc = { rule: it.map(i => i.sRule), ai: it.map(i => i.sAi), blend };
  return { ok: true, n, agree, kappa, bait2bait, fact2fact, origBait: n1, blindBait: z.reduce((a, x) => a + x, 0),
    aucBlind: { rule: aucRank(sc.rule, z), ai: aucRank(sc.ai, z), blend: aucRank(sc.blend, z) },
    aucOrig: { rule: aucRank(sc.rule, o), ai: aucRank(sc.ai, o), blend: aucRank(sc.blend, o) } };
}
