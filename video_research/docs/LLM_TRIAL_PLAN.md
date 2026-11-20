# Gemini-próbaterv (a valódi modellmérés: jóváhagyásra vár, az ügynök NEM futtatta)

## Szabályok, amelyeket ellenőriztem
- `CLAUDE.md`: elsődleges szolgáltató a Gemini; **„Tilos valódi Gemini vagy Groq API-hívást indítani; csak hamis átvitellel tesztelj.”** Ezért az ügynök nem indít éles hívást, és ezt a tiltást nem módosítottam. Tilos a fizetős csomagra váltás és a harmadik szolgáltató; kvótakimerülésnél a futás azonnal megáll (nincs szolgáltatóváltás); minden kérésnél napló: szolgáltató, modell, kimenetel, tokenek; kulcs soha nem kerülhet naplóba.
- `config/guard_policy.json`: az `anthropic` stb. tiltott; a `generativelanguage.googleapis.com` hosztnév csak a kijelölt átviteli fájlokban szerepelhet. Ezért az adapter (`llm_gemini.py`) a projekt meglévő `validation/hu_pilot/live/transport.py` átvitelét és `providers._envelope` válaszfeldolgozását használja, és saját fájlban nincs hosztnév. A `policy_guard` tiszta.
- Hálózat: a környezeti szabály már engedi a `generativelanguage.googleapis.com` hosztot (ez a korábbi pilotból származik); új engedély nem kellett.
- Tehát: a kód kész és hamis átvitellel tesztelt; **valódi hívást csak a felhasználó indíthat, saját kulccsal**, a `CLAUDE.md` tiltásának saját, tudatos feloldásával (ha ezt akarod, azt te döntöd el; én nem oldom fel).

## Javasolt próba
- Parancs: `GEMINI_API_KEY=… VR_GEMINI_MODEL=<a te modelled> python -m video_research.acceptance.runner --live --max-calls 30` (opcionális: `--no-semantic`).
- Tartalom: a 9 elfogadási eset (a szándékosan hibás `B_lossy` nélkül), ugyanazok a kézi elvárások mint a hamisított futásban; a kimenet bemenetet, tényleges kimenetet és eltérést mutat.
- Hívásszám: 9 kinyerés + tételenként 1 szemantikai ellenőrzés (a hamisított futásban 11 tétel) + legfeljebb 1 javítási kísérlet esetenként: **≈ 20 várható, legfeljebb 29 hívás**; kemény plafon: `--max-calls 30` (a program megáll, ha eléri).
- Tokenek (becslés): bemenet ≈ 12 ezer (kinyerés) + ≈ 2–3 ezer (szemantikai); kimenet hívásonként legfeljebb 4096 (`maxOutputTokens`), jellemzően jóval kevesebb. **Tokenplafon: ≤ 150 ezer összesen** (29 × 4096 ≈ 119 ezer a kimeneti felső korlát).
- Tempó: 13 s minimális kérésköz (a pilot `min_interval_s` értéke) → kb. 5–7 perc.
- Költségkeret: **0 USD pénzbeli költség**: a próba az ingyenes szint kvótáján belül marad, mert a fizetős csomag a projektben tilos. Árat nem becsülök (nem tudom a csomagodat). Ha a kvóta kimerül, a futás megáll (`LLMQuotaExhausted`), semmi sem vált másik szolgáltatóra.
- Gépelt megerősítés („IGEN”) nélkül nem indul hívás. A kulcs nem kerül kimenetre, naplóba vagy fájlba.
- **Jóváhagyás:** erre a tervre külön, kifejezett jóváhagyást kérek; addig nincs valódi modellhívás.

## Mit mér majd, és mit nem
Mér: kimarad-e elvárt tétel, kerül-e be téves, helyes-e az idézet, megmarad-e a korlátozás a magyar állításban, különbözik-e A és B a kérdés szerint, magyar kérdés + angol átirat közös kulcsszó nélkül, injekció, reklám, nulla találat. Nem mér: nagy mintán vett pontosságot (9 eset anekdotikus), költséget pénzben, hosszú (több órás) átiratok viselkedését.
