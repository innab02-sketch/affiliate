# -*- coding: utf-8 -*-
"""
================================================================================
config.py - קובץ ההגדרות המרכזי של סוכן סריקת הצעות ClickBank
================================================================================

זהו הקובץ היחיד שצריך לערוך כדי להתאים את הסוכן לצרכים שלך.
כל ההגדרות, מפתחות ה-API והפרמטרים נמצאים כאן.

מומלץ להעביר מפתחות רגישים (API keys) למשתני סביבה (environment variables)
במקום לכתוב אותם ישירות בקובץ. ראה/י את ההוראות בקובץ README.md.
================================================================================
"""

import os
import json
import tempfile

# ==============================================================================
# 1. קטגוריות לסריקה ב-ClickBank Marketplace
# ==============================================================================
# רשימת הקטגוריות שייסרקו מדי יום.
# המפתח (key) = מזהה הקטגוריה ב-URL של ClickBank.
# הערך (value) = שם תצוגה ידידותי שיופיע ב-Google Sheet.
#
# ניתן להוסיף/להסיר קטגוריות לפי הצורך.
CATEGORIES = {
    "home-garden": "בית וגינה",
    "pets": "חיות מחמד",
    "teaching-tools": "כלי הוראה",
    "e-commerce": "מסחר אלקטרוני",
    "health-fitness": "בריאות וכושר",
}

# ==============================================================================
# 2. סף ניקוד (Score Threshold)
# ==============================================================================
# רק הצעות שמקבלות ניקוד גבוה או שווה לערך זה יישמרו ב-Google Sheet.
# ערך בין 0 ל-100. ברירת המחדל היא 50.
SCORE_THRESHOLD = 50

# ==============================================================================
# 3. מפתחות API ופרטי גישה
# ==============================================================================
# מומלץ מאוד להשתמש במשתני סביבה. אם משתנה הסביבה לא קיים,
# המערכת תשתמש בערך שכתוב כאן כברירת מחדל (פחות מאובטח).

# --- ClickBank Credentials (לאסטרטגיית Playwright + Login) ---
# שם המשתמש/אימייל של חשבון ClickBank שלך
CB_USERNAME = os.environ.get("CB_USERNAME", "")
# סיסמת חשבון ClickBank שלך
CB_PASSWORD = os.environ.get("CB_PASSWORD", "")

# --- ClickBank API Key (לאסטרטגיית Analytics API — אופציונלי) ---
# ניתן ליצור ב: accounts.clickbank.com > Settings > API Keys
# פורמט: API-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CB_API_KEY = os.environ.get("CB_API_KEY", "")

# --- Claude API (Anthropic) ---
# קבל/י מפתח מ: https://console.anthropic.com/
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# מודל Claude לשימוש.
# claude-haiku-4-20250414 = זול ומהיר
# claude-sonnet-4-20250514 = איכות גבוהה יותר
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-20250414")

# ==============================================================================
# 4. הגדרות Google Sheets
# ==============================================================================
# מזהה הגיליון (Sheet ID) - נמצא ב-URL של הגיליון:
# https://docs.google.com/spreadsheets/d/<<<זה ה-ID>>>/edit
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

# שם לשונית (Worksheet/Tab) בתוך הגיליון שאליה ייכתבו הנתונים.
GOOGLE_WORKSHEET_NAME = os.environ.get("GOOGLE_WORKSHEET_NAME", "ClickBank Offers")

# --- Service Account: קורא את ה-JSON ממשתנה סביבה GOOGLE_SERVICE_ACCOUNT_JSON ---
# אם המשתנה קיים - שומר לקובץ זמני ומשתמש בו.
# אם לא - מחפש קובץ service_account.json בתיקיית הפרויקט.
_sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
if _sa_json:
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    _tmp.write(_sa_json)
    _tmp.close()
    GOOGLE_SERVICE_ACCOUNT_FILE = _tmp.name
else:
    GOOGLE_SERVICE_ACCOUNT_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "service_account.json"
    )

# ==============================================================================
# 5. הגדרות שליחת מייל (אופציונלי)
# ==============================================================================
# אם רוצים לקבל סיכום במייל של ההצעות הטובות ביותר - הפעל/י את האפשרות.
EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "false").lower() == "true"

# הגדרות שרת SMTP. הדוגמה מתאימה ל-Gmail.
# חשוב: עבור Gmail צריך ליצור "App Password" (סיסמת אפליקציה) ולא הסיסמה הרגילה.
# מדריך: https://support.google.com/accounts/answer/185833
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASS", "")

# כתובת השולח וכתובת הנמען (ניתן לשים כמה נמענים מופרדים בפסיק).
EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = os.environ.get("EMAIL_TO", SMTP_USERNAME)

# כמה הצעות מובילות לכלול בסיכום המייל.
EMAIL_TOP_N = int(os.environ.get("EMAIL_TOP_N", "10"))

# ==============================================================================
# 6. הגדרות סקרייפינג (Scraping)
# ==============================================================================
# כמה מוצרים מקסימום לסרוק בכל קטגוריה (כדי לא להעמיס).
MAX_PRODUCTS_PER_CATEGORY = int(os.environ.get("MAX_PRODUCTS_PER_CATEGORY", "30"))

# האם להריץ את הדפדפן במצב Headless (ללא ממשק גרפי).
# על שרת Linux ללא מסך - חובה להשאיר True.
HEADLESS = True

# מספר ניסיונות חוזרים במקרה של כשל בטעינת עמוד.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

# זמן המתנה (בשניות) בין ניסיונות חוזרים.
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "5"))

# Timeout (במילישניות) לטעינת עמוד ב-Playwright.
PAGE_TIMEOUT = int(os.environ.get("PAGE_TIMEOUT", "60000"))

# User-Agent שיוצג לשרת (מדמה דפדפן אמיתי כדי לעקוף הגנות בוט).
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

# ==============================================================================
# 7. הגדרות לוגים (Logging)
# ==============================================================================
# נתיב לתיקיית הלוגים.
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# רמת הלוג: DEBUG / INFO / WARNING / ERROR
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ==============================================================================
# 8. מודל הניקוד (Scoring Model) - משקלים
# ==============================================================================
# המשקלים של כל קריטריון בחישוב הציון הסופי.
# הציון הסופי = ממוצע משוקלל של כל הקריטריונים, מנורמל ל-0-100.
SCORING_WEIGHTS = {
    "epc": 3.0,          # רווח לקליק
    "commission": 2.5,   # אחוז עמלה
    "recurring": 2.5,    # מודל מנוי חוזר
    "gravity": 2.0,      # Gravity (כמות אפיליאטים מצליחים)
    "stability": 1.0,    # יציבות / גיל ההצעה
}
