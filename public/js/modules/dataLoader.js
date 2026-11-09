// Nyitott adatfolyam: friss JSON a hálózatról (a gyorsítótárat az IndexedDB és a service worker adja).
export async function fetchJson() {
  let last;
  for (const u of ['atm_history.json', '../data/metrics/atm_history.json']) {
    try {
      const r = await fetch(u, { cache: 'no-store' });
      if (r.ok) return await r.json();
      last = new Error('HTTP ' + r.status);
    } catch (e) { last = e; }
  }
  throw last;
}
