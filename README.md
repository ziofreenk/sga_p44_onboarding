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
| `docs/` | Contratto API P44, stato, procedura di collaudo |
| `scripts/` | `collaudo.ps1`: collaudo completo su Windows (#8) |
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
rem report KPI/anomalie sugli export dell'orchestratore -> output\report\
python -m src.onboarding.report_kpi --input output
rem test automatici (84, ~1 minuto: include una demo di 95 giorni virtuali)
python -m unittest discover -s tests -t . -v
```

## Demo completa (un comando)
```bat
python -m src.onboarding.demo --giorni 95 --data-rif 2026-11-12
```
Genera i dati fittizi, avvia il mock in-process su una porta libera (solo 127.0.0.1), esegue un ciclo
dell'orchestratore per ogni giorno virtuale e produce il report finale. Ogni run scrive in una cartella nuova
`output\demo\run_AAAAMMGG_hhmmss\` (nessun file sovrascritto). Esito atteso con i default (30 vettori + 2 KO):
20 accettati (66,7%), 5 rifiutati, 5 a tentativi esauriti, 35 solleciti 1 + 25 solleciti 2, 15 re-inviti.
Opzioni: `--vettori`, `--ko`, `--seed`, `--cartella`, `--quiet`. RAM < 50 MB, disco ~1 MB per run.

Report (`report\` del run o di `--output`):
| File | Contenuto |
|---|---|
| `report_kpi.md` | Sintesi, funnel, KPI per area (accettazione, efficacia solleciti, tempi di risposta, solleciti, inviti, esecuzione), anomalie con azione suggerita |
| `kpi.csv` | `area;kpi;valore;unita` (UTF-8 BOM, decimali con virgola per Excel) |
| `anomalie.csv` | `gravita;tipo;vat;codice_vettore;ragione_sociale;dettaglio;azione_suggerita` |
File generati (esclusi da git): `data/vettori_fittizi.csv`, `data/scenari.json`, `data/p44_mock.db` e `data/orchestratore.db` (sqlite, pochi KB),
`output/mail/*.eml` (inviti), `output/solleciti/*.eml`, `output/eventi.csv`, `output/stato_vettori.csv`. RAM del mock: ~20-30 MB.

## Collaudo su Windows (#8)
```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collaudo.ps1 [-Python C:\...\python.exe] [-Porta 8044]
```
Ambiente + test + demo 95 giorni + prova CLI su porta reale; esito in `output\collaudo\<timestamp>\esito.md`.
Procedura, errori tipici e checklist di revisione del report con FM Italy: `docs/collaudo.md`.

## Stato
Fase 1 – mock P44 completato (#2, #3). Fase 2 – query SGA (#4) e dati fittizi (#5) completati. Fase 3 – orchestratore (#6) completato. Fase 4 – report KPI/anomalie e demo (#7) completati. Fase 5 – collaudo (#8) in corso. Vedi `docs/STATO.md` e Notion per scaletta e decisioni.
