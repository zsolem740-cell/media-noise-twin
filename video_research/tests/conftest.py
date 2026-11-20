"""Közös hálózati zár: a tesztek semmilyen nem helyi kapcsolatot nem nyithatnak (éles Apify/LLM/Gemini/Groq hívás tilos)."""
import socket

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    original = socket.socket.connect

    def guarded(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"TILTOTT HÁLÓZATI KÉRÉS a tesztben ({host})")
        return original(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guarded)
