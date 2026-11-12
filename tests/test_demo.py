"""Test end-to-end della demo (#7): 95 giorni virtuali col mock P44 + report finale.

Esiti attesi con 30 vettori (5 per scenario) e 2 KO:
  ACCETTA_SUBITO +1, DOPO_SOLLECITO_1 +3, DOPO_SOLLECITO_2 +6, SCADE_POI_ACCETTA re-invito +2 → 20 accettati;
  RIFIUTA → 5 rifiutati; NESSUNA_RISPOSTA scade a +30/+60/+90 → 5 a TENTATIVI_ESAURITI.
"""

import os
import tempfile
import unittest
from datetime import date

from src.onboarding import demo


def kpi(r, nome):
    return next(k["valore"] for k in r["kpi"] if k["kpi"] == nome)


class TestDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cartella = demo.prepara_cartella(os.path.join(cls.tmp.name, "run"))
        cls.r = demo.esegui_demo(cls.cartella, giorni=95, data_rif=date(2026, 11, 12), log=None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_funnel_atteso(self):
        f = self.r["funnel"]
        self.assertIsNone(self.r["interrotto"])
        self.assertEqual(self.r["invitati"], 30)
        self.assertEqual((f["ACCETTATI"], f["RIFIUTATI"], f["TENTATIVI_ESAURITI"], f["IN_CORSO"]), (20, 5, 5, 0))
        self.assertEqual(kpi(self.r, "Tasso di accettazione"), 66.7)
        self.assertEqual(kpi(self.r, "Righe CSV scartate"), 2)

    def test_solleciti_inviti_tempi(self):
        self.assertEqual(kpi(self.r, "Solleciti 1 inviati (+2 gg)"), 35)
        self.assertEqual(kpi(self.r, "Solleciti 2 inviati (+5 gg)"), 25)
        self.assertEqual(kpi(self.r, "Re-inviti inviati (dopo EXPIRED)"), 15)
        self.assertEqual(kpi(self.r, "Inviti scaduti (EXPIRED)"), 20)
        self.assertEqual(kpi(self.r, "Cicli completati"), 96)
        c = self.r["accettati_per_categoria"]
        self.assertEqual([c[k] for k in ("senza sollecito", "dopo S1", "dopo S2", "re-invito")], [5] * 4)
        self.assertEqual(kpi(self.r, "Tempo di accettazione dall'invito del tentativo - mediana"), 2.5)
        self.assertEqual(kpi(self.r, "Tempo di accettazione dal primo invito - max"), 32.0)

    def test_file_prodotti_e_anomalie(self):
        for nome in ("eventi.csv", "stato_vettori.csv", "vettori_fittizi.csv", "scenari.json",
                     os.path.join("report", "report_kpi.md"), os.path.join("report", "kpi.csv"),
                     os.path.join("report", "anomalie.csv")):
            self.assertTrue(os.path.isfile(os.path.join(self.cartella, nome)), nome)
        self.assertEqual(len(os.listdir(os.path.join(self.cartella, "solleciti"))), 60)
        tipi = [a["tipo"] for a in self.r["anomalie"]]
        self.assertEqual((tipi.count("TENTATIVI_ESAURITI"), tipi.count("RIFIUTATO"), tipi.count("SCARTO_CSV")),
                         (5, 5, 2))

    def test_cartella_non_vuota_rifiutata(self):
        with self.assertRaisesRegex(ValueError, "non è vuota"):
            demo.prepara_cartella(self.cartella)


if __name__ == "__main__":
    unittest.main()
