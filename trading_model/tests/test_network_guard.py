"""A közös hálózati zár működésének igazolása a kereskedelmi modell tesztjeiben.

A zár a `tests/conftest.py` autouse fixture-e (`block_external_network`), amelyet a mappa `conftest.py`-ja importál. Ezek a próbák NEM telepítenek zárat: azt igazolják, hogy a közösen aktív zár él.
Python-szintű védelem (a `socket.socket.connect` hívás szűrése), nem operációs rendszer szintű hálózati elszigetelés: a névfeloldást, az UDP-t és más folyamatokat nem fogja meg.
A próbák egyike sem hoz létre valódi kapcsolatot: a `connect` hívás egy nem-socket objektumon fut, így ha a zár hiányzik vagy hibás, a hívás típushibával áll meg, még mielőtt bármi kimenne.
"""
import socket
from pathlib import Path

import pytest

OWN_TESTS = "trading_model/tests/"


def test_the_shared_guard_is_attached_to_every_collected_test_of_this_folder(request):
    items = [i for i in request.session.items if i.nodeid.startswith(OWN_TESTS)]
    assert items, "nincs begyűjtött teszt ebben a mappában"
    unguarded = [i.nodeid for i in items if "e2e" not in i.keywords and "block_external_network" not in i.fixturenames]
    assert not unguarded, unguarded


def test_the_active_connect_is_the_shared_guard_and_refuses_non_local_hosts(request):
    assert "block_external_network" in request.fixturenames
    assert socket.socket.connect.__name__ == "guarded_connect", "a közös zár nem aktív ebben a tesztben"
    not_a_socket = object()
    for host in ("203.0.113.7", "example.com", "8.8.8.8"):
        with pytest.raises(RuntimeError, match="TILTOTT"):
            socket.socket.connect(not_a_socket, (host, 9))


def test_the_guard_lets_loopback_through_to_the_real_connect_without_connecting(request):
    assert socket.socket.connect.__name__ == "guarded_connect"
    not_a_socket = object()
    for host in ("127.0.0.1", "localhost", "::1"):
        with pytest.raises(TypeError):                    # a zár átengedte; a valódi connect elutasítja a nem-socketet, kapcsolat nem jön létre
            socket.socket.connect(not_a_socket, (host, 9))


def test_the_conftest_reuses_the_shared_guard_instead_of_defining_its_own():
    src = (Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")
    assert "from tests.conftest import block_external_network" in src
    assert "def block_external_network" not in src
