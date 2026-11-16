import socket
import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch, request):
    """Minden külső hálózati kapcsolatot blokkol a unit és integration tesztekben."""
    if "e2e" in request.keywords:
        return

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(
                f"TILTOTT HÁLÓZATI KÉRÉS a tesztben ({host})! "
                "A unit és integration tesztekben tilos az élő API-hívás."
            )
        return original_connect(self, address, *args, **kwargs)

    original_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def dummy_env(monkeypatch):
    """Hamis API-kulcsokat állít be, hogy véletlenül se használjon éles titkokat."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-dummy-gemini-key-never-logged")
    monkeypatch.setenv("GROQ_API_KEY", "test-dummy-groq-key-never-logged")
    monkeypatch.setenv("PILOT_DRY_RUN", "1")
