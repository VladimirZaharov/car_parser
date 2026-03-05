#!/bin/bash
# ============================================================
# install.sh — установка Chrome + ChromeDriver на Ubuntu 21+
# Запускать: bash install.sh
# ============================================================
set -e

echo "=== [1/5] Обновление пакетов ==="
sudo apt-get update -y

echo "=== [2/5] Системные зависимости Chrome ==="
sudo apt-get install -y \
  wget curl gnupg ca-certificates \
  fonts-liberation libappindicator3-1 libasound2 libatk-bridge2.0-0 \
  libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 libexpat1 \
  libfontconfig1 libgbm1 libgcc1 libglib2.0-0 libgtk-3-0 libnspr4 \
  libnss3 libpango-1.0-0 libpangocairo-1.0-0 libstdc++6 libx11-6 \
  libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
  libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 \
  libxtst6 lsb-release xdg-utils unzip xvfb

echo "=== [3/5] Установка Google Chrome ==="
if ! command -v google-chrome &>/dev/null; then
  wget -q -O /tmp/chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y /tmp/chrome.deb || \
    sudo dpkg -i /tmp/chrome.deb && sudo apt-get install -f -y
  rm /tmp/chrome.deb
  echo "Chrome установлен: $(google-chrome --version)"
else
  echo "Chrome уже установлен: $(google-chrome --version)"
fi

echo "=== [4/5] Установка ChromeDriver через webdriver-manager ==="
# webdriver-manager сам скачает chromedriver нужной версии
pip install --break-system-packages webdriver-manager 2>/dev/null || \
  pip install webdriver-manager

echo "=== [5/5] Установка Python-зависимостей ==="
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi
pip install -r requirements.txt

echo ""
echo "=== Проверка ==="
google-chrome --version
python3 -c "
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

opts = Options()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--disable-gpu')
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=opts)
driver.get('https://example.com')
print('Chrome OK! Заголовок:', driver.title)
driver.quit()
"
echo ""
echo "✅ Установка завершена!"
