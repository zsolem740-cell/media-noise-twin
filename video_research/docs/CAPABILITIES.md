# Képességek, korlátok, eltérések a specifikációtól (2026-11-20)

"Tesztelve" = a `video_research/tests` offline tesztkészletben (hamis hálózattal) lefut. "Élő próba" = valódi hálózati hívás ebben a munkamenetben.

## Platformonként

| Képesség | YouTube | TikTok |
|---|---|---|
| Link normalizálás, engedélylista | tesztelve (watch, youtu.be, shorts) | tesztelve (`/@user/video/ID`; `vm.tiktok.com` rövid link elutasítva) |
| Metaadat | oEmbed: cím, készítő. **Élő próba sikeres** (`jNQXAC9IVRw`). Hossz, dátum: null | oEmbed. **Élő próba**: a válasz cím és szerző nélkül jött, a készítő a link @kezelője. Hossz, dátum: null |
| Felirat/átirat | `youtube-transcript-api` (MIT); időbélyeggel, nyelvvel, gépi/kézi jelöléssel; tesztelve hamis klienssel. **Élő próba sikertelen**: a YouTube ebből a felhő-IP-ből blokkolt (Google "sorry" oldalra irányít). A blokkot szándékosan nem kerüljük meg | **Nincs.** Nincs nyilvános, hitelesítés nélküli felirat-API; hang → beszédfelismerés útvonal nincs megvalósítva |
| Beszédfelismerés (felirat híján) | nincs | nincs |
| Kulcsszavas keresés | nincs (M4) | nincs (M4) |
| Vizuális elemzés | nincs; a jelentés ezt kimondja | nincs |

## Információkinyerés
- **Modell nélküli extraktív alapút** (`extractive.py`): a kérdés kulcsszavaihoz (első 6 karakter) illő szegmenseket választja ki szó szerint. Nem fordít, nem összefoglal, **nyelvfüggő**: magyar kérdéssel angol átiratban csak a közös szavakra talál. A kategória csak `warning`/`recommendation`/`claim`.
- **Nyelvi modell**: az `LLMClient` felület kész (strukturált JSON, Pydantic-validálás, programozott idézetellenőrzés, egy javítási kísérlet, külön szemantikai lépés), de **valódi adapter nincs**. Ok: a repo `CLAUDE.md`-je és `config/guard_policy.json`-ja tiltja a harmadik szolgáltatót (az `anthropic` importot minden PR-en hibának veszi). A szabályt nem módosítottam. Döntés kell: jóváhagyott szabályváltás után `anthropic_provider.py`, vagy a már engedélyezett Gemini illesztése (éles hívás itt nem indítható).
- Az idézetellenőrzés és a státuszok (`source_claim`, `repeated_across_sources`, `unsupported`) tesztelve; `verified` nincs.

## Eltérések a megadott javaslattól
- A tároló nem üres, ezért a már meglévő `video_research/` csomagot bővítettem, nem hoztam létre külön `app/` fát.
- Migráció: saját, verziózott SQL (`migrations/0001_init.sql`), nem Alembic. SQLAlchemy Core, nem ORM. **Csak SQLite-on futtattam**, PostgreSQL-en nem; a Docker Compose megírva, nem indítottam.
- Nincs `JobStep`/`FindingEvidence` külön ORM-modell: `job_steps` tábla, a bizonyíték a `Finding.source_references` (SourceReference).
- A videók **feladatonként** tárolódnak; a feladatok közötti gyorsítótár és a `platform+platform_video_id` globális egyediség **nincs** (a törlés ezért nem érint más feladatot).
- A `plan` állapotot a worker használja (`queued → planning → awaiting_approval`), a spec állapotlistáján felül.
- Felület: egyetlen, szerver által kiszolgált HTML (`templates/index.html`), nincs keretrendszer, nem megbízható szöveg csak `textContent`-tel jelenik meg.
- Anthropic-kulcs/modell konfigurációs nevek (`ANTHROPIC_*`) nincsenek, mert nincs LLM-adapter; `TRANSCRIPTION_PROVIDER` sincs (nincs átíró). A többi név alias vagy `VR_*`.

## Ismert biztonsági és üzemeltetési hiányok
- Az API-kulcsos MVP egyfelhasználós, TLS, korlátozás és auditnapló nélkül: nyilvános internetre változtatás nélkül nem tehető ki.
- Nincs sebességkorlát az API-n; a `VR_MAX_PARALLEL_RUNS` nem érvényesül (soros feldolgozás).
- Ideiglenes médiafájl nincs (nincs letöltés), ezért a törlésük sem tesztelt.
- Nincs ütemezett megőrzés-törlés: a `python -m video_research.main purge` kézzel/cronból futtatandó.
- A hosszt nem ismerő videóknál (oEmbed) a videóperc-keret nem érvényesíthető; a jelentés ezt jelzi.
- A worker-újraindulás és a lease-átvétel SQLite-on tesztelt; PostgreSQL alatti versengést nem próbáltam.
- A prompt-injekció elleni védelem szerkezeti (elválasztott blokk, lezáró jel kiszűrése, programozott kimenet-ellenőrzés), nem garancia valódi modell ellen: valódi modellel nem próbáltam.
