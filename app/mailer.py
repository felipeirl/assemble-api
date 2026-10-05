"""E-mail de verificação de conta, em HTML com o design system do app (sem domínio próprio).

O link vem do Firebase Auth (`generate_email_verification_link`) e abre a página padrão do
Firebase, então não é preciso domínio. O envio usa SMTP comum, por exemplo uma conta do Gmail
com senha de app. Sem SMTP configurado, o app pede o e-mail padrão do próprio Firebase.
"""

import html
import logging
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any

from app.i18n import EN, PT_BR

SMTP_TIMEOUT_SECONDS = 20.0
SMTP_SSL_PORT = 465

# Tokens do design system (app/core/designsystem/theme/Color.kt).
HERO_RED = "#E62429"
LOGO_RED = "#FF114B"
LOGO_PINK = "#FF3475"
MIDNIGHT = "#0B1020"
OFF_WHITE = "#F5F1E8"
INK = "#111827"
SLATE = "#596273"
MIST = "#D9DDE5"
HEADING_FONT = "'Barlow Condensed','Arial Narrow','Helvetica Neue',Arial,sans-serif"
BODY_FONT = "Inter,'Helvetica Neue',Arial,sans-serif"

COPY = {
    PT_BR: {
        "subject": "Confirme o seu e-mail no Assemble",
        "preheader": "Falta só um toque para começar a conversar com os personagens.",
        "greeting": "Fala, {name}!",
        "title": "Confirme o seu e-mail",
        "body": "Para liberar a sua conta e começar a descobrir personagens, confirme que este e-mail é seu.",
        "button": "Confirmar e-mail",
        "fallback": "Se o botão não abrir, copie este endereço no navegador:",
        "ignore": "Não criou uma conta no Assemble? É só ignorar este e-mail: nada acontece sem a confirmação.",
        "footer": "Projeto acadêmico. Não é afiliado à Marvel, à Comic Vine nem a qualquer editora. "
        "Toda conversa é ficção gerada por IA.",
        "text_intro": "Confirme o seu e-mail para liberar a sua conta no Assemble:",
        "tagline": "Descubra personagens. Converse com eles.",
        "step1": "Toque no botão abaixo",
        "step2": "Volte ao app",
        "step3": "Comece a descobrir",
        "security": "Por segurança, o link vale por pouco tempo e só funciona uma vez.",
    },
    EN: {
        "subject": "Confirm your email on Assemble",
        "preheader": "One tap left to start chatting with the characters.",
        "greeting": "Hey {name}!",
        "title": "Confirm your email",
        "body": "To unlock your account and start discovering characters, confirm that this email is yours.",
        "button": "Confirm email",
        "fallback": "If the button doesn't open, copy this address into your browser:",
        "ignore": "Didn't create an Assemble account? Just ignore this email: nothing happens without the confirmation.",
        "footer": "Academic project. Not affiliated with Marvel, Comic Vine or any publisher. "
        "Every chat is AI-generated fiction.",
        "text_intro": "Confirm your email to unlock your Assemble account:",
        "tagline": "Discover characters. Talk to them.",
        "step1": "Tap the button below",
        "step2": "Go back to the app",
        "step3": "Start discovering",
        "security": "For your safety, the link expires soon and works only once.",
    },
}

logger = logging.getLogger(__name__)


class MailerError(Exception):
    """O e-mail não pôde ser enviado (SMTP fora do ar ou recusado)."""


LOGO_CID = "assemble-logo"
LOGO_PATH = Path(__file__).parent / "assets" / "assemble-logo.png"


def render_verification(
    name: str, link: str, locale: str, logo_src: str = f"cid:{LOGO_CID}"
) -> tuple[str, str, str]:
    """(assunto, texto simples, HTML) do e-mail de verificação.

    `logo_src` é `cid:` no e-mail (a imagem vai junto, como parte do e-mail) e uma URL `data:`
    na prévia aberta no navegador.
    """
    copy = COPY.get(locale, COPY[EN])
    safe_name = html.escape(name)
    safe_link = html.escape(link, quote=True)
    greeting = copy["greeting"].format(name=safe_name)
    step = (
        f'<td width="33%" align="center" valign="top" style="padding:0 6px;font-family:{BODY_FONT};">'
        f'<div style="width:30px;height:30px;line-height:30px;border-radius:15px;background:{MIDNIGHT};'
        f"color:#FFFFFF;font-family:{HEADING_FONT};font-weight:800;font-size:16px;text-align:center;"
        f'margin:0 auto 8px auto;">{{n}}</div>'
        f'<div style="font-size:12px;line-height:1.4;color:{SLATE};">{{label}}</div></td>'
    )
    steps = "".join(
        step.format(n=n, label=copy[key]) for n, key in ((1, "step1"), (2, "step2"), (3, "step3"))
    )
    page = f"""<!doctype html>
<html lang="{locale}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{copy["subject"]}</title>
</head>
<body style="margin:0;padding:0;background:{OFF_WHITE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{copy["preheader"]}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{OFF_WHITE};">
<tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#FFFFFF;border-radius:28px;overflow:hidden;">
<tr><td align="center" bgcolor="{MIDNIGHT}" style="padding:36px 32px 28px 32px;background:{MIDNIGHT};">
<img src="{logo_src}" width="84" height="106" alt="Assemble" style="display:block;border:0;outline:none;width:84px;height:106px;">
<div style="margin-top:16px;font-family:{HEADING_FONT};font-weight:800;font-size:38px;letter-spacing:3px;line-height:1;color:#FFFFFF;text-transform:uppercase;">Assemble</div>
<div style="margin-top:8px;font-family:{BODY_FONT};font-size:13px;letter-spacing:.5px;color:{MIST};">{copy["tagline"]}</div>
</td></tr>
<tr><td height="6" bgcolor="{LOGO_RED}" style="height:6px;line-height:6px;font-size:0;background:{LOGO_RED};background-image:linear-gradient(90deg,{LOGO_RED},{LOGO_PINK});">&nbsp;</td></tr>
<tr><td style="padding:36px 36px 8px 36px;font-family:{BODY_FONT};color:{INK};">
<div style="font-size:15px;color:{SLATE};">{greeting}</div>
<h1 style="margin:8px 0 14px 0;font-family:{HEADING_FONT};font-weight:800;font-size:36px;line-height:1.05;text-transform:uppercase;color:{MIDNIGHT};">{copy["title"]}</h1>
<p style="margin:0 0 28px 0;font-size:16px;line-height:1.55;color:{INK};">{copy["body"]}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td align="center" bgcolor="{LOGO_RED}" style="border-radius:18px;background:{LOGO_RED};background-image:linear-gradient(135deg,{LOGO_RED},{LOGO_PINK});">
<a href="{safe_link}" style="display:inline-block;padding:17px 40px;font-family:{BODY_FONT};font-size:17px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:18px;">{copy["button"]}</a>
</td></tr></table>
</td></tr></table>
</td></tr>
<tr><td style="padding:32px 30px 4px 30px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{steps}</tr></table>
</td></tr>
<tr><td style="padding:28px 36px 8px 36px;font-family:{BODY_FONT};font-size:13px;line-height:1.55;color:{SLATE};">
<div>{copy["fallback"]}</div>
<div style="margin-top:6px;word-break:break-all;"><a href="{safe_link}" style="color:{HERO_RED};">{safe_link}</a></div>
</td></tr>
<tr><td style="padding:16px 36px 32px 36px;font-family:{BODY_FONT};font-size:13px;line-height:1.55;color:{SLATE};">
<div>{copy["security"]}</div>
<div style="margin-top:6px;">{copy["ignore"]}</div>
</td></tr>
<tr><td bgcolor="{MIDNIGHT}" style="padding:22px 36px;background:{MIDNIGHT};font-family:{BODY_FONT};font-size:12px;line-height:1.55;color:{MIST};">
{copy["footer"]}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    plain_greeting = copy["greeting"].format(name=name)
    text = f"{plain_greeting}\n\n{copy['text_intro']}\n{link}\n\n{copy['ignore']}\n"
    return copy["subject"], text, page


class VerificationMailer:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        sender_name: str,
        smtp_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._sender_name = sender_name
        self._smtp_factory = smtp_factory

    def send_verification(self, to: str, name: str, link: str, locale: str) -> None:
        subject, text, page = render_verification(name, link, locale)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self._sender_name, self._user))
        message["To"] = to
        message.set_content(text)
        message.add_alternative(page, subtype="html")
        message.get_body(("html",)).add_related(
            LOGO_PATH.read_bytes(), maintype="image", subtype="png", cid=f"<{LOGO_CID}>"
        )
        try:
            self._deliver(message)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("Falha ao enviar o e-mail de verificação: %s", type(exc).__name__)
            raise MailerError(type(exc).__name__) from exc

    def _deliver(self, message: EmailMessage) -> None:
        if self._smtp_factory is not None:
            with self._smtp_factory(self._host, self._port) as smtp:
                smtp.login(self._user, self._password)
                smtp.send_message(message)
            return
        context = ssl.create_default_context()
        if self._port == SMTP_SSL_PORT:
            with smtplib.SMTP_SSL(
                self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS, context=context
            ) as smtp:
                smtp.login(self._user, self._password)
                smtp.send_message(message)
            return
        with smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.starttls(context=context)
            smtp.login(self._user, self._password)
            smtp.send_message(message)
