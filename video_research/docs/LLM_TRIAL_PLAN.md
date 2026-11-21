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
