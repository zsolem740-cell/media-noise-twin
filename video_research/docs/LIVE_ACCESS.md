# Szabályos, helyi átiratlekérés (élő adatelérési próba)

Cél: a felhasználó saját gépéről, **a blokkolás megkerülése és böngészőcookie nélkül** átiratot kérni egy nyilvános YouTube-videóhoz, és látni, mi történik. Ezt az ügynök felhős környezetéből nem tudtam teljesíteni: ott a YouTube blokkolta a feliratkérést (lásd lent).

## Menete
1. Elkülönített környezet: `python -m venv .venv && .venv/bin/pip install -r video_research/requirements.txt` (a `requirements.txt` tartalmazza a `youtube-transcript-api`-t és a `requests`-et).
2. Csak nyilvános, bárki által megnyitható videó. Bejelentkezés, cookie, jelszó, proxy-forgatás nincs és nem is kell.
3. Futtatás (modell nélkül, ingyenesen, a kulcsszavas baseline-nal; a jelentés ezt „NEM AI-elemzés”-ként jelöli):
   `.venv/bin/python -m video_research.trial "kérdés" https://www.youtube.com/watch?v=<azonosító>`
4. Értelmezd az állapotot:
   - `completed` + átirat a forráslistában: a lekérés sikerült.
   - `failed` + „A YouTube blokkolta a feliratkérést” vagy „átmeneti hálózati hiba”: **a letöltés nem sikerült**. Ez nem „nincs találat”: a jelentésben a „Nem találtam a feltételeknek megfelelő információt.” mondat csak akkor szerepel, ha legalább egy videó átirata ténylegesen feldolgozódott (teszt: `test_blocked_youtube_gives_failed_job…`).
   - `completed` + „Nincs hozzáférhető átirat”: a videónak nincs felirata (letiltott vagy nincs).
5. Ha blokkolt: ne ismételgesd tömegesen, ne használj proxy-forgatót vagy CAPTCHA-megoldót. Másik hálózat vagy a felirat kézi letöltése és **átiratimportja** (`POST /api/jobs/import`) a szabályos kerülőút; az import `user_provided_transcript` eredetű, és nem bizonyít platformintegrációt.

## Szükséges kimenő hosztok (a tényleges klienshívások alapján)
| Host | Ki hívja | Mire |
|---|---|---|
| `www.youtube.com` | `youtube-transcript-api` 1.2.5 (`_transcripts.py`: `https://www.youtube.com/watch?v={id}`, `…/youtubei/v1/player`, a lejátszó-válaszban kapott felirat-`baseUrl`) és a saját oEmbed (`adapters/youtube.py`, `…/oembed`) | felirat, metaadat |
| `www.tiktok.com` | `adapters/tiktok.py` (`…/oembed`) | csak metaadat |
Nem kérek általános domain- vagy internetengedélyt. A `consent.youtube.com` a kliens kódjában csak a sütilétrehozás szöveges ellenőrzésében szerepel (nem kapcsolódik hozzá); kérésben nem láttam. A felhős futásban a blokkolt kérés a `www.google.com/sorry/…` oldalra irányított: ezt a hosztot **nem** engedélyezzük, mert az a CAPTCHA-/botvédelmi oldal.
A Gemini-próbához (csak a felhasználó futtatja) a környezeti szabályban már szerepel a `generativelanguage.googleapis.com`.

## Mi történt az ügynök próbájakor (2026-11-20, felhős tároló)
- `www.youtube.com/oembed`: 200, a metaadat megjött („Me at the zoo”) → metaadat élőben igazolt.
- Feliratkérés: a YouTube a `www.google.com/sorry/…` oldalra irányította a kérést (IP-/botvédelem) → **nem sikerült**, nem kerültem meg. Élő átirat egyszer sem érkezett.
- `www.tiktok.com/oembed`: 200, de cím és szerző nélkül; átirat TikTokról nincs.
