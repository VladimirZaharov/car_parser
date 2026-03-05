import asyncio
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path

import telegram
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


async def send_telegram_message(bot: Bot, chat_id: str, text: str):
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    except TelegramError as e:
        logger.error(f"Telegram send error: {e}")


def format_ad_message(ad: dict, query_name: str) -> str:
    lines = [
        f"🚗 <b>Новое объявление!</b>  [{ad['source']}]",
        f"🔍 <i>{query_name}</i>",
        f"",
        f"📋 <b>{ad['title']}</b>",
        f"💰 {ad['price']}",
    ]
    if ad.get("mileage"):
        lines.append(f"🔢 Пробег: {ad['mileage']}")
    if ad.get("location"):
        lines.append(f"📍 {ad['location']}")
    lines.append(f"")
    lines.append(f"🔗 <a href=\"{ad['url']}\">Открыть объявление →</a>")
    lines.append(f"<i>⏰ {ad['found_at'][:19].replace('T', ' ')}</i>")
    return "\n".join(lines)


async def run_once(config: dict, bot: Bot, seen_ids: set) -> int:
    car_parser = CarParser(config)
    chat_id = config["telegram"]["chat_id"]
    new_count = 0

    for query in config["search_queries"]:
        query_name = query.get("name", "Без имени")
        sources = query.get("sources", ["avito", "autoru"])

        # Avito
        if "avito" in sources:
            ads = car_parser.parse_avito(query)
            for ad in ads:
                if ad["id"] not in seen_ids:
                    seen_ids.add(ad["id"])
                    msg = format_ad_message(ad, query_name)
                    await send_telegram_message(bot, chat_id, msg)
                    new_count += 1
                    await asyncio.sleep(1.5)

            # Пауза между Avito и Auto.ru для одного запроса
            if "autoru" in sources:
                delay = random.uniform(5, 12)
                logger.debug(f"Пауза {delay:.1f}s между источниками...")
                await asyncio.sleep(delay)

        # Auto.ru
        if "autoru" in sources:
            ads = car_parser.parse_autoru(query)
            for ad in ads:
                if ad["id"] not in seen_ids:
                    seen_ids.add(ad["id"])
                    msg = format_ad_message(ad, query_name)
                    await send_telegram_message(bot, chat_id, msg)
                    new_count += 1
                    await asyncio.sleep(1.5)

        # Пауза между запросами (важно для Avito!)
        delay = random.uniform(8, 20)
        logger.debug(f"Пауза {delay:.1f}s перед следующим запросом...")
        await asyncio.sleep(delay)

    save_seen_ids(seen_ids)
    logger.info(f"Скан завершён. Новых объявлений: {new_count}")
    return new_count


async def main():
    config = load_config()
    interval_minutes = config.get("interval_minutes", 60)
    bot_token = config["telegram"]["bot_token"]

    bot = Bot(token=bot_token)

    try:
        me = await bot.get_me()
        logger.info(f"Бот запущен: @{me.username}")
    except TelegramError as e:
        logger.error(f"Не удалось подключиться к Telegram: {e}")
        return

    seen_ids = load_seen_ids()
    logger.info(f"Загружено {len(seen_ids)} ранее виденных ID")

    chat_id = config["telegram"]["chat_id"]
    queries_info = "\n".join(
        f"  • {q.get('name', '?')} [{', '.join(q.get('sources', ['avito','autoru']))}]"
        for q in config["search_queries"]
    )
    await send_telegram_message(
        bot,
        chat_id,
        f"✅ <b>Парсер запущен!</b>\n\n"
        f"📊 Запросов: {len(config['search_queries'])}\n"
        f"{queries_info}\n\n"
        f"⏱ Интервал: каждые {interval_minutes} мин.",
    )

    logger.info(f"Цикл опроса запущен, интервал={interval_minutes} мин")

    while True:
        try:
            await run_once(config, bot, seen_ids)
        except Exception as e:
            logger.error(f"Ошибка при сканировании: {e}", exc_info=True)

        logger.info(f"Ждём {interval_minutes} минут до следующего скана...")
        await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    asyncio.run(main())
