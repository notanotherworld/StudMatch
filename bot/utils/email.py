"""Email утилиты: отправка кода верификации."""
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from bot.config import settings


async def send_verification_code(to_email: str, code: str) -> None:
    """Отправить письмо с кодом верификации."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"СтудМэч — Код верификации: {code}"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
      <div style="max-width:480px; margin:0 auto; background:#fff; border-radius:12px; padding:32px;">
        <h2 style="color:#6C3CE4; margin-top:0;">🎓 СтудМэч</h2>
        <p>Привет! Вот твой код верификации:</p>
        <div style="background:#6C3CE4; color:#fff; font-size:36px; font-weight:bold;
                    text-align:center; padding:20px; border-radius:8px; letter-spacing:8px;">
          {code}
        </div>
        <p style="color:#888; font-size:13px; margin-top:20px;">
          Код действителен 15 минут. Если ты не регистрировался — просто проигнорируй это письмо.
        </p>
      </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        start_tls=True,
    )
