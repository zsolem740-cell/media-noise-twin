# Gemini-próbaterv (a valódi modellmérés: jóváhagyásra vár, az ügynök NEM futtatta)

## Szabályok, amelyeket ellenőriztem
- `CLAUDE.md`: elsődleges szolgáltató a Gemini; **„Tilos valódi Gemini vagy Groq API-hívást indítani; csak hamis átvitellel tesztelj.”** Ezért az ügynök nem indít éles hívást, és ezt a tiltást nem módosítottam. Tilos a fizetős csomagra váltás és a harmadik szolgáltató; kvótakimerülésnél a futás azonnal megáll (nincs szolgáltatóváltás); minden kérésnél napló: szolgáltató, modell, kimenetel, tokenek; kulcs soha nem kerülhet naplóba.
- `config/guard_policy.json`: az `anthropic` stb. tiltott; a `generativelanguage.googleapis.com` hosztnév csak a kijelölt átviteli fájlokban szerepelhet. Ezért az adapter (`llm_gemini.py`) a projekt meglévő `validation/hu_pilot/live/transport.py` átvitelét és `providers._envelope` válaszfeldolgozását használja, és saját fájlban nincs hosztnév. A `policy_guard` tiszta.
- Hálózat: a környezeti szabály már engedi a `generativelanguage.googleapis.com` hosztot (ez a korábbi pilotból származik); új engedély nem kellett.
- Tehát: a kód kész és hamis átvitellel tesztelt; **valódi hívást csak a felhasználó indíthat, saját kulccsal**, a `CLAUDE.md` tiltásának saját, tudatos feloldásával (ha ezt akarod, azt te döntöd el; én nem oldom fel).

## Jóváhagyott feltételek és az előfeltételek állapota (2026-11-21)
A tulajdonos egyetlen futást engedélyezett az alábbi keretekkel. **Az indítás két igazolatlan előfeltétel miatt még NEM történt meg; hívás nem volt.**

| Feltétel | Állapot |
|---|---|
| Egy teljes futás; 3 indító eset (`A_tools` magyar kérdés + angol átirat; `G_needle` egy részlet sok zajban; `D_irrelevant` irreleváns, nulla találat), majd a többi 11; az indítók beleszámítanak a keretbe | a vezérlő megvalósítva és hamis átvitellel tesztelve (`acceptance/live.py`, `tests/test_live_controller.py`) |
| ≤ 45 tényleges hálózati kérés (újrapróbálással és javítással) | átvitel-szinten kikényszerítve, minden kérés előtt ellenőrizve |
| ≤ 220 000 összes token, a jelentett gondolkodási tokenekkel | minden kérés előtt: becsült bemenet + `maxOutputTokens` ≤ maradék; a válaszból `max(total, prompt+candidates+thoughts)` számolódik |
| ≤ 20 perc | kikényszerítve (a 13 s kérésköz is beleszámít) |
| Kvótakimerülés, hitelesítési/technikai hiba, modell- vagy szolgáltatóváltás, titok a kérésben: megállás | kikényszerítve; tartalmi hiba (blokkolt, csonka, érvénytelen válasz) rögzítve, a futás megy tovább |
| Lefagyasztott bemenet: commit SHA, tiszta munkafa, prompt-verzió (hash), eset-, kiértékelő- és kinyerő-hash, modellazonosító | a futás előtt jegyzék, a futás végén újraellenőrzés; eltérés = érvénytelen futás |
| Nyers modellkimenet és feldolgozott eredmény külön, titok nélkül | `raw_model_io.json` / `processed_results.json` (a `results/` mappa nincs a repóban) |
| **Igazoltan ingyenes projekt és modell** | **NEM igazolt** (lásd lent): az ügynök ezt nem tudja ellenőrizni → megállás |
| **Szabályengedély (CLAUDE.md)** | **Tulajdonosi szabálymódosítás szükséges; jóváhagyásra vár** (lásd lent) |
| **Pontos modellazonosító** | **A felhasználónak kell megadnia** (nincs elfogadott érték a projektben: lásd lent) |

Indítás (csak az összes igazolás és a szabály-jóváhagyás után): `VR_GEMINI_MODEL=<azonosító> python -m video_research.acceptance.runner --live --attest-free-tier --attest-no-billing --attest-owner-rule-change --max-requests 45 --max-tokens 220000 --max-seconds 1200`. A három `--attest-*` kapcsoló **a tulajdonos igazolása**, nem az ügynöké; igazolás nélkül a program nem hív. Nem tiszta munkafával nem indul.

## A valódi modell elfogadási feltétele (nem a modell önminősítése)
A siker a kézi elvárás (`gold`) ellen mérendő: kimaradt-e elvárt tétel, került-e be téves, helyes-e az idézet és a forráskapcsolat (létező szegmens, az idézet a szegmens szövege, az időbélyeg a fájlból való), megmarad-e a korlátozás a magyar állításban, minden nyomnak van-e ellenőrzési kérdése. A modell saját `relevance`/`concrete`/`consistent` jelzése csak bemenet a kapukhoz, nem elfogadási feltétel.

## Mit mér majd, és mit nem
Mér: kimarad-e elvárt tétel, kerül-e be téves, helyes-e az idézet, megmarad-e a korlátozás a magyar állításban, különbözik-e A és B a kérdés szerint, magyar kérdés + angol átirat közös kulcsszó nélkül, injekció, reklám, nulla találat. Nem mér: nagy mintán vett pontosságot (9 eset anekdotikus), költséget pénzben, hosszú (több órás) átiratok viselkedését.


## Első, kisebb próba (előkészítés, 2026-11-21; jóváhagyásra vár, hívás nem volt)
- Modell: `gemini-3.6-flash` (tervezett azonosító; ez még **nem** futtatási engedély és **nem** igazolt ingyenesség).
- Esetek: `A_tools` (magyar kérdés, angol átirat), `G_needle` (egy hasznos részlet sok zajban), `D_irrelevant` (irreleváns, elvárt nulla találat).
- Javasolt plafon: 6 tényleges kérés (minden retry és javítás beleszámít), 30 000 összes token, 600 s, nincs modell-/szolgáltatóváltás.
- **Hívás nélküli illeszkedés-vizsgálat (a meglévő vezérlő, hamis átvitel, 1500 token/kérés):** a három eset legalább **7 kérést** igényel még újrapróbálás és javítás nélkül is (A: 1 kinyerés + 3 szemantikai ellenőrzés; G: 1 + 1; D: 1), ezért a **6 kérés nem elég**: a 6. kérés után a `D_irrelevant` nem fut le. Az idő (≈7 × 13 s kérésköz ≈ 1,5 perc) és a token (≈11 ezer hamis értékkel) belefér; a valós gondolkodási tokenszám ismeretlen. A tételszám a valódi modellnél más lehet, ami a szemantikai hívások számát változtatja.
- A vezérlőnek **nincs részhalmaz-kapcsolója**: a jelenlegi `--live` mind a 14 esetet futtatná; a három esetre szűkítés kódváltoztatás (nem végeztem el). A vizsgálatot egy eldobható szkripttel végeztem, a repó módosítása nélkül.
- Döntés a tulajdonosé: a kérésplafon emelése (legalább 7, tartalékkal pl. 10), a szemantikai ellenőrzés kikapcsolása (kódváltoztatás kell), vagy a plafon megtartása azzal, hogy a `D_irrelevant` nem fut le. Önállóan nem növeltem.

## Ismert korlát: közös kvótakeret az óránkénti bottal
A `.github/workflows/gemini-labels.yml` óránként fut (`cron: 17 * * * *`), a `GEMINI_API_KEY` titkot és a `GEMINI_MODEL` változót használja. A Gemini limitjei **projektenként és modellenként** érvényesek, ezért ha a próba kulcsa ugyanahhoz a projekthez tartozik, és a bot ugyanazt a modellt használja, a napi (RPD) és percenkénti keret közös: a próba fogyaszthatja a bot keretét, és a bot a próbáét. A bot napi felhasználását a próba előtt a tulajdonosnak kell figyelembe vennie. A botot nem módosítottam és nem állítottam le. Hogy ugyanaz-e a projekt és a modell, innen nem állapítható meg.
