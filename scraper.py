# -*- coding: utf-8 -*-
"""
================================================================================
scraper.py - מודול סריקת ClickBank Marketplace (גרסה 2 — מתוקנת)
================================================================================

מדוע הגרסה הקודמת לא עבדה:
- ClickBank מגן על accounts.clickbank.com ב-CloudFront WAF
- כל בקשה ללא session cookies אמיתיים מקבלת 403 — גם מ-Playwright
- ה-RSS/XML feed הופסק ב-2022
- אין API ציבורי לחיפוש ב-Marketplace

הפתרון — 3 אסטרטגיות לפי סדר עדיפות:

1. Playwright + Login + GraphQL Interception [ראשי]
   - Playwright מתחבר עם credentials אמיתיים
   - אחרי login, מנווט ל-Marketplace ומיירט קריאות GraphQL
   - מחזיר נתונים מלאים: Gravity, EPC, Commission, Recurring
   - דורש: CB_USERNAME + CB_PASSWORD ב-config.py

2. ClickBank Blog "Top Offers" Parser [גיבוי ציבורי]
   - מפרסר https://www.clickbank.com/blog/clickbank-top-offers/
   - ציבורי לחלוטין, ללא login, ללא bot protection
   - מתעדכן חודשי, ~20 הצעות מובילות עם EPC, APV, Hop Conversion Rate
   - Gravity מוערך מ-EPC (לא מדויק אבל שמיש)

3. ClickBank Analytics REST API [גיבוי — הצעות קיימות בלבד]
   - מחזיר נתוני ביצועים של הצעות שהמשתמשת כבר מקדמת
   - דורש: CB_API_KEY ב-config.py
================================================================================
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger("clickbank_scanner.scraper")

# ─────────────────────────────────────────────────────────────────────────────
# קבועים
# ─────────────────────────────────────────────────────────────────────────────

CB_ACCOUNTS_BASE = "https://accounts.clickbank.com"
CB_API_BASE = "https://api.clickbank.com/rest/1.3"
BLOG_TOP_OFFERS_URL = "https://www.clickbank.com/blog/clickbank-top-offers/"

# מיפוי קטגוריות ClickBank לנושאים לזיהוי אוטומטי מהבלוג
CATEGORY_KEYWORDS = {
    "health-fitness": [
        "health", "fitness", "weight", "diet", "supplement", "sleep",
        "pain", "brain", "energy", "blood", "sugar", "fat", "muscle",
        "testosterone", "menopause", "vision", "hearing", "keto",
    ],
    "home-garden": [
        "home", "garden", "survival", "woodwork", "diy", "house",
        "plant", "prepper", "emergency", "water", "solar",
    ],
    "pets": ["pet", "dog", "cat", "animal", "training", "puppy"],
    "teaching-tools": [
        "teach", "learn", "course", "education", "language", "study",
        "kids", "school", "math", "reading",
    ],
    "e-commerce": [
        "ecommerce", "e-commerce", "shopify", "store", "business",
        "marketing", "amazon", "dropship", "traffic", "funnel",
    ],
    "spirituality": [
        "spiritual", "manifest", "law of attraction", "meditation",
        "psychic", "numerology", "astrology", "tarot", "genius",
        "brainwave", "frequency",
    ],
    "self-help": [
        "self", "confidence", "anxiety", "relationship", "dating",
        "attraction", "social", "shy", "introvert",
    ],
}

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ─────────────────────────────────────────────────────────────────────────────
# עזרים
# ─────────────────────────────────────────────────────────────────────────────

def _parse_number(text) -> float:
    """ממיר מחרוזת למספר עשרוני, מסיר $, %, פסיקים."""
    if text is None:
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", str(text))
    if cleaned in ("", ".", "-"):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_number(text: str, pattern: str) -> float:
    """חולץ מספר ראשון שמתאים ל-pattern מתוך טקסט."""
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return _parse_number(m.group(1))
    return 0.0


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _empty_offer(name: str, category: str) -> dict:
    """מחזיר מבנה ריק של הצעה עם ערכי ברירת מחדל."""
    return {
        "product_name": name,
        "category": category,
        "gravity": 0.0,
        "epc": 0.0,
        "commission": 0.0,
        "recurring": False,
        "offer_link": "",
        "vendor": "",
        "avg_sale": 0.0,
        "hop_conversion_rate": 0.0,
        "scraped_at": datetime.now().isoformat(),
        "source": "unknown",
    }


def _map_to_category(raw_text: str, requested_categories: list) -> str:
    """ממפה טקסט חופשי לקטגוריית ClickBank סטנדרטית."""
    text_lower = raw_text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return requested_categories[0] if requested_categories else "health-fitness"


def _estimate_gravity_from_epc(epc: float, hop_conv: float = 0.0) -> float:
    """
    מעריך Gravity מ-EPC ו-Hop Conversion Rate.
    הצעות עם EPC גבוה בדרך כלל יש להן Gravity גבוה.
    """
    if epc >= 3.0:
        base = 200.0
    elif epc >= 2.0:
        base = 120.0
    elif epc >= 1.0:
        base = 70.0
    elif epc >= 0.5:
        base = 35.0
    else:
        base = 12.0

    if hop_conv >= 3.0:
        base *= 1.4
    elif hop_conv >= 1.5:
        base *= 1.15

    return round(base, 1)


# ─────────────────────────────────────────────────────────────────────────────
# אסטרטגיה 1: Playwright + Login + GraphQL Interception
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_via_playwright_login(categories: list) -> list:
    """
    מתחבר ל-ClickBank עם credentials אמיתיים דרך Playwright,
    מנווט ל-Marketplace, ומיירט קריאות GraphQL לחילוץ נתוני מוצרים.

    זו האסטרטגיה הראשית — מחזירה נתונים מלאים כולל Gravity.
    דורש: CB_USERNAME + CB_PASSWORD ב-config.py
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error("Playwright לא מותקן. הרץ: pip install playwright && playwright install chromium")
        return []

    if not getattr(config, "CB_USERNAME", "") or not getattr(config, "CB_PASSWORD", ""):
        logger.warning("CB_USERNAME/CB_PASSWORD לא הוגדרו — מדלג על אסטרטגיה 1")
        return []

    all_offers = []
    graphql_data = []

    def _capture_response(response):
        """מיירט תגובות GraphQL עם נתוני marketplace."""
        if "graphql" not in response.url:
            return
        if response.status != 200:
            return
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            body = response.json()
            body_str = json.dumps(body)
            if any(kw in body_str.lower() for kw in ["gravity", "marketplace", "commission", "epc", "affiliate"]):
                graphql_data.append(body)
                logger.debug("GraphQL marketplace response captured (%d bytes)", len(body_str))
        except Exception as exc:
            logger.debug("שגיאה בפענוח GraphQL: %s", exc)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=getattr(config, "HEADLESS", True),
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=getattr(config, "USER_AGENT", HTTP_HEADERS["User-Agent"]),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        page.on("response", _capture_response)

        try:
            # ─── Login ───
            logger.info("Playwright: מתחבר ל-ClickBank...")
            page.goto(f"{CB_ACCOUNTS_BASE}/login.htm", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            page.fill('input[name="username"]', config.CB_USERNAME)
            page.fill('input[name="password"]', config.CB_PASSWORD)
            page.click('button[type="submit"], button:has-text("Login")')
            page.wait_for_timeout(7000)

            if "login" in page.url.lower():
                logger.error("Login נכשל — בדקי CB_USERNAME ו-CB_PASSWORD ב-config.py")
                page.screenshot(path=f"{config.LOG_DIR}/cb_login_failed.png")
                browser.close()
                return []

            logger.info("Login הצליח. URL: %s", page.url)

            # ─── סריקת קטגוריות ───
            for category in categories:
                logger.info("Playwright: סורקת קטגוריה '%s'", category)
                graphql_data.clear()

                # נסה URLs שונים של marketplace
                mkpl_urls = [
                    f"{CB_ACCOUNTS_BASE}/master/marketplace?category={category}&sortField=GRAVITY&sortOrder=DESC",
                    f"{CB_ACCOUNTS_BASE}/mkplSearchResult.htm?category={category}&sortField=GRAVITY&sortOrder=DESC&resultsPerPage=100",
                ]

                page_ok = False
                for url in mkpl_urls:
                    try:
                        page.goto(url, timeout=30000, wait_until="domcontentloaded")
                        page.wait_for_timeout(6000)
                        content = page.content()
                        if any(kw in content.lower() for kw in ["gravity", "commission", "product", "epc"]):
                            logger.info("  תוכן marketplace נמצא ב: %s", url)
                            page_ok = True
                            break
                    except PWTimeout:
                        logger.debug("  Timeout: %s", url)

                if not page_ok:
                    logger.warning("  לא הצלחתי לטעון marketplace לקטגוריה '%s'", category)
                    page.screenshot(path=f"{config.LOG_DIR}/cb_mkpl_{category}_failed.png")
                    continue

                # נסה GraphQL responses שנלכדו
                if graphql_data:
                    offers = _parse_graphql_data(graphql_data, category)
                    if offers:
                        logger.info("  %d הצעות מ-GraphQL", len(offers))
                        all_offers.extend(offers)
                        continue

                # גיבוי: פרסר HTML ישירות
                html = page.content()
                offers = _parse_marketplace_html(html, category)
                if offers:
                    logger.info("  %d הצעות מ-HTML", len(offers))
                    all_offers.extend(offers)
                else:
                    logger.warning("  לא נמצאו הצעות לקטגוריה '%s'", category)
                    page.screenshot(path=f"{config.LOG_DIR}/cb_mkpl_{category}_empty.png")

        except Exception as exc:
            logger.error("שגיאה ב-Playwright: %s", exc, exc_info=True)
        finally:
            browser.close()

    return all_offers


def _parse_graphql_data(responses: list, category: str) -> list:
    """מפרסר תגובות GraphQL מ-ClickBank marketplace."""
    offers = []
    for body in responses:
        # נסה מבנים שונים של GraphQL response
        data = body.get("data", body)
        products = (
            _deep_get(data, "marketplaceSearch", "products")
            or _deep_get(data, "marketplace", "products")
            or _deep_get(data, "affiliateMarketplace", "results")
            or _deep_get(data, "searchResults", "items")
            or []
        )
        for p in products:
            if not isinstance(p, dict):
                continue
            name = p.get("title") or p.get("name") or p.get("productName") or "Unknown"
            offer = _empty_offer(name, category)
            offer.update({
                "gravity": float(p.get("gravity") or p.get("gravityScore") or 0),
                "epc": float(p.get("epc") or p.get("earningsPerClick") or 0),
                "commission": float(p.get("commissionRate") or p.get("commission") or 0),
                "recurring": bool(p.get("recurring") or p.get("hasRecurring")),
                "vendor": str(p.get("vendor") or p.get("vendorId") or ""),
                "offer_link": str(p.get("affiliateLink") or p.get("hopLink") or ""),
                "avg_sale": float(p.get("avgSale") or p.get("averageSaleAmount") or 0),
                "source": "graphql",
            })
            offers.append(offer)
    return offers


def _deep_get(d: dict, *keys):
    """מחלץ ערך מקינון עמוק ב-dict."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _parse_marketplace_html(html: str, category: str) -> list:
    """מפרסר HTML של דף marketplace (mkplSearchResult.htm)."""
    soup = BeautifulSoup(html, "html.parser")
    offers = []

    # נסה סלקטורים שונים לכרטיסי מוצרים
    for sel in ["div.resultItem", "div.product-item", "li.product", "div[class*='result']", "tr.result"]:
        products = soup.select(sel)
        if products:
            logger.debug("  HTML parser: %d מוצרים עם '%s'", len(products), sel)
            break
    else:
        products = []

    for p in products:
        text = p.get_text(" ", strip=True)
        name_el = p.select_one("a.productTitle, .title, h3, h4, .name, a") or p.find("a")
        name = name_el.get_text(strip=True) if name_el else ""
        if not name or len(name) < 3:
            continue

        offer = _empty_offer(name, category)
        offer.update({
            "gravity": _extract_number(text, r"Grav[ity]*[:\s]+([\d.,]+)"),
            "epc": _extract_number(text, r"EPC[:\s]+\$?([\d.,]+)"),
            "commission": _extract_number(text, r"Commission[:\s]*([\d.,]+)\s*%?")
                          or _extract_number(text, r"([\d.,]+)\s*%"),
            "recurring": bool(re.search(r"recurring|rebill|subscription", text, re.I)),
            "offer_link": (p.select_one("a[href]") or {}).get("href", "") if p.select_one("a[href]") else "",
            "source": "html_parse",
        })
        offers.append(offer)

    return offers


# ─────────────────────────────────────────────────────────────────────────────
# אסטרטגיה 2: ClickBank Blog "Top Offers" Parser (ציבורי)
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_via_blog_parser(categories: list) -> list:
    """
    מפרסר את דף הבלוג הציבורי של ClickBank "Top Offers".

    יתרונות: ציבורי לחלוטין, ללא login, ללא bot protection, עובד תמיד.
    חסרונות: מתעדכן פעם בחודש, ~20 הצעות מובילות בלבד, אין Gravity ישיר.

    מחזיר: שם, EPC, APV, Hop Conversion Rate, קטגוריה, קישור, Vendor.
    """
    logger.info("Blog Parser: סורקת %s", BLOG_TOP_OFFERS_URL)

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = requests.get(BLOG_TOP_OFFERS_URL, headers=HTTP_HEADERS, timeout=30)
            resp.raise_for_status()
            break
        except Exception as exc:
            logger.warning("Blog Parser ניסיון %d/%d נכשל: %s", attempt, config.MAX_RETRIES, exc)
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_DELAY)
    else:
        logger.error("Blog Parser: לא הצלחתי לטעון את הדף")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    offers = []

    # הדף בנוי כ-H2 לכל הצעה: "1) Product Name" עם bullet points של נתונים
    offer_headers = [
        h for h in soup.find_all(["h2", "h3"])
        if re.match(r"^\d+\)", h.get_text(strip=True))
    ]
    logger.info("Blog Parser: נמצאו %d כותרות הצעות", len(offer_headers))

    for header in offer_headers:
        offer_name = re.sub(r"^\d+\)\s*", "", header.get_text(strip=True)).strip()
        if not offer_name or len(offer_name) < 3:
            continue

        # אסוף טקסט וקישורים עד לכותרת הבאה
        section_parts = []
        section_links = []
        el = header.next_sibling
        while el:
            tag = getattr(el, "name", None)
            if tag in ["h2", "h3"]:
                break
            if hasattr(el, "get_text") and hasattr(el, "find_all"):
                section_parts.append(el.get_text(" ", strip=True))
                for a in el.find_all("a", href=True):
                    section_links.append(a["href"])
            elif hasattr(el, "get_text"):
                section_parts.append(el.get_text(" ", strip=True))
            elif isinstance(el, str):
                section_parts.append(el.strip())
            el = el.next_sibling
        section_text = " ".join(section_parts)

        # חלץ נתונים
        epc = _extract_number(section_text, r"\*\*EPC[:\*\s]+\$?([\d.]+)")
        if epc == 0.0:
            epc = _extract_number(section_text, r"EPC[:\s]+\$?([\d.]+)")

        apv = _extract_number(section_text, r"\*\*APV[:\*\s]+\$?([\d.]+)")
        if apv == 0.0:
            apv = _extract_number(section_text, r"APV[:\s]+\$?([\d.]+)")

        hop_conv = _extract_number(section_text, r"Hop Conversion Rate[:\s]+([\d.]+)")
        commission = _extract_number(section_text, r"([\d.]+)\s*%\s*commission")
        if commission == 0.0:
            commission = _extract_number(section_text, r"commission[:\s]+([\d.]+)\s*%?")

        recurring = bool(re.search(r"recurring|rebill|subscription|monthly", section_text, re.I))

        vendor_m = re.search(r"Nickname[:\s]+\*?\*?([a-zA-Z0-9_]+)", section_text, re.I)
        vendor = vendor_m.group(1) if vendor_m else ""

        cat_m = re.search(r"Category[:\s]+\*?\*?([^\n\|*]+)", section_text, re.I)
        raw_cat = cat_m.group(1).strip() if cat_m else ""
        combined_text = f"{raw_cat} {offer_name} {section_text[:300]}"
        matched_cat = _map_to_category(combined_text, categories)

        # קישור להצעה (לא ClickBank internal)
        offer_link = ""
        for lnk in section_links:
            if lnk.startswith("http") and "clickbank.com" not in lnk.lower():
                offer_link = lnk
                break
        if not offer_link and section_links:
            offer_link = section_links[0]

        # Gravity מוערך
        est_gravity = _estimate_gravity_from_epc(epc, hop_conv)

        offer = _empty_offer(offer_name, matched_cat)
        offer.update({
            "gravity": est_gravity,
            "epc": epc,
            "commission": commission if commission > 0 else 75.0,  # ממוצע ClickBank
            "recurring": recurring,
            "offer_link": offer_link,
            "vendor": vendor,
            "avg_sale": apv,
            "hop_conversion_rate": hop_conv,
            "source": "blog_top_offers",
        })
        offers.append(offer)
        logger.debug("  Blog: %s | EPC=$%.2f | Gravity~%.0f | Cat=%s",
                     offer_name[:40], epc, est_gravity, matched_cat)

    logger.info("Blog Parser: %d הצעות נמצאו", len(offers))
    return offers


# ─────────────────────────────────────────────────────────────────────────────
# אסטרטגיה 3: ClickBank Analytics REST API
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_via_analytics_api(categories: list) -> list:
    """
    משתמש ב-ClickBank Analytics API הרשמי עם API key.
    מגבלה: מחזיר רק נתוני ביצועים של הצעות שהמשתמשת כבר מקדמת.
    דורש: CB_API_KEY ב-config.py
    """
    api_key = getattr(config, "CB_API_KEY", "")
    if not api_key:
        logger.warning("CB_API_KEY לא הוגדר — מדלג על Analytics API")
        return []

    logger.info("Analytics API: מנסה לשלוף נתונים...")
    headers = {"Authorization": api_key, "Accept": "application/json"}
    offers = []

    try:
        resp = requests.get(
            f"{CB_API_BASE}/analytics/affiliate",
            headers=headers,
            params={"startDate": _days_ago(30), "endDate": _today()},
            timeout=30,
        )
        if resp.status_code == 403:
            logger.warning("Analytics API: 403 — בדקי CB_API_KEY")
            return []
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("data", []):
            vendor = item.get("vendor", "")
            if not vendor:
                continue
            offer = _empty_offer(vendor, categories[0] if categories else "health-fitness")
            offer.update({
                "vendor": vendor,
                "epc": float(item.get("epc") or 0),
                "avg_sale": float(item.get("avgSale") or 0),
                "recurring": bool(item.get("recurring")),
                "source": "analytics_api",
            })
            offers.append(offer)

    except Exception as exc:
        logger.error("Analytics API שגיאה: %s", exc)

    logger.info("Analytics API: %d הצעות", len(offers))
    return offers


# ─────────────────────────────────────────────────────────────────────────────
# פונקציה ראשית — scrape_all()
# ─────────────────────────────────────────────────────────────────────────────

def scrape_all() -> list:
    """
    מריצה את כל אסטרטגיות הסריקה לפי סדר עדיפות ומחזירה רשימה מאוחדת.

    סדר עדיפות:
    1. Playwright + Login (נתונים מלאים, מחייב credentials)
    2. Blog Top Offers (נתונים חלקיים, ציבורי — תמיד רץ כהשלמה)
    3. Analytics API (נתוני ביצועים, מחייב API key)
    """
    # תמיכה בשני פורמטים של CATEGORIES: dict או list
    if isinstance(config.CATEGORIES, dict):
        categories = list(config.CATEGORIES.keys())
    else:
        categories = list(config.CATEGORIES)

    logger.info("מתחיל סריקה. קטגוריות: %s", categories)
    all_offers = []
    strategy_used = []

    # ─── אסטרטגיה 1: Playwright + Login ───
    if getattr(config, "CB_USERNAME", "") and getattr(config, "CB_PASSWORD", ""):
        logger.info("=== אסטרטגיה 1: Playwright + Login ===")
        try:
            offers = _scrape_via_playwright_login(categories)
            if offers:
                logger.info("אסטרטגיה 1: %d הצעות", len(offers))
                all_offers.extend(offers)
                strategy_used.append("playwright_login")
        except Exception as exc:
            logger.error("אסטרטגיה 1 נכשלה: %s", exc)
    else:
        logger.info("מדלג על אסטרטגיה 1 (אין CB_USERNAME/CB_PASSWORD)")

    # ─── אסטרטגיה 2: Blog Parser (תמיד רץ — מוסיף הצעות מובילות) ───
    logger.info("=== אסטרטגיה 2: Blog Top Offers Parser ===")
    try:
        blog_offers = _scrape_via_blog_parser(categories)
        if blog_offers:
            existing_names = {o["product_name"].lower().strip() for o in all_offers}
            new_offers = [o for o in blog_offers if o["product_name"].lower().strip() not in existing_names]
            logger.info("אסטרטגיה 2: %d הצעות חדשות מהבלוג", len(new_offers))
            all_offers.extend(new_offers)
            strategy_used.append("blog_parser")
    except Exception as exc:
        logger.error("אסטרטגיה 2 נכשלה: %s", exc)

    # ─── אסטרטגיה 3: Analytics API ───
    if getattr(config, "CB_API_KEY", "") and not all_offers:
        logger.info("=== אסטרטגיה 3: Analytics API ===")
        try:
            api_offers = _scrape_via_analytics_api(categories)
            if api_offers:
                all_offers.extend(api_offers)
                strategy_used.append("analytics_api")
        except Exception as exc:
            logger.error("אסטרטגיה 3 נכשלה: %s", exc)

    if not all_offers:
        logger.error("כל האסטרטגיות נכשלו — לא נמצאו הצעות")
        return []

    # הסר כפילויות לפי שם
    seen = set()
    unique = []
    for o in all_offers:
        key = o["product_name"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(o)

    logger.info(
        "סריקה הסתיימה: %d הצעות ייחודיות (אסטרטגיות: %s)",
        len(unique), ", ".join(strategy_used)
    )
    return unique
