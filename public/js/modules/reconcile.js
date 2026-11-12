// Egyeztetés két szavazó között: a közös hírekre az egyezés és a kappa (összesen és nyelvenként), és a szabály AUC-ja a másik szavazó címkéivel.
// Nem ír át semmit: csak olvas és kiír.
import { aucRank } from './audit.js';
import { detectLangCode } from './lang.js';

const ok2 = v => v && (v.vote === 'fact' || v.vote === 'bait');
const codeOf = v => (v.lang && v.lang !== 'other' && v.lang !== '?' ? v.lang : detectLangCode(v.title, v.domain));
const NAMES = { hu: 'magyar', en: 'angol', de: 'német', sl: 'szlovén', hr: 'horvát', sk: 'szlovák', other: 'egyéb', '?': 'bizonytalan' };

function kappaOf(pairs) {
  const n = pairs.length;
  if (!n) return { n: 0, agree: NaN, kappa: NaN, bait: [0, 0] };
  const a = pairs.map(p => (p.a.vote === 'bait' ? 1 : 0)), b = pairs.map(p => (p.b.vote === 'bait' ? 1 : 0));
  const agree = a.filter((x, i) => x === b[i]).length / n;
  const pa = a.reduce((s, x) => s + x, 0) / n, pb = b.reduce((s, x) => s + x, 0) / n, pe = pa * pb + (1 - pa) * (1 - pb);
  return { n, agree, kappa: pe < 1 ? (agree - pe) / (1 - pe) : NaN, bait: [a.reduce((s, x) => s + x, 0), b.reduce((s, x) => s + x, 0)] };
}

export function reconcile(mine, theirs, lam = 0.3) {
  const mm = new Map(mine.filter(ok2).map(v => [v.id, v]));
  const th = theirs.filter(ok2);
  const pairs = th.filter(v => mm.has(v.id)).map(v => ({ a: mm.get(v.id), b: v }));
  const byLang = {};
  pairs.forEach(p => { (byLang[codeOf(p.b)] ||= []).push(p); });
  const langRes = {}; Object.entries(byLang).forEach(([k, arr]) => { langRes[k] = kappaOf(arr); });
  // a másik szavazó vak szavazatai: a szabály és az AI pontossága az ő címkéivel, nyelvenként (a szavazatnál elmentett, tanulás előtti becslésekkel)
  const auc = {};
  const groups = {}; th.filter(v => v.blind === true && Number.isFinite(v.sRule) && Number.isFinite(v.sAi)).forEach(v => { (groups[codeOf(v)] ||= []).push(v); });
  Object.entries(groups).forEach(([k, arr]) => {
    const y = arr.map(v => (v.vote === 'bait' ? 1 : 0)), bait = y.reduce((s, x) => s + x, 0);
    auc[k] = { n: arr.length, bait, rule: bait >= 5 && arr.length - bait >= 5 ? aucRank(arr.map(v => v.sRule), y) : NaN,
      blend: bait >= 5 && arr.length - bait >= 5 ? aucRank(arr.map(v => (1 - lam) * v.sRule + lam * v.sAi), y) : NaN };
  });
  const dis = pairs.filter(p => p.a.vote !== p.b.vote).slice(0, 8).map(p => ({ title: p.a.title, mine: p.a.vote, theirs: p.b.vote }));
  return { nMine: mm.size, nTheirs: th.length, overlap: kappaOf(pairs), byLang: langRes, auc, disagreements: dis };
}

const f2 = x => (Number.isFinite(x) ? x.toFixed(2) : '–');
const pc = x => (Number.isFinite(x) ? Math.round(x * 100) + '%' : '–');
export function formatRecon(r, mineName = 'A', theirName = 'B') {
  const L = [`EGYEZTETÉS · ${mineName} (${r.nMine} szavazat) ↔ ${theirName} (${r.nTheirs} szavazat)`];
  const o = r.overlap;
  L.push(o.n >= 10 ? `közös hír: ${o.n} · egyezés ${pc(o.agree)} · kappa ${f2(o.kappa)} (hangos: ${mineName} ${o.bait[0]}, ${theirName} ${o.bait[1]})` : `közös hír: csak ${o.n} (legalább 10 kell az egyezés méréséhez; közös nyelv és a közös sor kell hozzá)`);
  Object.entries(r.byLang).filter(([, v]) => v.n >= 5).forEach(([k, v]) => L.push(`  ${NAMES[k] || k}: ${v.n} közös hír · egyezés ${pc(v.agree)} · kappa ${f2(v.kappa)}`));
  Object.entries(r.auc).forEach(([k, v]) => L.push(`${theirName} vak szavazatai, ${NAMES[k] || k}: ${v.n} db (${v.bait} hangos) · szabály AUC ${f2(v.rule)} · keverék AUC ${f2(v.blend)}${Number.isFinite(v.rule) ? '' : ' (még kevés)'}`));
  if (r.disagreements.length) { L.push('eltérések (a szabály pontosításához):'); r.disagreements.forEach(d => L.push(`  ${mineName}: ${d.mine === 'bait' ? 'hangos' : 'nyugodt'} · ${theirName}: ${d.theirs === 'bait' ? 'hangos' : 'nyugodt'} · ${String(d.title).slice(0, 70)}`)); }
  if (o.n >= 10 && o.kappa < 0.6) L.push('jelzés: a két szavazó egyezése mérsékelt (kappa < 0,6): a szabály vagy a címkék pontosításra szorulnak');
  return L.join('\n');
}

// ---- Több szavazó: páronkénti egyezés, nyelvenkénti átlag, konszenzus-címkék és a szabály AUC-ja a konszenzussal ----
export function splitBackupTexts(text) {
  const t = String(text || '').trim();
  if (!t) return [];
  try { JSON.parse(t); return [t]; } catch (_) {}
  return t.split(/\n/).map(x => x.trim()).filter(x => x.startsWith('{') || x.startsWith('['));   // a mentés egysoros: több mentés = több sor
}

export function reconcileMany(sets, lam = 0.3) {
  const seen = new Map();
  const S = sets.map(s => {
    const base = s.voter || '?'; const n = (seen.get(base) || 0) + 1; seen.set(base, n);
    return { voter: n > 1 ? `${base}#${n}` : base, dupe: n > 1, votes: s.votes.filter(ok2) };
  });
  const maps = S.map(s => new Map(s.votes.map(v => [v.id, v])));
  const pairs = [];
  for (let i = 0; i < S.length; i++) for (let j = i + 1; j < S.length; j++) {
    const ps = S[j].votes.filter(v => maps[i].has(v.id)).map(v => ({ a: maps[i].get(v.id), b: v }));
    const byLang = {}; ps.forEach(p => { (byLang[codeOf(p.a)] ||= []).push(p); });
    pairs.push({ a: S[i].voter, b: S[j].voter, all: kappaOf(ps), byLang: Object.fromEntries(Object.entries(byLang).map(([k, arr]) => [k, kappaOf(arr)])) });
  }
  // nyelvenkénti átlagos kappa a legalább 10 közös hírű párokból
  const langK = {};
  pairs.forEach(p => Object.entries(p.byLang).forEach(([k, v]) => { if (v.n >= 10 && Number.isFinite(v.kappa)) (langK[k] ||= []).push(v); }));
  const langAvg = Object.fromEntries(Object.entries(langK).map(([k, a]) => [k, { pairs: a.length, n: a.reduce((s, x) => s + x.n, 0), kappa: a.reduce((s, x) => s + x.kappa, 0) / a.length, agree: a.reduce((s, x) => s + x.agree, 0) / a.length }]));
  // konszenzus: a legalább 2 szavazó által értékelt hírek többségi címkéje (döntetlennél kimarad)
  const items = new Map();
  S.forEach(s => s.votes.forEach(v => { (items.get(v.id) || items.set(v.id, []).get(v.id)).push({ voter: s.voter, v }); }));
  const consensus = [], disagree = [];
  items.forEach(r => {
    if (r.length < 2) return;
    const bait = r.filter(x => x.v.vote === 'bait').length, fact = r.length - bait;
    if (bait !== fact) consensus.push({ rec: r[0].v, label: bait > fact ? 1 : 0, raters: r.length, agree: Math.max(bait, fact) / r.length });
    if (bait && fact) disagree.push(r);
  });
  const gold = {};
  consensus.forEach(c => { (gold[codeOf(c.rec)] ||= []).push(c); });
  const ruleAuc = Object.fromEntries(Object.entries(gold).map(([k, arr]) => {
    const y = arr.map(c => c.label), bait = y.reduce((s, x) => s + x, 0), ok = Number.isFinite(arr[0].rec.sRule) && bait >= 5 && arr.length - bait >= 5;
    return [k, { n: arr.length, bait, rule: ok ? aucRank(arr.map(c => c.rec.sRule), y) : NaN }];
  }));
  // szavazónként: az egyezés a többiekkel (átlagos páros egyezés)
  const perVoter = S.map(s => {
    const rel = pairs.filter(p => (p.a === s.voter || p.b === s.voter) && p.all.n >= 10);
    return { voter: s.voter, n: s.votes.length, dupe: s.dupe, avgKappa: rel.length ? rel.reduce((x, p) => x + p.all.kappa, 0) / rel.length : NaN, partners: rel.length };
  });
  return { voters: S.map(s => ({ voter: s.voter, n: s.votes.length, dupe: s.dupe })), pairs, langAvg, consensus: { n: consensus.length, agree: consensus.length ? consensus.reduce((s, c) => s + c.agree, 0) / consensus.length : NaN }, ruleAuc, perVoter,
    disagreements: disagree.slice(0, 8).map(r => ({ title: r[0].v.title, votes: r.map(x => `${x.voter}: ${x.v.vote === 'bait' ? 'hangos' : 'nyugodt'}`) })) };
}

export function formatReconMany(r) {
  const L = [`EGYEZTETÉS · szavazók: ${r.voters.map(v => `${v.voter} (${v.n})`).join(', ')}`];
  if (r.voters.some(v => v.dupe)) L.push('FIGYELEM: két szavazó ugyanazt az azonosítót használja (#2 jelöli); mindenki más betűt válasszon az Öntanuló AI panelen.');
  if (r.voters.length < 2) L.push('legalább két szavazó mentése kell (a mentéseket külön sorba illeszd).');
  r.pairs.forEach(p => L.push(p.all.n >= 10 ? `${p.a}–${p.b}: közös hír ${p.all.n} · egyezés ${pc(p.all.agree)} · kappa ${f2(p.all.kappa)}` : `${p.a}–${p.b}: közös hír csak ${p.all.n} (legalább 10 kell; közös nyelv és közös sor kell hozzá)`));
  Object.entries(r.langAvg).forEach(([k, v]) => L.push(`  ${NAMES[k] || k}: átlagos egyezés ${pc(v.agree)} · kappa ${f2(v.kappa)} (${v.pairs} pár, ${v.n} közös hír)`));
  if (r.consensus.n) L.push(`konszenzus-címke: ${r.consensus.n} hír (átlagos egyetértés a többségi címkével ${pc(r.consensus.agree)})`);
  Object.entries(r.ruleAuc).forEach(([k, v]) => L.push(`  a szabály a konszenzussal, ${NAMES[k] || k}: ${v.n} hír (${v.bait} hangos) · AUC ${f2(v.rule)}${Number.isFinite(v.rule) ? '' : ' (még kevés)'}`));
  const out = r.perVoter.filter(v => Number.isFinite(v.avgKappa)); const mean = out.length ? out.reduce((s, v) => s + v.avgKappa, 0) / out.length : NaN;
  out.forEach(v => { if (out.length >= 3 && v.avgKappa < mean - 0.2) L.push(`jelzés: ${v.voter} egyezése a többiekkel alacsony (kappa ${f2(v.avgKappa)} a ${f2(mean)} átlaghoz képest): érdemes átbeszélni a szabályt`); });
  if (r.disagreements.length) { L.push('eltérések (a szabály pontosításához):'); r.disagreements.forEach(d => L.push(`  ${d.votes.join(' · ')} · ${String(d.title).slice(0, 60)}`)); }
  const lowest = r.pairs.filter(p => p.all.n >= 10).some(p => p.all.kappa < 0.6);
  if (lowest) L.push('jelzés: legalább egy szavazópár egyezése mérsékelt (kappa < 0,6): a szabály vagy a címkék pontosításra szorulnak');
  return L.join('\n');
}
