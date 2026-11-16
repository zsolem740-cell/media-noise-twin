// Közös segédek a JS-tesztekhez: csak szintetikus adat, valódi szavazat soha nem kerül a repóba.
export const T0 = Date.UTC(2026, 10, 1);
export const HOUR = 3600e3;

// Egy szavazat-rekord az alkalmazás formátumában (b: 1 = hangos / bait, 0 = nyugodt / fact).
export function vote(id, b, extra = {}) {
  return { id: String(id), vote: b ? 'bait' : 'fact', title: `Szintetikus cím ${id}`, domain: 'pelda.hu', sRule: b ? 0.6 : 0.1, sAi: b ? 0.7 : 0.2,
    atm: b ? 400 : 50, ts: T0 + Number(String(id).replace(/\D/g, '') || 0) * 1000, lang: 'hu', ...extra };
}

// Két címkesor, amelyre a kappa kézzel számolható:
// egyezés 8/10 = 0,8; pa = pb = 0,4; pe = 0,4·0,4 + 0,6·0,6 = 0,52; kappa = (0,8 − 0,52) / 0,48 = 0,58333…
export const A10 = [1, 1, 0, 0, 1, 0, 0, 0, 1, 0];
export const B10 = [1, 0, 0, 0, 1, 0, 1, 0, 1, 0];
export const KAPPA10 = (0.8 - 0.52) / 0.48;

export const near = (x, y, eps = 1e-9) => Math.abs(x - y) <= eps;

// Determinisztikus véletlen a tesztekhez.
export function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
