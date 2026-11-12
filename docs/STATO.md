# Stato progetto e punto di ripresa

Ultimo aggiornamento: 2026-11-12, sessione 3

## Fatto
- Struttura del repo, README, `.gitignore` (`materiali/`, `data/`, `output/` esclusi)
- `docs/p44-api-contract.md`: contratto delle API P44 da replicare (OAuth2, Network Invitations)
- Notion "P44 - Automatic onboarding system": registro decisioni, scaletta attività, rischi
- Repo sincronizzato su GitHub (main)
- #2 Mock P44 (`src/p44_mock/`): OAuth2 client_credentials (Basic o form), POST/GET invitations con validazione,
  paginazione, filtri, 409 su invito IN_PROGRESS duplicato, ApiError, mail di invito `.eml` in `output/mail/`
- #3 Evoluzione stati per scenario (6 scenari, EXPIRED a 30 gg, re-invito) + `/_sim/clock`, `/_sim/reset`, `/_sim/scenari`
- 31 test `unittest` verdi (`python -m unittest discover -s tests -t . -v`), dettagli in `docs/p44-api-contract.md` §5
- #4 Query SGA `sql/01_vettori_inviti_p44.sql`: società 1, reparti FMI, ultimi 3 mesi, POC tipo 01 (default
  "Ufficio Traffico"), vettori senza P.IVA scartati. Conteggio 11/11/2026: **773 vettori invitabili**, 16.776 viaggi
  (403 con nominativo di default). Esclusi: 4 non attivi, 61 bloccati, 26 FERCAM, 257 senza P.IVA
- #5 Generatore dati fittizi (`src/onboarding/genera_dati_fittizi.py`, tracciato in `src/onboarding/tracciato.py`):
  CSV con le 19 colonne della query #4 (`;`, UTF-8 BOM, ordinato come la query) + `scenari.json` {VAT_P44: scenario}
  per `python -m src.p44_mock --scenari`. Default 30 vettori OK (5 per ciascuno dei 6 scenari, minimo 6) + 2 KO_MANCA_EMAIL
  (esclusi da scenari.json); P.IVA IT con cifra di controllo valida, 3 esteri (DE/AT/PL), ~metà con "Ufficio Traffico",
  e-mail `*.test`, telefoni `+xx000...`, codici vettore 900001+. Riproducibile con `--seed` e `--data-rif`.
  Comando: `python -m src.onboarding.genera_dati_fittizi --data-rif 2026-11-12` → `data/vettori_fittizi.csv`, `data/scenari.json`
- 51 test `unittest` verdi (31 mock + 20 generatore, incluso caricamento di scenari.json nello Store del mock)

## Prossimi passi
1. #6 Orchestratore: legge il CSV (solo ESITO_CONTROLLO = OK, usa `tracciato.py`), inviti con identificativo VAT = VAT_P44,
   monitoraggio (GET per `inviteeIdentifier.value`), solleciti +2/+5 gg (.eml), re-invito su EXPIRED, log eventi
2. (facoltativo) Estrazione reale con `sga_esporta_csv` in `C:\Tools\mcp-sga\estrazioni` (dati aziendali: mai su git);
   verificare che il formato di ULTIMO_VIAGGIO coincida con quello del generatore (`AAAA-MM-GG hh:mm:ss`)
3. Verificare sul PC Windows (Python 3.12): i test sono stati eseguiti con Python 3.10 nella VM Linux

## Convenzioni
- Python 3.12, solo libreria standard. Commenti in italiano
- Le decisioni vanno su Notion (DB "Registro decisioni"); questo file va aggiornato a ogni handoff
- Push: token in `C:\Tools\.secrets\claude_general_personal_access_token.txt (classic PAT)`, passato con `http.extraheader` (mai scritto in `.git/config`)

## Decisioni chiave (dettaglio su Notion)
- Perimetro: invio inviti + monitoraggio stato. Integrazione API del vettore esclusa
- Sollecito: mail FERCAM al referente del vettore a +2 e +5 giorni dall'invito. EXPIRED → nuovo invito
- Referente Ufficio Vettori POC: Francesco Orlando, francesco.orlando@fercam.com (mittente dei solleciti)
- Estrazione vettori: vedi decisioni "Dati SGA" su Notion (perimetro FMI 3 mesi, POC default, no P.IVA = scarto)
- Mock: stati inviti evolvono da soli per scenario + orologio virtuale; EXPIRED dopo 30 giorni
