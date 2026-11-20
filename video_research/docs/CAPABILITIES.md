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

## Termékcél: zajból a kevés érdemi információ (nem általános összefoglaló)
Az „1–2% hasznos tartalom” célkép, **nem mért arány és nem kvóta**: a kódban nincs rögzített kiválasztási arány vagy darabszám-plafon (teszt: 30 releváns szegmens → 30 megtartott; releváns szegmens nélkül → üres jelentés).
- **Nincs kötelező találat.** Ha a feldolgozott videókban nincs megfelelő részlet: a feladat `completed`, a jelentés „Nem találtam a feltételeknek megfelelő információt.”, és nem töltjük fel. (Ha nem sikerült feldolgozni a videókat, az más: `failed`/`partially_completed`, hiányokkal.)
- **Részletszintű szűrés:** a jelölt egy szegmens(csoport), nem a videó. Egy gyenge videó egyetlen jó részlete megmarad, egy jó videó irreleváns részei kimaradnak.
- **Két külön tengely.** *Hasznosság:* `relevance` (direct/partial), `concrete`, `disposition` (keep/lead). *Alátámasztottság:* `evidence_status` (source_claim / repeated_across_sources / unsupported) és a szemantikai ellenőrzés. A pontos idézet megléte csak annyit jelent, hogy az átiratban elhangzott, nem azt, hogy igaz; a jelentés ezt kimondja. Az ismétlés nem igazolás.
- **Három kimeneti csoport:** megtartandó információk (`keep`), ellenőrizendő nyomok (`lead`: részben releváns, a modell kétsége, kétes jelentésbeli egyezés, gyenge kulcsszó-egyezés), kihagyott részletek (szűrési napló, rövid indokkal).
- **Megtartási kapu** (`extraction._validate_items`): releváns, konkrét, programozottan igazolt idézet, és nem a felhasználó által megadott `known_information` ismétlése. A kapu után az ismétlés új forrásként csatolódik a meglévő megállapításhoz (`merge.py`); az eltérő feltétel (`condition`), ellenpélda (`stance`), verzió (`version`) vagy szám külön megállapítás marad, `related_ids`-kel összekötve. Az összevonás nem oldja fel a kétséget (a szigorúbb besorolás marad).
- **Rövid fő jelentés, külön részletek:** `GET /api/jobs/{id}/report` (rövid, idézet nélkül), `/evidence` (idézetek, szegmensek, időbélyegek, korlátok), `/filter-log` (kihagyott jelöltek és ismétlésként csatoltak, indokkal), `/export` (teljes). A szűrési napló csak a *javaslatba került* jelölteket naplózza; a javaslatba sem került szegmensek számát összesíti.
- **Visszajelzés:** `POST /api/jobs/{id}/findings/{fid}/feedback` — `useful`, `not_relevant`, `already_known`, `extracted_wrong`, `needs_check` (+ rövid megjegyzés). Tároljuk (`finding_feedback`, a történet is megmarad), a jelentés az utolsót mutatja. A `already_known` nem hamis és nem értéktelen: a megállapítás a helyén marad. **Nincs automatikus modellbetanítás vagy önfejlesztés, és nem is ígérünk ilyet**: a visszajelzés nem változtat a kinyerésen (teszt: ugyanaz a bemenet ugyanazt adja).
- **„ResearchBrief”:** ilyen modell nincs a tárolóban; a kutatási kérdés és kontextus a meglévő `ResearchPlan`-ben él (`question`, új `known_information`), a hash-es jóváhagyás is ezt fedi. Párhuzamos rendszert nem építettem.
- Korlát: a modell nélküli alapút (`extractive.py`) kulcsszó-egyezéssel dönt, ezért gyenge: az általános bevezető sorok is `lead`-ként bekerülhetnek. A valódi szűrési minőség modellt igényel, amit nem próbáltam ki.

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
