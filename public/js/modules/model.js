// Tiszta modell – a Python atm_engine tükre (a paramétereket a JSON "model" blokkja adja).
export const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const escRx = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Pontozási mód (a szerver adja a modellben): 'sqrt_int' = round(√(G% · S% · (100 − V%))), 'classic' = G · S · (1 − V).
let SCORING = 'classic';
export const setScoring = m => { SCORING = m === 'sqrt_int' ? 'sqrt_int' : 'classic'; };
export const scoringMode = () => SCORING;
export const half = x => Math.floor(x + 0.5); // .5-nél felfelé, mint a szerver (Python) oldalon
export const atmRef = () => (SCORING === 'sqrt_int' ? 742 : 0.55);
export function atmParts(v, s, g) { return { g: half(g * 100), s: half(s * 100), w: 100 - half(v * 100) }; }
export function atmValue(v, s, g) {
  if (SCORING === 'sqrt_int') { const p = atmParts(v, s, g); return half(Math.sqrt(p.g * p.s * p.w)); }
  return g * s * (1 - v);
}
export const fmtAtm = (x, d = 3) => (SCORING === 'sqrt_int' ? String(half(x)) : x.toFixed(d));

// Az AI minden címre ad egy kis alap-becslést; ezt (a szabály szerint nyugodt hírek mediánját) levonjuk, hogy a gyök ne erősítse fel.
export function aiBaseline(items, preds) {
  const calm = [];
  for (let i = 0; i < items.length; i++) if (!items[i].S) calm.push(preds[i]);
  if (calm.length < 30) return 0;
  calm.sort((a, b) => a - b);
  return calm[calm.length >> 1];
}

// Forrásnév egységesítése (edition.cnn.com → cnn.com), a szerverrel azonos szabály.
let ALIASES = {};
const PREFIX = /^(?:www\d*|m|amp|mobile|edition)\./;
export function canonDomain(d) {
  let x = String(d || '').toLowerCase().trim();
  for (let n = 0; n < 3; n++) {
    if (x.split('.').length >= 3 && PREFIX.test(x)) x = x.replace(PREFIX, '');
    else break;
  }
  return ALIASES[x] || x;
}

export function buildModel(raw) {
  setScoring(raw.scoring);
  ALIASES = raw.domain_aliases || {};
  return Object.assign({}, raw, {
    rx: raw.clickbait.map(k => new RegExp('(?<![\\p{L}\\p{N}_])' + escRx(k), 'u')),
  });
}

export function domainOf(u) {
  try {
    const h = new URL(u).hostname.toLowerCase();
    return canonDomain(h);
  } catch (_) { return ''; }
}

export function tierOf(domain, trust) {
  for (const [name, t] of Object.entries(trust)) {
    if (name === 'default' || typeof t !== 'object') continue;
    for (const d of t.domains) {
      if (domain === d || domain.endsWith('.' + d)) return name;
    }
  }
  return 'default';
}

export function realityIndex(domain, trust) {
  const t = tierOf(domain, trust);
  return t === 'default' ? trust.default : trust[t].value;
}

// Szabály-alapú szenzációszint, a találatokkal együtt (magyarázathoz).
export function ruleParts(text, m) {
  const low = text.toLowerCase();
  const kw = m.clickbait.filter((_, i) => m.rx[i].test(low));
  const ex = (text.match(/!/g) || []).length;
  const words = text.match(/\p{L}{3,}/gu) || [];
  const caps = words.length
    ? words.filter(w => w === w.toUpperCase() && w !== w.toLowerCase()).length / words.length
    : 0;
  const S = clamp(0.5 * Math.min(kw.length / 3, 1) + 0.25 * Math.min(ex / 2, 1) + 0.25 * Math.min(caps / 0.3, 1), 0, 1);
  return { kw, ex, caps, S };
}

export const sensation = (text, m) => ruleParts(text, m).S;
export const level = (a, th) => (a >= th.high ? 'high' : a >= th.low ? 'mid' : 'low');

// Személyes forráskorrekció: Tény +1 / Clickbait −1; olvasás ≥45 s +0,5, <10 s −0,5.
export function buildNetMap(votes, dwell) {
  const net = new Map();
  const add = (d, x) => { if (d) net.set(d, (net.get(d) || 0) + x); };
  votes.forEach(v => add(canonDomain(v.domain), v.vote === 'fact' ? 1 : -1));
  dwell.forEach(d => add(canonDomain(d.domain), d.secs >= 45 ? 0.5 : d.secs < 10 ? -0.5 : 0));
  return net;
}
export const adjustV = (v, net) => clamp(v + clamp(0.03 * net, -0.15, 0.15), 0.05, 0.99);

export function quantile(sorted, q) {
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function relTime(iso) {
  if (!iso) return '';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'most';
  if (s < 3600) return Math.floor(s / 60) + ' perce';
  if (s < 86400) return Math.floor(s / 3600) + ' órája';
  return Math.floor(s / 86400) + ' napja';
}

export const safeHref = u => (/^https?:\/\//i.test(u || '') ? u : '#');
