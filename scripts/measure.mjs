#!/usr/bin/env node
// Parancssoros mérés a szavazók mentéseiből: ugyanazokat a modulokat használja, mint az alkalmazás
// (Egyeztetés gomb + az Audit szavazónkénti sorai), így a mentéseket nem kell telefonon egymásba illeszteni.
//
//   node scripts/measure.mjs mentes-A.txt mentes-B.txt [...]     tömör szöveges összefoglaló
//   node scripts/measure.mjs --json mentes-*.txt                  ugyanez gépi (JSON) formában
//   node scripts/measure.mjs --lam 0.4 mentes-*.txt               az AI súlya a keverékben (alap: 0.3)
//
// Csak olvas: a mentésfájlokat nem módosítja, és semmit nem ír a repóba. Egy fájlban több mentés is lehet (soronként egy).
// A mentéseket a repón KÍVÜL vagy a (git által figyelmen kívül hagyott) mentesek/ mappában tartsd. Node 22.7+ kell.
import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseBackup } from '../public/js/modules/backup.js';
import { reconcileMany, formatReconMany, splitBackupTexts } from '../public/js/modules/reconcile.js';
import { blindVotes, repeatStats, twoStep } from '../public/js/modules/audit.js';
import { blindStats } from '../public/js/modules/blind.js';

const f2 = x => (Number.isFinite(x) ? x.toFixed(2) : '–');
const pc = x => (Number.isFinite(x) ? Math.round(x * 100) + '%' : '–');

export function parseArgs(argv) {
  const o = { json: false, lam: 0.3, files: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--json') o.json = true;
    else if (a === '--lam') { o.lam = Number(argv[++i]); if (!(o.lam >= 0 && o.lam <= 1)) throw new Error('a --lam értéke 0 és 1 közötti szám'); }
    else if (a === '-h' || a === '--help') o.help = true;
    else if (a.startsWith('--')) throw new Error(`ismeretlen kapcsoló: ${a}`);
    else o.files.push(a);
  }
  return o;
}

// Mentés-szövegek ({name, text}) → szavazónkénti készletek; a hibás darabok a `bad` listába kerülnek.
export function loadSets(inputs) {
  const sets = [], bad = [];
  inputs.forEach(({ name, text }) => {
    const parts = splitBackupTexts(text);
    if (!parts.length) { bad.push({ name, error: 'nem találtam benne mentést' }); return; }
    parts.forEach((t, i) => {
      const p = parseBackup(t);
      if (!p.ok) { bad.push({ name, error: p.error }); return; }
      sets.push({ name, voter: p.data.voter || `X${sets.length + 1}`, data: p.data, invalid: p.stats.invalid, part: i });
    });
  });
  return { sets, bad };
}

// Szavazónkénti számok: az Audit megfelelő függvényeivel (értékelő sor, rejtett ismétlés, vak újracímkézés, kétlépéses).
export function voterSummary(set, lam = 0.3) {
  const d = set.data, votes = d.votes;
  const ver = {}; votes.forEach(v => { const k = v.ver || 'ismeretlen'; ver[k] = (ver[k] || 0) + 1; });
  return {
    voter: set.voter, file: set.name, created: d.created || '', invalid: set.invalid,
    votes: votes.length, bait: votes.filter(v => v.vote === 'bait').length, mids: d.mids.length,
    blind: votes.filter(v => v.blind === true).length, shared: votes.filter(v => v.shared === true).length, ver,
    evalQueue: blindVotes(votes, lam, x => x.blind === true && x.queue === 'eval'),
    allBlind: blindVotes(votes, lam),
    repeats: repeatStats(d.repeats || []),
    relabel: blindStats(d.blind, lam),
    twoStep: twoStep(votes, lam),
  };
}

export function measure(sets, lam = 0.3) {
  return {
    lam,
    voters: sets.map(s => voterSummary(s, lam)),
    recon: reconcileMany(sets.map(s => ({ voter: s.voter, votes: s.data.votes.concat(s.data.mids) })), lam),
  };
}

export function formatMeasure(m, bad = []) {
  const L = [`MÉRÉS · ${m.voters.length} mentés · λ ${m.lam}`];
  m.voters.forEach(v => {
    const e = v.evalQueue, r = v.repeats, b = v.relabel, t = v.twoStep;
    L.push(`${v.voter} (${v.file}${v.created ? ', ' + v.created.slice(0, 16) + 'Z' : ''}): ${v.votes} szavazat (${v.bait} hangos) · közepes ${v.mids} · vak ${v.blind} · közös sor ${v.shared} · kódverzió: ${Object.entries(v.ver).sort().map(([k, n]) => `${k} ${n}`).join(', ') || '–'}${v.invalid ? ` · HIBÁS rekord: ${v.invalid}` : ''}`);
    L.push(e.ok
      ? `  értékelő sor: ${e.n} db (${e.bait} hangos) · AUC szabály ${f2(e.rule)} · AI ${f2(e.ai)} · keverék ${f2(e.blend)} [${f2(e.ci.auc[0])}–${f2(e.ci.auc[1])}]`
      : `  értékelő sor: még kevés (${e.n} db, ${e.bait || 0} hangos; legalább 30 és 5 kell)`);
    if (r.ok) L.push(`  rejtett ismétlés: ${r.n} pár · egyezés ${pc(r.agree)} · kappa ${f2(r.kappa)}`);
    else if (r.n) L.push(`  rejtett ismétlés: még kevés (${r.n} pár, legalább 10 kell)`);
    if (b.ok) L.push(`  vak újracímkézés: ${b.n} hír · egyezés ${pc(b.agree)} · kappa ${f2(b.kappa)} · keverék AUC a vak címkékkel ${f2(b.aucBlind.blend)}`);
    if (t.ok) L.push(`  kétlépéses: ${t.n} pár · egyezés ${pc(t.agree)} · kappa ${f2(t.kappa)}`);
  });
  bad.forEach(x => L.push(`KIHAGYVA ${x.name}: ${x.error}`));
  L.push(formatReconMany(m.recon));
  return L.join('\n');
}

const USAGE = 'használat: node scripts/measure.mjs [--json] [--lam 0.3] mentes-A.txt mentes-B.txt [...]';

function main(argv) {
  let o;
  try { o = parseArgs(argv); } catch (e) { console.error(`${e.message}\n${USAGE}`); return 2; }
  if (o.help || !o.files.length) { console.error(USAGE); return o.help ? 0 : 2; }
  const inputs = [];
  for (const f of o.files) {
    try { inputs.push({ name: basename(f), text: readFileSync(f, 'utf8') }); }
    catch (e) { console.error(`nem olvasható: ${f} (${e.code || e.message})`); return 2; }
  }
  const { sets, bad } = loadSets(inputs);
  if (!sets.length) { bad.forEach(x => console.error(`KIHAGYVA ${x.name}: ${x.error}`)); console.error('egyetlen érvényes mentés sincs'); return 1; }
  const m = measure(sets, o.lam);
  console.log(o.json ? JSON.stringify({ ...m, skipped: bad }) : formatMeasure(m, bad));
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = main(process.argv.slice(2));
