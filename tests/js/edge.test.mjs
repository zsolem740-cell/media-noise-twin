// Szélső esetek: hiányzó adat, közös hírek hiánya, a „közepes” címke kezelése, hiányos rekordok egyesítése.
import test from 'node:test';
import assert from 'node:assert/strict';
import { reconcile, reconcileMany, formatRecon, formatReconMany } from '../../public/js/modules/reconcile.js';
import { blindVotes, timeSplit, twoStep, repeatStats, midStats, langSplit, concentration, voteFlags } from '../../public/js/modules/audit.js';
import { calibrate } from '../../public/js/modules/calibration.js';
import { blindStats, pickSample, nextItem, answeredCount } from '../../public/js/modules/blind.js';
import { planRestore, parseBackup, buildBackup, serialize } from '../../public/js/modules/backup.js';
import { progress, pickRepeat, buildPools } from '../../public/js/modules/quick.js';
import { vote, A10, B10, KAPPA10, near, T0 } from './helpers.mjs';

const mid = (id, extra = {}) => ({ ...vote(id, 0), vote: 'mid', ...extra });
const strip = (v, ...keys) => { const o = { ...v }; keys.forEach(k => delete o[k]); return o; };

// ---- közös hírek hiánya ----

test('nincs közös hír: két szavazó', () => {
  const mine = A10.map((b, i) => vote(i, b)), theirs = B10.map((b, i) => vote(100 + i, b));
  const r = reconcile(mine, theirs);
  assert.equal(r.overlap.n, 0);
  assert.ok(Number.isNaN(r.overlap.kappa) && Number.isNaN(r.overlap.agree));
  assert.deepEqual(r.byLang, {});
  assert.deepEqual(r.disagreements, []);
  const text = formatRecon(r);
  assert.match(text, /közös hír: csak 0/);
  assert.doesNotMatch(text, /NaN|undefined/);
});

test('nincs közös hír: több szavazó', () => {
  const r = reconcileMany([{ voter: 'A', votes: A10.map((b, i) => vote(i, b)) }, { voter: 'B', votes: B10.map((b, i) => vote(100 + i, b)) },
    { voter: 'C', votes: A10.map((b, i) => vote(200 + i, b)) }]);
  assert.deepEqual(r.pairs.map(p => p.all.n), [0, 0, 0]);
  assert.ok(r.pairs.every(p => Number.isNaN(p.all.kappa)));
  assert.equal(r.consensus.n, 0);
  assert.ok(Number.isNaN(r.consensus.agree));
  assert.deepEqual([r.langAvg, r.ruleAuc, r.disagreements], [{}, {}, []]);
  assert.ok(r.perVoter.every(v => Number.isNaN(v.avgKappa) && v.partners === 0));
  const text = formatReconMany(r);
  assert.match(text, /A–B: közös hír csak 0/);
  assert.doesNotMatch(text, /NaN|undefined|jelzés:/);                  // adat nélkül nincs figyelmeztetés sem
});

test('kevés közös hír: a pár kimarad a nyelvi átlagból és a szavazónkénti egyezésből', () => {
  const r = reconcileMany([{ voter: 'A', votes: A10.slice(0, 9).map((b, i) => vote(i, b)) }, { voter: 'B', votes: B10.slice(0, 9).map((b, i) => vote(i, b)) }]);
  assert.equal(r.pairs[0].all.n, 9);
  assert.deepEqual(r.langAvg, {});                                     // 10 közös hír alatt nem átlagol
  assert.ok(r.perVoter.every(v => v.partners === 0));
});

// ---- hiányzó adat ----

test('üres bemenet: egyik számítás sem dob kivételt', () => {
  const r = reconcile([], []);
  assert.deepEqual([r.nMine, r.nTheirs, r.overlap.n], [0, 0, 0]);
  const m = reconcileMany([]);
  assert.deepEqual([m.voters, m.pairs, m.perVoter], [[], [], []]);
  assert.match(formatReconMany(m), /legalább két szavazó/);
  const e = reconcileMany([{ voter: 'A', votes: [] }, { voter: 'B', votes: [] }]);
  assert.deepEqual(e.voters.map(v => v.n), [0, 0]);
  assert.equal(e.pairs[0].all.n, 0);
  assert.deepEqual(blindVotes([]), { ok: false, n: 0, bait: 0 });
  assert.deepEqual(timeSplit([]), { ok: false, n: 0 });
  assert.deepEqual(twoStep([]), { ok: false, n: 0 });
  assert.deepEqual(repeatStats([]), { ok: false, n: 0 });
  assert.deepEqual(midStats([], []), { ok: false, n: 0 });
  assert.equal(calibrate([]).ready, false);
  assert.deepEqual(concentration([]), { domains: 0, top: [], top5Share: 0 });
  assert.equal(voteFlags([]).n, 0);
  assert.deepEqual(progress([]), { eval: 0, bait: 0, train: 0 });
  assert.deepEqual(pickSample([], 100), []);
  assert.equal(pickRepeat([], [], T0, () => 0), null);
  assert.deepEqual(buildPools([], { voted: new Set(), skipped: new Set(), langOk: () => true }), { eval: [], train: [], shared: [] });
  assert.equal(nextItem(null), null);
  assert.equal(answeredCount(null), 0);
});

test('szavazó-azonosító nélküli mentés: „?” jelölést kap, és azonosnak számít', () => {
  const r = reconcileMany([{ votes: A10.map((b, i) => vote(i, b)) }, { votes: B10.map((b, i) => vote(i, b)) }]);
  assert.deepEqual(r.voters.map(v => [v.voter, v.dupe]), [['?', false], ['?#2', true]]);
  assert.ok(near(r.pairs[0].all.kappa, KAPPA10));
});

test('pontszám nélküli szavazat: az egyezésbe beszámít, az AUC-ból kimarad', () => {
  const a = A10.concat(A10);
  const mine = a.map((b, i) => vote(i, b));
  const theirs = a.map((b, i) => strip(vote(i, b, { blind: true }), 'sRule', 'sAi'));
  const r = reconcile(mine, theirs);
  assert.equal(r.overlap.n, 20);                                       // a címke megvan: a kappa számolható
  assert.equal(r.overlap.kappa, 1);
  assert.deepEqual(r.auc, {});                                         // pontszám nélkül nincs AUC-csoport
  const half = a.map((b, i) => (i < 6 ? strip(vote(i, b, { blind: true }), 'sAi') : vote(i, b, { blind: true })));
  assert.equal(reconcile(mine, half).auc.hu.n, 14);
  assert.equal(blindVotes(theirs).n, 0);
  assert.equal(calibrate(theirs).n, 0);
  assert.equal(twoStep(theirs.map(v => ({ ...v, vote2: 'bait' }))).n, 0);
});

test('pontszám nélküli konszenzus: a szabály AUC-ja nem számítható, nem hibás érték', () => {
  const a = A10.concat(A10), bare = a.map((b, i) => strip(vote(i, b), 'sRule'));
  const r = reconcileMany([{ voter: 'A', votes: bare }, { voter: 'B', votes: bare }]);
  assert.equal(r.consensus.n, 20);
  assert.ok(Number.isNaN(r.ruleAuc.hu.rule));
  assert.match(formatReconMany(r), /AUC – \(még kevés\)/);
});

test('időbélyeg nélküli szavazat: az időbeli tesztből és a vak mintavétel korszűréséből', () => {
  const votes = Array.from({ length: 120 }, (_, i) => (i < 30 ? strip(vote(i, i % 3 === 0), 'ts') : vote(i, i % 3 === 0)));
  assert.deepEqual(timeSplit(votes), { ok: false, n: 90 });            // csak az időbélyegesek számítanak
  assert.equal(pickRepeat([strip(vote(1, 1, { blind: true }), 'ts')], [], T0 + 1e12, () => 0), null);   // kor nélkül nem ismétli
  assert.equal(pickSample([strip(vote(1, 1), 'ts')], 10).length, 1);   // a vak mintába bekerülhet (a kora ismeretlen)
});

test('nyelvjelölés nélküli szavazat: a nyelv a címből becsült', () => {
  const hu = i => `Ülésezett a megyei közgyűlés, és döntött az új hídról ${i}`, en = i => `The president said that the new law will not be passed ${i}`;
  const mk = (i, b) => strip(vote(i, b, { title: i < 10 ? hu(i) : en(i), domain: i < 10 ? 'pelda.hu' : 'example.com' }), 'lang');
  const a = A10.concat(A10), r = reconcile(a.map((b, i) => mk(i, b)), a.map((b, i) => mk(i, b)));
  assert.deepEqual(Object.keys(r.byLang).sort(), ['en', 'hu']);
  assert.deepEqual([r.byLang.hu.n, r.byLang.en.n], [10, 10]);
  const s = langSplit(a.map((b, i) => mk(i, b)));
  assert.deepEqual([s.hu.n, s.hu.bait], [10, 4]);
});

test('vak újracímkézés: a megválaszolatlan és a kihagyott hír nem számít', () => {
  const a = A10.concat(A10), b = B10.concat(B10);
  const items = a.map((o, i) => ({ id: String(i), title: `c${i}`, orig: o, sRule: o ? 0.6 : 0.1, sAi: o ? 0.7 : 0.2 }))
    .concat([{ id: 'x', title: 'x', orig: 1, sRule: 0.5, sAi: 0.5 }, { id: 'y', title: 'y', orig: 0, sRule: 0.5, sAi: 0.5 }]);
  const answers = Object.fromEntries(b.map((z, i) => [String(i), z]));
  answers.x = 2;                                                       // kihagyva: megválaszolt, de nem címke
  const st = { items, answers };
  assert.equal(answeredCount(st), 20);
  assert.equal(nextItem(st).id, 'y');
  const r = blindStats(st);
  assert.ok(r.ok && r.n === 20 && near(r.kappa, KAPPA10));
});

test('vak újracímkézés: ha minden válasz azonos, a kappa 0 és az AUC nem számítható', () => {
  const a = A10.concat(A10);
  const items = a.map((o, i) => ({ id: String(i), title: `c${i}`, orig: o, sRule: o ? 0.6 : 0.1, sAi: 0.3 }));
  const r = blindStats({ items, answers: Object.fromEntries(items.map(i => [i.id, 0])) });
  assert.equal(r.kappa, 0);                                            // az egyezés pontosan a véletlen szintje
  assert.ok(Number.isNaN(r.aucBlind.rule));
  assert.equal(r.aucOrig.rule, 1);
  assert.equal(r.aucOrig.ai, 0.5);                                     // csupa holtverseny
});

// ---- a „közepes” címke ----

test('közepes: nem számít értékelőnek sem a páros egyezésben, sem a konszenzusban', () => {
  const a = A10.map((b, i) => vote(i, b));
  const c = A10.map((b, i) => (i < 4 ? mid(i) : vote(i, b)));
  const two = reconcileMany([{ voter: 'A', votes: a }, { voter: 'C', votes: c }]);
  assert.equal(two.voters[1].n, 6);
  assert.equal(two.pairs[0].all.n, 6);
  assert.equal(two.consensus.n, 6);                                    // a 4 „közepes” hírt csak egy szavazó értékelte
  const r = reconcile(a, c);
  assert.deepEqual([r.nMine, r.nTheirs, r.overlap.n], [10, 6, 6]);
});

test('közepes: nem tanít és nem számít az AUC-ba, a haladásba és az ismétlésbe', () => {
  const mids = Array.from({ length: 40 }, (_, i) => mid(i, { blind: true, queue: 'eval', ts: T0 }));
  assert.equal(progress(mids).bait, 0);
  assert.equal(pickRepeat(mids, [], T0 + 1e12, () => 0), null);
  assert.deepEqual(repeatStats(A10.map((_, i) => ({ id: String(i), first: 'mid', second: 'mid' }))), { ok: false, n: 0 });
  assert.equal(twoStep(mids.map(v => ({ ...v, vote2: 'mid' }))).n, 0);
});

test('közepes: átlagos AI-érték a nyugodt és a hangos között (midStats)', () => {
  const q = { blind: true, quick: true };
  const votes = [vote(1, 0, { ...q, sAi: 0.1 }), vote(2, 0, { ...q, sAi: 0.3 }), vote(3, 1, { ...q, sAi: 0.9 }),
    vote(4, 1, { blind: true, sAi: 0.0 }), vote(5, 1, { quick: true, sAi: 0.0 })];   // nem gyorsszavazat / nem vak: kimarad
  const mids = [mid(6, { blind: true, sAi: 0.4 }), mid(7, { blind: true, sAi: 0.6 }), mid(8, { sAi: 1 }), strip(mid(9, { blind: true }), 'sAi')];
  const r = midStats(votes, mids);
  assert.ok(r.ok);
  assert.equal(r.n, 3);                                                // csak a vak „közepes” jelölések
  assert.ok(near(r.share, 3 / 6));
  assert.ok(near(r.fact, 0.2) && near(r.mid, 0.5) && near(r.bait, 0.9));   // az AI-érték nélküli rekord az átlagból kimarad
  assert.deepEqual(midStats(votes, [mid(8)]), { ok: false, n: 0 });
});

test('közepes: a mentés külön listában viszi, a körbeforduló megőrzi', () => {
  const p = parseBackup(serialize(buildBackup({ voter: 'A', votes: [vote(1, 1)], mids: [mid(2, { blind: true, queue: 'eval' })] }, T0)));
  assert.deepEqual([p.data.votes.length, p.data.mids.length], [1, 1]);
  assert.deepEqual([p.data.mids[0].vote, p.data.mids[0].blind, p.data.mids[0].queue], ['mid', true, 'eval']);
});

// ---- egyesítés: címkeváltás és hiányos rekordok ----

test('egyesítés: címkeváltás a nyugodt/hangos és a közepes között', () => {
  const r = planRestore([vote(1, 0, { ts: 100 }), vote(2, 1, { ts: 100 })], [mid(3, { ts: 100 }), mid(4, { ts: 300 })],
    { votes: [vote(3, 1, { ts: 200 }), vote(4, 1, { ts: 200 })], mids: [mid(1, { ts: 200 }), mid(2, { ts: 50 })] });
  assert.deepEqual(r.stats, { added: 0, updated: 2, same: 2 });
  assert.deepEqual(r.votes.map(v => v.id).sort(), ['2', '3']);         // 1: közepes lett (újabb); 3: hangos lett (újabb)
  assert.deepEqual(r.mids.map(v => v.id).sort(), ['1', '4']);          // 2 és 4: a meglévő újabb, marad
  assert.equal(r.votes.length + r.mids.length, 4);                     // egy hír csak az egyik listában szerepel
});

test('egyesítés: időbélyeg nélküli rekordok', () => {
  const noTs = (id, b) => strip(vote(id, b), 'ts');
  const r = planRestore([noTs(1, 0), vote(2, 0, { ts: 100 }), noTs(3, 0)], [], { votes: [noTs(1, 1), noTs(2, 1), vote(3, 1, { ts: 5 })], mids: [] });
  assert.deepEqual(r.stats, { added: 0, updated: 1, same: 2 });
  const by = Object.fromEntries(r.votes.map(v => [v.id, v.vote]));
  assert.deepEqual(by, { 1: 'fact', 2: 'fact', 3: 'bait' });           // időbélyeg nélkül a meglévő marad; a bélyeges az újabb
});

test('egyesítés: üres oldalak és a mentésen belüli ismétlődés', () => {
  assert.deepEqual(planRestore([], [], { votes: [], mids: [] }), { votes: [], mids: [], write: [], stats: { added: 0, updated: 0, same: 0 } });
  const keep = planRestore([vote(1, 1)], [mid(2)], { votes: [], mids: [] });
  assert.deepEqual([keep.votes.length, keep.mids.length, keep.write.length], [1, 1, 0]);   // üres mentés nem töröl
  const dup = planRestore([], [], { votes: [vote(1, 0, { ts: 100 }), vote(1, 1, { ts: 200 }), vote(1, 0, { ts: 150 })], mids: [] });
  assert.deepEqual(dup.votes.map(v => [v.id, v.vote, v.ts]), [['1', 'bait', 200]]);       // a legújabb marad
});
