#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
main.py - הסקריפט הראשי של סוכן סריקת הצעות ClickBank
================================================================================

זהו נקודת הכניסה של המערכת. הוא מתזמר את כל השלבים:
  1. סריקת ClickBank Marketplace (scraper.py)
  2. ניקוד באמצעות Claude (scorer.py)
  3. סינון לפי סף הניקוד
  4. כתיבה ל-Google Sheets (sheets.py)
  5. שליחת סיכום במייל (emailer.py) - אופציונלי

הרצה:
    python3 main.py

המערכת מתוכננת לרוץ אוטומטית מדי יום באמצעות cron (ראה/י README.md).
כל שגיאה מטופלת בחן ונרשמת ללוג, כך שכשל בשלב אחד לא מפיל את כל התהליך.
================================================================================
"""

import sys
import logging
from datetime import datetime

import config
import scraper
import scorer
import sheets
import emailer


def setup_logging():
    """
    מגדיר את מערכת הלוגים: כתיבה גם לקובץ (יומי) וגם לקונסול.
    """
    import os

    os.makedirs(config.LOG_DIR, exist_ok=True)
    log_file = os.path.join(
        config.LOG_DIR, f"scanner_{datetime.now().strftime('%Y-%m-%d')}.log"
    )

    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("clickbank_scanner")
    root.setLevel(log_level)
    root.handlers.clear()

    # Handler לקובץ.
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Handler לקונסול.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    return root


def main():
    """הפונקציה הראשית - מריצה את כל התהליך מקצה לקצה."""
    logger = setup_logging()
    start_time = datetime.now()

    logger.info("=" * 70)
    logger.info("מתחיל ריצת סוכן סריקת ClickBank - %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 70)

    # --- שלב 1: סריקה ---
    try:
        products = scraper.scrape_all()
    except Exception as exc:  # noqa: BLE001
        logger.exception("שגיאה קריטית בשלב הסריקה: %s", exc)
        products = []

    if not products:
        logger.warning("לא נשלפו מוצרים כלל. מסיים את הריצה.")
        return 1

    # --- שלב 2: ניקוד באמצעות Claude ---
    try:
        scored = scorer.score_products(products, use_claude_for_analysis=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("שגיאה בשלב הניקוד: %s", exc)
        scored = products  # נמשיך עם מה שיש (ללא ניתוח AI).

    # --- שלב 3: סינון לפי סף ---
    kept = scorer.filter_by_threshold(scored)

    if not kept:
        logger.info("אף הצעה לא עברה את סף הניקוד (%d). אין מה לכתוב.", config.SCORE_THRESHOLD)
        # עדיין נסיים בהצלחה - פשוט לא היו הצעות טובות מספיק היום.
        return 0

    # --- שלב 4: כתיבה ל-Google Sheets ---
    try:
        sheets.append_offers(kept)
    except Exception as exc:  # noqa: BLE001
        logger.exception("שגיאה בשלב הכתיבה ל-Google Sheets: %s", exc)

    # --- שלב 5: שליחת מייל סיכום (אופציונלי) ---
    try:
        emailer.send_summary(kept)
    except Exception as exc:  # noqa: BLE001
        logger.exception("שגיאה בשלב שליחת המייל: %s", exc)

    # --- סיכום ---
    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 70)
    logger.info(
        "הריצה הסתיימה בהצלחה. %d הצעות נשמרו מתוך %d שנסרקו. משך: %.1f שניות.",
        len(kept),
        len(products),
        duration,
    )
    logger.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
