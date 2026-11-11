// Fő vezérlő: állapot, eseménybusz, indítás.
import { buildModel, clamp, atmValue, buildNetMap, adjustV, tierOf, ruleParts, fmtAtm, atmRef, atmParts, scoringMode, aiBaseline } from './modules/model.js';
import { Learner } from './modules/learner.js';
import { calibrate, lambdaFinal } from './modules/calibration.js';
import { FilterEngine } from './modules/filterEngine.js';
import { Globe } from './modules/globe.js';
import { createGlobe3D } from './modules/globe3d.js';
import { store } from './modules/store.js';
import { fetchJson } from './modules/dataLoader.js';
import * as ui from './modules/uiRenderer.js';
import { parseShare, openShare, analyze } from './modules/share.js';
import { suggest, githubLinks } from './modules/suggest.js';
import { buildDiag } from './modules/diag.js';
import { runAudit } from './modules/audit.js';
import { loadBlind, saveBlind, pickSample, nextItem, answeredCount, blindStats } from './modules/blind.js';

const bus = new EventTarget();
const on = (n, f) => bus.addEventListener(n, f);
const emit = n => bus.dispatchEvent(new Event(n));

const cap = () => (state.model && state.model.atm_cap !== undefined ? state.model.atm_cap : 0.6); // a csúszka teteje = nincs korlát

const GLOBE_PREF = 'mnt-globe';
const lsFlag = (k, d) => { try { const v = localStorage.getItem(k); return v === '1' ? true : v === '0' ? false : d; } catch (_) { return d; } };
const lsSetFlag = (k, v) => { try { localStorage.setItem(k, v ? '1' : '0'); } catch (_) {} };
const BACKUP_KEY = 'mnt-backup';
const getBackup = () => { try { return Number(localStorage.getItem(BACKUP_KEY)) || 0; } catch (_) { return 0; } };
const setBackup = () => { try { localStorage.setItem(BACKUP_KEY, String(Date.now())); } catch (_) {} };
const getPref = () => { try { return localStorage.getItem(GLOBE_PREF) || '3d'; } catch (_) { return '3d'; } };
const setPref = v => { try { localStorage.setItem(GLOBE_PREF, v); } catch (_) {} };

const state = {
  g2d: null, g3d: null, suggestion: null,
  data: null, model: null, votes: [], dwell: [], learner: new Learner(), cal: null,
  region: 'ALL', sort: 'time', maxAtm: 0.6, sliderCap: null, type: 'all',
  rows: [], net: new Map(), lam: 0.2, aiBase: 0, blind: null, blindOpen: false, auditText: '', blindVote: lsFlag('mnt-blindvote', true), showSource: lsFlag('mnt-showsrc', false), revealed: new Set(), opened: new Set(), globe: null,
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
  const data = JSON.stringify(state.votes.map(v => ({
    id: v.id, domain: v.domain, vote: v.vote, title: v.title, sRule: v.sRule, sAi: v.sAi,
    S0: v.S0, S: v.S, V: v.V, region: v.region, atm: v.atm,
  })), null, 1);
  const done = ok => { if (ok) { setBackup(); renderHealthBar(); } ui.setStatus(ok ? `${state.votes.length} szavazat a vágólapon (mentés rögzítve)` : 'a másolás nem sikerült'); };
  try { navigator.clipboard.writeText(data).then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

// Egészség-sáv: a szerver problémái + a szavazatmentés emlékeztetője (a szavazatok csak a telefonon vannak).
function renderHealthBar() {
  const list = ((state.data && state.data.health) || []).map(h => ({ text: h.text }));
  const nv = state.votes.length, last = getBackup();
  const days = last ? (Date.now() - last) / 86400000 : null;
  if (nv >= 100 && (days === null || days > 14)) {
    list.push({ soft: true, text: `Szavazatmentés: ${days === null ? 'még nem mentetted' : Math.floor(days) + ' napja mentetted'} (${nv} szavazat csak ezen a telefonon van). Az Öntanuló AI panelben másold ki a szavazatokat.` });
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
      { th: state.model && state.model.thresholds, blind: blindStats(state.blind, state.lam), lam: state.lam });
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
        const items = pickSample(state.votes);
        if (items.length < 20) { ui.setStatus('kevés (24 óránál régebbi) szavazat a vak újracímkézéshez'); return; }
        state.blind = { created: Date.now(), items, answers: {} };
        saveBlind(state.blind);
      }
      state.blindOpen = true; renderPanels();
    },
    onAnswer: k => { const cur = nextItem(state.blind); if (!cur) return; state.blind.answers[cur.id] = k; saveBlind(state.blind); renderPanels(); },
    onClose: () => { state.blindOpen = false; renderPanels(); },
  };
}

function copyAudit() {
  const done = ok => ui.setStatus(ok ? 'audit a vágólapon' : 'a másolás nem sikerült');
  try { navigator.clipboard.writeText(state.auditText || '').then(() => done(true), () => done(false)); } catch (_) { done(false); }
}

function exportDiag() {
  const txt = buildDiag({ data: state.data, model: state.model, rows: state.rows, votes: state.votes, cal: state.cal, lam: state.lam, aiBase: state.aiBase, regionLabel, lastBackup: getBackup(), now: Date.now() });
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
    blindVote: state.blindVote, showSource: state.showSource, revealed: state.revealed, opened: state.opened,
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
    }, { onExport: exportVotes, onDiag: exportDiag, onAudit: runAuditUi, onAuditCopy: copyAudit, auditText: state.auditText, blind: blindView(),
    blindVote: state.blindVote, showSource: state.showSource,
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

const persistAi = () => store.put('ai', 'state', state.learner.exportState());

async function ensureLearner() {
  if (!state.data || !state.data.items || state.learner.boot) return;
  state.learner.bootstrap(state.data.items.map(i => ({ text: i.title, target: i.S0 !== undefined ? i.S0 : i.S })));
  state.votes.forEach(v => { if (v.title) state.learner.learnVote(v.title, v.vote === 'bait'); }); // elveszett állapot pótlása
  await persistAi();
}

async function vote(it, kind) {
  const mine = state.votes.find(v => v.id === it.id);
  if (mine && mine.vote === kind) {
    await store.del('votes', it.id);
    state.votes = state.votes.filter(v => v.id !== it.id);
  } else {
    // sRule és sAi: a tanulás ELŐTTI értékek, ezekből mér a kalibráció
    const rec = { id: it.id, domain: it.source_domain, vote: kind, title: it.title, sRule: it.S, sAi: it.sAi,
      S0: it.S0, S: it.Seff, V: it.v, region: it.region, atm: it.atm, ts: Date.now(),
      blind: !!state.blindVote && !state.revealed.has(it.id), srcShown: !!state.showSource };  // blind: a szavazat a számok és a szín ismerete nélkül született
    await store.put('votes', null, rec);
    state.votes = state.votes.filter(v => v.id !== it.id).concat(rec);
    state.learner.learnVote(it.title, kind === 'bait'); // itt tanul az AI
    await persistAi();
  }
  render();
}

// Második (elolvasás utáni) ítélet: csak eltárolódik, a tanulót nem módosítja.
async function vote2(it, kind) {
  const rec = state.votes.find(v => v.id === it.id);
  if (!rec) return;
  const next = rec.vote2 === kind ? undefined : kind;
  const upd = Object.assign({}, rec, { vote2: next, ts2: next ? Date.now() : undefined });
  await store.put('votes', null, upd);
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

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  // A hálózati letöltés azonnal indul; a tárolók (időkorláttal) párhuzamosan töltődnek, így egy zárolt adatbázis sem állítja meg a felületet.
  const fresh = fetchJson().then(d => d, () => null);
  const [votes, dwell, saved, cached] = await Promise.all([
    store.getAll('votes'), store.getAll('dwell'), store.get('ai', 'state'), store.get('cache', 'atm'),
  ]);
  if (getPref() === '3d') enable3D();   // háttérben; hiba esetén marad a 2D
  state.votes = votes; state.dwell = dwell; state.blind = loadBlind();
  if (saved) state.learner = new Learner(saved);
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
  if (share && ui.$('shareModal').open && !ui.$('shareResult').childNodes.length) analyze(shareCtx);
}

if (typeof document !== 'undefined') init();
