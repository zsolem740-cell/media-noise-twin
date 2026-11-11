// HUD kártyák, mérőórák és panelek. Csak textContent-et használ (az RSS-tartalom nem kerülhet HTML-be).
import { level, relTime, safeHref, fmtAtm, atmRef, scoringMode } from './model.js';

export const $ = id => document.getElementById(id);

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

export function setStatus(t) { $('status').textContent = t; }

export function renderKpis(stats, data) {
  $('kpi-atm').textContent = stats.n ? fmtAtm(stats.avgAtm) : '–';
  $('kpi-p90').textContent = stats.n ? fmtAtm(stats.p90) : '–';
  $('kpi-n').textContent = String(stats.n);
  const f = $('kpi-fresh');
  f.textContent = data && data.generated_at ? relTime(data.generated_at) : '–';
  const age = data && data.generated_at ? (Date.now() - Date.parse(data.generated_at)) / 60000 : 0;
  f.className = age > 180 ? 'bad' : age > 90 ? 'warn' : '';  // elavuló adat: borostyán 90 perc, piros 3 óra fölött (a GitHub ütemezése kb. óránkénti ritmust ad)
}

// Egészség-sáv: szerver oldali problémák (hard) és kliens oldali emlékeztetők (soft).
export function renderHealth(list) {
  const box = $('healthBox');
  if (!box) return;  // régi, gyorsítótárazott index.html mellett sem állhat meg az app
  box.replaceChildren();
  (list || []).forEach(h => box.append(el('div', h.soft ? 'soft' : '', (h.soft ? 'ℹ ' : '⚠ ') + h.text)));
  box.hidden = !(list && list.length);
}

export function renderChips(box, regions, active, onPick) {
  box.replaceChildren();
  [{ code: 'ALL', short: 'Mind', name: 'Mind' }].concat(regions).forEach(r => {
    const b = el('button', 'chip', r.short || r.code);
    b.type = 'button';
    b.title = r.name;
    b.setAttribute('aria-pressed', String(active === r.code));
    b.addEventListener('click', () => onPick(r));
    box.append(b);
  });
}

export function renderList(box, rows, ctx) {
  box.replaceChildren(...rows.slice(0, 80).map(r => card(r, ctx)));
}

function card(it, ctx) {
  const c = el('article', 'card lvl-' + level(it.atm, ctx.th) + (it.alert ? ' alert' : ''));
  if (it.alert) c.append(el('span', 'badge', 'HIVATALOS FIGYELMEZTETÉS'));
  const t = el('a', 'title', it.title);
  t.href = safeHref(it.link); t.target = '_blank'; t.rel = 'noopener noreferrer';
  t.addEventListener('click', () => ctx.onOpen(it));
  c.append(t, el('div', 'meta', `${it.source || it.source_domain || '?'} · ${ctx.regionLabel(it.region)} · ${relTime(it.published)}`));

  const bar = el('div', 'bar'); const fill = document.createElement('i');
  fill.style.width = Math.min(100, (it.atm / atmRef()) * 100) + '%'; bar.append(fill); c.append(bar);

  const nums = el('div', 'nums');
  [`ATM ${fmtAtm(it.atm, 2)}`, `V ${it.v.toFixed(2)}`, `S ${it.Seff.toFixed(2)}`, `AI ${it.sAi.toFixed(2)}`, `G ${it.G.toFixed(2)}`]
    .forEach(x => nums.append(el('span', '', x)));
  c.append(nums);

  const mine = ctx.votes.get(it.id);
  const acts = el('div', 'acts');
  [['fact', 'Tény'], ['bait', 'Clickbait']].forEach(([k, label]) => {
    const b = el('button', 'vote ' + k, label);
    b.type = 'button'; b.setAttribute('aria-pressed', String(mine === k));
    b.addEventListener('click', () => ctx.onVote(it, k));
    acts.append(b);
  });
  const why = el('button', 'vote why', 'Miért?'); why.type = 'button';
  const box = el('div', 'explain'); box.hidden = true;
  why.addEventListener('click', () => {
    box.hidden = !box.hidden;
    if (!box.hidden && !box.childNodes.length) ctx.explain(it).forEach(l => box.append(el('div', '', l)));
  });
  acts.append(why);
  c.append(acts, box);
  return c;
}

const sec = (box, title) => { const h = el('h3', '', title); box.append(h); return h; };
const row = (box, text, cls) => box.append(el('div', 'li ' + (cls || ''), text));

export function renderAi(box, ai, handlers = {}) {
  box.replaceChildren();
  sec(box, 'Állapot');
  row(box, `Szavazat: ${ai.votes} · tanulási lépés: ${ai.steps}`);
  row(box, `AI súlya az S értékben: ${(ai.lambda * 100).toFixed(0)}% (${ai.calibrated ? 'kalibrált' : 'szavazatszámból'})`);
  row(box, ai.boot ? 'Alaptanítás kész (a szabályokból indult).' : 'Alaptanítás még nem futott le.');
  const c = ai.cal;
  sec(box, 'Kalibráció a szavazataidból');
  if (!c || !c.ready) {
    row(box, `Még kevés adat: ${c ? c.n1 : 0} clickbait és ${c ? c.n0 : 0} tény jelölés (mindkettőből legalább 5 kell).`);
  } else {
    row(box, `${c.n} szavazat (${c.n1} clickbait, ${c.n0} tény) – AUC: szabály ${c.aucRule.toFixed(2)}, AI ${c.aucAi.toFixed(2)}`);
    row(box, `Legjobb keverés: AI ${(c.best.lam * 100).toFixed(0)}% (AUC ${c.best.auc.toFixed(2)}) – ${c.usable ? 'használatban' : 'használatba 30 szavazattól kerül'}`);
  }
  sec(box, 'Javaslat a beállításokhoz (config/user.json)');
  if (handlers.onSuggest) {
    const s = el('button', 'btn small', 'Javaslat készítése a szavazatokból');
    s.type = 'button';
    s.addEventListener('click', handlers.onSuggest);
    box.append(s);
  }
  if (ai.suggestion) renderSuggestion(box, ai.suggestion, ai.links, handlers);
  if (handlers.onExport) {
    const b = el('button', 'btn small', 'Szavazatok másolása (JSON)');
    b.type = 'button';
    b.addEventListener('click', handlers.onExport);
    box.append(b);
  }
  if (handlers.onDiag) {
    const d = el('button', 'btn small', 'Diagnosztika másolása');
    d.type = 'button';
    d.addEventListener('click', handlers.onDiag);
    box.append(d);
  }
  if (ai.top) {
    sec(box, 'Zajosnak tanult szavak');
    row(box, ai.top.pos.length ? ai.top.pos.map(x => x.word).join(', ') : 'még nincs elég adat');
    sec(box, 'Nyugodtnak tanult szavak');
    row(box, ai.top.neg.length ? ai.top.neg.map(x => x.word).join(', ') : 'még nincs elég adat');
  }
}

function renderSuggestion(box, s, links, handlers) {
  if (!s.ready) {
    row(box, `Még kevés szavazat: legalább 20 kell (mindkét fajtából legalább 6). Most ${s.nb} clickbait és ${s.nf} tény van.`);
    return;
  }
  row(box, s.keywords.length ? `Új kulcsszavak: ${s.keywords.join(', ')}` : 'Új kulcsszó: nincs elég ismétlődő szó.');
  row(box, s.noisy.length ? `Zajosnak jelölt források: ${s.noisy.map(r => `${r.domain} (${r.bait}/${r.n})`).join(', ')}` : 'Zajosnak jelölt forrás: nincs.');
  row(box, s.trusted.length ? `Megbízhatónak jelölt források: ${s.trusted.map(r => `${r.domain} (${r.fact}/${r.n})`).join(', ')}` : 'Megbízhatónak jelölt forrás: nincs.');
  row(box, `Szenzációszint: a Clickbait jelölések mediánja ${s.medBait.toFixed(2)}, a Tényeké ${s.medFact.toFixed(2)}${s.bestS === null ? '' : `; legjobb elválasztó küszöb: S ≈ ${s.bestS.toFixed(2)}`}.`);
  if (s.empty) { row(box, 'Egyelőre nincs módosítási javaslat, gyűjts további szavazatokat.'); return; }
  box.append(el('pre', 'snippet', s.text));
  const copy = el('button', 'btn small', 'Részlet másolása');
  copy.type = 'button';
  copy.addEventListener('click', handlers.onCopySuggestion);
  box.append(copy);
  if (links) {
    [['Új fájl a GitHubon', links.newUrl], ['Meglévő fájl szerkesztése', links.editUrl]].forEach(([t, u]) => {
      const a = el('a', 'linkbtn', t); a.href = u; a.target = '_blank'; a.rel = 'noopener noreferrer'; box.append(a);
    });
  }
  row(box, 'Ha már van config/user.json, a kapcsos zárójelen belülre fésüld be a kulcsokat (a clickbait_add és a trust részt).');
}

export function renderInsights(box, ins, regionLabel, cfg) {
  box.replaceChildren();
  sec(box, 'Beállítás');
  if (cfg && cfg.warning) row(box, `Hiba a config/user.json-ban, az alapbeállítás érvényes: ${cfg.warning}`, 'up');
  else if (cfg && cfg.user) row(box, `Saját beállítás betöltve (config/user.json): ${cfg.applied.join(', ')}`);
  else row(box, 'Alapbeállítás (nincs config/user.json).');
  if (!ins) { row(box, 'Még nincs elemzés – a következő futás után jelenik meg.'); return; }

  sec(box, 'Trend (24 óra az előzőhöz képest)');
  const codes = Object.keys(ins.trend || {});
  if (!codes.length) row(box, 'nincs adat');
  codes.forEach(code => {
    const t = ins.trend[code];
    const eps = scoringMode() === 'sqrt_int' ? 2 : 0.002;
    const arrow = t.delta === null ? '–' : t.delta > eps ? '▲' : t.delta < -eps ? '▼' : '■';
    row(box, `${arrow} ${regionLabel(code)}: ${t.now === null ? '–' : fmtAtm(t.now)}${t.delta === null ? '' : ' (' + (t.delta > 0 ? '+' : '') + fmtAtm(t.delta) + ')'} · ${t.n} hír`,
      t.delta > eps ? 'up' : t.delta < -eps ? 'down' : '');
  });

  sec(box, 'Ugyanaz az esemény, eltérő hangnem');
  if (!ins.events || !ins.events.length) row(box, 'még nincs több forrásból összeálló esemény');
  (ins.events || []).slice(0, 5).forEach(ev => {
    const d = el('div', 'li', ev.label.slice(0, 110));
    d.append(el('small', '', ` · ${ev.n} hír · hangnem-szórás ${ev.spread.toFixed(2)}`));
    box.append(d);
    ev.sources.slice(0, 4).forEach(s => row(box, `${'█'.repeat(Math.max(1, Math.round(s.S * 10)))} ${s.S.toFixed(2)} ${s.domain || s.source}: ${s.title.slice(0, 70)}`, 'src'));
  });

  sec(box, 'Szokatlanul zajos (a forrás megszokottjához képest)');
  if (!ins.anomalies.length) row(box, 'nincs ilyen hír');
  ins.anomalies.forEach(a => {
    const d = el('div', 'li up', `${a.title}`);
    d.append(el('small', '', ` · ${a.source} · z=${a.z}`));
    box.append(d);
  });

  sec(box, 'Felszálló kifejezések (elmúlt 6 óra)');
  row(box, ins.bursts.length ? ins.bursts.map(b => `${b.term} (${b.recent}×)`).join(', ') : 'nincs kiugró téma');

  sec(box, 'Legzajosabb források (átlag ATM)');
  if (!ins.sources.length) row(box, 'még gyűlik az adat');
  ins.sources.slice(0, 8).forEach(s => row(box, `${s.domain}: ATM ${fmtAtm(s.mean_ATM)} · S ${s.mean_S.toFixed(2)} · ${s.n} hír`));
}

export function showPick(box, row) {
  box.replaceChildren();
  if (!row) { box.hidden = true; return; }
  box.hidden = false;
  const a = el('a', '', row.title);
  a.href = safeHref(row.link); a.target = '_blank'; a.rel = 'noopener noreferrer';
  box.append(a, el('small', '', ` ${row.source || ''} · ATM ${fmtAtm(row.atm, 2)}`));
}
