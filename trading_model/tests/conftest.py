# A közös hálózati zár (tests/conftest.py) itt is érvényes: a kereskedelmi modell tesztjei sem hívhatnak külső hálózatot.
# Python-szintű védelem (a socket.socket.connect hívás szűrése), nem operációs rendszer szintű hálózati elszigetelés.
from tests.conftest import block_external_network  # noqa: F401
