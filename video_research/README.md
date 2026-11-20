# Videós kutatóügynök (`video_research/`)

Magyar kutatási kérdésből vagy videólinkekből forráskövethető, magyar nyelvű jelentést és strukturált exportot (JSON, CSV, Markdown) készít YouTube- és TikTok-videók átirataiból. Nem videóvágó, nem tartalomgyártó, nem posztoló.
Különálló csomag: a Média-Zaj appot, a magyar pilotot és a `trading_model/` mappát nem érinti.

## Állapot (őszintén)

Részletes, platformonkénti lista: `docs/CAPABILITIES.md`. A három külső projekt értékelése: `docs/ASSESSMENT.md`. Példa jelentés: `docs/EXAMPLE_REPORT.md` (fixture).

| Rész | Állapot |
|---|---|
| Folyamat (terv → hash-hez kötött jóváhagyás → metaadat → felirat → kivonat → idézetellenőrzés → magyar jelentés) | kész, offline tesztelt (SQLite) |
| YouTube metaadat + felirat | kész; **metaadat élőben igazolt, felirat élőben sikertelen** (a YouTube blokkolta a felhő-IP-t, nem kerültem meg) |
| TikTok | csak metaadat (élőben részleges: cím nélkül); **átirat nincs** |
| Keresés, beszédfelismerés, vizuális elemzés | nincs |
| Információkivonat | modell nélküli extraktív alapút; **LLM-adapter nincs** (lásd lent) |
| Apify-adapter (korábbi kör) | változatlan, csak hamis klienssel tesztelt |
| Zajszűrés: nincs kötelező találat, részletszintű szűrés, megtartandó/nyom/kihagyott csoport, rövid fő jelentés + külön bizonyíték és napló, visszajelzés | kész, offline tesztelt; valódi modellel nem próbáltam |
| API (`/api/jobs…`, export, törlés), egyszerű weboldal (`/`) | API: TestClient-tel tesztelt; a weboldal JS-e szintaktikailag ellenőrzött, **böngészőben nem futtattam** |
| PostgreSQL, Docker Compose | nem futtatva |

Vertikális próba (nincs modell- és fizetős hívás): `python -m video_research.trial "kérdés" LINK [LINK…] [--fixture video_research/tests/fixtures/videos.json]`.

## Döntést igénylő ütközés: harmadik szolgáltató

A feladat az Anthropic SDK-t kéri, de a `CLAUDE.md` tiltja a harmadik szolgáltató bevonását, és a `scripts/policy_guard.py` (`config/guard_policy.json`, `forbidden_providers`) minden PR-en hibának veszi az `anthropic` importot és hosztnevet. A szabályt nem lazítottam és nem kerültem meg. Ezért az LLM az `llm.LLMClient` felület mögött áll, a worker most `NullLLM`-et kap: kinyerés nélkül a feladat érthető hibával áll meg, kitalált kimenet nincs. Két út van, a döntés a felhasználóé:
1. Jóváhagyott szabályváltás (`guard_policy.json` + `CLAUDE.md`), utána egy `AnthropicLLM(LLMClient)` adapter külön ágon, PR-ben.
2. A már engedélyezett szolgáltató (Gemini) adapterének illesztése ugyanezen a felületen (élő hívás itt továbbra is tilos, csak hamis átvitellel tesztelhető).

Az Apify nincs a tiltott listán, de a `CLAUDE.md` szövege szerint harmadik szolgáltatót érint: használata előtt jóváhagyás kell.

## Korlátozott ügynök

Az MI: javasol keresőkifejezést, kinyer, (később) jelentést fogalmaz. A kód: ellenőrzi a tervet, csak regisztrált adaptert hív, tárolja az állapotot, érvényesíti a kereteket. A modell nem kap titkot/eszközt/hálózatot, nem választ Actort és URL-t (az URL csak a felhasználó kéréséből jön, normalizálva). A videó és az átirat nem megbízható bemenet: elválasztott blokkban megy a modellnek, a lezáró jelet kiszűrjük, és a kimenetből csak programozottan ellenőrzött idézettel rendelkező megállapítás marad meg.

## Folyamat és állapotok

`POST /api/jobs` (Idempotency-Key fejléc) → azonnal `job_id`, `queued` → worker: `planning` → `awaiting_approval` (a terv, a keretek és a költségbecslés megjelenik) → `POST /api/jobs/{id}/approve` → `queued` → `running` → `completed | partially_completed | failed | cancelled`. A részlépések (`job_steps`) és a szolgáltatói futások (`provider_runs`) tároltak; újraindításkor a kész lépések kimaradnak, a mentett futásazonosítójú futást lekérdezi, nem indítja újra.

Végpontok (bearer-token, `/api` alatt): `POST /jobs/plan` (ingyenes előnézet), `POST /jobs`, `POST /jobs/{id}/approve` (törzs: `{"plan_hash": …}`; eltérő hash 409), `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `GET /jobs/{id}/report` és `/export?format=json|markdown|csv`, `DELETE /jobs/{id}`; `GET /health`, `GET /` (oldal).

## Forráshűség

- Állítás-státusz: `source_claim` (egy videó), `repeated_across_sources` (több videó; **nem** igazolás, a videók ugyanazt az eredeti forrást is ismételhetik), `unsupported` (nem ellenőrizhető idézet: külön listába kerül, nem megállapítás). `verified` nincs.
- Idézet: normalizált szó szerinti egyezés keresése az átiratban (legfeljebb 6 szomszédos szegmens). Nem található → a megállapítás kimarad, és ez a jelentésben szerepel. Időbélyeg csak az átiratból, ha van.
- Az állítás–idézet jelentésbeli ellenőrzése külön, heurisztikus lépés (`semantic_check`), a jelentés nem garanciaként mutatja.
- Összevonáskor minden forráshivatkozás megmarad; az eltérő megfogalmazások a korlátok közé kerülnek.

## Költség és keretek

`VR_MAX_VIDEOS` (alap 10, az első valódi próba plafonja; `VR_ALLOW_MORE_THAN_TRIAL=1` oldja), `VR_MAX_VIDEO_MINUTES`, `VR_LLM_TOKEN_BUDGET`, `VR_COST_BUDGET_USD`, `VR_MAX_RUNTIME_SECONDS`, `VR_MAX_PARALLEL_RUNS` (**még nem érvényesül**: a worker egyszerre egy feladatot dolgoz, a feladaton belüli feldolgozás soros). A kérésben kért keret a szerveré alá nem emelhető. Új fizetős futás csak akkor indul, ha a futás költségplafonja (`max_total_charge_usd` az Apify-nak) belefér a hátralévő keretbe. A becslés (`estimated_cost`, nincs egységár → `null` és magyarázat) elkülönül a ténylegesen ismert költségtől (`recorded_cost`; ismeretlen költségű futás jelölve). A megszakítás best effort: a szolgáltatói leállítás nem azonnali és nem garantált, ezt a válasz és a jelentés is kimondja.

## Biztonság

Titok csak környezeti változóból (`SecretStr`, maszkolt); a naplószűrő (`util.redact`) a tokenmintákat kitakarja. Platform-engedélylista és URL-normalizálás (hitelesítő adat az URL-ben, nem http(s), idegen host, rövid TikTok-link elutasítva). Saját letöltés nincs, ezért SSRF-felület sincs; ha később lesz, a célcím-ellenőrzés kötelező. Az 1. verzió nem kér platformjelszót/cookie-t (`requires_cookies_or_login` Actor elutasítva). Éles módban fixture-adapter nem regisztrálható, az API token nélkül zárva marad.

## Futtatás

```
pip install -r video_research/requirements.txt
python -m pytest video_research/tests          # offline, hálózati zárral
VR_DATABASE_URL=sqlite:///vr.db python -m video_research.main migrate
```
Fejlesztésben `VR_MODE=dev VR_FIXTURE_FILE=video_research/tests/fixtures/videos.json` regisztrálja a jelölt teszt-fixture-t (a jelentés figyelmeztetést kap). Compose: lásd `docker-compose.yml`, `.env.example`.

## Apify Actor kiválasztása

Lásd `docs/ACTORS.md`. Az Actor-azonosító és a mezőleképezés a `VR_ACTORS_FILE` JSON-ban van; nincs beégetett azonosító, az ellenőrzés még nem történt meg.
