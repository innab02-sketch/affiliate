# -*- coding: utf-8 -*-
"""
================================================================================
scorer.py - מודול הניקוד באמצעות Gemini API (Google)
================================================================================

מודול זה מחשב ציון מספרי לכל הצעה ושולח את הנתונים ל-Gemini לניתוח איכותני.

מודל הניקוד (משקלים):
- EPC (רווח לקליק):       משקל 3.0
- אחוז עמלה:              משקל 2.5
- מנוי חוזר (Recurring):  משקל 2.5
- Gravity:                משקל 2.0
- יציבות / גיל ההצעה:     משקל 1.0

הציון הסופי = ממוצע משוקלל מנורמל לטווח 0-100.

הערה: הציון המספרי מחושב מקומית (דטרמיניסטי, עקבי ב-100%).
Gemini משמש לניתוח האיכותני בעברית בלבד — חוסך עלויות ומונע אי-עקביות.

הגדרת API Key:
  - ב-config.py: GEMINI_API_KEY = "AIza..."
  - או כמשתנה סביבה: export GEMINI_API_KEY="AIza..."
  - ניתן לקבל מפתח חינמי ב: https://aistudio.google.com/app/apikey
================================================================================
"""

import time
import logging

from google import genai
from google.genai import types

import config

logger = logging.getLogger("clickbank_scanner.scorer")


# ==============================================================================
# חישוב נקודות לכל קריטריון לפי הטווחים שהוגדרו
# ==============================================================================

def _score_epc(epc):
    """ניקוד EPC: >$2=100, $1-2=70, $0.50-1=40, <$0.50=10"""
    if epc > 2:
        return 100
    if epc >= 1:
        return 70
    if epc >= 0.5:
        return 40
    return 10


def _score_commission(commission):
    """ניקוד עמלה: >40%=100, 25-40%=70, 10-25%=40, <10%=10"""
    if commission > 40:
        return 100
    if commission >= 25:
        return 70
    if commission >= 10:
        return 40
    return 10


def _score_recurring(recurring):
    """ניקוד מנוי חוזר: כן=100, לא=0"""
    return 100 if recurring else 0


def _score_gravity(gravity):
    """ניקוד Gravity: >100=100, 50-100=70, 20-50=40, <20=10"""
    if gravity > 100:
        return 100
    if gravity >= 50:
        return 70
    if gravity >= 20:
        return 40
    return 10


def _score_stability(age_months):
    """
    ניקוד יציבות (גיל ההצעה בחודשים):
    >12 חודשים=100, 6-12 חודשים=70, <6 חודשים=40
    אם גיל לא ידוע — מחזיר ערך ניטרלי (70).
    """
    if age_months is None:
        return 70
    if age_months > 12:
        return 100
    if age_months >= 6:
        return 70
    return 40


def compute_local_score(product):
    """
    מחשב את הציון המשוקלל המקומי (0-100) עבור מוצר בודד.
    מחזיר: (final_score: float, pts: dict)
    """
    weights = config.SCORING_WEIGHTS

    pts = {
        "epc":        _score_epc(product.get("epc", 0)),
        "commission": _score_commission(product.get("commission", 0)),
        "recurring":  _score_recurring(product.get("recurring", False)),
        "gravity":    _score_gravity(product.get("gravity", 0)),
        "stability":  _score_stability(product.get("age_months")),
    }

    total_weight = sum(weights.values())
    weighted_sum = sum(pts[k] * weights[k] for k in weights)
    final_score = round(weighted_sum / total_weight, 1)

    return final_score, pts


# ==============================================================================
# ניתוח איכותני באמצעות Gemini API
# ==============================================================================

# הנחיית המערכת ל-Gemini
_SYSTEM_INSTRUCTION = (
    "אתה מומחה לשיווק שותפים (affiliate marketing) ולהערכת הצעות ב-ClickBank. "
    "תפקידך לנתח הצעת מוצר ולספק ניתוח קצר, חד וענייני בעברית (2-3 משפטים), "
    "שמסביר האם זו הצעה מומלצת לקידום, מהן נקודות החוזק והחולשה, "
    "ולמי היא מתאימה. התבסס על הנתונים: EPC, עמלה, מודל מנוי, ו-Gravity. "
    "ענה אך ורק בעברית, בצורה תמציתית ומקצועית."
)


def _build_prompt(product, score, pts):
    """בונה את הפרומפט שיישלח ל-Gemini עבור מוצר בודד."""
    recurring_he = "כן" if product.get("recurring") else "לא"
    return (
        f"נתוני ההצעה:\n"
        f"- שם המוצר: {product.get('product_name')}\n"
        f"- קטגוריה: {product.get('category')}\n"
        f"- Gravity: {product.get('gravity')}\n"
        f"- EPC: ${product.get('epc')}\n"
        f"- אחוז עמלה: {product.get('commission')}%\n"
        f"- מנוי חוזר: {recurring_he}\n"
        f"\n"
        f"ציון אוטומטי שחושב: {score}/100\n"
        f"פירוק נקודות: EPC={pts['epc']}, עמלה={pts['commission']}, "
        f"מנוי={pts['recurring']}, Gravity={pts['gravity']}, יציבות={pts['stability']}\n"
        f"\n"
        f"ספקי ניתוח קצר בעברית (2-3 משפטים) על ההצעה הזו עבור משווקת שותפים."
    )


def _build_gemini_client():
    """
    יוצר לקוח Gemini מאומת.
    מחזיר None אם המפתח חסר או לא תקין.
    """
    api_key = config.GEMINI_API_KEY
    if not api_key or api_key.startswith("AIza-placeholder"):
        logger.warning("GEMINI_API_KEY לא מוגדר. ניתוח AI מושבת.")
        return None
    try:
        client = genai.Client(api_key=api_key)
        return client
    except Exception as exc:  # noqa: BLE001
        logger.error("נכשל אתחול לקוח Gemini: %s", exc)
        return None


def _analyze_with_gemini(client, product, score, pts):
    """
    שולח בקשה ל-Gemini לקבלת ניתוח איכותני בעברית.
    כולל ניסיונות חוזרים במקרה של כשל.
    מחזיר מחרוזת ניתוח, או הודעת ברירת מחדל במקרה של כשל מתמשך.
    """
    prompt = _build_prompt(product, score, pts)

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    max_output_tokens=300,
                    temperature=0.3,   # נמוך = תשובות עקביות ועסקיות
                ),
            )
            analysis = (response.text or "").strip()
            return analysis if analysis else "אין ניתוח זמין."

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "כשל בקריאה ל-Gemini עבור '%s' (ניסיון %d/%d): %s",
                product.get("product_name"),
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_DELAY)

    return "לא ניתן היה להפיק ניתוח (שגיאת Gemini API)."


# ==============================================================================
# פונקציות ציבוריות
# ==============================================================================

def score_products(products, use_ai_for_analysis=True):
    """
    מקבל רשימת מוצרים, מחשב ציון לכל אחד, ומוסיף ניתוח מ-Gemini.
    מחזיר את הרשימה מועשרת בשדות 'score' ו-'ai_analysis'.

    use_ai_for_analysis — אם True, יישלחו בקשות ל-Gemini לניתוח איכותני.
                          אם False, ידולג שלב ה-AI (חוסך עלויות/מכסה).
    """
    if not products:
        logger.info("אין מוצרים לניקוד.")
        return []

    logger.info("מתחיל ניקוד של %d מוצרים", len(products))

    # אתחול לקוח Gemini פעם אחת לכל הסשן
    client = None
    if use_ai_for_analysis:
        client = _build_gemini_client()
        if client is None:
            logger.warning("ממשיך ללא ניתוח Gemini (אין לקוח תקין).")

    scored = []
    for product in products:
        score, pts = compute_local_score(product)
        product["score"] = score

        if client is not None:
            product["ai_analysis"] = _analyze_with_gemini(client, product, score, pts)
            # Rate limiting: 10 RPM = max 1 request per 6 seconds
            time.sleep(7)
        else:
            product["ai_analysis"] = "ניתוח AI מושבת (הגדירי GEMINI_API_KEY)."

        scored.append(product)
        logger.debug("מוצר '%s' קיבל ציון %s", product.get("product_name"), score)

    logger.info("הניקוד הסתיים.")
    return scored


def filter_by_threshold(products, threshold=None):
    """
    מסנן את המוצרים ומחזיר רק את אלה שעברו את סף הניקוד.
    ממיין מהציון הגבוה לנמוך.
    """
    if threshold is None:
        threshold = config.SCORE_THRESHOLD

    kept = [p for p in products if p.get("score", 0) >= threshold]
    kept.sort(key=lambda p: p.get("score", 0), reverse=True)

    logger.info(
        "%d מתוך %d הצעות עברו את סף הניקוד (%d)",
        len(kept),
        len(products),
        threshold,
    )
    return kept
