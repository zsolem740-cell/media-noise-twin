// Fő vezérlő: állapot, eseménybusz, indítás.
import { buildModel, clamp, atmValue, buildNetMap, adjustV, tierOf, ruleParts, fmtAtm, atmRef, atmParts, scoringMode, aiBaseline } from './modules/model.js';
import { Learner } from './modules/learner.js';
import { calibrate, lambdaFinal } from './modules/calibration.js';
import { FilterEngine } from './modules/filterEngine.js';
import { Globe } from './modules/globe.js';
import { createGlobe3D } from './modules/globe3d.js';
import { store, vstore } from './modules/store.js';
import { fetchJson } from './modules/dataLoader.js';
import * as ui from './modules/uiRenderer.js';
import { parseShare, openShare, analyze } from './modules/share.js';
import { suggest, githubLinks } from './modules/suggest.js';
import { buildDiag, APP_VERSION } from './modules/diag.js';
import { runAudit } from './modules/audit.js';
import { detectLangCode } from './modules/lang.js';
import { reconcileMany, formatReconMany, splitBackupTexts } from './modules/reconcile.js';
import { buildBackup, serialize, parseBackup, planRestore, ghRepoPrivate, ghPut, ghGet, validRepoRef, maskToken, shouldAutoBackup } from './modules/backup.js';
import { buildPools, takeNext, pickRepeat, progress as quickProgress, loadRepeats, saveRepeats, loadSkipped, saveSkipped, TARGET } from './modules/quick.js';
import { loadBlind, saveBlind, pickSample, nextItem, answeredCount, blindStats } from './modules/blind.js';
import { VOTERS, validVoter, LEGACY_VOTER, vkey, cloudPath, LEGACY_CLOUD_PATH, planMigration, planLocalCopy, localSets, restoreScope, pickBackupFor, blindAtVote } from './modules/voters.js';

const bus = new EventTarget();
const on = (n, f) => bus.addEventListener(n, f);
const emit = n => bus.dispatchEvent(new Event(n));

const cap = () => (state.model && state.model.atm_cap !== undefined ? state.model.atm_cap : 0.6); // a csúszka teteje = nincs korlát

const GLOBE_PREF = 'mnt-globe';
const lsFlag = (k, d) => { try { const v = localStorage.getItem(k); return v === '1' ? true : v === '0' ? false : d; } catch (_) { return d; } };
const lsSetFlag = (k, v) => { try { localStorage.setItem(k, v ? '1' : '0'); } catch (_) {} };
const LANGS = [['hu', 'Magyar'], ['en', 'Angol'], ['de', 'Német'], ['sl', 'Szlovén']];
const loadVoter = () => { try { const v = localStorage.getItem('mnt-voter'); return /^[A-J]$/.test(v || '') ? v : 'A'; } catch (_) { return 'A'; } };
const voterChosen = () => { try { return /^[A-J]$/.test(localStorage.getItem('mnt-voter') || ''); } catch (_) { return false; } };
const loadLangs = voter => { try { const j = JSON.parse(localStorage.getItem(vkey('mnt-langs', voter)) || 'null'); if (Array.isArray(j) && j.length) return new Set(j.filter(x => typeof x === 'string')); } catch (_) {} return new Set(['hu']); };
const CLOUD_KEY = 'mnt-cloud';
// A felhő-mentés beállítása, az utolsó mentés ideje, a nyelvek, az ismétlések, a kihagyottak és a vak minta szavazónként külön kulcs alatt vannak.
const loadCloud = voter => { try { return JSON.parse(localStorage.getItem(vkey(CLOUD_KEY, voter)) || 'null') || {}; } catch (_) { return {}; } };
const saveCloud = c => { try { localStorage.setItem(vkey(CLOUD_KEY, state.voter), JSON.stringify(c)); } catch (_) {} };
const BACKUP_KEY = 'mnt-backup';
const getBackup = () => { try { return Number(localStorage.getItem(vkey(BACKUP_KEY, state.voter))) || 0; } catch (_) { return 0; } };
const setBackup = (voter = state.voter) => { try { localStorage.setItem(vkey(BACKUP_KEY, voter), String(Date.now())); } catch (_) {} };
const getPref = () => { try { return localStorage.getItem(GLOBE_PREF) || '3d'; } catch (_) { return '3d'; } };
const setPref = v => { try { localStorage.setItem(GLOBE_PREF, v); } catch (_) {} };

const state = {
  g2d: null, g3d: null, suggestion: null,
  data: null, model: null, votes: [], dwell: [], learner: new Learner(), cal: null,
  region: 'ALL', sort: 'time', maxAtm: 0.6, sliderCap: null, type: 'all',
  rows: [], net: new Map(), lam: 0.2, aiBase: 0, blind: null, blindOpen: false, auditText: '', blindVote: lsFlag('mnt-blindvote', true), showSource: lsFlag('mnt-showsrc', false), voter: loadVoter(), langs: new Set(['hu']), reconText: '', langCache: new Map(), midVotes: [], cloud: {}, pendingRestore: null, bkOpen: false, cloudBusy: false, quick: null, repeats: [], skipped: new Set(), migErr: false, localVoters: [], revealed: new Set(), opened: new Set(), globe: null,
};

function setData(d) {
  state.data = d;
  state.model = d && d.model ? buildModel(d.model) : null;
  syncSlider();
}

// A korlát-csúszka skálája a pontozási módtól függ (egész: 0–1000, klasszikus: 0,05–0,6).
function syncSlider() {
  const m = state.model;
  if (!m) return;
  const c = cap(), r = ui.$('atmRange'), classic = m.scoring !== 'sqrt_int';
  if (state.sliderCap === c) return;
  r.min = classic ? 0.05 : 0; r.max = c; r.step = classic ? 0.01 : 5; r.value = c;
  state.sliderCap = c; state.maxAtm = c;
}

const regionOf = code => (state.model ? state.model.regions.find(r => r.code === code) : null);
const regionLabel = code => { const r = regionOf(code); return r ? (r.short || r.code) : code; };

function recompute() {
  const items = (state.data && state.data.items) || [];
  state.net = buildNetMap(state.votes, state.dwell);
  state.cal = calibrate(state.votes);
  state.lam = lambdaFinal(state.votes.length, state.cal);
  const preds = items.map(it => (state.learner.boot ? state.learner.predict(it.title) : it.S));
  state.aiBase = aiBaseline(items, preds);
  state.rows = items.map((it, i) => {
    const sAi = preds[i];
    const sAiAdj = Math.max(0, sAi - state.aiBase);
    const Seff = clamp((1 - state.lam) * it.S + state.lam * sAiAdj, 0, 1);
    const v = adjustV(it.V, state.net.get(it.source_domain) || 0);
    return Object.assign({}, it, { sAi, sAiAdj, Seff, v, atm: atmValue(v, Seff, it.G) });
  });
}

function explain(it) {
  const m = state.model;
  const lines = [];
  const tier = tierOf(it.source_domain, m.trust);
  const adj = state.net.get(it.source_domain) || 0;
  const learnedShift = it.V0 !== undefined && Math.abs(it.V - it.V0) > 0.004
    ? ` · tanult eltolás ${it.V - it.V0 > 0 ? '+' : ''}${(it.V - it.V0).toFixed(2)}` : '';
  lines.push(`Forrás: ${it.source_domain || '?'} → ${tier === 'default' ? 'ismeretlen' : (m.trust[tier].label || tier)}, V ${it.v.toFixed(2)}${learnedShift}${adj ? ` (személyes korrekció ${adj > 0 ? '+' : ''}${adj.toFixed(1)} pont)` : ''}`);
  const p = ruleParts(`${it.title} ${it.summary || ''}`, m);
  lines.push(p.kw.length ? `Kulcsszavak: ${p.kw.join(', ')}` : 'Kulcsszó-találat: nincs');
  lines.push(`Felkiáltójel: ${p.ex} · NAGYBETŰS szavak: ${(p.caps * 100).toFixed(0)}%`);
  if (it.body && it.body.ok) {
    lines.push(`Cikk-szöveg (${it.body.len} karakter): kulcsszó ${it.body.kw}, felkiáltójel ${it.body.ex}${it.body.ov === null || it.body.ov === undefined ? '' : `, cím–szöveg egyezés ${(it.body.ov * 100).toFixed(0)}%`}`);
  }
  const learned = state.learner.boot ? state.learner.explain(it.title) : [];
  lines.push(`AI becslés: ${it.sAi.toFixed(2)} (alapszint ${state.aiBase.toFixed(2)} levonva → ${it.sAiAdj.toFixed(2)})${learned.length ? ' · tanult zajos jelek: ' + learned.join(', ') : ''}`);
  lines.push(`S = ${((1 - state.lam) * 100).toFixed(0)}% szabály (${it.S.toFixed(2)}) + ${(state.lam * 100).toFixed(0)}% AI → ${it.Seff.toFixed(2)}`);
  if (scoringMode() === 'sqrt_int') {
    const q = atmParts(it.v, it.Seff, it.G);
    lines.push(`ATM = √(G ${q.g} × S ${q.s} × (100 − V ${100 - q.w})) = √(${q.g} × ${q.s} × ${q.w}) = ${it.atm}`);
  } else {
    lines.push(`ATM = G ${it.G.toFixed(2)} × S ${it.Seff.toFixed(2)} × (1 − V ${it.v.toFixed(2)}) = ${it.atm.toFixed(3)}`);
  }
  return lines;
}

function exportVotes() {
  // teljes rekordok (a vak jelző, a sor, a nyelv, a második ítélet is mentődik), a „közepes” jelölésekkel együtt
  const data = JSON.stringify(state.votes.concat(state.midVotes).map(v => ({
    id: v.id, domain: v.domain, vote: v.vote, title: v.title, sRule: v.sRule, sAi: v.sAi,
    S0: v.S0, S: v.S, V: v.V, region: v.region, atm: v.atm,
    ts: v.ts, blind: v.blind, srcShown: v.srcShown, lang: v.lang, queue: v.queue, quick: v.quick, shared: v.shared, voter: v.voter, mig: v.mig, ver: v.ver, vote2: v.vote2, ts2: v.ts2,
  })), null, 1);
  const done = ok => { if (ok) { setBackup(); renderHealthBar(); } ui.setStatus(ok ? `${state.votes.length} szavazat a vágólapon (mentés rögzítve)` : 'a másolás nem sikerült'); };
  try { navigator.clipboard.writeText(data).then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

// Egészség-sáv: a szerver problémái + a szavazatmentés emlékeztetője (a szavazatok csak a telefonon vannak).
function renderHealthBar() {
  const list = ((state.data && state.data.health) || []).map(h => ({ text: h.text }));
  if (state.migErr) list.push({ soft: true, text: 'A korábbi szavazatok áttöltése a szavazónkénti tárolóba most nem sikerült (a régi adatok érintetlenek). Zárd be az alkalmazás többi lapját, és töltsd újra az oldalt.' });
  const nv = state.votes.length, last = getBackup();
  const days = last ? (Date.now() - last) / 86400000 : null;
  const c = state.cloud || {}, cloudOn = !!(c.repo && c.token), cloudDays = c.last ? (Date.now() - c.last) / 86400000 : null;
  if (cloudOn) {
    if (c.err) list.push({ soft: true, text: `Felhő-mentés hiba: ${c.err}` });
    else if (nv >= 100 && (cloudDays === null || cloudDays > 3)) list.push({ soft: true, text: `Felhő-mentés: ${cloudDays === null ? 'még nem futott le' : Math.floor(cloudDays) + ' napja mentett'}. Az Öntanuló AI panel „Mentés és helyreállítás” részében kézzel is indítható.` });
  } else if (nv >= 100 && (days === null || days > 3)) {
    list.push({ soft: true, text: `Szavazatmentés: ${days === null ? 'még nem mentetted' : Math.floor(days) + ' napja mentetted'} (${nv} szavazat csak ezen az eszközön van). Az Öntanuló AI panelben: Mentés és helyreállítás → Mentés felhőbe.` });
  }
  ui.renderHealth(list);
}

// Audit: futás közben nem másol (a vágólap felhasználói érintést kér), az eredmény a panelben jelenik meg, a „Audit másolása” gombbal másolható.
let auditBusy = false;
async function runAuditUi() {
  if (auditBusy) return;
  auditBusy = true;
  ui.setStatus('audit fut… (néhány másodperc)');
  try {
    state.auditText = await runAudit(state.votes, (state.data && state.data.items) || [], () => new Promise(r => setTimeout(r, 0)),
      { th: state.model && state.model.thresholds, blind: blindStats(state.blind, state.lam), lam: state.lam, mids: state.midVotes, repeats: state.repeats });
    ui.setStatus('audit kész');
  } catch (_) { state.auditText = 'Az audit hibára futott.'; ui.setStatus('audit hiba'); }
  auditBusy = false;
  renderPanels();
}

function blindView() {
  const b = state.blind, it = nextItem(b);
  return { open: state.blindOpen, total: b ? b.items.length : 0, answered: answeredCount(b), title: it ? it.title : '',
    onStart: () => {
      if (!state.blind) {
        const items = pickSample(state.votes, 100, Date.now(), 24, 5, null, state.langs);
        if (items.length < 20) { ui.setStatus('kevés (24 óránál régebbi) szavazat a vak újracímkézéshez'); return; }
        state.blind = { created: Date.now(), items, answers: {} };
        saveBlind(state.blind, state.voter);
      }
      state.blindOpen = true; renderPanels();
    },
    onNew: () => {
      const prev = state.blind;
      const items = pickSample(state.votes, 100, Date.now(), 24, (Date.now() % 9973) + 1, new Set(prev ? prev.items.map(i => i.id) : []), state.langs);
      if (items.length < 20) { ui.setStatus('kevés új, 24 óránál régebbi magyar szavazat az új mintához'); return; }
      try { if (prev) localStorage.setItem(vkey('mnt-blind-prev', state.voter), JSON.stringify(prev)); } catch (_) {}
      state.blind = { created: Date.now(), items, answers: {} };
      saveBlind(state.blind, state.voter); state.blindOpen = true; renderPanels();
    },
    onAnswer: k => { const cur = nextItem(state.blind); if (!cur) return; state.blind.answers[cur.id] = k; saveBlind(state.blind, state.voter); renderPanels(); },
    onClose: () => { state.blindOpen = false; renderPanels(); },
  };
}

function copyAudit() {
  const done = ok => ui.setStatus(ok ? 'audit a vágólapon' : 'a másolás nem sikerült');
  try { navigator.clipboard.writeText(state.auditText || '').then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

function exportDiag() {
  const txt = buildDiag({ data: state.data, model: state.model, rows: state.rows, votes: state.votes, cal: state.cal, lam: state.lam, aiBase: state.aiBase, regionLabel, lastBackup: getBackup(), cloudOn: !!(state.cloud.repo && state.cloud.token), cloudLast: state.cloud.last || 0, cloudErr: state.cloud.err || '', now: Date.now() });
  const done = ok => ui.setStatus(ok ? 'diagnosztika a vágólapon' : 'a másolás nem sikerült');
  try { navigator.clipboard.writeText(txt).then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

function render() {
  recompute();
  const regions = state.model ? state.model.regions : [];
  const th = state.model ? state.model.thresholds : { low: 0.1, high: 0.25 };
  const votes = new Map(state.votes.map(v => [v.id, v.vote]));
  const fe = new FilterEngine(state.rows);
  const rows = fe.getFiltered({ region: state.region, maxAtm: state.maxAtm >= cap() ? Infinity : state.maxAtm, type: state.type, votes });

  ui.renderKpis(fe.getStats(rows), state.data);
  renderHealthBar();
  ui.renderChips(ui.$('filters'), regions, state.region, r => {
    state.region = r.code;
    if (r.center) state.globe.focus(r.center[0], r.center[1]);
    emit('filter');
  });

  rows.sort(state.sort === 'noise'
    ? (a, b) => b.atm - a.atm
    : (a, b) => (b.published || '').localeCompare(a.published || ''));
  const votes2 = new Map(state.votes.filter(v => v.vote2).map(v => [v.id, v.vote2]));
  ui.renderList(ui.$('list'), rows, { th, votes, votes2, regionLabel, onVote: vote, onVote2: vote2, onOpen: markOpen, explain,
    blindVote: state.blindVote, showSource: state.showSource, revealed: state.revealed, opened: state.opened, langOk, langOf,
    onReveal: id => { state.revealed.add(id); render(); } });
  ui.$('empty').hidden = rows.length > 0;
  ui.$('sortBtn').textContent = 'Rendezés: ' + (state.sort === 'time' ? 'idő' : 'zaj');
  ui.$('atmVal').textContent = state.maxAtm >= cap() ? 'nincs korlát' : '≤ ' + fmtAtm(state.maxAtm, 2);
  ui.$('thInfo').textContent = state.model ? `sárga ≥ ${fmtAtm(th.low, 2)} · piros ≥ ${fmtAtm(th.high, 2)}` : '';

  state.globe.setThresholds(th);
  state.globe.setPoints(rows.filter(r => r.lat !== undefined).slice(0, 800)
    .map(r => ({ id: r.id, lat: r.lat, lng: r.lng, atm: r.atm, size: Math.min(r.atm / atmRef(), 1) * 0.55 })));

  const secs = state.dwell.map(x => x.secs);
  const avg = secs.length ? Math.round(secs.reduce((a, b) => a + b, 0) / secs.length) : 0;
  ui.$('personal').textContent = state.votes.length || secs.length
    ? `${state.votes.length} szavazat · ${secs.length} olvasás · átl. ${avg} s` : '';

  renderPanels();
}

function renderPanels() {
  if (ui.$('aiBox').open) {
    const top = state.learner.boot ? state.learner.topWords(state.rows.slice(0, 600).map(r => r.title), 8) : null;
    ui.renderAi(ui.$('aiBody'), {
      votes: state.votes.length, steps: state.learner.steps, lambda: state.lam, boot: state.learner.boot, top,
      cal: state.cal, calibrated: !!(state.cal && state.cal.usable),
      suggestion: state.suggestion, links: githubLinks(location),
    }, { onExport: exportVotes, onDiag: exportDiag, onAudit: runAuditUi, onAuditCopy: copyAudit, auditText: state.auditText, blind: blindView(), backup: backupInfo(), onQuick: openQuick,
    quickInfo: (() => { const p = quickProgress(state.votes); return `Gyorsszavazás: értékelő sor ${p.eval}/${TARGET.eval} (clickbait ${p.bait}/${TARGET.bait}), tanító sor ${p.train}, közepes ${state.midVotes.length}`; })(),
    blindVote: state.blindVote, showSource: state.showSource, voter: state.voter, voterChosen: voterChosen(),
    langs: LANGS.map(([code, label]) => ({ code, label, on: state.langs.has(code) })),
    onSetVoter: switchVoter,
    onToggleLang: code => { if (state.langs.has(code)) state.langs.delete(code); else state.langs.add(code); try { localStorage.setItem(vkey('mnt-langs', state.voter), JSON.stringify([...state.langs])); } catch (_) {} render(); },
    onToggleBlindVote: () => { state.blindVote = !state.blindVote; lsSetFlag('mnt-blindvote', state.blindVote); render(); },
    onToggleSource: () => { state.showSource = !state.showSource; lsSetFlag('mnt-showsrc', state.showSource); render(); }, onSuggest, onCopySuggestion });
  }
  if (ui.$('insBox').open) ui.renderInsights(ui.$('insBody'), state.data && state.data.insights, regionLabel, state.data && state.data.config);
}

function onSuggest() {
  state.suggestion = state.model ? suggest(state.votes, state.model, ((state.data && state.data.items) || []).map(i => i.title)) : { ready: false, n: 0, nb: 0, nf: 0 };
  renderPanels();
}

function onCopySuggestion() {
  const text = state.suggestion && state.suggestion.text;
  const done = ok => ui.setStatus(ok ? 'a beállítás-részlet a vágólapon' : 'a másolás nem sikerült');
  if (!text) return;
  try { navigator.clipboard.writeText(text).then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

const persistAi = () => vstore.putAi(state.voter, state.learner.exportState());

// ---- Szavazónkénti tárolás ----
// Áttöltés a régi, közös tárolóból: csak másol (a régi adatbázisból és a régi kulcsokból semmi nem törlődik), és újrafuttatva sem ír felül semmit.
async function migrateLegacy() {
  try {
    const meta = await vstore.getMetaStrict('migrated');
    const [old, keys] = await Promise.all([store.getAllStrict('votes'), vstore.keysStrict()]);
    const plan = planMigration(old, new Set(keys), loadVoter(), meta ? meta.ts : 0);
    if (plan.entries.length) await vstore.putEntriesStrict(plan.entries);
    if (!meta) {
      const ai = await store.getStrict('ai', 'state');
      if (ai && !(await vstore.getAiStrict(plan.owner))) await vstore.putAiStrict(plan.owner, ai);
      try { planLocalCopy(k => localStorage.getItem(k), plan.owner).forEach(([k, v]) => localStorage.setItem(k, v)); } catch (_) {}
    }
    await vstore.putMetaStrict('migrated', { ts: Date.now(), first: meta ? meta.first : Date.now(), owner: meta ? meta.owner : plan.owner, copied: (meta ? meta.copied : 0) + plan.entries.length });
    state.migErr = false;
    return plan.entries.length;
  } catch (_) { state.migErr = true; return 0; }
}

// Az aktuális szavazó adatainak betöltése: a memóriában mindig csak az ő szavazatai, ismétlései, kihagyottjai, vak mintája és tanulója van.
async function loadVoterState() {
  const v = state.voter;
  const [all, saved] = await Promise.all([vstore.allVotes(), vstore.getAi(v)]);
  if (v !== state.voter) return;                      // közben megint szavazót váltottak
  const mine = all.filter(r => r.voter === v);
  state.localVoters = localSets(all).map(s => s.voter);
  state.votes = mine.filter(r => r.vote !== 'mid'); state.midVotes = mine.filter(r => r.vote === 'mid');
  state.repeats = loadRepeats(v); state.skipped = loadSkipped(v); state.blind = loadBlind(v);
  state.cloud = loadCloud(v); state.langs = loadLangs(v);
  state.learner = saved ? new Learner(saved) : new Learner();
  state.revealed = new Set(); state.opened = new Set();
  state.pendingRestore = null; state.auditText = ''; state.reconText = ''; state.suggestion = null; state.blindOpen = false;
}

async function switchVoter(v) {
  if (!validVoter(v)) return;
  const changed = v !== state.voter;
  try { localStorage.setItem('mnt-voter', v); } catch (_) {}
  if (changed) {
    await commitPending();
    if (state.quick && !state.quick.ask) { state.quick = null; paintQuick(); }
    state.voter = v;
    await loadVoterState();
    await ensureLearner();
  }
  ui.setStatus(`szavazó: ${v} · ${nAll()} szavazat ezen az eszközön`);
  render(); renderPanels();
}

async function ensureLearner() {
  if (!state.data || !state.data.items || state.learner.boot) return;
  state.learner.bootstrap(state.data.items.map(i => ({ text: i.title, target: i.S0 !== undefined ? i.S0 : i.S })));
  state.votes.forEach(v => { if (v.title && v.queue !== 'eval') state.learner.learnVote(v.title, v.vote === 'bait'); }); // elveszett állapot pótlása
  await persistAi();
}

async function vote(it, kind) {
  const mine = state.votes.find(v => v.id === it.id);
  if (mine && mine.vote === kind) {
    await vstore.delVote(state.voter, it.id);
    state.votes = state.votes.filter(v => v.id !== it.id);
  } else {
    // sRule és sAi: a tanulás ELŐTTI értékek, ezekből mér a kalibráció
    const rec = { id: it.id, domain: it.source_domain, vote: kind, title: it.title, sRule: it.S, sAi: it.sAi,
      S0: it.S0, S: it.Seff, V: it.v, region: it.region, atm: it.atm, ts: Date.now(),
      blind: blindAtVote(state.blindVote, state.revealed.has(it.id), !!mine), srcShown: !!state.showSource, ver: APP_VERSION, lang: langOf(it), voter: state.voter };  // blind: a szavazat a számok és a szín ismerete nélkül született
    await vstore.putVote(rec);
    if (!state.localVoters.includes(state.voter)) state.localVoters = state.localVoters.concat(state.voter).sort();
    state.votes = state.votes.filter(v => v.id !== it.id).concat(rec);
    state.learner.learnVote(it.title, kind === 'bait'); // itt tanul az AI
    await persistAi();
  }
  render();
}

// A cím nyelve (magyar = 'hu'): a szavazó csak ezt tudja megítélni.
function langOf(it) {
  let l = state.langCache.get(it.id);
  if (!l) { l = detectLangCode(it.title, it.source_domain); state.langCache.set(it.id, l); }
  return l;
}
const langOk = it => state.langs.has(langOf(it));

// ---- Mentés és helyreállítás ----
function makeBackupText() {
  let prev = null; try { prev = JSON.parse(localStorage.getItem(vkey('mnt-blind-prev', state.voter)) || 'null'); } catch (_) {}
  return serialize(buildBackup({ app: APP_VERSION, votes: state.votes, mids: state.midVotes, repeats: state.repeats, skipped: state.skipped,
    voter: state.voter, prefs: { blindVote: state.blindVote, showSource: state.showSource, langs: [...state.langs], voter: state.voter }, blind: state.blind, blindPrev: prev }));
}
const nAll = () => state.votes.length + state.midVotes.length;

// Egy másik helyi szavazó mentése a tárolóból (az aktuális szavazóé a memóriából készül: makeBackupText).
function backupTextFor(voter, recs) {
  let prev = null; try { prev = JSON.parse(localStorage.getItem(vkey('mnt-blind-prev', voter)) || 'null'); } catch (_) {}
  return serialize(buildBackup({ app: APP_VERSION, votes: recs.filter(r => r.vote !== 'mid'), mids: recs.filter(r => r.vote === 'mid'), repeats: loadRepeats(voter), skipped: loadSkipped(voter),
    voter, prefs: { blindVote: state.blindVote, showSource: state.showSource, langs: [...loadLangs(voter)], voter }, blind: loadBlind(voter), blindPrev: prev }));
}

// Minden helyi szavazó mentése egy szövegben: szavazónként egy önálló mentés, soronként egy.
// Így az Egyeztetés közvetlenül beolvassa, a Helyreállítás pedig mindig csak az aktuális szavazó sorát veszi ki belőle.
async function allBackupText() {
  const sets = localSets(await vstore.allVotes());
  const texts = sets.map(s => (s.voter === state.voter ? makeBackupText() : backupTextFor(s.voter, s.votes)));
  return { text: texts.join('\n'), voters: sets.map(s => s.voter), n: sets.reduce((a, s) => a + s.votes.length, 0) };
}

function copyText(text, mark, okMsg) {
  const done = ok => { if (ok) { mark(); renderHealthBar(); renderPanels(); } ui.setStatus(ok ? okMsg : 'a másolás nem sikerült'); };
  try { navigator.clipboard.writeText(text).then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

async function shareText(text, name, mark, copyMsg) {
  const sent = msg => { mark(); renderHealthBar(); renderPanels(); ui.setStatus(msg); };
  try {
    const file = new File([text], name, { type: 'text/plain' });   // a böngésző a .json-t nem engedi megosztani, a .txt-t igen
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: name });
      sent('mentés elküldve a megosztón át'); return;
    }
  } catch (e) { if (e && e.name === 'AbortError') { ui.setStatus('mentés megszakítva'); return; } }
  try {   // tartalék: letöltés
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = name; a.click();
    sent('mentés letöltve'); return;
  } catch (_) {}
  copyText(text, mark, copyMsg);
}

const today = () => new Date().toISOString().slice(0, 10);
const copyBackup = () => copyText(makeBackupText(), setBackup, `teljes mentés a vágólapon (${state.voter} szavazó, ${nAll()} szavazat)`);
const shareBackup = () => shareText(makeBackupText(), `media-noise-szavazatok-${state.voter}-${today()}.txt`, setBackup, `teljes mentés a vágólapon (${state.voter} szavazó, ${nAll()} szavazat)`);

async function exportAll(share) {
  const a = await allBackupText();
  if (!a.n) { ui.setStatus('ezen az eszközön még nincs szavazat'); return; }
  const mark = () => a.voters.forEach(v => setBackup(v)), msg = `minden szavazó mentése a vágólapon (${a.voters.join(', ')}; ${a.n} szavazat)`;
  if (share) await shareText(a.text, `media-noise-szavazatok-mind-${today()}.txt`, mark, msg);
  else copyText(a.text, mark, msg);
}

const cloudCfg = path => ({ repo: state.cloud.repo, token: state.cloud.token, path: path || cloudPath(state.voter) });   // szavazónként külön fájl: nem írják felül egymás mentését
function cloudFail(msg) { state.cloud = Object.assign({}, state.cloud, { err: msg }); saveCloud(state.cloud); ui.setStatus('felhő-mentés: ' + msg); renderHealthBar(); renderPanels(); }

async function cloudSave(repo, token) {
  repo = String(repo || '').trim(); token = String(token || '').trim();
  if (!validRepoRef(repo)) { ui.setStatus('a tároló neve „felhasználó/tároló” alakú legyen'); return; }
  if (token.length < 20) { ui.setStatus('a kulcs túl rövid'); return; }
  const chk = await ghRepoPrivate({ repo, token });
  if (!chk.ok) { ui.setStatus('felhő-mentés: ' + chk.error); return; }
  state.cloud = { repo, token, last: 0, count: 0, err: '' }; saveCloud(state.cloud);
  ui.setStatus('felhő-mentés beállítva, az első mentés indul…');
  await cloudBackup(true);
}

async function cloudBackup(manual) {
  const c = state.cloud;
  if (!c || !c.repo || !c.token || state.cloudBusy) return;
  state.cloudBusy = true;
  try {
    const priv = await ghRepoPrivate(cloudCfg());
    if (!priv.ok) { cloudFail(priv.error); return; }
    const r = await ghPut(cloudCfg(), makeBackupText(), `Mentés ${new Date().toISOString().slice(0, 16)}Z · ${nAll()} szavazat`);
    if (!r.ok) { cloudFail(r.error); return; }
    state.cloud = Object.assign({}, c, { last: Date.now(), count: nAll(), err: '' }); saveCloud(state.cloud);
    setBackup(); renderHealthBar(); renderPanels();
    ui.setStatus(`felhő-mentés kész (${nAll()} szavazat)`);
  } finally { state.cloudBusy = false; }
}
function maybeAutoBackup() { if (shouldAutoBackup(state.cloud, nAll())) cloudBackup(false); }

async function cloudRestore() {
  const c = state.cloud; if (!c || !c.repo || !c.token) return;
  ui.setStatus('letöltés a GitHubról…');
  let r = await ghGet(cloudCfg());
  if (!r.ok && r.status === 404 && state.voter === LEGACY_VOTER) r = await ghGet(cloudCfg(LEGACY_CLOUD_PATH));   // a régi, közös nevű mentés az akkori egyetlen szavazóé
  if (!r.ok) { ui.setStatus('felhő: ' + r.error); return; }
  previewRestore(r.text);
}

function previewRestore(text) {
  // a szövegben több mentés is lehet (soronként egy: „minden szavazó mentése”); csak az aktuális szavazóé kerül ide, más szavazóé soha
  const parts = splitBackupTexts(text);
  const parsed = (parts.length ? parts : [text]).map(parseBackup);
  const good = parsed.filter(x => x.ok);
  if (!good.length) { ui.setStatus('helyreállítás: ' + parsed[0].error); return; }
  const pk = pickBackupFor(good, state.voter);
  if (!pk.ok) { ui.setStatus(pk.error); return; }
  const p = pk.p, sc = pk.sc;
  p.data = sc.data;
  const plan = planRestore(state.votes, state.midVotes, p.data);
  const total = p.data.votes.length + p.data.mids.length;
  state.pendingRestore = { parsed: p.data, plan,
    summary: `A mentésben ${total} szavazat van${p.data.created ? ' (' + p.data.created.slice(0, 16).replace('T', ' ') + ')' : ''}${p.stats.invalid ? `, ${p.stats.invalid} sérült kihagyva` : ''}${sc.others ? `, ${sc.others} más szavazóé kihagyva` : ''}${pk.total > 1 ? `; a fájl ${pk.total} mentéséből a(z) ${state.voter} szavazóé` : ''}. Új: ${plan.stats.added} · frissülne: ${plan.stats.updated} · változatlan: ${plan.stats.same}. Az eszközön most ${nAll()} szavazat van.` };
  state.bkOpen = true; renderPanels();
}

async function confirmRestore() {
  const R = state.pendingRestore; if (!R) return;
  ui.setStatus('helyreállítás folyamatban…');
  await vstore.putVotes(R.plan.write);
  if (R.plan.write.length && !state.localVoters.includes(state.voter)) state.localVoters = state.localVoters.concat(state.voter).sort();
  state.votes = R.plan.votes; state.midVotes = R.plan.mids;
  const d = R.parsed;
  const rk = new Set(state.repeats.map(r => r.id + '|' + r.ts)); d.repeats.forEach(r => { if (!rk.has(r.id + '|' + r.ts)) state.repeats.push(r); }); saveRepeats(state.repeats, state.voter);
  d.skipped.forEach(x => state.skipped.add(x)); saveSkipped(state.skipped, state.voter);
  if (!state.blind && d.blind) { state.blind = d.blind; saveBlind(state.blind, state.voter); }
  const setIf = (key, prop, val) => { try { if (typeof val === 'boolean' && localStorage.getItem(key) === null) { state[prop] = val; lsSetFlag(key, val); } } catch (_) {} };
  setIf('mnt-blindvote', 'blindVote', d.prefs.blindVote); setIf('mnt-showsrc', 'showSource', d.prefs.showSource);
  try { if (localStorage.getItem(vkey('mnt-langs', state.voter)) === null && Array.isArray(d.prefs.langs) && d.prefs.langs.length) { state.langs = new Set(d.prefs.langs); localStorage.setItem(vkey('mnt-langs', state.voter), JSON.stringify(d.prefs.langs)); } } catch (_) {}
  state.learner = new Learner(); await ensureLearner();    // a tanuló a visszaállított szavazatokból újraépül
  state.pendingRestore = null; setBackup(); render(); renderPanels();
  ui.setStatus(`helyreállítva: ${R.plan.stats.added} új, ${R.plan.stats.updated} frissített szavazat`);
}

// Egyeztetés a másik szavazóval: csak olvas és kiír, a tárolóba nem ír.
async function runRecon(text) {
  const parts = splitBackupTexts(text);
  // az eszközön lévő összes szavazó (beillesztés nélkül), az aktuális szavazó az első
  const local = localSets(await vstore.allVotes()).filter(s => s.voter !== state.voter);
  const sets = [{ voter: state.voter, votes: state.votes.concat(state.midVotes) }].concat(local);
  if (!parts.length && sets.length < 2) { ui.setStatus('egyeztetés: illeszd be legalább egy másik szavazó mentését (ezen az eszközön nincs másik szavazó)'); return; }
  let bad = 0;
  parts.forEach((t, i) => { const p = parseBackup(t); if (!p.ok) { bad++; return; } sets.push({ voter: p.data.voter || ('X' + (i + 1)), votes: p.data.votes.concat(p.data.mids) }); });
  if (sets.length < 2) { ui.setStatus('egyeztetés: a beillesztett mentés(ek) nem olvashatók'); return; }
  state.reconText = formatReconMany(reconcileMany(sets, state.lam));
  state.bkOpen = true; renderPanels();
  if (bad) ui.setStatus(`egyeztetés kész, de ${bad} mentés nem volt olvasható`);
}
function copyRecon() {
  const done = ok => ui.setStatus(ok ? 'az egyeztetés eredménye a vágólapon' : 'a másolás nem sikerült');
  try { navigator.clipboard.writeText(state.reconText || '').then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

function backupInfo() {
  const c = state.cloud || {}, on = !!(c.repo && c.token), last = getBackup();
  const ago = ms => (ms ? (Date.now() - ms < 36e5 ? 'az elmúlt órában' : Date.now() - ms < 864e5 ? Math.floor((Date.now() - ms) / 36e5) + ' órája' : Math.floor((Date.now() - ms) / 864e5) + ' napja') : 'még nem');
  return {
    open: state.bkOpen, onToggle: o => { state.bkOpen = o; },
    voters: state.localVoters, onShareAll: () => exportAll(true), onCopyAll: () => exportAll(false),
    lines: [`${state.voter} szavazó az eszközön: ${state.votes.length} szavazat + ${state.midVotes.length} közepes.${state.localVoters.length > 1 ? ` Szavazók ezen az eszközön: ${state.localVoters.join(', ')}.` : ''} Utolsó mentés (bármely módon): ${ago(last)}.`, on ? `Felhő-mentés: ${c.err ? 'HIBA – ' + c.err : 'utoljára ' + ago(c.last) + ' (' + (c.count || 0) + ' szavazat)'}.` : 'Felhő-mentés: nincs beállítva.'],
    cloud: { configured: on, repo: c.repo || '', masked: maskToken(c.token) },
    pending: state.pendingRestore ? { summary: state.pendingRestore.summary } : null,
    onShare: shareBackup, onCopy: copyBackup, onRestorePreview: previewRestore, onRestoreConfirm: confirmRestore,
    onRestoreCancel: () => { state.pendingRestore = null; renderPanels(); },
    reconText: state.reconText, onRecon: runRecon, onReconCopy: copyRecon,
    onCloudSave: cloudSave, onCloudNow: () => cloudBackup(true), onCloudRestore: cloudRestore,
    onCloudForget: () => { state.cloud = {}; saveCloud({}); ui.setStatus('a kulcs törölve erről az eszközről'); renderHealthBar(); renderPanels(); },
  };
}

// ---- Gyorsszavazó mód ----
function quickView() {
  const Q = state.quick;
  if (Q && Q.ask) return { open: true, ask: true, voter: state.voter, voters: VOTERS, onPick: startQuick, onClose: closeQuick };
  return { open: !!Q, voter: state.voter, title: Q && Q.cur ? Q.cur.it.title : '', p: quickProgress(state.votes), target: TARGET,
    mids: state.midVotes.filter(v => v.blind === true).length, canUndo: !!(Q && Q.last),
    onAnswer: quickAnswer, onUndo: quickUndo, onClose: closeQuick };
}
const paintQuick = () => { const r = ui.$('quick'); if (r) ui.renderQuick(r, quickView()); };
const nextQuick = () => pickRepeat(state.votes, state.repeats, Date.now()) || takeNext(state.quick.q);

// Indításkor mindig megkérdezi, ki szavaz (egy koppintás): közös eszközön így nem kerül a szavazat a másik szavazó neve alá.
function openQuick() {
  state.quick = { ask: true };
  paintQuick();
}

async function startQuick(v) {
  if (!validVoter(v) || !state.quick || !state.quick.ask) return;
  await switchVoter(v);
  const voted = new Set(state.votes.map(v => v.id).concat(state.midVotes.map(v => v.id)));
  const pools = buildPools(state.rows, { voted, skipped: state.skipped, langOk });
  state.quick = { q: { eval: pools.eval, train: pools.train, shared: pools.shared, step: 0, used: new Set() }, cur: null, last: null, pending: null };
  state.quick.cur = nextQuick();
  paintQuick();
}

// A tanító sor szavazatából a tanuló a KÖVETKEZŐ válasznál (vagy kilépéskor) tanul, így az utolsó válasz még visszavonható.
async function commitPending() {
  const Q = state.quick;
  if (!Q || !Q.pending) return;
  state.learner.learnVote(Q.pending.title, Q.pending.bait);
  Q.pending = null;
  await persistAi();
}

async function quickAnswer(kind) {
  const Q = state.quick;
  if (!Q || !Q.cur) return;
  await commitPending();
  const cur = Q.cur, entry = { cur, kind };
  if (cur.rep) {
    if (kind === 'fact' || kind === 'bait') { state.repeats.push({ id: cur.it.id, first: cur.first, second: kind, ts: Date.now() }); saveRepeats(state.repeats, state.voter); entry.repeat = true; }
  } else if (kind === 'skip') {
    state.skipped.add(cur.it.id); saveSkipped(state.skipped, state.voter); entry.skipped = true;
  } else {
    const it = cur.it;
    const rec = { id: it.id, domain: it.source_domain, vote: kind, title: it.title, sRule: it.S, sAi: it.sAi, S0: it.S0, S: it.Seff, V: it.v,
      region: it.region, atm: it.atm, ts: Date.now(), blind: true, srcShown: false, ver: APP_VERSION, lang: langOf(it), queue: cur.queue, quick: true, voter: state.voter, shared: cur.shared ? true : undefined };
    await vstore.putVote(rec);
    if (!state.localVoters.includes(state.voter)) state.localVoters = state.localVoters.concat(state.voter).sort();
    if (kind === 'mid') state.midVotes = state.midVotes.filter(v => v.id !== it.id).concat(rec);
    else state.votes = state.votes.filter(v => v.id !== it.id).concat(rec);
    if (cur.queue === 'train' && kind !== 'mid') Q.pending = { title: it.title, bait: kind === 'bait' };
    entry.rec = rec;
  }
  Q.last = entry;
  Q.cur = nextQuick();
  paintQuick();
}

async function quickUndo() {
  const Q = state.quick;
  if (!Q || !Q.last) return;
  const e = Q.last;
  if (e.rec) {
    await vstore.delVote(state.voter, e.rec.id);
    state.votes = state.votes.filter(v => v.id !== e.rec.id);
    state.midVotes = state.midVotes.filter(v => v.id !== e.rec.id);
    Q.pending = null;           // a még nem tanított szavazat nem tanít
  }
  if (e.skipped) { state.skipped.delete(e.cur.it.id); saveSkipped(state.skipped, state.voter); }
  if (e.repeat) { state.repeats = state.repeats.slice(0, -1); saveRepeats(state.repeats, state.voter); }
  // a már kihúzott következő hír visszakerül a sora elejére, így nem vész el, és a váltakozás ritmusa sem tolódik el
  if (Q.cur && !Q.cur.rep) { Q.q[Q.cur.queue].unshift(Q.cur.it); Q.q.used.delete(Q.cur.it.id); Q.q.step--; }
  Q.cur = e.cur; Q.last = null;
  paintQuick();
}

async function closeQuick() {
  await commitPending();
  state.quick = null;
  paintQuick();
  render();
  maybeAutoBackup();
}

function onQuickKey(e) {
  if (!state.quick) return;
  const k = String(e.key || '').toLowerCase();
  const map = { n: 'fact', f: 'fact', m: 'mid', h: 'bait', c: 'bait', ' ': 'skip' };
  if (map[k]) { if (e.preventDefault) e.preventDefault(); quickAnswer(map[k]); }
  else if (k === 'z') quickUndo();
  else if (k === 'escape') closeQuick();
}

// Második (elolvasás utáni) ítélet: csak eltárolódik, a tanulót nem módosítja.
async function vote2(it, kind) {
  const rec = state.votes.find(v => v.id === it.id);
  if (!rec) return;
  const next = rec.vote2 === kind ? undefined : kind;
  const upd = Object.assign({}, rec, { vote2: next, ts2: next ? Date.now() : undefined });
  await vstore.putVote(upd);
  state.votes = state.votes.filter(v => v.id !== it.id).concat(upd);
  render();
}

function markOpen(it) {
  state.opened.add(it.id);
  try { sessionStorage.setItem('mnt-open', JSON.stringify({ id: it.id, domain: it.source_domain, title: it.title, t: Date.now() })); } catch (_) {}
}

async function collectDwell() {
  let p;
  try { p = JSON.parse(sessionStorage.getItem('mnt-open') || 'null'); sessionStorage.removeItem('mnt-open'); } catch (_) { return; }
  if (!p) return;
  const secs = Math.round((Date.now() - p.t) / 1000);
  if (secs < 2 || secs > 3600) return;
  const rec = { id: p.id, domain: p.domain, secs, ts: Date.now() };
  await store.add('dwell', rec);
  state.dwell.push(rec);
  if (p.title && state.learner.boot && (secs < 10 || secs >= 45)) {
    state.learner.learnWeak(p.title, secs < 10 ? 0.65 : 0.35); // gyenge jel
    await persistAi();
  }
  render();
}

// Glóbusz-váltás: a 2D (Canvas) mindig kéznél van; a 3D (Three.js) háttérben töltődik, hiba esetén visszaesik 2D-re.
const pickHandler = p => ui.showPick(ui.$('pick'), p ? state.rows.find(r => r.id === p.id) : null);

function activateGlobe(g) {
  const old = state.globe;
  if (old && old !== g) {
    old.stop();
    Object.assign(g.rot, old.rot);
    g.zoom = old.zoom; g.full = old.full; g.target = null;
  }
  if (g._touchAction) g._touchAction();
  state.g2d.c.style.display = g.is3d ? 'none' : '';
  if (state.g3d) state.g3d.c.style.display = g.is3d ? '' : 'none';
  state.globe = g;
  g.start();
  ui.$('gMode').textContent = g.is3d ? '3D' : '2D';
  render();
}

async function enable3D() {
  if (!state.g3d) {
    let c3 = null;
    try {
      c3 = document.createElement('canvas');
      c3.className = 'globecv'; c3.id = 'globe3d';
      c3.setAttribute('aria-label', 'Hírek glóbusza (3D)');
      c3.style.display = 'none';
      state.g2d.c.parentNode.append(c3);
      state.g3d = await createGlobe3D(c3, {
        th: state.model ? state.model.thresholds : undefined,
        onPick: pickHandler,
        onError: () => { activateGlobe(state.g2d); ui.setStatus('3D hiba – 2D nézet'); },
      });
    } catch (_) {
      if (c3 && c3.remove) c3.remove();
      ui.setStatus('3D nem érhető el – 2D nézet');
      return false;
    }
  }
  activateGlobe(state.g3d);
  return true;
}

const shareCtx = () => ({ model: state.model, learner: state.learner, lam: state.lam, aiBase: state.aiBase, net: state.net });

async function init() {
  state.g2d = new Globe(ui.$('globe'), { onPick: pickHandler });
  state.globe = state.g2d;
  state.globe.start();

  ui.$('gZoomIn').addEventListener('click', () => state.globe.zoomBy(1.5));
  ui.$('gZoomOut').addEventListener('click', () => state.globe.zoomBy(1 / 1.5));
  ui.$('gFull').addEventListener('click', () => {
    const wrap = ui.$('globeWrap');
    const full = !wrap.classList.contains('full');
    wrap.classList.toggle('full', full);
    if (document.body) document.body.style.overflow = full ? 'hidden' : '';
    ui.$('gFull').textContent = full ? '✕' : '⤢';
    state.globe.setFull(full);
  });
  ui.$('gMode').addEventListener('click', async () => {
    if (state.globe.is3d) { setPref('2d'); activateGlobe(state.g2d); return; }
    setPref('3d');
    ui.setStatus('3D betöltése…');
    if (await enable3D()) ui.setStatus('3D nézet');
  });
  ui.$('sortBtn').addEventListener('click', () => { state.sort = state.sort === 'time' ? 'noise' : 'time'; emit('filter'); });
  ui.$('typeSel').addEventListener('change', e => { state.type = e.target.value; emit('filter'); });
  ui.$('atmRange').addEventListener('input', e => { state.maxAtm = Number(e.target.value); emit('filter'); });
  ui.$('aiBox').addEventListener('toggle', renderPanels);
  ui.$('insBox').addEventListener('toggle', renderPanels);
  ui.$('analyzeBtn').addEventListener('click', () => analyze(shareCtx));
  ui.$('closeBtn').addEventListener('click', () => ui.$('shareModal').close());
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') collectDwell(); });
  on('filter', render);

  document.addEventListener('keydown', onQuickKey);
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  // A hálózati letöltés azonnal indul; a tárolók (időkorláttal) párhuzamosan töltődnek, így egy zárolt adatbázis sem állítja meg a felületet.
  const fresh = fetchJson().then(d => d, () => null);
  const [dwell, cached] = await Promise.all([store.getAll('dwell'), store.get('cache', 'atm'), migrateLegacy()]);
  await loadVoterState();
  if (getPref() === '3d') enable3D();   // háttérben; hiba esetén marad a 2D
  state.dwell = dwell;
  if (cached) { setData(cached); ui.setStatus('mentett adat'); }
  render();

  const share = parseShare();
  if (share) openShare(share, shareCtx);

  const d = await fresh;
  if (d) {
    setData(d);
    store.put('cache', 'atm', d);
    ui.setStatus('friss adat');
  } else {
    ui.setStatus(state.data ? 'offline – mentett adat' : 'nincs adat');
  }
  await ensureLearner();
  render();
  maybeAutoBackup();
  if (share && ui.$('shareModal').open && !ui.$('shareResult').childNodes.length) analyze(shareCtx);
}

if (typeof document !== 'undefined') init();
