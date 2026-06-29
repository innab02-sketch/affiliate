# -*- coding: utf-8 -*-
"""
================================================================================
scorer.py - מודול הניקוד באמצעות Claude API (Anthropic)
================================================================================

מודול זה שולח את נתוני המוצרים ל-Claude ומקבל בחזרה:
1. ציון מספרי (0-100) לכל הצעה
2. ניתוח קצר בעברית שמסביר את הציון

מודל הניקוד (משקלים):
- EPC (רווח לקליק):    משקל 3.0
- אחוז עמלה:           משקל 2.5
- מנוי חוזר (Recurring): משקל 2.5
- Gravity:             משקל 2.0
- יציבות / גיל ההצעה:   משקל 1.0

הציון הסופי = ממוצע משוקלל מנורמל לטווח 0-100.

הערה: כדי לוודא עקביות ושקיפות, חישוב הציון המספרי מתבצע גם מקומית
(deterministic) וגם דרך Claude. אנו משתמשים בחישוב המקומי כמקור אמת
לציון, וב-Claude לניתוח האיכותני (כדי לחסוך עלויות ולמנוע חוסר עקביות).
ניתן לשנות התנהגות זו דרך הפרמטר use_claude_for_score.
================================================================================
"""

import json
import time
import logging

import anthropic

import config

logger = logging.getLogger("clickbank_scanner.scorer")


# ==============================================================================
# חישוב נקודות לכל קריטריון לפי הטווחים שהוגדרו על ידי המשתמשת
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
    הערה: גיל ההצעה לא תמיד זמין מ-ClickBank ישירות. אם לא ידוע,
    נשתמש בהערכת בסיס לפי Gravity (Gravity גבוה לרוב מעיד על הצעה ותיקה ויציבה).
    """
    if age_months is None:
        # אין נתון גיל - מחזירים ערך ניטרלי בינוני.
        return 70
    if age_months > 12:
        return 100
    if age_months >= 6:
        return 70
    return 40


def compute_local_score(product):
    """
    מחשב את הציון המשוקלל המקומי (0-100) עבור מוצר בודד.
    זהו מקור האמת לציון המספרי.
    """
    weights = config.SCORING_WEIGHTS

    pts = {
        "epc": _score_epc(product.get("epc", 0)),
        "commission": _score_commission(product.get("commission", 0)),
        "recurring": _score_recurring(product.get("recurring", False)),
        "gravity": _score_gravity(product.get("gravity", 0)),
        "stability": _score_stability(product.get("age_months")),
    }

    total_weight = sum(weights.values())
    weighted_sum = sum(pts[k] * weights[k] for k in weights)
    final_score = round(weighted_sum / total_weight, 1)

    return final_score, pts


# ==============================================================================
# ניתוח איכותני באמצעות Claude
# ==============================================================================

SYSTEM_PROMPT = """אתה מומחה לשיווק שותפים (affiliate marketing) ולהערכת הצעות ב-ClickBank.
תפקידך לנתח הצעת מוצר ולספק ניתוח קצר, חד וענייני בעברית (2-3 משפטים),
שמסביר האם זו הצעה מומלצת לקידום, מהן נקודות החוזק והחולשה,
ולמי היא מתאימה. התבסס על הנתונים: EPC, עמלה, מודל מנוי, ו-Gravity.
ענה אך ורק בעברית, בצורה תמציתית ומקצועית."""


def _build_user_prompt(product, score, pts):
    """בונה את ההודעה שתישלח ל-Claude עבור מוצר בודד."""
    recurring_he = "כן" if product.get("recurring") else "לא"
    return f"""נתוני ההצעה:
- שם המוצר: {product.get('product_name')}
- קטגוריה: {product.get('category')}
- Gravity: {product.get('gravity')}
- EPC: ${product.get('epc')}
- אחוז עמלה: {product.get('commission')}%
- מנוי חוזר: {recurring_he}

ציון אוטומטי שחושב: {score}/100
פירוק נקודות: EPC={pts['epc']}, עמלה={pts['commission']}, מנוי={pts['recurring']}, Gravity={pts['gravity']}, יציבות={pts['stability']}

ספק ניתוח קצר בעברית (2-3 משפטים) על ההצעה הזו עבור משווקת שותפים."""


def _analyze_with_claude(client, product, score, pts):
    """
    שולח בקשה ל-Claude לקבלת ניתוח איכותני.
    כולל ניסיונות חוזרים במקרה של כשל.
    מחזיר מחרוזת ניתוח, או הודעת ברירת מחדל במקרה של כשל מתמשך.
    """
    user_prompt = _build_user_prompt(product, score, pts)

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            # חילוץ הטקסט מהתשובה.
            analysis = "".join(
                block.text for block in response.content if hasattr(block, "text")
            ).strip()
            return analysis or "אין ניתוח זמין."
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "כשל בקריאה ל-Claude עבור '%s' (ניסיון %d/%d): %s",
                product.get("product_name"),
                attempt,
                config.MAX_RETRIES,
                exc,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_DELAY)

    return "לא ניתן היה להפיק ניתוח (שגיאת API)."


def score_products(products, use_claude_for_analysis=True):
    """
    מקבל רשימת מוצרים, מחשב ציון לכל אחד, ומוסיף ניתוח מ-Claude.
    מחזיר את הרשימה כשהיא מועשרת בשדות 'score' ו-'ai_analysis'.

    use_claude_for_analysis - אם True, יישלחו בקשות ל-Claude לניתוח איכותני.
                              אם False, ידולג שלב ה-Claude (חוסך עלויות).
    """
    if not products:
        logger.info("אין מוצרים לניקוד.")
        return []

    logger.info("מתחיל ניקוד של %d מוצרים", len(products))

    client = None
    if use_claude_for_analysis:
        try:
            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        except Exception as exc:  # noqa: BLE001
            logger.error("נכשלה אתחול לקוח Claude: %s. ממשיך ללא ניתוח AI.", exc)
            client = None

    scored = []
    for product in products:
        score, pts = compute_local_score(product)
        product["score"] = score

        if client is not None:
            product["ai_analysis"] = _analyze_with_claude(client, product, score, pts)
        else:
            product["ai_analysis"] = "ניתוח AI מושבת."

        scored.append(product)
        logger.debug(
            "מוצר '%s' קיבל ציון %s", product.get("product_name"), score
        )

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
