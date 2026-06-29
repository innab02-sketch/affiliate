# -*- coding: utf-8 -*-
"""
================================================================================
scraper.py - מודול הסקרייפינג של ClickBank Marketplace
================================================================================

מודול זה אחראי על שליפת נתוני המוצרים מ-ClickBank Marketplace.
משתמש ב-Playwright (דפדפן אמיתי) כדי לעקוף הגנות בוט (bot protection),
שכן בקשות HTTP רגילות נחסמות על ידי ClickBank.

לכל מוצר נשלפים הנתונים הבאים:
- שם המוצר (Product Name)
- Gravity (מדד פופולריות בקרב אפיליאטים)
- EPC (Earnings Per Click - רווח ממוצע לקליק)
- אחוז עמלה (Commission %)
- האם ההצעה מבוססת מנוי חוזר (Recurring)
- קישור להצעה (Offer Link)
================================================================================
"""

import re
import time
import logging

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import config

logger = logging.getLogger("clickbank_scanner.scraper")

# כתובת הבסיס של דף הקטגוריות ב-ClickBank Marketplace.
# פורמט: ?includeKeywords=&category=<category>&sortField=...&...
BASE_URL = "https://accounts.clickbank.com/mkplSearchResult.htm"


def _parse_number(text):
    """
    ממיר מחרוזת טקסט למספר עשרוני (float).
    מסיר תווים כמו $, %, פסיקים ורווחים.
    מחזיר 0.0 אם לא ניתן להמיר.
    """
    if text is None:
        return 0.0
    # שמירה רק על ספרות, נקודה עשרונית וסימן מינוס.
    cleaned = re.sub(r"[^0-9.\-]", "", str(text))
    if cleaned in ("", ".", "-"):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _build_category_url(category_key):
    """
    בונה את כתובת ה-URL לסריקת קטגוריה ספציפית,
    ממוינת לפי Gravity (הכי פופולריים קודם).
    """
    return (
        f"{BASE_URL}?includeKeywords=&excludeKeywords=&category={category_key}"
        f"&sortField=GRAVITY&sortOrder=DESC&minGravity=&maxGravity="
        f"&minInitialDollarPerSale=&maxInitialDollarPerSale="
        f"&minRecurringDollarPerSale=&maxRecurringDollarPerSale="
        f"&minPercentPerSale=&maxPercentPerSale=&resultsPerPage=50"
    )


def _extract_product_from_card(card):
    """
    מחלץ את נתוני המוצר מתוך כרטיס מוצר בודד (DOM element).
    מבנה ה-DOM של ClickBank עשוי להשתנות מעת לעת, ולכן הקוד
    מנסה מספר סלקטורים אפשריים ומטפל בכשלים בחן.

    מחזיר מילון (dict) עם נתוני המוצר, או None אם החילוץ נכשל.
    """
    try:
        # --- שם המוצר ---
        name = None
        for sel in ["h3", ".title", "[class*='title']", "h2", "strong"]:
            el = card.query_selector(sel)
            if el:
                txt = (el.inner_text() or "").strip()
                if txt:
                    name = txt
                    break
        if not name:
            return None

        # מילון לאיסוף השדות המספריים לפי תוויות הטקסט בכרטיס.
        full_text = card.inner_text() or ""

        # --- Gravity ---
        gravity = 0.0
        m = re.search(r"Gravity[:\s]*([\d.,]+)", full_text, re.IGNORECASE)
        if m:
            gravity = _parse_number(m.group(1))

        # --- EPC (Avg $/sale או Avg %/sale עשויים להופיע; EPC לעיתים נגזר) ---
        # ClickBank מציג לרוב "Avg $/sale" ו-"Avg Rebill Total".
        # ה-EPC לא תמיד מוצג ישירות; ננסה לאתר אותו, ואם לא - נגזור הערכה.
        epc = 0.0
        m = re.search(r"EPC[:\s]*\$?([\d.,]+)", full_text, re.IGNORECASE)
        if m:
            epc = _parse_number(m.group(1))

        # --- Avg $/sale (משמש כגיבוי להערכת EPC אם EPC לא מוצג) ---
        avg_sale = 0.0
        m = re.search(r"Avg\s*\$?/?\s*sale[:\s]*\$?([\d.,]+)", full_text, re.IGNORECASE)
        if m:
            avg_sale = _parse_number(m.group(1))

        # --- אחוז עמלה (Commission %) ---
        commission = 0.0
        m = re.search(r"([\d.,]+)\s*%", full_text)
        if m:
            commission = _parse_number(m.group(1))
        # ננסה גם תווית מפורשת.
        m2 = re.search(r"Commission[:\s]*([\d.,]+)\s*%?", full_text, re.IGNORECASE)
        if m2:
            commission = _parse_number(m2.group(1))

        # --- האם מנוי חוזר (Recurring / Rebill) ---
        recurring = bool(
            re.search(r"recurring|rebill|subscription", full_text, re.IGNORECASE)
        )

        # --- קישור להצעה ---
        link = ""
        link_el = card.query_selector("a[href]")
        if link_el:
            href = link_el.get_attribute("href") or ""
            if href.startswith("http"):
                link = href
            elif href:
                link = "https://accounts.clickbank.com" + href

        # אם EPC לא נמצא ישירות, נשתמש ב-avg_sale כקירוב גס (אופציונלי).
        if epc == 0.0 and avg_sale > 0:
            # הערכה גסה בלבד; ה-EPC האמיתי דורש נתוני המרה.
            epc = round(avg_sale * 0.01, 2)

        return {
            "product_name": name,
            "gravity": gravity,
            "epc": epc,
            "commission": commission,
            "recurring": recurring,
            "offer_link": link,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("נכשל חילוץ כרטיס מוצר: %s", exc)
        return None


def scrape_category(page, category_key, category_name):
    """
    סורק קטגוריה בודדת ומחזיר רשימת מוצרים.

    page          - אובייקט עמוד של Playwright
    category_key  - מזהה הקטגוריה ב-URL
    category_name - שם תצוגה ידידותי בעברית
    """
    url = _build_category_url(category_key)
    logger.info("סורק קטגוריה '%s' (%s)", category_name, category_key)

    products = []

    # ניסיונות חוזרים במקרה של כשל.
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            page.goto(url, timeout=config.PAGE_TIMEOUT, wait_until="domcontentloaded")
            # המתנה קצרה לטעינת תוכן דינמי (JavaScript).
            page.wait_for_timeout(4000)

            # ניסיון לאתר כרטיסי מוצרים לפי מספר סלקטורים אפשריים.
            card_selectors = [
                "div.results-product",
                "div[class*='product']",
                "div.mkpl-product",
                "article",
                "li[class*='result']",
            ]

            cards = []
            for sel in card_selectors:
                cards = page.query_selector_all(sel)
                if cards:
                    logger.debug("נמצאו %d כרטיסים עם הסלקטור '%s'", len(cards), sel)
                    break

            if not cards:
                logger.warning(
                    "לא נמצאו כרטיסי מוצרים בקטגוריה '%s' (ניסיון %d). "
                    "ייתכן שמבנה הדף השתנה.",
                    category_name,
                    attempt,
                )
                # שמירת צילום מסך לצורכי דיבאג.
                try:
                    shot = f"{config.LOG_DIR}/debug_{category_key}.png"
                    page.screenshot(path=shot, full_page=True)
                    logger.info("נשמר צילום מסך לדיבאג: %s", shot)
                except Exception:  # noqa: BLE001
                    pass

            # חילוץ נתונים מכל כרטיס.
            for card in cards[: config.MAX_PRODUCTS_PER_CATEGORY]:
                product = _extract_product_from_card(card)
                if product:
                    product["category"] = category_name
                    products.append(product)

            if products:
                logger.info(
                    "נשלפו %d מוצרים מהקטגוריה '%s'", len(products), category_name
                )
                return products

            # אם הגענו לכאן בלי מוצרים - ננסה שוב.
            raise RuntimeError("לא נשלפו מוצרים")

        except (PlaywrightTimeoutError, RuntimeError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "כשל בסריקת '%s' (ניסיון %d/%d): %s",
                category_name,
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_DELAY)
            else:
                logger.error(
                    "נכשלה סריקת הקטגוריה '%s' לאחר %d ניסיונות.",
                    category_name,
                    config.MAX_RETRIES,
                )

    return products


def scrape_all():
    """
    סורק את כל הקטגוריות שהוגדרו ב-config ומחזיר רשימה מאוחדת של כל המוצרים.
    מנהל את מחזור החיים של דפדפן Playwright (פתיחה וסגירה).
    """
    all_products = []

    logger.info("מתחיל סריקה של %d קטגוריות", len(config.CATEGORIES))

    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(
                headless=config.HEADLESS,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=config.USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            # הסתרת סימני אוטומציה נפוצים (anti-bot evasion).
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()

            for category_key, category_name in config.CATEGORIES.items():
                try:
                    products = scrape_category(page, category_key, category_name)
                    all_products.extend(products)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "שגיאה לא צפויה בקטגוריה '%s': %s", category_name, exc
                    )
                # הפסקה קצרה בין קטגוריות כדי לא להעמיס.
                page.wait_for_timeout(2000)

        finally:
            if browser:
                browser.close()

    logger.info("הסריקה הסתיימה. סך הכל %d מוצרים נשלפו.", len(all_products))
    return all_products
