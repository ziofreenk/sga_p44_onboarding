"""Avvio del mock P44.

Uso (dalla radice del repo):
    python -m src.p44_mock [--port 8044] [--db data/p44_mock.db] [--mail-dir output/mail]
                           [--scenari scenari.json] [--quiet]

Credenziali client: variabili d'ambiente P44_MOCK_CLIENT_ID / P44_MOCK_CLIENT_SECRET
(se assenti si usano valori demo, segnalati a console).
"""

import argparse
import json
import os
import sys

from .server import MockP44Server
from .store import Store

ID_DEMO, SECRET_DEMO = "fercam-poc", "fercam-poc-secret"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="p44_mock", description="Mock locale API project44")
    ap.add_argument("--host", default="127.0.0.1", help="interfaccia (default solo locale)")
    ap.add_argument("--port", type=int, default=8044)
    ap.add_argument("--db", default=os.path.join("data", "p44_mock.db"),
                    help="file sqlite (':memory:' per non persistere)")
    ap.add_argument("--mail-dir", default=os.path.join("output", "mail"),
                    help="cartella dei .eml di invito ('' per disattivare)")
    ap.add_argument("--scenari", help="JSON {\"<P.IVA>\": \"<SCENARIO>\"} per forzare gli scenari")
    ap.add_argument("--quiet", action="store_true", help="non loggare le richieste")
    a = ap.parse_args(argv)

    scenari = {}
    if a.scenari:
        with open(a.scenari, encoding="utf-8") as f:
            scenari = json.load(f)
    if a.db != ":memory:" and os.path.dirname(a.db):
        os.makedirs(os.path.dirname(a.db), exist_ok=True)

    cid = os.environ.get("P44_MOCK_CLIENT_ID", ID_DEMO)
    sec = os.environ.get("P44_MOCK_CLIENT_SECRET", SECRET_DEMO)
    if (cid, sec) == (ID_DEMO, SECRET_DEMO):
        print("ATTENZIONE: credenziali demo in uso (impostare P44_MOCK_CLIENT_ID/SECRET)", file=sys.stderr)

    store = Store(a.db, scenari)
    srv = MockP44Server((a.host, a.port), store, cid, sec, a.mail_dir or None, log=not a.quiet)
    print(f"Mock P44 in ascolto su http://{a.host}:{a.port}  (ora virtuale: {store.adesso():%Y-%m-%d %H:%M} UTC)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArresto mock P44")
    finally:
        srv.server_close()
        store.chiudi()


if __name__ == "__main__":
    main()
