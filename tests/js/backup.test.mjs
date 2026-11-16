// Mentés és helyreállítás: a formátum, az ellenőrzés és az egyesítés szabályai (nem töröl, az újabb időbélyeg marad).
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildBackup, serialize, parseBackup, planRestore, validVote, shouldAutoBackup, toBase64Utf8, validRepoRef, maskToken,
  ghRepoPrivate, ghPut, BACKUP_FORMAT, BACKUP_VERSION } from '../../public/js/modules/backup.js';
import { vote, T0, HOUR } from './helpers.mjs';

const state = () => ({
  app: 'v0-teszt', voter: 'B', token: 'TITKOS-KULCS', cloud: { token: 'TITKOS-KULCS' },
  votes: [vote(1, 1, { blind: true, queue: 'eval', quick: true, shared: true, voter: 'B', ver: 'v0-teszt', idegen: 'x', S0: null }), vote(2, 0)],
  mids: [{ ...vote(3, 0), vote: 'mid' }],
  repeats: [{ id: '1', first: 'bait', second: 'fact', ts: T0 }], skipped: new Set(['9']), prefs: { langs: ['hu', 'de'] },
  blind: { items: [{ id: '1', title: 'x', orig: 1, sRule: 0.5, sAi: 0.5 }], answers: { 1: 1 } },
});

test('mentés: körbeforduló (build → serialize → parse)', () => {
  const text = serialize(buildBackup(state(), T0));
  assert.ok(!text.includes('\n'));                                     // egysoros: több mentés soronként illeszthető
  const p = parseBackup(text);
  assert.ok(p.ok);
  assert.equal(p.stats.invalid, 0);
  const d = p.data;
  assert.equal(d.voter, 'B');
  assert.deepEqual(d.votes.map(v => v.id), ['1', '2']);
  assert.deepEqual(d.mids.map(v => v.vote), ['mid']);
  assert.deepEqual(d.skipped, ['9']);
  assert.deepEqual(d.prefs, { langs: ['hu', 'de'] });
  assert.equal(d.repeats.length, 1);
  assert.equal(d.blind.items.length, 1);
  const v = d.votes[0];
  assert.deepEqual([v.blind, v.queue, v.quick, v.shared, v.voter, v.ver], [true, 'eval', true, true, 'B', 'v0-teszt']);
  assert.ok(!('idegen' in v) && !('S0' in v));                         // ismeretlen és üres mezők nem kerülnek a mentésbe
});

test('mentés: a kulcs soha nem kerül bele', () => {
  const text = serialize(buildBackup(state(), T0));
  assert.ok(!text.includes('TITKOS-KULCS'));
  const b = JSON.parse(text);
  assert.equal(b.format, BACKUP_FORMAT);
  assert.equal(b.version, BACKUP_VERSION);
  assert.deepEqual(b.counts, { votes: 2, mids: 1, repeats: 1 });
});

test('beolvasás: hibás bemenetek elutasítva, kivétel nélkül', () => {
  for (const t of ['', '   ', 'nem json', '{"format":"mas"}', '42', 'null', '{"format":"mnt-backup","version":99,"votes":[]}'])
    assert.equal(parseBackup(t).ok, false, t);
  assert.equal(parseBackup(undefined).ok, false);
  const half = serialize(buildBackup(state(), T0));
  assert.equal(parseBackup(half.slice(0, half.length - 20)).ok, false);   // csonka szöveg
});

test('beolvasás: a régi, sima szavazat-lista is jó', () => {
  const p = parseBackup(JSON.stringify([vote(1, 1), { ...vote(2, 0), vote: 'mid' }, vote(3, 0)]));
  assert.ok(p.ok && p.data.legacy);
  assert.deepEqual(p.data.votes.map(v => v.id), ['1', '3']);
  assert.deepEqual(p.data.mids.map(v => v.id), ['2']);
  assert.equal(p.data.voter, '');
});

test('beolvasás: a hibás rekordok kimaradnak; ha a többség hibás, az egész elutasítva', () => {
  const good = [vote(1, 1), vote(2, 0), vote(3, 0)];
  const some = parseBackup(JSON.stringify({ format: BACKUP_FORMAT, version: 1, votes: [...good, { id: 'x' }] }));
  assert.ok(some.ok);
  assert.deepEqual([some.stats.valid, some.stats.invalid], [3, 1]);
  const most = parseBackup(JSON.stringify({ format: BACKUP_FORMAT, version: 1, votes: [good[0], { id: 'x' }, { id: 'y' }] }));
  assert.equal(most.ok, false);
});

test('validVote: a kötelező mezők és a típusok', () => {
  assert.ok(validVote(vote(1, 1)));
  assert.ok(validVote({ id: 'a', vote: 'mid', title: 't' }));
  for (const bad of [null, 'x', {}, { ...vote(1, 1), vote: 'igen' }, { ...vote(1, 1), id: 5 }, { ...vote(1, 1), id: '' }, { ...vote(1, 1), title: '' },
    { ...vote(1, 1), sRule: 'sok' }, { ...vote(1, 1), ts: NaN }, { ...vote(1, 1), domain: 7 }, { ...vote(1, 1), title: 'x'.repeat(1001) }])
    assert.equal(validVote(bad), false);
});

test('egyesítés: nem töröl, az újabb időbélyeg marad', () => {
  const existing = [vote(1, 1, { ts: 100 }), vote(2, 0, { ts: 200 }), vote(3, 0, { ts: 300 })];
  const mids = [{ ...vote(4, 0), vote: 'mid', ts: 100 }];
  const incoming = { votes: [vote(1, 0, { ts: 150 }), vote(2, 1, { ts: 150 }), vote(5, 1, { ts: 1 })], mids: [{ ...vote(3, 0), vote: 'mid', ts: 300 }] };
  const snapshot = JSON.stringify([existing, mids, incoming]);
  const r = planRestore(existing, mids, incoming);
  assert.deepEqual(r.stats, { added: 1, updated: 1, same: 2 });
  const by = Object.fromEntries(r.votes.concat(r.mids).map(v => [v.id, v]));
  assert.deepEqual(Object.keys(by).sort(), ['1', '2', '3', '4', '5']);  // minden korábbi megmaradt
  assert.equal(by[1].vote, 'fact');                                    // az újabb felülírta
  assert.equal(by[2].vote, 'fact');                                    // a régebbi nem
  assert.equal(by[3].vote, 'fact');                                    // azonos időbélyegnél a meglévő marad
  assert.deepEqual(r.write.map(v => v.id).sort(), ['1', '5']);
  assert.deepEqual(r.mids.map(v => v.id), ['4']);
  assert.equal(JSON.stringify([existing, mids, incoming]), snapshot);  // a bemenetet nem módosítja
});

test('egyesítés: ugyanaz a mentés kétszer nem változtat', () => {
  const votes = [vote(1, 1), vote(2, 0)];
  const once = planRestore([], [], { votes, mids: [] });
  const twice = planRestore(once.votes, once.mids, { votes, mids: [] });
  assert.deepEqual(twice.stats, { added: 0, updated: 0, same: 2 });
  assert.equal(twice.write.length, 0);
});

test('automatikus mentés időzítése', () => {
  const now = T0, meta = { repo: 'a/b', token: 't', last: now - 25 * HOUR, count: 10 };
  assert.equal(shouldAutoBackup(null, 5, now), false);
  assert.equal(shouldAutoBackup({ repo: 'a/b' }, 5, now), false);                       // kulcs nélkül soha
  assert.equal(shouldAutoBackup({ repo: 'a/b', token: 't' }, 5, now), true);            // még nem volt mentés
  assert.equal(shouldAutoBackup(meta, 11, now), true);                                  // napi egy, ha változott
  assert.equal(shouldAutoBackup(meta, 10, now), false);                                 // változás nélkül nem
  assert.equal(shouldAutoBackup({ ...meta, last: now - HOUR }, 11, now), false);
  assert.equal(shouldAutoBackup({ ...meta, last: now - HOUR }, 110, now), true);        // +100 szavazat
  assert.equal(shouldAutoBackup({ ...meta, last: now - 60e3 }, 500, now), false);       // de legfeljebb 10 percenként
});

test('GitHub-segédek: base64, tárolónév, kulcs maszkolása', () => {
  const s = 'árvíztűrő tükörfúrógép – „teszt”';
  assert.equal(Buffer.from(toBase64Utf8(s), 'base64').toString('utf8'), s);
  const big = 'ő'.repeat(70000);
  assert.equal(Buffer.from(toBase64Utf8(big), 'base64').toString('utf8'), big);
  assert.ok(validRepoRef('valaki/mentes-1') && validRepoRef(' valaki/mentes '));
  for (const bad of ['', 'valaki', 'a/b/c', 'a b/c', 'https://github.com/a/b']) assert.equal(validRepoRef(bad), false, bad);
  assert.equal(maskToken('abcdefgh1234'), '••••1234');
  assert.equal(maskToken(''), '');
});

const fakeFetch = responses => { const calls = []; const f = async (url, opt = {}) => { calls.push({ url, opt }); return responses.shift(); }; f.calls = calls; return f; };
const res = (status, body = {}) => ({ status, json: async () => body, text: async () => JSON.stringify(body) });

test('feltöltés előtt: nyilvános tárolóba nem ír', async () => {
  const cfg = { repo: 'a/b', token: 't' };
  assert.deepEqual(await ghRepoPrivate(cfg, fakeFetch([res(200, { private: true })])), { ok: true });
  assert.equal((await ghRepoPrivate(cfg, fakeFetch([res(200, { private: false })]))).ok, false);
  assert.equal((await ghRepoPrivate(cfg, fakeFetch([res(200, {})]))).ok, false);       // hiányzó mező = nem privát
  assert.equal((await ghRepoPrivate(cfg, fakeFetch([res(404)]))).ok, false);
  assert.equal((await ghRepoPrivate(cfg, async () => { throw new Error('offline'); })).ok, false);
});

test('feltöltés: új fájl, meglévő fájl (sha), ütközésnél egy újrapróbálás', async () => {
  const cfg = { repo: 'a/b', token: 't', path: 'szavazatok.json' };
  let f = fakeFetch([res(404), res(201)]);
  assert.deepEqual(await ghPut(cfg, 'x', 'm', f), { ok: true, created: true });
  assert.equal(JSON.parse(f.calls[1].opt.body).sha, undefined);
  f = fakeFetch([res(200, { sha: 'abc' }), res(200)]);
  assert.deepEqual(await ghPut(cfg, 'x', 'm', f), { ok: true, created: false });
  assert.equal(JSON.parse(f.calls[1].opt.body).sha, 'abc');
  assert.equal(Buffer.from(JSON.parse(f.calls[1].opt.body).content, 'base64').toString(), 'x');
  f = fakeFetch([res(200, { sha: 'a' }), res(409), res(200, { sha: 'b' }), res(200)]);
  assert.equal((await ghPut(cfg, 'x', 'm', f)).ok, true);
  assert.equal(f.calls.length, 4);
  f = fakeFetch([res(401)]);
  assert.equal((await ghPut(cfg, 'x', 'm', f)).ok, false);
  assert.equal(f.calls.length, 1);                                     // hibás kulccsal nem próbál írni
});
