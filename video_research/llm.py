"""Szolgáltatófüggetlen LLM-felület. Az MI csak értelmez, javasol és kinyer: eszközt, titkot, hálózatot nem kap.

Ebben a kiadásban NINCS valódi LLM-adapter: a repository szabályai (CLAUDE.md, config/guard_policy.json) harmadik szolgáltatót
nem engednek, és az `anthropic` importot az Őr tiltja. Valódi adapter a felhasználó jóváhagyott szabályváltása után adható be
az `LLMClient` felületen át (lásd README). Tesztben és fejlesztésben hamis implementáció használható.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    data: dict
    tokens: int          # a ténylegesen felhasznált (bemenet+kimenet) tokenek; ismeretlen esetben a hívó becslése, jelölve a naplóban


class LLMClient(Protocol):
    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult: ...


class NullLLM:
    """Nincs beállított modell: minden hívás érthető hibával áll meg, kitalált kimenet nincs."""
    def complete_json(self, *, system: str, user: str, schema_name: str, max_tokens: int) -> LLMResult:
        raise LLMUnavailable("Nincs beállított LLM-szolgáltató. A kinyerés és a jelentés nem készíthető el modell nélkül.")


def estimate_tokens(text: str) -> int:
    """Durva előzetes becslés (kb. 3 karakter/token magyar szövegnél) a keret ELŐZETES ellenőrzéséhez; a tényleges érték az LLMResult.tokens."""
    return max(1, len(text) // 3)
