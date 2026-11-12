"""Test del report KPI/anomalie (#7) su eventi costruiti a mano (nessun mock HTTP)."""

import csv
import os
import tempfile
import unittest
from datetime import datetime, timezone

from src.onboarding import report_kpi as rk
from src.onboarding.registro import COLONNE_EVENTI, COLONNE_STATO

RIF = datetime(2026, 12, 20, 7, 0, tzinfo=timezone.utc)


def ev(giorno, tipo, vat="", tent="", det="", codice="", ragione=""):
    """Evento come riga di eventi.csv; giorno = giorno di dicembre 2026 del ciclo (07:00Z)."""
    r = dict.fromkeys(COLONNE_EVENTI, "")
    r.update(istante_logico=f"2026-12-{giorno:02d}T07:00:00.000Z", istante_reale="2026-11-12T08:00:00.000Z",
             vat=vat, codice_vettore=codice or (f"C{vat}" if vat else ""), ragione_sociale=ragione or vat,
             tipo=tipo, tentativo=str(tent), dettaglio=det)
    return r


def st(vat, stato, tentativi=1, esaurito=0, creato="", s1="", s2="", ctrl="2026-12-20T07:00:00.000Z"):
    r = dict.fromkeys(COLONNE_STATO, "")
    r.update(vat=vat, codice_vettore=f"C{vat}", ragione_sociale=vat, email=f"{vat.lower()}@x.test",
             stato=stato, tentativi=str(tentativi), esaurito=str(esaurito), invito_creato=creato,
             sollecito1=s1, sollecito2=s2, ultimo_controllo=ctrl)
    return r


def creato(g, ora="07:00:00"):
    return f"2026-12-{g:02d}T{ora}.000Z"


def invito(g, vat, n=1):
    tipo = "INVITO_INVIATO" if n == 1 else "REINVITO_INVIATO"
    return ev(g, tipo, vat, n, f"a x@x.test; creato={creato(g)}")


def esito(g, vat, stato, n=1, ts=None):
    det = f"IN_PROGRESS -> {stato}" + (f" il {ts}" if ts is not False else "")
    if ts is None:
        det = f"IN_PROGRESS -> {stato} il {creato(g, '06:00:00')}"
    return ev(g, f"STATO_{stato}", vat, n, det)


def kpi(analisi, nome):
    return next(k["valore"] for k in analisi["kpi"] if k["kpi"] == nome)


def tipi_anomalie(analisi):
    return sorted(a["tipo"] for a in analisi["anomalie"])


class TestAnalisi(unittest.TestCase):
    def setUp(self):
        # A: accetta senza sollecito (+1 gg, esito alle 06:00 → 0,96 gg)
        # B: accetta dopo S1 e S2 (+6)
        # C: scade (+30... compresso), re-invito accettato in 2 gg
        # D: rifiuta a +4 dopo S1
        # E: in corso da 3 giorni con S1
        self.eventi = [
            ev(1, "CICLO_INIZIO"), invito(1, "A"), invito(1, "B"), invito(1, "D"),
            ev(1, "SCARTATO", "", "", "ESITO_CONTROLLO=KO_MANCA_EMAIL", codice="K1", ragione="Ko Srl"),
            ev(1, "SCARTATO", "IT1", "", "VAT_P44 IT1 duplicata nel CSV (già presente su altro codice vettore)",
               codice="K2"),
            ev(1, "CICLO_FINE"),
            esito(2, "A", "ACCEPTED"),
            ev(3, "SOLLECITO_1", "B", 1), ev(3, "SOLLECITO_1", "D", 1),
            esito(5, "D", "DECLINED"),
            ev(6, "SOLLECITO_2", "B", 1),
            esito(7, "B", "ACCEPTED"),
            invito(2, "C"), esito(10, "C", "EXPIRED"), invito(10, "C", 2), esito(12, "C", "ACCEPTED", 2),
            invito(17, "E"), ev(19, "SOLLECITO_1", "E", 1),
        ]
        self.stato = [st("A", "ACCEPTED"), st("B", "ACCEPTED", s1="x", s2="x"), st("C", "ACCEPTED", 2),
                      st("D", "DECLINED", s1="x"), st("E", "IN_PROGRESS", creato=creato(17), s1="x")]
        self.a = rk.analizza(self.eventi, self.stato, RIF)

    def test_funnel_e_tassi(self):
        f = self.a["funnel"]
        self.assertEqual((f["ACCETTATI"], f["RIFIUTATI"], f["IN_CORSO"]), (3, 1, 1))
        self.assertEqual(kpi(self.a, "Tasso di accettazione"), 60.0)
        self.assertEqual(kpi(self.a, "Tasso di accettazione al 1° invito"), 40.0)
        self.assertEqual(kpi(self.a, "Tasso di accettazione su re-invito"), 100.0)
        self.assertEqual(kpi(self.a, "Tasso di risposta (accettati + rifiutati)"), 80.0)

    def test_efficacia_solleciti(self):
        c = self.a["accettati_per_categoria"]
        self.assertEqual((c["senza sollecito"], c["dopo S1"], c["dopo S2"], c["re-invito"]), (1, 0, 1, 1))
        # solleciti di A=0, B=2, C=0 → 2/3
        self.assertEqual(kpi(self.a, "Solleciti medi per vettore accettato"), 0.67)

    def test_tempi_dal_tentativo_e_dal_primo_invito(self):
        t = self.a["tempi"]["ACCEPTED"]
        # dal tentativo: A 23h = 0,958; B 5,958; C (re-invito g10 → esito g12 06:00) 1,958
        self.assertAlmostEqual(t["tentativo"]["media"], (0.958333 + 5.958333 + 1.958333) / 3, places=4)
        self.assertAlmostEqual(t["tentativo"]["max"], 5.958333, places=4)
        # dal primo invito: C dal g2 → g12 06:00 = 9,958
        self.assertAlmostEqual(t["primo"]["max"], 9.958333, places=4)
        self.assertEqual(self.a["tempi"]["DECLINED"]["tentativo"]["n"], 1)

    def test_fallback_data_ciclo_se_manca_lastmodified(self):
        eventi = [invito(1, "A"), ev(4, "STATO_ACCEPTED", "A", 1, "IN_PROGRESS -> ACCEPTED")]
        a = rk.analizza(eventi, [st("A", "ACCEPTED")], RIF)
        self.assertAlmostEqual(a["tempi"]["ACCEPTED"]["tentativo"]["media"], 3.0)

    def test_scarti_per_motivo(self):
        self.assertEqual(kpi(self.a, "Righe CSV scartate"), 2)
        self.assertEqual(kpi(self.a, "Scarti: VAT_P44 duplicata"), 1)
        self.assertEqual(kpi(self.a, "Scarti: ESITO_CONTROLLO=KO_MANCA_EMAIL"), 1)

    def test_conteggi_solleciti_inviti(self):
        self.assertEqual(kpi(self.a, "Solleciti 1 inviati (+2 gg)"), 3)
        self.assertEqual(kpi(self.a, "Solleciti 2 inviati (+5 gg)"), 1)
        self.assertEqual(kpi(self.a, "Primi inviti inviati"), 5)
        self.assertEqual(kpi(self.a, "Re-inviti inviati (dopo EXPIRED)"), 1)
        self.assertEqual(kpi(self.a, "Inviti scaduti (EXPIRED)"), 1)

    def test_anomalie_base(self):
        self.assertEqual(tipi_anomalie(self.a), ["RIFIUTATO", "SCARTO_CSV", "SCARTO_CSV"])
        self.assertTrue(all(a["azione_suggerita"] for a in self.a["anomalie"]))

    def test_anomalie_operative(self):
        eventi = [ev(1, "ERRORE_API", "A", "", "HTTP 400"), ev(2, "CICLO_INTERROTTO", det="HTTP 401"),
                  ev(8, "SOLLECITO_2", "B", 1, "+7 gg; x.eml; sollecito 1 non inviato (ciclo in ritardo)")]
        stato = [st("A", "EXPIRED", 3, esaurito=1),
                 st("B", "IN_PROGRESS", creato=creato(1), s2="x"),
                 st("C", "IN_PROGRESS", creato=creato(10), s1="x"),                 # +10 gg senza S2
                 st("D", "CANCELLED"),
                 st("E", "ACCEPTED", ctrl="2026-12-15T07:00:00.000Z"),              # non controllato
                 st("F", "EXPIRED", 2)]                                              # in attesa re-invito
        a = rk.analizza(eventi, stato, RIF)
        self.assertEqual(tipi_anomalie(a), sorted(["ERRORE_API", "CICLO_INTERROTTO", "SOLLECITO_1_SALTATO",
                                                   "TENTATIVI_ESAURITI", "SOLLECITO_2_MANCANTE", "ANNULLATO",
                                                   "NON_CONTROLLATO"]))
        self.assertEqual([x["gravita"] for x in a["anomalie"]][:3], ["ALTA"] * 3)
        self.assertEqual(a["funnel"]["SCADUTI_IN_ATTESA"], 1)
        self.assertEqual(a["funnel"]["TENTATIVI_ESAURITI"], 1)
        self.assertEqual(kpi(a, "Solleciti 2 senza sollecito 1 (ciclo in ritardo)"), 1)

    def test_nessun_invitato_niente_divisioni_per_zero(self):
        a = rk.analizza([ev(1, "CICLO_INIZIO"), ev(1, "CICLO_FINE")], [], RIF)
        self.assertIsNone(kpi(a, "Tasso di accettazione"))
        self.assertIsNone(kpi(a, "Tempo di accettazione dal primo invito - media"))
        self.assertIn("n.d.", rk.rendi_markdown(a))


class TestFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _scrivi(self, nome, colonne, righe):
        with open(os.path.join(self.dir, nome), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=colonne, delimiter=";")
            w.writeheader()
            w.writerows(righe)

    def test_genera_i_tre_file(self):
        self._scrivi("eventi.csv", COLONNE_EVENTI, [invito(1, "A"), esito(3, "A", "DECLINED")])
        self._scrivi("stato_vettori.csv", COLONNE_STATO, [st("A", "DECLINED")])
        r = rk.genera_report(self.dir, data_rif=RIF)
        for nome in ("report_kpi.md", "kpi.csv", "anomalie.csv"):
            self.assertTrue(os.path.isfile(os.path.join(self.dir, "report", nome)))
        with open(r["file"]["kpi.csv"], "rb") as f:
            self.assertTrue(f.read().startswith(b"\xef\xbb\xbfarea;kpi;valore;unita"))
        with open(r["file"]["kpi.csv"], encoding="utf-8-sig") as f:
            righe = {x["kpi"]: x["valore"] for x in csv.DictReader(f, delimiter=";")}
        self.assertEqual(righe["Tasso di rifiuto"], "100,0")       # decimali con virgola (Excel IT)
        with open(r["file"]["anomalie.csv"], encoding="utf-8-sig") as f:
            an = list(csv.DictReader(f, delimiter=";"))
        self.assertEqual(an[0]["tipo"], "RIFIUTATO")
        with open(r["file"]["report_kpi.md"], encoding="utf-8") as f:
            md = f.read()
        self.assertIn("## Funnel", md)
        self.assertIn("RIFIUTATO", md)

    def test_colonne_mancanti(self):
        self._scrivi("eventi.csv", ["id", "tipo"], [])
        self._scrivi("stato_vettori.csv", COLONNE_STATO, [])
        with self.assertRaisesRegex(ValueError, "colonne mancanti"):
            rk.genera_report(self.dir)

    def test_cli_file_assente(self):
        self.assertEqual(rk.main(["--input", os.path.join(self.dir, "non_esiste")]), 1)


if __name__ == "__main__":
    unittest.main()
