"""A public/js/modules/lang.js detectLang függvényének hű portja (csak a magyar / nem magyar döntés). Egyezését a tesztek a JS-sel vetik össze."""
import re

_W = lambda s: set(s.split())
HU = _W('az egy és hogy nem meg már még van volt lesz ez ezt ezek de csak vagy mint után szerint miatt között ellen kell lehet nagy új két mit mikor hol aki akik több nagyon itt ott ma holnap most éjjel azt azok volna lett lettek akkor ahogy közben nélkül után előtt szinte miért hogyan egyik másik minden semmi sem sok kevés fel le ki be el át vissza rá ide oda ennek annak által felé alatt fölött mellett mögött helyett szerinti miatt')
EN = _W('the of and to in for on with at by from as that this it are was be has have will after over new says said not but you your how why what who his her their they we us out up into about more than he she its be been were')
DE = _W('der die das und ist nicht ein eine mit von zu den dem im auf für bei auch nach wie über aus wird hat sind sich noch nur zum zur oder aber wegen gegen am vom beim einen einer wurde werden wurden kein keine')
SL = _W('in je se da na za so ki od pa bo kot po ne tudi ali ter ima bil bila bilo ni sta smo ste jih jo ga mu ji')
HU_ACC = re.compile(r'[áéíóúöüőű]')
HU_ONLY = re.compile(r'[őű]')
OTHER_CH = re.compile(r'[äßčšžćđłąęřěňůýÿñçãõ]')
LETTERS = re.compile(r'[^\W\d_]+')


def detect_lang(text, domain=''):
    s = str(text or '').lower()
    if not s.strip():
        return '?'
    tok = LETTERS.findall(s)
    hu = ot = 0.0
    for w in tok:
        if w in HU:
            hu += 1.5
        if w in EN or w in DE or w in SL:
            ot += 1.5
    hu += len(HU_ONLY.findall(s)) * 3 + len(HU_ACC.findall(s)) * 0.6
    ot += len(OTHER_CH.findall(s)) * 2.5
    if re.search(r'\.hu$', str(domain).lower()):
        hu += 1.5
    if 'a' in tok:
        hu += 0.5
    if hu >= 2 and hu > ot * 1.2:
        return 'hu'
    if ot >= 1.5 and ot > hu:
        return 'other'
    return '?'
