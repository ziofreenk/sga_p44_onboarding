"""Tracciato del CSV vettori: identico all'output di sql/01_vettori_inviti_p44.sql.

Usato sia dal generatore di dati fittizi sia dall'orchestratore, così il passaggio
dai dati fittizi all'estrazione SGA reale non cambia il codice.
Formato file (come lo strumento sga_esporta_csv): separatore ';', UTF-8 con BOM.
"""

COLONNE = [
    "SOCIETA",
    "CODICE_VETTORE",
    "RAGIONE_SOCIALE",
    "NAZIONE",
    "PARTITA_IVA",
    "VAT_P44",                 # identificativo VAT inviato a P44 (prefisso paese + P.IVA)
    "CODICE_FISCALE",
    "POC_EMAIL",
    "POC_NOMINATIVO",
    "POC_NOMINATIVO_DEFAULT",  # S = nominativo assente in SGA, usato "Ufficio Traffico"
    "POC_NOME",                # -> contacts[].givenName
    "POC_COGNOME",             # -> contacts[].familyName
    "POC_TELEFONO",
    "POC_LOCALE",              # -> contacts[].locale
    "POC_FONTE",               # INTERLOCUTORE | TESTATA_VETTORE | ANAGRAFICA_FORNITORE
    "N_VIAGGI",
    "ULTIMO_VIAGGIO",
    "N_REPARTI_FMI",
    "ESITO_CONTROLLO",         # OK | KO_MANCA_EMAIL: si invitano solo le righe OK
]

SEPARATORE = ";"
ENCODING = "utf-8-sig"
NOMINATIVO_DEFAULT = "Ufficio Traffico"

# Lingua del contatto per nazione: stessa mappa della CASE nella query SGA
LOCALE_PER_NAZIONE = {
    "IT": "it-IT", "DE": "de-DE", "AT": "de-DE", "FR": "fr-FR", "ES": "es-ES", "PL": "pl-PL",
    "CZ": "cs-CZ", "HU": "hu-HU", "RO": "ro-RO", "BG": "bg-BG", "LT": "lt-LT", "TR": "tr-TR",
    "UA": "uk-UA", "PT": "pt-BR",
}


def locale_per_nazione(nazione: str) -> str:
    return LOCALE_PER_NAZIONE.get((nazione or "").upper(), "en-US")
