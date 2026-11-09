// Web Share Target: megosztott cím/szöveg/URL elemzése a modellel.
import { domainOf, tierOf, realityIndex, ruleParts, adjustV, atmValue, level, clamp, fmtAtm } from './model.js';
import { $, el } from './uiRenderer.js';

export function parseShare() {
  const p = new URLSearchParams(location.search);
  if (!(p.has('url') || p.has('text') || p.has('title'))) return null;
  const title = p.get('title') || '';
  let text = p.get('text') || '';
  let url = p.get('url') || '';
  if (!url) {
    const m = text.match(/https?:\/\/\S+/);
    if (m) { url = m[0]; text = text.replace(m[0], '').trim(); }
  }
  history.replaceState(null, '', location.pathname);
  return { text: (title + ' ' + text).trim(), url };
}

export function openShare(s, ctx) {
  $('shareText').value = s.text;
  $('shareUrl').value = s.url;
  const sel = $('shareRegion');
  sel.replaceChildren();
  const regs = ctx().model ? ctx().model.regions : [{ code: 'HU-VA', name: 'Vas megye' }];
  regs.forEach(r => { const o = el('option', '', `${r.short || r.code} – ${r.name}`); o.value = r.code; sel.append(o); });
  $('shareResult').replaceChildren();
  $('shareModal').showModal();
  if (ctx().model) analyze(ctx);
}

export function analyze(ctx) {
  const box = $('shareResult');
  box.replaceChildren();
  const { model: m, learner, lam, aiBase, net } = ctx();
  if (!m) { box.append(el('p', '', 'Még nincs modell: az első betöltéshez hálózat kell.')); return; }
  const text = $('shareText').value.trim();
  const url = $('shareUrl').value.trim();
  const region = $('shareRegion').value;
  const dom = domainOf(url);
  const tier = tierOf(dom, m.trust);
  const v = adjustV(realityIndex(dom, m.trust), net.get(dom) || 0);
  const parts = ruleParts(text, m);
  const sAi = text && learner.boot ? learner.predict(text) : parts.S;
  const s = clamp((1 - lam) * parts.S + lam * Math.max(0, sAi - (aiBase || 0)), 0, 1);
  const g = m.weights[region] !== undefined ? m.weights[region] : 0.5;
  const a = atmValue(v, s, g);

  box.append(el('div', 'big ' + { low: 'lo', mid: 'mid', high: 'hi' }[level(a, m.thresholds)], 'ATM ' + fmtAtm(a)));
  box.append(el('p', '', `V ${v.toFixed(2)} (${tier === 'default' ? 'ismeretlen' : (m.trust[tier].label || tier)}${dom ? ', ' + dom : ''}) · S ${s.toFixed(2)} (szabály ${parts.S.toFixed(2)}, AI ${sAi.toFixed(2)}) · G ${g.toFixed(2)}`));
  if (parts.kw.length) box.append(el('p', '', 'Kulcsszavak: ' + parts.kw.join(', ')));
  if (!text) box.append(el('p', '', 'Szöveg nélkül csak a forrás megbízhatósága számít. Illeszd be a címet a pontosabb S értékhez.'));
  if (!dom) box.append(el('p', '', 'Nincs érvényes URL, így a forrás ismeretlennek számít.'));
}
