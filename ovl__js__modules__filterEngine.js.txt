/* Média-Zaj Twin v40 – kliensoldali öntanuló szűrő.
   Logisztikus regresszió 65 536 dimenziós hash-elt jellemzőtéren (előjeles hash-elés), AdaGrad + L2 tanulással.
   Tanítójel: szavazat (👍 érték / 👎 zaj). Az olvasási idő 2026-11-05-től nem tanít (előre rögzített szabály: az olvasási idő pozitívjai a 👎 hírek alatt pontoztak, AUC 0,32; a címkézéshez nyitott részletek szennyezték a jelet). Az AUC-alapú λ-keverés a tanult p valószínűséget
   és az előzetes (1 − ATM/plafon) tisztaság-pontot keveri: λ csak annyit kap, amennyire a modell a saját
   korábbi szavazataidat előre tudta jelezni. Minden a telefonodon marad (localStorage). */
export const DIM = 65536;
const MASK = DIM - 1;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

export function fold(s) {
  return String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/ß/g, "ss");
}
export function fnv1a(str, seed = 2166136261) {
  let h = seed >>> 0;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h >>> 0;
}
const STOP = new Set(["the", "and", "for", "with", "that", "this", "from", "have", "has", "will", "was", "were", "are", "not", "but", "der", "die", "das", "und", "nicht", "ist", "mit", "von", "egy", "hogy", "nem", "van", "volt", "meg", "mar", "mint", "csak", "vagy"]);

/* Jellemzők: szavak, szópárok, forrás, hatókör, téma, hely, ATM-sáv, igazolás. Visszatér: Map(index → érték), L2-normált. */
export function featuresOf(a) {
  const f = new Map();
  const add = (key, val) => {
    const idx = fnv1a(key) & MASK;
    const sign = (fnv1a(key, 0x9e3779b9) & 1) ? 1 : -1;
    f.set(idx, (f.get(idx) || 0) + sign * val);
  };
  const words = (txt) => fold(txt).match(/[a-z0-9]{3,}/g)?.filter((w) => !STOP.has(w) && !/^\d+$/.test(w)) || [];
  const tw = words(a.title), sw = words(a.summary || "").slice(0, 40);
  tw.forEach((w) => add("w:" + w, 1));
  sw.forEach((w) => add("w:" + w, 0.4));
  for (let i = 0; i < tw.length - 1; i++) add("b:" + tw[i] + "_" + tw[i + 1], 0.7);
  add("src:" + fold(a.source), 1.2);
  add("sc:" + a.scope, 0.6);
  (a.topics || []).forEach((t) => add("tp:" + t, 0.8));
  if (a.geo && a.geo.name) add("pl:" + fold(a.geo.name), 0.8);
  const b = clamp(Math.floor((a.atm || 0) / 0.06), 0, 5);
  add("atm:" + b, 0.5);
  add("sv:" + Math.round((a.s || 0) * 4) + "_" + Math.round((a.v || 0) * 4), 0.4);
  if (a.truth && a.truth.verdict) add("tr:" + a.truth.verdict, 0.6);
  if (a.event_sources > 1) add("multi", 0.4);
  let n2 = 0;
  f.forEach((v) => { n2 += v * v; });
  const k = n2 > 0 ? 1 / Math.sqrt(n2) : 1;
  f.forEach((v, i) => f.set(i, v * k));
  return f;
}

/* AUC (Mann–Whitney), egyenlő értékeknél átlagrang. Ha hiányzik pozitív vagy negatív minta: null. */
export function computeAUC(preds, labels) {
  const n = preds.length;
  const idx = [...Array(n).keys()].sort((i, j) => preds[i] - preds[j]);
  const rank = new Array(n);
  for (let i = 0; i < n;) {
    let j = i;
    while (j + 1 < n && preds[idx[j + 1]] === preds[idx[i]]) j++;
    const r = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) rank[idx[k]] = r;
    i = j + 1;
  }
  let pos = 0, sumPos = 0;
  for (let i = 0; i < n; i++) if (labels[i] >= 0.5) { pos++; sumPos += rank[i]; }
  const neg = n - pos;
  if (!pos || !neg) return null;
  return (sumPos - pos * (pos + 1) / 2) / (pos * neg);
}

const memStore = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };

export class FilterEngine {
  constructor({ storage, key = "mnt.filter.v38", lr = 0.35, l2 = 1e-4, atmCap = 0.3, dwell = false } = {}) {
    this.storage = storage || (typeof localStorage !== "undefined" ? localStorage : memStore());
    this.key = key; this.lr = lr; this.l2 = l2; this.atmCap = atmCap; this.dwellOn = !!dwell;
    this.reset(false);
    this.load();
  }
  reset(persist = true) {
    this.w = new Float32Array(DIM); this.g = new Float32Array(DIM);
    this.bias = 0; this.gb = 0; this.hist = []; this.trained = 0;
    if (persist) { try { this.storage.removeItem(this.key); } catch (e) { /* nincs tár */ } }
  }
  rawP(feats) {
    let z = this.bias;
    feats.forEach((v, i) => { z += this.w[i] * v; });
    return 1 / (1 + Math.exp(-clamp(z, -30, 30)));
  }
  predict(a) { return this.rawP(featuresOf(a)); }
  prior(a) { return 1 - clamp((a.atm || 0) / this.atmCap, 0, 1); }
  auc() {
    if (this.hist.length < 10) return null;
    return computeAUC(this.hist.map((h) => h.p), this.hist.map((h) => h.y));
  }
  /* Csak az explicit szavazatokra (👍/👎): az olvasási idő implicit pozitívjai nélkül. Mérés, nem befolyásolja a λ-t. Legalább 10 szavazat és mindkét osztály kell. */
  aucVotes() {
    const v = this.hist.filter((h) => h.kind === "vote");
    if (v.length < 10) return null;
    return computeAUC(v.map((h) => h.p), v.map((h) => h.y));
  }
  /* λ ∈ [0, 0.9]: 0, amíg nincs legalább 5 értékes és 5 zajnak jelölt minta; utána az AUC-ból: (AUC−0.5)/0.4, a minták számával arányos bizalommal */
  lambda() {
    const pos = this.hist.filter((h) => h.y >= 0.5).length, neg = this.hist.length - pos;
    if (pos < 5 || neg < 5) return 0;
    const auc = this.auc();
    if (auc === null) return 0;
    return clamp((auc - 0.5) / 0.4, 0, 1) * 0.9 * Math.min(1, this.hist.length / 60);
  }
  score(a) {
    const p = this.predict(a), prior = this.prior(a), lambda = this.lambda();
    return { score: lambda * p + (1 - lambda) * prior, p, prior, lambda };
  }
  /* label: 1 = értékes/tény, 0 = zaj; weight: a jel erőssége. A jóslat a tanítás ELŐTT kerül az AUC-előzménybe. */
  train(a, label, weight = 1, kind = "vote") {
    const feats = featuresOf(a), p = this.rawP(feats);
    this.hist.push({ p: +p.toFixed(5), y: label, w: weight, kind, id: a.id, pr: +this.prior(a).toFixed(4), t: Date.now() });   // az azonosító, az előzetes pont és az idő az utólagos elemzéshez kell
    if (this.hist.length > 300) this.hist.shift();
    const err = (p - label) * weight;
    feats.forEach((v, i) => {
      const gr = err * v + this.l2 * this.w[i];
      this.g[i] += gr * gr;
      this.w[i] -= this.lr * gr / Math.sqrt(this.g[i] + 1e-3);
    });
    this.gb += err * err;
    this.bias -= this.lr * 0.5 * err / Math.sqrt(this.gb + 1e-3);
    this.trained++;
    this.save();
    return p;
  }
  /* Olvasási idő: alapból KIKAPCSOLVA (dwellOn = false), nem tanít és nem kerül a naplóba. Bekapcsolva: ≥ 8 mp = gyenge pozitív (legfeljebb 0.6 súly); megnyitott, de ≤ 1.5 mp alatt bezárt = gyenge negatív; közte nincs jel. */
  trainDwell(a, seconds, opened = false) {
    if (!this.dwellOn) return null;
    if (seconds >= 8) return this.train(a, 1, Math.min(0.6, seconds / 40), "dwell");
    if (opened && seconds <= 1.5) return this.train(a, 0, 0.25, "dwell");
    return null;
  }
  /* A teljes AUC-előzmény CSV-ben (elemzéshez): sorszám, idő, hír-azonosító, a tanítás ELŐTTI jóslat, az előzetes (1 − ATM/plafon) pont, címke, súly, fajta. */
  exportCsv() {
    const q = (x) => (x === undefined || x === null ? "" : String(x));
    return ["n,ido,id,p,prior,y,suly,fajta", ...this.hist.map((h, i) => [i + 1, h.t ? new Date(h.t).toISOString() : "", q(h.id), q(h.p), q(h.pr), q(h.y), q(h.w), q(h.kind)].join(","))].join("\n");
  }
  stats() { return { lambda: this.lambda(), auc: this.auc(), aucVote: this.aucVotes(), nVote: this.hist.filter((h) => h.kind === "vote").length, samples: this.hist.length, trained: this.trained }; }
  save() {
    try {
      const nz = [];
      for (let i = 0; i < DIM; i++) if (this.w[i] !== 0 || this.g[i] !== 0) nz.push([i, +this.w[i].toFixed(5), +this.g[i].toFixed(5)]);
      if (nz.length > 20000) nz.sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).length = 20000;
      this.storage.setItem(this.key, JSON.stringify({ v: 1, b: this.bias, gb: this.gb, n: this.trained, h: this.hist.slice(-300), nz }));
    } catch (e) { /* megtelt a tár: a tanulás a munkamenetben marad */ }
  }
  load() {
    try {
      const o = JSON.parse(this.storage.getItem(this.key) || "null");
      if (!o || o.v !== 1) return;
      this.bias = o.b || 0; this.gb = o.gb || 0; this.trained = o.n || 0; this.hist = Array.isArray(o.h) ? o.h : [];
      for (const [i, w, g] of o.nz || []) { if (i >= 0 && i < DIM) { this.w[i] = w; this.g[i] = g; } }
    } catch (e) { /* sérült tár: üres modell */ }
  }
}
