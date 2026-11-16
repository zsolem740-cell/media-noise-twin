// Több szavazó egyeztetése, a közös sor és a gyorsszavazó sorrendje, a nyelvfelismerés alapesetei.
import test from 'node:test';
import assert from 'node:assert/strict';
import { reconcile, reconcileMany, formatRecon, formatReconMany, splitBackupTexts } from '../../public/js/modules/reconcile.js';
import { isShared, buildPools, takeNext, pickRepeat, progress } from '../../public/js/modules/quick.js';
import { detectLang, detectLangCode, votable } from '../../public/js/modules/lang.js';
import { buildBackup, serialize } from '../../public/js/modules/backup.js';
import { vote, A10, B10, KAPPA10, near, rng, T0, HOUR } from './helpers.mjs';

const setOf = (voter, labels, extra = {}) => ({ voter, votes: labels.map((b, i) => vote(i, b, extra)) });

test('több szavazó: páronkénti kappa és nyelvi átlag', () => {
  const r = reconcileMany([setOf('A', A10), setOf('B', B10), setOf('C', A10)]);
  assert.deepEqual(r.voters.map(v => v.voter), ['A', 'B', 'C']);
  assert.deepEqual(r.pairs.map(p => `${p.a}-${p.b}`), ['A-B', 'A-C', 'B-C']);
  assert.ok(near(r.pairs[0].all.kappa, KAPPA10) && near(r.pairs[2].all.kappa, KAPPA10));
  assert.equal(r.pairs[1].all.kappa, 1);
  assert.equal(r.langAvg.hu.pairs, 3);
  assert.ok(near(r.langAvg.hu.kappa, (2 * KAPPA10 + 1) / 3));
});

test('több szavazó: konszenzus a többségi címke, döntetlennél kimarad', () => {
  const three = reconcileMany([setOf('A', A10), setOf('B', B10), setOf('C', A10)]);
  assert.equal(three.consensus.n, 10);                                 // három szavazónál nincs döntetlen
  assert.ok(near(three.consensus.agree, (8 + 2 * (2 / 3)) / 10));
  assert.equal(three.disagreements.length, 2);
  const two = reconcileMany([setOf('A', A10), setOf('B', B10)]);
  assert.equal(two.consensus.n, 8);                                    // a 2 eltérő hír döntetlen: kimarad
  assert.equal(two.consensus.agree, 1);
});

test('több szavazó: a szabály AUC-ja a konszenzussal, nyelvenként', () => {
  const a = A10.concat(A10);
  const r = reconcileMany([{ voter: 'A', votes: a.map((b, i) => vote(i, b)) }, { voter: 'B', votes: a.map((b, i) => vote(i, b)) }]);
  assert.deepEqual([r.ruleAuc.hu.n, r.ruleAuc.hu.bait, r.ruleAuc.hu.rule], [20, 8, 1]);
  const few = reconcileMany([setOf('A', [1, 0, 0]), setOf('B', [1, 0, 0])]);
  assert.ok(Number.isNaN(few.ruleAuc.hu.rule));                        // 5 hangos és 5 nyugodt alatt nem mér
});

test('több szavazó: azonos azonosító jelzése, kevés közös hír, kiugró szavazó', () => {
  const dup = reconcileMany([setOf('A', A10), setOf('A', B10)]);
  assert.deepEqual(dup.voters.map(v => [v.voter, v.dupe]), [['A', false], ['A#2', true]]);
  assert.match(formatReconMany(dup), /ugyanazt az azonosítót/);
  assert.match(formatReconMany(reconcileMany([setOf('A', A10)])), /legalább két szavazó/);
  assert.match(formatReconMany(reconcileMany([setOf('A', [1, 0]), setOf('B', [1, 0])])), /közös hír csak 2/);
  const a = A10.concat(A10), flip = a.map(x => 1 - x);
  const out = reconcileMany([{ voter: 'A', votes: a.map((b, i) => vote(i, b)) }, { voter: 'B', votes: a.map((b, i) => vote(i, b)) },
    { voter: 'C', votes: a.map((b, i) => vote(i, b)) }, { voter: 'D', votes: flip.map((b, i) => vote(i, b)) }]);
  const text = formatReconMany(out);
  assert.match(text, /jelzés: D egyezése a többiekkel alacsony/);
  assert.doesNotMatch(text, /jelzés: [ABC] egyezése/);
});

test('egyeztetés: nem írja át a bemenetet', () => {
  const sets = [setOf('A', A10), setOf('B', B10)], before = JSON.stringify(sets);
  reconcileMany(sets);
  reconcile(sets[0].votes, sets[1].votes);
  assert.equal(JSON.stringify(sets), before);
});

test('két szavazó: nyelvi bontás és a másik vak címkéivel mért AUC', () => {
  const a = A10.concat(A10);
  const mine = a.map((b, i) => vote(i, b, { lang: i < 10 ? 'hu' : 'de' }));
  const theirs = a.map((b, i) => vote(i, b, { lang: i < 10 ? 'hu' : 'de', blind: true }));
  const r = reconcile(mine, theirs);
  assert.deepEqual([r.byLang.hu.n, r.byLang.de.n], [10, 10]);
  assert.ok(Number.isNaN(r.auc.hu.rule));                              // nyelvenként 4 hangos: 5 alatt nem mér
  const one = reconcile(mine, theirs.map(v => ({ ...v, lang: 'hu' })));
  assert.deepEqual([one.auc.hu.n, one.auc.hu.bait, one.auc.hu.rule, one.auc.hu.blend], [20, 8, 1, 1]);
  assert.match(formatRecon(one), /közös hír: 20 · egyezés 100% · kappa 1\.00/);
});

test('mentések szétválasztása: egy mentés, több sor, szemét sorok', () => {
  const a = serialize(buildBackup({ voter: 'A', votes: [vote(1, 1)] })), b = serialize(buildBackup({ voter: 'B', votes: [vote(1, 0)] }));
  assert.deepEqual(splitBackupTexts(a), [a]);
  assert.deepEqual(splitBackupTexts(`${a}\n\n  ${b}\r\n`), [a, b]);
  assert.deepEqual(splitBackupTexts(`A mentése:\n${a}\nB mentése:\n${b}`), [a, b]);
  assert.deepEqual(splitBackupTexts(''), []);
  assert.deepEqual(splitBackupTexts(JSON.stringify(JSON.parse(a), null, 2)), [JSON.stringify(JSON.parse(a), null, 2)]);   // tördelt JSON is egy mentés
});

test('közös sor: azonosító szerint kijelölt, a hírek kb. 10%-a', () => {
  const ids = Array.from({ length: 5000 }, (_, i) => `hir-${i}`);
  const share = ids.filter(isShared).length / ids.length;
  assert.ok(share > 0.07 && share < 0.13, `közös arány: ${share}`);
  assert.equal(isShared('hir-1'), isShared('hir-1'));
  assert.equal(isShared(123), isShared('123'));
});

test('közös sor: minden szavazónál azonos sorrend, a saját véletlentől függetlenül', () => {
  const rows = Array.from({ length: 400 }, (_, i) => ({ id: `hir-${i}`, title: `c${i}`, S: (i % 7) / 7, sAi: (i % 5) / 5 }));
  const ctx = { voted: new Set(), skipped: new Set(), langOk: () => true };
  const pa = buildPools(rows, ctx, rng(1)), pb = buildPools(rows.slice().reverse(), ctx, rng(2));
  assert.ok(pa.shared.length > 10);
  assert.deepEqual(pa.shared.map(r => r.id), pb.shared.map(r => r.id));
  assert.notDeepEqual(pa.eval.map(r => r.id), pb.eval.map(r => r.id));
  assert.ok(pa.train.length <= 150);
});

test('sorok: a szavazott, kihagyott és nem olvasott nyelvű hír kimarad', () => {
  const rows = [{ id: 'a', title: 'x', S: 0, sAi: 0 }, { id: 'b', title: 'x', S: 0, sAi: 0 }, { id: 'c', title: 'x', S: 0, sAi: 0, lang: 'de' },
    { id: 'd', title: 'x', S: 0, sAi: 0 }, { id: 'e', title: '', S: 0, sAi: 0 }];
  const p = buildPools(rows, { voted: new Set(['a']), skipped: new Set(['b']), langOk: r => r.lang !== 'de' });
  assert.deepEqual(p.eval.map(r => r.id), ['d']);
});

test('gyorsszavazó: minden ötödik közös (értékelő típusú), minden harmadik tanító, egy hír csak egyszer', () => {
  const mk = (p, n) => Array.from({ length: n }, (_, i) => ({ id: `${p}${i}` }));
  const q = { eval: mk('e', 30).concat([{ id: 's0' }]), train: mk('t', 30), shared: mk('s', 5), used: new Set(), step: 0 };
  const seq = []; for (let i = 0; i < 20; i++) seq.push(takeNext(q));
  seq.forEach((x, i) => {
    if (i % 5 === 4) assert.deepEqual([x.queue, x.shared, x.it.id[0]], ['eval', true, 's']);
    else if (i % 3 === 2) assert.deepEqual([x.queue, x.shared], ['train', undefined]);
    else assert.deepEqual([x.queue, x.shared], ['eval', undefined]);
  });
  assert.equal(new Set(seq.map(x => x.it.id)).size, 20);
  const empty = { eval: [], train: [], shared: [], used: new Set(), step: 0 };
  assert.equal(takeNext(empty), null);
});

test('rejtett ismétlés: csak 48 óránál régebbi, vak, még nem ismételt szavazat', () => {
  const now = T0 + 100 * HOUR;
  const votes = [vote(1, 1, { blind: true, ts: now - 49 * HOUR }), vote(2, 1, { blind: true, ts: now - 47 * HOUR }),
    vote(3, 0, { blind: false, ts: now - 90 * HOUR }), vote(4, 0, { blind: true, ts: now - 90 * HOUR })];
  const always = () => 0;
  const r = pickRepeat(votes, [{ id: '4' }], now, always);
  assert.deepEqual([r.it.id, r.first, r.queue, r.rep], ['1', 'bait', 'rep', true]);
  assert.deepEqual(Object.keys(r.it).sort(), ['id', 'title']);         // a szám és a forrás nem megy át
  assert.equal(pickRepeat(votes, [{ id: '4' }, { id: '1' }], now, always), null);
  assert.equal(pickRepeat(votes, [], now, () => 0.5), null);           // az esetek ~10%-ában kérdez
});

test('gyorsszavazó haladás: csak a vak szavazatok számítanak', () => {
  const votes = [vote(1, 1, { blind: true, queue: 'eval' }), vote(2, 0, { blind: true, queue: 'eval' }), vote(3, 1, { blind: true, queue: 'train' }), vote(4, 1, { queue: 'eval' })];
  assert.deepEqual(progress(votes), { eval: 2, bait: 1, train: 1 });
});

test('nyelvfelismerés: egyértelmű címek', () => {
  assert.equal(detectLang('Ülésezett a megyei közgyűlés Szombathelyen, és döntött az új hídról'), 'hu');
  assert.equal(detectLang('The president said that the new law will not be passed'), 'other');
  assert.equal(detectLang(''), '?');
  assert.equal(detectLangCode('The president said that the new law will not be passed'), 'en');
  assert.equal(detectLangCode('Der Bürgermeister hat die neue Brücke in der Stadt eröffnet und ist nicht zufrieden'), 'de');
  assert.equal(detectLangCode('Ülésezett a megyei közgyűlés Szombathelyen, és döntött az új hídról'), 'hu');
  assert.ok(votable('hu') && !votable('other') && !votable('?'));
});
