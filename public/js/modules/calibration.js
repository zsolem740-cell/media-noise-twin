// Kalibráció a saját szavazatokból: előrejelző (prequential) kiértékelés AUC-val.
// A szavazatnál elmentjük a szabály-S-t és az AI tanulás ELŐTTI becslését, így a mérés nem a tanítóadaton történik.
import { clamp } from './model.js';
import { lambdaFor } from './learner.js';

export function auc(scores, labels) {
  let pos = 0, win = 0;
  for (let i = 0; i < scores.length; i++) {
    if (!labels[i]) continue;
    pos++;
    for (let j = 0; j < scores.length; j++) {
      if (labels[j]) continue;
      win += scores[i] > scores[j] ? 1 : scores[i] === scores[j] ? 0.5 : 0;
    }
  }
  const neg = scores.length - pos;
  return pos && neg ? win / (pos * neg) : 0.5;
}

export function calibrate(votes) {
  const v = votes.filter(x => Number.isFinite(x.sRule) && Number.isFinite(x.sAi));
  const y = v.map(x => (x.vote === 'bait' ? 1 : 0));
  const n1 = y.filter(Boolean).length, n0 = y.length - n1;
  if (n1 < 5 || n0 < 5) return { n: v.length, n1, n0, ready: false, usable: false };
  const aucRule = auc(v.map(x => x.sRule), y), aucAi = auc(v.map(x => x.sAi), y);
  let best = { lam: 0, auc: aucRule };
  for (let k = 1; k <= 9; k++) {
    const l = k / 10;
    const a = auc(v.map(x => (1 - l) * x.sRule + l * x.sAi), y);
    if (a > best.auc + 1e-9) best = { lam: l, auc: a };
  }
  return { n: v.length, n1, n0, ready: true, aucRule, aucAi, best, usable: v.length >= 30 && n1 >= 8 && n0 >= 8 };
}

// Az AI súlya az S értékben: kalibrált, ha van elég adat, különben a szavazatszámból számolt.
export const lambdaFinal = (votesCount, cal) => (cal && cal.usable ? clamp(cal.best.lam, 0.1, 0.8) : lambdaFor(votesCount));
