"""Generatore di vettori fittizi con il tracciato della query SGA (#5).

Produce:
  - CSV vettori (tracciato in tracciato.py), da usare al posto dell'estrazione SGA;
  - scenari.json {VAT_P44: SCENARIO} da passare al mock P44 con --scenari.

Uso (dalla radice del repo):
    python -m src.onboarding.genera_dati_fittizi [--n 30] [--ko 2] [--seed 44]
        [--csv data/vettori_fittizi.csv] [--scenari data/scenari.json] [--data-rif AAAA-MM-GG]
    python -m src.p44_mock --port 8044 --scenari data/scenari.json

--n   vettori invitabili (ESITO_CONTROLLO = OK), minimo 6 per coprire tutti gli scenari del mock;
--ko  vettori scartati dal controllo qualità (KO_MANCA_EMAIL): stanno nel CSV ma non in scenari.json.
Stesso seed + stessa --data-rif => stessi file (demo riproducibili).

Tutti i dati sono inventati: P.IVA con cifra di controllo valida ma casuale,
e-mail su dominio riservato .test (RFC 2606), telefoni +39 000..., nessun dato SGA reale.
"""

import argparse
import csv
import json
import os
import random
from datetime import date, datetime, timedelta

from ..p44_mock.scenari import SCENARI
from .tracciato import (COLONNE, ENCODING, NOMINATIVO_DEFAULT, SEPARATORE,
                        locale_per_nazione)

# Ordine fisso degli scenari: la distribuzione è a rotazione (30 vettori -> 5 per scenario)
ORDINE_SCENARI = [
    "ACCETTA_SUBITO", "ACCETTA_DOPO_SOLLECITO_1", "ACCETTA_DOPO_SOLLECITO_2",
    "RIFIUTA", "NESSUNA_RISPOSTA", "SCADE_POI_ACCETTA",
]
assert set(ORDINE_SCENARI) == set(SCENARI), "allineare ORDINE_SCENARI agli scenari del mock"

REPARTI_FMI = ["BF1", "BO2", "BZ6", "CB1", "CE2", "CF2", "F31", "FI1", "G11", "G22",
               "G92", "GE1", "PC1", "SL3", "TN1", "TN2", "TO2", "VN3"]

_PREFISSI = ["Autotrasporti", "Trasporti", "Logistica", "Spedizioni", "Autolinee", "Transport"]
_COGNOMI_SOC = ["Alpina", "Adriatica", "del Brennero", "Padana", "Tirrenica", "Dolomiti", "Ligure",
                "Emiliana", "Lagunare", "Appennino", "Garda", "Valsugana", "Etna", "Po", "Ticino"]
_FORME = ["S.r.l.", "S.p.A.", "S.n.c.", "S.a.s."]
_NOMI = ["Mario", "Luca", "Giulia", "Anna", "Marco", "Paolo", "Sara", "Elena", "Davide", "Chiara"]
_COGNOMI = ["Rossi", "Bianchi", "Verdi", "Gallo", "Fontana", "Moretti", "Conti", "Greco", "Ferri", "Costa"]
# Pochi vettori esteri per coprire le lingue diverse da it-IT
_ESTERI = {"DE": ("Spedition", "GmbH"), "AT": ("Transporte", "GmbH"), "PL": ("Transport", "Sp. z o.o.")}
_PREFISSO_TEL = {"IT": "+39", "DE": "+49", "AT": "+43", "PL": "+48"}


def piva_italiana(rnd: random.Random) -> str:
    """P.IVA italiana fittizia: 7 cifre matricola + 3 ufficio + cifra di controllo (algoritmo ufficiale)."""
    base = [rnd.randint(0, 9) for _ in range(7)] + [int(c) for c in f"{rnd.randint(1, 100):03d}"]
    somma = 0
    for i, c in enumerate(base):
        if i % 2 == 0:
            somma += c
        else:
            d = c * 2
            somma += d - 9 if d > 9 else d
    return "".join(map(str, base)) + str((10 - somma % 10) % 10)


def piva_valida(piva: str) -> bool:
    """Verifica la cifra di controllo di una P.IVA italiana di 11 cifre."""
    if len(piva) != 11 or not piva.isdigit():
        return False
    somma = 0
    for i, c in enumerate(map(int, piva[:10])):
        d = c if i % 2 == 0 else (c * 2 - 9 if c * 2 > 9 else c * 2)
        somma += d
    return (10 - somma % 10) % 10 == int(piva[10])


def _slug(testo: str) -> str:
    return "".join(ch for ch in testo.lower() if ch.isalnum())


def genera_vettori(n: int = 30, seed: int = 44, data_rif: date = None, ko: int = 0):
    """Restituisce (righe CSV come dict, mappa scenari {VAT_P44: scenario}).

    n righe OK (invitabili, scenari a rotazione) + ko righe KO_MANCA_EMAIL (escluse dalla mappa).
    Righe ordinate come la query SGA: N_VIAGGI decrescente, poi RAGIONE_SOCIALE.
    """
    if n < len(ORDINE_SCENARI):
        raise ValueError(f"servono almeno {len(ORDINE_SCENARI)} vettori OK per coprire tutti gli scenari")
    if ko < 0:
        raise ValueError("ko deve essere >= 0")
    rnd = random.Random(seed)
    data_rif = data_rif or date.today()
    righe, scenari, usate = [], {}, set()
    for k in range(n + ko):
        scarto = k >= n   # righe finali: vettori senza e-mail (KO)
        scenario = ORDINE_SCENARI[k % len(ORDINE_SCENARI)]
        # 1 vettore su 10 estero (lingua diversa), gli altri italiani
        nazione = list(_ESTERI)[k // 10 % len(_ESTERI)] if k % 10 == 9 else "IT"
        while True:
            if nazione == "IT":
                piva = piva_italiana(rnd)
            elif nazione == "AT":   # UID austriaco: U + 8 cifre
                piva = "U" + "".join(str(rnd.randint(0, 9)) for _ in range(8))
            else:                   # DE 9 cifre, PL 10 cifre
                piva = "".join(str(rnd.randint(0, 9)) for _ in range(10 if nazione == "PL" else 9))
            if piva not in usate:
                usate.add(piva)
                break
        cognome_soc = rnd.choice(_COGNOMI_SOC)
        if nazione == "IT":
            nome_soc = f"{rnd.choice(_PREFISSI)} {cognome_soc} {k + 1:02d} {rnd.choice(_FORME)}"
        else:
            pref, forma = _ESTERI[nazione]
            nome_soc = f"{pref} {cognome_soc} {k + 1:02d} {forma}"
        dominio = f"{_slug(cognome_soc)}{k + 1:02d}.test"
        # ~ metà con nominativo di default (come in SGA: 403 su 773)
        default = k % 2 == 1
        if default:
            nome, cognome, nominativo = NOMINATIVO_DEFAULT, "", NOMINATIVO_DEFAULT
            email, fonte = f"traffico@{dominio}", "TESTATA_VETTORE"
        else:
            nome, cognome = rnd.choice(_NOMI), rnd.choice(_COGNOMI)
            nominativo = f"{nome} {cognome}"
            email = f"{_slug(nome)}.{_slug(cognome)}@{dominio}"
            fonte = "INTERLOCUTORE" if k % 4 == 0 or k % 4 == 2 else "TESTATA_VETTORE"
        if scarto:
            # come la query: nessuna e-mail valida => POC_EMAIL e POC_FONTE nulli, nominativo di default
            nome, cognome, nominativo, default = NOMINATIVO_DEFAULT, "", NOMINATIVO_DEFAULT, True
            email, fonte = "", ""
        vat = ("EL" if nazione == "GR" else nazione) + piva
        ultimo = datetime.combine(data_rif - timedelta(days=rnd.randint(1, 90)), datetime.min.time()) \
            + timedelta(hours=rnd.randint(6, 19))
        righe.append({
            "SOCIETA": 1,
            "CODICE_VETTORE": 900001 + k,  # range fittizio, fuori dai codici SGA tipici
            "RAGIONE_SOCIALE": nome_soc,
            "NAZIONE": nazione,
            "PARTITA_IVA": piva,
            "VAT_P44": vat,
            "CODICE_FISCALE": piva if nazione == "IT" else "",
            "POC_EMAIL": email,
            "POC_NOMINATIVO": nominativo,
            "POC_NOMINATIVO_DEFAULT": "S" if default else "N",
            "POC_NOME": nome,
            "POC_COGNOME": cognome,
            "POC_TELEFONO": f"{_PREFISSO_TEL[nazione]}000{rnd.randint(1000000, 9999999)}",  # 000: numero fittizio
            "POC_LOCALE": locale_per_nazione(nazione),
            "POC_FONTE": fonte,
            "N_VIAGGI": rnd.randint(1, 120),
            "ULTIMO_VIAGGIO": ultimo.strftime("%Y-%m-%d %H:%M:%S"),
            "N_REPARTI_FMI": rnd.randint(1, 3),
            "ESITO_CONTROLLO": "KO_MANCA_EMAIL" if scarto else "OK",
        })
        if not scarto:
            scenari[vat] = scenario
    righe.sort(key=lambda r: (-r["N_VIAGGI"], r["RAGIONE_SOCIALE"]))
    return righe, scenari


def scrivi_csv(percorso: str, righe):
    if os.path.dirname(percorso):
        os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "w", encoding=ENCODING, newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE, delimiter=SEPARATORE)
        w.writeheader()
        w.writerows(righe)


def leggi_csv(percorso: str):
    with open(percorso, encoding=ENCODING, newline="") as f:
        return list(csv.DictReader(f, delimiter=SEPARATORE))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Genera vettori fittizi + mappa scenari del mock P44")
    ap.add_argument("--n", type=int, default=30, help="vettori invitabili (min 6)")
    ap.add_argument("--ko", type=int, default=2, help="vettori KO_MANCA_EMAIL (default 2)")
    ap.add_argument("--seed", type=int, default=44)
    ap.add_argument("--csv", default=os.path.join("data", "vettori_fittizi.csv"))
    ap.add_argument("--scenari", default=os.path.join("data", "scenari.json"))
    ap.add_argument("--data-rif", help="data di riferimento AAAA-MM-GG (default oggi)")
    a = ap.parse_args(argv)
    if a.n < len(ORDINE_SCENARI):
        ap.error(f"--n deve essere >= {len(ORDINE_SCENARI)} (un vettore per scenario)")
    if a.ko < 0:
        ap.error("--ko deve essere >= 0")
    data_rif = date.fromisoformat(a.data_rif) if a.data_rif else None
    righe, scenari = genera_vettori(a.n, a.seed, data_rif, a.ko)
    scrivi_csv(a.csv, righe)
    if os.path.dirname(a.scenari):
        os.makedirs(os.path.dirname(a.scenari), exist_ok=True)
    with open(a.scenari, "w", encoding="utf-8") as f:
        json.dump(scenari, f, indent=2, ensure_ascii=False)
    conteggio = {s: list(scenari.values()).count(s) for s in ORDINE_SCENARI}
    print(f"{len(righe)} vettori ({a.n} OK, {a.ko} KO) -> {a.csv}\nscenari -> {a.scenari}: {conteggio}")


if __name__ == "__main__":
    main()
