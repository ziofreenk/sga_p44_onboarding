"""Test del generatore di vettori fittizi (#5).

Esecuzione (dalla radice del repo):
    python -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta

from src.onboarding import genera_dati_fittizi as gen
from src.onboarding.tracciato import COLONNE, ENCODING, NOMINATIVO_DEFAULT, locale_per_nazione
from src.p44_mock.scenari import SCENARI
from src.p44_mock.store import Store

DATA_RIF = date(2026, 11, 12)
# Colonne della SELECT finale di sql/01_vettori_inviti_p44.sql, nell'ordine della query
COLONNE_QUERY = [
    "SOCIETA", "CODICE_VETTORE", "RAGIONE_SOCIALE", "NAZIONE", "PARTITA_IVA", "VAT_P44",
    "CODICE_FISCALE", "POC_EMAIL", "POC_NOMINATIVO", "POC_NOMINATIVO_DEFAULT", "POC_NOME",
    "POC_COGNOME", "POC_TELEFONO", "POC_LOCALE", "POC_FONTE", "N_VIAGGI", "ULTIMO_VIAGGIO",
    "N_REPARTI_FMI", "ESITO_CONTROLLO",
]
RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestTracciato(unittest.TestCase):
    def test_colonne_come_query(self):
        self.assertEqual(COLONNE, COLONNE_QUERY)

    def test_colonne_presenti_nella_query_sql(self):
        # verifica incrociata sul file SQL: ogni colonna compare come alias nella SELECT finale
        with open(os.path.join(RADICE, "sql", "01_vettori_inviti_p44.sql"), encoding="utf-8") as f:
            select_finale = f.read().split("4. Output")[1]
        select_finale = select_finale.split("FROM    Base")[0]
        trovate = set(re.findall(r"\bAS\s+([A-Z_0-9]+)", select_finale))          # alias espliciti
        trovate |= set(re.findall(r"^\s*(?:SELECT\s+)?b\.([A-Z_0-9]+),?\s*$", select_finale, re.M))  # b.COL
        for col in COLONNE:
            self.assertIn(col, trovate, col)

    def test_locale(self):
        self.assertEqual(locale_per_nazione("AT"), "de-DE")
        self.assertEqual(locale_per_nazione("xx"), "en-US")
        self.assertEqual(locale_per_nazione(None), "en-US")


class TestPartitaIva(unittest.TestCase):
    def test_piva_generate_valide(self):
        import random
        rnd = random.Random(1)
        for _ in range(500):
            self.assertTrue(gen.piva_valida(gen.piva_italiana(rnd)))

    def test_piva_valida_casi_noti(self):
        self.assertTrue(gen.piva_valida("00098090210"))     # P.IVA FERCAM (cifra di controllo corretta)
        self.assertFalse(gen.piva_valida("00098090211"))
        self.assertFalse(gen.piva_valida("1234"))
        self.assertFalse(gen.piva_valida("0009809021A"))


class TestGeneratore(unittest.TestCase):
    def setUp(self):
        self.righe, self.scenari = gen.genera_vettori(30, 44, DATA_RIF, ko=2)
        self.ok = [r for r in self.righe if r["ESITO_CONTROLLO"] == "OK"]
        self.ko = [r for r in self.righe if r["ESITO_CONTROLLO"] != "OK"]

    def test_conteggi(self):
        self.assertEqual(len(self.righe), 32)
        self.assertEqual(len(self.ok), 30)
        self.assertEqual(len(self.ko), 2)
        self.assertEqual(len(self.scenari), 30)

    def test_tutti_gli_scenari_coperti(self):
        self.assertEqual(set(self.scenari.values()), set(SCENARI))
        for s in SCENARI:   # 30 vettori / 6 scenari => 5 ciascuno
            self.assertEqual(list(self.scenari.values()).count(s), 5)

    def test_copertura_con_minimo(self):
        _, scenari = gen.genera_vettori(6, 1, DATA_RIF)
        self.assertEqual(set(scenari.values()), set(SCENARI))

    def test_n_insufficiente(self):
        with self.assertRaises(ValueError):
            gen.genera_vettori(5, 1, DATA_RIF)
        with self.assertRaises(ValueError):
            gen.genera_vettori(6, 1, DATA_RIF, ko=-1)

    def test_scenari_solo_righe_ok(self):
        self.assertEqual(set(self.scenari), {r["VAT_P44"] for r in self.ok})
        for r in self.ko:
            self.assertNotIn(r["VAT_P44"], self.scenari)
            self.assertEqual(r["POC_EMAIL"], "")
            self.assertEqual(r["ESITO_CONTROLLO"], "KO_MANCA_EMAIL")

    def test_identificativi_unici_e_coerenti(self):
        vat = [r["VAT_P44"] for r in self.righe]
        self.assertEqual(len(vat), len(set(vat)))
        codici = [r["CODICE_VETTORE"] for r in self.righe]
        self.assertEqual(len(codici), len(set(codici)))
        for r in self.righe:
            self.assertEqual(r["VAT_P44"], r["NAZIONE"] + r["PARTITA_IVA"])  # regola CASE della query
            if r["NAZIONE"] == "IT":
                self.assertTrue(gen.piva_valida(r["PARTITA_IVA"]), r["PARTITA_IVA"])
                self.assertEqual(r["CODICE_FISCALE"], r["PARTITA_IVA"])
            self.assertEqual(r["POC_LOCALE"], locale_per_nazione(r["NAZIONE"]))
            self.assertEqual(r["SOCIETA"], 1)

    def test_vettori_esteri_presenti(self):
        self.assertEqual({r["NAZIONE"] for r in self.righe}, {"IT", "DE", "AT", "PL"})

    def test_nominativo_default(self):
        default = [r for r in self.righe if r["POC_NOMINATIVO_DEFAULT"] == "S"]
        self.assertTrue(default)
        self.assertTrue([r for r in self.righe if r["POC_NOMINATIVO_DEFAULT"] == "N"])
        for r in default:
            self.assertEqual(r["POC_NOMINATIVO"], NOMINATIVO_DEFAULT)
            self.assertEqual(r["POC_NOME"], NOMINATIVO_DEFAULT)   # givenName obbligatorio per P44
            self.assertEqual(r["POC_COGNOME"], "")
        for r in self.righe:
            if r["POC_NOMINATIVO_DEFAULT"] == "N":
                self.assertEqual(r["POC_NOMINATIVO"], f'{r["POC_NOME"]} {r["POC_COGNOME"]}')

    def test_dati_inventati(self):
        for r in self.ok:
            self.assertRegex(r["POC_EMAIL"], r"^[a-z0-9.]+@[a-z0-9]+\.test$")   # dominio riservato RFC 2606
            self.assertIn(r["POC_FONTE"], ("INTERLOCUTORE", "TESTATA_VETTORE", "ANAGRAFICA_FORNITORE"))
        for r in self.righe:
            self.assertRegex(r["POC_TELEFONO"], r"^\+\d{2}000\d{7}$")
            self.assertGreaterEqual(r["CODICE_VETTORE"], 900001)

    def test_periodo_e_contatori(self):
        for r in self.righe:
            ultimo = datetime.strptime(r["ULTIMO_VIAGGIO"], "%Y-%m-%d %H:%M:%S").date()
            self.assertLess(ultimo, DATA_RIF)                                # @DataA escluso
            self.assertGreaterEqual(ultimo, DATA_RIF - timedelta(days=92))   # ultimi 3 mesi
            self.assertGreaterEqual(r["N_VIAGGI"], 1)
            self.assertTrue(1 <= r["N_REPARTI_FMI"] <= len(gen.REPARTI_FMI))

    def test_ordinamento_come_query(self):
        chiavi = [(-r["N_VIAGGI"], r["RAGIONE_SOCIALE"]) for r in self.righe]
        self.assertEqual(chiavi, sorted(chiavi))

    def test_riproducibile(self):
        self.assertEqual(gen.genera_vettori(30, 44, DATA_RIF, ko=2), (self.righe, self.scenari))
        self.assertNotEqual(gen.genera_vettori(30, 45, DATA_RIF, ko=2)[0], self.righe)


class TestFileEMock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = os.path.join(self.tmp.name, "out", "vettori.csv")
        self.json = os.path.join(self.tmp.name, "out", "scenari.json")
        with contextlib.redirect_stdout(io.StringIO()):
            gen.main(["--n", "12", "--ko", "1", "--seed", "7", "--data-rif", "2026-11-12",
                      "--csv", self.csv, "--scenari", self.json])

    def tearDown(self):
        self.tmp.cleanup()

    def test_csv_tracciato_e_formato(self):
        with open(self.csv, "rb") as f:
            grezzo = f.read()
        self.assertTrue(grezzo.startswith(b"\xef\xbb\xbf"))           # UTF-8 con BOM
        intestazione = grezzo.decode(ENCODING).splitlines()[0]
        self.assertEqual(intestazione, ";".join(COLONNE))
        righe = gen.leggi_csv(self.csv)
        self.assertEqual(len(righe), 13)
        self.assertEqual(list(righe[0]), COLONNE)

    def test_scenari_json_caricato_dal_mock(self):
        with open(self.json, encoding="utf-8") as f:
            mappa = json.load(f)
        self.assertEqual(len(mappa), 12)
        self.assertEqual(set(mappa.values()), set(SCENARI))
        # stesso caricamento di "python -m src.p44_mock --scenari": nessun errore, scenario forzato
        store = Store(":memory:", mappa)
        for vat, scenario in mappa.items():
            self.assertEqual(store._scenario_per([{"type": "VAT", "value": vat}]), scenario)

    def test_cli_n_insufficiente(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            gen.main(["--n", "3", "--csv", self.csv, "--scenari", self.json])


if __name__ == "__main__":
    unittest.main()
