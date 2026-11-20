# Gemini-próbaterv (a valódi modellmérés: jóváhagyásra vár, az ügynök NEM futtatta)

## Szabályok, amelyeket ellenőriztem
- `CLAUDE.md`: elsődleges szolgáltató a Gemini; **„Tilos valódi Gemini vagy Groq API-hívást indítani; csak hamis átvitellel tesztelj.”** Ezért az ügynök nem indít éles hívást, és ezt a tiltást nem módosítottam. Tilos a fizetős csomagra váltás és a harmadik szolgáltató; kvótakimerülésnél a futás azonnal megáll (nincs szolgáltatóváltás); minden kérésnél napló: szolgáltató, modell, kimenetel, tokenek; kulcs soha nem kerülhet naplóba.
- `config/guard_policy.json`: az `anthropic` stb. tiltott; a `generativelanguage.googleapis.com` hosztnév csak a kijelölt átviteli fájlokban szerepelhet. Ezért az adapter (`llm_gemini.py`) a projekt meglévő `validation/hu_pilot/live/transport.py` átvitelét és `providers._envelope` válaszfeldolgozását használja, és saját fájlban nincs hosztnév. A `policy_guard` tiszta.
- Hálózat: a környezeti szabály már engedi a `generativelanguage.googleapis.com` hosztot (ez a korábbi pilotból származik); új engedély nem kellett.
- Tehát: a kód kész és hamis átvitellel tesztelt; **valódi hívást csak a felhasználó indíthat, saját kulccsal**, a `CLAUDE.md` tiltásának saját, tudatos feloldásával (ha ezt akarod, azt te döntöd el; én nem oldom fel).

## Javasolt próba (konkrét terv és keret; JÓVÁHAGYÁSRA VÁR)
- Ellenőrzött előfeltételek: a `guard_policy.json` `allowed_providers` listáján a `gemini` szerepel; a `CLAUDE.md` szerint elsődleges szolgáltató; a hálózati szabály engedi a `generativelanguage.googleapis.com` hosztot; a `GEMINI_API_KEY` környezeti változó be van állítva ebben a környezetben (az értékét nem olvastam és nem használtam). **Engedélyezett szolgáltató, de a valódi hívást a `CLAUDE.md` az ügynöknek tiltja**, ezért nem indítottam.
- Parancs (a te gépeden vagy a te kifejezett, esetenkénti jóváhagyásoddal): `GEMINI_API_KEY=… VR_GEMINI_MODEL=<a te modelled> python -m video_research.acceptance.runner --live --max-calls 45` (opcionális: `--no-semantic`).
- Tartalom: **14 elfogadási eset** (a modellhívás nélküli, szándékosan hibás `B_lossy` nélkül), ugyanazok a kézi elvárások, mint a hamisított futásban. Az A és B kérdés ugyanazon az átiraton szerepel.
- Hívásszám: 14 kinyerés + tételenként 1 szemantikai ellenőrzés (a hamisított futásban 15 tétel) + legfeljebb 1 javítási kísérlet esetenként. **Várható ≈ 29, legfeljebb 43 hívás.** Kemény plafon: `--max-calls 45` (a program megáll, ha eléri).
- Tokenek (becslés): bemenet ≈ 24 ezer (kinyerés) + ≈ 3 ezer (szemantikai); kimenet hívásonként legfeljebb 4096, jellemzően jóval kevesebb. **Tokenplafon: ≤ 220 ezer összesen** (43 × 4096 ≈ 176 ezer a kimeneti felső korlát + bemenet).
- Tempó: 13 s minimális kérésköz → kb. 8–10 perc.
- Költségkeret: **0 USD pénzbeli költség**: az ingyenes szint kvótáján belül; a fizetős csomag a projektben tilos, árat nem becsülök. Kvótakimerüléskor a futás megáll (`LLMQuotaExhausted`), nincs szolgáltatóváltás.
- Gépelt megerősítés („IGEN”) nélkül nem indul hívás. A kulcs nem kerül kimenetre, naplóba vagy fájlba.
- **Kérem a kifejezett jóváhagyásodat erre a konkrét tervre és keretre** (és azt, hogy a `CLAUDE.md` „tilos valódi Gemini-hívás” szabályát erre az egy futásra te oldod fel, vagy te futtatod). Addig nincs valódi modellhívás.

## A valódi modell elfogadási feltétele (nem a modell önminősítése)
A siker a kézi elvárás (`gold`) ellen mérendő: kimaradt-e elvárt tétel, került-e be téves, helyes-e az idézet és a forráskapcsolat (létező szegmens, az idézet a szegmens szövege, az időbélyeg a fájlból való), megmarad-e a korlátozás a magyar állításban, minden nyomnak van-e ellenőrzési kérdése. A modell saját `relevance`/`concrete`/`consistent` jelzése csak bemenet a kapukhoz, nem elfogadási feltétel.

## Mit mér majd, és mit nem
Mér: kimarad-e elvárt tétel, kerül-e be téves, helyes-e az idézet, megmarad-e a korlátozás a magyar állításban, különbözik-e A és B a kérdés szerint, magyar kérdés + angol átirat közös kulcsszó nélkül, injekció, reklám, nulla találat. Nem mér: nagy mintán vett pontosságot (9 eset anekdotikus), költséget pénzben, hosszú (több órás) átiratok viselkedését.
