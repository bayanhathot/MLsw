# WARNING: STRICTLY FORBIDDEN TO MODIFY THIS FILE
# Changing this file will result in an automatic PR failure.
# These calls simulate a remote enterprise service.

import sqlite3
import time
from urllib import error, request


class HeavyDB:
    """Simulated slow enterprise database (sqlite + remote service latency)."""

    _PING_URL = "https://httpbin.org/delay/0.6"

    def _simulate_remote_latency(self) -> None:
        """Simulate network/service delay with a real HTTP call."""
        try:
            req = request.Request(self._PING_URL, method="GET")
            with request.urlopen(req, timeout=1.0):
                pass
        except (error.URLError, TimeoutError, OSError):
            # Keep latency behavior even without outbound internet.
            time.sleep(0.6)

    def __init__(self):
        self._simulate_remote_latency()
        print("Establishing secure tunnel to HeavyDB... Please wait...")
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
        )
        self._conn.commit()

    def add_product(self, name: str) -> None:
        self._simulate_remote_latency()
        self._conn.execute("INSERT INTO products (name) VALUES (?)", (name,))
        self._conn.commit()

    def remove_product(self, name: str) -> None:
        self._simulate_remote_latency()
        self._conn.execute("DELETE FROM products WHERE name = ?", (name,))
        self._conn.commit()

    def get_products(self) -> list[str]:
        self._simulate_remote_latency()
        cur = self._conn.execute("SELECT name FROM products ORDER BY id")
        return [row[0] for row in cur.fetchall()]
