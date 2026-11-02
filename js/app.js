/* Média-Zaj Twin v40.2 – kliensoldali alkalmazás (HUD, lista, glóbusz, tanuló szűrő, címkéző űrlap, Gemini-javaslat).
   ATM = G·S·(1−V): G = fizikai nyugalom (M1, az egész környezetre közös), S = a hír nyelvi zaja, V = a hír érvényessége. */
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

/* ───────── címkézés (v40.1): hírérték, valóság, stílus, címkéző. Csak ezen a telefonon tárolódik, a tanuló szűrőt NEM tanítja. ───────── */
const labels = lsGet("mnt.labels.v1", {});
const labPref = lsGet("mnt.labpref.v1", { forras: "sajat" });
export const LAB = [
  { f: "ertek", name: "Hírérték", opts: [["magas", "magas"], ["kozepes", "közepes"], ["alacsony", "alacsony"]] },
  { f: "valosag", name: "Valóság", opts: [["igaz", "igaz"], ["hamis", "hamis"], ["nem_ellenorizheto", "nem ellenőrizhető"]] },
  { f: "stilus", name: "Stílus", opts: [["nyugodt", "nyugodt"], ["felfokozott", "felfokozott"]] },
  { f: "forras", name: "Címkéző", opts: [["sajat", "saját"], ["gemini", "Gemini"]] },
];
const LAB_MAIN = ["ertek", "valosag", "stilus"];
const LAB_OK = Object.fromEntries(LAB.map((r) => [r.f, new Set(r.opts.map((o) => o[0]))]));
function saveLabels() { try { localStorage.setItem("mnt.labels.v1", JSON.stringify(labels)); return true; } catch (e) { return false; } }
export function labelState(l) { const n = l ? LAB_MAIN.filter((f) => l[f]).length : 0; return n === 3 ? "Címkézve (3/3)" : n ? `Részben címkézve (${n}/3)` : "Még nincs címke"; }
const GEM_NAMES = { ertek: { magas: "magas", kozepes: "közepes", alacsony: "alacsony" }, stilus: { nyugodt: "nyugodt", felfokozott: "felfokozott" }, valosag: { igaz: "igaz", hamis: "hamis", nem_ellenorizheto: "nem ellenőrizhető" } };
const gemOf = (a) => (S.gem && S.gem.labels && S.gem.labels[a.id]) || null;
export function gemBlock(a, g = gemOf(a), entry = (S.gem && S.gem.search_entries && S.gem.search_entries[a.id]) || "") {
  if (!g) return "";
  const nm = (f, v) => (v && GEM_NAMES[f][v]) || "–";
  const src = (g.forrasok || []).filter((x) => /^https:\/\//.test(String(x.uri || ""))).map((x) => `<a href="${esc(x.uri)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`).join(" · ");
  const se = entry ? `<iframe class="gem-se" sandbox="allow-popups allow-popups-to-escape-sandbox" srcdoc="${esc('<base target="_blank">' + entry)}" loading="lazy"></iframe>` : "";
  return `<div class="gem"><h4>Gemini javaslat <span class="dim">· ${esc(g.model || "")}</span></h4><p>Hírérték: <b>${nm("ertek", g.ertek)}</b> · Stílus: <b>${nm("stilus", g.stilus)}</b> · Valóság: <b>${g.valosag ? nm("valosag", g.valosag) : "nincs ítélet"}</b> · bizonyosság ${typeof g.magabiztossag === "number" ? g.magabiztossag.toFixed(2) : "–"}</p>${g.indoklas ? `<p class="dim">${esc(g.indoklas)}</p>` : ""}${src ? `<p class="dim">Források: ${src}</p>` : ""}${g.valosag_megjegyzes ? `<p class="dim">${esc(g.valosag_megjegyzes)}</p>` : ""}<button data-act="gem" class="gem-ok">Elfogadom (címkéző: Gemini)</button>${se}</div>`;
}
export function labForm(a, l = labels[a.id] || {}, pref = labPref) {
  const rows = LAB.map((r) => { const cur = l[r.f] || (r.f === "forras" ? pref.forras : null); return `<div class="lab-row"><span>${r.name}</span><span class="seg">${r.opts.map(([v, t]) => `<button data-act="lab" data-f="${r.f}" data-v="${v}" class="${cur === v ? "on" : ""}">${t}</button>`).join("")}</span></div>`; }).join("");
  return `<div class="lab">${gemBlock(a)}<h4>Címkézés (kutatás)</h4>${rows}<input class="lab-note" maxlength="200" placeholder="megjegyzés vagy forráslink (hamisnál ajánlott)" value="${esc(l.megj || "")}"><p class="dim lab-state">${labelState(l)}</p></div>`;
}
function labRecord(a) {
  return labels[a.id] || (labels[a.id] = { id: a.id, ts: new Date().toISOString(), cim: String(a.title || "").slice(0, 200), link: safeUrl(a.link), cikk_forras: String(a.source || ""), megjelent: a.published || "", atm: a.atm, g: a.g, s: a.s, v: a.v, fiz: (a.truth && a.truth.verdict) || "", forras: labPref.forras });
}
export function setLabel(a, f, v) {
  if (!LAB_OK[f] || !LAB_OK[f].has(v)) return false;
  const l = labRecord(a);
  if (f === "forras") { l.forras = v; labPref.forras = v; lsSet("mnt.labpref.v1", labPref); }
  else l[f] = l[f] === v ? "" : v;                              // ugyanarra koppintva törlődik
  l.upd = new Date().toISOString();
  if (!LAB_MAIN.some((k) => l[k]) && !l.megj) delete labels[a.id];   // üres címke nem marad
  return saveLabels();
}
export function applyGem(a, g = gemOf(a)) {
  if (!g) return false;
  const l = labRecord(a);
  if (LAB_OK.ertek.has(g.ertek)) l.ertek = g.ertek;
  if (LAB_OK.stilus.has(g.stilus)) l.stilus = g.stilus;
  if (g.valosag && LAB_OK.valosag.has(g.valosag)) l.valosag = g.valosag;
  l.forras = "gemini"; l.gem_bizonyossag = typeof g.magabiztossag === "number" ? g.magabiztossag : ""; l.gem_modell = String(g.model || "");
  const okSrc = (g.forrasok || []).filter((x) => /^https:\/\//.test(String(x.uri || "")));
  if (!l.megj && g.valosag && okSrc.length) l.megj = okSrc.map((x) => x.title).slice(0, 3).join(", ").slice(0, 200);
  l.upd = new Date().toISOString();
  return saveLabels();
}
export function setNote(a, text) {
  const l = labRecord(a); l.megj = String(text || "").trim().slice(0, 200); l.upd = new Date().toISOString();
  if (!LAB_MAIN.some((k) => l[k]) && !l.megj) delete labels[a.id];
  return saveLabels();
}
export function csvCell(x) { let t = String(x ?? "").replace(/[\r\n]+/g, " "); if (/^[=+\-@\t]/.test(t)) t = "'" + t; return /[",;]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t; }
const CSV_COLS = ["id", "idopont", "cim", "link", "cikk_forras", "megjelent", "atm", "g", "s", "v", "fizikai_itelet", "hirertek", "valosag", "stilus", "cimkezo", "megjegyzes", "gem_bizonyossag", "gem_modell"];
export function labelsCsv(all) {
  const num = (x) => (typeof x === "number" && isFinite(x) ? x.toFixed(4) : "");
  const rows = Object.values(all).sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  return [CSV_COLS.join(","), ...rows.map((l) => [l.id, l.ts, l.cim, l.link, l.cikk_forras, l.megjelent, num(l.atm), num(l.g), num(l.s), num(l.v), l.fiz, l.ertek, l.valosag, l.stilus, l.forras, l.megj, l.gem_bizonyossag, l.gem_modell].map(csvCell).join(","))].join("\n");
}
function labPaint(cardEl, a) {
  const l = labels[a.id] || {};
  if (cardEl.querySelectorAll) cardEl.querySelectorAll('[data-act="lab"]').forEach((b) => { const cur = l[b.dataset.f] || (b.dataset.f === "forras" ? labPref.forras : null); b.classList.toggle("on", cur === b.dataset.v); });
  const st = cardEl.querySelector && cardEl.querySelector(".lab-state"); if (st) st.textContent = labelState(l);
  labCount();
}
export function gemChipUpdate() {
  const box = document.getElementById("chips"); if (!box || !box.appendChild) return;
  let b = document.getElementById("gem-chip");
  const n = S.arts.filter((a) => gemOf(a)).length, m = S.gemMode | 0;
  if (!n && !m) { if (b && b.remove) b.remove(); return; }       // nincs javaslat: nincs gomb
  if (!b) { b = document.createElement("button"); b.id = "gem-chip"; if (b.dataset) b.dataset.gem = "1"; box.appendChild(b); }
  const fresh = S.arts.filter((a) => gemOf(a) && !labels[a.id]).length;
  b.textContent = m === 0 ? `Gemini (${n})` : m === 1 ? `Gemini: mind (${n})` : `Gemini: új (${fresh})`;
  b.classList.toggle("off", m === 0);
}
export const gemTag = (a, l = labels[a.id]) => `${gemOf(a) ? '<em class="gtag">Gemini</em>' : ""}${l && LAB_MAIN.some((f) => l[f]) ? '<em class="gtag ok">címkézve</em>' : ""}`;
function labCount() { const el = document.getElementById("lab-count"); if (el) el.textContent = `${Object.keys(labels).length} címkézett hír (${Object.values(labels).filter((l) => LAB_MAIN.every((f) => l[f])).length} teljes), csak ezen a telefonon.`; }
async function copyText(txt) {
  try { await navigator.clipboard.writeText(txt); return true; } catch (e) {
    try { const ta = document.createElement("textarea"); ta.value = txt; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok; } catch (e2) { return false; }
  }
}
function labUi() {
  const box = document.querySelector("#settings .box"), anchor = $("s-reset");
  if (!box || !anchor || $("s-lab")) return;
  const w = document.createElement("div"); w.id = "s-lab"; w.className = "lab-set";
  w.innerHTML = `<p class="dim" id="lab-count"></p><button id="lab-copy">Címkék másolása (CSV)</button><button id="lab-clear" class="ghost">Címkék törlése</button><p class="dim" id="lab-msg"></p><textarea id="lab-out" readonly hidden></textarea>`;
  box.insertBefore(w, anchor);
  $("lab-copy").addEventListener("click", async () => {
    const n = Object.keys(labels).length, msg = $("lab-msg"), out = $("lab-out");
    if (!n) { msg.textContent = "Még nincs címke."; return; }
    const csv = labelsCsv(labels), ok = await copyText(csv);
    out.hidden = ok; if (!ok) { out.value = csv; try { out.select(); } catch (e) { /* kézzel kijelölhető */ } }
    msg.textContent = ok ? `${n} címke a vágólapon (CSV).` : "A másolás nem sikerült: a szöveg alább kijelölhető, másold ki kézzel.";
  });
  $("lab-clear").addEventListener("click", () => { if (confirm("Biztosan törlöd az összes címkét? (A szavazatok és a tanult szűrő megmarad.)")) { Object.keys(labels).forEach((k) => delete labels[k]); saveLabels(); labCount(); $("lab-msg").textContent = "A címkék törölve."; } });
  labCount();
}
function injectLabCss() {
  if (typeof document === "undefined" || !document.head || !document.createElement || document.getElementById("lab-css")) return;
  const st = document.createElement("style"); st.id = "lab-css";
  st.textContent = ".lab{margin-top:8px;padding:8px;border:1px dashed var(--line);border-radius:10px}.lab h4{margin:0 0 4px;font-size:11px;color:var(--am);font-weight:600}.lab-row{display:flex;align-items:center;gap:6px;margin:4px 0}.lab-row>span:first-child{width:62px;flex:none;font-size:11px;color:var(--dim)}.seg{display:flex;gap:4px;flex:1;flex-wrap:wrap}.seg button{flex:1;min-width:0;padding:4px 6px;min-height:30px;font-size:11px;border-radius:8px}.seg button.on{background:rgba(139,92,246,.35);border-color:var(--vi)}.seg button[data-v=nem_ellenorizheto]{flex-basis:100%}.gem{margin-bottom:8px;padding:8px;border:1px solid var(--vi);border-radius:10px;background:rgba(139,92,246,.10)}.gem h4{margin:0 0 4px;font-size:11px;color:var(--am);font-weight:600}.gem p{margin:4px 0;font-size:12px;overflow-wrap:anywhere}.gem a{color:var(--am)}.gtag{border:1px solid var(--vi)!important;color:var(--am)!important}.gtag.ok{border-color:#3fb950!important;color:#3fb950!important}.gem-ok{width:100%;min-height:34px;margin-top:4px}.gem-se{width:100%;height:80px;border:0;border-radius:8px;margin-top:6px;background:#fff}.lab-note{width:100%;margin-top:4px;font:inherit;font-size:11px;color:var(--ink);background:rgba(5,10,24,.6);border:1px solid var(--line);border-radius:8px;padding:6px}.lab-set{display:flex;flex-direction:column;gap:6px}#lab-out{width:100%;height:90px;font:inherit;font-size:10px;color:var(--ink);background:rgba(5,10,24,.7);border:1px solid var(--line);border-radius:8px}";
  document.head.appendChild(st);
}

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
    try { S.gem = await getJson("data/metrics/gemini_labels.json"); } catch (e) { S.gem = null; }
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
const gemOK = (a) => { const m = S.gemMode | 0; return m === 0 || (m === 1 ? !!gemOf(a) : !!gemOf(a) && !labels[a.id]); };
const visible = () => ordered(S.arts.filter((a) => S.scopes[a.scope] && (!S.hide || a.atm <= S.thr) && gemOK(a)), S.mode, engine);

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
  if (m.g) b.push("⚖ G fizikai nyugalom " + Number(m.g.value).toFixed(2) + " (" + ({ M1: "Solaris M1", derived: "jelzőkből becsült", default: "nincs mérés, feltételezett" }[m.g.source] || m.g.source) + ")");
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
 <div class="bars">${bar("S zaj", a.s, "s")}${bar("V érvényes", a.v, "v")}</div>
 <div class="tags">${tags}${badge}${gemTag(a)}</div>
 <div class="detail" hidden>${a.summary ? `<p>${esc(a.summary)}</p>` : ""}<p class="dim">ATM = G·S·(1−V) = ${a.g.toFixed(2)} (fizikai nyugalom) · ${a.s.toFixed(2)} (zaj) · ${(1 - a.v).toFixed(2)} (1 − érvényesség)${tr.verdict && tr.verdict !== "n/a" ? ` · fizikai ellenőrzés: ${esc(tr.verdict)} (V ${tr.dv > 0 ? "+" : ""}${tr.dv}${tr.ds ? ", S +" + tr.ds : ""})` : ""}</p>
 <p class="dim">Tanult pontszám: ${sc.score.toFixed(2)} (p ${sc.p.toFixed(2)} · tisztaság ${sc.prior.toFixed(2)} · λ ${sc.lambda.toFixed(2)})${a.z != null ? " · forrás-eltérés z " + a.z : ""}</p>${labForm(a)}</div>
 <div class="votes"><button data-act="up" class="${vt === 1 ? "on" : ""}">👍 Hasznos</button><button data-act="down" class="${vt === 0 ? "on" : ""}">👎 Zaj</button><button data-act="open" class="ghost">Részletek</button></div>
</article>`;
}
function render() {
  try { gemChipUpdate(); } catch (e) { /* a szűrőgomb hibája nem akaszthatja meg a listát */ }
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
  if (act === "gem") { const ok = applyGem(a); labPaint(cardEl, a); const st = cardEl.querySelector && cardEl.querySelector(".lab-state"); if (st) st.textContent = ok ? "Gemini-javaslat elfogadva · " + labelState(labels[a.id]) : "Nem sikerült menteni (tele a tár?)"; return; }
  if (act === "lab") { const ok = setLabel(a, t.dataset.f, t.dataset.v); labPaint(cardEl, a); if (!ok) { const st = cardEl.querySelector && cardEl.querySelector(".lab-state"); if (st) st.textContent = "Nem sikerült menteni (tele a tár?)"; } return; }
  if (!act && ev.target.closest(".lab")) return;       // az űrlap mezői nem nyitják/zárják a részleteket
  if (act === "up" || act === "down") { vote(a, act === "up" ? 1 : 0); const y = $("sheet").scrollTop; render(); $("sheet").scrollTop = y; return; }
  if (act === "link") { stopReading(); reading = { id: a.id, since: Date.now(), away: true }; return; }
  const d = cardEl.querySelector(".detail"), open = d.hidden;
  if (reading && reading.id !== a.id) stopReading();
  d.hidden = !open;
  if (open) { reading = { id: a.id, since: Date.now(), opened: true }; S.selected = a.id; if (globe && a.geo) { globe.select(a.id); globe.focus(a.geo.lat, a.geo.lon); } }
  else stopReading(a.id);
});
$("list").addEventListener("change", (ev) => {
  const el = ev.target; if (!el || !el.classList || !el.classList.contains("lab-note")) return;
  const cardEl = el.closest(".card"), a = cardEl && byId(cardEl.dataset.id); if (!a) return;
  setNote(a, el.value); labPaint(cardEl, a);
});
$("chips").addEventListener("click", (ev) => { const gb = ev.target.closest("[data-gem]"); if (gb && gb.dataset && gb.dataset.gem === "1") { S.gemMode = ((S.gemMode | 0) + 1) % 3; S.limit = 50; render(); } });
$("chips").addEventListener("click", (ev) => { const b = ev.target.closest("[data-scope]"); if (!b) return; S.scopes[b.dataset.scope] = !S.scopes[b.dataset.scope]; b.classList.toggle("off", !S.scopes[b.dataset.scope]); S.limit = 50; render(); });
$("mode").addEventListener("change", (ev) => { S.mode = ev.target.value; S.limit = 50; render(); });
$("hide").addEventListener("change", (ev) => { S.hide = ev.target.checked; render(); });
$("thr").addEventListener("input", (ev) => { S.thr = ev.target.value / 100; $("thr-val").textContent = atmTxt(S.thr); if (S.hide) render(); });
$("more").addEventListener("click", () => { S.limit += 50; render(); });
$("b-refresh").addEventListener("click", load);
$("b-focus").addEventListener("click", () => { const r = (S.meta && S.meta.region) || { lat: 47, lon: 16.6 }; if (globe) globe.focus(r.lat, r.lon); });
$("b-auto").addEventListener("click", () => { prefs.auto = !prefs.auto; lsSet("mnt.pref.v38", prefs); if (globe) globe.setAutoRotate(prefs.auto); $("b-auto").classList.toggle("off", !prefs.auto); });
$("b-sheet").addEventListener("click", () => $("app").classList.toggle("peek"));
$("b-settings").addEventListener("click", () => { labUi(); labCount(); $("settings").hidden = false; });
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
    try { const sm = document.querySelector(".title small"); if (sm && sm.innerHTML) sm.innerHTML = sm.innerHTML.replace("· v40 ·", "· v40.2 ·"); } catch (e) { /* csak felirat */ }
  } catch (e) { $("kind").textContent = "nincs glóbusz"; }
  await load();
  setInterval(() => { if (!document.hidden) load(); }, 5 * 60 * 1000);
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
}
if (typeof document !== "undefined" && document.getElementById("globe")) { injectLabCss(); start(); }
