# 🚗 Car Parser Bot — Руководство по установке

## Требования
- Ubuntu 21+ (или 20.04 LTS)
- Python 3.9+
- Telegram бот (получить у @BotFather)

---

## Шаг 1 — Получить Telegram токен и Chat ID

### 1.1 Создать бота
1. Открыть Telegram → найти **@BotFather**
2. Отправить `/newbot`
3. Придумать имя и username для бота
4. Скопировать **токен** (вида `123456789:ABCdef...`)

### 1.2 Узнать Chat ID
1. Написать своему боту любое сообщение
2. Открыть в браузере:
   ```
   https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates
   ```
3. Найти поле `"chat":{"id": XXXXXXXXX}` — это ваш **Chat ID**

> Для группы: добавьте бота в группу, напишите сообщение,
> Chat ID будет отрицательным числом, например `-1001234567890`

---

## Шаг 2 — Установка на Ubuntu

```bash
# Обновить пакеты
sudo apt update && sudo apt upgrade -y

# Установить Python и pip
sudo apt install python3 python3-pip python3-venv git -y

# Клонировать / скопировать проект
mkdir -p ~/car_parser
# Скопируйте все файлы проекта в ~/car_parser/
cd ~/car_parser

# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
```

---

## Шаг 3 — Настройка config.json

Отредактируйте файл `config.json`:

```bash
nano ~/car_parser/config.json
```

Заполните:
```json
{
  "telegram": {
    "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    "chat_id": "987654321"
  },
  "interval_minutes": 30,
  "search_queries": [
    {
      "name": "Toyota Camry Москва",
      "sources": ["avito", "autoru"],
      "brand": "toyota",
      "model": "camry",
      "year_min": 2018,
      "price_max": 2000000,
      "region": "moskva"
    }
  ]
}
```

### Параметры запроса:
| Параметр | Описание | Пример |
|---|---|---|
| `name` | Название запроса для уведомлений | `"Toyota Camry"` |
| `sources` | Площадки для парсинга | `["avito", "autoru"]` |
| `brand` | Марка авто (латиницей) | `"toyota"`, `"bmw"`, `"honda"` |
| `model` | Модель (латиницей) | `"camry"`, `"x5"`, `"cr-v"` |
| `year_min` | Год от | `2018` |
| `year_max` | Год до | `2023` |
| `price_min` | Цена от (руб) | `500000` |
| `price_max` | Цена до (руб) | `2000000` |
| `mileage_max` | Пробег до (км) | `100000` |
| `region` | Регион Avito | `"moskva"`, `"rossiya"` |

---

## Шаг 4 — Тестовый запуск

```bash
cd ~/car_parser
source venv/bin/activate
python bot.py
```

Если всё настроено правильно — в Telegram придёт сообщение:
> ✅ **Парсер запущен!**

---

## Шаг 5 — Автозапуск через systemd

```bash
# Скопировать service-файл (замените YOUR_USERNAME на своё имя пользователя)
sudo cp ~/car_parser/car_parser.service /etc/systemd/system/

# Отредактировать service-файл — вставить правильный username
sudo nano /etc/systemd/system/car_parser.service
# Замените оба вхождения YOUR_USERNAME на своё имя пользователя Ubuntu

# Активировать и запустить
sudo systemctl daemon-reload
sudo systemctl enable car_parser
sudo systemctl start car_parser

# Проверить статус
sudo systemctl status car_parser
```

### Управление сервисом:
```bash
sudo systemctl stop car_parser      # остановить
sudo systemctl restart car_parser   # перезапустить
sudo journalctl -u car_parser -f    # смотреть логи в реальном времени
```

---

## Просмотр логов

```bash
# Лог приложения
tail -f ~/car_parser/car_parser.log

# Системный лог
sudo journalctl -u car_parser -n 50
```

---

## Устранение неполадок

### Бот не отправляет сообщения
- Проверьте токен и chat_id в `config.json`
- Убедитесь что вы написали боту хотя бы одно сообщение

### Объявления не находятся
- Avito и Auto.ru могут блокировать запросы — это нормально
- Парсер повторит попытку на следующем цикле
- Попробуйте увеличить `interval_minutes` до 60

### Ошибка при установке зависимостей
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚠️ Важно

Парсинг Avito и Auto.ru может нарушать их **условия использования**.
Используйте бота в личных некоммерческих целях и с разумными интервалами
(не чаще 1 раза в 15 минут), чтобы не перегружать серверы.
