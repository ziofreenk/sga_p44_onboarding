# Collaudo #8 - PC Windows (Python 3.12) e revisione report con FM Italy

Ultimo aggiornamento: 2026-11-12. Attività #8 della Scaletta (Notion), milestone M5.

## Obiettivi
- Confermare che il POC gira sul PC di Francesco (Windows, Python 3.12, **senza admin**, rete aziendale con proxy)
- Verificare che test, demo e prova CLI diano gli stessi risultati della VM Linux
- Far validare il report KPI/anomalie al referente operativo FM Italy (Ufficio Vettori)

## Ambito
- Incluso: suite unittest, demo 95 giorni, prova CLI con mock su porta reale, revisione del report demo
- Escluso: estrazione reale da SGA (passo facoltativo successivo), chiamate a P44 reale, schedulazione del job

## Prerequisiti
- Python 3.12 (portable o `py -3.12`), solo libreria standard: **nessun `pip install`**
- PowerShell 5.1 o superiore (già presente su Windows); esecuzione con `-ExecutionPolicy Bypass` (solo processo, no admin)
- Porta locale libera > 1024 (default 8044, cambiabile con `-Porta`)
- Spazio disco: ~5 MB per run in `output\collaudo\` (db sqlite, .eml, CSV, log). RAM: < 100 MB

## Esecuzione
Dalla radice del repo `C:\Tools\sga_p44_onboarding`:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collaudo.ps1
# con Python portable non nel PATH:
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collaudo.ps1 -Python C:\percorso\python.exe
```
Durata attesa: 2-4 minuti. Lo script non modifica file del repo: scrive solo in `output\collaudo\<timestamp>\`.

| Passo | Cosa fa | Atteso |
|---|---|---|
| 1. Ambiente | versione Python, SQLite, SO, proxy di sistema → `ambiente.txt` | Python 3.12.x |
| 2. Test | `python -m unittest discover -s tests -t . -v` → `test.err.log` | 84 test OK |
| 3. Demo | 95 giorni virtuali, seed 44 → `demo\report\` | invitati 30, accettati 20 (66,7%), rifiutati 5, esauriti 5, in corso 0, anomalie 12 |
| 4. Prova CLI | genera dati, avvia `python -m src.p44_mock` sulla porta, 2 cicli orchestratore (+3 giorni), report | exit 0, 30 mail di invito, 20 solleciti S1, report creato |

Esito in `esito.md` (SUPERATO / NON SUPERATO). Exit code dello script: 0 = superato, 1 = no.

## Correzioni preventive per Windows (fatte prima del collaudo)
- **Proxy aziendale**: su Windows `urllib` legge il proxy dal registro e non lo salta per `127.0.0.1`.
  Le chiamate al mock passano ora da `p44_client.apri()`, che esclude il proxy solo per gli indirizzi
  di loopback (P44 reale continua a usare il proxy di sistema). Test: `tests/test_rete_locale.py`
- **Avvio lento del mock**: `HTTPServer` chiama `socket.getfqdn()` all'avvio; con DNS aziendale può costare secondi
  a ogni test. `MockP44Server.server_bind` ora lo evita
- **Encoding console/log**: lo script imposta `PYTHONUTF8=1`; i file CSV restano `;` + UTF-8 BOM (apertura diretta in Excel)
- Verificato: tutti i db sqlite vengono chiusi prima della pulizia delle cartelle temporanee (su Windows un file
  aperto non si cancella)

## In caso di errore
| Sintomo | Causa probabile | Azione |
|---|---|---|
| "Python non trovato" | Python non nel PATH e `py` assente | `-Python <percorso python.exe>` |
| Passo 4: "porta 8044 occupata" | altro processo (mock di una prova precedente) | `-Porta 8051` oppure chiudere il processo |
| Test o CLI con errori di rete/timeout | firewall/antivirus su loopback | inviare `test.err.log` / `cli_*.err.log` |
| `PermissionError` WinError 32 nei test | file sqlite ancora aperto (antivirus o indicizzazione) | ripetere; se persiste inviare il log |
| Script bloccato da policy | ExecutionPolicy di gruppo | lanciare con `powershell -ExecutionPolicy Bypass -File ...` |

## Revisione del report con il referente FM Italy
File da mostrare: `output\collaudo\<timestamp>\demo\report\report_kpi.md` (+ `kpi.csv`, `anomalie.csv` in Excel)
e due mail di esempio da `demo\solleciti\` (una IT, una EN).

Domande da chiudere (ogni risposta va nel Registro decisioni su Notion).
**Esito 12/11/2026**: referente Ufficio Vettori per il POC = Francesco Orlando; tutti i valori attuali R1-R8 confermati (decisione 19).

| # | Tema | Domanda per FM Italy | Valore attuale nel POC |
|---|---|---|---|
| R1 | Tempi solleciti | +2 e +5 giorni di calendario vanno bene? Giorni lavorativi? | +2 / +5 giorni di calendario UTC |
| R2 | Re-inviti | Max 3 tentativi dopo EXPIRED (30 gg) è corretto? | 3 tentativi |
| R3 | Rifiuti | DECLINED: solo gestione manuale o un re-invito dopo X giorni? | solo manuale |
| R4 | Testi mail | Testo, mittente e Reply-To dei solleciti; serve una lingua oltre IT/EN (DE)? | IT/EN, mittente Ufficio Vettori POC |
| R5 | Anomalie | Gravità e azioni suggerite sono quelle giuste? Chi prende in carico le ALTA? | vedi tabella anomalie |
| R6 | KPI | Quali KPI servono davvero (settimanale)? Mancano KPI (es. per reparto/filiale)? | 30+ KPI in 9 sezioni |
| R7 | Formato | Markdown + CSV va bene o serve Excel/mail riepilogativa? | `report_kpi.md`, `kpi.csv`, `anomalie.csv` |
| R8 | Priorità | Ordine di invito dei sub-vettori (per volume viaggi, per reparto)? | ordine della query SGA |

## Scaletta del collaudo

| # | Attività | Responsabile | Inizio | Fine | Durata | Dipendenze | Stato | Note |
|---|---|---|---|---|---|---|---|---|
| 8.1 | Correzioni preventive Windows + script di collaudo | Claude (PM/Dev) | 12/11/2026 | 12/11/2026 | 0,5 g | #7 | Completata | proxy, getfqdn, `scripts\collaudo.ps1` |
| 8.2 | Esecuzione `collaudo.ps1` sul PC Windows | Francesco | 12/11/2026 | 12/11/2026 | 0,5 g | 8.1 | Completata | SUPERATO: Python 3.12.10, 84 test OK, demo e CLI OK |
| 8.3 | Analisi esiti e correzioni | Claude (PM/Dev) | 12/11/2026 | 12/11/2026 | - | 8.2 | Completata | nessuna correzione necessaria |
| 8.4 | Individuazione referente FM Italy | Francesco | 12/11/2026 | 12/11/2026 | - | - | Completata | per il POC: Francesco Orlando (decisione 19) |
| 8.5 | Revisione report e domande R1-R8 | Francesco + Referente FM Italy | 12/11/2026 | 12/11/2026 | - | 8.2, 8.4 | Completata | valori attuali confermati (decisione 19) |
| 8.6 | Recepimento modifiche richieste | Claude (PM/Dev) | 12/11/2026 | 12/11/2026 | - | 8.5 | Completata | nessuna modifica richiesta - **M5** collaudo chiuso |

Rischi residui: policy aziendali su PowerShell/antivirus (mitigazione: comandi Python manuali sotto).

## Esito esecuzione 8.2 (12/11/2026 09:45)
| Passo | Esito | Dettaglio |
|---|---|---|
| Ambiente | OK | LAPMI057, Windows 11, Python 3.12.10, SQLite 3.49.1, PowerShell 5.1 |
| Test unittest | OK | 84 test in 107 s |
| Demo 95 giorni | OK | 62 s, KPI come attesi |
| Prova CLI porta 8044 | OK | 30 mail di invito, 20 solleciti, report creato |

Nota: urllib sul PC non vede alcun proxy di sistema, quindi il bypass del proxy per il mock non è stato esercitato
dal vivo (resta coperto da `tests/test_rete_locale.py`).

## Criteri di accettazione (definizione di "fatto")
- `esito.md` SUPERATO sul PC Windows con Python 3.12 (4 passi OK)
- KPI della demo identici alla VM Linux
- Domande R1-R8 con risposta registrata su Notion; eventuali modifiche implementate e testate

## Comandi manuali (alternativa allo script)
```powershell
py -3.12 -m unittest discover -s tests -t . -v
py -3.12 -m src.onboarding.demo --data-rif 2026-11-12
```
