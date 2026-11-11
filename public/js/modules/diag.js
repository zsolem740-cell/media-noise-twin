// Diagnosztika: tömör, pontos szöveg a vágólapra (beszélgetésbe illesztéshez, kevés tokenért).
import { quantile, fmtAtm, scoringMode } from './model.js';

export const APP_VERSION = 'v47.4';
const cut = (t, n) => (t.length > n ? t.slice(0, n - 1) + '…' : t);

export function buildDiag(s) {
  const rows = s.rows || [];
  const data = s.data || {};
  const th = (s.model && s.model.thresholds) || { low: 0, high: 0 };
  const L = [];
  const now = s.now || Date.now();
  const age = data.generated_at ? Math.max(0, Math.round((now - Date.parse(data.generated_at)) / 60000)) : null;
  const cfg = data.config;
  const cfgText = !cfg ? '?' : cfg.warning ? `FIGYELMEZTETÉS: ${cfg.warning}` : cfg.user ? 'user.json OK' : 'alap';
  L.push(`MNT DIAG ${APP_VERSION} · ${scoringMode()} · ${new Date(now).toISOString().slice(0, 16)}Z`);
  L.push(`adat: ${rows.length} hír · frissítve ${age === null ? '?' : age + ' perce'} · config: ${cfgText}`);

  const atm = rows.map(r => r.atm).sort((a, b) => a - b);
  if (atm.length) {
    const mean = atm.reduce((a, b) => a + b, 0) / atm.length;
    const hi = atm.filter(a => a >= th.high).length, mid = atm.filter(a => a >= th.low && a < th.high).length;
    L.push(`ATM: átlag ${fmtAtm(mean)} · p90 ${fmtAtm(quantile(atm, 0.9))} · sárga ≥ ${fmtAtm(th.low)}: ${mid} db · piros ≥ ${fmtAtm(th.high)}: ${hi} db`);
  }

  const by = new Map();
  rows.forEach(r => { const g = by.get(r.region) || { n: 0, sum: 0 }; g.n++; g.sum += r.atm; by.set(r.region, g); });
  const label = s.regionLabel || (x => x);
  if (by.size) L.push('régiók: ' + [...by.entries()].sort((a, b) => b[1].n - a[1].n).map(([k, g]) => `${label(k)} ${fmtAtm(g.sum / g.n)} (${g.n})`).join(' · '));

  const newest = new Map();
  rows.forEach(r => { const t = Date.parse(r.published); if (t && (!newest.has(r.region) || t > newest.get(r.region))) newest.set(r.region, t); });
  if (newest.size) L.push('legfrissebb hír régiónként (óra): ' + [...newest.entries()].map(([k, t]) => { const h = Math.max(0, (now - t) / 3600000); return `${label(k)} ${h < 10 ? h.toFixed(1) : Math.round(h)}`; }).join(' · '));

  const votes = s.votes || [];
  const c = s.cal;
  const nBait = c ? c.n1 : votes.filter(v => v.vote === 'bait').length;
  const nFact = c ? c.n0 : votes.length - nBait;
  let ai = `AI: ${votes.length} szavazat (${nBait} clickbait / ${nFact} tény) · λ ${Math.round((s.lam || 0) * 100)}% · alapszint ${(s.aiBase || 0).toFixed(2)}`;
  if (c && c.usable) ai += ` · AUC szabály ${c.aucRule.toFixed(2)} / AI ${c.aucAi.toFixed(2)} / keverék ${c.best.auc.toFixed(2)}`;
  L.push(ai);

  const src = (data.insights && data.insights.sources) || [];
  if (src.length) L.push('források (≥5 hír, legzajosabb): ' + src.slice(0, 5).map(x => `${x.domain} ${fmtAtm(x.mean_ATM)} (${x.n})`).join(', '));

  const rs = data.research && data.research.status;
  if (rs) {
    const okN = rs.ok ? rs.ok.length : 0, failN = rs.failed ? Object.keys(rs.failed).length : 0;
    const via = rs.via && Object.keys(rs.via).length ? ' (' + Object.entries(rs.via).map(([k, v]) => `${k} ${v}`).join(', ') + ')' : '';
    let t = `piaci napló: ${rs.news_days || 0} hírnap · ár ${okN}/${okN + failN} OK${via} · utolsó ár ${rs.price_last || '–'}`;
    const f = rs.failed ? Object.entries(rs.failed).slice(0, 3).map(([k, v]) => `${k} (${v})`).join(', ') : '';
    if (f) t += ` · hiba: ${f}`;
    if (rs.match_now) t += ` · most ${rs.match_now.n} cégegyezés`;
    const e = rs.eval;
    if (e) t += e.state === 'kész'
      ? ` · igazolt ${Math.round(e.confirmed * 100)}% (véletlen ${Math.round(e.baseline * 100)}%, p=${e.p_confirm}) · ATM→eltúlzott AUC ${e.auc} (p=${e.p_auc})`
      : ` · értékelés: gyűjt ${e.n}/${e.need}`;
    L.push(t);
  }

  const hl = (data.health || []).map(h => h.id).join(', ');
  const mb = data.summary && data.summary.bytes ? (data.summary.bytes / 1e6).toFixed(2) : '?';
  const bk = s.lastBackup ? Math.floor((now - s.lastBackup) / 86400000) + ' napja' : 'még nem';
  L.push(`egészség: ${hl || 'rendben'} · adatfájl ${mb} MB · szavazatmentés: ${bk}`);

  const top = [...rows].sort((a, b) => b.atm - a.atm).slice(0, 3);
  if (top.length) L.push('legzajosabb hírek: ' + top.map(r => `${fmtAtm(r.atm)} · ${cut(r.title || '', 55)} (${r.source_domain || '?'})`).join(' | '));
  return L.join('\n');
}
