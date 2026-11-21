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


## Első, kisebb próba — frissített, NEM jóváhagyott futási keret (2026-11-21)
- **Futásazonosító (javasolt, a jóváhagyásnak ezt kell megneveznie):** `LIVE-G36F-3C-001`
- **Modell:** `gemini-3.6-flash` (tervezett azonosító; nem engedély, nem igazolt ingyenesség). Nincs modell- vagy szolgáltatóváltás: más modellel válaszoló szolgáltató megállítja a futást.
- **Esetek (explicit `--cases`, csak ezek futnak, ebben a sorrendben):** `A_tools`, `G_needle`, `D_irrelevant`. A szemantikai ellenőrzés **bekapcsolva** marad.
- **Keret:** legfeljebb **10 tényleges API-kérés** (minden retry és javítás beleszámít), legfeljebb **30 000 összes szolgáltatói token**, legfeljebb **600 s**.
- **A 10 kérés nem garantál teljes befejezést.** Hívás nélkül mért minimum a három esetre: 7 kérés (3 kinyerés + 4 szemantikai ellenőrzés, hamis átvitellel, a hamisító modell tételszámával). Valódi modellnél a tételszám, a retry és a javítás miatt több is lehet; a maradék 3 kérés tartalék, nem garancia.
- **Keretkimerülés = részleges állapot, nem hiba elrejtése.** A kész esetek és az ellenőrzött tételek megmaradnak; a ki nem futott esetek (`cases_not_run`), a részlegesek (`cases_partial`) és a ki nem szűrt/ellenőrizetlen tételek (`unchecked_not_results`) külön jelölve vannak. **Az a kinyert tétel, amelynek a szemantikai ellenőrzése elmaradt, nem szerepel a megállapítások között és nem „ellenőrzött eredmény”**; külön listában van, „NEM eredmény” felirattal, és a lefedettség `semantic_check_incomplete` okot mutat.
- **Pontos indítóparancs** (a tulajdonos a saját környezetében; a `GEMINI_API_KEY` az ő környezetében van; a három `--attest-*` kapcsoló **az ő igazolása**, az ügynök nem állította be):
  `VR_GEMINI_MODEL=gemini-3.6-flash python -m video_research.acceptance.runner --live --cases A_tools,G_needle,D_irrelevant --run-id LIVE-G36F-3C-001 --max-requests 10 --max-tokens 30000 --max-seconds 600 --attest-free-tier --attest-no-billing --attest-owner-rule-change`
  Minden paraméter kötelező (nincs alapérték); üres, hibás, ismeretlen, kizárt vagy ismétlődő esetlistára, hiányzó futásazonosítóra/keretre, használt futásazonosítóra, nem tiszta munkafára a program hívás nélkül megáll.

### Mit garantál a keret és mit nem (pontosan)
| Keret | Kikényszerítés | Szigorú? |
|---|---|---|
| Kérésszám | az átvitel-rétegben minden tényleges kérés előtt; az újrapróbálás és a javítás is ott megy át | **Igen**: a 11. kérés nem indulhat (tesztelve) |
| Idő (600 s) | minden kérés előtt (a 13 s kérésköz várakozása után) | Részben: a már elindított kérés befejeződhet; a túllépés legfeljebb egy kérés időkorlátja (60 s) |
| Token (30 000) | minden kérés előtt: **konzervatív becsült bemenet** (kérés-törzs karakterszáma/2 + 1, nem tokenizáló) + a kérésben beállított `maxOutputTokens` (kinyerés 4096, szemantikai 50) ≤ maradék; a válasz után a ténylegesen jelentett tokenek (`max(total, prompt+candidates+thoughts)`) számolódnak | **NEM kemény plafon.** Lásd lent. |

A token-plafon azért nem szigorú, mert (1) a valódi bemeneti tokenszámot csak a válaszból tudjuk meg (az előzetes `countTokens` újabb API-kérés volna), a becslés heurisztika; (2) a gondolkodási tokenekre **nem állítottam be korlátot**: a `gemini-3.6-flash`-hoz tartozó gondolkodás-korlát mező nevét nem ellenőriztem és nem találom ki, és azt sem igazoltam, hogy a `maxOutputTokens` a gondolkodási tokeneket is korlátozza erre a modellre; így egy válasz a foglalást ismeretlen mértékben túllépheti; (3) időtúllépett vagy hibás kérés tényleges tokenhasználata ismeretlen (kérésként számolt, tokenként 0); (4) a szolgáltató oldali elszámolás eltérhet a saját számlálótól. Garantált tulajdonság: **új kérés nem indul, ha a már számolt tokenek + a konzervatív foglalás meghaladná a plafont**; az utólagos számlálás önmagában nem plafon, és nem is nevezem annak.
Ismert kockázat: a szemantikai ellenőrzés kimeneti korlátja 50 token; gondolkodó modellnél ez csonkolást okozhat, ilyenkor az érintett tétel **ellenőrizetlen** marad (nem elfogadott). Nem módosítottam (a prompt/paraméter lefagyasztott; módosítás új verziózott futás).

## Ismert korlát: közös kvótakeret az óránkénti bottal
A `.github/workflows/gemini-labels.yml` óránként fut (`cron: 17 * * * *`), a `GEMINI_API_KEY` titkot és a `GEMINI_MODEL` változót használja. A Gemini limitjei **projektenként és modellenként** érvényesek, ezért ha a próba kulcsa ugyanahhoz a projekthez tartozik, és a bot ugyanazt a modellt használja, a napi (RPD) és percenkénti keret közös: a próba fogyaszthatja a bot keretét, és a bot a próbáét. A bot napi felhasználását a próba előtt a tulajdonosnak kell figyelembe vennie. A botot nem módosítottam és nem állítottam le. Hogy ugyanaz-e a projekt és a modell, innen nem állapítható meg.
