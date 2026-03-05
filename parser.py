import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
#  Пул User-Agent для ротации
# ──────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _sleep(min_s: float = 3.0, max_s: float = 8.0):
    """Случайная пауза между запросами, чтобы не триггерить rate-limit."""
    delay = random.uniform(min_s, max_s)
    logger.debug(f"Sleeping {delay:.1f}s...")
    time.sleep(delay)


# ──────────────────────────────────────────────────────────────
class CarParser:
    def __init__(self, config: dict):
        self.config = config

    # ============================================================
    #  AVITO
    # ============================================================
    def _avito_session(self) -> requests.Session:
        s = requests.Session()
        ua = _random_ua()
        s.headers.update(
            {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
        )
        # Получаем куки с главной страницы (имитируем первый заход)
        try:
            s.get("https://www.avito.ru/", timeout=15)
            _sleep(1.5, 3.0)
        except Exception:
            pass
        return s

    def build_avito_url(self, search_params: dict) -> str:
        region = search_params.get("region", "rossiya")
        brand = search_params.get("brand", "").lower().replace(" ", "_")
        model = search_params.get("model", "").lower().replace(" ", "_")

        if brand and model:
            path = f"/{region}/avtomobili/{brand}/{model}/cars"
        elif brand:
            path = f"/{region}/avtomobili/{brand}/cars"
        else:
            path = f"/{region}/avtomobili/cars"

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

        url = "https://www.avito.ru" + path
        if params:
            url += "?" + "&".join(params)
        return url

    def parse_avito(self, search_params: dict) -> list[dict]:
        url = self.build_avito_url(search_params)
        ads = []
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                session = self._avito_session()
                resp = session.get(url, timeout=30, allow_redirects=True)

                if resp.status_code == 429:
                    wait = 60 * attempt  # 60, 120, 180 сек
                    logger.warning(
                        f"Avito 429 (попытка {attempt}/{max_retries}). "
                        f"Ждём {wait}s..."
                    )
                    time.sleep(wait)
                    continue

                if resp.status_code == 403:
                    logger.warning("Avito 403 — возможно, нужен прокси. Пропускаем.")
                    break

                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                # Avito рендерит данные в JSON внутри <script>
                ads = self._parse_avito_json_state(soup)

                if not ads:
                    # Fallback: HTML-парсинг
                    ads = self._parse_avito_html(soup)

                logger.info(
                    f"Avito: найдено {len(ads)} объявлений "
                    f"для '{search_params.get('name', '')}'"
                )
                break

            except requests.exceptions.HTTPError as e:
                logger.error(f"Avito HTTP ошибка: {e}")
                break
            except Exception as e:
                logger.error(f"Avito ошибка (попытка {attempt}): {e}")
                if attempt < max_retries:
                    _sleep(10, 20)

        return ads

    def _parse_avito_json_state(self, soup: BeautifulSoup) -> list[dict]:
        """Avito вкладывает данные листинга в window.__initialData__ или похожий JSON."""
        ads = []
        for script in soup.find_all("script"):
            text = script.string or ""
            # Пробуем найти массив items в JSON-данных страницы
            match = re.search(r'"items"\s*:\s*(\[.*?\])\s*[,}]', text, re.DOTALL)
            if not match:
                continue
            try:
                items_raw = json.loads(match.group(1))
                for item in items_raw:
                    ad = self._map_avito_json_item(item)
                    if ad:
                        ads.append(ad)
                if ads:
                    break
            except Exception:
                continue
        return ads

    def _map_avito_json_item(self, item: dict) -> Optional[dict]:
        ad_id = str(item.get("id", ""))
        if not ad_id:
            return None
        title = item.get("title", "Без названия")
        price_obj = item.get("priceDetailed") or item.get("price", {})
        if isinstance(price_obj, dict):
            price = price_obj.get("string") or price_obj.get("value", "Цена не указана")
        else:
            price = str(price_obj) if price_obj else "Цена не указана"
        url_part = item.get("urlPath", "")
        link = f"https://www.avito.ru{url_part}" if url_part else ""
        location = item.get("location", {}).get("name", "") if isinstance(item.get("location"), dict) else ""
        return {
            "id": f"avito_{ad_id}",
            "source": "Avito",
            "title": title,
            "price": str(price),
            "url": link,
            "location": location,
            "found_at": datetime.now().isoformat(),
        }

    def _parse_avito_html(self, soup: BeautifulSoup) -> list[dict]:
        ads = []
        items = soup.select("div[data-marker='item']")
        if not items:
            items = soup.select("div[class*='iva-item-root']")
        for item in items:
            try:
                ad = self._extract_avito_html_item(item)
                if ad:
                    ads.append(ad)
            except Exception as e:
                logger.debug(f"Avito HTML item error: {e}")
        return ads

    def _extract_avito_html_item(self, item) -> Optional[dict]:
        ad_id = item.get("data-item-id") or item.get("id", "")
        if not ad_id:
            return None
        title_el = item.select_one("[itemprop='name'], [class*='title-root'], h3")
        title = title_el.get_text(strip=True) if title_el else "Без названия"
        price_el = item.select_one("[itemprop='price'], [class*='price-text'], [class*='price_value']")
        price = price_el.get_text(strip=True) if price_el else "Цена не указана"
        link_el = item.select_one("a[data-marker='item-title'], a[href*='/avtomobili/']")
        link = ""
        if link_el:
            href = link_el.get("href", "")
            link = f"https://www.avito.ru{href}" if href.startswith("/") else href
        geo_el = item.select_one("[data-marker='item-address'], [class*='geo-root']")
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

    # ============================================================
    #  AUTO.RU  — через публичный API (search)
    # ============================================================
    # Auto.ru использует внутренний REST API, который возвращает JSON.
    # Он не требует авторизации для базового поиска.

    _AUTORU_API = "https://auto.ru/-/ajax/desktop/listing/"

    # Словарь категорий марок для API auto.ru
    # (если марки нет — используем поиск по параметрам)

    def _autoru_api_payload(self, search_params: dict) -> dict:
        brand = search_params.get("brand", "").upper()
        model = search_params.get("model", "").upper().replace("-", "_")

        payload: dict = {
            "category": "cars",
            "section": "used",
            "output_type": "list",
            "page": 1,
            "page_size": 50,
        }

        if brand:
            payload["catalog_filter"] = [{"mark": brand, "model": model} if model else {"mark": brand}]

        if search_params.get("price_min"):
            payload["price_from"] = int(search_params["price_min"])
        if search_params.get("price_max"):
            payload["price_to"] = int(search_params["price_max"])
        if search_params.get("year_min"):
            payload["year_from"] = int(search_params["year_min"])
        if search_params.get("year_max"):
            payload["year_to"] = int(search_params["year_max"])
        if search_params.get("mileage_max"):
            payload["km_age_to"] = int(search_params["mileage_max"])

        return payload

    def parse_autoru(self, search_params: dict) -> list[dict]:
        ads = []
        payload = self._autoru_api_payload(search_params)
        headers = {
            "User-Agent": _random_ua(),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://auto.ru/",
            "Origin": "https://auto.ru",
            "x-client-app-version": "202403.01.0",
            "x-page-request-id": "".join(random.choices("0123456789abcdef", k=32)),
        }

        try:
            resp = requests.post(
                self._AUTORU_API,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if resp.status_code in (401, 403):
                # Fallback на HTML-парсинг если API закрыт
                logger.warning("Auto.ru API вернул 403, пробуем HTML-парсинг...")
                return self._parse_autoru_html(search_params)

            resp.raise_for_status()
            data = resp.json()

            offers = data.get("offers", [])
            for offer in offers:
                ad = self._map_autoru_offer(offer)
                if ad:
                    ads.append(ad)

            logger.info(
                f"Auto.ru API: найдено {len(ads)} объявлений "
                f"для '{search_params.get('name', '')}'"
            )

        except requests.exceptions.JSONDecodeError:
            logger.warning("Auto.ru API вернул не JSON, пробуем HTML...")
            return self._parse_autoru_html(search_params)
        except Exception as e:
            logger.error(f"Auto.ru API ошибка: {e}")
            return self._parse_autoru_html(search_params)

        return ads

    def _map_autoru_offer(self, offer: dict) -> Optional[dict]:
        ad_id = offer.get("id", "")
        if not ad_id:
            return None

        # Название: марка + модель + год
        car = offer.get("vehicle_info", {})
        mark = car.get("mark_info", {}).get("name", "")
        model = car.get("model_info", {}).get("name", "")
        year = str(offer.get("documents", {}).get("year", ""))
        title = " ".join(filter(None, [mark, model, year])) or "Авто"

        # Цена
        price_info = offer.get("price_info", {})
        price_rub = price_info.get("price", 0)
        price = f"{price_rub:,}".replace(",", " ") + " ₽" if price_rub else "Цена не указана"

        # Ссылка
        link = offer.get("url", "") or f"https://auto.ru/cars/used/sale/{ad_id}/"

        # Пробег
        mileage = offer.get("state", {}).get("mileage", "")
        mileage_str = f"{mileage:,} км".replace(",", " ") if mileage else ""

        # Город
        seller = offer.get("seller", {})
        location_info = seller.get("location", {})
        city = location_info.get("region_info", {}).get("name", "") or location_info.get("address", "")

        return {
            "id": f"autoru_{ad_id}",
            "source": "Auto.ru",
            "title": title,
            "price": price,
            "url": link,
            "location": city,
            "year": year,
            "mileage": mileage_str,
            "found_at": datetime.now().isoformat(),
        }

    # HTML fallback для Auto.ru
    def _parse_autoru_html(self, search_params: dict) -> list[dict]:
        brand = search_params.get("brand", "all").lower().replace(" ", "_")
        model = search_params.get("model", "").lower().replace(" ", "_")
        url = (
            f"https://auto.ru/cars/used/sale/{brand}/{model or 'all'}/"
        )
        params = []
        if search_params.get("price_min"):
            params.append(f"price_from={search_params['price_min']}")
        if search_params.get("price_max"):
            params.append(f"price_to={search_params['price_max']}")
        if search_params.get("year_min"):
            params.append(f"year_from={search_params['year_min']}")
        if search_params.get("year_max"):
            params.append(f"year_to={search_params['year_max']}")
        if params:
            url += "?" + "&".join(params)

        ads = []
        try:
            headers = {
                "User-Agent": _random_ua(),
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Referer": "https://auto.ru/",
            }
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Auto.ru также прячет данные в JSON
            for script in soup.find_all("script"):
                text = script.string or ""
                if '"offers"' in text and '"listing"' in text:
                    m = re.search(r'"offers"\s*:\s*(\[.+?\])\s*,\s*"', text, re.DOTALL)
                    if m:
                        try:
                            offers = json.loads(m.group(1))
                            for offer in offers:
                                ad = self._map_autoru_offer(offer)
                                if ad:
                                    ads.append(ad)
                            break
                        except Exception:
                            pass

            if not ads:
                # Совсем базовый HTML fallback
                items = soup.select("div.ListingItem, article[class*='ListingItem']")
                for item in items:
                    link_el = item.select_one("a[href*='/cars/used/sale/']")
                    if not link_el:
                        continue
                    href = link_el.get("href", "")
                    id_m = re.search(r"/(\d+-[a-f0-9]+)/?$", href)
                    if not id_m:
                        continue
                    ad_id = id_m.group(1)
                    title_el = item.select_one("h3, [class*='ItemTitle']")
                    title = title_el.get_text(strip=True) if title_el else "Авто"
                    price_el = item.select_one("[class*='priceValue'], [class*='Price']")
                    price = price_el.get_text(strip=True) if price_el else "Цена не указана"
                    link = href if href.startswith("http") else f"https://auto.ru{href}"
                    ads.append({
                        "id": f"autoru_{ad_id}",
                        "source": "Auto.ru",
                        "title": title,
                        "price": price,
                        "url": link,
                        "location": "",
                        "found_at": datetime.now().isoformat(),
                    })

            logger.info(f"Auto.ru HTML: найдено {len(ads)} объявлений для '{search_params.get('name', '')}'")
        except Exception as e:
            logger.error(f"Auto.ru HTML ошибка: {e}")

        return ads
