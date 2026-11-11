# Stato progetto e punto di ripresa

Ultimo aggiornamento: 2026-11-11, fine sessione 1

## Fatto
- Struttura del repo, README, `.gitignore` (`materiali/`, `data/`, `output/` esclusi)
- `docs/p44-api-contract.md`: contratto delle API P44 da replicare (OAuth2, Network Invitations)
- Notion "P44 - Automatic onboarding system": registro decisioni, scaletta attività, rischi
- Primo commit solo in locale: il push è negato dal token fine-grained, che non include il repo

## Prossimi passi
1. #2 Mock P44 (`src/p44_mock/`): `http.server` + `sqlite3` sulla porta 8044, OAuth2 + invitations, test `unittest`
2. #3 Endpoint `/_sim/*`
3. #4 Query SGA vettori (con MCP sga-db)

## Convenzioni
- Python 3.12, solo libreria standard. Commenti in italiano
- Le decisioni vanno su Notion (DB "Registro decisioni"); questo file va aggiornato a ogni handoff
- Push: token in `C:\Tools\.secrets\github-rw.txt`, passato con `http.extraheader` (mai scritto in `.git/config`)
