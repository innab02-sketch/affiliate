#!/bin/bash
# ==============================================================================
# setup.sh - סקריפט עזר להתקנת הסביבה והתלויות
# ==============================================================================

echo "מתחיל התקנת סביבה עבור סוכן ClickBank..."

# יצירת סביבה וירטואלית (מומלץ)
if [ ! -d "venv" ]; then
    echo "יוצר סביבה וירטואלית (venv)..."
    python3 -m venv venv
fi

# הפעלת הסביבה הווירטואלית
source venv/bin/activate

# שדרוג pip
pip install --upgrade pip

# התקנת ספריות Python
echo "מתקין תלויות מתוך requirements.txt..."
pip install -r requirements.txt

# התקנת דפדפן Playwright
echo "מתקין דפדפנים עבור Playwright..."
playwright install chromium
playwright install-deps chromium

echo "ההתקנה הושלמה בהצלחה!"
echo "כדי להריץ את הסקריפט ידנית:"
echo "source venv/bin/activate && python main.py"
