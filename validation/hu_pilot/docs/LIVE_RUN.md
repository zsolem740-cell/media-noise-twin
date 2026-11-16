# Éles modellfuttatás (Gemini, Groq) – kézzel indítva a GitHubon

A modell csak az emberi címkézés **lezárása után** futhat. Ezt a kód is kikényszeríti. Én (a fejlesztő eszköz) valódi API-hívást nem indítok; a futtatást te indítod a GitHub Actions felületén.

## 1. Előfeltétel: lezárás és futtatási csomag
1. Az emberi címkézés lezárva: `python -m validation.hu_pilot.run freeze EXPORT...` (a kapu átment vagy eldönthetetlen).
2. A futtatási csomag: `python -m validation.hu_pilot.run export-bundle`. Ez a `validation/hu_pilot/run_bundle.json` fájlt írja: az 50 cím szövege és a lezárás aggregált adata (kapu döntése, kappa, a hash-ek). **Szavazat, szavazónkénti címke és emberi érték nincs benne** (a kód ellenőrzi). Nem íródik felül.
3. A fájlt fel kell vinni a tárolóba (külön ágon, jóváhagyással), mert a GitHub-munkafolyamat csak ott látja. A tároló nyilvános: a csomagban az 50 hírcím és a kapu aggregált adata lesz látható, mást nem tartalmaz.

## 2. Kulcsok a GitHubon
- **`GEMINI_API_KEY`** (repó-titok): megvan (a `gemini-labels` munkafolyamat is használja).
- **`GROQ_API_KEY`** (repó-titok): ellenőrizd, hogy létezik-e ezen a néven. Ha nincs, a Groq futás elutasítja magát, és a hibaüzenet a kulcs *nevét* mondja.
- **`GEMINI_MODEL`** (repó-változó, nem titok): a Gemini modellje, ha a futtatáskor nem adsz meg másikat. A Groq modellje a konfigurációban rögzített (`openai/gpt-oss-120b`), ettől nem lehet eltérni.

## 3. Indítás
Actions, **Pilot modellfuttatás (kézi indítású)**, **Run workflow**:
1. **Először `mode = check`:** hálózat nélkül ellenőriz (csomag épsége, az 50 kérés, a kulcs megléte). Hívás nincs. A kimenet `status: OK` kell legyen.
2. **Éles futás:** `mode = run`, `confirm = INDITSD`, Geminihez a `model` (vagy a `GEMINI_MODEL` változó). Egy futás egy szolgáltató: előbb a Gemini, a Groq külön futásban.
3. Egy futás az 50 címet egyesével küldi, a konfigurált időközzel (Gemini 13 mp, Groq 15 mp), kb. 11-13 perc.

## Csomagos kísérlet (egy kérésben több cím)
A pilot **mérése egy cím egy kérésben** marad (ez az elfogadott mód, tiszta mérés). A csomagos mód ettől **külön kísérlet** ugyanazon az 50 címen, hogy kiderüljön, egyezik-e az eredménye az egyesével kapottal, mielőtt az éles címkézésben csomagot használnánk.
- **Mi változik:** a rendszerszabály szó szerint ugyanaz (hash változatlan), csak a felhasználói üzenet és a válasz-séma különbözik: a címek egymástól függetlenek (`<post id="k">`), a válasz `{"results": [...]}`, címenként a négy jellel. A csomagok összeállítása rögzített maggal véletlenszerű (a szomszéd címek nem a feed sorrendje).
- **Indítás:** ugyanaz a munkafolyamat, `batch_size` = 2-20 (javaslat: 10), **külön `run_name`-mel** (például `pilot-csomag-10`). A `batch_size` 0 = egyesével (a mérés).
- **Mit nyersz:** 50 cím helyett 5 kérés (10-es csomaggal), és a hosszú utasítás nem megy ki ötvenszer, tehát kevesebb token (a napi keretet a token is korlátozza).
- **Hibák:** csonka vagy blokkolt válasznál a csomag felezése (a hibás cím elkülönül), a címenként érvénytelen válasz egyszer újra csomagba kerül, utána hiba. A folytatás ugyanazokat a csomagokat adja.
- **Összevetés:** `python -m validation.hu_pilot.run compare-runs <egyesével futás mappája> <csomagos futás mappája>` (a két futás `model_runs/<név>` mappája, az artifactokból). Kiírja az azonos összpontszámú címek arányát, az átlagos eltérést (0-8), a rangkorrelációt, a jelenkénti egyezést, az érvénytelen arányt, a kérések és a tokenek arányát, és a `config.json`-ban rögzített elfogadási küszöbök szerinti igen/nem választ (javasolt: rangkorreláció legalább 0,8, átlagos eltérés legfeljebb 0,75, érvénytelen arány legfeljebb 10%). **A küszöböket a csomagos futás előtt kell véglegesíteni.**
- **Következtetés csak ennyi:** ha a csomagos mód a küszöbökön belül marad, az éles címkézésben megfontolható; a pilot emberi összevetésének alapja akkor is az egyesével futás.

## 4. Szabályok, amiket a kód tart
- Mérési futás: szolgáltatóváltás nincs, harmadik szolgáltató nincs, fizetős csomagra váltás nincs.
- Napi kvótánál a futás azonnal megáll, a kész címek megmaradnak. A folytatás a visszaállás + 5 perc után lehet, az első kérés próba (napi legfeljebb 3).
- A kulcs csak fejlécben megy, a naplóban és a kimenetben sehol nem szerepel. Átirányítást a kód nem követ.
- Minden kéréshez naplósor: szolgáltató, kért és visszaadott modell, kimenetel, tokenek.
- Az érvénytelen, üres, csonka vagy blokkolt válasz nem vált szolgáltatót.

## 5. Ha megáll (kvóta)
A munkafolyamat hibával zárul (kilépési kód 3), de a futás fájljait feltölti (*pilot-run-<run_name>* artifact, 14 napig). Folytatás: a kvóta visszaállása + 5 perc után indítsd újra **ugyanazzal a `run_name`-mel**, és a `resume_run_id` mezőbe írd a megállt futás azonosítóját (a futás oldalának címében a szám). A kész címek nem mennek ki újra.

## 6. Eredmény
A futás fájljai az Actions futás **artifactjában** vannak (`log.jsonl`, `scores.jsonl`, `results.csv`, `summary.json`, `quota_stops.jsonl`), a `results/` mappába nem commitolunk semmit. Egy nyilvános tárolóban az artifact a tárolóhoz hozzáférők számára letölthető, ezért a pontszámok 14 napig nem titkosak (50 nyilvános hírcímről szólnak).

## Mit nem próbáltam ki
- Magát a GitHub-munkafolyamatot (a YAML szerkezetét ellenőriztem, de Actions-futás nem volt).
- A valódi Gemini és Groq végpontokat. Az átvitelt helyi hamis szerverrel teszteltem (fejlécek, 429 és Retry-After, időtúllépés, átirányítás, kvótamegállás és folytatás). A valódi API válaszformátumai a korábbi, hamis válaszokkal tesztelt osztályozón alapulnak.
- A folytatás `download-artifact` lépését.
Ezért az első éles lépés a `check`, és az első valódi kérések eredményét érdemes végignézni, mielőtt a teljes futás lefut.
