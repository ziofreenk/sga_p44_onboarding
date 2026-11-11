"""Persistenza del mock P44 (sqlite3) con orologio virtuale ed evoluzione degli stati.

Thread-safety: una sola connessione protetta da un lock (il server HTTP è multi-thread).
Tutti gli orari sono UTC, formato ISO-8601 a larghezza fissa ("...T..:..:..sssZ"),
quindi confrontabili anche come stringhe in SQL.
"""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from .scenari import SCENARI, esito_per_tentativo, scenario_predefinito

STATI_FINALI = ("ACCEPTED", "DECLINED", "CANCELLED", "EXPIRED")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invitations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    capability        TEXT NOT NULL,
    invitee_json      TEXT NOT NULL,
    status            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    last_modified_at  TEXT NOT NULL,
    -- campi interni della simulazione (mai esposti dalle API P44)
    scenario          TEXT NOT NULL,
    tentativo         INTEGER NOT NULL,
    esito             TEXT NOT NULL,
    scadenza_esito    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invitation_identifiers (
    invitation_id  INTEGER NOT NULL REFERENCES invitations(id) ON DELETE CASCADE,
    type           TEXT NOT NULL,
    value          TEXT NOT NULL   -- normalizzato in maiuscolo
);
CREATE INDEX IF NOT EXISTS ix_ident ON invitation_identifiers(type, value);
CREATE INDEX IF NOT EXISTS ix_inv_status ON invitations(status, scadenza_esito);
CREATE TABLE IF NOT EXISTS sim_state (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sim_scenari (valore TEXT PRIMARY KEY, scenario TEXT NOT NULL);
"""


def fmt(dt: datetime) -> str:
    """datetime UTC → ISO-8601 con millisecondi e suffisso Z (larghezza fissa)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse(s: str) -> datetime:
    """ISO-8601 (anche con Z o offset) → datetime UTC aware."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ora_reale() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, percorso_db: str = ":memory:", scenari=None):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(percorso_db, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        # Mappa scenari "di base" (es. da file all'avvio): riapplicata a ogni reset
        self._scenari_base = dict(scenari or {})
        if self._scenari_base:
            self.imposta_scenari(self._scenari_base)
        with self._lock, self._db:
            if self._get_state("virtual_base") is None:
                self._reset_orologio(None)

    # ------------------------------------------------------------------ orologio
    def _get_state(self, chiave):
        r = self._db.execute("SELECT valore FROM sim_state WHERE chiave = ?", (chiave,)).fetchone()
        return r["valore"] if r else None

    def _set_state(self, chiave, valore):
        self._db.execute(
            "INSERT INTO sim_state(chiave, valore) VALUES(?, ?) "
            "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore", (chiave, valore))

    def _reset_orologio(self, istante_virtuale):
        reale = _ora_reale()
        self._set_state("real_base", fmt(reale))
        self._set_state("virtual_base", fmt(istante_virtuale or reale))

    def adesso(self) -> datetime:
        """Ora virtuale = base virtuale + tempo reale trascorso dalla base."""
        with self._lock:
            vb = parse(self._get_state("virtual_base"))
            rb = parse(self._get_state("real_base"))
        return vb + (_ora_reale() - rb)

    def imposta_orologio(self, istante: datetime) -> datetime:
        """Porta l'orologio virtuale a un istante preciso (anche indietro)."""
        with self._lock, self._db:
            self._reset_orologio(istante)
        return self.adesso()

    def avanza_orologio(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("l'orologio può solo avanzare (usare 'set' per spostarlo)")
        return self.imposta_orologio(self.adesso() + delta)

    # ------------------------------------------------------------------ scenari
    def imposta_scenari(self, mappa: dict):
        """mappa: {valore identificativo (es. P.IVA): nome scenario}."""
        for valore, scenario in mappa.items():
            if scenario not in SCENARI:
                raise ValueError(f"scenario sconosciuto: {scenario}")
        with self._lock, self._db:
            for valore, scenario in mappa.items():
                self._db.execute(
                    "INSERT INTO sim_scenari(valore, scenario) VALUES(?, ?) "
                    "ON CONFLICT(valore) DO UPDATE SET scenario = excluded.scenario",
                    (valore.strip().upper(), scenario))

    def _scenario_per(self, identificativi) -> str:
        for ident in identificativi:
            r = self._db.execute("SELECT scenario FROM sim_scenari WHERE valore = ?",
                                 (ident["value"].strip().upper(),)).fetchone()
            if r:
                return r["scenario"]
        return scenario_predefinito(identificativi[0]["value"])

    # ------------------------------------------------------------------ reset
    def reset(self, istante=None, scenari=None):
        """Svuota gli inviti, riporta l'orologio a 'istante' (default: ora reale) e
        ripristina la mappa scenari di base, più quella eventualmente passata."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM invitation_identifiers")
            self._db.execute("DELETE FROM invitations")
            self._db.execute("DELETE FROM sim_scenari")
            self._reset_orologio(istante)
        mappa = dict(self._scenari_base)
        mappa.update(scenari or {})
        if mappa:
            self.imposta_scenari(mappa)

    # ------------------------------------------------------------------ evoluzione
    def _evolvi(self, adesso: datetime):
        """Applica le transizioni maturate: lo stato finale prende come
        lastModifiedDateTime l'istante virtuale previsto dallo scenario."""
        self._db.execute(
            "UPDATE invitations SET status = esito, last_modified_at = scadenza_esito "
            "WHERE status = 'IN_PROGRESS' AND scadenza_esito <= ?", (fmt(adesso),))

    # ------------------------------------------------------------------ inviti
    def _chiavi_in_corso(self, capability, identificativi):
        """Inviti IN_PROGRESS con la stessa capability e almeno un identificativo uguale."""
        trovati = 0
        for ident in identificativi:
            r = self._db.execute(
                "SELECT COUNT(*) AS n FROM invitations i JOIN invitation_identifiers x "
                "ON x.invitation_id = i.id WHERE i.capability = ? AND i.status = 'IN_PROGRESS' "
                "AND x.type = ? AND x.value = ?",
                (capability, ident["type"], ident["value"].strip().upper())).fetchone()
            trovati += r["n"]
        return trovati

    def _tentativi_precedenti(self, capability, identificativi):
        ids = set()
        for ident in identificativi:
            for r in self._db.execute(
                    "SELECT i.id FROM invitations i JOIN invitation_identifiers x "
                    "ON x.invitation_id = i.id WHERE i.capability = ? AND x.type = ? AND x.value = ?",
                    (capability, ident["type"], ident["value"].strip().upper())):
                ids.add(r["id"])
        return len(ids)

    def crea_invito(self, capability: str, invitee: dict):
        """Crea un invito IN_PROGRESS. Restituisce (invito, None) oppure (None, 'DUPLICATO')."""
        identificativi = invitee["identifiers"]
        with self._lock, self._db:
            adesso = self.adesso()
            self._evolvi(adesso)
            if self._chiavi_in_corso(capability, identificativi):
                return None, "DUPLICATO"
            tentativo = self._tentativi_precedenti(capability, identificativi) + 1
            scenario = self._scenario_per(identificativi)
            esito, giorni = esito_per_tentativo(scenario, tentativo)
            ts = fmt(adesso)
            cur = self._db.execute(
                "INSERT INTO invitations(capability, invitee_json, status, created_at, "
                "last_modified_at, scenario, tentativo, esito, scadenza_esito) "
                "VALUES(?, ?, 'IN_PROGRESS', ?, ?, ?, ?, ?, ?)",
                (capability, json.dumps(invitee, ensure_ascii=False), ts, ts, scenario,
                 tentativo, esito, fmt(adesso + timedelta(days=giorni))))
            for ident in identificativi:
                self._db.execute(
                    "INSERT INTO invitation_identifiers(invitation_id, type, value) VALUES(?, ?, ?)",
                    (cur.lastrowid, ident["type"], ident["value"].strip().upper()))
            return self._riga(cur.lastrowid), None

    def _riga(self, id_):
        return self._db.execute("SELECT * FROM invitations WHERE id = ?", (id_,)).fetchone()

    def cerca_inviti(self, capability=None, tipo_ident=None, valore_ident=None,
                     pagina=1, dimensione=10):
        """Restituisce (righe della pagina, totale). Ordine: creazione crescente."""
        where, par = [], []
        if capability:
            where.append("i.capability = ?")
            par.append(capability)
        if tipo_ident or valore_ident:
            sub, sub_par = [], []
            if tipo_ident:
                sub.append("x.type = ?")
                sub_par.append(tipo_ident)
            if valore_ident:
                sub.append("x.value = ?")
                sub_par.append(valore_ident.strip().upper())
            where.append("EXISTS (SELECT 1 FROM invitation_identifiers x WHERE "
                         "x.invitation_id = i.id AND " + " AND ".join(sub) + ")")
            par.extend(sub_par)
        sql_where = (" WHERE " + " AND ".join(where)) if where else ""
        with self._lock, self._db:
            self._evolvi(self.adesso())
            totale = self._db.execute(
                "SELECT COUNT(*) AS n FROM invitations i" + sql_where, par).fetchone()["n"]
            righe = self._db.execute(
                "SELECT * FROM invitations i" + sql_where + " ORDER BY i.id LIMIT ? OFFSET ?",
                par + [dimensione, (pagina - 1) * dimensione]).fetchall()
        return righe, totale

    def chiudi(self):
        with self._lock:
            self._db.close()


def invito_json(riga) -> dict:
    """Rappresentazione P44 dell'invito: solo i campi del contratto, niente dati di simulazione."""
    return {
        "capability": riga["capability"],
        "invitee": json.loads(riga["invitee_json"]),
        "status": riga["status"],
        "createdDateTime": riga["created_at"],
        "lastModifiedDateTime": riga["last_modified_at"],
    }
