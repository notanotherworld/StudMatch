"""
Email сервис СтудМэч.
- Поддержка Яндекс SMTP (smtp.yandex.ru, порт 465 SSL и 587 TLS).
- Адаптивные фирменные HTML-шаблоны для кодов верификации и рассылок.
- Диагностика и тестовая отправка.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from bot.config import settings

logger = logging.getLogger(__name__)


async def send_email_message(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
) -> None:
    """
    Универсальная отправка email через SMTP (Яндекс / Mail.ru / Gmail / др.).
    Автоматически определяет режим SSL (порт 465) или STARTTLS (порт 587).
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("⚠️ SMTP_USER или SMTP_PASSWORD не настроены в .env. Письмо не отправлено.")
        raise ValueError("SMTP не настроен: укажите SMTP_USER и SMTP_PASSWORD в .env")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    # Текстовая версия для почтовых клиентов без HTML
    plain_text = text_content or "Пожалуйста, откройте это письмо в почтовом клиенте с поддержкой HTML."
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Определение режима шифрования
    port = int(settings.SMTP_PORT or 465)
    use_ssl = (port == 465 or getattr(settings, "SMTP_USE_SSL", False))
    use_starttls = (port == 587)

    logger.info(f"📧 Отправка письма на {to_email} через {settings.SMTP_HOST}:{port} (SSL: {use_ssl}, STARTTLS: {use_starttls})...")

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=port,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        use_tls=use_ssl,
        start_tls=use_starttls,
        timeout=15.0,
    )
    logger.info(f"✅ Письмо успешно доставлено на {to_email}")


async def send_verification_code(to_email: str, code: str, university_name: Optional[str] = None) -> None:
    """Отправить фирменное письмо с кодом верификации студента."""
    uni_label = f" ({university_name})" if university_name else ""
    subject = f"🎓 СтудМэч: Код подтверждения студента — {code}"

    html_body = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{subject}</title>
    </head>
    <body style="margin:0; padding:0; background-color:#0e1017; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#f1f5f9;">
      <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout:fixed; background-color:#0e1017; padding:40px 10px;">
        <tr>
          <td align="center">
            
            <!-- Контейнер карточки -->
            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:520px; background-color:#161926; border:1px solid rgba(255,255,255,0.1); border-radius:18px; overflow:hidden; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
              
              <!-- Шапка -->
              <tr>
                <td style="padding:32px 32px 20px; text-align:center; background:linear-gradient(180deg, rgba(99,102,241,0.15) 0%, rgba(22,25,38,0) 100%);">
                  <div style="font-size:28px; font-weight:800; color:#ffffff; letter-spacing:-0.5px;">
                    🎓 <span style="color:#818cf8;">Студ</span>Мэч
                  </div>
                  <div style="font-size:13px; color:#94a3b8; margin-top:6px; font-weight:500;">
                    Студенческий нетворкинг и карьера{uni_label}
                  </div>
                </td>
              </tr>

              <!-- Основной блок -->
              <tr>
                <td style="padding:10px 32px 30px; text-align:center;">
                  <h1 style="font-size:20px; font-weight:700; color:#f8fafc; margin:0 0 12px;">Подтверждение статуса студента</h1>
                  <p style="font-size:14px; line-height:1.6; color:#94a3b8; margin:0 0 24px;">
                    Введи этот 6-значный код в Telegram-боте, чтобы подтвердить студенческий статус, получить бейдж <b>[ 🎓 Верифицирован ]</b>, <b>+100 баллов</b> рейтинга и <b>+3 суперлайка</b>.
                  </p>

                  <!-- Код верификации -->
                  <div style="background-color:#1e2336; border:1px solid rgba(99,102,241,0.4); border-radius:14px; padding:18px 24px; display:inline-block; margin-bottom:24px;">
                    <span style="font-family:'SF Mono', Monaco, Consolas, monospace; font-size:36px; font-weight:800; color:#a5b4fc; letter-spacing:10px; display:block; padding-left:10px;">
                      {code}
                    </span>
                  </div>

                  <div style="font-size:12px; color:#64748b; line-height:1.5;">
                    ⏳ Код действителен <b>15 минут</b>.<br>
                    Если ты не запрашивал код, просто проигнорируй это письмо.
                  </div>
                </td>
              </tr>

              <!-- Подвал -->
              <tr>
                <td style="background-color:#11131d; padding:20px 32px; text-align:center; border-top:1px solid rgba(255,255,255,0.06); font-size:12px; color:#475569;">
                  СтудМэч &copy; 2026. Платформа студенческого сообщества и карьеры.
                </td>
              </tr>

            </table>

          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    text_body = f"СтудМэч: Твой код подтверждения студента: {code}. Код действителен 15 минут."
    await send_email_message(to_email, subject, html_body, text_body)


async def send_informational_email(
    to_email: str,
    subject: str,
    title: str,
    text_body: str,
    button_text: Optional[str] = None,
    button_url: Optional[str] = None,
) -> None:
    """Отправить информационное / маркетинговое письмо с кнопкой действия."""
    btn_html = ""
    if button_text and button_url:
        btn_html = f"""
        <div style="margin:28px 0 10px; text-align:center;">
          <a href="{button_url}" target="_blank" style="background:linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); color:#ffffff; font-size:15px; font-weight:700; text-decoration:none; padding:14px 28px; border-radius:12px; display:inline-block; box-shadow:0 4px 14px rgba(99,102,241,0.4);">
            {button_text}
          </a>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{subject}</title>
    </head>
    <body style="margin:0; padding:0; background-color:#0e1017; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color:#f1f5f9;">
      <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout:fixed; background-color:#0e1017; padding:40px 10px;">
        <tr>
          <td align="center">
            
            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:540px; background-color:#161926; border:1px solid rgba(255,255,255,0.1); border-radius:18px; overflow:hidden; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
              
              <tr>
                <td style="padding:28px 32px 18px; text-align:center; background:linear-gradient(180deg, rgba(99,102,241,0.15) 0%, rgba(22,25,38,0) 100%);">
                  <div style="font-size:26px; font-weight:800; color:#ffffff;">
                    🎓 <span style="color:#818cf8;">Студ</span>Мэч
                  </div>
                </td>
              </tr>

              <tr>
                <td style="padding:10px 32px 30px;">
                  <h1 style="font-size:20px; font-weight:700; color:#f8fafc; margin:0 0 16px; text-align:center;">{title}</h1>
                  <div style="font-size:14px; line-height:1.6; color:#94a3b8; margin:0 0 20px; white-space:pre-wrap;">
                    {text_body}
                  </div>
                  {btn_html}
                </td>
              </tr>

              <tr>
                <td style="background-color:#11131d; padding:18px 32px; text-align:center; border-top:1px solid rgba(255,255,255,0.06); font-size:12px; color:#475569;">
                  СтудМэч &copy; 2026. Вы получили это письмо, так как зарегистрированы на платформе.
                </td>
              </tr>

            </table>

          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    await send_email_message(to_email, subject, html_content, text_body)


async def send_test_email(to_email: str) -> Dict[str, Any]:
    """
    Тестовая отправка письма для диагностики SMTP в админ-панели.
    Возвращает словарь с результатом и деталями.
    """
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
    subject = f"🧪 СтудМэч: Проверка работы почтового сервера ({now_str})"
    title = "Тестовое письмо от СтудМэч"
    body = (
        f"Почтовый сервер Яндекс SMTP успешно подключён и работает стабильно!\n\n"
        f"Параметры подключения:\n"
        f"• Хост: {settings.SMTP_HOST}\n"
        f"• Порт: {settings.SMTP_PORT}\n"
        f"• Отправитель: {settings.SMTP_FROM}\n"
        f"• Время отправки: {now_str}\n\n"
        f"Все уведомления и коды верификации доставляются корректно."
    )

    try:
        await send_informational_email(
            to_email=to_email,
            subject=subject,
            title=title,
            text_body=body,
            button_text="🚀 Открыть панель управления",
            button_url=f"{settings.DOMAIN}/admin",
        )
        return {
            "success": True,
            "message": f"Тестовое письмо успешно отправлено на {to_email} через {settings.SMTP_HOST}:{settings.SMTP_PORT}!",
        }
    except Exception as e:
        logger.error(f"❌ Ошибка тестовой отправки SMTP: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }
