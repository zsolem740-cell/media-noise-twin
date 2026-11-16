// AUC és kappa: kézzel kiszámolt mintákon. Súlyokat, kulcsszavakat és küszöböket szándékosan nem rögzít.
import test from 'node:test';
import assert from 'node:assert/strict';
import { aucRank, repeatStats, twoStep, blindVotes, timeSplit, concentration, voteFlags } from '../../public/js/modules/audit.js';
import { auc, calibrate } from '../../public/js/modules/calibration.js';
import { blindStats, pickSample } from '../../public/js/modules/blind.js';
import { reconcile } from '../../public/js/modules/reconcile.js';
import { vote, A10, B10, KAPPA10, near, rng, T0, HOUR } from './helpers.mjs';

test('AUC: kézzel számolt értékek', () => {
  // pozitív 0,35 és 0,8; negatív 0,1 és 0,4 → a 4 párból 3 helyes sorrendű
  assert.equal(aucRank([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75);
  assert.equal(auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]), 0.75);
  assert.equal(aucRank([1, 2, 3, 4], [0, 0, 1, 1]), 1);
  assert.equal(aucRank([4, 3, 2, 1], [0, 0, 1, 1]), 0);
});

test('AUC: egyező pontszám fél pontot ér', () => {
  assert.equal(aucRank([0.5, 0.5], [0, 1]), 0.5);
  assert.equal(auc([0.5, 0.5], [0, 1]), 0.5);
  assert.equal(aucRank([0.2, 0.5, 0.5, 0.9], [0, 0, 1, 1]), 0.875);   // (1 + 0,5 + 1 + 1) / 4
});

test('AUC: egyetlen osztálynál nincs érték', () => {
  assert.ok(Number.isNaN(aucRank([0.1, 0.2], [1, 1])));
  assert.ok(Number.isNaN(aucRank([], [])));
  assert.equal(auc([0.1, 0.2], [0, 0]), 0.5);                          // a kalibráció semleges értéket ad
});

test('AUC: a két megvalósítás véletlen adaton is megegyezik', () => {
  const R = rng(3);
  for (let k = 0; k < 20; k++) {
    const n = 5 + Math.floor(R() * 60);
    const s = Array.from({ length: n }, () => Math.round(R() * 10) / 10);   // sok egyező pontszám
    const y = Array.from({ length: n }, () => (R() < 0.4 ? 1 : 0));
    if (!y.includes(1) || !y.includes(0)) continue;
    assert.ok(near(aucRank(s, y), auc(s, y), 1e-12));
  }
});

test('AUC: a pontszámok monoton átalakítása nem változtat', () => {
  const s = [0.1, 0.9, 0.3, 0.3, 0.7, 0.2], y = [0, 1, 0, 1, 1, 0];
  assert.equal(aucRank(s, y), aucRank(s.map(x => 5 * x + 2), y));
});

test('kappa: szavazók között (reconcile)', () => {
  const mine = A10.map((b, i) => vote(i, b)), theirs = B10.map((b, i) => vote(i, b));
  const r = reconcile(mine, theirs);
  assert.equal(r.overlap.n, 10);
  assert.ok(near(r.overlap.agree, 0.8));
  assert.ok(near(r.overlap.kappa, KAPPA10));
  assert.deepEqual(r.overlap.bait, [4, 4]);
  assert.equal(r.disagreements.length, 2);
  assert.ok(near(reconcile(theirs, mine).overlap.kappa, KAPPA10));     // szimmetrikus
});

test('kappa: teljes egyezés 1, a „közepes” és a nem közös hír kimarad', () => {
  const mine = A10.map((b, i) => vote(i, b)).concat([{ ...vote(50, 0), vote: 'mid' }, vote(60, 1)]);
  const theirs = A10.map((b, i) => vote(i, b)).concat([vote(50, 1), vote(70, 0)]);
  const r = reconcile(mine, theirs);
  assert.equal(r.overlap.n, 10);
  assert.equal(r.overlap.kappa, 1);
  assert.equal(r.overlap.agree, 1);
});

test('kappa: ha mindkét szavazó mindent ugyanúgy jelöl, nincs érték (0/0)', () => {
  const all = A10.map((_, i) => vote(i, 0));
  assert.ok(Number.isNaN(reconcile(all, all).overlap.kappa));
});

test('kappa: rejtett ismétlések (repeatStats)', () => {
  const reps = A10.map((a, i) => ({ id: String(i), first: a ? 'bait' : 'fact', second: B10[i] ? 'bait' : 'fact' }));
  const r = repeatStats(reps);
  assert.ok(r.ok && r.n === 10 && near(r.agree, 0.8) && near(r.kappa, KAPPA10));
  assert.equal(repeatStats(reps.slice(0, 9)).ok, false);               // 10 pár alatt nem mér
  assert.equal(repeatStats(reps.concat([{ id: 'x', first: 'mid', second: 'bait' }])).n, 10);
});

test('kappa: kétlépéses címkézés (twoStep)', () => {
  const a = A10.concat(A10), b = B10.concat(B10);
  const votes = a.map((x, i) => vote(i, x, { vote2: b[i] ? 'bait' : 'fact' }));
  const r = twoStep(votes);
  assert.ok(r.ok && r.n === 20 && near(r.agree, 0.8) && near(r.kappa, KAPPA10));
  assert.equal(r.titleBait, 8);
  assert.equal(r.readBait, 8);
  assert.equal(twoStep(votes.slice(0, 19)).ok, false);
});

test('kappa: vak újracímkézés (blindStats)', () => {
  const a = A10.concat(A10), b = B10.concat(B10);
  const items = a.map((o, i) => ({ id: String(i), title: `c${i}`, orig: o, sRule: o ? 0.6 : 0.1, sAi: o ? 0.7 : 0.2 }));
  const answers = Object.fromEntries(b.map((z, i) => [String(i), z]));
  const r = blindStats({ items, answers });
  assert.ok(r.ok && r.n === 20 && near(r.agree, 0.8) && near(r.kappa, KAPPA10));
  assert.equal(r.aucOrig.rule, 1);                                     // a pontszám a régi címkét tökéletesen elválasztja
  assert.ok(r.aucBlind.rule < 1);
  assert.ok(near(r.bait2bait, 6 / 8) && near(r.fact2fact, 10 / 12));
  assert.equal(blindStats(null).ok, false);
  assert.equal(blindStats({ items, answers: { 0: 1 } }).ok, false);   // 20 válasz alatt nem mér
});

test('vak minta: csak elég régi, a szavazó nyelvén írt, még nem mintázott hírek', () => {
  const now = T0 + 1000 * HOUR;
  const votes = Array.from({ length: 60 }, (_, i) => vote(i, i % 3 === 0, { ts: now - 48 * HOUR }))
    .concat([vote(900, 1, { ts: now - HOUR }), vote(901, 1, { ts: now - 48 * HOUR, lang: 'en' })]);
  const s = pickSample(votes, 30, now, 24, 5, new Set(['0']));
  const ids = new Set(s.map(x => x.id));
  assert.equal(s.length, 30);
  assert.equal(ids.size, 30);
  assert.ok(!ids.has('900') && !ids.has('901') && !ids.has('0'));
  assert.deepEqual(pickSample(votes, 30, now, 24, 5), pickSample(votes, 30, now, 24, 5));   // azonos maggal azonos minta
});

test('vak szavazatok AUC-ja: küszöb és szűrés', () => {
  const votes = Array.from({ length: 40 }, (_, i) => vote(i, i % 4 === 0, { blind: i < 34, queue: i % 2 ? 'eval' : 'train' }));
  const r = blindVotes(votes);
  assert.ok(r.ok && r.n === 34 && r.bait === 9 && r.rule === 1);
  assert.ok(r.ci.auc[0] <= r.blend && r.blend <= r.ci.auc[1]);
  assert.equal(blindVotes(votes, 0.3, x => x.blind === true && x.queue === 'eval').ok, false);   // 17 db: 30 alatt nem mér
  assert.equal(blindVotes(votes.map(v => ({ ...v, vote: 'fact' }))).ok, false);                  // 5 hangos alatt nem mér
});

test('időbeli teszt: az első 70% választja a λ-t, az utolsó 30% mér', () => {
  const votes = Array.from({ length: 120 }, (_, i) => vote(i, i % 3 === 0));
  const r = timeSplit(votes);
  assert.ok(r.ok && r.nTrain === 84 && r.nTest === 36 && r.testBait === 12);
  assert.equal(r.rule, 1);
  assert.equal(timeSplit(votes.slice(0, 99)).ok, false);
});

test('kalibráció: kevés adatnál nem használható, jó AI-nál λ > 0', () => {
  assert.equal(calibrate([vote(1, 1), vote(2, 0)]).ready, false);
  // a szabály vak (mindenre 0,3), az AI tökéletes → a legjobb keverék az AI-t használja
  const votes = Array.from({ length: 40 }, (_, i) => vote(i, i % 2, { sRule: 0.3 }));
  const c = calibrate(votes);
  assert.ok(c.ready && c.usable && c.aucRule === 0.5 && c.aucAi === 1 && c.best.lam > 0 && c.best.auc === 1);
});

test('koncentráció és szavazat-jelzők', () => {
  const votes = [vote(1, 1, { domain: 'a.hu', blind: true, ver: 'v47.9' }), vote(2, 0, { domain: 'a.hu', blind: false }), vote(3, 0, { domain: 'b.hu' })];
  const c = concentration(votes);
  assert.equal(c.domains, 2);
  assert.deepEqual(c.top[0], { d: 'a.hu', n: 2, rate: 0.5 });
  assert.equal(c.top5Share, 1);
  const f = voteFlags(votes);
  assert.deepEqual([f.n, f.blind, f.revealed, f.none], [3, 1, 1, 1]);
  assert.deepEqual(f.ver, { 'v47.9': 1, ismeretlen: 2 });
});
