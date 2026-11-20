# Videós kutatóügynök (`video_research/`)

Magyar kutatási kérdésből vagy videólinkekből forráskövethető, magyar nyelvű jelentést és strukturált exportot (JSON, CSV, Markdown) készít YouTube- és TikTok-videók átirataiból. Nem videóvágó, nem tartalomgyártó, nem posztoló.
Különálló csomag: a Média-Zaj appot, a magyar pilotot és a `trading_model/` mappát nem érinti.

## Állapot (őszintén)

| Rész | Állapot |
|---|---|
| Adatmodellek, URL-normalizálás + platform-engedélylista | kész, tesztelt |
| Adatbázis (SQLAlchemy Core, verziózott migráció, idempotencia, lease/heartbeat, részállapotok, szolgáltatói futásazonosítók) | kész, **SQLite-on tesztelt**; PostgreSQL-en nem futtattam (nincs itt PG) |
| Tervezés + jóváhagyás fizetős futás előtt, költség-/idő-/token-/videókeret, megszakítás, újraindítás, retry+backoff+jitter, bizonytalan kimenetel kezelése | kész, tesztelt |
| Idézet programozott ellenőrzése, összevonás forrásmegőrzéssel, magyar jelentés, export | kész, tesztelt |
| Webes API (FastAPI, bearer-token) + háttér-worker | kész, tesztelt (TestClient) |
| Apify-adapter (hivatalos `apify-client`) | kész, **csak hamis klienssel tesztelt**; Actor nincs kiválasztva |
| **Valódi LLM-adapter** | **nincs** (lásd alább) |
| Docker Compose | megírva, **nem futtattam** (nincs Docker itt) |
| Éles Apify-/LLM-hívás, valódi videó | **egyszer sem történt** |
| Ellentmondás-észlelés, külső (független) forrásos ellenőrzés | nincs; a jelentés ezt kimondja |
| Instagram, Facebook, OCR, Android-kliens, ütemezés, MCP | nincs; nincs is adapterhely, amely működőnek látszana |

## Döntést igénylő ütközés: harmadik szolgáltató

A feladat az Anthropic SDK-t kéri, de a `CLAUDE.md` tiltja a harmadik szolgáltató bevonását, és a `scripts/policy_guard.py` (`config/guard_policy.json`, `forbidden_providers`) minden PR-en hibának veszi az `anthropic` importot és hosztnevet. A szabályt nem lazítottam és nem kerültem meg. Ezért az LLM az `llm.LLMClient` felület mögött áll, a worker most `NullLLM`-et kap: kinyerés nélkül a feladat érthető hibával áll meg, kitalált kimenet nincs. Két út van, a döntés a felhasználóé:
1. Jóváhagyott szabályváltás (`guard_policy.json` + `CLAUDE.md`), utána egy `AnthropicLLM(LLMClient)` adapter külön ágon, PR-ben.
2. A már engedélyezett szolgáltató (Gemini) adapterének illesztése ugyanezen a felületen (élő hívás itt továbbra is tilos, csak hamis átvitellel tesztelhető).

Az Apify nincs a tiltott listán, de a `CLAUDE.md` szövege szerint harmadik szolgáltatót érint: használata előtt jóváhagyás kell.

## Korlátozott ügynök

Az MI: javasol keresőkifejezést, kinyer, (később) jelentést fogalmaz. A kód: ellenőrzi a tervet, csak regisztrált adaptert hív, tárolja az állapotot, érvényesíti a kereteket. A modell nem kap titkot/eszközt/hálózatot, nem választ Actort és URL-t (az URL csak a felhasználó kéréséből jön, normalizálva). A videó és az átirat nem megbízható bemenet: elválasztott blokkban megy a modellnek, a lezáró jelet kiszűrjük, és a kimenetből csak programozottan ellenőrzött idézettel rendelkező megállapítás marad meg.

## Folyamat és állapotok

`POST /jobs` (Idempotency-Key fejléc) → azonnal `job_id`, `queued` → worker: `planning` → `awaiting_approval` (a terv, a keretek és a költségbecslés megjelenik) → `POST /jobs/{id}/approve` → `queued` → `running` → `completed | partially_completed | failed | cancelled`. A részlépések (`job_steps`) és a szolgáltatói futások (`provider_runs`) tároltak; újraindításkor a kész lépések kimaradnak, a mentett futásazonosítójú futást lekérdezi, nem indítja újra.

Végpontok (bearer-token): `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `GET /jobs/{id}/report?format=json|markdown|csv`, `GET /health`.

## Forráshűség

- Állítás-státusz: `creator_claim` (egy videó), `repeated_across_videos` (több videó; **nem** igazolás). Az `independently_verified` értéket az 1. verzió soha nem állítja elő.
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
