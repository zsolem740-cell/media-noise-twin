import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "trading_model"]

ALLOWED_SOCKET_FILES = {"tests/conftest.py", "trading_model/tests/test_network_guard.py"}

RED = "\033[91m"
GREEN = "\033[92m"
RESET = "\033[0m"

FORBIDDEN_TEST_IMPORTS = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "urllib",
    "socket",
    "subprocess",
    "openai",
    "anthropic",
}
DANGEROUS_CALLS = {"eval", "exec"}
SECRET_REGEXES = [
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"sk-[0-9A-Za-z\-_]{20,}"),
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),
    re.compile(r"Bearer\s+[0-9A-Za-z\-_.=]{16,}", re.IGNORECASE),
    re.compile(r"(?i)\b(?:api_key|secret|token|password)\s*=\s*['\"]([^'\"]{8,})['\"]"),
]
PLACEHOLDER_HINTS = ("REDACTED", "DUMMY", "EXAMPLE", "PLACEHOLDER", "YOUR_", "CHANGEME", "XXXX")


def is_placeholder_match(matched_text: str) -> bool:
    upper_val = matched_text.upper()
    return any(hint in upper_val for hint in PLACEHOLDER_HINTS)


def is_forbidden_test_module(module_name: str, allowed_modules: set[str]) -> bool:
    if module_name in allowed_modules:
        return False
    return any(
        module_name == mod or module_name.startswith(f"{mod}.")
        for mod in FORBIDDEN_TEST_IMPORTS
    )


def analyze_python_file(path: Path) -> list[str]:
    errors: list[str] = []
    rel = path.relative_to(ROOT).as_posix()
    is_conftest = rel == "tests/conftest.py"
    is_restricted_test = is_conftest or rel.startswith(("tests/unit/", "tests/integration/", "trading_model/tests/"))
    # A socket importja csak ott engedett, ahol a hálózati zárat magát állítja vagy próbálja ki; a kereskedelmi modell zárpróbája nem hoz létre kapcsolatot.
    allowed_in_file = {"socket"} if rel in ALLOWED_SOCKET_FILES else set()

    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"{rel}: Nem UTF-8 kódolású fájl!"]

    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as exc:
        return [f"{rel}:{exc.lineno}: SZINTAKTIKAI HIBA — {exc.msg}"]

    for idx, line in enumerate(source.splitlines(), start=1):
        for pat in SECRET_REGEXES:
            for match in pat.finditer(line):
                candidate = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                if not is_placeholder_match(candidate):
                    errors.append(f"{rel}:{idx}: BIZTONSÁGI HIBA — Beégetett API-kulcs vagy hitelesítő mintázat!")
                    break

    for node in ast.walk(tree):
        if is_restricted_test:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if is_forbidden_test_module(alias.name, allowed_in_file):
                        errors.append(f"{rel}:{node.lineno}: TILTOTT IMPORT tesztben — '{alias.name}'")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if is_forbidden_test_module(node.module, allowed_in_file):
                    errors.append(f"{rel}:{node.lineno}: TILTOTT IMPORT tesztben — '{node.module}'")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_CALLS:
                errors.append(f"{rel}:{node.lineno}: VESZÉLYES HÍVÁS — '{node.func.id}()'")

        if isinstance(node, ast.ExceptHandler) and node.type is None:
            errors.append(f"{rel}:{node.lineno}: KÓDMINŐSÉGI HIBA — Üres 'except:' blokk (adj meg konkrét kivételt)")

    return errors


def main() -> None:
    all_errors: list[str] = []
    checked_count = 0

    for base in SCAN_DIRS:
        if not base.exists():
            continue
        for py_file in sorted(base.rglob("*.py")):
            checked_count += 1
            all_errors.extend(analyze_python_file(py_file))

    print(f"=== CODE GUARD ANALIZÁTOR ({checked_count} Python fájl ellenőrizve) ===")
    if all_errors:
        print(f"{RED}HIBA: {len(all_errors)} probléma található! A kód NEM mehet élesbe:{RESET}")
        for err in all_errors:
            print(f"  {RED}[X] {err}{RESET}")
        sys.exit(1)

    print(f"{GREEN}[OK] Minden ellenőrzött kód szintaktikailag és szabályzatilag tiszta.{RESET}")
    sys.exit(0)


if __name__ == "__main__":
    main()
