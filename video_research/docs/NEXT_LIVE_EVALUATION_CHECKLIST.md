# A következő valódi-modell értékelés előzetes rögzítési listája

**Ezt a futás ELŐTT, külön rögzítjük és lefagyasztjuk (hash). A futás alatt semmi sem módosítható.** Valódi hívás csak külön jóváhagyott, azonosított futásra; a szabály és a futás jóváhagyása két külön lépés.

| # | Rögzítendő | Megjegyzés |
|---|---|---|
| 1 | **Kutatási kérdés** (magyarul), eseményenként | pontos szöveg |
| 2 | **Elvárt hasznos részletek** | átiratszegmens(ek) vagy idézet szerint, és hogy milyen tételfajta (eszköz, lépés, előfeltétel, költség, hiba/korlát…) |
| 3 | **Kizárandó zaj** | konkrét szegmensek/típusok (köszönés, reklám, off-topic…), amelyek nem kerülhetnek be |
| 4 | **Megőrzendő feltételek és korlátok** | szócsoportok, amelyek a magyar állításban benne kell legyenek (pl. „csak”, „nálam”, verzió, szám) |
| 5 | **Új futásazonosító és keretek** | modell, kérés-, token- (tervezési), idő-keret, konfigurációs verzió, commit SHA |
| 6 | **Átirat forrása** | a felhasználó által biztosított valódi átirat és formátuma (`text`/`srt`/`vtt`), nyelve; a videólink nem igazolt egyezés |
| 7 | **Hash-ek** | esetkészlet, elvárások, kiértékelő, promptok, generálási konfiguráció |

## Elvek
- **A modell által készített kivonat nem lehet saját maga egyedüli értékelési alapja.** Az elvárásokat (2–4.) ember írja az átirat alapján a futás előtt; a kiértékelés ezek ellen és programozott ellenőrzések (idézet megléte, szegmens, időbélyeg) ellen mér. A modell önminősítése (`relevance`, `concrete`, szemantikai `consistent`) csak a kapuk bemenete, nem elfogadási feltétel.
- **Sablonhelyőrző nem tényleges adat.** Kitöltetlen mezővel (pl. „[értékek…]”) az ügynök nem indít hívást, hanem kérdez. A „nem látható” csak kifejezett kijelentésként elfogadott, és a hiány rögzítendő.
- Az ingyenesség és a kvóta igazolása: tényleges szöveges értékek (szint, számlázás hiánya, RPM/TPM/RPD, mai maradék, a bot projekt/modell azonossága) vagy kifejezett „nem látható”.
- Az előző futás eredménye és kiértékelése (`LIVE_RUN_001_RECORD.md`) változatlan marad; új futás új azonosítót és új mappát kap.
