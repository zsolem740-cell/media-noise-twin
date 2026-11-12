// Az előnézet saját kerete: elkülönítés, vak mód őrök, fülek, állapotsáv. Az app.js és a modulok (a megjelenítő és a glóbusz kivételével) változatlanok.

// 1) Elkülönítés: az éles alkalmazás eredetén (github.io) az előnézet nem indul el, így nem érhet a tesztelők tárolójához.
if (/(^|\.)github\.io$/.test(location.hostname) || /^\/?media-noise-twin\//.test(location.pathname)) {
  document.body.textContent = 'Az előnézet külön eredeten fut. Ezen a címen nem indul el, hogy ne érje el a tesztelők adatait.';
  throw new Error('előnézet: az éles eredeten nem fut');
}

const $ = id => document.getElementById(id);
const blindOn = () => { try { return localStorage.getItem('mnt-blindvote') !== '0'; } catch (_) { return true; } };
const lsGet = k => { try { return localStorage.getItem(k); } catch (_) { return null; } };

// 2) A glóbusz vak módban egyszínű és egyforma méretű (a glóbusz-modulok előnézeti másolata ezeket a kampókat hívja).
Object.defineProperty(window, '__mntNeutral', { get: blindOn });
window.__mntPts = pts => (blindOn() ? pts.map(p => ({ id: p.id, lat: p.lat, lng: p.lng, atm: 0, size: 0.2 })) : pts);

// 3) A vak mód váltását a localStorage-ból követjük (az app.js onnan olvassa).
const origSet = Storage.prototype.setItem;
Storage.prototype.setItem = function (k, v) {
  origSet.call(this, k, v);
  if (this === window.localStorage && /^(mnt-blindvote|mnt-voter|mnt-backup:)/.test(k)) queueMicrotask(() => { syncBlind(); syncStrip(); });
};

let allow = false;
const stop = e => { if (!allow && blindOn()) { e.stopImmediatePropagation(); e.preventDefault(); } };
document.addEventListener('click', e => { if (e.target.closest && e.target.closest('#sortBtn')) stop(e); }, true);   // vak módban nincs rendezés zaj szerint
document.addEventListener('input', e => { if (e.target && e.target.id === 'atmRange') stop(e); }, true);            // és nincs ATM-korlát

function resetControls() {   // vak módra váltáskor a már beállított zaj szerinti rendezés és ATM-korlát visszaáll
  allow = true;
  const s = $('sortBtn'); if (s && /zaj/.test(s.textContent)) s.click();
  const r = $('atmRange'); if (r && Number(r.value) < Number(r.max)) { r.value = r.max; r.dispatchEvent(new Event('input', { bubbles: true })); }
  allow = false;
}
let wasBlind = null;
function syncBlind() {
  const b = blindOn();
  document.body.classList.toggle('blind', b);
  if (b && wasBlind !== true) setTimeout(resetControls, 0);
  wasBlind = b;
}

// 4) Állapotsáv: szavazó, vak mód, mentés kora.
function ago(ms) {
  if (!ms) return null;
  const d = Date.now() - ms;
  return d < 36e5 ? 'az elmúlt órában' : d < 864e5 ? Math.floor(d / 36e5) + ' órája' : Math.floor(d / 864e5) + ' napja';
}
function syncStrip() {
  const voter = lsGet('mnt-voter') || 'A';
  $('sv').textContent = voter;
  const b = blindOn();
  $('sb').textContent = b ? 'be' : 'ki';
  $('stBlind').classList.toggle('on', b);
  const t = Number(lsGet('mnt-backup:' + voter)) || 0, when = ago(t);
  $('sm').textContent = when || 'még nincs';
  const old = !t || Date.now() - t > 3 * 864e5;
  $('stSave').classList.toggle('warn', old);
}
setInterval(syncStrip, 30000);

// 5) Fülek (hash: #hirek, #cimkezes, #terkep, #beallitasok)
const TABS = ['hirek', 'cimkezes', 'terkep', 'beallitasok'];
function ai(open) {   // az AI-panel csak a Beállítások fülön renderelődik (mint az éles felületen: csak nyitva)
  const box = $('aiBox'), ins = $('insBox');
  box.open = open; ins.open = open;
  box.dispatchEvent(new Event('toggle')); ins.dispatchEvent(new Event('toggle'));
}
function show() {
  const h = (location.hash || '').replace('#', '');
  const tab = TABS.includes(h) ? h : 'hirek';
  TABS.forEach(t => { $('tab-' + t).hidden = t !== tab; });
  document.querySelectorAll('.tabbar a').forEach(a => { if (a.dataset.tab === tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  if (tab === 'terkep') window.dispatchEvent(new Event('resize'));   // a glóbusz a látható méretre igazodik
  if (tab === 'beallitasok') ai(true);
  else { ai(false); if (tab === 'cimkezes') syncQuickTab(); }
  syncStrip(); window.scrollTo(0, 0);
}
window.addEventListener('hashchange', show);

// 6) Címkézés fül: a gyorsszavazót és az állapotát az AI-panel kezelői adják.
function withHandlers(fn) {
  const box = $('aiBox'), was = box.open;
  box.open = true; box.dispatchEvent(new Event('toggle'));   // a renderAi kitölti a window.__mnt* mezőket
  try { fn(); } finally { box.open = was; }
}
function syncQuickTab() {
  withHandlers(() => {
    $('quickInfo').textContent = window.__mntQuickInfo || '';
    $('cvoter').textContent = 'Szavazó: ' + (window.__mntQuickVoter || lsGet('mnt-voter') || 'A');
  });
}
$('startQuick').addEventListener('click', () => withHandlers(() => { if (window.__mntQuick) window.__mntQuick(); }));

// 7) Indulás: az alkalmazás betöltése
syncBlind(); syncStrip(); show();
import('./js/app.js').then(() => { syncBlind(); syncStrip(); show(); }).catch(e => { document.body.append(String(e)); });
