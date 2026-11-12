"""Mail di sollecito FERCAM al referente del vettore (decisione #7): file .eml su disco.

P44 non espone un'API di re-invio: il sollecito è una mail dell'Ufficio Vettori FERCAM
che invita il vettore a completare l'invito già ricevuto da project44.
"""

import os
import re
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

MITTENTE = "FERCAM Ufficio Vettori <francesco.orlando@fercam.com>"

_TESTI = {
    "it": ("Sollecito {n}: invito project44 di FERCAM in attesa - {rs}",
           "Gentile {nome},\n\n"
           "il {data} project44 le ha inviato, per conto di FERCAM, l'invito a condividere il "
           "tracciamento dei mezzi (TRUCKLOAD_ASSET_TRACKING) per {rs} (P.IVA {vat}).\n"
           "Risulta ancora in attesa di risposta.\n\n"
           "Le chiediamo di accettarlo tramite il link presente nella mail di project44 "
           "(mittente no-reply di project44: verifichi anche la cartella spam).\n"
           "Per qualsiasi chiarimento può rispondere a questa mail.\n\n"
           "Cordiali saluti\nFERCAM - Ufficio Vettori\n"),
    "en": ("Reminder {n}: pending project44 invitation from FERCAM - {rs}",
           "Dear {nome},\n\n"
           "on {data} project44 sent you, on behalf of FERCAM, an invitation to share asset "
           "tracking (TRUCKLOAD_ASSET_TRACKING) for {rs} (VAT {vat}).\n"
           "The invitation is still pending.\n\n"
           "Please accept it through the link in the project44 e-mail "
           "(sent from a project44 no-reply address: please also check your spam folder).\n"
           "Feel free to reply to this e-mail for any question.\n\n"
           "Kind regards\nFERCAM - Carrier Office\n"),
}


def scrivi_sollecito(cartella: str, numero: int, vettore: dict, invito_creato, istante) -> str:
    """vettore: riga del CSV (tracciato.COLONNE). Restituisce il percorso del .eml."""
    os.makedirs(cartella, exist_ok=True)
    lingua = "it" if (vettore.get("POC_LOCALE") or "").startswith("it") else "en"
    oggetto, corpo = _TESTI[lingua]
    rs, vat = vettore["RAGIONE_SOCIALE"], vettore["VAT_P44"]
    msg = EmailMessage()
    msg["From"] = MITTENTE
    msg["Reply-To"] = MITTENTE
    msg["To"] = vettore["POC_EMAIL"]
    msg["Date"] = format_datetime(istante)
    msg["Message-ID"] = make_msgid(domain="fercam.com")
    msg["Subject"] = oggetto.format(n=numero, rs=rs)
    msg["X-FERCAM-POC"] = f"sollecito={numero}; vat={vat}; codice_vettore={vettore['CODICE_VETTORE']}"
    nome = vettore.get("POC_NOMINATIVO") or vettore.get("POC_NOME", "")
    if lingua == "en" and vettore.get("POC_NOMINATIVO_DEFAULT") == "S":
        nome = "Sir or Madam"   # "Ufficio Traffico" non ha senso in una mail in inglese
    msg.set_content(corpo.format(nome=nome,
                                 rs=rs, vat=vat, data=invito_creato.strftime("%d/%m/%Y")))
    nome_file = f"{istante.strftime('%Y%m%dT%H%M%S')}_sollecito{numero}_{re.sub(r'[^A-Za-z0-9_-]', '_', vat)}.eml"
    percorso = os.path.join(cartella, nome_file)
    with open(percorso, "wb") as f:
        f.write(bytes(msg))
    return percorso
