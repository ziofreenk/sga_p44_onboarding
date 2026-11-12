"""Test del mock P44: server reale su porta effimera, client HTTP standard.

Esecuzione (dalla radice del repo):
    python -m unittest discover -s tests -t . -v
"""

import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from src.onboarding.p44_client import apri
from src.p44_mock.scenari import SCENARI, esito_per_tentativo, scenario_predefinito
from src.p44_mock.server import MockP44Server
from src.p44_mock.store import Store, parse

CID, SEC = "test-client", "test-secret"
T0 = "2026-12-01T08:00:00Z"  # istante virtuale di partenza dei test


def payload(vat="IT01234567890", **extra_contatto):
    contatto = {"email": "poc@esempio-vettore.test", "givenName": "Mario",
                "familyName": "Rossi", "locale": "it-IT"}
    contatto.update(extra_contatto)
    return {"capability": "TRUCKLOAD_ASSET_TRACKING",
            "invitee": {"identifiers": [{"type": "VAT", "value": vat}],
                        "organization": {"name": "Trasporti Esempio S.r.l."},
                        "contacts": [contatto]}}


class MockTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mail_dir = os.path.join(self.tmp.name, "mail")
        self.store = Store(":memory:")
        self.srv = MockP44Server(("127.0.0.1", 0), self.store, CID, SEC, self.mail_dir, log=False)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.sim("/_sim/reset", {"now": T0})

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.store.chiudi()
        self.tmp.cleanup()

    # ---------------------------------------------------------------- client
    def call(self, metodo, path, corpo=None, headers=None, form=None):
        h = dict(headers or {})
        dati = None
        if form is not None:
            dati = urllib.parse.urlencode(form).encode()
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif corpo is not None:
            dati = json.dumps(corpo).encode()
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=dati, headers=h, method=metodo)
        try:
            with apri(req, 5) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def token(self):
        st, b = self.call("POST", "/api/v4/oauth2/token",
                          form={"grant_type": "client_credentials", "client_id": CID, "client_secret": SEC})
        self.assertEqual(st, 200)
        return b["access_token"]

    def auth(self):
        if not hasattr(self, "_tok"):
            self._tok = self.token()
        return {"Authorization": f"Bearer {self._tok}"}

    def invita(self, corpo):
        return self.call("POST", "/services/invitation/v1/invitations", corpo, self.auth())

    def elenco(self, **q):
        qs = ("?" + urllib.parse.urlencode(q)) if q else ""
        return self.call("GET", "/services/invitation/v1/invitations" + qs, headers=self.auth())

    def stato(self, vat):
        st, b = self.elenco(**{"inviteeIdentifier.value": vat})
        self.assertEqual(st, 200)
        return [r["status"] for r in b["results"]]

    def sim(self, path, corpo):
        st, b = self.call("POST", path, corpo)
        self.assertEqual(st, 200, b)
        return b

    def avanza(self, giorni=0, ore=0):
        return self.sim("/_sim/clock", {"advanceDays": giorni, "advanceHours": ore})


class TestOAuth2(MockTestBase):
    def test_token_con_form(self):
        st, b = self.call("POST", "/api/v4/oauth2/token",
                          form={"grant_type": "client_credentials", "client_id": CID, "client_secret": SEC})
        self.assertEqual(st, 200)
        self.assertEqual(b["token_type"], "BEARER")
        self.assertEqual(b["expires_in"], 43200)
        self.assertTrue(b["access_token"])

    def test_token_con_basic(self):
        basic = base64.b64encode(f"{CID}:{SEC}".encode()).decode()
        st, b = self.call("POST", "/api/v4/oauth2/token", form={"grant_type": "client_credentials"},
                          headers={"Authorization": f"Basic {basic}"})
        self.assertEqual(st, 200)

    def test_basic_e_form_insieme_400(self):
        basic = base64.b64encode(f"{CID}:{SEC}".encode()).decode()
        st, b = self.call("POST", "/api/v4/oauth2/token",
                          form={"grant_type": "client_credentials", "client_id": CID, "client_secret": SEC},
                          headers={"Authorization": f"Basic {basic}"})
        self.assertEqual(st, 400)
        self.assertEqual(b["httpStatusCode"], 400)
        self.assertIn("supportReferenceId", b)

    def test_grant_type_errato_400(self):
        st, _ = self.call("POST", "/api/v4/oauth2/token",
                          form={"grant_type": "password", "client_id": CID, "client_secret": SEC})
        self.assertEqual(st, 400)

    def test_content_type_json_400(self):
        st, _ = self.call("POST", "/api/v4/oauth2/token",
                          {"grant_type": "client_credentials", "client_id": CID, "client_secret": SEC})
        self.assertEqual(st, 400)

    def test_credenziali_errate_401(self):
        st, _ = self.call("POST", "/api/v4/oauth2/token",
                          form={"grant_type": "client_credentials", "client_id": CID, "client_secret": "x"})
        self.assertEqual(st, 401)

    def test_credenziali_mancanti_401(self):
        st, _ = self.call("POST", "/api/v4/oauth2/token", form={"grant_type": "client_credentials"})
        self.assertEqual(st, 401)

    def test_inviti_senza_token_401(self):
        st, b = self.call("POST", "/services/invitation/v1/invitations", payload())
        self.assertEqual(st, 401)
        st, _ = self.call("GET", "/services/invitation/v1/invitations",
                          headers={"Authorization": "Bearer inventato"})
        self.assertEqual(st, 401)

    def test_token_resta_valido_dopo_avanzamento_orologio(self):
        h = self.auth()
        self.avanza(giorni=40)
        st, _ = self.call("GET", "/services/invitation/v1/invitations", headers=h)
        self.assertEqual(st, 200)


class TestInviti(MockTestBase):
    def test_crea_invito_201(self):
        st, b = self.invita(payload())
        self.assertEqual(st, 201, b)
        self.assertEqual(set(b), {"capability", "invitee", "status", "createdDateTime", "lastModifiedDateTime"})
        self.assertEqual(b["status"], "IN_PROGRESS")
        self.assertEqual(b["capability"], "TRUCKLOAD_ASSET_TRACKING")
        self.assertEqual(b["createdDateTime"], b["lastModifiedDateTime"])
        self.assertEqual(parse(b["createdDateTime"]).date(), parse(T0).date())

    def test_locale_default_en_us(self):
        corpo = payload()
        del corpo["invitee"]["contacts"][0]["locale"]
        st, b = self.invita(corpo)
        self.assertEqual(st, 201)
        self.assertEqual(b["invitee"]["contacts"][0]["locale"], "en-US")

    def test_mail_eml_scritta(self):
        self.invita(payload())
        files = os.listdir(self.mail_dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith(".eml"))
        with open(os.path.join(self.mail_dir, files[0]), encoding="utf-8") as f:
            testo = f.read()
        self.assertIn("To: poc@esempio-vettore.test", testo)
        self.assertIn("Invito a collegarsi", testo)  # contatto it-IT

    def test_validazioni_400(self):
        casi = []
        c = payload(); c["capability"] = "LTL"; casi.append(c)
        c = payload(); c["invitee"]["identifiers"][0]["type"] = "PIVA"; casi.append(c)
        c = payload(); c["invitee"]["identifiers"] = []; casi.append(c)
        c = payload(); del c["invitee"]["organization"]; casi.append(c)
        c = payload(); c["invitee"]["contacts"][0]["email"] = "non-una-mail"; casi.append(c)
        c = payload(); del c["invitee"]["contacts"][0]["givenName"]; casi.append(c)
        casi.append(payload(locale="xx-XX"))
        for corpo in casi:
            with self.subTest(corpo=corpo):
                st, b = self.invita(corpo)
                self.assertEqual(st, 400)
                self.assertTrue(b["errors"])

    def test_json_non_valido_400(self):
        req = urllib.request.Request(self.base + "/services/invitation/v1/invitations", data=b"{x",
                                     headers={**self.auth(), "Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            apri(req, 5)
        self.assertEqual(cm.exception.code, 400)

    def test_duplicato_in_corso_409(self):
        self.assertEqual(self.invita(payload())[0], 201)
        st, b = self.invita(payload())
        self.assertEqual(st, 409)
        # stesso vettore con P.IVA in minuscolo/spazi: sempre duplicato
        self.assertEqual(self.invita(payload(vat=" it01234567890 "))[0], 409)

    def test_elenco_paginazione_e_filtri(self):
        for i in range(12):
            self.assertEqual(self.invita(payload(vat=f"IT{i:011d}"))[0], 201)
        st, b = self.elenco()
        self.assertEqual(st, 200)
        self.assertEqual(b["paginationInfo"], {"pageNumber": 1, "pageSize": 10, "total": 12})
        self.assertEqual(len(b["results"]), 10)
        st, b = self.elenco(pageNumber=2, pageSize=10)
        self.assertEqual(len(b["results"]), 2)
        st, b = self.elenco(**{"inviteeIdentifier.type": "VAT", "inviteeIdentifier.value": "IT00000000005"})
        self.assertEqual(b["paginationInfo"]["total"], 1)
        self.assertEqual(b["results"][0]["invitee"]["identifiers"][0]["value"], "IT00000000005")
        st, b = self.elenco(**{"inviteeIdentifier.type": "SCAC"})
        self.assertEqual(b["paginationInfo"]["total"], 0)
        st, b = self.elenco(capability="TRUCKLOAD_ASSET_TRACKING")
        self.assertEqual(b["paginationInfo"]["total"], 12)

    def test_parametri_elenco_non_validi_400(self):
        for q in ({"pageSize": 26}, {"pageNumber": 0}, {"pageSize": "abc"},
                  {"inviteeIdentifier.type": "PIVA"}, {"capability": "LTL"}):
            with self.subTest(q=q):
                self.assertEqual(self.elenco(**q)[0], 400)

    def test_404_e_405(self):
        self.assertEqual(self.call("GET", "/services/altro", headers=self.auth())[0], 404)
        self.assertEqual(self.call("DELETE", "/services/invitation/v1/invitations", headers=self.auth())[0], 405)
        self.assertEqual(self.call("GET", "/api/v4/oauth2/token")[0], 405)


class TestEvoluzioneStati(MockTestBase):
    """Scenari forzati via /_sim/reset; tempi: solleciti +2/+5 gg, EXPIRED a 30 gg."""

    MAPPA = {"IT00000000001": "ACCETTA_SUBITO", "IT00000000002": "ACCETTA_DOPO_SOLLECITO_1",
             "IT00000000003": "ACCETTA_DOPO_SOLLECITO_2", "IT00000000004": "RIFIUTA",
             "IT00000000005": "NESSUNA_RISPOSTA", "IT00000000006": "SCADE_POI_ACCETTA"}

    def setUp(self):
        super().setUp()
        self.sim("/_sim/reset", {"now": T0, "scenari": self.MAPPA})
        for vat in self.MAPPA:
            self.assertEqual(self.invita(payload(vat=vat))[0], 201)

    def stati(self):
        return {vat: self.stato(vat)[-1] for vat in self.MAPPA}

    def test_cronologia_scenari(self):
        attesi = {  # giorno virtuale -> stati attesi (ultimo invito per vettore)
            0: ["IN_PROGRESS"] * 6,
            1: ["ACCEPTED"] + ["IN_PROGRESS"] * 5,
            2: ["ACCEPTED"] + ["IN_PROGRESS"] * 5,  # giorno del 1° sollecito
            3: ["ACCEPTED", "ACCEPTED"] + ["IN_PROGRESS"] * 4,
            4: ["ACCEPTED", "ACCEPTED", "IN_PROGRESS", "DECLINED", "IN_PROGRESS", "IN_PROGRESS"],
            6: ["ACCEPTED", "ACCEPTED", "ACCEPTED", "DECLINED", "IN_PROGRESS", "IN_PROGRESS"],
            29: ["ACCEPTED", "ACCEPTED", "ACCEPTED", "DECLINED", "IN_PROGRESS", "IN_PROGRESS"],
            30: ["ACCEPTED", "ACCEPTED", "ACCEPTED", "DECLINED", "EXPIRED", "EXPIRED"],
        }
        giorno = 0
        for g, stati in attesi.items():
            self.avanza(giorni=g - giorno)
            giorno = g
            with self.subTest(giorno=g):
                self.assertEqual(list(self.stati().values()), stati)

    def test_last_modified_uguale_all_istante_di_transizione(self):
        self.avanza(giorni=10)
        _, b = self.elenco(**{"inviteeIdentifier.value": "IT00000000004"})
        inv = b["results"][0]
        delta = parse(inv["lastModifiedDateTime"]) - parse(inv["createdDateTime"])
        self.assertEqual(delta.days, 4)

    def test_reinvito_dopo_expired(self):
        self.avanza(giorni=30)
        # 2° invito: NESSUNA_RISPOSTA scade di nuovo, SCADE_POI_ACCETTA accetta a +2 gg
        for vat in ("IT00000000005", "IT00000000006"):
            st, b = self.invita(payload(vat=vat))
            self.assertEqual(st, 201)
            self.assertEqual(b["status"], "IN_PROGRESS")
        self.avanza(giorni=2)
        self.assertEqual(self.stato("IT00000000005"), ["EXPIRED", "IN_PROGRESS"])
        self.assertEqual(self.stato("IT00000000006"), ["EXPIRED", "ACCEPTED"])

    def test_reinvito_dopo_declined_ammesso(self):
        self.avanza(giorni=4)
        self.assertEqual(self.invita(payload(vat="IT00000000004"))[0], 201)

    def test_reset_svuota(self):
        self.sim("/_sim/reset", {})
        _, b = self.elenco()
        self.assertEqual(b["paginationInfo"]["total"], 0)
        # scenari forzati azzerati: torna l'assegnazione deterministica
        self.assertEqual(self.store._scenario_per([{"type": "VAT", "value": "IT00000000001"}]),
                         scenario_predefinito("IT00000000001"))


class TestOrologio(MockTestBase):
    def test_get_e_avanzamento(self):
        st, b = self.call("GET", "/_sim/clock")
        self.assertEqual(st, 200)
        t1 = parse(b["now"])
        self.assertLess(abs((t1 - parse(T0)).total_seconds()), 5)
        t2 = parse(self.avanza(giorni=2, ore=3)["now"])
        self.assertAlmostEqual((t2 - t1).total_seconds(), 2 * 86400 + 3 * 3600, delta=5)

    def test_set(self):
        b = self.sim("/_sim/clock", {"set": "2027-01-15T10:00:00Z"})
        self.assertEqual(parse(b["now"]).date().isoformat(), "2027-01-15")

    def test_errori_400(self):
        for corpo in ({}, {"advanceDays": -1}, {"advanceDays": "due"}, {"set": "ieri"}, {"advanceDays": True}):
            with self.subTest(corpo=corpo):
                self.assertEqual(self.call("POST", "/_sim/clock", corpo)[0], 400)

    def test_reset_scenario_sconosciuto_400(self):
        st, _ = self.call("POST", "/_sim/reset", {"scenari": {"IT1": "BOH"}})
        self.assertEqual(st, 400)

    def test_elenco_scenari(self):
        st, b = self.call("GET", "/_sim/scenari")
        self.assertEqual(st, 200)
        self.assertEqual(set(b), set(SCENARI))


class TestScenariUnit(unittest.TestCase):
    def test_assegnazione_deterministica(self):
        self.assertEqual(scenario_predefinito("IT01234567890"), scenario_predefinito(" it01234567890"))
        self.assertIn(scenario_predefinito("IT01234567890"), SCENARI)

    def test_esito_per_tentativo_ripete_ultimo(self):
        self.assertEqual(esito_per_tentativo("SCADE_POI_ACCETTA", 1), ("EXPIRED", 30))
        self.assertEqual(esito_per_tentativo("SCADE_POI_ACCETTA", 2), ("ACCEPTED", 2))
        self.assertEqual(esito_per_tentativo("SCADE_POI_ACCETTA", 5), ("ACCEPTED", 2))

    def test_store_persistente_su_file(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "mock.db")
            s = Store(db)
            s.imposta_orologio(datetime(2027, 3, 1, tzinfo=timezone.utc))
            s.chiudi()
            s = Store(db)
            self.assertEqual(s.adesso().date().isoformat(), "2027-03-01")
            s.chiudi()


if __name__ == "__main__":
    unittest.main()
