"""Orchestratore FERCAM dell'onboarding sub-vettori su project44 (attività #6).

Un "ciclo" è idempotente e va eseguito una volta al giorno (es. Utilità di pianificazione
di Windows, a livello utente). Per ogni vettore OK del CSV (tracciato della query SGA #4):
  1. GET invitations per inviteeIdentifier VAT = VAT_P44 → invito corrente = il più recente;
  2. nessun invito → POST invito (tentativo 1);
  3. IN_PROGRESS → sollecito 1 a +2 gg e sollecito 2 a +5 gg dall'invito (giorni di calendario UTC);
  4. EXPIRED → nuovo invito (re-invito) fino a --max-tentativi, poi evento TENTATIVI_ESAURITI;
  5. ACCEPTED / DECLINED / CANCELLED → stato finale, solo evento di cambio stato.
Ogni passaggio è registrato nel log eventi (sqlite + output/eventi.csv).

Uso (dalla radice del repo, mock avviato su 8044):
    python -m src.onboarding.orchestratore --csv data/vettori_fittizi.csv --orologio mock
Credenziali: P44_CLIENT_ID / P44_CLIENT_SECRET (default: credenziali demo del mock).
"""

import argparse
import csv
import os
import sys

from . import tracciato
from .p44_client import ClientP44, ErroreP44, OrologioMock, OrologioSistema
from .registro import Registro
from .solleciti import scrivi_sollecito
from .tempo import fmt_iso, giorni_calendario, parse_iso

GIORNI_SOLLECITO_1 = 2
GIORNI_SOLLECITO_2 = 5
MAX_TENTATIVI = 3            # 1 invito + 2 re-inviti dopo EXPIRED
STATI_FINALI = {"ACCEPTED", "DECLINED", "CANCELLED", "CANCELED"}


class ErroreSistemico(Exception):
    """Errore che rende inutile proseguire il ciclo (rete giù, credenziali errate)."""


# ---------------------------------------------------------------------- input
def leggi_vettori(percorso: str):
    """Legge il CSV della query SGA. Restituisce (righe OK, righe scartate con motivo)."""
    with open(percorso, encoding=tracciato.ENCODING, newline="") as f:
        lettore = csv.DictReader(f, delimiter=tracciato.SEPARATORE)
        mancanti = [c for c in tracciato.COLONNE if c not in (lettore.fieldnames or [])]
        if mancanti:
            raise ValueError(f"CSV non conforme al tracciato, colonne mancanti: {', '.join(mancanti)}")
        ok, scarti, viste = [], [], set()
        for r in lettore:
            r = {k: (v or "").strip() for k, v in r.items() if k}
            vat = r["VAT_P44"].upper()
            if r["ESITO_CONTROLLO"] != "OK":
                scarti.append((r, f"ESITO_CONTROLLO={r['ESITO_CONTROLLO'] or 'vuoto'}"))
            elif not vat or not r["POC_EMAIL"] or not r["RAGIONE_SOCIALE"]:
                scarti.append((r, "VAT_P44, POC_EMAIL o RAGIONE_SOCIALE mancanti"))
            elif vat in viste:
                scarti.append((r, f"VAT_P44 {vat} duplicata nel CSV (già presente su altro codice vettore)"))
            else:
                r["VAT_P44"] = vat
                viste.add(vat)
                ok.append(r)
    return ok, scarti


def invitee_da_riga(r: dict) -> dict:
    """Riga CSV → oggetto invitee del contratto P44 (vedi docs/p44-api-contract.md)."""
    contatto = {"email": r["POC_EMAIL"],
                "givenName": r["POC_NOME"] or tracciato.NOMINATIVO_DEFAULT,
                "locale": r["POC_LOCALE"] or tracciato.locale_per_nazione(r["NAZIONE"])}
    if r.get("POC_COGNOME"):
        contatto["familyName"] = r["POC_COGNOME"]
    if r.get("POC_TELEFONO"):
        contatto["phone"] = r["POC_TELEFONO"]
    return {"identifiers": [{"type": "VAT", "value": r["VAT_P44"]}],
            "organization": {"name": r["RAGIONE_SOCIALE"]},
            "contacts": [contatto]}


# ---------------------------------------------------------------------- orchestratore
class Orchestratore:
    def __init__(self, client: ClientP44, registro: Registro, orologio, cartella_output: str,
                 max_tentativi: int = MAX_TENTATIVI, log=print):
        self.client = client
        self.reg = registro
        self.orologio = orologio
        self.out = cartella_output
        self.cartella_solleciti = os.path.join(cartella_output, "solleciti")
        self.max_tentativi = max_tentativi
        self.log = log or (lambda *_: None)

    def esegui_ciclo(self, percorso_csv: str) -> dict:
        adesso = self.orologio.adesso()
        ok, scarti = leggi_vettori(percorso_csv)
        conteggi = {"vettori": len(ok), "scartati": len(scarti), "inviti": 0, "reinviti": 0,
                    "solleciti": 0, "errori": 0, "cambi_stato": 0}
        self.reg.evento(adesso, "CICLO_INIZIO", dettaglio=f"csv={os.path.basename(percorso_csv)}; "
                                                          f"vettori OK={len(ok)}; scartati={len(scarti)}")
        for r, motivo in scarti:
            if not self.reg.scarto_noto(r["CODICE_VETTORE"]):   # evento una sola volta
                self.reg.registra_scarto(r["CODICE_VETTORE"], motivo, adesso)
                self.reg.evento(adesso, "SCARTATO", r.get("VAT_P44") or None, r["CODICE_VETTORE"],
                                r.get("RAGIONE_SOCIALE"), dettaglio=motivo)
        try:
            for r in ok:
                try:
                    self._gestisci(r, adesso, conteggi)
                except ErroreP44 as e:
                    if e.status in (0, 401, 403):
                        raise ErroreSistemico(str(e)) from e
                    conteggi["errori"] += 1
                    self.reg.salva_vettore(r["VAT_P44"], ultimo_errore=str(e))
                    self.reg.evento(adesso, "ERRORE_API", r["VAT_P44"], r["CODICE_VETTORE"],
                                    r["RAGIONE_SOCIALE"], dettaglio=f"{e} {e.dettaglio.get('errors', '')}")
                self.reg.commit()   # commit per vettore: un'interruzione non perde il lavoro fatto
        except ErroreSistemico as e:
            self.reg.evento(adesso, "CICLO_INTERROTTO", dettaglio=str(e))
            self.reg.commit()
            self.reg.esporta(self.out)
            raise
        self.reg.evento(adesso, "CICLO_FINE", dettaglio="; ".join(f"{k}={v}" for k, v in conteggi.items()))
        self.reg.commit()
        self.reg.esporta(self.out)
        return conteggi

    # ------------------------------------------------------------------ singolo vettore
    def _gestisci(self, r: dict, adesso, conteggi: dict):
        vat = r["VAT_P44"]
        anag = {"codice_vettore": r["CODICE_VETTORE"], "ragione_sociale": r["RAGIONE_SOCIALE"],
                "email": r["POC_EMAIL"]}
        ev = lambda tipo, tent=None, det="": self.reg.evento(  # noqa: E731
            adesso, tipo, vat, r["CODICE_VETTORE"], r["RAGIONE_SOCIALE"], tent, det)

        inviti = self.client.inviti_per_identificativo(vat)
        if not inviti:
            self._invita(r, adesso, 1, conteggi, ev)
            return

        corrente = max(inviti, key=lambda i: parse_iso(i["createdDateTime"]))
        tentativi, stato = len(inviti), corrente["status"]
        rec = self.reg.vettore(vat)
        if rec is None or rec["invito_creato"] != corrente["createdDateTime"]:
            # invito non creato da questo registro (es. primo avvio su dati esistenti)
            ev("INVITO_GIA_PRESENTE", tentativi, f"stato={stato}; creato={corrente['createdDateTime']}")
            self.reg.salva_vettore(vat, **anag, invito_creato=corrente["createdDateTime"],
                                   sollecito1=None, sollecito2=None, stato=stato)
            rec = self.reg.vettore(vat)
        elif rec["stato"] != stato:
            conteggi["cambi_stato"] += 1
            ev(f"STATO_{stato}", tentativi,
               f"{rec['stato']} -> {stato} il {corrente['lastModifiedDateTime']}")
        self.reg.salva_vettore(vat, **anag, stato=stato, tentativi=tentativi,
                               ultimo_controllo=fmt_iso(adesso), ultimo_errore=None)

        if stato == "IN_PROGRESS":
            self._sollecita(r, rec, corrente, adesso, tentativi, conteggi, ev)
        elif stato == "EXPIRED":
            if tentativi < self.max_tentativi:
                self._invita(r, adesso, tentativi + 1, conteggi, ev)
            elif not rec["esaurito"]:
                self.reg.salva_vettore(vat, esaurito=1)
                ev("TENTATIVI_ESAURITI", tentativi,
                   f"{tentativi} inviti scaduti: gestione manuale dell'Ufficio Vettori")
        # ACCEPTED / DECLINED / CANCELLED: nessuna azione automatica

    def _invita(self, r, adesso, tentativo, conteggi, ev):
        vat = r["VAT_P44"]
        try:
            invito = self.client.crea_invito(invitee_da_riga(r))
        except ErroreP44 as e:
            if e.status != 409:
                raise
            # già IN_PROGRESS su P44 (es. creato da altri): si adotta al prossimo controllo
            ev("INVITO_GIA_PRESENTE", tentativo, "409 da P44: invito IN_PROGRESS già esistente")
            return
        self.reg.salva_vettore(vat, codice_vettore=r["CODICE_VETTORE"],
                               ragione_sociale=r["RAGIONE_SOCIALE"], email=r["POC_EMAIL"],
                               stato=invito["status"], tentativi=tentativo,
                               invito_creato=invito["createdDateTime"], sollecito1=None,
                               sollecito2=None, esaurito=0, ultimo_controllo=fmt_iso(adesso),
                               ultimo_errore=None)
        tipo = "INVITO_INVIATO" if tentativo == 1 else "REINVITO_INVIATO"
        conteggi["inviti" if tentativo == 1 else "reinviti"] += 1
        ev(tipo, tentativo, f"a {r['POC_EMAIL']}; creato={invito['createdDateTime']}")
        self.log(f"  {tipo:<17} {vat:<16} {r['RAGIONE_SOCIALE']} (tentativo {tentativo})")

    def _sollecita(self, r, rec, invito, adesso, tentativo, conteggi, ev):
        creato = parse_iso(invito["createdDateTime"])
        giorni = giorni_calendario(creato, adesso)
        if giorni >= GIORNI_SOLLECITO_2 and not rec["sollecito2"]:
            numero, nota = 2, ("" if rec["sollecito1"] else "; sollecito 1 non inviato (ciclo in ritardo)")
        elif giorni >= GIORNI_SOLLECITO_1 and not rec["sollecito1"] and not rec["sollecito2"]:
            numero, nota = 1, ""
        else:
            return
        percorso = scrivi_sollecito(self.cartella_solleciti, numero, r, creato, adesso)
        self.reg.salva_vettore(r["VAT_P44"], **{f"sollecito{numero}": fmt_iso(adesso)})
        conteggi["solleciti"] += 1
        ev(f"SOLLECITO_{numero}", tentativo, f"+{giorni} gg; {os.path.basename(percorso)}{nota}")
        self.log(f"  SOLLECITO_{numero}       {r['VAT_P44']:<16} {r['RAGIONE_SOCIALE']} (+{giorni} gg)")


# ---------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="orchestratore", description="Onboarding sub-vettori FERCAM su P44")
    ap.add_argument("--csv", default=os.path.join("data", "vettori_fittizi.csv"),
                    help="CSV vettori (tracciato query SGA #4)")
    ap.add_argument("--base-url", default=os.environ.get("P44_BASE_URL", "http://127.0.0.1:8044"))
    ap.add_argument("--db", default=os.path.join("data", "orchestratore.db"))
    ap.add_argument("--output", default="output", help="cartella di eventi.csv, stato_vettori.csv, solleciti/")
    ap.add_argument("--orologio", choices=("sistema", "mock"), default="sistema",
                    help="'mock' = ora virtuale da /_sim/clock (solo demo col mock)")
    ap.add_argument("--max-tentativi", type=int, default=MAX_TENTATIVI)
    a = ap.parse_args(argv)

    cid = os.environ.get("P44_CLIENT_ID", "fercam-poc")
    sec = os.environ.get("P44_CLIENT_SECRET", "fercam-poc-secret")
    if "P44_CLIENT_ID" not in os.environ:
        print("ATTENZIONE: credenziali demo del mock (impostare P44_CLIENT_ID/P44_CLIENT_SECRET)", file=sys.stderr)
    orologio = OrologioMock(a.base_url) if a.orologio == "mock" else OrologioSistema()

    reg = Registro(a.db)
    try:
        orch = Orchestratore(ClientP44(a.base_url, cid, sec), reg, orologio, a.output, a.max_tentativi)
        print(f"Ciclo onboarding P44 - ora {fmt_iso(orologio.adesso())} - {a.base_url}")
        c = orch.esegui_ciclo(a.csv)
    except ErroreSistemico as e:
        print(f"CICLO INTERROTTO: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    finally:
        reg.chiudi()
    print("Esito: " + ", ".join(f"{k}={v}" for k, v in c.items()))
    print(f"Log: {os.path.join(a.output, 'eventi.csv')}  Stato: {os.path.join(a.output, 'stato_vettori.csv')}")
    return 1 if c["errori"] else 0


if __name__ == "__main__":
    sys.exit(main())
