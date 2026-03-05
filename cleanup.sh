#!/bin/bash
# ============================================================
# cleanup.sh — полная очистка Chrome, ChromeDriver, парсера
# Запускать: bash cleanup.sh
# ============================================================

echo "=== [1/6] Удаление Google Chrome ==="
sudo apt-get remove --purge -y google-chrome-stable 2>/dev/null || true
sudo apt-get remove --purge -y google-chrome 2>/dev/null || true
sudo rm -f /etc/apt/sources.list.d/google-chrome*.list
sudo rm -f /etc/apt/trusted.gpg.d/google*.gpg
sudo rm -f /usr/share/keyrings/google*.gpg

echo "=== [2/6] Удаление Chromium и chromedriver ==="
sudo apt-get remove --purge -y chromium-browser chromium chromium-chromedriver 2>/dev/null || true
sudo rm -f /usr/local/bin/chromedriver
sudo rm -f /usr/bin/chromedriver

echo "=== [3/6] Удаление Python-пакетов и venv ==="
# Удаляем виртуальное окружение если есть
rm -rf ~/car_parser/venv 2>/dev/null || true
rm -rf ~/car_parser/env 2>/dev/null || true

# Удаляем системные pip-пакеты если ставились напрямую
pip3 uninstall -y selenium webdriver-manager beautifulsoup4 lxml \
  python-telegram-bot httpx anyio 2>/dev/null || true

echo "=== [4/6] Удаление кэша webdriver-manager ==="
rm -rf ~/.wdm 2>/dev/null || true
rm -rf /root/.wdm 2>/dev/null || true

echo "=== [5/6] Удаление файлов парсера ==="
echo "Папка парсера: ~/car_parser"
read -p "Удалить ~/car_parser полностью? (y/N): " confirm
if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
  rm -rf ~/car_parser
  echo "Папка удалена."
else
  echo "Папка оставлена."
fi

echo "=== [6/6] Удаление systemd-сервиса ==="
sudo systemctl stop car_parser 2>/dev/null || true
sudo systemctl disable car_parser 2>/dev/null || true
sudo rm -f /etc/systemd/system/car_parser.service
sudo systemctl daemon-reload

echo "=== Финальная очистка apt ==="
sudo apt-get autoremove -y
sudo apt-get autoclean -y

echo ""
echo "✅ Всё очищено!"
echo ""
echo "Что осталось (если нужно убрать вручную):"
echo "  - Python 3 и pip (системные, не трогали)"
echo "  - ~/.cache/pip  (кэш pip, можно: rm -rf ~/.cache/pip)"
