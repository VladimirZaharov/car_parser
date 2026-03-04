import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import aiohttp
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CarParser:
    def __init__(self, config: dict):
        self.config = config
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    # ------------------------------------------------------------------ #
    #  AVITO                                                               #
    # ------------------------------------------------------------------ #
    def build_avito_url(self, search_params: dict) -> str:
        base = "https://www.avito.ru"
        region = search_params.get("region", "rossiya")
        brand = search_params.get("brand", "").lower().replace(" ", "_")
        model = search_params.get("model", "").lower().replace(" ", "_")

        if brand and model:
            path = f"/{region}/avtomobili/{brand}/{model}"
        elif brand:
            path = f"/{region}/avtomobili/{brand}"
        else:
            path = f"/{region}/avtomobili"

        params = []
        if search_params.get("price_min"):
            params.append(f"pmin={search_params['price_min']}")
        if search_params.get("price_max"):
            params.append(f"pmax={search_params['price_max']}")
        if search_params.get("year_min"):
            params.append(f"params[201][from]={search_params['year_min']}")
        if search_params.get("year_max"):
            params.append(f"params[201][to]={search_params['year_max']}")
        if search_params.get("mileage_max"):
            params.append(f"params[922][to]={search_params['mileage_max']}")

        url = base + path + "/cars"
        if params:
            url += "?" + "&".join(params)
        return url

    def parse_avito(self, search_params: dict) -> list[dict]:
        url = self.build_avito_url(search_params)
        ads = []
        try:
            session = requests.Session()
            resp = session.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Avito item cards
            items = soup.select("div[data-marker='item']")
            if not items:
                items = soup.select("div[class*='iva-item-root']")

            for item in items:
                try:
                    ad = self._extract_avito_ad(item)
                    if ad:
                        ads.append(ad)
                except Exception as e:
                    logger.debug(f"Avito item parse error: {e}")

            logger.info(f"Avito: found {len(ads)} ads for query '{search_params.get('name', url)}'")
        except Exception as e:
            logger.error(f"Avito fetch error: {e}")
        return ads

    def _extract_avito_ad(self, item) -> Optional[dict]:
        # ID
        ad_id = item.get("data-item-id") or item.get("id", "")
        if not ad_id:
            return None

        # Title
        title_el = item.select_one("[itemprop='name'], [class*='title-root'], h3")
        title = title_el.get_text(strip=True) if title_el else "Без названия"

        # Price
        price_el = item.select_one("[itemprop='price'], [class*='price-text'], [class*='price_value']")
        price = price_el.get_text(strip=True) if price_el else "Цена не указана"

        # Link
        link_el = item.select_one("a[href*='/avtomobili/'], a[data-marker='item-title']")
        link = ""
        if link_el:
            href = link_el.get("href", "")
            link = f"https://www.avito.ru{href}" if href.startswith("/") else href

        # Location
        geo_el = item.select_one("[class*='geo-root'], [class*='location'], [data-marker='item-address']")
        location = geo_el.get_text(strip=True) if geo_el else ""

        return {
            "id": f"avito_{ad_id}",
            "source": "Avito",
            "title": title,
            "price": price,
            "url": link,
            "location": location,
            "found_at": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------ #
    #  AUTO.RU                                                             #
    # ------------------------------------------------------------------ #
    def build_autoru_url(self, search_params: dict) -> str:
        brand = search_params.get("brand", "").lower().replace(" ", "_") or "all"
        model = search_params.get("model", "").lower().replace(" ", "_")

        if model:
            base = f"https://auto.ru/cars/used/sale/{brand}/{model}/"
        else:
            base = f"https://auto.ru/cars/used/sale/{brand}/all/"

        params = []
        if search_params.get("price_min"):
            params.append(f"price_from={search_params['price_min']}")
        if search_params.get("price_max"):
            params.append(f"price_to={search_params['price_max']}")
        if search_params.get("year_min"):
            params.append(f"year_from={search_params['year_min']}")
        if search_params.get("year_max"):
            params.append(f"year_to={search_params['year_max']}")
        if search_params.get("mileage_max"):
            params.append(f"km_age_to={search_params['mileage_max']}")

        url = base
        if params:
            url += "?" + "&".join(params)
        return url

    def parse_autoru(self, search_params: dict) -> list[dict]:
        url = self.build_autoru_url(search_params)
        ads = []
        try:
            # auto.ru requires more realistic headers
            headers = {**self.headers, "Referer": "https://auto.ru/"}
            session = requests.Session()
            resp = session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            items = soup.select("div.ListingItem, article.ListingItem, div[class*='ListingItem_']")
            for item in items:
                try:
                    ad = self._extract_autoru_ad(item)
                    if ad:
                        ads.append(ad)
                except Exception as e:
                    logger.debug(f"Auto.ru item parse error: {e}")

            logger.info(f"Auto.ru: found {len(ads)} ads for query '{search_params.get('name', url)}'")
        except Exception as e:
            logger.error(f"Auto.ru fetch error: {e}")
        return ads

    def _extract_autoru_ad(self, item) -> Optional[dict]:
        # Try to get unique ID from link
        link_el = item.select_one("a[href*='/cars/used/sale/']")
        if not link_el:
            return None

        href = link_el.get("href", "")
        # Extract ID from URL like /cars/used/sale/honda/cr_v/123456789-abc/
        id_match = re.search(r"/sale/[^/]+/[^/]+/(\d+-[a-f0-9]+)/", href)
        ad_id = id_match.group(1) if id_match else href

        # Title
        title_el = item.select_one(".ListingItemTitle__link, [class*='ItemTitle'], h3")
        title = title_el.get_text(strip=True) if title_el else "Без названия"

        # Price
        price_el = item.select_one(".ListingItem__priceValue, [class*='Price_'], [class*='price']")
        price = price_el.get_text(strip=True) if price_el else "Цена не указана"

        link = href if href.startswith("http") else f"https://auto.ru{href}"

        # Location
        geo_el = item.select_one(".MetroListPlace__regionName, [class*='Place_'], [class*='place']")
        location = geo_el.get_text(strip=True) if geo_el else ""

        # Year & mileage
        year_el = item.select_one("[class*='year'], .ListingItem__year")
        year = year_el.get_text(strip=True) if year_el else ""

        return {
            "id": f"autoru_{ad_id}",
            "source": "Auto.ru",
            "title": title,
            "price": price,
            "url": link,
            "location": location,
            "year": year,
            "found_at": datetime.now().isoformat(),
        }
