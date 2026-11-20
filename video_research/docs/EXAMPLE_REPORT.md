# Példa jelentés (TESZT-FIXTURE, nem valódi videók)

Előállítva: `python -m video_research.trial "Hol akad el az ügynök az ablakoknál, és milyen eszközt említenek?" --fixture video_research/tests/fixtures/videos.json <YouTube-link> <TikTok-link>`. A tartalom kitalált minta; az extraktív alapút szó szerinti szegmenseket ad, nem összefoglalást.

## Kutatási jelentés

> **⚠ TESZT-FIXTURE adatok, nem valódi videók.**

**Kérdés:** Hol akad el az ügynök az ablakoknál, és milyen eszközt említenek?
https://www.youtube.com/watch?v=AAAAAAAAAAA
https://www.tiktok.com/@fixture_user/video/1234567890123

**Állapot:** partially_completed · Rögzített szolgáltatói költség: 0.0000 USD (csak a ténylegesen ismert költség)

## Összefoglaló
2 videó azonosítva, ebből 1 átirattal; 3 megállapítás, ebből 0 több videóban is szerepel. Kutatási kérdés: Hol akad el az ügynök az ablakoknál, és milyen eszközt említenek?

## Megállapítások

### claim
- **Az AutoDroid nevű eszköz képes a telefon felületét vezérelni.** — _a videó készítőjének állítása (nem ellenőrzött)_
  - „Az AutoDroid nevű eszköz képes a telefon felületét vezérelni.” — [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:04; szegm.: vid_7ecebd77774f497e:s1) https://www.youtube.com/watch?v=AAAAAAAAAAA [jelentés-ellenőrzés: not_checked]
  - _Korlát:_ Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a kérdéssel való relevanciát kulcsszó-egyezés adja.
- **Ma az Androidos AI-ügynökökről beszélünk.** — _a videó készítőjének állítása (nem ellenőrzött)_
  - „Ma az Androidos AI-ügynökökről beszélünk.” — [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:00; szegm.: vid_7ecebd77774f497e:s0) https://www.youtube.com/watch?v=AAAAAAAAAAA [jelentés-ellenőrzés: not_checked]
  - _Korlát:_ Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a kérdéssel való relevanciát kulcsszó-egyezés adja.

### warning
- **Viszont gyakran elakad a felugró ablakoknál.** — _a videó készítőjének állítása (nem ellenőrzött)_
  - „Viszont gyakran elakad a felugró ablakoknál.” — [FIXTURE] Androidos AI-ügynökök bemutató (youtube, 0:13; szegm.: vid_7ecebd77774f497e:s3) https://www.youtube.com/watch?v=AAAAAAAAAAA [jelentés-ellenőrzés: not_checked]
  - _Korlát:_ Extraktív kivonat modell nélkül: a szegmens szó szerinti szövege, nem összefoglalás; a kérdéssel való relevanciát kulcsszó-egyezés adja.

## Hiányzó információ
- Nincs hozzáférhető átirat: https://www.tiktok.com/@fixture_user/video/1234567890123

## Források
- [FIXTURE] Android ügynök rövid — tiktok — https://www.tiktok.com/@fixture_user/video/1234567890123 (szolgáltató: fixture, átirat: nincs)
- [FIXTURE] Androidos AI-ügynökök bemutató — youtube — https://www.youtube.com/watch?v=AAAAAAAAAAA (szolgáltató: fixture, átirat: platform_caption)

## Lefedettségi korlátok
- FIGYELEM: TESZT-FIXTURE adatok szerepelnek a jelentésben, nem valódi videók.
- A rendszer külső (független forrásos) ellenőrzést nem végzett: az állítások a videók tartalmát tükrözik, nem igazolt tények.
- Ellentmondás-észlelés ebben a verzióban nem történik; a `contradictions` mező üres, ez NEM jelenti, hogy nincs ellentmondás.
- Vizuális elemzés ebben a verzióban nincs: a csak képen látható információkat (felirat a képen, kijelzők, ábrák) a rendszer nem vizsgálja.
- Az idézetek programozottan ellenőrzöttek az átiratban; az állítás és az idézet jelentésbeli kapcsolatának ellenőrzése heurisztikus, nem tévedhetetlen.

