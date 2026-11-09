// Javaslat a beállításokhoz a saját szavazatokból: új kulcsszavak, általad zajosnak / megbízhatónak jelölt források,
// és a szenzációszint elválasztó küszöbe. A kimenet kész config/user.json-részlet.
import { tierOf, canonDomain } from './model.js';

const words = t => (t.toLowerCase().match(/\p{L}{4,}/gu) || []);
const median = a => {
  if (!a.length) return 0;
  const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

export const MIN_VOTES = 20, MIN_PER_CLASS = 6;

export function suggest(votes, model, corpus = []) {
  const v = votes.filter(x => x.title && (x.vote === 'bait' || x.vote === 'fact'));
  const nb = v.filter(x => x.vote === 'bait').length, nf = v.length - nb;
  if (v.length < MIN_VOTES || nb < MIN_PER_CLASS || nf < MIN_PER_CLASS) return { ready: false, n: v.length, nb, nf };

  // 1) kulcsszavak: legalább 3 Clickbait-címben szerepel, Tény-címben soha, és a modell még nem fedi
  const cnt = new Map();
  for (const x of v) {
    for (const w of new Set(words(x.title))) {
      const c = cnt.get(w) || { b: 0, f: 0 };
      if (x.vote === 'bait') c.b++; else c.f++;
      cnt.set(w, c);
    }
  }
  const covered = w => model.clickbait.some(k => w.startsWith(k));
  // Közönséges szó (a teljes hírfolyam sok címében szerepel) nem jó kulcsszó: csak a ritka, jellegzetes szavak jöhetnek szóba.
  const df = new Map();
  for (const t of corpus) for (const w of new Set(words(t))) if (cnt.has(w)) df.set(w, (df.get(w) || 0) + 1);
  const common = Math.max(5, Math.floor(0.02 * corpus.length));
  const keywords = [...cnt.entries()]
    .filter(([w, c]) => w.length >= 5 && c.b >= 3 && c.f === 0 && !covered(w) && (df.get(w) || 0) <= common)
    .sort((a, b) => b[1].b - a[1].b || (a[0] < b[0] ? -1 : 1))
    .slice(0, 8)
    .map(([w]) => (w.length > 8 ? w.slice(0, 8) : w)); // a szabály előtag-egyezést használ, így a ragozott alakok is találnak

  // 2) források
  const src = new Map();
  for (const x of v) {
    if (!x.domain) continue;
    const dom = canonDomain(x.domain);
    const c = src.get(dom) || { b: 0, f: 0 };
    if (x.vote === 'bait') c.b++; else c.f++;
    src.set(dom, c);
  }
  const rows = [...src.entries()].map(([domain, c]) => ({ domain, n: c.b + c.f, bait: c.b, fact: c.f }))
    .filter(r => r.n >= 4 && tierOf(r.domain, model.trust) !== 'official');
  const noisy = rows.filter(r => r.bait / r.n >= 0.75).sort((a, b) => b.n - a.n);
  const trusted = rows.filter(r => r.fact / r.n >= 0.75).sort((a, b) => b.n - a.n);

  // 3) elválasztó küszöb a szabály-alapú szenzációszintre (Youden-féle J)
  const sb = v.filter(x => x.vote === 'bait' && Number.isFinite(x.sRule)).map(x => x.sRule);
  const sf = v.filter(x => x.vote === 'fact' && Number.isFinite(x.sRule)).map(x => x.sRule);
  let bestS = null, bestJ = 0;
  if (sb.length && sf.length) {
    for (const t of new Set([...sb, ...sf])) {
      const j = sb.filter(s => s >= t).length / sb.length - sf.filter(s => s >= t).length / sf.length;
      if (j > bestJ) { bestJ = j; bestS = t; }
    }
  }

  const json = {};
  if (keywords.length) json.clickbait_add = keywords;
  const trust = {};
  if (noisy.length) trust.my_noisy = { value: 0.3, label: 'általam zajosnak jelölt', domains_add: noisy.map(r => r.domain) };
  if (trusted.length) trust.my_trusted = { value: 0.8, label: 'általam megbízhatónak jelölt', domains_add: trusted.map(r => r.domain) };
  if (Object.keys(trust).length) json.trust = trust;

  return {
    ready: true, n: v.length, nb, nf, keywords, noisy, trusted,
    medBait: median(sb), medFact: median(sf), bestS, bestJ,
    empty: !Object.keys(json).length,
    text: JSON.stringify(json, null, 2),
  };
}

// A GitHub-oldalak címei az alkalmazás saját címéből (felhasznalo.github.io/repo/).
export function githubLinks(loc) {
  const m = /^([^.]+)\.github\.io$/i.exec(loc.hostname || '');
  const repo = (loc.pathname || '').split('/').filter(Boolean)[0];
  if (!m || !repo) return null;
  const base = `https://github.com/${m[1]}/${repo}`;
  return { newUrl: `${base}/new/main?filename=config/user.json`, editUrl: `${base}/edit/main/config/user.json` };
}
