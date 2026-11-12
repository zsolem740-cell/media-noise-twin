// Teljes mentés és helyreállítás: szavazatok, „közepes” jelölések, rejtett ismétlések, beállítások, vak minta.
// Három út: megosztás (Drive, Keep…), vágólap, és opcionálisan automatikus feltöltés egy PRIVÁT GitHub-tárolóba (szűkre szabott kulccsal).
// A kulcs soha nem kerül a mentésbe, és a feltöltés megtagadva, ha a tároló nyilvános.
export const BACKUP_FORMAT = 'mnt-backup';
export const BACKUP_VERSION = 1;
const VOTES = ['fact', 'bait', 'mid'];
const FIELDS = ['id', 'domain', 'vote', 'title', 'sRule', 'sAi', 'S0', 'S', 'V', 'region', 'atm', 'ts', 'blind', 'srcShown', 'lang', 'queue', 'quick', 'shared', 'voter', 'ver', 'vote2', 'ts2', 'mig'];

const compact = v => { const o = {}; FIELDS.forEach(k => { if (v[k] !== undefined && v[k] !== null) o[k] = v[k]; }); return o; };

export function buildBackup(s, now = Date.now()) {
  return {
    format: BACKUP_FORMAT, version: BACKUP_VERSION, created: new Date(now).toISOString(), app: s.app || '', voter: s.voter || '',
    counts: { votes: (s.votes || []).length, mids: (s.mids || []).length, repeats: (s.repeats || []).length },
    votes: (s.votes || []).map(compact), mids: (s.mids || []).map(compact),
    repeats: s.repeats || [], skipped: [...(s.skipped || [])], prefs: s.prefs || {},
    blind: s.blind || null, blindPrev: s.blindPrev || null,
  };
}
export const serialize = b => JSON.stringify(b);

const num = x => x === undefined || (typeof x === 'number' && Number.isFinite(x));
export function validVote(v) {
  return !!v && typeof v === 'object' && typeof v.id === 'string' && v.id.length > 0 && v.id.length <= 300 && VOTES.includes(v.vote)
    && typeof v.title === 'string' && v.title.length > 0 && v.title.length <= 1000
    && num(v.sRule) && num(v.sAi) && num(v.atm) && num(v.ts) && (v.domain === undefined || typeof v.domain === 'string');
}

// Beolvasás: a teljes mentést és a régi, sima szavazat-listát (JSON tömb) is elfogadja. Csak adatot olvas, kódot soha nem futtat.
export function parseBackup(text) {
  const t = String(text || '').trim();
  if (!t) return { ok: false, error: 'üres szöveg' };
  if (t.length > 60e6) return { ok: false, error: 'túl nagy fájl' };
  let j; try { j = JSON.parse(t); } catch (_) { return { ok: false, error: 'nem érvényes JSON (a szöveg sérült vagy csonka)' }; }
  let obj;
  if (Array.isArray(j)) obj = { format: BACKUP_FORMAT, version: 1, votes: j.filter(x => x && x.vote !== 'mid'), mids: j.filter(x => x && x.vote === 'mid'), legacy: true };
  else if (j && j.format === BACKUP_FORMAT) obj = j;
  else return { ok: false, error: 'ez nem a Média-Zaj mentése' };
  if (!(obj.version <= BACKUP_VERSION)) return { ok: false, error: 'újabb verziójú mentés: előbb frissítsd az alkalmazást' };
  const rawV = Array.isArray(obj.votes) ? obj.votes : [], rawM = Array.isArray(obj.mids) ? obj.mids : [];
  if (rawV.length + rawM.length > 300000) return { ok: false, error: 'túl sok szavazat' };
  const votes = rawV.filter(validVote).map(compact), mids = rawM.filter(validVote).map(compact);
  const invalid = rawV.length + rawM.length - votes.length - mids.length;
  if (invalid > (rawV.length + rawM.length) * 0.5) return { ok: false, error: 'a mentés nagy része sérült' };
  return { ok: true, data: { votes, mids, repeats: Array.isArray(obj.repeats) ? obj.repeats.filter(r => r && typeof r.id === 'string') : [],
    skipped: Array.isArray(obj.skipped) ? obj.skipped.filter(x => typeof x === 'string') : [], prefs: obj.prefs && typeof obj.prefs === 'object' ? obj.prefs : {},
    voter: typeof obj.voter === 'string' ? obj.voter : '',
    blind: obj.blind && Array.isArray(obj.blind.items) ? obj.blind : null, blindPrev: obj.blindPrev && Array.isArray(obj.blindPrev.items) ? obj.blindPrev : null,
    created: obj.created || '', legacy: !!obj.legacy }, stats: { valid: votes.length + mids.length, invalid } };
}

// Egyesítés azonosító szerint: soha nem töröl; ütközésnél az újabb időbélyegű marad.
export function planRestore(existingVotes, existingMids, incoming) {
  const map = new Map();
  existingVotes.concat(existingMids).forEach(v => map.set(v.id, v));
  const write = []; const stats = { added: 0, updated: 0, same: 0 };
  incoming.votes.concat(incoming.mids).forEach(v => {
    const cur = map.get(v.id);
    if (!cur) { map.set(v.id, v); write.push(v); stats.added++; }
    else if ((v.ts || 0) > (cur.ts || 0)) { map.set(v.id, v); write.push(v); stats.updated++; }
    else stats.same++;
  });
  const all = [...map.values()];
  return { votes: all.filter(v => v.vote !== 'mid'), mids: all.filter(v => v.vote === 'mid'), write, stats };
}

// ---- GitHub (privát tároló, Contents API) ----
export function toBase64Utf8(str) {
  const bytes = new TextEncoder().encode(str); let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
export const validRepoRef = s => /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/.test(String(s || '').trim());
export const maskToken = t => (t ? '••••' + String(t).slice(-4) : '');
export function ghErrorText(status) {
  if (status === 401) return 'a kulcs hibás vagy lejárt (hozz létre újat a GitHubon)';
  if (status === 403) return 'a kulcsnak nincs jogosultsága, vagy korlátozás van érvényben';
  if (status === 404) return 'a tároló vagy a fájl nem található (a tároló neve és a kulcs hozzáférése?)';
  if (status === 409 || status === 422) return 'ütközés a feltöltésnél, próbáld újra';
  return `a GitHub hibát jelzett (${status})`;
}
const hdr = (token, accept = 'application/vnd.github+json') => ({ Authorization: `Bearer ${token}`, Accept: accept, 'X-GitHub-Api-Version': '2022-11-28' });
const apiUrl = cfg => `https://api.github.com/repos/${cfg.repo}/contents/${cfg.path || 'szavazatok.json'}`;

// A feltöltés előtt kötelező ellenőrzés: a tároló PRIVÁT-e.
export async function ghRepoPrivate(cfg, fetchFn = fetch) {
  try {
    const r = await fetchFn(`https://api.github.com/repos/${cfg.repo}`, { headers: hdr(cfg.token) });
    if (r.status !== 200) return { ok: false, error: ghErrorText(r.status) };
    const j = await r.json();
    return j.private === true ? { ok: true } : { ok: false, error: 'a tároló NYILVÁNOS, a mentés megtagadva (hozz létre privát tárolót)' };
  } catch (_) { return { ok: false, error: 'nincs hálózat' }; }
}

export async function ghPut(cfg, content, message, fetchFn = fetch) {
  try {
    for (let attempt = 0; attempt < 2; attempt++) {
      let sha;
      const g = await fetchFn(apiUrl(cfg), { headers: hdr(cfg.token) });
      if (g.status === 200) sha = (await g.json()).sha;
      else if (g.status !== 404) return { ok: false, status: g.status, error: ghErrorText(g.status) };
      const body = JSON.stringify(Object.assign({ message, content: toBase64Utf8(content) }, sha ? { sha } : {}));
      const p = await fetchFn(apiUrl(cfg), { method: 'PUT', headers: Object.assign(hdr(cfg.token), { 'Content-Type': 'application/json' }), body });
      if (p.status === 200 || p.status === 201) return { ok: true, created: p.status === 201 };
      if ((p.status === 409 || p.status === 422) && attempt === 0) continue;
      return { ok: false, status: p.status, error: ghErrorText(p.status) };
    }
    return { ok: false, error: ghErrorText(409) };
  } catch (_) { return { ok: false, error: 'nincs hálózat' }; }
}

export async function ghGet(cfg, fetchFn = fetch) {
  try {
    const r = await fetchFn(apiUrl(cfg), { headers: hdr(cfg.token, 'application/vnd.github.raw+json') });
    if (r.status !== 200) return { ok: false, status: r.status, error: ghErrorText(r.status) };
    return { ok: true, text: await r.text() };
  } catch (_) { return { ok: false, error: 'nincs hálózat' }; }
}

// Automatikus mentés: naponta egyszer, ha változott, vagy +100 új szavazatnál.
export function shouldAutoBackup(meta, nVotes, now = Date.now()) {
  if (!meta || !meta.repo || !meta.token) return false;
  if (!meta.last) return true;
  const age = now - meta.last;
  if (nVotes - (meta.count || 0) >= 100) return age > 10 * 60e3;   // sűrű ismétlődés ellen legalább 10 perc
  return age > 24 * 3600e3 && nVotes !== (meta.count || 0);
}
