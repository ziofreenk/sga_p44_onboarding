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

## 4. Perimetro e simulazione (decisione 11/11/2026)
Perimetro: **invio inviti + monitoraggio stato**. L'integrazione del vettore (registrazione NMC, GPS, mezzi) è **fuori perimetro**.

| Aspetto | Su P44 reale | Nel mock |
|---|---|---|
| Mail di invito al vettore | inviata da P44 | file `.eml` in `output/mail/` |
| Evoluzione stato invito | azione del vettore / scadenza piattaforma | automatica per scenario del vettore + orologio virtuale |
| Sollecito | mail FERCAM (Ufficio Vettori, francesco.orlando@fercam.com) | file `.eml` generato dall'orchestratore |

Endpoint extra del mock, **non P44**, usati solo per la demo: `POST /_sim/clock` (avanza l'orologio virtuale), `POST /_sim/reset`.

API pubbliche correlate non implementate: `capacityprovideraccounts`, `tl/connected-capacity`, `assets/tracking`.

## 5. Implementazione del mock (`src/p44_mock/`, attività #2 e #3)
Comportamenti del mock dove P44 non è documentato (scelte del POC, da confermare col CSM P44):
- `organization.name`, `contacts[].email` e `contacts[].givenName` sempre obbligatori (il vettore simulato non ha mai un account P44).
- `contacts[].locale` assente → valorizzato `en-US` nella risposta.
- **409**: esiste già un invito `IN_PROGRESS` con la stessa capability e almeno un identificativo uguale (confronto case-insensitive, spazi ignorati). Dopo `ACCEPTED/DECLINED/EXPIRED` un nuovo POST è ammesso (nuovo tentativo).
- La risposta contiene **solo** i campi del contratto (nessun `id`): il monitoraggio avviene con `GET` filtrato per `inviteeIdentifier.value`.
- `errors[]` dell'ApiError: oggetti `{"message": "..."}`.
- Token: scadenza sul tempo **reale** (12 h), non sull'orologio virtuale.

### Scenari dei vettori (giorni dalla creazione dell'invito)
| Scenario | 1° invito | Inviti successivi |
|---|---|---|
| `ACCETTA_SUBITO` | ACCEPTED +1 | idem |
| `ACCETTA_DOPO_SOLLECITO_1` | ACCEPTED +3 (dopo sollecito +2) | idem |
| `ACCETTA_DOPO_SOLLECITO_2` | ACCEPTED +6 (dopo sollecito +5) | idem |
| `RIFIUTA` | DECLINED +4 | idem |
| `NESSUNA_RISPOSTA` | EXPIRED +30 | idem |
| `SCADE_POI_ACCETTA` | EXPIRED +30 | ACCEPTED +2 |

Assegnazione: mappa esplicita `{"<P.IVA>": "<SCENARIO>"}` (file `--scenari` all'avvio o body di `/_sim/reset`), altrimenti
deterministica da SHA-256 del valore identificativo (stesso vettore → stesso scenario).
La transizione è applicata in modo "pigro" a ogni chiamata; `lastModifiedDateTime` = istante virtuale della transizione.

### Endpoint di simulazione (non P44, senza autenticazione, solo 127.0.0.1)
| Endpoint | Body | Effetto |
|---|---|---|
| `GET /_sim/clock` | – | `{"now": "..."}` ora virtuale |
| `POST /_sim/clock` | `{"advanceDays": n, "advanceHours": n}` oppure `{"set": "ISO-8601"}` | avanza / imposta l'orologio virtuale (avanzamento negativo → 400) |
| `POST /_sim/reset` | opzionale `{"now": "ISO-8601", "scenari": {...}}` | svuota gli inviti, riporta l'orologio, ripristina gli scenari di base + quelli passati |
| `GET /_sim/scenari` | – | elenco scenari e tempi |

L'orologio virtuale scorre col tempo reale a partire dall'ultima impostazione ed è persistito in sqlite (`data/p44_mock.db`).
