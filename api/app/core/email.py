"""Envio de e-mail transacional (convites) via API do Resend.

Falha de envio nunca derruba a criação do convite: o registro em
`invited_users`/`invitations` já é a fonte de verdade de quem tem acesso — o
e-mail é só uma notificação de conveniência. Por isso os erros aqui só geram
log de warning, nunca uma exceção que o chamador precise tratar.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ROLE_LABELS = {"org_admin": "administrador", "researcher": "pesquisador"}


async def send_invitation_email(
    *, to: str, org_name: str, invited_by_name: str, role: str
) -> None:
    if not settings.resend_api_key:
        logger.info("RESEND_API_KEY não configurada — convite para %s não terá e-mail enviado.", to)
        return

    role_label = ROLE_LABELS.get(role, role)
    subject = f"Convite para o Rizoma — {org_name}"
    html = f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color: #0b1f33;">🧬 Rizoma</h2>
      <p><strong>{invited_by_name}</strong> te convidou como <strong>{role_label}</strong>
      na organização <strong>{org_name}</strong>.</p>
      <p>Entre com sua conta Google institucional para aceitar o convite:</p>
      <p>
        <a href="{settings.app_public_url}/login"
           style="display: inline-block; padding: 10px 20px; background: #0ea5c8; color: #050d1a;
                  text-decoration: none; border-radius: 6px; font-weight: 600;">
          Entrar no Rizoma
        </a>
      </p>
      <p style="color: #667; font-size: 12px;">
        Se você não esperava este convite, pode ignorar este e-mail.
      </p>
    </div>
    """.strip()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.resend_from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Falha ao enviar e-mail de convite para %s via Resend.", to, exc_info=True)
