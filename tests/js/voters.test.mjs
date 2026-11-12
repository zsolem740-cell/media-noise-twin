// Szavazónkénti tárolás: áttöltés a régi közös tárolóból, a mentés szavazó szerinti szűrése, a vak jelzés, a kulcsok.
import test from 'node:test';
import assert from 'node:assert/strict';
import { VOTERS, validVoter, LEGACY_VOTER, vkey, recKey, cloudPath, LEGACY_CLOUD_PATH, legacyOwner, planMigration, planLocalCopy, LOCAL_KEYS,
  localSets, restoreScope, pickBackupFor, blindAtVote } from '../../public/js/modules/voters.js';
import { parseBackup, buildBackup, serialize, planRestore } from '../../public/js/modules/backup.js';
import { reconcileMany, splitBackupTexts } from '../../public/js/modules/reconcile.js';
import { vote, A10, B10, KAPPA10, near, T0 } from './helpers.mjs';

const mid = (id, extra = {}) => ({ ...vote(id, 0), vote: 'mid', ...extra });

test('szavazó-azonosító és kulcsok', () => {
  assert.equal(VOTERS.length, 10);
  assert.ok(VOTERS.every(validVoter));
  for (const bad of ['', 'K', 'a', 'AB', null, undefined, 1, 'A ']) assert.equal(validVoter(bad), false);
  assert.equal(recKey('A', 'x'), 'A|x');
  assert.notEqual(recKey('A', 'x'), recKey('B', 'x'));                 // ugyanaz a hír, két szavazó: két külön rekord
  assert.equal(vkey('mnt-skip', 'B'), 'mnt-skip:B');
  assert.equal(cloudPath('B'), 'szavazatok-B.json');
  assert.notEqual(cloudPath('A'), cloudPath('B'));
  assert.ok(VOTERS.every(v => cloudPath(v) !== LEGACY_CLOUD_PATH));
});

test('áttöltés: a jelöletlen (v47.9 előtti) szavazat az akkori egyetlen szavazóé, a jelölt a sajátjáé', () => {
  const old = [vote(1, 1), vote(2, 0, { voter: 'B' }), mid(3), vote(4, 1, { voter: 'A' }), vote(5, 0, { voter: 'x' })];
  const p = planMigration(old, new Set(), 'B');
  assert.equal(p.owner, LEGACY_VOTER);
  assert.deepEqual(p.entries.map(e => e.key), ['A|1', 'B|2', 'A|3', 'A|4', 'A|5']);
  assert.deepEqual(p.stats.byVoter, { A: 4, B: 1 });
  assert.equal(p.stats.unlabeled, 3);                                  // az érvénytelen jelölés is jelöletlennek számít
  assert.ok(p.entries.every(e => e.value.mig === true && validVoter(e.value.voter)));
  assert.equal(p.entries[2].value.vote, 'mid');                        // a „közepes” jelölés is átjön
});

test('áttöltés: csak a szavazó-jelölés óta használt eszközön a kiválasztott szavazóé a közös állapot', () => {
  const p = planMigration([vote(1, 1, { voter: 'C' }), vote(2, 0, { voter: 'C' })], new Set(), 'C');
  assert.equal(p.owner, 'C');
  assert.equal(legacyOwner([], 'D'), 'D');
  assert.equal(legacyOwner([], 'zz'), LEGACY_VOTER);
  assert.equal(legacyOwner([vote(1, 1)], 'D'), LEGACY_VOTER);
});

test('áttöltés: a rekord minden mezője megmarad, a bemenet nem változik', () => {
  const rec = vote(1, 1, { blind: true, queue: 'eval', quick: true, shared: true, vote2: 'fact', ts2: 5, ver: 'v47.6', S0: 0.2 });
  const old = [rec], before = JSON.stringify(old);
  const v = planMigration(old).entries[0].value;
  assert.deepEqual({ ...v, voter: undefined, mig: undefined }, { ...rec, voter: undefined, mig: undefined });
  assert.equal(JSON.stringify(old), before);
});

test('áttöltés: újrafuttatva nem ír felül és nem hoz vissza törölt szavazatot', () => {
  const old = [vote(1, 1, { ts: 100 }), vote(2, 0, { ts: 200 })];
  const first = planMigration(old, new Set(), 'A', 0);
  assert.equal(first.entries.length, 2);
  // második indulás: minden megvan → semmi teendő
  assert.equal(planMigration(old, new Set(first.entries.map(e => e.key)), 'A', 0).entries.length, 0);
  // a szavazó az új tárolóban visszavonta az 1-es szavazatát: a régi tárolóból nem jöhet vissza (régebbi az előző áttöltésnél)
  const again = planMigration(old, new Set(['A|2']), 'A', 1000);
  assert.equal(again.entries.length, 0);
  assert.equal(again.stats.old, 2);                                    // mindkét régi rekord régebbi az előző áttöltésnél
  // egy régi kóddal nyitva maradt lap az áttöltés UTÁN írt a régi tárolóba: ez átjön
  const late = planMigration(old.concat([vote(3, 1, { ts: 5000 })]), new Set(['A|2']), 'A', 1000);
  assert.deepEqual(late.entries.map(e => e.key), ['A|3']);
  // ami az új tárolóban már megvan (újabb szavazat), azt a régi nem írja felül
  assert.equal(planMigration([vote(2, 1, { ts: 5000 })], new Set(['A|2']), 'A', 1000).entries.length, 0);
});

test('áttöltés: üres és hibás bemenet', () => {
  assert.deepEqual(planMigration([]).entries, []);
  assert.deepEqual(planMigration(undefined).entries, []);
  const p = planMigration([null, 'x', {}, { id: '' }, { id: 5 }, vote(1, 1)]);
  assert.equal(p.entries.length, 1);
  assert.equal(p.stats.invalid, 5);
});

test('a régi helyi kulcsok másolása: csak a tulajdonoshoz, felülírás nélkül', () => {
  const ls = { 'mnt-repeats': '[1]', 'mnt-skip': '["x"]', 'mnt-cloud': '{"repo":"a/b"}', 'mnt-skip:A': '["sajat"]', 'mnt-voter': 'A' };
  const copies = planLocalCopy(k => (k in ls ? ls[k] : null), 'A');
  assert.deepEqual(copies, [['mnt-repeats:A', '[1]'], ['mnt-cloud:A', '{"repo":"a/b"}']]);   // a már meglévő mnt-skip:A marad
  assert.deepEqual(planLocalCopy(() => null, 'A'), []);
  assert.ok(!LOCAL_KEYS.includes('mnt-voter'));                        // a kiválasztott szavazó eszközszintű marad
});

test('helyi szavazók az egyeztetéshez: ugyanarra a hírre mindkét szavazat megvan', () => {
  const all = A10.map((b, i) => vote(i, b, { voter: 'A' })).concat(B10.map((b, i) => vote(i, b, { voter: 'B' })), [vote(99, 1), null]);
  const sets = localSets(all);
  assert.deepEqual(sets.map(s => [s.voter, s.votes.length]), [['A', 10], ['B', 10]]);   // jelöletlen rekord nem kerül szavazóhoz
  const r = reconcileMany(sets);
  assert.equal(r.pairs[0].all.n, 10);
  assert.ok(near(r.pairs[0].all.kappa, KAPPA10));
  assert.deepEqual(localSets([]), []);
});

test('helyreállítás: saját mentés teljes egészében visszaáll', () => {
  const text = serialize(buildBackup({ voter: 'B', votes: [vote(1, 1, { voter: 'B' }), vote(2, 0, { voter: 'B' })], mids: [mid(3, { voter: 'B' })],
    repeats: [{ id: '1', first: 'bait', second: 'bait', ts: 1 }], skipped: ['9'], prefs: { langs: ['hu'] } }, T0));
  const sc = restoreScope(parseBackup(text).data, 'B');
  assert.ok(sc.ok);
  assert.equal(sc.others, 0);
  assert.deepEqual([sc.data.votes.length, sc.data.mids.length, sc.data.repeats.length, sc.data.skipped.length], [2, 1, 1, 1]);
  assert.deepEqual(sc.data.prefs, { langs: ['hu'] });
});

test('helyreállítás: más szavazó mentése elutasítva', () => {
  const text = serialize(buildBackup({ voter: 'A', votes: [vote(1, 1, { voter: 'A' })] }, T0));
  const sc = restoreScope(parseBackup(text).data, 'B');
  assert.equal(sc.ok, false);
  assert.match(sc.error, /A szavazó mentése, ide \(B\) nem állítható vissza/);
});

test('helyreállítás: fejléc nélküli (v47.9 előtti) mentés az akkori egyetlen szavazóé', () => {
  const data = parseBackup(JSON.stringify([vote(1, 1), vote(2, 0)])).data;
  assert.equal(restoreScope(data, 'B').ok, false);
  const a = restoreScope(data, 'A');
  assert.ok(a.ok);
  assert.deepEqual(a.data.votes.map(v => v.voter), ['A', 'A']);        // a visszaállított rekord megkapja a szavazót
});

test('helyreállítás: közös eszközről származó, kevert mentésből csak a saját rekordok', () => {
  const votes = [vote(1, 1, { voter: 'A' }), vote(2, 0, { voter: 'B' }), vote(3, 1), vote(4, 0, { voter: 'B' })];
  const data = parseBackup(serialize(buildBackup({ voter: 'A', votes, mids: [mid(5, { voter: 'B' })], repeats: [{ id: '1', first: 'bait', second: 'fact', ts: 1 }], skipped: ['9'] }, T0))).data;
  const a = restoreScope(data, 'A');
  assert.deepEqual(a.data.votes.map(v => v.id), ['1', '3']);           // a jelöletlen a fejléc szavazójáé
  assert.equal(a.others, 3);
  assert.equal(a.data.repeats.length, 1);
  const b = restoreScope(data, 'B');
  assert.ok(b.ok);
  assert.deepEqual([b.data.votes.map(v => v.id), b.data.mids.map(v => v.id), b.others], [['2', '4'], ['5'], 2]);
  assert.deepEqual([b.data.repeats, b.data.skipped, b.data.prefs, b.data.blind], [[], [], {}, null]);   // a kiegészítő adat a fejléc szavazójáé
  assert.equal(restoreScope(data, 'C').ok, false);
});

test('helyreállítás: a szűrt mentés egyesítése nem érinti a másik szavazó rekordjait', () => {
  const mineB = [vote(1, 0, { voter: 'B', ts: 100 })];
  const data = parseBackup(serialize(buildBackup({ voter: 'A', votes: [vote(1, 1, { voter: 'A', ts: 999 }), vote(2, 1, { voter: 'B', ts: 50 })] }, T0))).data;
  const sc = restoreScope(data, 'B');
  const plan = planRestore(mineB, [], sc.data);
  assert.deepEqual(plan.stats, { added: 1, updated: 0, same: 0 });
  assert.equal(plan.votes.find(v => v.id === '1').vote, 'fact');       // A újabb szavazata ugyanarra a hírre nem írja felül B-ét
  assert.ok(plan.write.every(v => v.voter === 'B'));
});

test('üres mentés visszaállítása nem hiba', () => {
  const sc = restoreScope(parseBackup(serialize(buildBackup({ voter: 'A' }, T0))).data, 'B');
  assert.ok(sc.ok);
  assert.equal(sc.data.votes.length + sc.data.mids.length, 0);
});

test('vak jelzés: csak ha a kártya a szavazáskor tényleg rejtve volt', () => {
  assert.equal(blindAtVote(true, false, false), true);
  assert.equal(blindAtVote(false, false, false), false);               // a vak mód ki van kapcsolva
  assert.equal(blindAtVote(true, true, false), false);                 // a „Miért?” feltárta
  assert.equal(blindAtVote(true, false, true), false);                 // a saját szavazat után a kártya már feltárult: a módosítás nem vak
});

test('a mentés megőrzi az áttöltés jelölését', () => {
  const p = parseBackup(serialize(buildBackup({ voter: 'A', votes: [vote(1, 1, { voter: 'A', mig: true })] }, T0)));
  assert.equal(p.data.votes[0].mig, true);
});

// ---- minden helyi szavazó mentése egy szövegben (szavazónként egy önálló mentés, soronként egy) ----

const backupOf = (voter, labels, extra = {}, now = T0) => serialize(buildBackup({ voter, votes: labels.map((b, i) => vote(i, b, { voter })), ...extra }, now));
const parseAll = text => splitBackupTexts(text).map(parseBackup).filter(p => p.ok);

test('minden szavazó mentése: soronként egy önálló mentés, az egyeztetés közvetlenül beolvassa', () => {
  const all = [backupOf('A', A10), backupOf('B', B10), backupOf('C', A10)].join('\n');
  const parsed = parseAll(all);
  assert.deepEqual(parsed.map(p => p.data.voter), ['A', 'B', 'C']);
  const r = reconcileMany(parsed.map(p => ({ voter: p.data.voter, votes: p.data.votes.concat(p.data.mids) })));
  assert.equal(r.voters.some(v => v.dupe), false);
  assert.ok(near(r.pairs[0].all.kappa, KAPPA10));                      // A–B: ugyanarra a 10 hírre mindkét szavazat megvan
});

test('minden szavazó mentése: a helyreállítás csak az aktuális szavazó sorát veszi ki', () => {
  const all = [backupOf('A', A10, { skipped: ['a-kihagyott'] }), backupOf('B', B10, { skipped: ['b-kihagyott'], repeats: [{ id: '1', first: 'bait', second: 'bait', ts: 1 }] })].join('\n');
  const b = pickBackupFor(parseAll(all), 'B');
  assert.ok(b.ok);
  assert.equal(b.total, 2);
  assert.deepEqual(b.sc.data.votes.map(v => v.vote === 'bait' ? 1 : 0), B10);
  assert.ok(b.sc.data.votes.every(v => v.voter === 'B'));
  assert.deepEqual([b.sc.data.skipped, b.sc.data.repeats.length, b.sc.others], [['b-kihagyott'], 1, 0]);   // a kiegészítő adat is a sajátja
  const a = pickBackupFor(parseAll(all), 'A');
  assert.deepEqual(a.sc.data.votes.map(v => v.vote === 'bait' ? 1 : 0), A10);
  assert.deepEqual(a.sc.data.skipped, ['a-kihagyott']);
});

test('minden szavazó mentése: akinek nincs benne mentése, annak nem állít vissza semmit', () => {
  const all = [backupOf('A', A10), backupOf('B', B10)].join('\n');
  const c = pickBackupFor(parseAll(all), 'C');
  assert.equal(c.ok, false);
  assert.match(c.error, /2 mentése közül egyik sem a\(z\) C szavazóé/);
  assert.equal(pickBackupFor([], 'A').ok, false);
  const one = pickBackupFor(parseAll(backupOf('A', A10)), 'B');        // egyetlen mentésnél a régi, pontos hibaüzenet marad
  assert.match(one.error, /A szavazó mentése, ide \(B\) nem állítható vissza/);
});

test('minden szavazó mentése: ugyanattól a szavazótól több mentés közül a legfrissebb', () => {
  const old = backupOf('B', [1, 1, 1], {}, T0), fresh = backupOf('B', [0, 0, 0, 0], {}, T0 + 86400000);
  for (const text of [`${old}\n${fresh}`, `${fresh}\n${old}`]) {
    const b = pickBackupFor(parseAll(text), 'B');
    assert.equal(b.sc.data.votes.length, 4);
  }
});

test('minden szavazó mentése: a saját fejlécű mentés előnyt élvez a kevert régi mentéssel szemben', () => {
  const mixed = serialize(buildBackup({ voter: 'A', votes: [vote(1, 1, { voter: 'A' }), vote(2, 0, { voter: 'B' })] }, T0 + 86400000));
  const own = backupOf('B', B10, {}, T0);
  const b = pickBackupFor(parseAll(`${mixed}\n${own}`), 'B');
  assert.equal(b.sc.data.votes.length, 10);
  const onlyMixed = pickBackupFor(parseAll(mixed), 'B');               // ha csak a kevert van, abból a saját rekordok jönnek
  assert.deepEqual(onlyMixed.sc.data.votes.map(v => v.id), ['2']);
});

test('minden szavazó mentése: üres saját mentés helyett a rekordot tartalmazó kerül elő', () => {
  const empty = serialize(buildBackup({ voter: 'B' }, T0 + 86400000));
  const b = pickBackupFor(parseAll(`${empty}\n${backupOf('B', B10)}`), 'B');
  assert.equal(b.sc.data.votes.length, 10);
});
