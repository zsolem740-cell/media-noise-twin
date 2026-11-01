/* Média-Zaj Twin v38 – kliensoldali alkalmazás (HUD, lista, glóbusz, tanuló szűrő). */
import { createGlobe, atmColor, rgbCss } from "./modules/webglGlobe.js";
import { FilterEngine } from "./modules/filterEngine.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SCOPE_HU = { official: "Hivatalos", local: "Helyi", national: "Országos", international: "Nemzetközi" };
const TOPIC_HU = { earthquake: "földrengés", solar: "napkitörés", geomagnetic: "geomágneses", storm: "vihar", flood: "árvíz" };
const DEF_TH = { mid: 0.12, high: 0.25 };
const S = { arts: [], meta: null, hist: [], scopes: { official: true, local: true, national: true, international: true }, mode: "learned", hide: false, thr: 0.25, limit: 50, selected: null };
const lsGet = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* tele a tár */ } };
const engine = new FilterEngine();
const votes = lsGet("mnt.votes.v38", {});
const prefs = lsGet("mnt.pref.v38", { fallback: false, auto: true });
let globe = null, reading = null;

const th = () => (S.meta && S.meta.thresholds) || DEF_TH;
const pctl = (v, p) => { if (!v.length) return 0; const a = [...v].sort((x, y) => x - y), k = (a.length - 1) * p, lo = Math.floor(k), hi = Math.ceil(k); return a[lo] + (a[hi] - a[lo]) * (k - lo); };
const ts = (a) => Date.parse(a.published || a.first_seen || 0) || 0;
export function ago(iso, now = Date.now()) {
  const t = Date.parse(iso); if (!t) return "–";
  const m = Math.max(0, Math.round((now - t) / 60000));
  return m < 1 ? "most" : m < 60 ? m + " perce" : m < 1440 ? Math.round(m / 60) + " órája" : Math.round(m / 1440) + " napja";
}
const atmTxt = (v) => (v * 100).toFixed(1);
export const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "#");

/* ───────── adatok ───────── */
async function getJson(url) { const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store" }); if (!r.ok) throw new Error(url + " " + r.status); return r.json(); }
async function load() {
  try {
    const d = await getJson("data/articles.json");
    S.arts = d.articles || []; S.meta = d.meta || null;
    try { S.hist = (await getJson("data/metrics/atm_history.json")).points || []; } catch (e) { S.hist = []; }
    $("empty").hidden = true;
  } catch (e) {
    S.arts = []; S.meta = null; $("empty").hidden = false;
  }
  render();
}

/* ───────── szűrés és sorrend ───────── */
export function ordered(list, mode, eng) {
  const a = [...list];
  if (mode === "noisy") a.sort((x, y) => y.atm - x.atm);
  else if (mode === "clean") a.sort((x, y) => x.atm - y.atm);
  else if (mode === "recent") a.sort((x, y) => ts(y) - ts(x));
  else { const sc = new Map(a.map((x) => [x.id, eng.score(x).score])); a.sort((x, y) => sc.get(y.id) - sc.get(x.id) || ts(y) - ts(x)); }
  return a;
}
const visible = () => ordered(S.arts.filter((a) => S.scopes[a.scope] && (!S.hide || a.atm <= S.thr)), S.mode, engine);

/* ───────── HUD ───────── */
function renderHud(list) {
  const day = list.filter((a) => ts(a) >= Date.now() - 864e5), v = (day.length ? day : list).map((a) => a.atm);
  const mean = v.length ? v.reduce((x, y) => x + y, 0) / v.length : 0, p90 = pctl(v, 0.9), t = th();
  $("m-atm").textContent = atmTxt(mean); $("m-atm").style.color = rgbCss(atmColor(mean, t));
  $("m-p90").textContent = atmTxt(p90); $("m-p90").style.color = rgbCss(atmColor(p90, t));
  $("m-n").textContent = String(list.length);
  const g = S.meta && S.meta.generated_at;
  $("m-upd").textContent = g ? ago(g) : "–";
  const st = engine.stats();
  $("learn").textContent = `Tanuló szűrő: λ ${st.lambda.toFixed(2)} · AUC ${st.auc === null ? "–" : st.auc.toFixed(2)} · ${st.trained} tanítás`;
  const m = S.meta || {}, b = [];
  if (m.official) b.push(m.official.calm === false ? "🚨 HungaroMet: érvényes figyelmeztetés" : m.official.calm === true ? "✅ HungaroMet: nincs figyelmeztetés" : "ℹ HungaroMet: állapot ismeretlen");
  if (m.truth) b.push(m.truth.available ? "🔬 Fizikai mérés: " + ((m.truth.flags || []).length ? m.truth.flags.map((f) => TOPIC_HU[f] || f).join(", ") : "nyugodt") : "🔬 Fizikai mérés: nincs adat");
  if (m.warming_up) b.push("📈 Trend: gyűjtés (24 óra kell)");
  else if ((m.rising || []).length) b.push("📈 Felszálló: " + m.rising.slice(0, 3).map((r) => r.term).join(", "));
  const errs = Object.keys(m.errors || {});
  if (errs.length) b.push("⚠ Nem elérhető forrás: " + errs.join(", "));
  if (g && Date.now() - Date.parse(g) > 3 * 36e5) b.push("🕒 Az adat " + ago(g) + " változott (nincs új érdemi változás, vagy áll a gyűjtés)");
  $("banner").innerHTML = b.map((x) => `<span>${esc(x)}</span>`).join("");
  spark();
}
function spark() {
  const cv = $("spark"), ctx = cv.getContext && cv.getContext("2d"); if (!ctx) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2), w = cv.clientWidth || 120, h = cv.clientHeight || 30;
  cv.width = w * dpr; cv.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
  const pts = S.hist.filter((p) => Date.parse(p.t) > Date.now() - 7 * 864e5); if (pts.length < 2) return;
  const t0 = Date.parse(pts[0].t), t1 = Date.parse(pts[pts.length - 1].t) || t0 + 1, mx = Math.max(0.05, ...pts.map((p) => p.p90 || p.mean));
  const line = (key, col, dash) => { ctx.beginPath(); ctx.setLineDash(dash); ctx.strokeStyle = col; ctx.lineWidth = 1.4; pts.forEach((p, i) => { const x = (Date.parse(p.t) - t0) / (t1 - t0) * (w - 2) + 1, y = h - 2 - (p[key] / mx) * (h - 4); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke(); };
  line("p90", "rgba(245,158,11,.8)", [3, 3]); line("mean", "rgba(6,182,212,.95)", []);
}

/* ───────── lista ───────── */
function bar(label, v, cls) { return `<span class="bar ${cls}"><i style="width:${Math.round(v * 100)}%"></i><b>${label} ${v.toFixed(2)}</b></span>`; }
function card(a, sc) {
  const c = rgbCss(atmColor(a.atm, th())), vt = votes[a.id], tr = a.truth || {};
  const tags = (a.topics || []).map((t) => `<em>${esc(TOPIC_HU[t] || t)}</em>`).join("");
  const badge = tr.verdict === "igazolt" ? `<em class="ok">✔ fizikailag igazolt</em>` : tr.verdict === "nem igazolt" ? `<em class="bad">⚠ fizikailag nem igazolt</em>` : "";
  return `<article class="card${S.selected === a.id ? " sel" : ""}" data-id="${esc(a.id)}">
 <div class="row"><span class="atm" style="--c:${c}">ATM ${atmTxt(a.atm)}</span><span class="scope">${SCOPE_HU[a.scope] || a.scope}</span><span class="time">${ago(a.published || a.first_seen)}</span></div>
 <h3><a href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer" data-act="link">${esc(a.title)}</a></h3>
 <div class="meta">${esc(a.source)}${a.geo ? " · 📍 " + esc(a.geo.name) : ""}${a.event_sources > 1 ? " · 📰 " + a.event_sources + " forrás" : ""}</div>
 <div class="bars">${bar("G", a.g, "g")}${bar("S", a.s, "s")}${bar("V", a.v, "v")}</div>
 <div class="tags">${tags}${badge}</div>
 <div class="detail" hidden>${a.summary ? `<p>${esc(a.summary)}</p>` : ""}<p class="dim">ATM = G·S·(1−V) = ${a.g.toFixed(2)} · ${a.s.toFixed(2)} · ${(1 - a.v).toFixed(2)}${tr.verdict && tr.verdict !== "n/a" ? ` · fizikai ellenőrzés: ${esc(tr.verdict)} (V ${tr.dv > 0 ? "+" : ""}${tr.dv}${tr.ds ? ", S +" + tr.ds : ""})` : ""}</p>
 <p class="dim">Tanult pontszám: ${sc.score.toFixed(2)} (p ${sc.p.toFixed(2)} · tisztaság ${sc.prior.toFixed(2)} · λ ${sc.lambda.toFixed(2)})${a.z != null ? " · forrás-eltérés z " + a.z : ""}</p></div>
 <div class="votes"><button data-act="up" class="${vt === 1 ? "on" : ""}">👍 Hasznos</button><button data-act="down" class="${vt === 0 ? "on" : ""}">👎 Zaj</button><button data-act="open" class="ghost">Részletek</button></div>
</article>`;
}
function render() {
  const list = visible();
  renderHud(list);
  $("list").innerHTML = list.slice(0, S.limit).map((a) => card(a, engine.score(a))).join("") || (S.arts.length ? `<p class="dim pad">Nincs a szűrőknek megfelelő hír.</p>` : "");
  $("more").hidden = list.length <= S.limit; $("more").textContent = `Továbbiak (${list.length - S.limit})`;
  if (globe) {
    const mx = Math.log2(Math.max(2, ...list.map((a) => a.event_size || 1)));
    globe.setPoints(list.filter((a) => a.geo).map((a) => ({ id: a.id, lat: a.geo.lat, lon: a.geo.lon, atm: a.atm, size: Math.log2(a.event_size || 1) / mx })), th());
  }
}

/* ───────── tanítás: szavazat, olvasási idő ───────── */
const byId = (id) => S.arts.find((a) => a.id === id);
function vote(a, label) {
  if (votes[a.id] === label) return;
  votes[a.id] = label; lsSet("mnt.votes.v38", votes);
  engine.train(a, label, 1, "vote");
}
function stopReading(card) {
  if (!reading || (card && reading.id !== card)) return;
  const sec = (Date.now() - reading.since) / 1000, a = byId(reading.id), opened = reading.opened;
  reading = null;
  if (a && !votes[a.id]) engine.trainDwell(a, sec, opened);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (reading && reading.away) { const away = (Date.now() - reading.since) / 1000, a = byId(reading.id); reading = null; if (a && away >= 8) engine.trainDwell(a, away, false); render(); }
});

/* ───────── események ───────── */
$("list").addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-act]"), cardEl = ev.target.closest(".card"); if (!cardEl) return;
  const a = byId(cardEl.dataset.id); if (!a) return;
  const act = t && t.dataset.act;
  if (act === "up" || act === "down") { vote(a, act === "up" ? 1 : 0); const y = $("sheet").scrollTop; render(); $("sheet").scrollTop = y; return; }
  if (act === "link") { stopReading(); reading = { id: a.id, since: Date.now(), away: true }; return; }
  const d = cardEl.querySelector(".detail"), open = d.hidden;
  if (reading && reading.id !== a.id) stopReading();
  d.hidden = !open;
  if (open) { reading = { id: a.id, since: Date.now(), opened: true }; S.selected = a.id; if (globe && a.geo) { globe.select(a.id); globe.focus(a.geo.lat, a.geo.lon); } }
  else stopReading(a.id);
});
$("chips").addEventListener("click", (ev) => { const b = ev.target.closest("[data-scope]"); if (!b) return; S.scopes[b.dataset.scope] = !S.scopes[b.dataset.scope]; b.classList.toggle("off", !S.scopes[b.dataset.scope]); S.limit = 50; render(); });
$("mode").addEventListener("change", (ev) => { S.mode = ev.target.value; S.limit = 50; render(); });
$("hide").addEventListener("change", (ev) => { S.hide = ev.target.checked; render(); });
$("thr").addEventListener("input", (ev) => { S.thr = ev.target.value / 100; $("thr-val").textContent = atmTxt(S.thr); if (S.hide) render(); });
$("more").addEventListener("click", () => { S.limit += 50; render(); });
$("b-refresh").addEventListener("click", load);
$("b-focus").addEventListener("click", () => { const r = (S.meta && S.meta.region) || { lat: 47, lon: 16.6 }; if (globe) globe.focus(r.lat, r.lon); });
$("b-auto").addEventListener("click", () => { prefs.auto = !prefs.auto; lsSet("mnt.pref.v38", prefs); if (globe) globe.setAutoRotate(prefs.auto); $("b-auto").classList.toggle("off", !prefs.auto); });
$("b-sheet").addEventListener("click", () => $("app").classList.toggle("peek"));
$("b-settings").addEventListener("click", () => { $("settings").hidden = false; });
$("s-close").addEventListener("click", () => { $("settings").hidden = true; });
$("s-reset").addEventListener("click", () => { if (confirm("Biztosan törlöd a tanult szűrőt és a szavazataidat?")) { engine.reset(); Object.keys(votes).forEach((k) => delete votes[k]); lsSet("mnt.votes.v38", votes); render(); } });
$("s-2d").addEventListener("click", () => { prefs.fallback = !prefs.fallback; lsSet("mnt.pref.v38", prefs); location.reload(); });
$("s-2d").textContent = prefs.fallback ? "3D glóbusz bekapcsolása" : "Egyszerű 2D glóbusz (gyengébb telefonra)";
$("b-auto").classList.toggle("off", !prefs.auto);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $("settings").hidden = true; });

/* ───────── indítás ───────── */
async function start() {
  try {
    globe = await createGlobe($("globe"), {
      forceFallback: prefs.fallback, focus: [47, 16.6],
      onPick: (p) => { S.selected = p.id; const idx = visible().findIndex((a) => a.id === p.id); if (idx >= S.limit) S.limit = idx + 1; render(); const el = document.querySelector(`.card[data-id="${CSS.escape(p.id)}"]`); if (el) { $("app").classList.remove("peek"); el.scrollIntoView({ block: "center", behavior: "smooth" }); } },
    });
    globe.setAutoRotate(prefs.auto);
    $("kind").textContent = globe.kind === "webgl" ? "WebGL" : "2D";
  } catch (e) { $("kind").textContent = "nincs glóbusz"; }
  await load();
  setInterval(() => { if (!document.hidden) load(); }, 5 * 60 * 1000);
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
}
if (typeof document !== "undefined" && document.getElementById("globe")) start();
