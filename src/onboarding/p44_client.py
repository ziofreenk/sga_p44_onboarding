"""Client HTTP minimale per le API project44 usate dal POC (solo libreria standard).

Funziona identico col mock locale e con P44 reale: cambiano solo base_url e credenziali.
- OAuth2 client_credentials (HTTP Basic), token in cache fino a 60 s prima della scadenza;
  su 401 il token viene rigenerato una sola volta e la chiamata ripetuta.
- Retry con backoff solo su errori transitori (rete, 429, 5xx). Mai su 4xx applicativi.
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

PATH_TOKEN = "/api/v4/oauth2/token"
PATH_INVITI = "/services/invitation/v1/invitations"
CAPABILITY = "TRUCKLOAD_ASSET_TRACKING"
PAGE_SIZE_MAX = 25

# Opener senza proxy per gli indirizzi di loopback (mock locale). Su Windows urllib legge il proxy
# aziendale dal registro e non lo bypassa per 127.0.0.1: le chiamate al mock finirebbero sul proxy.
_OPENER_SENZA_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def e_loopback(url: str) -> bool:
    """True se l'URL punta alla macchina locale (localhost, 127.x.x.x, ::1)."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.")


def apri(req, timeout: float):
    """urlopen che salta il proxy di sistema per il mock locale; per P44 reale usa il proxy di sistema."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if e_loopback(url):
        return _OPENER_SENZA_PROXY.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


class ErroreP44(Exception):
    """Errore HTTP restituito da P44 (corpo ApiError, se presente, in .dettaglio)."""

    def __init__(self, status: int, messaggio: str, dettaglio=None):
        super().__init__(f"HTTP {status}: {messaggio}")
        self.status = status
        self.messaggio = messaggio
        self.dettaglio = dettaglio or {}


class ClientP44:
    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 timeout: float = 15.0, tentativi_rete: int = 3, pausa_retry: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self._cid, self._sec = client_id, client_secret
        self.timeout = timeout
        self.tentativi_rete = max(1, tentativi_rete)
        self.pausa_retry = pausa_retry
        self._token = None
        self._scadenza = 0.0

    # ------------------------------------------------------------------ HTTP grezzo
    def _http(self, metodo, path, corpo=None, headers=None, query=None):
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        h = {"Accept": "application/json"}
        h.update(headers or {})
        ultimo = None
        for n in range(self.tentativi_rete):
            req = urllib.request.Request(url, data=corpo, headers=h, method=metodo)
            try:
                with apri(req, self.timeout) as r:
                    raw = r.read()
                    return r.status, (json.loads(raw) if raw else None)
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    det = json.loads(raw) if raw else {}
                except ValueError:
                    det = {"raw": raw[:500].decode("utf-8", "replace")}
                errore = ErroreP44(e.code, (det or {}).get("errorMessage") or e.reason, det)
                if e.code == 429 or e.code >= 500:
                    ultimo = errore            # transitorio: riprova
                else:
                    raise errore
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                ultimo = ErroreP44(0, f"errore di rete: {e}")
            if n < self.tentativi_rete - 1:
                time.sleep(self.pausa_retry * (2 ** n))
        raise ultimo

    # ------------------------------------------------------------------ OAuth2
    def _bearer(self, forza=False) -> str:
        if forza or not self._token or time.time() >= self._scadenza - 60:
            basic = base64.b64encode(f"{self._cid}:{self._sec}".encode()).decode()
            _, b = self._http("POST", PATH_TOKEN,
                              corpo=b"grant_type=client_credentials",
                              headers={"Authorization": f"Basic {basic}",
                                       "Content-Type": "application/x-www-form-urlencoded"})
            self._token = b["access_token"]
            self._scadenza = time.time() + int(b.get("expires_in", 3600))
        return self._token

    def _api(self, metodo, path, corpo_json=None, query=None):
        dati = json.dumps(corpo_json).encode("utf-8") if corpo_json is not None else None
        for forza in (False, True):
            h = {"Authorization": f"Bearer {self._bearer(forza)}"}
            if dati is not None:
                h["Content-Type"] = "application/json"
            try:
                return self._http(metodo, path, dati, h, query)
            except ErroreP44 as e:
                if e.status != 401 or forza:
                    raise
        raise AssertionError("non raggiungibile")

    # ------------------------------------------------------------------ Network Invitations
    def crea_invito(self, invitee: dict, capability: str = CAPABILITY) -> dict:
        _, b = self._api("POST", PATH_INVITI, {"capability": capability, "invitee": invitee})
        return b

    def inviti_per_identificativo(self, valore: str, tipo: str = "VAT",
                                  capability: str = CAPABILITY) -> list:
        """Tutti gli inviti (tutte le pagine) per un identificativo del vettore."""
        risultati, pagina = [], 1
        while True:
            _, b = self._api("GET", PATH_INVITI, query={
                "capability": capability, "inviteeIdentifier.type": tipo,
                "inviteeIdentifier.value": valore, "pageNumber": pagina, "pageSize": PAGE_SIZE_MAX})
            risultati.extend(b.get("results") or [])
            totale = (b.get("paginationInfo") or {}).get("total", 0)
            if len(risultati) >= totale or not b.get("results") or pagina >= 25:
                return risultati
            pagina += 1


# ---------------------------------------------------------------------- orologi
class OrologioSistema:
    """Ora reale UTC (esercizio normale e P44 reale)."""

    def adesso(self):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)


class OrologioMock:
    """Ora virtuale letta da GET /_sim/clock del mock (solo demo/test, non esiste su P44)."""

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.url = base_url.rstrip("/") + "/_sim/clock"
        self.timeout = timeout

    def adesso(self):
        from .tempo import parse_iso
        with apri(self.url, self.timeout) as r:
            return parse_iso(json.loads(r.read())["now"])
