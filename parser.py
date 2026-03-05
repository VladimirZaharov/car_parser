"""
parser.py  —  Selenium-парсер для Avito и Auto.ru
──────────────────────────────────────────────────
Оба сайта открываются в headless Chrome.
Имитируется поведение живого пользователя:
  • случайные паузы между действиями
  • плавный скролл страницы
  • патч navigator.webdriver = undefined
  • ротация User-Agent при каждом запуске
"""

import json
import logging
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────── #
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver',   {get: () => undefined});
Object.defineProperty(navigator, 'plugins',     {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages',   {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
Object.defineProperty(navigator, 'platform',    {get: () => 'Win32'});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
"""


def _jitter(base: float, spread: float = 0.35) -> float:
    return max(0.3, base + random.uniform(-spread * base, spread * base))


def _make_options(proxy_url: str = "", headless: bool = True) -> Options:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    opts.add_argument("--lang=ru-RU,ru")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--log-level=3")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
    })
    if proxy_url:
        opts.add_argument(f"--proxy-server={proxy_url}")
    return opts


@contextmanager
def _driver_ctx(proxy_url: str = "", headless: bool = True):
    driver = None
    try:
        opts    = _make_options(proxy_url=proxy_url, headless=headless)
        service = Service()
        driver  = webdriver.Chrome(service=service, options=opts)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})
        driver.set_page_load_timeout(50)
        driver.implicitly_wait(4)
        yield driver
    except WebDriverException as e:
        logger.error(f"Chrome WebDriver: не удалось запустить — {e}")
        yield None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _scroll_page(driver, steps: int = 6):
    total = driver.execute_script("return document.body.scrollHeight")
    step  = total // steps
    for i in range(1, steps + 1):
        driver.execute_script(f"window.scrollTo(0, {step * i});")
        time.sleep(_jitter(1.1, 0.5))
    driver.execute_script("window.scrollTo(0, 400);")
    time.sleep(_jitter(0.8))


def _wait_for_any(driver, selectors: list, timeout: int = 20) -> Optional[str]:
    end = time.time() + timeout
    while time.time() < end:
        for sel in selectors:
            try:
                driver.find_element(By.CSS_SELECTOR, sel)
                return sel
            except NoSuchElementException:
                pass
        time.sleep(0.5)
    return None


def _is_blocked(driver) -> bool:
    src = driver.page_source.lower()
    return any(kw in src for kw in (
        "captcha", "antibot", "blocked", "доступ ограничен",
        "подозрительная активность", "robot", "recaptcha",
    ))


# ═══════════════════════════════════════════════════════════════════ #
class CarParser:
    def __init__(self, config: dict):
        self.config    = config
        proxy_cfg      = config.get("proxy") or {}
        self.proxy_url = proxy_cfg.get("url", "")
        self.headless  = config.get("selenium_headless", True)

    # ─── AVITO ──────────────────────────────────────────────────── #
    def build_avito_url(self, p: dict) -> str:
        region = p.get("region", "rossiya")
        brand  = p.get("brand", "").lower().replace(" ", "_")
        model  = p.get("model", "").lower().replace(" ", "_")
        if brand and model:
            path = f"/{region}/avtomobili/{brand}/{model}/cars"
        elif brand:
            path = f"/{region}/avtomobili/{brand}/cars"
        else:
            path = f"/{region}/avtomobili/cars"
        qs: dict = {}
        if p.get("price_min"):   qs["pmin"]              = p["price_min"]
        if p.get("price_max"):   qs["pmax"]              = p["price_max"]
        if p.get("year_min"):    qs["params[201][from]"] = p["year_min"]
        if p.get("year_max"):    qs["params[201][to]"]   = p["year_max"]
        if p.get("mileage_max"): qs["params[922][to]"]   = p["mileage_max"]
        url = "https://www.avito.ru" + path
        if qs:
            url += "?" + urlencode(qs)
        return url

    def parse_avito(self, search_params: dict) -> list:
        url  = self.build_avito_url(search_params)
        name = search_params.get("name", "—")
        logger.info(f"[Avito] Открываем Chrome -> {url}")
        with _driver_ctx(proxy_url=self.proxy_url, headless=self.headless) as driver:
            if driver is None:
                return []
            ads = self._load_avito(driver, url)
        logger.info(f"[Avito] Найдено {len(ads)} объявлений для '{name}'")
        return ads

    def _load_avito(self, driver, url: str) -> list:
        ads = []
        try:
            driver.get(url)
            time.sleep(_jitter(4, 0.3))
            if _is_blocked(driver):
                logger.warning("[Avito] Обнаружена капча/блокировка. Ждём 40s и обновляем...")
                time.sleep(_jitter(40, 0.15))
                driver.refresh()
                time.sleep(_jitter(8, 0.3))
            card_sel = _wait_for_any(driver, [
                "[data-marker='item']",
                "[class*='iva-item-root']",
                "div[class*='items-items'] > div",
            ], timeout=20)
            if card_sel:
                _scroll_page(driver)
            else:
                logger.warning("[Avito] Карточки не появились, пробуем JSON-LD")
            soup = BeautifulSoup(driver.page_source, "lxml")
            ads  = self._avito_jsonld(soup)
            if not ads:
                ads = self._avito_html(soup)
        except WebDriverException as e:
            logger.error(f"[Avito] Selenium error: {e}")
        return ads

    @staticmethod
    def _avito_jsonld(soup: BeautifulSoup) -> list:
        ads = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data  = json.loads(tag.string or "")
                items = data.get("itemListElement", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for it in items:
                    item  = it.get("item", it)
                    url   = item.get("url", "")
                    if not url or "avito.ru" not in url:
                        continue
                    mid   = re.search(r"/(\d+)/?$", url)
                    price = item.get("offers", {}).get("price", "")
                    ads.append({
                        "id":       f"avito_{mid.group(1) if mid else url}",
                        "source":   "Avito",
                        "title":    item.get("name", "—"),
                        "price":    f"{price} ₽" if str(price).isdigit() else str(price or "Цена не указана"),
                        "url":      url,
                        "location": item.get("availableAtOrFrom", {}).get("name", ""),
                        "found_at": datetime.now().isoformat(),
                    })
            except Exception:
                pass
        return ads

    @staticmethod
    def _avito_html(soup: BeautifulSoup) -> list:
        ads   = []
        items = []
        for sel in ["div[data-marker='item']", "div[class*='iva-item-root']", "article[class*='item']"]:
            items = soup.select(sel)
            if items:
                break
        for item in items:
            ad_id = item.get("data-item-id") or item.get("id", "")
            if not ad_id:
                continue
            title_el = item.select_one("[itemprop='name'], [class*='title-root'], h3, h2")
            price_el = item.select_one("[itemprop='price'], [class*='price-text'], [class*='price_value'], [class*='price-root']")
            link_el  = item.select_one("a[href*='/avtomobili/']") or item.select_one("a[data-marker='item-title']")
            geo_el   = item.select_one("[class*='geo-root'], [class*='location'], [data-marker='item-address']")
            href = link_el["href"] if link_el else ""
            ads.append({
                "id":       f"avito_{ad_id}",
                "source":   "Avito",
                "title":    title_el.get_text(strip=True) if title_el else "—",
                "price":    price_el.get_text(strip=True) if price_el else "Цена не указана",
                "url":      f"https://www.avito.ru{href}" if href.startswith("/") else href,
                "location": geo_el.get_text(strip=True)  if geo_el   else "",
                "found_at": datetime.now().isoformat(),
            })
        return ads

    # ─── AUTO.RU ────────────────────────────────────────────────── #
    _BRAND_SLUG = {
        "mitsubishi": "mitsubishi", "toyota": "toyota", "bmw": "bmw",
        "honda": "honda", "kia": "kia", "hyundai": "hyundai",
        "volkswagen": "volkswagen", "mercedes": "mercedes-benz",
        "nissan": "nissan", "ford": "ford", "skoda": "skoda",
        "lada": "vaz", "renault": "renault", "chevrolet": "chevrolet",
        "audi": "audi", "mazda": "mazda", "subaru": "subaru",
        "lexus": "lexus", "volvo": "volvo", "peugeot": "peugeot",
        "suzuki": "suzuki", "jeep": "jeep", "land_rover": "land_rover",
        "porsche": "porsche", "infiniti": "infiniti",
        "geely": "geely", "chery": "chery", "haval": "haval",
    }

    def build_autoru_url(self, p: dict) -> str:
        brand_key = p.get("brand", "").lower().replace(" ", "_").replace("-", "_")
        brand     = self._BRAND_SLUG.get(brand_key, brand_key)
        model     = p.get("model", "").lower().replace(" ", "_").replace("-", "_")
        if brand and model:
            path = f"/cars/used/sale/{brand}/{model}/all/"
        elif brand:
            path = f"/cars/used/sale/{brand}/all/"
        else:
            path = "/cars/used/sale/all/all/"
        qs: dict = {}
        if p.get("price_min"):   qs["price_from"] = p["price_min"]
        if p.get("price_max"):   qs["price_to"]   = p["price_max"]
        if p.get("year_min"):    qs["year_from"]  = p["year_min"]
        if p.get("year_max"):    qs["year_to"]    = p["year_max"]
        if p.get("mileage_max"): qs["km_age_to"]  = p["mileage_max"]
        url = "https://auto.ru" + path
        if qs:
            url += "?" + urlencode(qs)
        return url

    def parse_autoru(self, search_params: dict) -> list:
        url  = self.build_autoru_url(search_params)
        name = search_params.get("name", "—")
        logger.info(f"[Auto.ru] Открываем Chrome -> {url}")
        with _driver_ctx(proxy_url=self.proxy_url, headless=self.headless) as driver:
            if driver is None:
                return []
            ads = self._load_autoru(driver, url)
        logger.info(f"[Auto.ru] Найдено {len(ads)} объявлений для '{name}'")
        return ads

    def _load_autoru(self, driver, url: str) -> list:
        ads = []
        try:
            driver.get(url)
            time.sleep(_jitter(4, 0.3))
            if _is_blocked(driver):
                logger.warning("[Auto.ru] Обнаружена капча/блокировка. Ждём 40s...")
                time.sleep(_jitter(40, 0.15))
                driver.refresh()
                time.sleep(_jitter(8, 0.3))
            self._autoru_accept_cookies(driver)
            card_sel = _wait_for_any(driver, [
                "div.ListingItem",
                "article.ListingItem",
                "div[class*='ListingItem_']",
                "div[class*='listing-item']",
            ], timeout=25)
            if not card_sel:
                logger.warning("[Auto.ru] Карточки не найдены, пробуем JSON из страницы")
                soup = BeautifulSoup(driver.page_source, "lxml")
                return self._autoru_from_page_json(soup)
            _scroll_page(driver)
            soup = BeautifulSoup(driver.page_source, "lxml")
            ads  = self._autoru_from_page_json(soup)
            if not ads:
                ads = self._autoru_from_html(soup)
        except WebDriverException as e:
            logger.error(f"[Auto.ru] Selenium error: {e}")
        return ads

    @staticmethod
    def _autoru_accept_cookies(driver):
        for sel in [
            "button[data-id='cookie-agreement-button']",
            ".CookieAgreement__button",
            "[class*='cookie'] button",
        ]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                btn.click()
                time.sleep(_jitter(0.8))
                break
            except (NoSuchElementException, WebDriverException):
                pass

    @staticmethod
    def _autoru_from_page_json(soup: BeautifulSoup) -> list:
        ads = []
        for tag in soup.find_all("script"):
            src = tag.string or ""
            match = re.search(r'"offers"\s*:\s*(\[.*?\])\s*[,}]', src, re.DOTALL)
            if not match:
                continue
            try:
                offers = json.loads(match.group(1))
                for offer in offers:
                    ad = CarParser._parse_autoru_offer(offer)
                    if ad:
                        ads.append(ad)
                if ads:
                    break
            except Exception:
                pass
        return ads

    @staticmethod
    def _autoru_from_html(soup: BeautifulSoup) -> list:
        ads   = []
        items = []
        for sel in ["div.ListingItem", "article.ListingItem", "div[class*='ListingItem_']", "div[class*='listing-item']"]:
            items = soup.select(sel)
            if items:
                break
        if not items:
            links = soup.find_all("a", href=re.compile(r"/cars/used/sale/.+/\d+-\w+/"))
            seen: set = set()
            for a in links:
                href = a.get("href", "")
                if href in seen:
                    continue
                seen.add(href)
                m = re.search(r"/sale/[^/]+/[^/]+/(\d+-[a-f0-9]+)/", href)
                ads.append({
                    "id":       f"autoru_{m.group(1) if m else href}",
                    "source":   "Auto.ru",
                    "title":    a.get_text(strip=True) or "—",
                    "price":    "см. ссылку",
                    "url":      href if href.startswith("http") else f"https://auto.ru{href}",
                    "location": "",
                    "found_at": datetime.now().isoformat(),
                })
            return ads
        for item in items:
            try:
                link_el  = item.select_one("a[href*='/cars/used/sale/']")
                if not link_el:
                    continue
                href     = link_el.get("href", "")
                m        = re.search(r"/sale/[^/]+/[^/]+/(\d+-[a-f0-9]+)/", href)
                oid      = m.group(1) if m else href
                title_el = item.select_one(".ListingItemTitle__link, [class*='ItemTitle'], [class*='title'], h3, h2")
                price_el = item.select_one(".ListingItem__priceValue, [class*='Price_'], [class*='price-value'], [class*='Price__content']")
                geo_el   = item.select_one(".MetroListPlace__regionName, [class*='Place_'], [class*='place'], [class*='region']")
                year_el  = item.select_one("[class*='year'], .ListingItem__yearMileage")
                km_el    = item.select_one("[class*='mileage'], [class*='km']")
                ads.append({
                    "id":       f"autoru_{oid}",
                    "source":   "Auto.ru",
                    "title":    title_el.get_text(strip=True) if title_el else "—",
                    "price":    price_el.get_text(strip=True) if price_el else "Цена не указана",
                    "url":      href if href.startswith("http") else f"https://auto.ru{href}",
                    "location": geo_el.get_text(strip=True)  if geo_el  else "",
                    "year":     year_el.get_text(strip=True) if year_el else "",
                    "mileage":  km_el.get_text(strip=True)   if km_el   else "",
                    "found_at": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.debug(f"[Auto.ru] item parse error: {e}")
        return ads

    @staticmethod
    def _parse_autoru_offer(offer: dict) -> Optional[dict]:
        oid = offer.get("id", "")
        if not oid:
            return None
        car   = offer.get("car_info", {})
        docs  = offer.get("documents", {})
        price = offer.get("price_info", {}).get("price", 0)
        loc   = offer.get("seller", {}).get("location", {})
        state = offer.get("state", {})
        title = " ".join(filter(None, [
            car.get("mark_info",  {}).get("name", ""),
            car.get("model_info", {}).get("name", ""),
            str(docs.get("year", "")),
        ])) or "—"
        price_str = f"{price:,}".replace(",", "\u00a0") + "\u00a0\u20bd" if price else "Цена не указана"
        region    = loc.get("region_info", {}).get("name", "") or loc.get("city_name", "")
        return {
            "id":       f"autoru_{oid}",
            "source":   "Auto.ru",
            "title":    title,
            "price":    price_str,
            "url":      f"https://auto.ru/cars/used/sale/{oid}/",
            "location": region,
            "year":     str(docs.get("year", "")),
            "mileage":  str(state.get("mileage", "")),
            "found_at": datetime.now().isoformat(),
        }
