// ATM, P90, Tény/Clickbait és regionális szűrők.
import { quantile } from './model.js';

export class FilterEngine {
  constructor(rows) { this.rows = rows; }

  getFiltered({ region = 'ALL', maxAtm = 1, type = 'all', votes = new Map() } = {}) {
    return this.rows.filter(r => {
      if (region !== 'ALL' && r.region !== region) return false;
      if (r.atm > maxAtm) return false;
      const v = votes.get(r.id);
      if (type === 'fact') return v === 'fact';
      if (type === 'bait') return v === 'bait';
      if (type === 'unvoted') return !v;
      return true;
    });
  }

  getStats(rows) {
    if (!rows.length) return { avgAtm: 0, p90: 0, n: 0 };
    const sorted = rows.map(r => r.atm).sort((a, b) => a - b);
    return { avgAtm: sorted.reduce((a, b) => a + b, 0) / sorted.length, p90: quantile(sorted, 0.9), n: rows.length };
  }
}
