# Kereskedelmi modell (1. alap)

Külön, a Média-Zaj pilottól **független** modul (nem importál a `validation/hu_pilot/` alól, és a v1/v2/v3 promptokhoz nem nyúl). A felépítése a Média-Zaj módszerét követi: előbb a szabálykönyv és a rögzített kapu, utána a hálózatmentes mag hamis vagy szintetikus adattal, az éles réteg utoljára és csak külön jóváhagyással.

**A cél a megvalósíthatóság, nem a hozam.** A modul azt dönti majd el, hogy egy előre rögzített módszer a rögzített szabályok szerint, költségekkel együtt megáll-e egy zárt teszttartományon. Nem ad befektetési tanácsot, és nem ígér hozamot.

## Mi van most (1. alap)
- `docs/SZABALYOK.md`: a modul szabálykönyve (tiltások, a kapu és a zárt teszt szabályai).
- `docs/ADATSZERZODES.md`: az árfolyam-idősor formátuma és ellenőrzési szabályai.
- `docs/KUTATASI_KERDES_ES_KAPU.md`: a kutatási kérdés és a kapu **tervezete, nem rögzített, jóváhagyásra vár**.
- `data.py`: az adatszerződés szigorú ellenőrzése (nincs csendes javítás, kizárás vagy típusátalakítás).
- `synthetic.py`: determinisztikus, szintetikusnak jelölt idősor-generátor.
- `tests/`: tesztek, szintetikus fixture-rel és a közös hálózati zárral.

## Mi NINCS (szándékosan)
Backtest-motor, stratégia, kapu-számítás, papírkereskedés és éles réteg: ezek későbbi lépések. Hálózati kód, bróker- vagy tőzsdei kapcsolat, kulcs és fizetős szolgáltatás nincs, és jóváhagyás nélkül nem is lesz.

## Futtatás
```
python -m pytest trading_model/tests -o addopts="" -q -p no:cacheprovider
```
Ez a mappa a repó alapértelmezett tesztparancsának (`pytest.ini` `testpaths`) **még nincs a gyűjtési útvonalai között**; felvétele egy soros konfigurációs változtatás, amely külön jóváhagyást kér.

## Adat és kimenet
A szintetikus és a mentett adat jelölt. Generált kimenet és nyers adat csak a `results/` alá kerülhet (a git nem követi), commitolni tilos.
