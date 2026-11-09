// Öntanuló szenzáció-modell: hash-elt szó/bigram jellemzők + online logisztikus regresszió.
// Kulcs és szerver nélkül, a telefonon tanul; az állapot IndexedDB-ben marad.
import { clamp } from './model.js';

export const DIM = 1 << 16;
const L2 = 0.0005;

function fnv(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return (h >>> 0) % DIM;
}

export function features(text) {
  const words = text.toLowerCase().match(/\p{L}{3,}/gu) || [];
  const seen = new Map();
  const add = n => { if (!seen.has(n)) seen.set(n, fnv(n)); };
  words.forEach(w => add('w:' + w));
  for (let i = 0; i < words.length - 1; i++) add('b:' + words[i] + ' ' + words[i + 1]);
  const ex = (text.match(/!/g) || []).length;
  if (ex) add('x:felkiáltójel' + Math.min(ex, 3));
  const caps = (text.match(/\p{L}{3,}/gu) || []).filter(w => w === w.toUpperCase() && w !== w.toLowerCase()).length;
  if (caps) add('x:NAGYBETŰ' + Math.min(caps, 3));
  if (text.includes('?')) add('x:kérdőjel');
  return [...seen.entries()]; // [név, index]
}

export const lambdaFor = votes => clamp(0.2 + 0.5 * Math.min(votes / 60, 1), 0, 0.7);

export class Learner {
  constructor(state) {
    this.w = state && state.w ? new Float32Array(state.w) : new Float32Array(DIM);
    this.b = state && state.b !== undefined ? state.b : -1.5;
    this.steps = (state && state.steps) || 0;
    this.boot = !!(state && state.boot);
    this.votesSeen = (state && state.votesSeen) || 0;
  }

  exportState() {
    return { w: this.w, b: this.b, steps: this.steps, boot: this.boot, votesSeen: this.votesSeen };
  }

  _p(feat) {
    let z = this.b;
    for (const [, i] of feat) z += this.w[i];
    return 1 / (1 + Math.exp(-z));
  }

  predict(text) { return this._p(features(text)); }

  _step(feat, target, lr) {
    const g = (target - this._p(feat)) * lr;
    for (const [, i] of feat) this.w[i] += g - lr * L2 * this.w[i];
    this.b += g * 0.5;
    this.steps++;
  }

  // 1) Tanító-tanár: a szabály-alapú S a gyenge címke; így a modell általánosít a kulcsszólistán túl.
  bootstrap(samples, epochs = 3) {
    const prepared = samples.map(s => ({ f: features(s.text), t: clamp(s.target, 0, 1) }));
    for (let e = 0; e < epochs; e++) {
      for (let i = 0; i < prepared.length; i++) {
        const k = (i * 7919 + e * 104729) % prepared.length; // determinisztikus keverés
        this._step(prepared[k].f, prepared[k].t, 0.12);
      }
    }
    this.boot = true;
  }

  // 2) Emberi visszajelzés: erős tanulási lépés.
  learnVote(text, bait) {
    const f = features(text);
    for (let r = 0; r < 3; r++) this._step(f, bait ? 1 : 0, 0.25);
    this.votesSeen++;
  }

  // 3) Olvasási idő: gyenge jel.
  learnWeak(text, target) { this._step(features(text), target, 0.03); }

  explain(text, n = 3) {
    return features(text)
      .map(([name, i]) => ({ name, w: this.w[i] }))
      .filter(x => x.w > 0.25)
      .sort((a, b) => b.w - a.w)
      .slice(0, n)
      .map(x => x.name.replace(/^[wbx]:/, ''));
  }

  // Mit tanult: a korpusz leggyakoribb szavai közül a legnagyobb / legkisebb súlyúak.
  topWords(texts, n = 8) {
    const cnt = new Map();
    for (const t of texts) {
      for (const [name, i] of features(t)) {
        if (!name.startsWith('w:')) continue;
        const c = cnt.get(name);
        if (c) c.n++; else cnt.set(name, { i, n: 1 });
      }
    }
    const arr = [...cnt.entries()].filter(([, v]) => v.n >= 2).map(([k, v]) => ({ word: k.slice(2), w: this.w[v.i], n: v.n }));
    arr.sort((a, b) => b.w - a.w);
    return { pos: arr.slice(0, n).filter(x => x.w > 0.05), neg: arr.slice(-n).reverse().filter(x => x.w < -0.05) };
  }
}
