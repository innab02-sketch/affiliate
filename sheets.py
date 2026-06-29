# -*- coding: utf-8 -*-
"""
================================================================================
sheets.py - מודול הכתיבה ל-Google Sheets
================================================================================

מודול זה אחראי על כתיבת ההצעות שעברו את סף הניקוד ל-Google Sheet.
משתמש בספריית gspread יחד עם Service Account של Google.

כל הרצה מוסיפה שורות חדשות (append) עם תאריך ההרצה - כך נשמרת היסטוריה יומית.

פורמט העמודות:
תאריך | קטגוריה | שם מוצר | Gravity | EPC | עמלה% | מנוי חוזר | ציון | קישור | ניתוח AI
================================================================================
"""

import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger("clickbank_scanner.sheets")

# הרשאות נדרשות עבור Google Sheets API.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# כותרות העמודות (שורת הכותרת).
HEADER_ROW = [
    "תאריך",
    "קטגוריה",
    "שם מוצר",
    "Gravity",
    "EPC",
    "עמלה %",
    "מנוי חוזר",
    "ציון",
    "קישור להצעה",
    "ניתוח AI",
]


def _get_client():
    """
    יוצר ומחזיר לקוח gspread מאומת באמצעות Service Account.
    """
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _get_worksheet(client):
    """
    פותח את הגיליון לפי ה-ID ומחזיר את הלשונית (worksheet) המבוקשת.
    אם הלשונית לא קיימת - יוצר אותה. אם שורת הכותרת חסרה - מוסיף אותה.
    """
    spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)

    # ניסיון לפתוח את הלשונית; אם לא קיימת - יצירה.
    try:
        worksheet = spreadsheet.worksheet(config.GOOGLE_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        logger.info("הלשונית '%s' לא קיימת - יוצר חדשה.", config.GOOGLE_WORKSHEET_NAME)
        worksheet = spreadsheet.add_worksheet(
            title=config.GOOGLE_WORKSHEET_NAME, rows=1000, cols=len(HEADER_ROW)
        )

    # בדיקה אם קיימת שורת כותרת; אם לא - הוספה.
    existing = worksheet.get_all_values()
    if not existing:
        worksheet.append_row(HEADER_ROW, value_input_option="USER_ENTERED")
        logger.info("נוספה שורת כותרת ללשונית.")

    return worksheet


def _product_to_row(product, date_str):
    """ממיר מילון מוצר לשורת נתונים לפי סדר העמודות."""
    return [
        date_str,
        product.get("category", ""),
        product.get("product_name", ""),
        product.get("gravity", 0),
        product.get("epc", 0),
        product.get("commission", 0),
        "כן" if product.get("recurring") else "לא",
        product.get("score", 0),
        product.get("offer_link", ""),
        product.get("ai_analysis", ""),
    ]


def append_offers(products):
    """
    מוסיף את ההצעות ל-Google Sheet כשורות חדשות עם תאריך היום.
    מבצע כתיבה בכמות (batch) לחיסכון בקריאות API.
    כולל ניסיונות חוזרים במקרה של כשל.

    מחזיר True אם ההצלחה, False אחרת.
    """
    if not products:
        logger.info("אין הצעות לכתיבה ל-Google Sheet.")
        return True

    date_str = datetime.now().strftime("%Y-%m-%d")
    rows = [_product_to_row(p, date_str) for p in products]

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            client = _get_client()
            worksheet = _get_worksheet(client)
            worksheet.append_rows(rows, value_input_option="USER_ENTERED")
            logger.info(
                "נכתבו %d שורות ל-Google Sheet (לשונית '%s').",
                len(rows),
                config.GOOGLE_WORKSHEET_NAME,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "כשל בכתיבה ל-Google Sheet (ניסיון %d/%d): %s",
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                import time

                time.sleep(config.RETRY_DELAY)

    logger.error("נכשלה הכתיבה ל-Google Sheet לאחר %d ניסיונות.", config.MAX_RETRIES)
    return False
