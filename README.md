# media-noise-twin
Geolokalizált információs zaj- és algoritmikus torzításmérő (Vas megye / Alpokalja, HU/AT/SI).

## Modell
`ATM = G_k · S_i · (1 − V_i)`
- V_i valóságindex: hivatalos 0.95 · helyi sajtó 0.70 · egyéb 0.45
- S_i szenzációszint: kulcsszavak 50% · felkiáltójelek 25% · NAGYBETŰS szavak 25%
- G_k geo-súly: HU-VA 1.0 · HU-NAT 0.90 · AT-1 0.85 · SI-1 0.80 · INT 0.60

## Futtatás
```
pip install -r requirements.txt
python -m src.collectors.google_news   # -> data/raw/latest.json
python -m src.core.atm_engine          # -> data/metrics/atm_history.json
```
Források, geofence és trust-domainek: `config/sources.json`.

## Telepítés (GitHub)
1. Repo létrehozása, push a `main` ágra.
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions fül → `ingest-and-analyze` → Run workflow (utána 15 percenként fut).
4. Az adat változásakor a workflow commitol és elindítja a `deploy-pages`-t.
5. Telefonon: Chrome → az oldal megnyitása → „Telepítés" (a Megosztás-célpont csak telepített PWA-nál jelenik meg).

## PWA
- Offline-first: IndexedDB-ben az utolsó mátrix, a `sw.js` gyorsítótárazza a felületet.
- Share Target (`GET`): a megosztott cím/szöveg/URL az `app.js`-ben kerül elemzésre. A cikk oldalát a böngésző nem tudja letölteni (CORS), ezért az S_i a megosztott szövegből számolódik.
- Human-in-the-Loop (csak helyben): Tény +1 / Clickbait −1, olvasási idő ≥45 s +0,5, <10 s −0,5. Forrásonként ±0,03/pont, legfeljebb ±0,15 korrekció a V_i-n.

## v38 – moduláris HUD + AI (kulcs nélkül)
- `public/js/modules/`: model (pontszámítás) · learner (öntanuló logisztikus regresszió) · globe (Canvas glóbusz) · filterEngine · uiRenderer · store (IndexedDB) · dataLoader · share.
- Telefonon tanul: a Tény/Clickbait szavazatok és az olvasási idő finomítják az AI-t (S = szabály és AI keveréke, az AI súlya 20% → 70%).
- Szerveren tanul (`src/core/insights.py`): forrásonkénti Welford-alapvonal, anomália (z ≥ 2), 24 órás trend, felszálló kifejezések.
- `src/utils/geo.py`: város/ország-szótár a glóbusz pontjaihoz.

## v39 – bővítések
- **Hivatalos forrás:** a HungaroMet szöveges figyelmeztetése (országos + Vas vármegye) hírként, riasztáskor ntfy értesítéssel.
- **Közvetlen RSS:** New York Post, BBC (a CNN saját RSS-e 2024 óta nem frissül, ezért a CNN a Google News `site:` keresésen át jön).
- **Cikkszöveg:** az új hírek bevezetőjéből kulcsszó-, felkiáltójel- és cím–szöveg egyezés jelek (`src/collectors/article.py`).
- **Események:** `src/core/insights.py` – ugyanarról szóló hírek csoportosítása, forrásonkénti hangnem-szórás.
- **Tanuló V:** a tartósan zajos forrás hitelessége csökken (Bayes-zsugorítás, ±0,15).
- **Dinamikus küszöbök:** sárga/piros az adat 70./95. percentilise (alsó korláttal).
- **Kalibráció:** a saját szavazatokból AUC-mérés és az AI-súly (λ) optimalizálása; szavazatok exportja JSON-ban.
- **Értesítés:** `NTFY_TOPIC` titok (GitHub Secrets) → `src/core/notify.py`.

## v41 – WebGL glóbusz
- `public/js/modules/globe3d.js`: Three.js glóbusz (InstancedMesh pontok, partvonalak, glóbusz-izzás). A könyvtárat futásidőben tölti be (jsDelivr, három@0.160.0), a service worker gyorsítótárazza.
- Hiba, offline első indítás vagy WebGL hiánya esetén automatikusan a Canvas-glóbusz (`globe.js`) marad; a **3D/2D** gomb kézzel vált, a választást megjegyzi.

## v42 – szerkeszthető beállítás
- `config/user.json` a repóban: csak a módosítandó részeket kell megadni, a többi az alapbeállításból jön (minta: `config/user.example.json`).
- Szabályok: objektum mezőnként fésülődik, lista cserélődik; `*_add` / `*_remove` hozzáad / töröl; `regions` kóddal módosít (`enabled: false` kikapcsol); `trust` új szintje felülírja a beépítetteket; `clickbait_add` új kulcsszavak.
- Hibás fájl esetén az alapbeállítás marad, a hiba a Szerver-elemzés panelen is látszik.
- A fájl mentése azonnal elindítja a futást (push-eseményre).
- Az Öntanuló AI panel „Javaslat készítése" gombja a szavazatokból kész `user.json`-részletet állít össze.

## v43 – egész számú, gyökös pontozás
- `ATM = round( √( G% · S% · (100 − V%) ) )`: a tagok egész százalékok (.5-nél felfelé kerekítve), az eredmény egész szám (0–~742; tanult V mellett legfeljebb ~975).
- A 0,5% alatti szenzációszint 0-ra kerekedik (kiesik a halk zaj); a gyök felerősíti a kis értékeket és lágyítja a nagyokat.
- A küszöbök alsó korlátját a program átszámolja (0,05 → 224, 0,15 → 387), a percentilis alapú részük változatlan elv.
- Visszaállás a régi tizedes képletre: `config/user.json` → `{"scoring": {"mode": "classic"}}`.

## v44
- `exclude_domains`: az EU-s látogatókat blokkoló vagy képaláírás-szemetet adó források (Post Register, WV News stb.) kiesnek a gyűjtéskor és a régi adatokból is. Bővítés: `config/user.json` → `{"exclude_domains_add": ["pelda.com"]}`, visszavétel: `exclude_domains_remove`.
- AI-alapszint levonása: a telefon az AI-becslésből levonja a szabály szerint nyugodt hírek mediánját (legalább 30 ilyen hírnél), így a gyök nem erősíti fel az alapzajt.

## v45
- Postaláda: a workflow a repó `inbox/*.txt` fájljait (base64-es tar.gz frissítés-csomagok) magától kicsomagolja, ellenőrzi (csak src/, public/, config/sources.json, requirements.txt, README.md, PROJECT_VERSION, .gitignore; nem nyúl a config/user.json-hoz és a workflow-hoz), és hiba esetén a csomagot az `inbox/failed/` mappába teszi. A napló: `inbox/LOG.md`.
- A projekt a repó fájljaiban él (a workflow csak egyszer bontja ki: `PROJECT_VERSION` hiányában).
- Forrásnevek egyesítése (edition.cnn.com → cnn.com; egyedi: `domain_aliases`), töltelékszavak kiszűrése a felszálló kifejezésekből, „Diagnosztika másolása" gomb az Öntanuló AI panelben.

## v46
- Passzív piaci napló (`src/research/`): cégenként naponta összegzi a híreket (darab, ATM, a cím által állított irány), a napi záróárakat a stooq.com-ról tölti le (kulcs nélkül, legfeljebb 6 óránként), és magától kiértékeli, hogy az árfolyam igazolja-e a határozott piaci állításokat (permutációs teszt, AUC). A felületet és a pontozást nem érinti; az eredmény az `atm_history.json` `research` kulcsában van, az állapot a „Diagnosztika másolása" gombbal olvasható. Kutatási eszköz, nem befektetési tanács. Cégek és szavak: `config/sources.json` → `research` (a `config/user.json`-ban: `"research": {"companies_add": [...]}`).

### v46.1
- Árfolyamforrás: a Stooq 2026 márciusától kulcs nélkül nem ad adatot, ezért az alap a Yahoo grafikon-végpont (kulcs nélkül, nem hivatalos); a Stooq tartalék, ha `research.stooq_apikey` (vagy `STOOQ_APIKEY` környezeti változó) meg van adva. Hibás ár esetén óránként újrapróbál; a beállítás változásakor azonnal.
