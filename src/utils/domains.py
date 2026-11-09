"""Források egységes neve: edition.cnn.com és cnn.com ugyanaz a forrás.

Általános szabály: a www/wwwN/m/amp/mobile/edition előtag lekerül (ha marad legalább név + végződés);
egyedi eset: config/sources.json "domain_aliases": {"regi.hu": "uj.hu"}.
"""
import re

_PREFIX = re.compile(r"^(?:www\d*|m|amp|mobile|edition)\.")


def canon_domain(domain: str | None, aliases: dict | None = None) -> str:
    d = (domain or "").lower().strip().rstrip(".")
    for _ in range(3):
        if d.count(".") >= 2 and _PREFIX.match(d):
            d = _PREFIX.sub("", d, count=1)
        else:
            break
    return (aliases or {}).get(d, d)
