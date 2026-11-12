# SGA → project44: sistema di onboarding automatico dei sub-vettori (POC)

POC locale che simula il processo di onboarding dei **sub-vettori FERCAM** su project44 (P44):
invito, sollecito, registrazione avvenuta, connessione GPS e inserimento mezzi,
**senza chiamate reali a P44**.

## Principi
- **Mock P44 con API identiche** a quelle pubbliche P44 (path, metodi, payload, enum, codici HTTP): vedi `docs/p44-api-contract.md`.
  Passare al P44 reale = cambiare solo `base_url` e credenziali.
- **Sorgente vettori: SGA** (SQL Server) via query T-SQL in sola lettura (`sql/`). Dati fittizi in fase POC.
- **No admin, open source**: Python 3.12 + libreria standard; porte utente (> 1024).
- Documentazione di progetto, decisioni e dashboard: Notion "P44 - Automatic onboarding system".

## Struttura
| Cartella | Contenuto |
|---|---|
| `src/p44_mock/` | Server mock P44 (OAuth2 token, Network Invitations) + endpoint di simulazione `/_sim/*` |
| `src/onboarding/` | Orchestratore FERCAM: lettura vettori, inviti, solleciti, monitoraggio, report |
| `sql/` | Query T-SQL su SGA |
| `docs/` | Contratto API P44, note tecniche |
| `tests/` | Test automatici (`unittest`) |
| `materiali/` | Materiale locale non versionato |

## Avvio rapido (Windows, Python 3.12 portable/utente)
```bat
cd C:\Tools\sga_p44_onboarding
rem credenziali del mock (facoltative: senza, valori demo fercam-poc / fercam-poc-secret)
set P44_MOCK_CLIENT_ID=fercam-poc
set P44_MOCK_CLIENT_SECRET=fercam-poc-secret
python -m src.p44_mock --port 8044
rem dati fittizi (vettori + scenari del mock), poi mock con scenari forzati
python -m src.onboarding.genera_dati_fittizi --data-rif 2026-11-12
python -m src.p44_mock --port 8044 --scenari data\scenari.json
rem orchestratore: un ciclo (in demo con ora virtuale del mock); avanzare i giorni con POST /_sim/clock
python -m src.onboarding.orchestratore --csv data\vettori_fittizi.csv --orologio mock
rem test automatici
python -m unittest discover -s tests -t . -v
```
File generati (esclusi da git): `data/vettori_fittizi.csv`, `data/scenari.json`, `data/p44_mock.db` e `data/orchestratore.db` (sqlite, pochi KB),
`output/mail/*.eml` (inviti), `output/solleciti/*.eml`, `output/eventi.csv`, `output/stato_vettori.csv`. RAM del mock: ~20-30 MB.

## Stato
Fase 1 – mock P44 completato (#2, #3). Fase 2 – query SGA (#4) e dati fittizi (#5) completati. Fase 3 – orchestratore (#6) completato. Vedi `docs/STATO.md` e Notion per scaletta e decisioni.
