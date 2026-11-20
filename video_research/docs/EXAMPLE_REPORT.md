# Példa jelentés (TESZT-FIXTURE, nem valódi videók)

Előállítva: `python -m video_research.trial "Hol akad el az ügynök az ablakoknál, és milyen eszközt említenek?" --fixture video_research/tests/fixtures/videos.json <YouTube-link> <TikTok-link> --detail`. Kitalált minta; az extraktív alapút szó szerinti szegmenseket ad, nem összefoglalást. Első rész: a RÖVID fő jelentés; utána a külön elérhető részletes bizonyíték és szűrési napló.

## Kutatási jelentés

> **⚠ TESZT-FIXTURE adatok, nem valódi videók.**

**Kérdés:** Hol akad el az ügynök az ablakoknál, és milyen eszközt említenek?

**Állapot:** partially_completed · 1 videó feldolgozva (2 azonosított): 1 megtartandó információ, 2 ellenőrizendő nyom, 0 kihagyott/ismétlésként csatolt részlet.

## Megtartandó információk
- **Viszont gyakran elakad a felugró ablakoknál.** [warning] — _a videó készítőjének állítása (nem ellenőrzött)_
  - forrás: [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:13) https://www.youtube.com/watch?v=AAAAAAAAAAA · azonosító: fnd_dd7bb42a90684717

## Ellenőrizendő nyomok
- **Ma az Androidos AI-ügynökökről beszélünk.** [claim] — ok: csak részben releváns a kérdéshez; gyenge kulcsszó-egyezés: a relevanciát ember ellenőrizze
  - forrás: [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:00) https://www.youtube.com/watch?v=AAAAAAAAAAA · azonosító: fnd_d6d726e47d7f413e
- **Az AutoDroid nevű eszköz képes a telefon felületét vezérelni.** [claim] — ok: csak részben releváns a kérdéshez; gyenge kulcsszó-egyezés: a relevanciát ember ellenőrizze
  - forrás: [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:04) https://www.youtube.com/watch?v=AAAAAAAAAAA · azonosító: fnd_50ea29b643704213

## Kihagyott részletek
Nincs kihagyott jelölt.

## Hiányok
- Nincs hozzáférhető átirat: https://www.tiktok.com/@fixture_user/video/1234567890123

## Fő korlátok
- FIGYELEM: TESZT-FIXTURE adatok szerepelnek a jelentésben, nem valódi videók.
- A rendszer külső (független forrásos) ellenőrzést nem végzett: az állítások a videók tartalmát tükrözik, nem igazolt tények.
- Vizuális elemzés ebben a verzióban nincs: a csak képen látható információkat (felirat a képen, kijelzők, ábrák) a rendszer nem vizsgálja.
- Teljes bizonyíték (idézetek, szegmensek, időbélyegek) és szűrési napló: külön nézet.

## Részletes bizonyítékok

## Ma az Androidos AI-ügynökökről beszélünk.
- azonosító: fnd_d6d726e47d7f413e · kategória: claim · besorolás: lead · relevancia: partial · konkrét: True · alátámasztottság: source_claim
- ellenőrzendő, mert: csak részben releváns a kérdéshez; gyenge kulcsszó-egyezés: a relevanciát ember ellenőrizze
- „Ma az Androidos AI-ügynökökről beszélünk.” — [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:00) https://www.youtube.com/watch?v=AAAAAAAAAAA; szegmensek: vid_4f72c41f6ce64f14:s0; jelentés-ellenőrzés: not_checked (az idézet megléte nem bizonyítja az állítás igazságát)
- korlát: Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a relevanciát kulcsszó-egyezés adja.

## Az AutoDroid nevű eszköz képes a telefon felületét vezérelni.
- azonosító: fnd_50ea29b643704213 · kategória: claim · besorolás: lead · relevancia: partial · konkrét: True · alátámasztottság: source_claim
- ellenőrzendő, mert: csak részben releváns a kérdéshez; gyenge kulcsszó-egyezés: a relevanciát ember ellenőrizze
- „Az AutoDroid nevű eszköz képes a telefon felületét vezérelni.” — [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:04) https://www.youtube.com/watch?v=AAAAAAAAAAA; szegmensek: vid_4f72c41f6ce64f14:s1; jelentés-ellenőrzés: not_checked (az idézet megléte nem bizonyítja az állítás igazságát)
- korlát: Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a relevanciát kulcsszó-egyezés adja.

## Viszont gyakran elakad a felugró ablakoknál.
- azonosító: fnd_dd7bb42a90684717 · kategória: warning · besorolás: keep · relevancia: direct · konkrét: True · alátámasztottság: source_claim
- „Viszont gyakran elakad a felugró ablakoknál.” — [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:13) https://www.youtube.com/watch?v=AAAAAAAAAAA; szegmensek: vid_4f72c41f6ce64f14:s3; jelentés-ellenőrzés: not_checked (az idézet megléte nem bizonyítja az állítás igazságát)
- korlát: Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a relevanciát kulcsszó-egyezés adja.

## Teljes korlátlista
- FIGYELEM: TESZT-FIXTURE adatok szerepelnek a jelentésben, nem valódi videók.
- A rendszer külső (független forrásos) ellenőrzést nem végzett: az állítások a videók tartalmát tükrözik, nem igazolt tények.
- Ellentmondás-észlelés ebben a verzióban nem történik; a `contradictions` mező üres, ez NEM jelenti, hogy nincs ellentmondás.
- Vizuális elemzés ebben a verzióban nincs: a csak képen látható információkat (felirat a képen, kijelzők, ábrák) a rendszer nem vizsgálja.
- Az idézetek programozottan ellenőrzöttek az átiratban; ez nem bizonyítja az állítás igazságát. Az állítás és az idézet jelentésbeli kapcsolatának ellenőrzése heurisztikus, nem tévedhetetlen.

## Szűrési napló

Videók: 1/2 feldolgozva · szegmensek: 4 · nincs rögzített kiválasztási arány vagy kvóta; csak a javaslatba került jelöltek kapnak sort.

Nincs bejegyzés.

