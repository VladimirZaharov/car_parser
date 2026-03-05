"""
bot.py  —  Telegram-бот + планировщик
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError

from parser import CarParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("car_parser.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

SEEN_IDS_FILE = "seen_ids.json"


def load_seen_ids() -> set:
    if Path(SEEN_IDS_FILE).exists():
        with open(SEEN_IDS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids: set):
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(list(ids), f)


def load_config(path: str = "config.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def send_tg(bot: Bot, chat_id: str, text: str):
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    except TelegramError as e:
        logger.error(f"Telegram send error: {e}")


def format_ad(ad: dict, query_name: str) -> str:
    source_emoji = "🟠" if ad["source"] == "Avito" else "🔵"
    lines = [
        f"{source_emoji} <b>Новое объявление!</b>  [{ad['source']}]",
        f"🔍 <i>{query_name}</i>",
        f"📋 {ad['title']}",
        f"💰 {ad['price']}",
    ]
    if ad.get("year"):
        lines.append(f"📅 Год: {ad['year']}")
    if ad.get("mileage"):
        lines.append(f"🛣 Пробег: {ad['mileage']} км")
    if ad.get("location"):
        lines.append(f"📍 {ad['location']}")
    lines.append(f'🔗 <a href="{ad["url"]}">Открыть объявление</a>')
    lines.append(f"⏰ {ad['found_at'][:19].replace('T', ' ')}")
    return "\n".join(lines)


async def run_once(config: dict, bot: Bot, seen_ids: set) -> int:
    # Selenium блокирует event loop — запускаем в отдельном потоке
    loop      = asyncio.get_event_loop()
    car_parser = CarParser(config)
    chat_id   = config["telegram"]["chat_id"]
    new_count = 0

    for query in config["search_queries"]:
        name    = query.get("name", "—")
        sources = query.get("sources", ["avito", "autoru"])
        all_ads = []

        if "avito" in sources:
            avito_ads = await loop.run_in_executor(
                None, car_parser.parse_avito, query
            )
            all_ads.extend(avito_ads)

        # Небольшая пауза между сайтами
        await asyncio.sleep(3)

        if "autoru" in sources:
            autoru_ads = await loop.run_in_executor(
                None, car_parser.parse_autoru, query
            )
            all_ads.extend(autoru_ads)

        for ad in all_ads:
            if ad["id"] not in seen_ids:
                seen_ids.add(ad["id"])
                await send_tg(bot, chat_id, format_ad(ad, name))
                new_count += 1
                logger.info(f"  ↑ новое: {ad['id']} — {ad['title']}")
                await asyncio.sleep(1.2)

    save_seen_ids(seen_ids)
    logger.info(f"Скан завершён. Новых объявлений: {new_count}")
    return new_count


async def main():
    config   = load_config()
    interval = config.get("interval_minutes", 30)
    bot      = Bot(token=config["telegram"]["bot_token"])

    try:
        me = await bot.get_me()
        logger.info(f"Бот запущен: @{me.username}")
    except TelegramError as e:
        logger.error(f"Не удалось подключиться к Telegram: {e}")
        return

    seen_ids = load_seen_ids()
    logger.info(f"Загружено {len(seen_ids)} ранее виденных ID")

    chat_id = config["telegram"]["chat_id"]
    await send_tg(
        bot, chat_id,
        f"✅ <b>Парсер запущен!</b>\n"
        f"📊 Запросов: {len(config['search_queries'])}\n"
        f"⏱ Интервал: каждые {interval} мин.\n"
        f"🌐 Режим: Selenium (headless Chrome)",
    )

    logger.info(f"Цикл опроса запущен, интервал={interval} мин")
    while True:
        try:
            await run_once(config, bot, seen_ids)
        except Exception as e:
            logger.error(f"Ошибка во время скана: {e}", exc_info=True)
        logger.info(f"Следующий скан через {interval} мин...")
        await asyncio.sleep(interval * 60)


if __name__ == "__main__":
    asyncio.run(main())
