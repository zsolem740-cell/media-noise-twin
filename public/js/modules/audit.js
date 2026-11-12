// Audit: a szavazatokból futtatott ellenőrző tesztek a telefonon (nincs külső függés).
// 1) időbeli teszt: az első 70% szavazaton választott λ, az utolsó 30%-on mért AUC (a szavazatnál elmentett, tanulás ELŐTTI becslésekkel);
// 2) forrás-kihagyásos teszt: az AI újratanítva, véletlen és forrás szerinti (ismeretlen forrás) felosztással;
// 3) koncentráció: mennyire néhány forrásból jönnek a szavazatok.
import { Learner } from './learner.js';
import { detectLang } from './lang.js';

export const AUDIT_VERSION = 'v47.8';

// Rang-alapú AUC (O(n log n)), egyező pontszámoknál átlagrang.
export function aucRank(scores, labels) {
  const n = scores.length;
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => scores[a] - scores[b]);
  const rank = new Float64Array(n);
  for (let i = 0; i < n;) {
    let j = i;
    while (j + 1 < n && scores[order[j + 1]] === scores[order[i]]) j++;
    const r = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) rank[order[k]] = r;
    i = j + 1;
  }
  let n1 = 0, sum = 0;
  for (let i = 0; i < n; i++) if (labels[i]) { n1++; sum += rank[i]; }
  const n0 = n - n1;
  return n1 && n0 ? (sum - n1 * (n1 + 1) / 2) / (n1 * n0) : NaN;
}

function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

const y = v => (v.vote === 'bait' ? 1 : 0);
const hash = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };

function bootCI(sc1, sc2, labels, B = 200, seed = 11) {
  const n = labels.length, R = rng(seed), d = [], a1 = [];
  for (let b = 0; b < B; b++) {
    const idx = Array.from({ length: n }, () => Math.floor(R() * n));
    const l = idx.map(i => labels[i]);
    const x1 = aucRank(idx.map(i => sc1[i]), l), x2 = aucRank(idx.map(i => sc2[i]), l);
    if (Number.isFinite(x1) && Number.isFinite(x2)) { a1.push(x1); d.push(x1 - x2); }
  }
  const q = (arr, p) => { const s = arr.slice().sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
  return { auc: [q(a1, 0.025), q(a1, 0.975)], diff: [q(d, 0.025), q(d, 0.975)] };
}

// 1) Időbeli teszt
export function timeSplit(votes, frac = 0.7) {
  const v = votes.filter(x => Number.isFinite(x.sRule) && Number.isFinite(x.sAi) && Number.isFinite(x.ts)).sort((a, b) => a.ts - b.ts);
  if (v.length < 100) return { ok: false, n: v.length };
  const cut = Math.floor(v.length * frac), tr = v.slice(0, cut), te = v.slice(cut);
  const ytr = tr.map(y), yte = te.map(y);
  let best = { lam: 0, auc: aucRank(tr.map(x => x.sRule), ytr) };
  for (let k = 1; k <= 9; k++) {
    const l = k / 10, a = aucRank(tr.map(x => (1 - l) * x.sRule + l * x.sAi), ytr);
    if (a > best.auc + 1e-9) best = { lam: l, auc: a };
  }
  const rule = te.map(x => x.sRule), ai = te.map(x => x.sAi), blend = te.map(x => (1 - best.lam) * x.sRule + best.lam * x.sAi);
  const ci = bootCI(blend, rule, yte);
  return { ok: true, nTrain: tr.length, nTest: te.length, testBait: yte.reduce((a, b) => a + b, 0), lam: best.lam,
    rule: aucRank(rule, yte), ai: aucRank(ai, yte), blend: aucRank(blend, yte), ci };
}

// 3) Koncentráció
export function concentration(votes) {
  const m = new Map();
  votes.forEach(v => { const d = v.domain || '?'; const c = m.get(d) || { n: 0, bait: 0 }; c.n++; c.bait += y(v); m.set(d, c); });
  const arr = [...m.entries()].map(([d, c]) => ({ d, n: c.n, rate: c.bait / c.n })).sort((a, b) => b.n - a.n);
  const top5 = arr.slice(0, 5).reduce((a, b) => a + b.n, 0);
  return { domains: arr.length, top: arr.slice(0, 3), top5Share: votes.length ? top5 / votes.length : 0 };
}

// 2) Forrás-kihagyásos teszt (az AI újratanítása foldonként; a UI blokkolását a yieldFn kerüli el)
export async function sourceHoldout(votes, items, K = 5, yieldFn = async () => {}) {
  const v = votes.filter(x => x.title && x.domain).sort((a, b) => (a.ts || 0) - (b.ts || 0));
  if (v.length < 200 || !items || !items.length) return { ok: false, n: v.length };
  const samples = items.map(i => ({ text: i.title, target: i.S0 !== undefined ? i.S0 : i.S }));
  const labels = v.map(y);
  const out = {};
  for (const mode of ['random', 'grouped']) {
    const fold = v.map(x => (mode === 'grouped' ? hash(x.domain) : hash(String(x.id))) % K);
    const scores = new Array(v.length).fill(0.5);
    for (let k = 0; k < K; k++) {
      const L = new Learner();
      L.bootstrap(samples);
      for (let i = 0; i < v.length; i++) if (fold[i] !== k) L.learnVote(v[i].title, labels[i] === 1);
      for (let i = 0; i < v.length; i++) if (fold[i] === k) scores[i] = L.predict(v[i].title);
      await yieldFn();
    }
    out[mode] = aucRank(scores, labels);
  }
  return { ok: true, n: v.length, random: out.random, grouped: out.grouped };
}

// 8) Nyelvi bontás és kísérlet: számít-e a nem magyar szavazat a magyar hírek pontosságához?
const langOf = x => x.lang || detectLang(x.title, x.domain);
export function langSplit(votes) {
  const o = { hu: { n: 0, bait: 0 }, other: { n: 0, bait: 0 }, '?': { n: 0, bait: 0 } };
  votes.forEach(x => { const l = langOf(x); const c = o[l] || o['?']; c.n++; c.bait += y(x); });
  return o;
}
export async function languageExperiment(votes, items, K = 5, yieldFn = async () => {}) {
  const v = votes.filter(x => x.title).sort((a, b) => (a.ts || 0) - (b.ts || 0));
  const isHu = v.map(x => langOf(x) === 'hu');
  const nHu = isHu.filter(Boolean).length, baitHu = v.filter((x, i) => isHu[i] && y(x) === 1).length;
  if (nHu < 300 || baitHu < 30 || !items || !items.length) return { ok: false, nHu, baitHu };
  const samples = items.map(i => ({ text: i.title, target: i.S0 !== undefined ? i.S0 : i.S }));
  const fold = v.map(x => hash(String(x.id)) % K), labels = v.map(y);
  const sA = new Array(v.length).fill(0.5), sB = new Array(v.length).fill(0.5);
  for (let k = 0; k < K; k++) {
    const A = new Learner(), B = new Learner(); A.bootstrap(samples); B.bootstrap(samples);
    for (let i = 0; i < v.length; i++) {
      const test = isHu[i] && fold[i] === k;
      if (test) continue;
      A.learnVote(v[i].title, labels[i] === 1);               // A: az összes többi szavazatból
      if (isHu[i]) B.learnVote(v[i].title, labels[i] === 1);  // B: csak a magyar szavazatokból
    }
    for (let i = 0; i < v.length; i++) if (isHu[i] && fold[i] === k) { sA[i] = A.predict(v[i].title); sB[i] = B.predict(v[i].title); }
    await yieldFn();
  }
  const idx = v.map((_, i) => i).filter(i => isHu[i]), l = idx.map(i => labels[i]);
  const a = aucRank(idx.map(i => sA[i]), l), b = aucRank(idx.map(i => sB[i]), l);
  return { ok: true, nHu, baitHu, all: a, huOnly: b };
}

// 7) Az utolsó szavazatok jelzői: vak / feltárt / jelző nélküli (régi kóddal leadott), és hogy melyik kódverzióval születtek.
export function voteFlags(votes, last = 150) {
  const r = votes.slice().sort((a, b) => (a.ts || 0) - (b.ts || 0)).slice(-last);
  const o = { n: r.length, blind: 0, revealed: 0, none: 0, srcShown: 0, ver: {} };
  r.forEach(x => {
    if (x.blind === true) o.blind++; else if (x.blind === false) o.revealed++; else o.none++;
    if (x.srcShown === true) o.srcShown++;
    const k = x.ver || 'ismeretlen'; o.ver[k] = (o.ver[k] || 0) + 1;
  });
  return o;
}

// 5) Új, vak szavazatok (szám és szín nélkül született szavazatok): a valódi, torzítatlan pontosság.
export function blindVotes(votes, lam = 0.3, pred = x => x.blind === true) {
  const v = votes.filter(x => pred(x) && Number.isFinite(x.sRule) && Number.isFinite(x.sAi));
  const bait = v.filter(x => y(x) === 1).length;
  if (v.length < 30 || bait < 5) return { ok: false, n: v.length, bait };
  const yl = v.map(y), rule = v.map(x => x.sRule), ai = v.map(x => x.sAi), blend = v.map(x => (1 - lam) * x.sRule + lam * x.sAi);
  return { ok: true, n: v.length, bait, rule: aucRank(rule, yl), ai: aucRank(ai, yl), blend: aucRank(blend, yl), ci: bootCI(blend, rule, yl, 200, 17) };
}

// 10) Vak újratanítás: az AI csak a vak szavazatokból, vagy az összes szavazatból tanulva jobb-e a vak szavazatokon (keresztellenőrzés).
export async function blindExperiment(votes, items, K = 5, yieldFn = async () => {}) {
  const v = votes.filter(x => x.title).sort((a, b) => (a.ts || 0) - (b.ts || 0));
  const isB = v.map(x => x.blind === true);
  const nB = isB.filter(Boolean).length, baitB = v.filter((x, i) => isB[i] && y(x) === 1).length;
  if (nB < 150 || baitB < 20 || !items || !items.length) return { ok: false, nB, baitB };
  const samples = items.map(i => ({ text: i.title, target: i.S0 !== undefined ? i.S0 : i.S }));
  const fold = v.map(x => hash(String(x.id)) % K), labels = v.map(y);
  const sA = new Array(v.length).fill(0.5), sB = new Array(v.length).fill(0.5);
  for (let k = 0; k < K; k++) {
    const A = new Learner(), B = new Learner(); A.bootstrap(samples); B.bootstrap(samples);
    for (let i = 0; i < v.length; i++) {
      if (isB[i] && fold[i] === k) continue;
      if (v[i].queue !== 'eval') A.learnVote(v[i].title, labels[i] === 1);   // A: minden többi szavazatból
      if (isB[i] && v[i].queue !== 'eval') B.learnVote(v[i].title, labels[i] === 1);   // B: csak a vak szavazatokból
    }
    for (let i = 0; i < v.length; i++) if (isB[i] && fold[i] === k) { sA[i] = A.predict(v[i].title); sB[i] = B.predict(v[i].title); }
    await yieldFn();
  }
  const idx = v.map((_, i) => i).filter(i => isB[i]), l = idx.map(i => labels[i]);
  return { ok: true, nB, baitB, all: aucRank(idx.map(i => sA[i]), l), blindOnly: aucRank(idx.map(i => sB[i]), l) };
}

// 9) Gyorsszavazó sorok, rejtett ismétlések, „közepes” jelölések.
export function repeatStats(reps) {
  const p = reps.filter(r => (r.first === 'fact' || r.first === 'bait') && (r.second === 'fact' || r.second === 'bait'));
  if (p.length < 10) return { ok: false, n: p.length };
  const a = p.map(r => (r.first === 'bait' ? 1 : 0)), b = p.map(r => (r.second === 'bait' ? 1 : 0)), n = p.length;
  const agree = a.filter((x, i) => x === b[i]).length / n;
  const pa = a.reduce((s, x) => s + x, 0) / n, pb = b.reduce((s, x) => s + x, 0) / n, pe = pa * pb + (1 - pa) * (1 - pb);
  return { ok: true, n, agree, kappa: pe < 1 ? (agree - pe) / (1 - pe) : NaN };
}
export function midStats(votes, mids) {
  const bm = mids.filter(x => x.blind === true);
  if (!bm.length) return { ok: false, n: 0 };
  const q = votes.filter(x => x.blind === true && x.quick === true);
  const mean = a => { const b = a.filter(x => Number.isFinite(x.sAi)); return b.length ? b.reduce((s, x) => s + x.sAi, 0) / b.length : NaN; };
  return { ok: true, n: bm.length, share: bm.length / (bm.length + q.length), fact: mean(q.filter(x => x.vote === 'fact')), mid: mean(bm), bait: mean(q.filter(x => x.vote === 'bait')) };
}

// 6) Kétlépéses címkézés: a cím szerinti és az elolvasás utáni ítélet egyezése.
export function twoStep(votes, lam = 0.3) {
  const p = votes.filter(x => (x.vote2 === 'fact' || x.vote2 === 'bait') && Number.isFinite(x.sRule) && Number.isFinite(x.sAi));
  if (p.length < 20) return { ok: false, n: p.length };
  const a = p.map(y), b = p.map(x => (x.vote2 === 'bait' ? 1 : 0)), n = p.length;
  const agree = a.filter((x, i) => x === b[i]).length / n;
  const pa = a.reduce((s, x) => s + x, 0) / n, pb = b.reduce((s, x) => s + x, 0) / n, pe = pa * pb + (1 - pa) * (1 - pb);
  const blend = p.map(x => (1 - lam) * x.sRule + lam * x.sAi);
  return { ok: true, n, agree, kappa: pe < 1 ? (agree - pe) / (1 - pe) : NaN, aucRead: aucRank(blend, b), aucTitle: aucRank(blend, a),
    titleBait: a.reduce((s, x) => s + x, 0), readBait: b.reduce((s, x) => s + x, 0) };
}

// 4) Küszöb-elemzés: a szavazáskor látott ATM szerint (megjegyzés: a szín szavazás közben látszott, ezért torzíthat).
export function thresholdsReport(votes, th) {
  const v = votes.filter(x => Number.isFinite(x.atm));
  if (v.length < 100 || !th) return { ok: false, n: v.length };
  const tot = v.reduce((a, x) => a + y(x), 0);
  const band = (lo, hi) => { const s = v.filter(x => x.atm >= lo && x.atm < hi); return { n: s.length, rate: s.length ? s.reduce((a, x) => a + y(x), 0) / s.length : NaN }; };
  const at = T => { const s = v.filter(x => x.atm >= T), tp = s.reduce((a, x) => a + y(x), 0); return { n: s.length, prec: s.length ? tp / s.length : NaN, rec: tot ? tp / tot : NaN }; };
  const f1 = a => (a.prec + a.rec > 0 ? 2 * a.prec * a.rec / (a.prec + a.rec) : 0);
  let best = { T: 0, f1: -1 };
  for (const T of [...new Set(v.map(x => Math.round(x.atm / 5) * 5))].sort((a, b) => a - b)) {
    const a = at(T), f = f1(a);
    if (f > best.f1) best = { T, f1: f, prec: a.prec, rec: a.rec };
  }
  return { ok: true, n: v.length, th, bands: [band(0, th.low), band(th.low, th.high), band(th.high, Infinity)], low: at(th.low), high: at(th.high), lowF1: f1(at(th.low)), highF1: f1(at(th.high)), best };
}

const f2 = x => (Number.isFinite(x) ? x.toFixed(2) : '–');
const rg = r => `[${f2(r[0])}–${f2(r[1])}]`;

export function formatAudit(votes, ts, sh, conc, now = Date.now(), thr = { ok: false }, blind = { ok: false }, bv = { ok: false, n: 0 }, two = { ok: false, n: 0 }, vf = null, lg = null, qv = null) {
  const n1 = votes.filter(v => v.vote === 'bait').length;
  const L = [`AUDIT ${AUDIT_VERSION} · ${new Date(now).toISOString().slice(0, 16)}Z`];
  L.push(`szavazat: ${votes.length} (${n1} clickbait / ${votes.length - n1} tény) · ${conc.domains} forrás · az 5 legtöbbet szavazott forrás a szavazatok ${Math.round(conc.top5Share * 100)}%-a (${conc.top.map(t => `${t.d} ${t.n}, clickbait ${Math.round(t.rate * 100)}%`).join('; ')})`);
  if (ts.ok) {
    L.push(`időbeli teszt (első ${ts.nTrain} szavazat → utolsó ${ts.nTest}, ebből ${ts.testBait} clickbait): λ=${ts.lam.toFixed(1)} az első részen választva`);
    L.push(`  szabály ${f2(ts.rule)} · AI ${f2(ts.ai)} · keverék ${f2(ts.blend)} ${rg(ts.ci.auc)} · keverék mínusz szabály: ${rg(ts.ci.diff)}`);
  } else L.push(`időbeli teszt: kevés időbélyeges szavazat (${ts.n})`);
  if (sh.ok) {
    L.push(`forrás-kihagyás (AI újratanítva, 5 csoport): véletlen felosztás ${f2(sh.random)} · ismeretlen forrás ${f2(sh.grouped)} · különbség ${(sh.random - sh.grouped >= 0 ? '+' : '') + f2(sh.random - sh.grouped)}`);
  } else L.push('forrás-kihagyás: kevés szavazat vagy nincs betöltött adat');
  const pc = x => (Number.isFinite(x) ? Math.round(x * 100) + '%' : '–');
  if (thr.ok) {
    L.push(`küszöbök (${thr.n} szavazat, a szavazáskor látott ATM szerint; a szín szavazás közben látszott, ezért torzíthat): clickbait-arány sávonként: <${thr.th.low} ${pc(thr.bands[0].rate)} (${thr.bands[0].n}) · ${thr.th.low}–${thr.th.high} ${pc(thr.bands[1].rate)} (${thr.bands[1].n}) · ≥${thr.th.high} ${pc(thr.bands[2].rate)} (${thr.bands[2].n})`);
    L.push(`  sárga ≥${thr.th.low}: pontosság ${pc(thr.low.prec)}, lefedés ${pc(thr.low.rec)}, F1 ${f2(thr.lowF1)} · piros ≥${thr.th.high}: pontosság ${pc(thr.high.prec)}, lefedés ${pc(thr.high.rec)}, F1 ${f2(thr.highF1)} · F1-optimális küszöb: ${thr.best.T} (F1 ${f2(thr.best.f1)})`);
  }
  if (blind.ok) {
    L.push(`vak újracímkézés (${blind.n} hír, a szám és a forrás rejtve): egyezés a régi címkével ${pc(blind.agree)} · kappa ${f2(blind.kappa)} · a régi clickbaitből ${pc(blind.bait2bait)} maradt az, a régi tényből ${pc(blind.fact2fact)}`);
    L.push(`  AUC a vak címkékkel: szabály ${f2(blind.aucBlind.rule)} · AI ${f2(blind.aucBlind.ai)} · keverék ${f2(blind.aucBlind.blend)} (ugyanezen a mintán a régi címkékkel: ${f2(blind.aucOrig.blend)})`);
  }
  const nBlind = bv.n || 0;
  L.push(bv.ok
    ? `új vak szavazatok (szám és szín nélkül, ${bv.n} db, ${bv.bait} clickbait; cél: 300): szabály ${f2(bv.rule)} · AI ${f2(bv.ai)} · keverék ${f2(bv.blend)} ${rg(bv.ci.auc)} · keverék mínusz szabály ${rg(bv.ci.diff)}`
    : `új vak szavazatok: még kevés (${nBlind} db${bv.bait !== undefined ? `, ${bv.bait} clickbait` : ''}; legalább 30 db és 5 clickbait kell, a cél 300)`);
  if (qv) {
    const e = qv.eval;
    L.push(e.ok
      ? `értékelő sor (véletlen, vak; cél 300 és 40 clickbait): ${e.n} db (${e.bait} clickbait) · szabály ${f2(e.rule)} · AI ${f2(e.ai)} · keverék ${f2(e.blend)} ${rg(e.ci.auc)} · keverék mínusz szabály ${rg(e.ci.diff)}`
      : `értékelő sor (véletlen, vak): még kevés (${e.n} db, ${e.bait !== undefined ? e.bait : 0} clickbait; legalább 30 és 5 kell, a cél 300 és 40)`);
    if (qv.trainN || e.n) L.push(`tanító sor (vak, nem véletlen, a tanuló ezekből tanul): ${qv.trainN} db`);
    if (qv.rep.ok) L.push(`rejtett ismétlés (${qv.rep.n} pár): egyezés ${pc(qv.rep.agree)} · kappa ${f2(qv.rep.kappa)} (a saját következetességed)`);
    else if (qv.rep.n || qv.eval.n) L.push(`rejtett ismétlés: még kevés (${qv.rep.n} pár, legalább 10 kell)`);
    if (qv.mid.ok) L.push(`közepes jelölések: ${qv.mid.n} db (a gyorsszavazások ${pc(qv.mid.share)}-a) · átlagos AI-érték: tény ${f2(qv.mid.fact)} · közepes ${f2(qv.mid.mid)} · clickbait ${f2(qv.mid.bait)}`);
  }
  if (qv && qv.bexp) {
    const b = qv.bexp;
    if (b.ok) L.push(`AI újratanítva, vak szavazatokon mérve (${b.nB} vak szavazat, ${b.baitB} hangos): csak a vak szavazatokból ${f2(b.blindOnly)} · az összes szavazatból ${f2(b.all)} · különbség ${(b.blindOnly - b.all >= 0 ? '+' : '') + f2(b.blindOnly - b.all)}`);
    else L.push(`vak újratanítás: még kevés (${b.nB} vak szavazat, ${b.baitB} hangos; legalább 150 és 20 kell)`);
  }
  if (vf && vf.n) L.push(`az utolsó ${vf.n} szavazat: vak ${vf.blind} · feltárt (a „Miért?” vagy a kapcsoló miatt nem vak) ${vf.revealed} · jelző nélküli (régi kóddal leadva) ${vf.none} · forrás látszott ${vf.srcShown} · kódverzió: ${Object.entries(vf.ver).sort().map(([k, n]) => `${k} ${n}`).join(', ')}`);
  if (two.ok) L.push(`kétlépéses (cím → elolvasás után, ${two.n} pár): egyezés ${pc(two.agree)} · kappa ${f2(two.kappa)} · AUC az elolvasás utáni címkével ${f2(two.aucRead)} (a cím szerintivel: ${f2(two.aucTitle)})`);
  if (lg && lg.split) {
    const s = lg.split, p = c => `${c.n} (${c.bait} clickbait)`;
    L.push(`nyelvi bontás (a szavazat nyelve a címből becsült): magyar ${p(s.hu)} · egyéb nyelvű ${p(s.other)} · bizonytalan ${p(s['?'])}`);
    if (lg.huTime && lg.huTime.ok) L.push(`  csak a magyar szavazatokon, időbeli teszt (${lg.huTime.nTest} teszt-szavazat): szabály ${f2(lg.huTime.rule)} · AI ${f2(lg.huTime.ai)} · keverék ${f2(lg.huTime.blend)} ${rg(lg.huTime.ci.auc)}`);
    if (lg.exp && lg.exp.ok) L.push(`  AI újratanítva, magyar tesztadaton (${lg.exp.nHu} magyar szavazat): csak magyar szavazatokból ${f2(lg.exp.huOnly)} · az összes szavazatból ${f2(lg.exp.all)} · különbség ${(lg.exp.huOnly - lg.exp.all >= 0 ? '+' : '') + f2(lg.exp.huOnly - lg.exp.all)} (a régi címkék torzítottak, csak az összehasonlítás számít)`);
    else if (lg.exp) L.push(`  nyelvi kísérlet: kevés magyar szavazat (${lg.exp.nHu} db, ${lg.exp.baitHu} clickbait; legalább 300 db és 30 clickbait kell)`);
  }
  const flags = [];
  if (lg && lg.exp && lg.exp.ok && lg.exp.huOnly - lg.exp.all > 0.02) flags.push('a nem magyar szavazatok ártanak a magyar híreknél: érdemes kihagyni a tanításból');
  if (lg && lg.exp && lg.exp.ok && lg.exp.all - lg.exp.huOnly > 0.02) flags.push('a nem magyar szavazatok segítenek a magyar híreknél');
  if (sh.ok && sh.random - sh.grouped > 0.05) flags.push('az AI részben a forrást tanulta (ismeretlen forrásnál gyengébb)');
  if (ts.ok && ts.ci.diff[0] <= 0) flags.push('az AI hozzáadott értéke a szabályhoz képest nem bizonyított (a sáv tartalmazza a 0-t)');
  if (qv && qv.bexp && qv.bexp.ok && qv.bexp.blindOnly - qv.bexp.all > 0.02) flags.push('a régi (nem vak) szavazatok ártanak a tanulásnak: érdemes csak a vak szavazatokból tanítani');
  if (qv && qv.eval.ok && qv.eval.n < 300) flags.push(`az értékelő sor még kevés a döntéshez (${qv.eval.n}/300)`);
  if (qv && qv.rep.ok && qv.rep.kappa < 0.6) flags.push('a rejtett ismétlések egyezése mérsékelt (kappa < 0,6): a címke maga is bizonytalan');
  if (bv.ok && bv.n < 300) flags.push(`a vak szavazatok száma még kevés a döntéshez (${bv.n}/300)`);
  if (conc.top5Share > 0.6) flags.push('a szavazatok nagy része kevés forrásból jön');
  if (blind.ok && blind.aucOrig.blend - blind.aucBlind.blend > 0.05) flags.push('a vak címkékkel gyengébb az AUC: a korábbi szavazatokat valószínűleg befolyásolta a látott szám');
  if (blind.ok && blind.kappa < 0.6) flags.push('az ismételt címkézés egyezése mérsékelt (kappa < 0,6): a címke maga is bizonytalan');
  L.push('jelzés: ' + (flags.length ? flags.join('; ') : 'nincs figyelmeztetés'));
  return L.join('\n');
}

export async function runAudit(votes, items, yieldFn, opts = {}) {
  const ts = timeSplit(votes);
  const huVotes = votes.filter(x => langOf(x) === 'hu');
  const conc = concentration(votes);
  const sh = await sourceHoldout(votes, items, 5, yieldFn);
  return formatAudit(votes, ts, sh, conc, Date.now(), thresholdsReport(votes, opts.th), opts.blind || { ok: false }, blindVotes(votes, opts.lam || 0.3), twoStep(votes, opts.lam || 0.3), voteFlags(votes),
    { split: langSplit(votes), huTime: timeSplit(huVotes), exp: await languageExperiment(votes, items, 5, yieldFn) },
    { eval: blindVotes(votes, opts.lam || 0.3, x => x.blind === true && x.queue === 'eval'), trainN: votes.filter(x => x.blind === true && x.queue === 'train').length,
      rep: repeatStats(opts.repeats || []), mid: midStats(votes, opts.mids || []), bexp: await blindExperiment(votes, items, 5, yieldFn) });
}
