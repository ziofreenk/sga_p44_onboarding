"""Scenari di comportamento dei vettori simulati dal mock P44.

Ogni scenario è una lista di esiti, uno per tentativo di invito (1°, 2°, ...).
L'ultimo esito si ripete per i tentativi successivi.
Un esito è (stato_finale, giorni_dopo_la_creazione).

Tempi allineati alle decisioni approvate:
- solleciti FERCAM a +2 e +5 giorni dall'invito;
- scadenza invito (EXPIRED) dopo 30 giorni in IN_PROGRESS.
"""

import hashlib

GIORNI_SCADENZA = 30

SCENARI = {
    # Accetta prima del primo sollecito
    "ACCETTA_SUBITO": [("ACCEPTED", 1)],
    # Accetta dopo il 1° sollecito (+2 gg), prima del 2° (+5 gg)
    "ACCETTA_DOPO_SOLLECITO_1": [("ACCEPTED", 3)],
    # Accetta dopo il 2° sollecito
    "ACCETTA_DOPO_SOLLECITO_2": [("ACCEPTED", 6)],
    # Rifiuta l'invito
    "RIFIUTA": [("DECLINED", 4)],
    # Non risponde mai: ogni invito scade
    "NESSUNA_RISPOSTA": [("EXPIRED", GIORNI_SCADENZA)],
    # Il 1° invito scade, il nuovo invito viene accettato dopo 2 giorni
    "SCADE_POI_ACCETTA": [("EXPIRED", GIORNI_SCADENZA), ("ACCEPTED", 2)],
}

# Ordine stabile usato per l'assegnazione automatica (non cambiarlo: renderebbe
# non riproducibili le demo già registrate)
_ORDINE = sorted(SCENARI)


def scenario_predefinito(valore_identificativo: str) -> str:
    """Assegna uno scenario in modo deterministico dal valore dell'identificativo
    (es. partita IVA): stesso vettore → stesso scenario, a ogni avvio."""
    digest = hashlib.sha256(valore_identificativo.strip().upper().encode("utf-8")).digest()
    return _ORDINE[digest[0] % len(_ORDINE)]


def esito_per_tentativo(scenario: str, tentativo: int):
    """Restituisce (stato_finale, giorni) per il tentativo n (1-based)."""
    esiti = SCENARI[scenario]
    return esiti[min(tentativo, len(esiti)) - 1]
