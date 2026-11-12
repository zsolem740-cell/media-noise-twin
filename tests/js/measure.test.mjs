// A parancssoros mérő (scripts/measure.mjs): szintetikus mentésfájlokon, ideiglenes mappában.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs, loadSets, measure, formatMeasure } from '../../scripts/measure.mjs';
import { buildBackup, serialize } from '../../public/js/modules/backup.js';
import { vote, A10, B10, KAPPA10, near, T0 } from './helpers.mjs';

const SCRIPT = fileURLToPath(new URL('../../scripts/measure.mjs', import.meta.url));
const backup = (voter, labels, extra = {}) => serialize(buildBackup({ app: 'v0-teszt', voter, votes: labels.map((b, i) => vote(i, b, { voter, ver: 'v0-teszt' })), ...extra }, T0));
const run = (...args) => spawnSync(process.execPath, [SCRIPT, ...args], { encoding: 'utf8' });

function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'mnt-measure-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const a = join(dir, 'mentes-A.txt'), b = join(dir, 'mentes-B.txt');
  writeFileSync(a, backup('A', A10));
  writeFileSync(b, backup('B', B10));
  return { dir, a, b };
}

test('kapcsolók', () => {
  assert.deepEqual(parseArgs(['--json', '--lam', '0.5', 'a.txt', 'b.txt']), { json: true, lam: 0.5, files: ['a.txt', 'b.txt'] });
  assert.deepEqual(parseArgs([]), { json: false, lam: 0.3, files: [] });
  assert.throws(() => parseArgs(['--lam', 'sok']));
  assert.throws(() => parseArgs(['--lam', '2']));
  assert.throws(() => parseArgs(['--torol']));
});

test('mérés: a kappa megegyezik a kézzel számolttal', () => {
  const { sets, bad } = loadSets([{ name: 'a', text: backup('A', A10) }, { name: 'b', text: backup('B', B10) }]);
  assert.equal(bad.length, 0);
  const m = measure(sets);
  assert.deepEqual(m.voters.map(v => [v.voter, v.votes, v.bait]), [['A', 10, 4], ['B', 10, 4]]);
  assert.ok(near(m.recon.pairs[0].all.kappa, KAPPA10));
  assert.match(formatMeasure(m), /A–B: közös hír 10 · egyezés 80% · kappa 0\.58/);
});

test('mérés: szavazónkénti sorok (értékelő sor, rejtett ismétlés)', () => {
  const votes = Array.from({ length: 40 }, (_, i) => vote(i, i % 4 === 0, { blind: true, queue: 'eval', voter: 'A' }));
  const repeats = A10.map((x, i) => ({ id: String(i), first: x ? 'bait' : 'fact', second: B10[i] ? 'bait' : 'fact' }));
  const { sets } = loadSets([{ name: 'a', text: serialize(buildBackup({ voter: 'A', votes, repeats }, T0)) }]);
  const v = measure(sets).voters[0];
  assert.ok(v.evalQueue.ok && v.evalQueue.n === 40 && v.evalQueue.rule === 1);
  assert.ok(v.repeats.ok && near(v.repeats.kappa, KAPPA10));
  assert.equal(v.blind, 40);
  const text = formatMeasure(measure(sets));
  assert.match(text, /értékelő sor: 40 db \(10 hangos\) · AUC szabály 1\.00/);
  assert.match(text, /rejtett ismétlés: 10 pár · egyezés 80% · kappa 0\.58/);
});

test('mérés: egy fájlban több mentés, hibás darab kihagyva', () => {
  const { sets, bad } = loadSets([{ name: 'mind', text: `${backup('A', A10)}\n${backup('B', B10)}` }, { name: 'rossz', text: '{"format":"mas"}' }, { name: 'ures', text: '' }]);
  assert.deepEqual(sets.map(s => s.voter), ['A', 'B']);
  assert.deepEqual(bad.map(b => b.name), ['rossz', 'ures']);
  assert.match(formatMeasure(measure(sets), bad), /KIHAGYVA rossz: ez nem a Média-Zaj mentése/);
});

test('parancssor: szöveges és JSON kimenet, a mentésfájlok érintetlenek', t => {
  const { a, b } = fixture(t);
  const before = [readFileSync(a, 'utf8'), readFileSync(b, 'utf8')];
  const txt = run(a, b);
  assert.equal(txt.status, 0, txt.stderr);
  assert.match(txt.stdout, /^MÉRÉS · 2 mentés/);
  assert.match(txt.stdout, /kappa 0\.58/);
  const js = run('--json', a, b);
  assert.equal(js.status, 0, js.stderr);
  const j = JSON.parse(js.stdout);
  assert.ok(near(j.recon.pairs[0].all.kappa, KAPPA10));
  assert.equal(j.voters.length, 2);
  assert.deepEqual([readFileSync(a, 'utf8'), readFileSync(b, 'utf8')], before);
});

test('parancssor: hibák érthető üzenettel és nem nulla kilépéssel', t => {
  const { dir, a } = fixture(t);
  assert.equal(run().status, 2);
  assert.equal(run(join(dir, 'nincs.txt')).status, 2);
  assert.equal(run('--ismeretlen', a).status, 2);
  const bad = join(dir, 'rossz.txt'); writeFileSync(bad, 'nem mentés');
  const r = run(bad);
  assert.equal(r.status, 1);
  assert.match(r.stderr, /egyetlen érvényes mentés sincs/);
});
