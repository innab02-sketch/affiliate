# -*- coding: utf-8 -*-
"""
================================================================================
emailer.py - מודול שליחת סיכום ההצעות במייל (אופציונלי)
================================================================================

מודול זה שולח מייל סיכום עם ההצעות המובילות שעברו את סף הניקוד.
השליחה מתבצעת דרך שרת SMTP (לדוגמה Gmail).

המודול פעיל רק אם EMAIL_ENABLED=true בקובץ ההגדרות.
================================================================================
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import config

logger = logging.getLogger("clickbank_scanner.emailer")


def _build_html_body(products):
    """
    בונה גוף מייל בפורמט HTML עם טבלת ההצעות המובילות.
    """
    date_str = datetime.now().strftime("%d/%m/%Y")
    top = products[: config.EMAIL_TOP_N]

    rows_html = ""
    for i, p in enumerate(top, start=1):
        recurring_he = "כן" if p.get("recurring") else "לא"
        link = p.get("offer_link", "")
        link_html = f'<a href="{link}">קישור</a>' if link else "-"
        rows_html += f"""
        <tr>
            <td style="text-align:center;">{i}</td>
            <td>{p.get('product_name', '')}</td>
            <td style="text-align:center;">{p.get('category', '')}</td>
            <td style="text-align:center;"><b>{p.get('score', 0)}</b></td>
            <td style="text-align:center;">${p.get('epc', 0)}</td>
            <td style="text-align:center;">{p.get('commission', 0)}%</td>
            <td style="text-align:center;">{p.get('gravity', 0)}</td>
            <td style="text-align:center;">{recurring_he}</td>
            <td style="text-align:center;">{link_html}</td>
        </tr>"""

    return f"""
    <html dir="rtl">
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; direction: rtl;">
        <h2>סיכום הצעות ClickBank המובילות - {date_str}</h2>
        <p>להלן {len(top)} ההצעות המובילות שעברו את סף הניקוד ({config.SCORE_THRESHOLD}+):</p>
        <table border="1" cellpadding="8" cellspacing="0"
               style="border-collapse: collapse; width: 100%;">
            <thead style="background-color: #4CAF50; color: white;">
                <tr>
                    <th>#</th>
                    <th>שם מוצר</th>
                    <th>קטגוריה</th>
                    <th>ציון</th>
                    <th>EPC</th>
                    <th>עמלה</th>
                    <th>Gravity</th>
                    <th>מנוי</th>
                    <th>קישור</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <p style="margin-top: 20px; color: #666;">
            הנתונים המלאים כולל ניתוח ה-AI זמינים ב-Google Sheet שלך.<br>
            מייל זה נשלח אוטומטית על ידי סוכן סריקת ClickBank.
        </p>
    </body>
    </html>"""


def send_summary(products):
    """
    שולח מייל סיכום עם ההצעות המובילות.
    מחזיר True אם נשלח בהצלחה, False אחרת.
    לא עושה כלום אם EMAIL_ENABLED=false או אם אין הצעות.
    """
    if not config.EMAIL_ENABLED:
        logger.info("שליחת מייל מושבתת (EMAIL_ENABLED=false). מדלג.")
        return True

    if not products:
        logger.info("אין הצעות לשליחה במייל. מדלג.")
        return True

    date_str = datetime.now().strftime("%d/%m/%Y")
    subject = f"סיכום הצעות ClickBank מובילות - {date_str} ({len(products)} הצעות)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO

    html_body = _build_html_body(products)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # רשימת נמענים (תמיכה בכמה נמענים מופרדים בפסיק).
    recipients = [addr.strip() for addr in config.EMAIL_TO.split(",") if addr.strip()]

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
                server.starttls()
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.sendmail(config.EMAIL_FROM, recipients, msg.as_string())
            logger.info("מייל הסיכום נשלח בהצלחה אל %s", config.EMAIL_TO)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "כשל בשליחת מייל (ניסיון %d/%d): %s",
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                import time

                time.sleep(config.RETRY_DELAY)

    logger.error("נכשלה שליחת המייל לאחר %d ניסיונות.", config.MAX_RETRIES)
    return False
