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

// Mentés és helyreállítás (a kulcs csak maszkolva látszik).
function renderBackup(box, h) {
  const d = el('details', 'bk');
  d.open = !!h.open;
  d.addEventListener('toggle', () => { if (h.onToggle) h.onToggle(d.open); });
  d.append(el('summary', '', 'Mentés és helyreállítás'));
  const mk = (txt, fn) => { const b = el('button', 'btn small', txt); b.type = 'button'; b.addEventListener('click', fn); return b; };
  (h.lines || []).forEach(t => d.append(el('div', 'small', t)));
  d.append(mk('Mentés felhőbe (megosztás: Drive, Keep…)', h.onShare), mk('Teljes mentés másolása', h.onCopy));
  d.append(el('div', 'small bkhead', 'Helyreállítás (új eszközön vagy törlés után): illeszd be a mentés szövegét, vagy válaszd ki a mentés fájlját. Az egyesítés nem töröl semmit.'));
  const ta = el('textarea'); ta.rows = 3; ta.placeholder = 'a mentés szövege'; d.append(ta);
  d.append(mk('Előnézet (még nem ír át semmit)', () => h.onRestorePreview(ta.value)));
  const fi = el('input'); fi.type = 'file'; fi.accept = '.txt,.json,text/plain';
  fi.addEventListener('change', () => { const f = fi.files && fi.files[0]; if (f && f.text) f.text().then(t => h.onRestorePreview(t)); });
  d.append(fi);
  if (h.pending) { d.append(el('div', 'small bkpend', h.pending.summary)); d.append(mk('Visszaállítás megerősítése', h.onRestoreConfirm), mk('Mégse', h.onRestoreCancel)); }
  d.append(el('div', 'small bkhead', 'Egyeztetés a többi szavazóval: illeszd be a többiek mentésének szövegét (több mentés = több sor). Nem ír át semmit, csak kiírja az egyezést.'));
  const rt = el('textarea'); rt.rows = 3; rt.placeholder = 'a többi szavazó mentése (soronként egy)'; d.append(rt);
  d.append(mk('Egyeztetés (nem ír át semmit)', () => h.onRecon(rt.value)));
  if (h.reconText) { d.append(el('pre', 'auditpre', h.reconText)); d.append(mk('Egyeztetés eredményének másolása', h.onReconCopy)); }
  const c = h.cloud || {};
  d.append(el('div', 'small bkhead', c.configured ? `Automatikus felhő-mentés (privát GitHub-tároló): ${c.repo} · kulcs: ${c.masked}` : 'Automatikus felhő-mentés (opcionális): privát GitHub-tároló és csak arra az egy tárolóra szóló kulcs kell hozzá (lásd a Helyreállítási útmutatót).'));
  if (!c.configured) {
    const r = el('input'); r.type = 'text'; r.placeholder = 'felhasználó/tároló'; r.autocomplete = 'off';
    const t = el('input'); t.type = 'password'; t.placeholder = 'kulcs (github_pat_…)'; t.autocomplete = 'off';
    d.append(r, t, mk('Felhő-mentés beállítása', () => h.onCloudSave(r.value, t.value)));
  } else d.append(mk('Mentés most (GitHub)', h.onCloudNow), mk('Visszaállítás a GitHubról', h.onCloudRestore), mk('Kulcs törlése erről az eszközről', h.onCloudForget));
  box.append(d);
}

// Gyorsszavazó: egy cím, három nagy gomb, a számok és a forrás rejtve.
export function renderQuick(root, q) {
  root.replaceChildren();
  root.hidden = !q.open;
  if (!q.open) return;
  const mk = (cls, txt, fn) => { const b = el('button', cls, txt); b.type = 'button'; b.addEventListener('click', fn); return b; };
  if (q.ask) {   // indításkor: ki szavaz? (közös eszközön így nem kerül a szavazat a másik szavazó neve alá)
    const t = el('div', 'qtop');
    t.append(el('span', 'small', 'Gyorsszavazás'), mk('btn small', 'Kilépés', q.onClose));
    root.append(t, el('div', 'qtitle', 'Ki szavaz most?'));
    const g = el('div', 'qvoters');
    q.voters.forEach(v => g.append(mk('qbtn qvoter' + (v === q.voter ? ' cur' : ''), v, () => q.onPick(v))));
    root.append(g, el('div', 'small qrule', `Legutóbb: ${q.voter}. Minden szavazó a saját betűjét válassza: a szavazatok, az ismétlések és a tanuló szavazónként külön tárolódnak, a másik szavazó szavazatai nem látszanak.`));
    return;
  }
  const top = el('div', 'qtop');
  top.append(el('span', 'small', `Szavazó: ${q.voter} · Értékelő sor: ${q.p.eval}/${q.target.eval} · clickbait ${q.p.bait}/${q.target.bait} · tanító sor: ${q.p.train} · közepes: ${q.mids}`));
  top.append(mk('btn small', 'Kilépés', q.onClose));
  root.append(top);
  if (q.title) {
    root.append(el('div', 'qtitle', q.title));
    const g = el('div', 'qbtns');
    g.append(mk('qbtn fact', 'Nyugodt', () => q.onAnswer('fact')), mk('qbtn mid', 'Közepes', () => q.onAnswer('mid')), mk('qbtn bait', 'Hangos', () => q.onAnswer('bait')));
    root.append(g);
    const g2 = el('div', 'qbtns2');
    g2.append(mk('btn small', 'Kihagy', () => q.onAnswer('skip')));
    if (q.canUndo) g2.append(mk('btn small', 'Vissza', q.onUndo));
    root.append(g2);
    root.append(el('div', 'small', 'Billentyűk: N nyugodt · M közepes · H hangos · szóköz kihagy · Z vissza. A számok és a forrás szándékosan rejtve.'));
    root.append(el('div', 'small qrule', 'Hangos = a cím felkiáltójellel, NAGYBETŰVEL, érzelmi vagy túlzó szavakkal, titokzatos ígérettel hajt, akkor is, ha a cikk igaz. Nyugodt = a cím higgadtan közli a lényeget. Közepes = a kettő között, vagy nem tudod eldönteni.'));
  } else root.append(el('div', 'qtitle', 'Elfogyott a magyar hír, ami még nem kapott szavazatot. Később új hírek jönnek.'));
}

// Vak újracímkézés kártya: csak a cím látszik, a szám és a forrás szándékosan rejtve.
function renderBlind(box, b) {
  const mk = (txt, fn) => { const x = el('button', 'btn small', txt); x.type = 'button'; x.addEventListener('click', fn); return x; };
  if (!b.open) {
    box.append(mk(b.total ? `Vak újracímkézés folytatása (${b.answered}/${b.total})` : 'Vak újracímkézés indítása (100 magyar hír)', b.onStart));
    if (b.total && b.onNew) box.append(mk('Új vak minta (csak magyar hírek)', b.onNew));
    return;
  }
  const card = el('div', 'blindcard');
  card.append(el('div', 'small', `Vak újracímkézés: ${b.answered}/${b.total} · a számok és a forrás szándékosan rejtve`));
  if (b.title) {
    card.append(el('div', 'blindtitle', b.title));
    card.append(mk('Nyugodt', () => b.onAnswer(0)), mk('Hangos', () => b.onAnswer(1)), mk('Kihagy', () => b.onAnswer(-1)));
  } else card.append(el('div', 'small', 'Kész. Az eredményt az „Audit futtatása” mutatja.'));
  card.append(mk('Bezárás (mentve)', b.onClose));
  if (b.onNew) card.append(mk('Új minta (csak magyar hírek)', b.onNew));
  box.append(card);
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
  // Vak szavazás: a szavazásig nem látszik az ATM, az S, az AI-érték, a szín (és alapból a forrás neve); a szavazás vagy a „Miért?” után feltárul.
  const hidden = !!ctx.blindVote && !ctx.votes.has(it.id) && !(ctx.revealed && ctx.revealed.has(it.id));
  const c = el('article', 'card ' + (hidden ? 'blind' : 'lvl-' + level(it.atm, ctx.th)) + (it.alert ? ' alert' : ''));
  if (it.alert) c.append(el('span', 'badge', 'HIVATALOS FIGYELMEZTETÉS'));
  const t = el('a', 'title', it.title);
  t.href = safeHref(it.link); t.target = '_blank'; t.rel = 'noopener noreferrer';
  t.addEventListener('click', () => ctx.onOpen(it));
  const srcTxt = hidden && !ctx.showSource ? '' : `${it.source || it.source_domain || '?'} · `;
  c.append(t, el('div', 'meta', `${srcTxt}${ctx.regionLabel(it.region)} · ${relTime(it.published)}`));

  if (!hidden) {
    const bar = el('div', 'bar'); const fill = document.createElement('i');
    fill.style.width = Math.min(100, (it.atm / atmRef()) * 100) + '%'; bar.append(fill); c.append(bar);

    const nums = el('div', 'nums');
    [`ATM ${fmtAtm(it.atm, 2)}`, `V ${it.v.toFixed(2)}`, `S ${it.Seff.toFixed(2)}`, `AI ${it.sAi.toFixed(2)}`, `G ${it.G.toFixed(2)}`]
      .forEach(x => nums.append(el('span', '', x)));
    c.append(nums);
  }

  const mine = ctx.votes.get(it.id);
  const acts = el('div', 'acts');
  // Csak magyar nyelvű címre lehet szavazni (alapból): a fordított vagy ismeretlen nyelvű cím ítélete nem a cím stílusát mérné.
  const blockedLang = !mine && !!ctx.langOk && !ctx.langOk(it);
  if (blockedLang) acts.append(el('span', 'small langnote', 'Ezen a nyelven nem szavazol (a nyelvek az Öntanuló AI panelben állíthatók), vagy bizonytalan a nyelv.'));
  else [['fact', 'Nyugodt'], ['bait', 'Hangos']].forEach(([k, label]) => {
    const b = el('button', 'vote ' + k, label);
    b.type = 'button'; b.setAttribute('aria-pressed', String(mine === k));
    b.addEventListener('click', () => ctx.onVote(it, k));
    acts.append(b);
  });
  const why = el('button', 'vote why', 'Miért?'); why.type = 'button';
  const box = el('div', 'explain'); box.hidden = true;
  why.addEventListener('click', () => {
    if (hidden) { if (ctx.onReveal) ctx.onReveal(it.id); return; }  // a „Miért?” feltárja a számokat (a későbbi szavazat nem számít vaknak)
    box.hidden = !box.hidden;
    if (!box.hidden && !box.childNodes.length) ctx.explain(it).forEach(l => box.append(el('div', '', l)));
  });
  acts.append(why);
  c.append(acts, box);
  // Kétlépéses címkézés: a cikk megnyitása után második, elolvasás utáni ítélet (a tanulót nem módosítja).
  if (mine && ctx.opened && ctx.opened.has(it.id) && ctx.onVote2) {
    const mine2 = ctx.votes2 && ctx.votes2.get(it.id);
    const r2 = el('div', 'acts acts2');
    r2.append(el('span', 'small', 'Elolvasás után a cikk teljesítette a címet?'));
    [['fact', 'Teljesíti'], ['bait', 'Nem teljesíti']].forEach(([k, label]) => {
      const b = el('button', 'vote ' + k, label);
      b.type = 'button'; b.setAttribute('aria-pressed', String(mine2 === k));
      b.addEventListener('click', () => ctx.onVote2(it, k));
      r2.append(b);
    });
    c.append(r2);
  }
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
  if (handlers.onToggleBlindVote) {
    const t1 = el('button', 'btn small', `Vak szavazás: ${handlers.blindVote ? 'BE' : 'KI'} (koppints a váltáshoz)`);
    t1.type = 'button'; t1.addEventListener('click', handlers.onToggleBlindVote);
    const t2 = el('button', 'btn small', `Forrás neve szavazás előtt: ${handlers.showSource ? 'látszik' : 'rejtve'}`);
    t2.type = 'button'; t2.addEventListener('click', handlers.onToggleSource);
    box.append(t1, t2);
    if (handlers.onSetVoter) {
      box.append(el('div', 'small', `Szavazó (anonim betű; minden szavazó más betűt válasszon). Váltáskor az alkalmazás a kiválasztott szavazó saját szavazatait, sorait és tanulóját tölti be; a többieké nem látszik${handlers.voterChosen ? '' : ' – még nem választottad ki!'}:`));
      const sel = el('select'); sel.setAttribute('aria-label', 'Szavazó-azonosító');
      'ABCDEFGHIJ'.split('').forEach(c => { const o = el('option', '', c); o.value = c; sel.append(o); });
      sel.value = handlers.voter;
      sel.addEventListener('change', () => handlers.onSetVoter(sel.value));
      box.append(sel);
      box.append(el('div', 'small', 'Szavazható nyelvek (csak azokat a híreket kapod szavazásra, amiket olvasol):'));
      (handlers.langs || []).forEach(l => {
        const b = el('button', 'btn small', `${l.label}: ${l.on ? 'BE' : 'KI'}`);
        b.type = 'button'; b.addEventListener('click', () => handlers.onToggleLang(l.code));
        box.append(b);
      });
    }
    box.append(el('div', 'small', 'Címkézési szabály (a cím stílusa, nem a cikk igazsága): Hangos = a cím felkiáltójellel, NAGYBETŰVEL, érzelmi vagy túlzó szavakkal, titokzatos ígérettel hajt, akkor is, ha a cikk igaz. Nyugodt = a cím higgadtan közli a lényeget. Közepes = a kettő között, vagy nem tudod eldönteni. Vak módban a szűrő maradjon „Minden hír” állapotban.'));
  }
  if (handlers.onQuick) {
    const qb = el('button', 'btn small', 'Gyorsszavazás indítása (csak magyar hírek)');
    qb.type = 'button'; qb.addEventListener('click', handlers.onQuick);
    box.append(qb);
    if (handlers.quickInfo) box.append(el('div', 'small', handlers.quickInfo));
  }
  if (handlers.blind) renderBlind(box, handlers.blind);
  if (handlers.backup) renderBackup(box, handlers.backup);
  if (handlers.onAudit) {
    const a = el('button', 'btn small', handlers.auditText ? 'Audit újrafuttatása' : 'Audit futtatása');
    a.type = 'button';
    a.addEventListener('click', handlers.onAudit);
    box.append(a);
    if (handlers.auditText) {
      box.append(el('pre', 'auditpre', handlers.auditText));
      const c = el('button', 'btn small', 'Audit másolása');
      c.type = 'button';
      c.addEventListener('click', handlers.onAuditCopy);
      box.append(c);
    }
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
