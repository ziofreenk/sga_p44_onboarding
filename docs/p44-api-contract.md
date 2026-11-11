# Contratto API project44 replicato dal mock

Fonte: developers.project44.com (API reference v4 + guida EU "Expand Your Carrier Network"), letti il 2026-11-11.
La specifica OpenAPI ufficiale (`/_spec/api-reference/@v4/api-docs.json`) non è scaricabile dall'ambiente di sviluppo
(dominio non in allowlist): schemi non visibili segnati come **[da verificare]**.

## Base URL
| Ambiente | URL |
|---|---|
| NA | `https://na12.api.project44.com` |
| EU | `https://eu12.api.project44.com` (FERCAM) |
| Sandbox | `https://na12.api.sandbox.p-44.com` |
| **Mock POC** | `http://127.0.0.1:8044` |

## 1. OAuth2 – `POST /api/v4/oauth2/token`
- `Content-Type: application/x-www-form-urlencoded`
- Credenziali: HTTP Basic (client_id:client_secret) **oppure** campi `client_id`, `client_secret` (non entrambi).
- `grant_type=client_credentials` (unico valore ammesso).
- 200: `{"access_token": "...", "expires_in": 43200, "token_type": "BEARER"}` (~12 h).
- Errori: 400, 401, 403. Tutte le altre chiamate: `Authorization: Bearer <access_token>`; su 401 rigenerare il token.

## 2. Network Invitations
### `POST /services/invitation/v1/invitations` → 201
```json
{
  "capability": "TRUCKLOAD_ASSET_TRACKING",
  "invitee": {
    "identifiers": [{"type": "VAT", "value": "IT01234567890"}],
    "organization": {"name": "Trasporti Esempio S.r.l."},
    "contacts": [{"email": "poc@esempio-vettore.test", "givenName": "Mario",
                  "familyName": "Rossi", "locale": "it-IT", "phone": "+390000000000"}]
  }
}
```
- `identifiers[].type`: `VAT` | `SCAC` | `DOT_NUMBER` | `MC_NUMBER` | `P44_EU`
- `organization` obbligatoria se il vettore non supporta già asset tracking; `contacts[].email` + `givenName` obbligatori se il vettore non ha account P44.
- `locale`: `bg-BG, cs-CZ, de-DE, en-US (default), es-ES, hu-HU, it-IT, lt-LT, fr-FR, pt-BR, pl-PL, ro-RO, tr-TR, uk-UA`
- Risposta = invitation: `capability`, `invitee`, `status`, `createdDateTime`, `lastModifiedDateTime` (ISO-8601).
- Errori: 400, 401, 403, 404, 409 (409 = invito duplicato [da verificare]).

### `GET /services/invitation/v1/invitations` → 200
Query: `capability`, `inviteeIdentifier.type`, `inviteeIdentifier.value`, `pageNumber` (1..25, def. 1), `pageSize` (1..25, def. 10).
```json
{"paginationInfo": {"pageNumber": 1, "pageSize": 10, "total": 1},
 "results": [ { "...invitation..." } ]}
```

### Stati invito
| Stato | Significato |
|---|---|
| `IN_PROGRESS` | Creato, in attesa del vettore |
| `ACCEPTED` | Accettato: relazione di rete creata |
| `DECLINED` | Rifiutato dal vettore |
| `CANCELLED` | Annullato dall'invitante (guida EU: `CANCELED`; il mock accetta entrambi in lettura, emette `CANCELLED`) |
| `EXPIRED` | Scaduto dopo un periodo in `IN_PROGRESS` (durata non documentata) |

## 3. Errore standard (ApiError) [da verificare]
`{"httpStatusCode": 400, "httpMessage": "Bad Request", "errorMessage": "...", "errors": [], "supportReferenceId": "..."}`

## 4. Fuori dalle API pubbliche P44 (simulate con endpoint `/_sim/*`, NON P44)
| Passo | Su P44 reale avviene… | Nel mock |
|---|---|---|
| Mail di invito al vettore | inviata da P44 | file `.eml` in `output/mail/` |
| Registrazione / accettazione | il vettore clicca il link e si registra su NMC | `POST /_sim/invitations/{id}/accept` / `decline` |
| Connessione GPS | tab ELD/GPS in NMC | `POST /_sim/carriers/{vat}/gps` |
| Inserimento mezzi (targhe) | tab Fleet in NMC + License Plate Check | `POST /_sim/carriers/{vat}/vehicles` → ACTIVE/INACTIVE/UNKNOWN |
| Scadenza invito | piattaforma P44 | `POST /_sim/clock` (orologio virtuale) |

API pubbliche correlate non implementate in fase 1: `capacityprovideraccounts`, `tl/connected-capacity`, `assets/tracking`.
