"""Demo end-to-end dell'onboarding sub-vettori su P44 con il mock (attività #7).

Simula N giorni virtuali (default 95, cioè 3 scadenze da 30 gg: compaiono anche i vettori a
TENTATIVI_ESAURITI) e produce il report KPI finale. Tutto avviene in-process e in locale:
  1. genera i dati fittizi (#5) nella cartella del run;
  2. avvia il mock P44 su una porta libera scelta dal sistema (solo 127.0.0.1) con gli scenari forzati;
  3. esegue un ciclo dell'orchestratore al giorno (ore 07:00 UTC virtuali) avanzando /_sim/clock;
  4. genera il report (report_kpi.md, kpi.csv, anomalie.csv).

Ogni run scrive in una cartella NUOVA (default output/demo/run_AAAAMMGG_hhmmss): nessun file
esistente viene sovrascritto o cancellato.

Uso (dalla radice del repo):
    python -m src.onboarding.demo [--giorni 95] [--vettori 30] [--ko 2] [--seed 44]
                                  [--data-rif 2026-11-12] [--cartella output/demo/prova] [--quiet]
Risorse: < 50 MB RAM; su disco ~1 MB (sqlite, CSV, .eml) nella cartella del run.
"""

import argparse
import json
import os
import secrets
import sys
import threading
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import genera_dati_fittizi as gen
from .orchestratore import ErroreSistemico, Orchestratore
from .p44_client import ClientP44, OrologioMock, apri
from .registro import Registro
from .report_kpi import _fmt_valore, genera_report
from ..p44_mock.server import MockP44Server
from ..p44_mock.store import Store

GIORNI_DEFAULT = 95
ORA_CICLO = "07:00:00"   # ora virtuale (UTC) del job giornaliero


def _sim(base: str, path: str, corpo: dict) -> dict:
    req = urllib.request.Request(base + path, json.dumps(corpo).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    with apri(req, 10) as r:
        return json.loads(r.read())


def prepara_cartella(cartella: str = None, radice: str = os.path.join("output", "demo")) -> str:
    """Cartella del run: se indicata deve essere nuova o vuota; altrimenti run_<timestamp>."""
    if not cartella:
        cartella = os.path.join(radice, datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    if os.path.isdir(cartella) and os.listdir(cartella):
        raise ValueError(f"la cartella {cartella} non è vuota: indicarne una nuova (nessun file viene sovrascritto)")
    os.makedirs(cartella, exist_ok=True)
    return cartella


def esegui_demo(cartella: str, giorni: int = GIORNI_DEFAULT, n: int = 30, ko: int = 2, seed: int = 44,
                data_rif: date = None, log=print) -> dict:
    """Esegue la demo nella cartella (già preparata). Restituisce l'analisi del report + info del run."""
    if giorni < 1:
        raise ValueError("giorni deve essere >= 1")
    log = log or (lambda *_: None)
    data_rif = data_rif or date.today()
    inizio = f"{data_rif + timedelta(days=1)}T{ORA_CICLO}Z"

    # 1. dati fittizi (stesso tracciato della query SGA #4)
    righe, scenari = gen.genera_vettori(n, seed=seed, data_rif=data_rif, ko=ko)
    percorso_csv = os.path.join(cartella, "vettori_fittizi.csv")
    gen.scrivi_csv(percorso_csv, righe)
    with open(os.path.join(cartella, "scenari.json"), "w", encoding="utf-8") as f:
        json.dump(scenari, f, indent=2, ensure_ascii=False)

    # 2. mock P44 in-process, credenziali casuali valide solo per questo run
    cid, sec = "demo-" + secrets.token_hex(4), secrets.token_urlsafe(16)
    store = Store(os.path.join(cartella, "p44_mock.db"), scenari)
    srv = MockP44Server(("127.0.0.1", 0), store, cid, sec, os.path.join(cartella, "mail"), log=False)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    reg = Registro(os.path.join(cartella, "orchestratore.db"))
    interrotto = None
    try:
        _sim(base, "/_sim/reset", {"now": inizio})
        orch = Orchestratore(ClientP44(base, cid, sec), reg, OrologioMock(base), cartella, log=None)
        log(f"Demo P44: {n} vettori OK + {ko} KO, {giorni} giorni virtuali da {inizio[:10]}, mock {base}")
        # 3. un ciclo al giorno: giorno 0 (primi inviti) ... giorno N
        for g in range(giorni + 1):
            if g:
                _sim(base, "/_sim/clock", {"advanceDays": 1})
            try:
                c = orch.esegui_ciclo(percorso_csv)
            except ErroreSistemico as e:
                interrotto = f"giorno {g}: {e}"
                log(f"CICLO INTERROTTO al giorno {g}: {e}")
                break
            attivita = {k: v for k, v in c.items() if k not in ("vettori", "scartati") and v}
            if attivita:
                log(f"  giorno {g:>3}: " + ", ".join(f"{k}={v}" for k, v in attivita.items()))
    finally:
        reg.chiudi()
        srv.shutdown()
        srv.server_close()
        store.chiudi()

    # 4. report finale
    analisi = genera_report(cartella, os.path.join(cartella, "report"))
    analisi.update({"cartella": cartella, "giorni": giorni, "interrotto": interrotto, "scenari": scenari})
    return analisi


def main(argv=None):
    ap = argparse.ArgumentParser(prog="demo", description="Demo onboarding P44: N giorni virtuali + report KPI")
    ap.add_argument("--giorni", type=int, default=GIORNI_DEFAULT, help="giorni virtuali (default 95)")
    ap.add_argument("--vettori", type=int, default=30, help="vettori OK (min 6)")
    ap.add_argument("--ko", type=int, default=2, help="righe KO_MANCA_EMAIL")
    ap.add_argument("--seed", type=int, default=44)
    ap.add_argument("--data-rif", help="data di estrazione AAAA-MM-GG (default oggi)")
    ap.add_argument("--cartella", help="cartella del run, nuova o vuota (default output/demo/run_<timestamp>)")
    ap.add_argument("--quiet", action="store_true", help="non stampare l'attività giornaliera")
    a = ap.parse_args(argv)
    try:
        cartella = prepara_cartella(a.cartella)
        r = esegui_demo(cartella, a.giorni, a.vettori, a.ko, a.seed,
                        date.fromisoformat(a.data_rif) if a.data_rif else None,
                        log=(lambda *_: None) if a.quiet else print)
    except (OSError, ValueError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    k = {x["kpi"]: x for x in r["kpi"]}
    f = r["funnel"]
    print(f"\nRisultato dopo {a.giorni} giorni: invitati {r['invitati']}, accettati {f['ACCETTATI']} "
          f"({_fmt_valore(k['Tasso di accettazione'])}), rifiutati {f['RIFIUTATI']}, "
          f"tentativi esauriti {f['TENTATIVI_ESAURITI']}, in corso {f['IN_CORSO']}, anomalie {len(r['anomalie'])}")
    print(f"Report: {r['file']['report_kpi.md']}")
    return 2 if r["interrotto"] else 0


if __name__ == "__main__":
    sys.exit(main())
