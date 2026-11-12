"""Test dell'orchestratore (#6) contro il mock P44 reale su porta effimera.

Simula 36 giorni virtuali con un ciclo al giorno e verifica, per ciascuno dei 6 scenari,
inviti, solleciti +2/+5, re-invito dopo EXPIRED e stato finale.
"""

import csv
import email
import os
import tempfile
import threading
import unittest
import urllib.request
import json
from collections import Counter
from datetime import date

from src.onboarding import genera_dati_fittizi as gen
from src.onboarding import tracciato
from src.onboarding.orchestratore import ErroreSistemico, Orchestratore, invitee_da_riga, leggi_vettori
from src.onboarding.p44_client import ClientP44, OrologioMock
from src.onboarding.registro import Registro
from src.p44_mock.server import MockP44Server
from src.p44_mock.store import Store

CID, SEC = "test-client", "test-secret"
T0 = "2026-12-01T08:00:00Z"


class BaseOrchestratore(unittest.TestCase):
    N, KO = 30, 2

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        righe, self.scenari = gen.genera_vettori(self.N, seed=44, data_rif=date(2026, 11, 12), ko=self.KO)
        self.righe = righe
        self.csv = os.path.join(self.dir, "vettori.csv")
        gen.scrivi_csv(self.csv, righe)
        self.store = Store(":memory:", self.scenari)
        self.srv = MockP44Server(("127.0.0.1", 0), self.store, CID, SEC, None, log=False)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self._sim("/_sim/reset", {"now": T0})
        self.reg = Registro(":memory:")
        self.out = os.path.join(self.dir, "output")
        self.orch = self._orchestratore()

    def tearDown(self):
        self.reg.chiudi()
        self.srv.shutdown()
        self.srv.server_close()
        self.store.chiudi()
        self.tmp.cleanup()

    def _orchestratore(self, cid=CID, sec=SEC, **kw):
        client = ClientP44(self.base, cid, sec, timeout=5, tentativi_rete=1, pausa_retry=0)
        return Orchestratore(client, self.reg, OrologioMock(self.base), self.out, log=None, **kw)

    def _sim(self, path, corpo):
        req = urllib.request.Request(self.base + path, json.dumps(corpo).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def avanza(self, giorni):
        self._sim("/_sim/clock", {"advanceDays": giorni})

    def simula(self, giorni, orch=None):
        """Ciclo al giorno 0, poi uno al giorno per 'giorni' giorni."""
        orch = orch or self.orch
        orch.esegui_ciclo(self.csv)
        for _ in range(giorni):
            self.avanza(1)
            orch.esegui_ciclo(self.csv)

    def vat_per_scenario(self, scenario):
        return [v for v, s in self.scenari.items() if s == scenario]

    def tipi(self, vat):
        return Counter(e["tipo"] for e in self.reg.eventi(vat=vat))


class TestLetturaCsv(BaseOrchestratore):
    def test_solo_ok_e_scarti(self):
        ok, scarti = leggi_vettori(self.csv)
        self.assertEqual(len(ok), self.N)
        self.assertEqual(len(scarti), self.KO)
        self.assertTrue(all("KO_MANCA_EMAIL" in m for _, m in scarti))

    def test_tracciato_non_conforme(self):
        p = os.path.join(self.dir, "errato.csv")
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("A;B\n1;2\n")
        with self.assertRaises(ValueError):
            leggi_vettori(p)

    def test_vat_duplicata_scartata(self):
        righe = [dict(r) for r in self.righe]
        dup = dict(next(r for r in righe if r["ESITO_CONTROLLO"] == "OK"))
        dup["CODICE_VETTORE"] = "999999"
        righe.append(dup)
        gen.scrivi_csv(self.csv, righe)
        ok, scarti = leggi_vettori(self.csv)
        self.assertEqual(len(ok), self.N)
        self.assertTrue(any("duplicata" in m for _, m in scarti))

    def test_invitee_conforme_al_contratto(self):
        ok, _ = leggi_vettori(self.csv)
        default = next(r for r in ok if r["POC_NOMINATIVO_DEFAULT"] == "S")
        inv = invitee_da_riga(default)
        self.assertEqual(inv["identifiers"], [{"type": "VAT", "value": default["VAT_P44"]}])
        self.assertEqual(inv["contacts"][0]["givenName"], tracciato.NOMINATIVO_DEFAULT)
        self.assertNotIn("familyName", inv["contacts"][0])


class TestCicloCompleto(BaseOrchestratore):
    """36 giorni virtuali, max 3 tentativi."""

    @classmethod
    def setUpClass(cls):
        cls.atteso = {
            # scenario: (stato finale, tentativi, n. solleciti)
            "ACCETTA_SUBITO": ("ACCEPTED", 1, 0),
            "ACCETTA_DOPO_SOLLECITO_1": ("ACCEPTED", 1, 1),
            "ACCETTA_DOPO_SOLLECITO_2": ("ACCEPTED", 1, 2),
            "RIFIUTA": ("DECLINED", 1, 1),
            "NESSUNA_RISPOSTA": ("IN_PROGRESS", 2, 4),     # re-invito a +30, solleciti a +32 e +35
            "SCADE_POI_ACCETTA": ("ACCEPTED", 2, 2),
        }

    def test_scenari_su_36_giorni(self):
        self.simula(35)
        for scenario, (stato, tentativi, n_soll) in self.atteso.items():
            for vat in self.vat_per_scenario(scenario):
                with self.subTest(scenario=scenario, vat=vat):
                    rec = self.reg.vettore(vat)
                    t = self.tipi(vat)
                    self.assertEqual(rec["stato"], stato)
                    self.assertEqual(rec["tentativi"], tentativi)
                    self.assertEqual(t["SOLLECITO_1"] + t["SOLLECITO_2"], n_soll)
                    self.assertEqual(t["INVITO_INVIATO"], 1)
                    self.assertEqual(t["REINVITO_INVIATO"], tentativi - 1)
                    self.assertEqual(t["ERRORE_API"], 0)
        # file prodotti
        n_eml = len(os.listdir(os.path.join(self.out, "solleciti")))
        self.assertEqual(n_eml, sum(n * 5 for _, _, n in self.atteso.values()))
        for nome in ("eventi.csv", "stato_vettori.csv"):
            with open(os.path.join(self.out, nome), encoding="utf-8-sig") as f:
                self.assertGreater(len(list(csv.reader(f, delimiter=";"))), self.N)

    def test_tempi_solleciti(self):
        self.simula(6)
        vat = self.vat_per_scenario("ACCETTA_DOPO_SOLLECITO_2")[0]
        ev = {e["tipo"]: e["istante_logico"][:10] for e in self.reg.eventi(vat=vat)}
        self.assertEqual(ev["INVITO_INVIATO"], "2026-12-01")
        self.assertEqual(ev["SOLLECITO_1"], "2026-12-03")
        self.assertEqual(ev["SOLLECITO_2"], "2026-12-06")
        self.assertEqual(ev["STATO_ACCEPTED"], "2026-12-07")


class TestComportamenti(BaseOrchestratore):
    def test_idempotenza_stesso_giorno(self):
        self.orch.esegui_ciclo(self.csv)
        prima = len(self.reg.eventi())
        c = self.orch.esegui_ciclo(self.csv)
        self.assertEqual((c["inviti"], c["solleciti"], c["reinviti"]), (0, 0, 0))
        nuovi = [e["tipo"] for e in self.reg.eventi()][prima:]
        self.assertEqual(nuovi, ["CICLO_INIZIO", "CICLO_FINE"])
        self.assertEqual(len(self.reg.eventi(tipo="SCARTATO")), self.KO)   # scarti loggati una volta

    def test_ciclo_in_ritardo_solo_sollecito_2(self):
        self.orch.esegui_ciclo(self.csv)
        self.avanza(6)
        self.orch.esegui_ciclo(self.csv)
        vat = self.vat_per_scenario("NESSUNA_RISPOSTA")[0]
        t = self.tipi(vat)
        self.assertEqual((t["SOLLECITO_1"], t["SOLLECITO_2"]), (0, 1))
        self.assertIn("ritardo", self.reg.eventi(vat=vat, tipo="SOLLECITO_2")[0]["dettaglio"])

    def test_tentativi_esauriti(self):
        orch = self._orchestratore(max_tentativi=1)
        orch.esegui_ciclo(self.csv)
        self.avanza(30)
        orch.esegui_ciclo(self.csv)
        orch.esegui_ciclo(self.csv)
        for vat in self.vat_per_scenario("NESSUNA_RISPOSTA"):
            t = self.tipi(vat)
            self.assertEqual(t["TENTATIVI_ESAURITI"], 1)
            self.assertEqual(t["REINVITO_INVIATO"], 0)
            self.assertEqual(self.reg.vettore(vat)["stato"], "EXPIRED")

    def test_invito_gia_presente_adottato(self):
        ok, _ = leggi_vettori(self.csv)
        client = ClientP44(self.base, CID, SEC, tentativi_rete=1)
        client.crea_invito(invitee_da_riga(ok[0]))
        c = self.orch.esegui_ciclo(self.csv)
        self.assertEqual(c["inviti"], self.N - 1)
        self.assertEqual(self.tipi(ok[0]["VAT_P44"])["INVITO_GIA_PRESENTE"], 1)
        self.assertEqual(len(client.inviti_per_identificativo(ok[0]["VAT_P44"])), 1)

    def test_credenziali_errate_interrompono_il_ciclo(self):
        orch = self._orchestratore(sec="sbagliato")
        with self.assertRaises(ErroreSistemico):
            orch.esegui_ciclo(self.csv)
        self.assertEqual(len(self.reg.eventi(tipo="CICLO_INTERROTTO")), 1)
        self.assertEqual(len(self.reg.eventi(tipo="INVITO_INVIATO")), 0)

    def test_mail_sollecito(self):
        self.orch.esegui_ciclo(self.csv)
        self.avanza(2)
        self.orch.esegui_ciclo(self.csv)
        cartella = os.path.join(self.out, "solleciti")
        file_ = sorted(os.listdir(cartella))
        self.assertTrue(file_)
        with open(os.path.join(cartella, file_[0]), "rb") as f:
            msg = email.message_from_bytes(f.read())
        self.assertIn("francesco.orlando@fercam.com", msg["From"])
        self.assertIn("francesco.orlando@fercam.com", msg["Reply-To"])
        self.assertTrue(msg["To"].endswith(".test"))
        self.assertIn("1", msg["Subject"])


if __name__ == "__main__":
    unittest.main()
