# Stato progetto e punto di ripresa

Ultimo aggiornamento: 2026-11-11, fine sessione 1

## Fatto
- Struttura del repo, README, `.gitignore` (`materiali/`, `data/`, `output/` esclusi)
- `docs/p44-api-contract.md`: contratto delle API P44 da replicare (OAuth2, Network Invitations)
- Notion "P44 - Automatic onboarding system": registro decisioni, scaletta attività, rischi
- Repo sincronizzato su GitHub (main)

## Prossimi passi
1. #2 Mock P44 (`src/p44_mock/`): `http.server` + `sqlite3` sulla porta 8044, OAuth2 + invitations, test `unittest`
2. #3 Evoluzione stati inviti nel mock (scenari, EXPIRED) + `/_sim/clock`, `/_sim/reset`
3. #4 Query SGA vettori (con MCP sga-db)

## Convenzioni
- Python 3.12, solo libreria standard. Commenti in italiano
- Le decisioni vanno su Notion (DB "Registro decisioni"); questo file va aggiornato a ogni handoff
- Push: token in `C:\Tools\.secrets\claude_general_personal_access_token.txt (classic PAT)`, passato con `http.extraheader` (mai scritto in `.git/config`)

## Decisioni chiave (dettaglio su Notion)
- Perimetro: invio inviti + monitoraggio stato. Integrazione API del vettore esclusa
- Sollecito: mail FERCAM al referente del vettore a +2 e +5 giorni dall'invito. EXPIRED → nuovo invito
- Referente Ufficio Vettori POC: Francesco Orlando, francesco.orlando@fercam.com (mittente dei solleciti)
- Mock: stati inviti evolvono da soli per scenario + orologio virtuale; EXPIRED dopo 30 giorni
