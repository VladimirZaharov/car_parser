#!/bin/bash
# ============================================================
# install.sh — установка Chrome + ChromeDriver на Ubuntu 21+
# Запускать: bash install.sh
# ============================================================
set -e

echo "=== [1/6] Обновление пакетов ==="
sudo apt-get update -y

echo "=== [2/6] Системные зависимости Chrome ==="
sudo apt-get install -y \
  wget curl gnupg ca-certificates unzip xvfb \
  fonts-liberation libappindicator3-1 libasound2 libatk-bridge2.0-0 \
  libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 libexpat1 \
  libfontconfig1 libgbm1 libgcc1 libglib2.0-0 libgtk-3-0 libnspr4 \
  libnss3 libpango-1.0-0 libpangocairo-1.0-0 libstdc++6 libx11-6 \
  libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
  libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 \
  libxtst6 lsb-release xdg-utils

echo "=== [3/6] Установка Google Chrome ==="
if ! command -v google-chrome &>/dev/null; then
  wget -q -O /tmp/chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y /tmp/chrome.deb || \
    (sudo dpkg -i /tmp/chrome.deb; sudo apt-get install -f -y)
  rm -f /tmp/chrome.deb
fi
CHROME_VER=$(google-chrome --version | grep -oP '[\d.]+')
echo "Chrome: $CHROME_VER"

echo "=== [4/6] Установка ChromeDriver ==="
# Скачиваем ChromeDriver точно под версию Chrome
CHROME_MAJOR=$(echo "$CHROME_VER" | cut -d. -f1)
echo "Определяем ChromeDriver для Chrome $CHROME_MAJOR..."

# Chrome 115+ — новый API для скачивания драйверов
if [ "$CHROME_MAJOR" -ge 115 ]; then
  JSON_URL="https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
  # Ищем точное совпадение версии, иначе берём последний для этого major
  DRIVER_URL=$(curl -s "$JSON_URL" | python3 -c "
import sys, json
data = json.load(sys.stdin)
target = '$CHROME_VER'
major  = '$CHROME_MAJOR'
best_url = ''
best_ver = ''
for v in data.get('versions', []):
    ver = v.get('version','')
    if not ver.startswith(major + '.'):
        continue
    for dl in v.get('downloads', {}).get('chromedriver', []):
        if dl.get('platform') == 'linux64':
            best_url = dl['url']
            best_ver = ver
# last match wins (newest patch)
print(best_url)
" 2>/dev/null)

  if [ -n "$DRIVER_URL" ]; then
    echo "Скачиваем ChromeDriver: $DRIVER_URL"
    wget -q -O /tmp/chromedriver.zip "$DRIVER_URL"
    sudo unzip -o /tmp/chromedriver.zip -d /tmp/cd_extract/
    DRIVER_BIN=$(find /tmp/cd_extract/ -name "chromedriver" -type f | head -1)
    sudo mv "$DRIVER_BIN" /usr/local/bin/chromedriver
    sudo chmod +x /usr/local/bin/chromedriver
    rm -rf /tmp/chromedriver.zip /tmp/cd_extract/
    echo "ChromeDriver установлен: $(chromedriver --version)"
  else
    echo "Не удалось найти ChromeDriver через API, пробуем apt..."
    sudo apt-get install -y chromium-chromedriver 2>/dev/null || true
  fi
else
  # Chrome < 115 — старый API
  DRIVER_VER=$(curl -s "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_MAJOR}")
  wget -q -O /tmp/chromedriver.zip \
    "https://chromedriver.storage.googleapis.com/${DRIVER_VER}/chromedriver_linux64.zip"
  sudo unzip -o /tmp/chromedriver.zip -d /usr/local/bin/
  sudo chmod +x /usr/local/bin/chromedriver
  rm -f /tmp/chromedriver.zip
  echo "ChromeDriver установлен: $(chromedriver --version)"
fi

echo "=== [5/6] Python-зависимости ==="
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
  echo "(используем venv)"
fi
pip install -r requirements.txt

echo "=== [6/6] Проверка запуска Chrome ==="
python3 - << 'PYCHECK'
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
opts.add_argument("--disable-software-rasterizer")
opts.add_argument("--window-size=1920,1080")

# Пробуем chromedriver из PATH (установлен выше через apt/wget)
import shutil
driver_path = shutil.which("chromedriver")
if not driver_path:
    print("ОШИБКА: chromedriver не найден в PATH!")
    sys.exit(1)

print(f"Используем chromedriver: {driver_path}")
service = Service(driver_path)
driver  = webdriver.Chrome(service=service, options=opts)
driver.get("https://example.com")
print(f"Chrome OK! Заголовок: {driver.title}")
driver.quit()
PYCHECK

echo ""
echo "✅ Установка завершена! Запускайте: python bot.py"
