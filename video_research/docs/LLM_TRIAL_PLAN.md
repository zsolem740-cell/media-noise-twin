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
- **Keret:** legfeljebb **10 tényleges API-kérés** (minden retry és javítás beleszámít), **30 000 tokenes tervezési keret** (nem kemény plafon, lásd lent), **600 s** indítási időkeret (≤60 s dokumentált túlfutással).
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
### Generálási beállítások (konfigurációs verzió: `gen-cfg-2`) és indoklásuk
**Ok:** az eredeti szemantikai kérés `maxOutputTokens = 50` volt, gondolkodási beállítás nélkül. A Google dokumentációja szerint (Gemini thinking útmutató, „Token limits and max_output_tokens”) a kimeneti maximum a gondolkodási és a válaszokenekre **együtt** vonatkozik, kemény levágás; ha a modell gondolkodás közben eléri, a válasz csonka vagy üres (a gondolkodási tokeneket ettől még elszámolják), és kis maximum helyett a gondolkodási szint csökkentését javasolja. A `gemini-3.6-flash` alapértelmezett szintje `medium`, így az 50 token csonkolást vagy üres választ okozhatott volna.

| | Kinyerés (`findings`) | Szemantikai ellenőrzés (`semantic`) |
|---|---|---|
| `generationConfig.maxOutputTokens` | 4096 (változatlan) | **512** (volt: 50) |
| `generationConfig.thinkingConfig.thinkingLevel` | nincs beállítva (modell-alapérték, dok. szerint `medium`) | **`MINIMAL`** |
| `temperature`, `responseMimeType` | 0, `application/json` | 0, `application/json` |

- **Dokumentációs forrás és pontos ellenőrzés:** (1) a ténylegesen használt API a `generateContent` REST (`/v1beta/models/{model}:generateContent`, camelCase `generationConfig`; a repó meglévő, ellenőrzött átvitele). Ennek referenciája (`ai.google.dev/api/generate-content`, GenerationConfig) szerint létezik `thinkingConfig.thinkingLevel` (enum: `MINIMAL`, `LOW`, `MEDIUM`, `HIGH`, `XHIGH`; „Gemini 3 vagy újabb modellekhez ajánlott, korábbiaknál hibát ad”), `maxOutputTokens` és a használati mezők (`thoughtsTokenCount`, `totalTokenCount` = prompt + eszköz + gondolat + jelölt). (2) A gondolkodási útmutató modelltáblája szerint a `gemini-3.6-flash` szintjei: `minimal`, `low`, `medium`, `high`, alapértelmezett `medium`; a `minimal` „közel kikapcsolt” gondolkodás, **nem garantáltan nulla**. (3) Az útmutató példái az Interactions API-ra szólnak (`thinking_level`, `max_output_tokens`, snake_case), amelyet **nem használunk**; a „kimeneti maximum a gondolkodást is tartalmazza” kijelentés ott szerepel. A `generateContent` referencia `maxOutputTokens` leírása ezt nem mondja ki külön, ezért **óvatos feltevésként azonos viselkedést tételezünk fel**.
- **Miért `MINIMAL` és 512:** a feladat egy ~12 tokenes `{"verdict": …}` válasz; a dokumentáció egyszerű osztályozásra minimális gondolkodást javasol. A 512 a verdikt ~40-szerese, tehát a „közel kikapcsolt” gondolkodás kis maradéka is belefér, de a legrosszabb eset (4 szemantikai kérés × 512) is csak ≈2 ezer token foglalás. Nem vettem fel `thinkingBudget`-et (régebbi modellek mezője; a 3.x-hez a dok. a `thinkingLevel`-t ajánlja).
- **Nem ellenőrzött (hívás nélkül nem is lehet):** a `thinkingLevel` JSON-értékének írásmódja a REST-ben. A referencia nagybetűs enumneveket sorol (ezt használjuk: `"MINIMAL"`); az Interactions API példái kisbetűsek. Ha a szolgáltató ezt elutasítja (HTTP 400), az **technikai hiba, a futás megáll** (nem tartalmi elutasítás), és új verziózott futás kell. Hogy a `maxOutputTokens` valóban a gondolkodást is tartalmazza-e a `generateContent` útján: dokumentálatlan, óvatos feltevés.
- **Kinyerés: nem módosítottam** (kérésre csak a szemantikai ellenőrzés keretére kellett javaslat). Fennálló kockázat: közepes gondolkodás mellett a 4096-os kimeneti keret csonkolhat; ilyenkor a videó kimarad (`truncated`), és ez rögzítődik. Lehetséges új verzió (új jóváhagyással): `thinkingLevel: LOW` vagy nagyobb kimeneti keret a kinyerésre.

### Csonkolt, üres és érvénytelen válasz kezelése (offline tesztelve)
| Válasz | Besorolás | Eredmény |
|---|---|---|
| `finishReason = MAX_TOKENS` (akár csonka JSON-nal) | `truncated` | a tétel **ellenőrizetlen** (`check_failure: truncated`), nem „kétes”, nem tartalmi elutasítás, nem sikeres ellenőrzés |
| nincs candidate, csak gondolat-rész, üres szöveg | `empty` | ugyanígy ellenőrizetlen |
| JSON `verdict` nélkül, vagy ismeretlen verdikt | `invalid` | ugyanígy ellenőrizetlen (korábban „kétesnek” számított volna: javítva) |
| `{"verdict":"doubtful"}` | tartalmi ítélet | a tétel kimarad (`extraction_unreliable`), nem nyom |
| `{"verdict":"consistent"}` | sikeres ellenőrzés | a tétel megmarad |
Az ellenőrizetlen tételek külön listában („NEM eredmény”), a lefedettségben `semantic_check_incomplete`; a vezérlő a `truncated`/`empty` hibát `response_limit` osztályba sorolja (nem tartalmi, nem technikai-leállító). A futás megy tovább; a kérés-, token- és időkeret védi.

### Keretek és korlátaik (változatlanok)
- **Legfeljebb 10 tényleges kérés** — szigorú (átvitel-szinten, a 11. nem indulhat; retry és javítás beleszámít). Nem garantál teljes befejezést: a három eset minimuma 7 kérés.
- **30 000 token: tervezési keret, nem garantált kemény plafon.** Új kérés nem indul, ha a számolt tokenek + a konzervatív foglalás (kérés-törzs karakterszáma/2 + 1 és a `maxOutputTokens`) meghaladná. A tényleges használatot (`max(total, prompt+candidates+thoughts)`) a válaszok után számoljuk; a valós tokenszámot, a gondolkodási tokenek tényleges mennyiségét és az időtúllépett kérések használatát előre nem tudjuk. **Illeszkedés:** a 7 minimális kérés foglalásainak összege (a jelenlegi promptokkal, hamis átvitellel mérve) ≈ 23,9 ezer, vagyis még ha mind elérné a kimeneti keretét, belefér; a maradék ≈ 6 ezer miatt a 3 tartalék kérés (egy kinyerő/javító kérés foglalása ≈ 6,4–7,4 ezer) legrosszabb esetben **nem indulhat el**, ez nem hiba, hanem a keret működése. A keretet nem emeltem.
- **600 s indítási időkeret:** minden kérés előtt ellenőrizve (a 13 s kérésköz várakozása után); a már elindított kérés befejeződhet, **legfeljebb 60 s dokumentált túlfutással** (kérésenkénti időkorlát). A 7–10 kérés ≈ 1,5–2,2 perc kérésközzel belefér.
- Nincs modell- vagy szolgáltatóváltás; kvóta, hitelesítés, 400/403, modellváltás megállítja a futást.

## Ismert korlát: közös kvótakeret az óránkénti bottal
A `.github/workflows/gemini-labels.yml` óránként fut (`cron: 17 * * * *`), a `GEMINI_API_KEY` titkot és a `GEMINI_MODEL` változót használja. A Gemini limitjei **projektenként és modellenként** érvényesek, ezért ha a próba kulcsa ugyanahhoz a projekthez tartozik, és a bot ugyanazt a modellt használja, a napi (RPD) és percenkénti keret közös: a próba fogyaszthatja a bot keretét, és a bot a próbáét. A bot napi felhasználását a próba előtt a tulajdonosnak kell figyelembe vennie. A botot nem módosítottam és nem állítottam le. Hogy ugyanaz-e a projekt és a modell, innen nem állapítható meg.
