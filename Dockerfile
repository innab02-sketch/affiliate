FROM python:3.11-slim

# התקנת תלויות מערכת ל-Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# התקנת תלויות Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# התקנת Chromium עבור Playwright
RUN playwright install chromium

# העתקת קוד הפרויקט
COPY . .

# יצירת תיקיית לוגים
RUN mkdir -p logs

# הרצת הסקריפט
CMD ["python", "main.py"]
