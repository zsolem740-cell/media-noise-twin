# Külső projektek értékelése (2026-11-20)

Módszer: a három nyilvános tárolót `git clone --depth 1` paranccsal, hookok nélkül, a munkakönyvtáron kívüli, elkülönített mappába töltöttem le, és a forráskódot olvastam. **Semmit nem telepítettem és nem futtattam belőlük** (sem telepítőszkriptet, sem tesztet), ezért működésükre vonatkozó állítás nincs, csak olvasott kódra épülő megállapítás. Cookie-t, jelszót, kulcsot nem használtam.

| | NeuroLearn | social-media-scraper-skill | media-mcp |
|---|---|---|---|
| Vizsgált commit | `0a94570fb2ad2d9e0080cfd1ab2943a5b70edf2d` (2026-11-13) | `ddba8369f3e1a526ec193289abdf82784da5de3f` (2026-06-06) | `76585dec7f94ea9b4c2086de34222088024b3c20` (2026-08-20) |
| Licenc | MIT (`LICENSE`) | MIT | MIT |
| Természet | Python CLI + Claude-plugin, 371 fájl, ~55 ezer sor Python, 168 tesztfájl | **Nincs kód**: `SKILL.md` + `install.sh`/`setup.sh` (6 fájl) | Node/TypeScript MCP-szerver, ~30 eszköz, 6 tesztfájl, 0 Python |

## README-ígéret és tényleges kód

**NeuroLearn**
- *„YouTube, Instagram, TikTok”*: a transzkripció YouTube-ra feliratalapú (`skills/neurolearn/backends/subtitles.py`: `youtube-transcript-api`, tartalék `yt-dlp` felirat), más platformra hang-letöltés + beszédfelismerés (`utils/downloader.py`, `backends/groq.py` …). Platformfelirat TikTokra nincs.
- *„discover videos by topic across YouTube, IG, and TikTok”*: a `research/source.py` **csak YouTube-keresést** végez (`youtube_api.search_videos`, tartalék `ytsearchN:` yt-dlp-vel). A TikTok/IG a `subscribes` (csatornakövetés) alatt él, és ott a cookie-fájl kérése beépített (`subscribes/cli.py:65-68`, `410-413`).
- *Magyar nyelv*: nincs magyar-specifikus kód vagy teszt (grep: 0 találat). A felirat-nyelv paraméterezhető (`language`), a Whisper többnyelvű, de a magyarra nincs bizonyíték. A beépített nyelvi elemek (`pymorphy3`, `lemminflect`) orosz/angol célúak.
- *Időbélyeg*: a `Segment` (`utils/output_writer.py:16`) `start/end` mezője **nem nullázható**; időbélyeg nélküli szövegre a `utils/transcript_loader.py:94` `Segment(start=0.0, end=0.0, …)`-t gyárt. Ez a kért „ha nincs időbélyeg, maradjon null” elvvel ütközik. A Gemini-átiratnál az időbélyeget a modell generálja (`backends/gemini.py:34`, dokumentált eltolódási hibával, `:85-116`).
- *Vizuális elemzés*: valódi (`vision/frames.py`: ffmpeg kulcskockák; `vision/ocr.py`; `report/grounding.py`: „vak bíró” képellenőrzés), de az elemzést Gemini végzi, vagy a Claude Code chat olvassa a képeket.
- *Forrásmegőrzés*: van `report/grounding.py`, de ez **képaláírás–képkocka** egyezést ellenőriz, nem állítás–átirat-idézetet. Nincs Finding/evidence adatmodell, nincs idézetellenőrzés.
- *Programozható interfész*: CLI (`click`) és Gradio webui (`webui/app.py`, opcionális). Nincs HTTP API, nincs importálható, stabil Python-felület (belépés: `skills.neurolearn.transcribe:cli`).
- *Költségkontroll*: kvóta-óvatosság és figyelmeztetés van (`research/pipeline.py:193-204`), jóváhagyás- vagy keretrendszer nincs.
- *Tesztek*: 168 tesztfájl, `uv run pytest` a CI-ban (`.github/workflows/test.yml`); nem futtattam.
- *Függőségek* (`pyproject.toml`): `yt-dlp[default,deno]`, `bgutil-ytdlp-pot-provider` (külön PO-token szerver kell), `google-genai`, `groq`, `openai`, `deepgram-sdk`, `assemblyai`, `faster-whisper`, `sentence-transformers`, `scenedetect[opencv]` … Több GB-os, nehéz csomag; **öt felhős szolgáltatói SDK alapból**. A `report` extra WeasyPrint (LGPL). `requires-python >=3.11,<3.14`.
- *Telepítő*: `install.sh:7` `curl -LsSf https://astral.sh/uv/install.sh | sh` (ellenőrizetlen szkript letöltése és futtatása), `brew install ffmpeg`. `install.ps1` hasonló. Nem futtattam.
- Pozitív: a cookie csak fájlból jön, a `--cookies-from-browser` szándékosan nincs támogatva (`config.py:161`, `README` IMPORTANT).

**social-media-scraper-skill**
- Ez promptszöveg, nem szoftver: nincs tesztelhető kód, nincs hibakezelés, nincs költségkontroll, nincs adatmodell. A táblázat „✅ Visual analysis” ígérete egy Gemini-hívást leíró utasítás (`SKILL.md`), nem implementáció.
- **Biztonsági ellentmondás a követelményeinkkel**: `SKILL.md:170` `yt-dlp --cookies-from-browser chrome` (böngészőcookie), `:131` „bird … auto-detects [Chrome cookies]”, `SKILL.md:37` a Gemini-kulcs bekérése a beszélgetésben, `install.sh:72-73`/`setup.sh:304-305` `pip --break-system-packages`, `sudo apt-get install`, `npm install -g @steipete/bird`. A kért biztonsági szabályokkal összeegyeztethetetlen.
- Időbélyeget a faster-whisper adhat; a TikTok-ág a `yt-dlp` letöltésre épül.

**media-mcp**
- *TikTok*: csak a képkocka-kivonás eszköznél szerepel (`src/index.ts:769-771`); a README szerint a Cobalt-támogatás későbbi (`README.md:383`). Átirat TikTokra nincs.
- *YouTube*: `youtube-transcript` (npm) felirat, `offset`/`duration` megmarad (`src/youtube.ts:91-100`); felirat híján whisper.cpp (`src/transcribe.ts`), ilyenkor `segments: []`: nincs időbélyeg, és a hibát a `catch {}` (`youtube.ts:~108`) elnyeli.
- Keresés nincs. Magyarra külön támogatás nincs. A whisper-modellt futásidőben tölti a Hugging Facéről (`src/whisper-models.ts:26`), ellenőrzőösszeg nélkül (nem találtam).
- Van újrapróbálás backoffal és jitterrel (`src/http.ts`), de nincs SSRF-szűrő a letöltő eszközökben (nem találtam hoszt-ellenőrzést), és a Twitter-eszközök login-cookie-t kérnek (`src/twitter.ts:969`).
- Stack: Node 20 + TypeScript, nem Python; a mi rendszerünk Python/FastAPI.

## Hiányelemzés a specifikációhoz képest

| Követelmény | NeuroLearn | scraper-skill | media-mcp |
|---|---|---|---|
| YouTube-link → felirat időbélyeggel | igen | csak whisper | igen |
| TikTok-link → átirat | csak hang+ASR (cookie-s sorok a követésnél) | utasítás, cookie-val | nincs |
| Kulcsszavas keresés | YouTube igen, TikTok nem | nincs | nincs |
| Magyar tesztelt | nincs bizonyíték | nincs | nincs |
| Null időbélyeg | **nem** (0.0-t gyárt) | – | részben (`segments: []`) |
| Állítás–idézet–szegmens modell, programozott ellenőrzés | **nincs** | nincs | nincs |
| `source_claim`/`repeated`/`unsupported` státusz, ismétlés ≠ igazolás | nincs | nincs | nincs |
| Terv-jóváhagyás hash-hez kötve, költségkeret | nincs | nincs | nincs |
| Tartós sor, lease/heartbeat, folytatás | nincs (CLI) | nincs | nincs |
| Hitelesített API | nincs | nincs | MCP (stdio) |
| Vizuális elemzés | van (Gemini/Claude-chat) | utasítás | képkocka-kivonás |
| Nincs felhős függés alapból | nem (5 SDK) | nem | részben |
| Nincs böngészőcookie / jelszó | részben (fájl-cookie) | **nem** | részben |

## Javaslat

**Saját implementáció** (a döntésed is ez), kiegészítve:
1. **Nem érdemes forkolni vagy változtatás nélkül használni a NeuroLearnt**: a hiányzó réteg (Finding/evidence, idézetellenőrzés, hash-es jóváhagyás, tartós sor, API) a lényeg, és ezek nem építhetők rá tisztán; a függőségei (5 felhős SDK, PO-token szerver, torch-os csomagok) ütköznek a repo szolgáltatói szabályaival, a nem nullázható `Segment` az időbélyeg-elvvel.
2. **Mintaként felhasználható ötletek** (újraírva, nem másolva): a felirat-nyelv „eredeti elöl” sorrendje (`backends/subtitles.py:407-423`), a halluzináció-szűrő és a csendhatár-szeletelés a későbbi beszédfelismerő útvonalhoz, a „vak bíró” képellenőrzés (`report/grounding.py`) a későbbi vizuális lépéshez.
3. **Később, M3/M4-ben megfontolható integráció**: a `yt-dlp` (YouTube/TikTok metaadat és kereső) és `faster-whisper` közvetlen, shell nélküli, pinelt függőségként; ezek licencét és a hálózati kimenetét külön ellenőrizni kell.
4. A social-media-scraper-skill nem használható (cookie, `--break-system-packages`, kulcs a chatben). A media-mcp csak ötletforrás (retry/jitter).

A saját implementáció állapota: `README.md`, `docs/CAPABILITIES.md`.
