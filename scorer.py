# -*- coding: utf-8 -*-
"""
================================================================================
scorer.py - מודול הניקוד המקומי (ללא AI)
================================================================================

מודול זה מחשב ציון מספרי לכל הצעה על בסיס נתונים כמותיים בלבד.
אין צורך ב-API חיצוני — הכל רץ מקומית, מהיר ודטרמיניסטי.

מודל הניקוד (משקלים):
- EPC (רווח לקליק):       משקל 3.0
- אחוז עמלה:              משקל 2.5
- מנוי חוזר (Recurring):  משקל 2.5
- Gravity:                משקל 2.0
- יציבות / גיל ההצעה:     משקל 1.0

הציון הסופי = ממוצע משוקלל מנורמל לטווח 0-100.
================================================================================
"""

import logging

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


def _generate_summary(product, score, pts):
    """
    יוצר סיכום טקסטואלי קצר בעברית על בסיס הנתונים (ללא AI).
    """
    strengths = []
    weaknesses = []

    if pts["epc"] >= 70:
        strengths.append("EPC גבוה")
    elif pts["epc"] <= 10:
        weaknesses.append("EPC נמוך")

    if pts["commission"] >= 70:
        strengths.append("עמלה גבוהה")
    elif pts["commission"] <= 10:
        weaknesses.append("עמלה נמוכה")

    if pts["recurring"] == 100:
        strengths.append("מנוי חוזר")
    else:
        weaknesses.append("ללא מנוי חוזר")

    if pts["gravity"] >= 70:
        strengths.append("Gravity חזק")
    elif pts["gravity"] <= 10:
        weaknesses.append("Gravity נמוך")

    parts = []
    if strengths:
        parts.append(f"חוזקות: {', '.join(strengths)}")
    if weaknesses:
        parts.append(f"חולשות: {', '.join(weaknesses)}")

    if score >= 75:
        parts.append("הצעה מומלצת מאוד.")
    elif score >= 50:
        parts.append("הצעה סבירה.")
    else:
        parts.append("הצעה חלשה.")

    return " | ".join(parts)


# ==============================================================================
# פונקציות ציבוריות
# ==============================================================================

def score_products(products, use_ai_for_analysis=False):
    """
    מקבל רשימת מוצרים, מחשב ציון לכל אחד, ומוסיף סיכום טקסטואלי.
    מחזיר את הרשימה מועשרת בשדות 'score' ו-'ai_analysis'.
    """
    if not products:
        logger.info("אין מוצרים לניקוד.")
        return []

    logger.info("מתחיל ניקוד של %d מוצרים", len(products))

    scored = []
    for product in products:
        score, pts = compute_local_score(product)
        product["score"] = score
        product["ai_analysis"] = _generate_summary(product, score, pts)

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
