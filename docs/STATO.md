# Stato progetto e punto di ripresa

Ultimo aggiornamento: 2026-11-12, sessione 6

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
- #6 Orchestratore (`src/onboarding/orchestratore.py` + `p44_client.py`, `registro.py`, `solleciti.py`, `tempo.py`):
  ciclo giornaliero idempotente. Legge il CSV (solo OK; scarti KO, campi mancanti e VAT duplicate loggati una volta),
  GET inviti per `inviteeIdentifier` VAT → invito corrente = il più recente; nessun invito → POST (tentativo 1);
  IN_PROGRESS → sollecito 1 a +2 e sollecito 2 a +5 **giorni di calendario UTC** (.eml in `output/solleciti/`,
  mittente/Reply-To francesco.orlando@fercam.com, IT o EN da POC_LOCALE; ciclo in ritardo → solo sollecito 2);
  EXPIRED → re-invito fino a 3 tentativi, poi `TENTATIVI_ESAURITI`; ACCEPTED/DECLINED/CANCELLED → solo evento.
  409 su POST → invito adottato (`INVITO_GIA_PRESENTE`). Client: token in cache, rinnovo su 401, retry con backoff
  solo su rete/429/5xx; errori di rete/401/403 → `CICLO_INTERROTTO` (exit 2), altri 4xx → `ERRORE_API` e si prosegue.
  Registro sqlite `data/orchestratore.db` (vettori, eventi, scarti) + export a ogni ciclo `output/eventi.csv`,
  `output/stato_vettori.csv` (`;`, UTF-8 BOM). Orologio `--orologio mock` = ora virtuale da `/_sim/clock` (solo demo).
  Comando: `python -m src.onboarding.orchestratore --csv data/vettori_fittizi.csv --orologio mock`
- 63 test `unittest` verdi (+12 orchestratore: 36 giorni virtuali sui 6 scenari, tempi solleciti, idempotenza,
  ritardo, tentativi esauriti, 409, credenziali errate, mail). Prova end-to-end CLI con mock su porta 8045 OK

- #7 Report KPI/anomalie (`src/onboarding/report_kpi.py`): legge SOLO `eventi.csv` + `stato_vettori.csv` (vale anche
  per run reali). KPI: perimetro e scarti per motivo; funnel (accettati, rifiutati, in corso, scaduti in attesa,
  tentativi esauriti, annullati); tassi di accettazione (totale, 1° invito, su re-invito), risposta, rifiuto; efficacia
  solleciti (accettati senza sollecito / dopo S1 / dopo S2 / su re-invito); tempi di accettazione e rifiuto
  (media/mediana/min/max, dall'invito del tentativo e dal primo invito, con lastModifiedDateTime P44, fallback data ciclo);
  solleciti S1/S2/S2 senza S1/medi per accettato; inviti, re-inviti, EXPIRED, 409 adottati; cicli e errori.
  Anomalie con gravità e azione: TENTATIVI_ESAURITI, ERRORE_API, CICLO_INTERROTTO (ALTA); RIFIUTATO, SCARTO_CSV,
  SOLLECITO_2_MANCANTE, NON_CONTROLLATO (MEDIA); ANNULLATO, SOLLECITO_1_SALTATO (BASSA).
  Output `report_kpi.md`, `kpi.csv`, `anomalie.csv` (`;`, UTF-8 BOM, decimali con virgola).
  Comando: `python -m src.onboarding.report_kpi --input output`
- #7 Demo (`src/onboarding/demo.py`): dati fittizi + mock in-process su porta libera + 1 ciclo/giorno alle 07:00 UTC
  virtuali per 95 giorni (default: 3 scadenze da 30 gg) + report. Cartella nuova per run `output/demo/run_<timestamp>`.
  Esito (seed 44, 30+2): 20 accettati 66,7%, 5 rifiutati, 5 esauriti, S1 35, S2 25, re-inviti 15, 96 cicli, 12 anomalie.
  Comando: `python -m src.onboarding.demo --data-rif 2026-11-12` (~35 s nella VM Linux)
- 79 test `unittest` verdi (+12 report su eventi costruiti a mano, +4 demo end-to-end 95 giorni)
- #8 (parte Claude, sessione 6): correzioni preventive Windows + kit di collaudo
  - `p44_client.apri()`: per indirizzi loopback (mock) opener senza proxy; su Windows urllib userebbe il proxy
    aziendale del registro anche per 127.0.0.1. P44 reale usa ancora il proxy di sistema. Usato da client, orologio mock, demo, test
  - `MockP44Server.server_bind` senza `socket.getfqdn()` (lento con DNS aziendale)
  - Riga finale della demo con decimali a virgola (`66,7%`), come il report
  - `tests/test_rete_locale.py` (+5): loopback, mock raggiungibile con HTTP(S)_PROXY morto, controprova, avvio rapido
  - `scripts/collaudo.ps1` (PS 5.1, no admin): ambiente, test, demo vs KPI attesi, prova CLI su porta 8044 (mock reale
    + 2 cicli + report) → `output\collaudo\<ts>\esito.md`. Logica CLI simulata in bash nella VM (OK); lo script
    PowerShell NON è stato eseguito (niente pwsh nella VM)
  - `docs/collaudo.md`: procedura, errori tipici, domande R1-R8 per il referente FM Italy, scaletta 8.1-8.6
- 84 test verdi con Python 3.12.15 (uv, VM Linux, anche con `-W error::DeprecationWarning`) e 3.10

## Prossimi passi
1. #8 Francesco: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collaudo.ps1` sul PC Windows, poi inviare
   `esito.md` (e i log se KO). Quindi revisione report con FM Italy (domande R1-R8 in `docs/collaudo.md`)
2. (facoltativo) Estrazione reale con `sga_esporta_csv` in `C:\Tools\mcp-sga\estrazioni` (dati aziendali: mai su git);
   verificare che il formato di ULTIMO_VIAGGIO coincida con quello del generatore (`AAAA-MM-GG hh:mm:ss`)

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
- Orchestratore (#6, approvate da Francesco il 12/11/2026): max 3 tentativi di invito; DECLINED non re-invitato (gestione manuale);
  solleciti a giorni di calendario UTC; fonte di verità degli inviti = P44 (il registro locale tiene solo solleciti,
  ultimo stato visto ed eventi)
- Report e demo (#7, approvati da Francesco il 12/11/2026): demo 95 giorni di default; report Markdown + kpi.csv +
  anomalie.csv; tempi misurati sia dal tentativo sia dal primo invito
