"""Registro locale dell'orchestratore (sqlite3): stato per vettore, solleciti inviati, log eventi.

La fonte di verità sugli inviti resta P44 (GET invitations). Qui si conserva solo ciò che
P44 non sa: solleciti già inviati, ultimo stato visto (per rilevare i cambi) e lo storico eventi.
"""

import csv
import os
import sqlite3
from datetime import datetime, timezone

from .tempo import fmt_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vettori (
    vat               TEXT PRIMARY KEY,      -- VAT_P44 (identificativo inviato a P44)
    codice_vettore    TEXT NOT NULL,
    ragione_sociale   TEXT NOT NULL,
    email             TEXT,
    stato             TEXT,                  -- ultimo stato P44 visto dell'invito corrente
    tentativi         INTEGER NOT NULL DEFAULT 0,
    invito_creato     TEXT,                  -- createdDateTime dell'invito corrente (chiave del tentativo)
    sollecito1        TEXT,                  -- istante logico del sollecito, NULL = non inviato
    sollecito2        TEXT,
    esaurito          INTEGER NOT NULL DEFAULT 0,
    ultimo_controllo  TEXT,
    ultimo_errore     TEXT
);
CREATE TABLE IF NOT EXISTS eventi (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    istante_logico   TEXT NOT NULL,          -- ora del ciclo (virtuale nel POC)
    istante_reale    TEXT NOT NULL,
    vat              TEXT,
    codice_vettore   TEXT,
    ragione_sociale  TEXT,
    tipo             TEXT NOT NULL,
    tentativo        INTEGER,
    dettaglio        TEXT
);
CREATE INDEX IF NOT EXISTS ix_eventi_vat ON eventi(vat, tipo);
CREATE TABLE IF NOT EXISTS scarti (
    codice_vettore TEXT PRIMARY KEY,
    motivo         TEXT NOT NULL,
    istante        TEXT NOT NULL
);
"""

COLONNE_EVENTI = ["id", "istante_logico", "istante_reale", "vat", "codice_vettore",
                  "ragione_sociale", "tipo", "tentativo", "dettaglio"]
COLONNE_STATO = ["vat", "codice_vettore", "ragione_sociale", "email", "stato", "tentativi",
                 "invito_creato", "sollecito1", "sollecito2", "esaurito", "ultimo_controllo",
                 "ultimo_errore"]


class Registro:
    def __init__(self, percorso_db: str = ":memory:"):
        if percorso_db != ":memory:" and os.path.dirname(percorso_db):
            os.makedirs(os.path.dirname(percorso_db), exist_ok=True)
        self._db = sqlite3.connect(percorso_db)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def chiudi(self):
        self._db.close()

    def commit(self):
        self._db.commit()

    # ------------------------------------------------------------------ vettori
    def vettore(self, vat: str):
        return self._db.execute("SELECT * FROM vettori WHERE vat = ?", (vat,)).fetchone()

    def salva_vettore(self, vat: str, **campi):
        """Upsert: crea la riga se manca, poi aggiorna solo i campi passati."""
        self._db.execute(
            "INSERT INTO vettori(vat, codice_vettore, ragione_sociale) VALUES(?, ?, ?) "
            "ON CONFLICT(vat) DO NOTHING",
            (vat, campi.get("codice_vettore", ""), campi.get("ragione_sociale", "")))
        if campi:
            nomi = sorted(campi)
            self._db.execute(
                f"UPDATE vettori SET {', '.join(f'{n} = ?' for n in nomi)} WHERE vat = ?",
                [campi[n] for n in nomi] + [vat])

    # ------------------------------------------------------------------ scarti
    def scarto_noto(self, codice: str) -> bool:
        return self._db.execute("SELECT 1 FROM scarti WHERE codice_vettore = ?",
                                (codice,)).fetchone() is not None

    def registra_scarto(self, codice: str, motivo: str, istante):
        self._db.execute("INSERT OR IGNORE INTO scarti VALUES(?, ?, ?)",
                         (codice, motivo, fmt_iso(istante)))

    # ------------------------------------------------------------------ eventi
    def evento(self, istante, tipo: str, vat=None, codice=None, ragione=None,
               tentativo=None, dettaglio=""):
        self._db.execute(
            "INSERT INTO eventi(istante_logico, istante_reale, vat, codice_vettore, "
            "ragione_sociale, tipo, tentativo, dettaglio) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (fmt_iso(istante), fmt_iso(datetime.now(timezone.utc)), vat, codice, ragione,
             tipo, tentativo, dettaglio))

    def eventi(self, vat=None, tipo=None):
        where, par = [], []
        if vat:
            where.append("vat = ?")
            par.append(vat)
        if tipo:
            where.append("tipo = ?")
            par.append(tipo)
        sql = "SELECT * FROM eventi" + (" WHERE " + " AND ".join(where) if where else "")
        return self._db.execute(sql + " ORDER BY id", par).fetchall()

    # ------------------------------------------------------------------ export CSV (Excel)
    def esporta(self, cartella: str):
        """Riscrive output/eventi.csv e output/stato_vettori.csv (';', UTF-8 BOM)."""
        os.makedirs(cartella, exist_ok=True)
        for nome, sql, colonne in (
                ("eventi.csv", "SELECT * FROM eventi ORDER BY id", COLONNE_EVENTI),
                ("stato_vettori.csv", "SELECT * FROM vettori ORDER BY ragione_sociale", COLONNE_STATO)):
            percorso = os.path.join(cartella, nome)
            with open(percorso, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(colonne)
                for r in self._db.execute(sql):
                    w.writerow(["" if r[c] is None else r[c] for c in colonne])
