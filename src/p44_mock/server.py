"""Server HTTP del mock project44 (solo libreria standard).

API P44 replicate (vedi docs/p44-api-contract.md):
  POST /api/v4/oauth2/token
  POST /services/invitation/v1/invitations
  GET  /services/invitation/v1/invitations
Endpoint di simulazione (NON P44, solo demo/test, senza autenticazione):
  GET|POST /_sim/clock   POST /_sim/reset   GET /_sim/scenari
"""

import base64
import binascii
import json
import re
import secrets
import threading
import time
import uuid
from datetime import timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .mail import scrivi_mail_invito
from .scenari import SCENARI
from .store import Store, fmt, invito_json, parse

PATH_TOKEN = "/api/v4/oauth2/token"
PATH_INVITI = "/services/invitation/v1/invitations"

DURATA_TOKEN_S = 43200  # ~12 h, come P44
CAPABILITIES = {"TRUCKLOAD_ASSET_TRACKING"}
TIPI_IDENTIFICATIVO = {"VAT", "SCAC", "DOT_NUMBER", "MC_NUMBER", "P44_EU"}
LOCALES = {"bg-BG", "cs-CZ", "de-DE", "en-US", "es-ES", "hu-HU", "it-IT", "lt-LT",
           "fr-FR", "pt-BR", "pl-PL", "ro-RO", "tr-TR", "uk-UA"}
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY = 1_000_000  # 1 MB: protezione da payload abnormi


class ErroreApi(Exception):
    """Errore restituito al client nel formato ApiError di P44."""

    def __init__(self, status: int, messaggio: str, errori=None):
        super().__init__(messaggio)
        self.status = status
        self.messaggio = messaggio
        self.errori = errori or []


class MockP44Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, indirizzo, store: Store, client_id: str, client_secret: str,
                 cartella_mail=None, invitante="FERCAM", log=True):
        super().__init__(indirizzo, GestoreRichieste)
        self.store = store
        self.client_id = client_id
        self.client_secret = client_secret
        self.cartella_mail = cartella_mail
        self.invitante = invitante
        self.log = log
        self._token = {}  # access_token -> scadenza (epoch reale, secondi)
        self._lock_token = threading.Lock()

    # La scadenza del token usa il tempo REALE: avanzare l'orologio virtuale
    # di giorni non deve invalidare la sessione dell'orchestratore.
    def emetti_token(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock_token:
            ora = time.time()
            self._token = {t: s for t, s in self._token.items() if s > ora}  # pulizia
            self._token[token] = ora + DURATA_TOKEN_S
        return token

    def token_valido(self, token: str) -> bool:
        with self._lock_token:
            scad = self._token.get(token)
        return scad is not None and scad > time.time()

    def credenziali_ok(self, cid: str, secret: str) -> bool:
        # confronto a tempo costante
        return (secrets.compare_digest(cid.encode(), self.client_id.encode())
                and secrets.compare_digest(secret.encode(), self.client_secret.encode()))


class GestoreRichieste(BaseHTTPRequestHandler):
    server: MockP44Server
    server_version = "P44Mock/0.1"

    # ------------------------------------------------------------- utilità I/O
    def log_message(self, fmt_, *args):
        if self.server.log:
            super().log_message(fmt_, *args)

    def _invia_json(self, status: int, corpo):
        dati = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dati)))
        self.end_headers()
        self.wfile.write(dati)

    def _invia_errore(self, err: ErroreApi):
        self._invia_json(err.status, {
            "httpStatusCode": err.status,
            "httpMessage": HTTPStatus(err.status).phrase,
            "errorMessage": err.messaggio,
            "errors": [{"message": e} for e in err.errori],
            "supportReferenceId": str(uuid.uuid4()),
        })

    def _leggi_corpo(self) -> bytes:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ErroreApi(400, "Content-Length non valido")
        if n > MAX_BODY:
            raise ErroreApi(413, "Payload troppo grande")
        return self.rfile.read(n) if n > 0 else b""

    def _leggi_json(self, obbligatorio=True):
        raw = self._leggi_corpo()
        if not raw:
            if obbligatorio:
                raise ErroreApi(400, "Corpo della richiesta mancante")
            return {}
        try:
            dati = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErroreApi(400, "JSON non valido")
        if not isinstance(dati, dict):
            raise ErroreApi(400, "Il corpo deve essere un oggetto JSON")
        return dati

    def _richiedi_bearer(self):
        auth = self.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer ") or not self.server.token_valido(auth[7:].strip()):
            raise ErroreApi(401, "Token di accesso mancante, non valido o scaduto")

    # ------------------------------------------------------------- dispatch
    def _instrada(self, metodo: str):
        url = urlsplit(self.path)
        rotte = {
            (PATH_TOKEN, "POST"): self._post_token,
            (PATH_INVITI, "POST"): self._post_invito,
            (PATH_INVITI, "GET"): lambda: self._get_inviti(url.query),
            ("/_sim/clock", "GET"): self._get_clock,
            ("/_sim/clock", "POST"): self._post_clock,
            ("/_sim/reset", "POST"): self._post_reset,
            ("/_sim/scenari", "GET"): self._get_scenari,
        }
        percorso = url.path.rstrip("/") or "/"
        try:
            gestore = rotte.get((percorso, metodo))
            if gestore is None:
                if any(p == percorso for p, _ in rotte):
                    raise ErroreApi(405, f"Metodo {metodo} non ammesso su {percorso}")
                raise ErroreApi(404, f"Risorsa non trovata: {percorso}")
            gestore()
        except ErroreApi as e:
            self._invia_errore(e)
        except Exception as e:  # difesa: mai stack trace al client
            self.log_error("Errore interno: %r", e)
            self._invia_errore(ErroreApi(500, "Errore interno del mock"))

    def do_GET(self):
        self._instrada("GET")

    def do_POST(self):
        self._instrada("POST")

    def do_PUT(self):
        self._instrada("PUT")

    def do_DELETE(self):
        self._instrada("DELETE")

    # ------------------------------------------------------------- OAuth2
    def _post_token(self):
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            raise ErroreApi(400, "Content-Type deve essere application/x-www-form-urlencoded")
        try:
            form = {k: v[0] for k, v in parse_qs(self._leggi_corpo().decode("utf-8")).items()}
        except UnicodeDecodeError:
            raise ErroreApi(400, "Corpo non valido")

        basic = None
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("basic "):
            try:
                cid, _, sec = base64.b64decode(auth[6:].strip(), validate=True).decode("utf-8").partition(":")
            except (binascii.Error, UnicodeDecodeError):
                raise ErroreApi(400, "Header Authorization Basic non valido")
            basic = (cid, sec)
        nel_form = "client_id" in form or "client_secret" in form

        if basic and nel_form:
            raise ErroreApi(400, "Credenziali da fornire via HTTP Basic oppure nel form, non entrambi")
        if form.get("grant_type") != "client_credentials":
            raise ErroreApi(400, "grant_type deve essere client_credentials")
        cid, sec = basic if basic else (form.get("client_id", ""), form.get("client_secret", ""))
        if not cid or not sec:
            raise ErroreApi(401, "Credenziali client mancanti")
        if not self.server.credenziali_ok(cid, sec):
            raise ErroreApi(401, "Credenziali client non valide")
        self._invia_json(200, {"access_token": self.server.emetti_token(),
                               "expires_in": DURATA_TOKEN_S, "token_type": "BEARER"})

    # ------------------------------------------------------------- Inviti
    @staticmethod
    def _valida_invito(corpo: dict) -> list:
        err = []
        cap = corpo.get("capability")
        if cap not in CAPABILITIES:
            err.append(f"capability non valida: {cap!r} (ammessa: TRUCKLOAD_ASSET_TRACKING)")
        inv = corpo.get("invitee")
        if not isinstance(inv, dict):
            return err + ["invitee obbligatorio"]
        idents = inv.get("identifiers")
        if not isinstance(idents, list) or not idents:
            err.append("invitee.identifiers obbligatorio (almeno un elemento)")
        else:
            for i, x in enumerate(idents):
                if not isinstance(x, dict) or x.get("type") not in TIPI_IDENTIFICATIVO:
                    err.append(f"invitee.identifiers[{i}].type non valido")
                elif not isinstance(x.get("value"), str) or not x["value"].strip():
                    err.append(f"invitee.identifiers[{i}].value obbligatorio")
        # Nel mock il vettore non ha mai un account P44: organization e contatti obbligatori
        org = inv.get("organization")
        if not isinstance(org, dict) or not isinstance(org.get("name"), str) or not org["name"].strip():
            err.append("invitee.organization.name obbligatorio")
        contatti = inv.get("contacts")
        if not isinstance(contatti, list) or not contatti:
            err.append("invitee.contacts obbligatorio (almeno un elemento)")
        else:
            for i, c in enumerate(contatti):
                if not isinstance(c, dict):
                    err.append(f"invitee.contacts[{i}] non valido")
                    continue
                if not isinstance(c.get("email"), str) or not _RE_EMAIL.match(c["email"]):
                    err.append(f"invitee.contacts[{i}].email non valida")
                if not isinstance(c.get("givenName"), str) or not c["givenName"].strip():
                    err.append(f"invitee.contacts[{i}].givenName obbligatorio")
                if "locale" in c and c["locale"] not in LOCALES:
                    err.append(f"invitee.contacts[{i}].locale non supportato: {c['locale']!r}")
        return err

    def _post_invito(self):
        self._richiedi_bearer()
        corpo = self._leggi_json()
        errori = self._valida_invito(corpo)
        if errori:
            raise ErroreApi(400, "Richiesta non valida", errori)
        invitee = corpo["invitee"]
        for c in invitee["contacts"]:
            c.setdefault("locale", "en-US")  # default documentato da P44
        riga, problema = self.server.store.crea_invito(corpo["capability"], invitee)
        if problema == "DUPLICATO":
            raise ErroreApi(409, "Esiste già un invito IN_PROGRESS per questo vettore e capability")
        invito = invito_json(riga)
        scrivi_mail_invito(self.server.cartella_mail, invito, self.server.invitante,
                           parse(invito["createdDateTime"]))
        self._invia_json(201, invito)

    def _get_inviti(self, query: str):
        self._richiedi_bearer()
        q = {k: v[0] for k, v in parse_qs(query).items()}
        errori = []

        def intero(nome, default):
            v = q.get(nome)
            if v is None:
                return default
            if not v.isdigit() or not 1 <= int(v) <= 25:
                errori.append(f"{nome} deve essere un intero tra 1 e 25")
                return default
            return int(v)

        pagina, dim = intero("pageNumber", 1), intero("pageSize", 10)
        tipo = q.get("inviteeIdentifier.type")
        if tipo is not None and tipo not in TIPI_IDENTIFICATIVO:
            errori.append("inviteeIdentifier.type non valido")
        cap = q.get("capability")
        if cap is not None and cap not in CAPABILITIES:
            errori.append("capability non valida")
        if errori:
            raise ErroreApi(400, "Parametri non validi", errori)
        righe, totale = self.server.store.cerca_inviti(cap, tipo, q.get("inviteeIdentifier.value"),
                                                       pagina, dim)
        self._invia_json(200, {
            "paginationInfo": {"pageNumber": pagina, "pageSize": dim, "total": totale},
            "results": [invito_json(r) for r in righe],
        })

    # ------------------------------------------------------------- Simulazione (non P44)
    def _get_clock(self):
        self._invia_json(200, {"now": fmt(self.server.store.adesso())})

    def _post_clock(self):
        """Body: {"advanceDays": n} | {"advanceHours": n} | {"set": "ISO-8601"}."""
        corpo = self._leggi_json()
        store = self.server.store
        try:
            if "set" in corpo:
                adesso = store.imposta_orologio(parse(str(corpo["set"])))
            elif "advanceDays" in corpo or "advanceHours" in corpo:
                giorni, ore = corpo.get("advanceDays", 0), corpo.get("advanceHours", 0)
                if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (giorni, ore)):
                    raise ValueError("advanceDays/advanceHours devono essere numerici")
                adesso = store.avanza_orologio(timedelta(days=giorni, hours=ore))
            else:
                raise ValueError("indicare 'advanceDays', 'advanceHours' oppure 'set'")
        except (ValueError, OverflowError) as e:
            raise ErroreApi(400, str(e))
        self._invia_json(200, {"now": fmt(adesso)})

    def _post_reset(self):
        """Body opzionale: {"now": "ISO-8601", "scenari": {"<P.IVA>": "<SCENARIO>"}}."""
        corpo = self._leggi_json(obbligatorio=False)
        scenari = corpo.get("scenari") or {}
        if not isinstance(scenari, dict) or any(s not in SCENARI for s in scenari.values()):
            raise ErroreApi(400, "scenari non validi", [f"ammessi: {', '.join(sorted(SCENARI))}"])
        try:
            istante = parse(str(corpo["now"])) if corpo.get("now") else None
        except ValueError:
            raise ErroreApi(400, "now non è una data ISO-8601 valida")
        self.server.store.reset(istante, scenari)
        self._invia_json(200, {"now": fmt(self.server.store.adesso()), "reset": True})

    def _get_scenari(self):
        self._invia_json(200, {nome: [{"status": s, "afterDays": g} for s, g in esiti]
                               for nome, esiti in SCENARI.items()})
