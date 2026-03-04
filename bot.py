import asyncio
import json
import logging
import os
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
        f"🚗 <b>Новое объявление!</b> [{ad['source']}]",
        f"🔍 Запрос: <i>{query_name}</i>",
        f"📋 {ad['title']}",
        f"💰 {ad['price']}",
    ]
    if ad.get("year"):
        lines.append(f"📅 Год: {ad['year']}")
    if ad.get("location"):
        lines.append(f"📍 {ad['location']}")
    lines.append(f"🔗 <a href=\"{ad['url']}\">Открыть объявление</a>")
    lines.append(f"⏰ {ad['found_at'][:19].replace('T', ' ')}")
    return "\n".join(lines)


async def run_once(config: dict, bot: Bot, seen_ids: set):
    car_parser = CarParser(config)
    chat_id = config["telegram"]["chat_id"]
    new_count = 0

    for query in config["search_queries"]:
        query_name = query.get("name", "Без имени")
        sources = query.get("sources", ["avito", "autoru"])

        all_ads = []

        if "avito" in sources:
            ads = car_parser.parse_avito(query)
            all_ads.extend(ads)

        if "autoru" in sources:
            ads = car_parser.parse_autoru(query)
            all_ads.extend(ads)

        for ad in all_ads:
            if ad["id"] not in seen_ids:
                seen_ids.add(ad["id"])
                msg = format_ad_message(ad, query_name)
                await send_telegram_message(bot, chat_id, msg)
                new_count += 1
                logger.info(f"New ad sent: {ad['id']} — {ad['title']}")
                # Small delay between messages to avoid flood limit
                await asyncio.sleep(1)

    save_seen_ids(seen_ids)
    logger.info(f"Scan complete. New ads found: {new_count}")
    return new_count


async def main():
    config = load_config()
    interval_minutes = config.get("interval_minutes", 60)
    bot_token = config["telegram"]["bot_token"]

    bot = Bot(token=bot_token)

    # Verify bot connection
    try:
        me = await bot.get_me()
        logger.info(f"Bot started: @{me.username}")
    except TelegramError as e:
        logger.error(f"Cannot connect to Telegram: {e}")
        return

    seen_ids = load_seen_ids()
    logger.info(f"Loaded {len(seen_ids)} previously seen ad IDs")

    # Send startup notification
    chat_id = config["telegram"]["chat_id"]
    await send_telegram_message(
        bot,
        chat_id,
        f"✅ <b>Парсер запущен!</b>\n"
        f"📊 Запросов: {len(config['search_queries'])}\n"
        f"⏱ Интервал: каждые {interval_minutes} мин.",
    )

    logger.info(f"Starting polling loop, interval={interval_minutes} min")

    while True:
        try:
            await run_once(config, bot, seen_ids)
        except Exception as e:
            logger.error(f"Error during scan: {e}", exc_info=True)

        logger.info(f"Sleeping {interval_minutes} minutes until next scan...")
        await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    asyncio.run(main())
