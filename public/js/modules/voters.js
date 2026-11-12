// Szavazónkénti tárolás: tiszta (tárolótól és felülettől független) logika.
// Egy eszközön több szavazó is címkézhet: minden szavazat kulcsa a szavazó betűje ÉS a hír azonosítója,
// így ugyanarra a hírre mindkét szavazat külön megmarad, és egyik szavazó sem látja a másikét.
export const VOTERS = 'ABCDEFGHIJ'.split('');
export const validVoter = v => typeof v === 'string' && /^[A-J]$/.test(v);

// A szavazó-jelölés (v47.9) előtt egyetlen szavazó volt: az ő jelöletlen szavazatai ide kerülnek.
export const LEGACY_VOTER = 'A';

export const vkey = (base, voter) => `${base}:${voter}`;          // szavazónkénti localStorage-kulcs
export const recKey = (voter, id) => `${voter}|${id}`;            // szavazónkénti rekordkulcs az adatbázisban
export const cloudPath = voter => `szavazatok-${voter}.json`;     // szavazónkénti fájl a felhő-mentésben
export const LEGACY_CLOUD_PATH = 'szavazatok.json';

const usable = r => !!r && typeof r === 'object' && typeof r.id === 'string' && r.id.length > 0;
const ownerOf = (r, fallback) => (validVoter(r.voter) ? r.voter : fallback);

// Kié a régi, közös állapot (jelöletlen szavazatok, tanuló, ismétlések, kihagyottak)?
// Ha van jelöletlen (v47.9 előtti) szavazat, az egyetlen akkori szavazóé; különben az eszközön kiválasztott szavazóé.
export function legacyOwner(records, currentVoter) {
  if ((records || []).some(r => usable(r) && !validVoter(r.voter))) return LEGACY_VOTER;
  return validVoter(currentVoter) ? currentVoter : LEGACY_VOTER;
}

// Áttöltés a régi (hírenként egy rekordos) tárolóból: csak másol, a régi tárolóból semmit nem töröl.
// - ami az új tárolóban már megvan (existingKeys), azt nem írja felül;
// - `since`: az előző áttöltés ideje; utána csak az annál újabb régi rekordokat hozza át (egy régi kóddal nyitva maradt lap szavazatai);
// - az áthozott rekord `mig: true` jelölést kap: a közös tárolós időszakból való, az elemzésből kiszűrhető.
export function planMigration(oldRecords, existingKeys = new Set(), currentVoter = LEGACY_VOTER, since = 0) {
  const all = oldRecords || [];
  const owner = legacyOwner(all, currentVoter);
  const entries = [], byVoter = {};
  let invalid = 0, present = 0, old = 0, unlabeled = 0;
  for (const r of all) {
    if (!usable(r)) { invalid++; continue; }
    if (since && !((r.ts || 0) > since)) { old++; continue; }
    const voter = ownerOf(r, owner), key = recKey(voter, r.id);
    if (existingKeys.has(key)) { present++; continue; }
    if (!validVoter(r.voter)) unlabeled++;
    entries.push({ key, value: Object.assign({}, r, { voter, mig: true }) });
    byVoter[voter] = (byVoter[voter] || 0) + 1;
  }
  return { owner, entries, stats: { total: all.length, copied: entries.length, unlabeled, invalid, present, old, byVoter } };
}

// A régi, közös localStorage-kulcsok másolása a régi állapot tulajdonosához (csak ha neki még nincs sajátja; a régi kulcs megmarad).
export const LOCAL_KEYS = ['mnt-repeats', 'mnt-skip', 'mnt-blind', 'mnt-blind-prev', 'mnt-cloud', 'mnt-backup', 'mnt-langs'];
export function planLocalCopy(getItem, owner) {
  const out = [];
  for (const base of LOCAL_KEYS) {
    const val = getItem(base);
    if (val !== null && val !== undefined && getItem(vkey(base, owner)) === null) out.push([vkey(base, owner), val]);
  }
  return out;
}

// Az eszközön lévő összes szavazat szavazónként (az egyeztetéshez): [{ voter, votes }], betűrendben.
export function localSets(records) {
  const m = new Map();
  (records || []).forEach(r => { if (usable(r) && validVoter(r.voter)) (m.get(r.voter) || m.set(r.voter, []).get(r.voter)).push(r); });
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([voter, votes]) => ({ voter, votes }));
}

// Mit lehet egy beolvasott mentésből az adott szavazóhoz visszaállítani?
// - a mentés fejlécében álló szavazó a tulajdonos; fejléc nélkül (v47.9 előtti mentés) az akkori egyetlen szavazó;
// - a rekord saját jelölése erősebb a fejlécnél (közös eszközről származó, kevert mentés);
// - más szavazó rekordja soha nem kerül ide; a kiegészítő adatok (ismétlések, kihagyottak, vak minta, beállítások) csak a tulajdonosnak járnak.
export function restoreScope(data, voter) {
  const owner = validVoter(data.voter) ? data.voter : LEGACY_VOTER;
  const pick = list => (list || []).filter(r => ownerOf(r, owner) === voter).map(r => Object.assign({}, r, { voter }));
  const votes = pick(data.votes), mids = pick(data.mids);
  const total = (data.votes || []).length + (data.mids || []).length, others = total - votes.length - mids.length;
  if (total > 0 && votes.length + mids.length === 0) {
    const owners = [...new Set((data.votes || []).concat(data.mids || []).map(r => ownerOf(r, owner)))].sort().join(', ');
    return { ok: false, error: `ez a(z) ${owners} szavazó mentése, ide (${voter}) nem állítható vissza: használd az Egyeztetés gombot` };
  }
  const own = owner === voter;
  return { ok: true, others, data: Object.assign({}, data, { votes, mids, voter,
    repeats: own ? data.repeats || [] : [], skipped: own ? data.skipped || [] : [], prefs: own ? data.prefs || {} : {},
    blind: own ? data.blind || null : null, blindPrev: own ? data.blindPrev || null : null }) };
}

// Több mentést tartalmazó szövegből (soronként egy: „minden helyi szavazó mentése”) az adott szavazóhoz tartozó kiválasztása.
// `parsed`: a sikeresen beolvasott mentések (parseBackup eredményei). Előny: amelyikben van neki szóló rekord, azon belül amelyiknek a fejlécében ez a szavazó áll; több ilyen közül a legfrissebb.
export function pickBackupFor(parsed, voter) {
  const cands = (parsed || []).map(p => ({ p, sc: restoreScope(p.data, voter), own: (validVoter(p.data.voter) ? p.data.voter : LEGACY_VOTER) === voter }));
  const ok = cands.filter(c => c.sc.ok);
  if (!ok.length) return { ok: false, error: cands.length > 1 ? `a fájl ${cands.length} mentése közül egyik sem a(z) ${voter} szavazóé: használd az Egyeztetés gombot` : cands.length ? cands[0].sc.error : 'nincs beolvasható mentés' };
  const n = c => c.sc.data.votes.length + c.sc.data.mids.length;
  ok.sort((a, b) => ((n(b) > 0) - (n(a) > 0)) || (b.own - a.own) || String(b.p.data.created || '').localeCompare(String(a.p.data.created || '')));
  return { ok: true, p: ok[0].p, sc: ok[0].sc, total: cands.length };
}

// Vak-e a szavazat: csak akkor, ha a kártya a szavazás pillanatában tényleg rejtve volt
// (a vak mód be van kapcsolva, a „Miért?” nem tárta fel, és a szavazónak még nem volt szavazata a hírre: a saját szavazat után a kártya feltárul).
export const blindAtVote = (blindMode, revealed, hadOwnVote) => !!blindMode && !revealed && !hadOwnVote;
