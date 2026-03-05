# 🚗 Car Parser Bot — Selenium Edition

Парсер Avito и Auto.ru через headless Chrome. Обходит 429 и антибот-защиту.

---

## Установка на Ubuntu 21+

### 1. Установить зависимости системы

```bash
sudo apt update && sudo apt upgrade -y

# Python
sudo apt install python3 python3-pip python3-venv -y

# Google Chrome
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install /tmp/chrome.deb -y

# ChromeDriver (совпадает с версией Chrome автоматически через webdriver-manager)
sudo apt install chromium-chromedriver -y
```

### 2. Скопировать файлы проекта

```bash
mkdir -p ~/car_parser
# Скопируйте все файлы в ~/car_parser/
cd ~/car_parser
```

### 3. Создать виртуальное окружение и установить зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Настроить config.json

```bash
nano config.json
```

Обязательно заполните:
- `telegram.bot_token` — токен от @BotFather
- `telegram.chat_id` — ваш Chat ID (узнать: написать боту, открыть `https://api.telegram.org/bot<TOKEN>/getUpdates`)

Параметры Selenium:
| Параметр | Описание | По умолчанию |
|---|---|---|
| `selenium_headless` | `true` = без окна, `false` = с окном | `true` |
| `proxy.url` | Прокси, например `socks5://user:pass@host:1080` | пусто |

### 5. Тестовый запуск

```bash
cd ~/car_parser
source venv/bin/activate
python bot.py
```

Если всё верно — в Telegram придёт:
> ✅ **Парсер запущен!**
> 🌐 Режим: Selenium (headless Chrome)

---

## Автозапуск через systemd

```bash
# Скопировать service-файл
sudo cp ~/car_parser/car_parser.service /etc/systemd/system/

# Заменить YOUR_USERNAME на ваш логин (например ubuntu или user1)
sudo sed -i 's/YOUR_USERNAME/'"$USER"'/g' /etc/systemd/system/car_parser.service

# Включить и запустить
sudo systemctl daemon-reload
sudo systemctl enable car_parser
sudo systemctl start car_parser

# Проверить статус
sudo systemctl status car_parser
```

### Управление сервисом

```bash
sudo systemctl stop car_parser      # остановить
sudo systemctl restart car_parser   # перезапустить
sudo journalctl -u car_parser -f    # логи в реальном времени
tail -f ~/car_parser/car_parser.log # лог приложения
```

---

## Как работает Selenium-режим

1. Для каждого запроса открывается **отдельный экземпляр Chrome**
2. Применяется патч `navigator.webdriver = undefined` — сайт не определяет автоматизацию
3. Страница скроллится вниз (6 шагов) с паузами — имитация человека
4. Данные извлекаются из **JSON-LD** (встроенные данные) или через **CSS-селекторы**
5. При обнаружении капчи — пауза 40 сек + обновление страницы
6. Chrome закрывается после каждого запроса

## Отладка с видимым браузером

Если нужно визуально посмотреть что происходит — установите в config.json:
```json
"selenium_headless": false
```
Для Ubuntu без GUI нужен виртуальный дисплей:
```bash
sudo apt install xvfb -y
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
python bot.py
```

## Устранение неполадок

**`chromedriver` не найден:**
```bash
pip install webdriver-manager
# В parser.py уже используется Service() — он найдёт chromedriver автоматически
# если нужно явно: from webdriver_manager.chrome import ChromeDriverManager
#                  service = Service(ChromeDriverManager().install())
```

**Chrome падает на сервере без GUI:**
Убедитесь что в config.json стоит `"selenium_headless": true`

**Капча не проходит:**
Попробуйте прокси (раздел `proxy.url` в config.json) или увеличьте `interval_minutes` до 60.
