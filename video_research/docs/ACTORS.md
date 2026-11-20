# Apify Actor kiválasztása (még NEM történt meg)

Ebben a kiadásban egyetlen Actor sincs kiválasztva vagy ellenőrizve, és nem találtam ki azonosítót. Az adapter addig `ProviderNotConfigured` hibát ad (éles módban érthető hiba, kitalált találat nincs).

## Ellenőrzőlista Actoronként (képességenként: `<platform>:<capability>`)
1. Az Actor létezik és elérhető az Apify Console/Store-ban (azonosító: `felhasználó/név`).
2. Elolvasva az aktuális **input**-séma → `input_template` (helyettesítők: `{url}`, `{query}`, `{max_items}`).
3. Elolvasva az aktuális **output**-séma → `output_map` (pontozott útvonalak; átirat: `segments`, `segment_text`, `segment_start`, `segment_end`, `language` vagy egész szöveg: `text`).
4. Árazás és korlátok rögzítve → `pricing_note`, `price_per_item_usd` (ha ismert), `max_cost_per_run_usd` (ez megy `max_total_charge_usd`-ként a futásnak).
5. Cookie/bejelentkezés kell-e → ha igen, az 1. verzióban nem használható (`requires_cookies_or_login: true` elutasítva).
6. A kiválasztás oka dokumentálva ide, a `verified_on` dátum kitöltve. `verified_on` nélkül az adapter nem hív.
7. Az átirat eredete: `transcript_origin` = `platform_caption` vagy `speech_to_text`.

## Példa (SÉMA, nem valódi Actor)
```json
{"youtube:fetch_transcript": {"actor_id": "<ELLENŐRZENDŐ>", "capability": "fetch_transcript",
  "input_template": {"<ellenőrzött input mező>": "{url}"},
  "output_map": {"segments": "0.<ellenőrzött mező>", "segment_text": "<mező>", "segment_start": "<mező>"},
  "verified_on": "ÉÉÉÉ-HH-NN", "max_cost_per_run_usd": 0.5}}
```
Ellenőrzött SDK-hívások (`apify-client` 3.5.1, példányon ellenőrizve): `ApifyClient(token)`, `.actor(id).start(run_input=, max_items=, max_total_charge_usd=)`, `.run(id).get()`, `.run(id).abort(gracefully=)`, `.dataset(id).iterate_items(limit=)`.
