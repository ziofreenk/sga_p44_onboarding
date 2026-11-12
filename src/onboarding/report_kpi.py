"""Report KPI e anomalie dell'onboarding sub-vettori su P44 (attività #7).

Legge SOLO gli export dell'orchestratore (output/eventi.csv, output/stato_vettori.csv), quindi
funziona sia sulla demo col mock sia su un run reale, senza accedere al registro sqlite.

Produce in --output (default <input>/report), UTF-8:
  - report_kpi.md   report leggibile (sintesi, funnel, KPI per area, anomalie)
  - kpi.csv         area;kpi;valore;unita          (';', UTF-8 BOM, decimali con virgola)
  - anomalie.csv    gravita;tipo;vat;codice_vettore;ragione_sociale;dettaglio;azione_suggerita

Uso (dalla radice del repo):
    python -m src.onboarding.report_kpi --input output [--output output/report] [--data-rif 2026-12-31]

Tempi di risposta: misurati con il lastModifiedDateTime di P44 riportato negli eventi STATO_*
(fallback: data del ciclo che ha rilevato l'esito), in due modi:
  (a) dall'invito del tentativo che ha avuto esito; (b) dal primo invito (durata onboarding).
"""

import argparse
import csv
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .registro import COLONNE_EVENTI, COLONNE_STATO
from .tempo import giorni_calendario, parse_iso

GIORNI_SOLLECITO_2 = 5   # allineato all'orchestratore (decisione 7/16)
GRAVITA = ("ALTA", "MEDIA", "BASSA")
STATI_ANNULLATI = {"CANCELLED", "CANCELED"}

_RE_CREATO = re.compile(r"creato=(\S+)")
_RE_ESITO_IL = re.compile(r" il (\S+)\s*$")

# Etichette del funnel (ordine di presentazione)
FUNNEL = [
    ("ACCETTATI", "Accettati"),
    ("RIFIUTATI", "Rifiutati (DECLINED)"),
    ("IN_CORSO", "In corso (IN_PROGRESS)"),
    ("SCADUTI_IN_ATTESA", "Scaduti in attesa di re-invito"),
    ("TENTATIVI_ESAURITI", "Tentativi esauriti"),
    ("ANNULLATI", "Annullati (CANCELLED)"),
    ("ALTRO", "Altro / stato non noto"),
]

AZIONI = {
    "TENTATIVI_ESAURITI": "Contatto manuale (telefono) e verifica del referente/e-mail in SGA",
    "RIFIUTATO": "Contatto manuale dell'Ufficio Vettori per capire il motivo del rifiuto",
    "ANNULLATO": "Verificare chi ha annullato l'invito su P44 e se va ripetuto",
    "SCARTO_CSV": "Correggere l'anagrafica in SGA (e-mail, P.IVA, ragione sociale)",
    "ERRORE_API": "Verificare il payload inviato e la risposta P44; il vettore viene riprovato al ciclo successivo",
    "CICLO_INTERROTTO": "Verificare rete e credenziali P44; rilanciare il ciclo",
    "SOLLECITO_1_SALTATO": "Verificare la pianificazione giornaliera del job (ciclo non eseguito)",
    "SOLLECITO_2_MANCANTE": "Verificare l'invio dei solleciti e la cartella output/solleciti",
    "NON_CONTROLLATO": "Verificare se il vettore è uscito dall'estrazione SGA o se l'ultimo ciclo è fallito",
}
GRAVITA_TIPO = {
    "TENTATIVI_ESAURITI": "ALTA", "ERRORE_API": "ALTA", "CICLO_INTERROTTO": "ALTA",
    "RIFIUTATO": "MEDIA", "SCARTO_CSV": "MEDIA", "SOLLECITO_2_MANCANTE": "MEDIA", "NON_CONTROLLATO": "MEDIA",
    "ANNULLATO": "BASSA", "SOLLECITO_1_SALTATO": "BASSA",
}


# ---------------------------------------------------------------------- input
def leggi_export(percorso: str, colonne: list) -> list:
    """Legge un export dell'orchestratore (';', UTF-8 con o senza BOM) verificando le colonne."""
    with open(percorso, encoding="utf-8-sig", newline="") as f:
        lettore = csv.DictReader(f, delimiter=";")
        mancanti = [c for c in colonne if c not in (lettore.fieldnames or [])]
        if mancanti:
            raise ValueError(f"{os.path.basename(percorso)}: colonne mancanti {', '.join(mancanti)}")
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in lettore]


def _ts(s):
    """Stringa ISO → datetime UTC, None se vuota o non valida."""
    try:
        return parse_iso(s) if s else None
    except ValueError:
        return None


def _int(s, default=0):
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------- ricostruzione per vettore
def _storia_vettori(eventi: list) -> dict:
    """{vat: {"tentativi": {n: {...}}, "esaurito": bool}} ricostruito dagli eventi."""
    storia = defaultdict(lambda: {"tentativi": defaultdict(lambda: {
        "creato": None, "s1": False, "s2": False, "esito": None, "esito_ts": None}), "esaurito": False})
    for e in eventi:
        vat, tipo = e["vat"], e["tipo"]
        if not vat:
            continue
        n = _int(e["tentativo"], 1) or 1
        t = storia[vat]["tentativi"][n]
        logico = _ts(e["istante_logico"])
        if tipo in ("INVITO_INVIATO", "REINVITO_INVIATO", "INVITO_GIA_PRESENTE"):
            m = _RE_CREATO.search(e["dettaglio"])
            t["creato"] = t["creato"] or (_ts(m.group(1)) if m else None) or logico
            m = re.search(r"stato=(\w+)", e["dettaglio"])
            if tipo == "INVITO_GIA_PRESENTE" and m and m.group(1) != "IN_PROGRESS":
                t["esito"] = t["esito"] or m.group(1)          # esito adottato, istante non noto
        elif tipo == "SOLLECITO_1":
            t["s1"] = True
        elif tipo == "SOLLECITO_2":
            t["s2"] = True
        elif tipo.startswith("STATO_"):
            m = _RE_ESITO_IL.search(e["dettaglio"])
            t["esito"] = tipo[len("STATO_"):]
            t["esito_ts"] = (_ts(m.group(1)) if m else None) or logico
        elif tipo == "TENTATIVI_ESAURITI":
            storia[vat]["esaurito"] = True
    return storia


def _categoria(r: dict) -> str:
    stato = r["stato"].upper()
    if stato == "ACCEPTED":
        return "ACCETTATI"
    if stato == "DECLINED":
        return "RIFIUTATI"
    if stato in STATI_ANNULLATI:
        return "ANNULLATI"
    if r["esaurito"] == "1":
        return "TENTATIVI_ESAURITI"
    if stato == "EXPIRED":
        return "SCADUTI_IN_ATTESA"
    if stato == "IN_PROGRESS":
        return "IN_CORSO"
    return "ALTRO"


def _giorni(da, a):
    return (a - da).total_seconds() / 86400 if da and a else None


def _statistiche(valori):
    v = [x for x in valori if x is not None]
    if not v:
        return None
    return {"n": len(v), "media": statistics.mean(v), "mediana": statistics.median(v),
            "min": min(v), "max": max(v)}


# ---------------------------------------------------------------------- analisi
def analizza(eventi: list, stato: list, data_rif: datetime = None) -> dict:
    """Calcola KPI e anomalie. Restituisce un dict con: rif, periodo, funnel, kpi, anomalie, tempi."""
    istanti = [t for t in (_ts(e["istante_logico"]) for e in eventi) if t]
    rif = data_rif or (max(istanti) if istanti else datetime.now(timezone.utc))
    periodo = (min(istanti), max(istanti)) if istanti else (None, None)
    storia = _storia_vettori(eventi)
    tipi = Counter(e["tipo"] for e in eventi)

    # --- funnel (stato corrente da stato_vettori.csv)
    invitati = [r for r in stato if _int(r["tentativi"]) >= 1]
    funnel = Counter(_categoria(r) for r in invitati)
    n_inv = len(invitati)

    # --- esiti per vettore: tentativo che ha chiuso, solleciti, tempi
    acc_cat = Counter()
    tempi = {"ACCEPTED": {"tentativo": [], "primo": []}, "DECLINED": {"tentativo": [], "primo": []}}
    solleciti_accettati = 0
    for r in invitati:
        stato_v = r["stato"].upper()
        if stato_v not in tempi:
            continue
        tent = storia.get(r["vat"], {"tentativi": {}})["tentativi"]
        n = _int(r["tentativi"], 1)
        t = tent.get(n, {})
        primo = tent.get(1, {}).get("creato") if 1 in tent else None
        esito_ts = t.get("esito_ts")
        tempi[stato_v]["tentativo"].append(_giorni(t.get("creato"), esito_ts))
        tempi[stato_v]["primo"].append(_giorni(primo, esito_ts))
        if stato_v == "ACCEPTED":
            if n > 1:
                acc_cat["re-invito"] += 1
            elif t.get("s2"):
                acc_cat["dopo S2"] += 1
            elif t.get("s1"):
                acc_cat["dopo S1"] += 1
            else:
                acc_cat["senza sollecito"] += 1
            solleciti_accettati += sum(int(x["s1"]) + int(x["s2"]) for x in tent.values())
    st = {k: {m: _statistiche(v[m]) for m in v} for k, v in tempi.items()}

    # --- KPI
    acc = funnel["ACCETTATI"]
    reinvitati = sum(1 for r in invitati if _int(r["tentativi"]) > 1)
    s2_senza_s1 = sum(1 for e in eventi if e["tipo"] == "SOLLECITO_2" and "sollecito 1 non inviato" in e["dettaglio"])
    scarti = [e for e in eventi if e["tipo"] == "SCARTATO"]
    motivi = Counter(_motivo_scarto(e["dettaglio"]) for e in scarti)
    kpi = []

    def add(area, nome, valore, unita=""):
        kpi.append({"area": area, "kpi": nome, "valore": valore, "unita": unita})

    add("Perimetro", "Vettori nel registro (invitati almeno una volta)", n_inv, "vettori")
    add("Perimetro", "Righe CSV scartate", len(scarti), "righe")
    for motivo, c in sorted(motivi.items()):
        add("Perimetro", f"Scarti: {motivo}", c, "righe")
    for chiave, etichetta in FUNNEL:
        add("Funnel", etichetta, funnel[chiave], "vettori")
    add("Accettazione", "Tasso di accettazione", _pct(acc, n_inv), "%")
    add("Accettazione", "Tasso di accettazione al 1° invito", _pct(acc - acc_cat["re-invito"], n_inv), "%")
    add("Accettazione", "Tasso di accettazione su re-invito", _pct(acc_cat["re-invito"], reinvitati), "%")
    add("Accettazione", "Tasso di risposta (accettati + rifiutati)", _pct(acc + funnel["RIFIUTATI"], n_inv), "%")
    add("Accettazione", "Tasso di rifiuto", _pct(funnel["RIFIUTATI"], n_inv), "%")
    for cat in ("senza sollecito", "dopo S1", "dopo S2", "re-invito"):
        add("Efficacia solleciti", f"Accettati {cat}", acc_cat[cat], "vettori")
    for esito, nome in (("ACCEPTED", "accettazione"), ("DECLINED", "rifiuto")):
        for misura, desc in (("tentativo", "dall'invito del tentativo"), ("primo", "dal primo invito")):
            s = st[esito][misura]
            for k in ("media", "mediana", "min", "max"):
                add("Tempi di risposta", f"Tempo di {nome} {desc} - {k}", round(s[k], 1) if s else None, "giorni")
    add("Solleciti", "Solleciti 1 inviati (+2 gg)", tipi["SOLLECITO_1"], "mail")
    add("Solleciti", "Solleciti 2 inviati (+5 gg)", tipi["SOLLECITO_2"], "mail")
    add("Solleciti", "Solleciti 2 senza sollecito 1 (ciclo in ritardo)", s2_senza_s1, "mail")
    add("Solleciti", "Solleciti medi per vettore accettato", round(solleciti_accettati / acc, 2) if acc else None, "mail")
    add("Inviti", "Primi inviti inviati", tipi["INVITO_INVIATO"], "inviti")
    add("Inviti", "Re-inviti inviati (dopo EXPIRED)", tipi["REINVITO_INVIATO"], "inviti")
    add("Inviti", "Inviti scaduti (EXPIRED)", tipi["STATO_EXPIRED"], "inviti")
    add("Inviti", "Inviti già presenti su P44 adottati (409/primo avvio)", tipi["INVITO_GIA_PRESENTE"], "inviti")
    add("Esecuzione", "Cicli avviati", tipi["CICLO_INIZIO"], "cicli")
    add("Esecuzione", "Cicli completati", tipi["CICLO_FINE"], "cicli")
    add("Esecuzione", "Cicli interrotti", tipi["CICLO_INTERROTTO"], "cicli")
    add("Esecuzione", "Errori API (vettore saltato)", tipi["ERRORE_API"], "errori")

    return {"rif": rif, "periodo": periodo, "invitati": n_inv, "funnel": funnel, "kpi": kpi,
            "tempi": st, "accettati_per_categoria": acc_cat,
            "anomalie": trova_anomalie(eventi, stato, rif)}


def _motivo_scarto(dettaglio: str) -> str:
    if "duplicata" in dettaglio:
        return "VAT_P44 duplicata"
    return dettaglio or "motivo non indicato"


def _pct(num, den):
    return round(100 * num / den, 1) if den else None


def trova_anomalie(eventi: list, stato: list, rif: datetime) -> list:
    anomalie = []

    def add(tipo, vat="", codice="", ragione="", dettaglio=""):
        anomalie.append({"gravita": GRAVITA_TIPO[tipo], "tipo": tipo, "vat": vat or "",
                         "codice_vettore": codice or "", "ragione_sociale": ragione or "",
                         "dettaglio": dettaglio, "azione_suggerita": AZIONI[tipo]})

    for e in eventi:
        anag = (e["vat"], e["codice_vettore"], e["ragione_sociale"])
        data = e["istante_logico"][:10]
        if e["tipo"] == "SCARTATO":
            add("SCARTO_CSV", *anag, e["dettaglio"])
        elif e["tipo"] == "ERRORE_API":
            add("ERRORE_API", *anag, f"{data}: {e['dettaglio']}")
        elif e["tipo"] == "CICLO_INTERROTTO":
            add("CICLO_INTERROTTO", dettaglio=f"{data}: {e['dettaglio']}")
        elif e["tipo"] == "SOLLECITO_2" and "sollecito 1 non inviato" in e["dettaglio"]:
            add("SOLLECITO_1_SALTATO", *anag, f"{data}: tentativo {e['tentativo']}")

    for r in stato:
        anag = (r["vat"], r["codice_vettore"], r["ragione_sociale"])
        cat = _categoria(r) if _int(r["tentativi"]) >= 1 else "ALTRO"
        if cat == "TENTATIVI_ESAURITI":
            add("TENTATIVI_ESAURITI", *anag, f"{r['tentativi']} inviti scaduti; e-mail {r['email']}")
        elif cat == "RIFIUTATI":
            add("RIFIUTATO", *anag, f"tentativo {r['tentativi']}; e-mail {r['email']}")
        elif cat == "ANNULLATI":
            add("ANNULLATO", *anag, f"tentativo {r['tentativi']}")
        creato = _ts(r["invito_creato"])
        if cat == "IN_CORSO" and creato and not r["sollecito2"] \
                and giorni_calendario(creato, rif) >= GIORNI_SOLLECITO_2:
            add("SOLLECITO_2_MANCANTE", *anag, f"invito del {r['invito_creato'][:10]}, +{giorni_calendario(creato, rif)} gg")
        ctrl = _ts(r["ultimo_controllo"])
        if ctrl and ctrl.date() < rif.date():
            add("NON_CONTROLLATO", *anag, f"ultimo controllo {r['ultimo_controllo'][:10]}, stato {r['stato']}")

    ordine = {g: i for i, g in enumerate(GRAVITA)}
    anomalie.sort(key=lambda a: (ordine[a["gravita"]], a["tipo"], a["ragione_sociale"]))
    return anomalie


# ---------------------------------------------------------------------- output
def _fmt_num(v):
    if v is None:
        return "n.d."
    if isinstance(v, float):
        return f"{v:.1f}".replace(".", ",")
    return str(v)


def _fmt_valore(k):
    v = k["valore"]
    if v is None:
        return "n.d."
    if k["unita"] == "%":
        return _fmt_num(float(v)) + "%"
    if isinstance(v, float) and k["unita"] == "mail":
        return f"{v:.2f}".replace(".", ",")
    return _fmt_num(v)


def scrivi_csv_kpi(percorso: str, kpi: list):
    with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["area", "kpi", "valore", "unita"])
        for k in kpi:
            v = k["valore"]
            w.writerow([k["area"], k["kpi"], "" if v is None else str(v).replace(".", ","), k["unita"]])


COLONNE_ANOMALIE = ["gravita", "tipo", "vat", "codice_vettore", "ragione_sociale", "dettaglio", "azione_suggerita"]


def scrivi_csv_anomalie(percorso: str, anomalie: list):
    with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE_ANOMALIE, delimiter=";")
        w.writeheader()
        w.writerows(anomalie)


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def rendi_markdown(a: dict, fonte: str = "") -> str:
    k = {x["kpi"]: x for x in a["kpi"]}
    da, al = a["periodo"]
    conta = Counter(x["gravita"] for x in a["anomalie"])
    per_gravita = ", ".join(f"{g} {conta[g]}" for g in GRAVITA)
    righe = [
        "# Report KPI onboarding sub-vettori su P44",
        "",
        f"- Data di riferimento: **{a['rif']:%Y-%m-%d %H:%M} UTC**",
        f"- Periodo eventi: {da:%Y-%m-%d} → {al:%Y-%m-%d}" if da else "- Periodo eventi: nessun evento",
        f"- Fonti: `{fonte or 'eventi.csv, stato_vettori.csv'}`",
        f"- Generato il {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "",
        "## Sintesi",
        "",
        f"- **{a['invitati']}** vettori invitati, **{a['funnel']['ACCETTATI']}** accettati "
        f"(**{_fmt_valore(k['Tasso di accettazione'])}**), {a['funnel']['RIFIUTATI']} rifiutati, "
        f"{a['funnel']['TENTATIVI_ESAURITI']} a tentativi esauriti, {a['funnel']['IN_CORSO']} in corso",
        f"- Tempo mediano di accettazione dal primo invito: "
        f"**{_fmt_valore(k['Tempo di accettazione dal primo invito - mediana'])} giorni**",
        f"- Solleciti inviati: {k['Solleciti 1 inviati (+2 gg)']['valore']} S1 + "
        f"{k['Solleciti 2 inviati (+5 gg)']['valore']} S2; re-inviti: {k['Re-inviti inviati (dopo EXPIRED)']['valore']}",
        f"- Anomalie: **{len(a['anomalie'])}** ({per_gravita})",
        "",
        "## Funnel",
        "",
        "| Stato | Vettori | % su invitati |",
        "|---|---:|---:|",
    ]
    for chiave, etichetta in FUNNEL:
        n = a["funnel"][chiave]
        if n or chiave != "ALTRO":
            righe.append(f"| {etichetta} | {n} | {_fmt_num(_pct(n, a['invitati']))}% |")
    righe.append(f"| **Totale invitati** | **{a['invitati']}** | 100% |")

    area_corrente = None
    for x in a["kpi"]:
        if x["area"] == "Funnel":
            continue
        if x["area"] != area_corrente:
            area_corrente = x["area"]
            righe += ["", f"## {area_corrente}", "", "| KPI | Valore | Unità |", "|---|---:|---|"]
        righe.append(f"| {_md_escape(x['kpi'])} | {_fmt_valore(x)} | {'' if x['unita'] == '%' else x['unita']} |")

    righe += ["", f"## Anomalie ({len(a['anomalie'])})", ""]
    if not a["anomalie"]:
        righe.append("Nessuna anomalia rilevata.")
    else:
        righe += ["| Gravità | Tipo | Vettore | P.IVA | Dettaglio | Azione suggerita |", "|---|---|---|---|---|---|"]
        for x in a["anomalie"]:
            vettore = f"{x['codice_vettore']} {x['ragione_sociale']}".strip() or "-"
            righe.append(f"| {x['gravita']} | {x['tipo']} | {_md_escape(vettore)} | {x['vat'] or '-'} | "
                         f"{_md_escape(x['dettaglio'])} | {_md_escape(x['azione_suggerita'])} |")
    righe += ["", "## Note di lettura", "",
              "- Funnel: stato corrente dell'ultimo invito di ciascun vettore (fonte di verità: P44).",
              "- Tempi: dal `createdDateTime` dell'invito al `lastModifiedDateTime` dell'esito su P44.",
              "- Efficacia solleciti: un accettato su re-invito è contato solo come \"re-invito\".",
              "- I vettori DECLINED non vengono re-invitati (decisione 15): gestione manuale.", ""]
    return "\n".join(righe)


def genera_report(cartella_input: str, cartella_output: str = None, data_rif: datetime = None) -> dict:
    """Legge gli export, calcola KPI/anomalie e scrive i 3 file. Restituisce l'analisi + i percorsi."""
    cartella_output = cartella_output or os.path.join(cartella_input, "report")
    eventi = leggi_export(os.path.join(cartella_input, "eventi.csv"), COLONNE_EVENTI)
    stato = leggi_export(os.path.join(cartella_input, "stato_vettori.csv"), COLONNE_STATO)
    analisi = analizza(eventi, stato, data_rif)
    os.makedirs(cartella_output, exist_ok=True)
    percorsi = {n: os.path.join(cartella_output, n) for n in ("report_kpi.md", "kpi.csv", "anomalie.csv")}
    with open(percorsi["report_kpi.md"], "w", encoding="utf-8", newline="\n") as f:
        f.write(rendi_markdown(analisi, os.path.abspath(cartella_input)))
    scrivi_csv_kpi(percorsi["kpi.csv"], analisi["kpi"])
    scrivi_csv_anomalie(percorsi["anomalie.csv"], analisi["anomalie"])
    analisi["file"] = percorsi
    return analisi


def main(argv=None):
    ap = argparse.ArgumentParser(prog="report_kpi", description="Report KPI/anomalie onboarding P44")
    ap.add_argument("--input", default="output", help="cartella con eventi.csv e stato_vettori.csv")
    ap.add_argument("--output", help="cartella del report (default <input>/report)")
    ap.add_argument("--data-rif", help="istante di riferimento ISO (default: ultimo evento)")
    a = ap.parse_args(argv)
    try:
        rif = parse_iso(a.data_rif if "T" in (a.data_rif or "T") else a.data_rif + "T23:59:59Z") \
            if a.data_rif else None
        r = genera_report(a.input, a.output, rif)
    except (OSError, ValueError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    k = {x["kpi"]: x for x in r["kpi"]}
    print(f"Invitati {r['invitati']}, accettati {r['funnel']['ACCETTATI']} "
          f"({_fmt_valore(k['Tasso di accettazione'])}), anomalie {len(r['anomalie'])}")
    print(f"Report: {r['file']['report_kpi.md']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
