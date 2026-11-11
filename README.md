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
rem test automatici
python -m unittest discover -s tests -t . -v
```
File generati (esclusi da git): `data/p44_mock.db` (sqlite, pochi KB), `output/mail/*.eml`. RAM del mock: ~20-30 MB.

## Stato
Fase 1 – mock P44 completato (#2, #3). Vedi `docs/STATO.md` e Notion per scaletta e decisioni.
