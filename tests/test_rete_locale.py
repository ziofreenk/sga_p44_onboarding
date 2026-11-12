"""Test di rete locale (#8, collaudo Windows): il mock deve essere raggiungibile anche con un proxy
di sistema configurato, e l'avvio del server non deve dipendere dal DNS (niente getfqdn).

Esecuzione: python -m unittest tests.test_rete_locale -v
"""

import json
import os
import threading
import time
import unittest
import urllib.request
from unittest import mock

from src.onboarding.p44_client import ClientP44, apri, e_loopback
from src.p44_mock.server import MockP44Server
from src.p44_mock.store import Store

CID, SEC = "test-client", "test-secret"
# Proxy inesistente: se una chiamata al mock lo usasse, fallirebbe con errore di connessione
PROXY_MORTO = "http://127.0.0.1:9"


class TestLoopback(unittest.TestCase):
    def test_riconoscimento(self):
        for url in ("http://127.0.0.1:8044/x", "http://localhost:8044", "http://[::1]:8044/", "http://127.5.6.7/"):
            self.assertTrue(e_loopback(url), url)
        for url in ("https://na12.api.project44.com/api/v4/oauth2/token", "http://10.0.0.1/", "http://128.0.0.1/"):
            self.assertFalse(e_loopback(url), url)


class TestMockConProxyDiSistema(unittest.TestCase):
    def setUp(self):
        t0 = time.monotonic()
        self.store = Store(":memory:")
        self.srv = MockP44Server(("127.0.0.1", 0), self.store, CID, SEC, None, log=False)
        self.avvio = time.monotonic() - t0
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        # Ambiente con proxy configurato e senza eccezioni NO_PROXY (come un PC aziendale)
        env = {k: v for k, v in os.environ.items() if k.lower() not in ("no_proxy", "http_proxy", "https_proxy")}
        env.update({"HTTP_PROXY": PROXY_MORTO, "HTTPS_PROXY": PROXY_MORTO})
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.srv.shutdown()
        self.srv.server_close()
        self.store.chiudi()

    def test_avvio_server_rapido(self):
        self.assertEqual(self.srv.server_name, "127.0.0.1")
        self.assertLess(self.avvio, 1.0)

    def test_apri_salta_il_proxy(self):
        with apri(self.base + "/_sim/clock", 5) as r:
            self.assertIn("now", json.loads(r.read()))

    def test_urlopen_standard_userebbe_il_proxy(self):
        # Controprova: senza apri() la chiamata passa dal proxy (morto) e fallisce
        with self.assertRaises(OSError):
            urllib.request.urlopen(self.base + "/_sim/clock", timeout=3)

    def test_client_p44_via_mock(self):
        # Token OAuth2 + GET inviti attraverso il client reale, con proxy di sistema attivo
        c = ClientP44(self.base, CID, SEC, tentativi_rete=1)
        self.assertEqual(c.inviti_per_identificativo("IT00000000000"), [])

if __name__ == "__main__":
    unittest.main()
