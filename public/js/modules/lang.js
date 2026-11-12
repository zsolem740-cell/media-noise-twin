// Egyszerű, könyvtár nélküli nyelvfelismerés a hírcímekhez: magyar / egyéb / ismeretlen.
// Jelek: magyar betűk (ő, ű, á, é, í, ó, ú), gyakori magyar és más nyelvű (angol, német, szlovén/horvát/szlovák) töltelékszavak, .hu domain.
// Cél nem a pontos nyelvazonosítás, hanem annak eldöntése, hogy a magyar nyelvű szavazó értékelheti-e a címet.

const W = s => new Set(s.split(/\s+/));
const HU = W('az egy és hogy nem meg már még van volt lesz ez ezt ezek de csak vagy mint után szerint miatt között ellen kell lehet nagy új két mit mikor hol aki akik több nagyon itt ott ma holnap most éjjel azt azok volna lett lettek akkor ahogy közben nélkül után előtt szinte miért hogyan egyik másik minden semmi sem sok kevés fel le ki be el át vissza rá ide oda ennek annak által felé alatt fölött mellett mögött helyett szerinti miatt');
const EN = W('the of and to in for on with at by from as that this it are was be has have will after over new says said not but you your how why what who his her their they we us out up into about more than he she its be been were');
const DE = W('der die das und ist nicht ein eine mit von zu den dem im auf für bei auch nach wie über aus wird hat sind sich noch nur zum zur oder aber wegen gegen am vom beim einen einer wurde werden wurden kein keine');
const SL = W('in je se da na za so ki od pa bo kot po ne tudi ali ter ima bil bila bilo ni sta smo ste jih jo ga mu ji');
const HU_ACC = /[áéíóúöüőű]/g, HU_ONLY = /[őű]/g, OTHER_CH = /[äßčšžćđłąęřěňůýÿñçãõ]/g;

export function detectLang(text, domain = '') {
  const s = String(text || '').toLowerCase();
  if (!s.trim()) return '?';
  const tok = s.match(/\p{L}+/gu) || [];
  let hu = 0, ot = 0;
  for (const w of tok) {
    if (HU.has(w)) hu += 1.5;
    if (EN.has(w) || DE.has(w) || SL.has(w)) ot += 1.5;
  }
  hu += (s.match(HU_ONLY) || []).length * 3 + (s.match(HU_ACC) || []).length * 0.6;
  ot += (s.match(OTHER_CH) || []).length * 2.5;
  if (/\.hu$/.test(String(domain).toLowerCase())) hu += 1.5;
  if (tok.includes('a')) hu += 0.5;  // a határozott névelő: magyarban nagyon gyakori, de más nyelvekben is előfordul
  if (hu >= 2 && hu > ot * 1.2) return 'hu';
  if (ot >= 1.5 && ot > hu) return 'other';
  return '?';
}

// Szavazható: csak a biztosan magyar cím (az ismeretlen vagy más nyelvű hír szavazása alapból tiltott; kapcsolóval feloldható).
export const votable = lang => lang === 'hu';

// Finomabb nyelvkód a szavazói nyelvi beállításhoz: hu, en, de, sl, hr, sk; egyébként other vagy ?.
// A magyar eldöntését a detectLang végzi (változatlan); a többi nyelvet a nyelvspecifikus töltelékszavak, betűk és a .si/.hr/.sk domain jelzik.
const EN_C = new Set([...EN].filter(w => w !== 'in'));   // az „in” német és szlovén szó is: az angol jelzésből kimarad
const SL_U = W('v ki bo bodo so tudi ali ter bil bila bilo kot pri med lahko zelo več nov nova nove novi zaradi tega vendar kjer kako zakaj ima imajo bomo');
const HR_U = W('u su koji koja koje će kao također ili te iz više novi nova nove bit bio bila bilo prema nakon zbog jer ovaj ova ovo kako zašto');
const SK_U = W('sa pre ako ale ktorý ktorá ktoré nový nová nové bude budú majú podľa tiež aj už ešte preto však');
export function detectLangCode(text, domain = '') {
  const base = detectLang(text, domain);
  if (base === 'hu') return 'hu';
  const s = String(text || '').toLowerCase(), tok = s.match(/\p{L}+/gu) || [], d = String(domain).toLowerCase();
  const cnt = (set) => tok.filter(w => set.has(w)).length;
  const ch = re => (s.match(re) || []).length;
  const sc = {
    en: 1.5 * cnt(EN_C),
    de: 1.5 * cnt(DE) + 0.8 * ch(/[äß]/g) + 0.3 * ch(/[öü]/g) + 0.8 * tok.filter(w => /(ung|heit|keit|schaft|lich|isch|meister|ins)$/.test(w) && w.length > 5).length + 0.4 * ch(/sch/g) + (/\.(de|at)$/.test(d) ? 1.5 : 0),
    sl: 1.5 * cnt(SL_U) + 0.8 * ch(/[čšž]/g) + (/\.si$/.test(d) ? 1.5 : 0),
    hr: 1.5 * cnt(HR_U) + 2 * ch(/[ćđ]/g) + 0.8 * ch(/[čšž]/g) + 0.8 * ch(/ije/g) + (/\.hr$/.test(d) ? 1.5 : 0),
    sk: 1.5 * cnt(SK_U) + 2 * ch(/[ľĺŕôďťň]/g) + 0.8 * ch(/ä/g) + (/\.sk$/.test(d) ? 1.5 : 0),
  };
  const r = Object.entries(sc).sort((a, b) => b[1] - a[1]);
  if (r[0][1] >= 1.5 && r[0][1] - r[1][1] >= 0.5) return r[0][0];
  return base === 'other' ? 'other' : '?';
}
