# Telepítési környezet és függőségek (ellenőrizve 2026-11-20)

## Két környezet volt: ne keverd
1. **Régi venv** (`…/scratchpad/venv`, az előző körökben): `include-system-site-packages = true`, mert a `httpx2`-t nem tudtam beletelepíteni. Tehát **NEM teljesen izolált**: 118 csomagot örökölt a rendszer-Pythonból (pl. `fastapi 0.165.0`, `SQLAlchemy 2.1.9`, `apify_client 3.5.1`, `pytest 9.1.1`, `httpx2 2.13.1`, `starlette 1.7.0`; a venv saját `starlette 1.10.0`-ját viszont előnyben részesítette). Az első körben ráadásul a `fastapi`, `sqlalchemy`, `apify-client`, `colorama` csomagokat **rendszerszinten** telepítettem, ami ellentmondott a kérésednek. Az előző beszámolók eredményei ebben a vegyes környezetben születtek.
2. **Új, valóban izolált venv** (`…/scratchpad/venv_iso`, `include-system-site-packages = false`): `pip install -r video_research/requirements.txt pytest httpx2` és a tároló gyökér `requirements.txt` + `pyyaml` (ezt a `tests.yml` is telepíti). **Az ebben a körben jelentett tesztek ebben futottak.**

## A „httpx2” megnevezés
- Valódi PyPI-csomag: `httpx2` (szerzője a metaadat szerint Tom Christie; „The next generation HTTP client”), a modulneve is `httpx2`. Nem elírás és nem az `httpx`.
- A Starlette `TestClient`-je (`starlette 1.10.0` forrása: `import httpx2 as httpx`; hibaüzenete: „requires the httpx2 package”) ezt kéri; a `httpx` régi neve már csak elavult tartalék. A rendszerben az `mcp 2.3.0` függősége.
- Verziók: rendszer `httpx2 2.13.1` (régi venv), izolált venv `httpx2 2.16.2`. `httpx` (régi név) egyik környezetben sincs telepítve.
- A korábbi beszámolóban „httpx2”-t „előre telepítettnek” neveztem; pontosan: a rendszer-Pythonban volt, az első izolált telepítési kísérletemet a környezet engedélyezési szűrője megtagadta, a másodikat (ugyanazt a csomagot, ellenőrzött metaadattal, izolált venvbe) elfogadta.
- A csomag a tesztek (`TestClient`) függősége, nem az alkalmazásé: `video_research/requirements-dev.txt`.

## Futtatásban használt verziók (izolált venv, `pip freeze`)
`fastapi==0.165.0`, `starlette==1.10.0`, `pydantic==2.14.4` (`pydantic_core==2.50.5`), `SQLAlchemy==2.1.9`, `youtube-transcript-api==1.2.5`, `requests==2.34.2`, `uvicorn==0.54.0`,
`apify_client==3.5.1`, `psycopg==3.3.9` (+binary), `httpx2==2.16.2`, `pytest==9.2.0`, `PyYAML==6.0.3`. Python 3.13. A requirements-fájlok csak alsó korlátot kötnek ki (`fastapi>=0.115` stb.), nincs lockfile: az ismételhető telepítéshez a fenti verziók használhatók.
A `psycopg` és az `apify-client` telepítve van, de PostgreSQL-lel és valódi Apify-jal nem próbáltam.
