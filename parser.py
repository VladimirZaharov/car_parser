"""
parser.py  —  Selenium-парсер Avito + Auto.ru
Работает на Ubuntu-сервере без GUI (headless Chrome).
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
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# webdriver-manager сам скачивает ChromeDriver под вашу версию Chrome
try:
    from webdriver_manager.chrome import ChromeDriverManager
    _WDM_AVAILABLE = True
except ImportError:
    _WDM_AVAILABLE = False

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────── #
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
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
        # --headless=new требует Chrome 112+
        # Если вдруг старый Chrome — попробуем оба варианта
        opts.add_argument("--headless=new")

    # ── обязательные флаги для серверного запуска ──
    opts.add_argument("--no-sandbox")                    # без этого Chrome не стартует под root / в контейнере
    opts.add_argument("--disable-dev-shm-usage")         # /dev/shm часто мал на серверах → используем /tmp
    opts.add_argument("--disable-gpu")                   # GPU не нужен в headless
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--single-process")               # стабильнее на VPS с ограниченной памятью
    opts.add_argument("--no-zygote")                    # отключить zygote-процесс (нужно при --single-process)
    opts.add_argument("--remote-debugging-port=0")      # случайный порт, без конфликтов

    # ── размер окна и локаль ──
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=ru-RU,ru")
    opts.add_argument("--accept-lang=ru-RU,ru")

    # ── маскировка под живой браузер ──
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)

    # ── прочее ──
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--log-level=3")
    opts.add_argument("--silent")

    opts.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        # Не загружать картинки — быстрее и меньше трафика
        "profile.managed_default_content_settings.images": 2,
    })

    if proxy_url:
        opts.add_argument(f"--proxy-server={proxy_url}")

    return opts


def _make_service() -> Service:
    """
    Находит chromedriver и возвращает Service.

    Порядок поиска:
      1. chromedriver в PATH (установлен install.sh через wget/apt)
      2. webdriver-manager — с явным поиском бинарника в папке
         (wdm >= 4.x кладёт рядом THIRD_PARTY_NOTICES, нужен сам бинарник)
    """
    import os
    import stat
    import shutil

    # ── 1. chromedriver в PATH — самый надёжный вариант ──
    in_path = shutil.which("chromedriver")
    if in_path:
        logger.info(f"ChromeDriver из PATH: {in_path}")
        return Service(in_path)

    # ── 2. webdriver-manager как запасной вариант ──
    if _WDM_AVAILABLE:
        try:
            raw_path = ChromeDriverManager().install()
            logger.info(f"webdriver-manager: {raw_path}")

            # Проверяем сам путь
            if os.path.isfile(raw_path) and os.access(raw_path, os.X_OK):
                return Service(raw_path)

            # wdm вернул не бинарник (например THIRD_PARTY_NOTICES) —
            # ищем файл с именем 'chromedriver' в той же директории
            search_root = os.path.dirname(raw_path)
            for dirpath, _, filenames in os.walk(search_root):
                for fname in filenames:
                    if fname in ("chromedriver", "chromedriver.exe"):
                        full = os.path.join(dirpath, fname)
                        os.chmod(full, os.stat(full).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                        logger.info(f"ChromeDriver найден через wdm: {full}")
                        return Service(full)
        except Exception as e:
            logger.warning(f"webdriver-manager ошибка: {e}")

    raise RuntimeError(
        "chromedriver не найден!\n"
        "Запустите install.sh или установите вручную:\n"
        "  sudo apt install chromium-chromedriver"
    )


@contextmanager
def _driver_ctx(proxy_url: str = "", headless: bool = True):
    """Контекст-менеджер: открывает Chrome, применяет stealth-патч, закрывает при выходе."""
    driver = None
    try:
        opts    = _make_options(proxy_url=proxy_url, headless=headless)
        service = _make_service()
        driver  = webdriver.Chrome(service=service, options=opts)

        # Применяем патч ДО загрузки любой страницы
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _STEALTH_JS}
        )
        driver.set_page_load_timeout(50)
        driver.implicitly_wait(4)

        logger.info("Chrome запущен успешно")
        yield driver

    except WebDriverException as e:
        # Попытка с --headless (старый синтаксис) если новый не сработал
        logger.warning(f"Chrome с --headless=new упал ({e}), пробуем старый --headless...")
        try:
            opts = _make_options(proxy_url=proxy_url, headless=False)
            opts.add_argument("--headless")              # старый флаг (Chrome < 112)
            service = _make_service()
            driver  = webdriver.Chrome(service=service, options=opts)
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": _STEALTH_JS}
            )
            driver.set_page_load_timeout(50)
            driver.implicitly_wait(4)
            logger.info("Chrome запущен (старый headless-режим)")
            yield driver
        except WebDriverException as e2:
            logger.error(f"Chrome не удалось запустить: {e2}")
            yield None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _scroll_page(driver, steps: int = 6):
    """Плавный скролл вниз с рандомными паузами."""
    try:
        total = driver.execute_script("return document.body.scrollHeight") or 3000
        step  = total // steps
        for i in range(1, steps + 1):
            driver.execute_script(f"window.scrollTo(0, {step * i});")
            time.sleep(_jitter(1.1, 0.5))
        driver.execute_script("window.scrollTo(0, 400);")
        time.sleep(_jitter(0.8))
    except Exception:
        pass


def _wait_for_any(driver, selectors: list, timeout: int = 20) -> Optional[str]:
    """Ждёт первый из CSS-селекторов, возвращает нашедший."""
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
#  CarParser                                                          #
# ═══════════════════════════════════════════════════════════════════ #
class CarParser:
    def __init__(self, config: dict):
        self.config    = config
        proxy_cfg      = config.get("proxy") or {}
        self.proxy_url = proxy_cfg.get("url", "")
        self.headless  = config.get("selenium_headless", True)

    # ────────────────────────────────────────────────────────────── #
    #  AVITO                                                         #
    # ────────────────────────────────────────────────────────────── #
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
                logger.warning("[Avito] Капча/блокировка. Ждём 40s...")
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
            logger.error(f"[Avito] Ошибка: {e}")
        return ads

    @staticmethod
    def _avito_jsonld(soup: BeautifulSoup) -> list:
        ads = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data  = json.loads(tag.string or "")
                items = (data.get("itemListElement", []) if isinstance(data, dict)
                         else (data if isinstance(data, list) else []))
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
                        "price":    (f"{price} ₽" if str(price).isdigit()
                                     else str(price or "Цена не указана")),
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
            price_el = item.select_one(
                "[itemprop='price'], [class*='price-text'], [class*='price_value'], [class*='price-root']")
            link_el  = (item.select_one("a[href*='/avtomobili/']") or
                        item.select_one("a[data-marker='item-title']"))
            geo_el   = item.select_one(
                "[class*='geo-root'], [class*='location'], [data-marker='item-address']")
            href = link_el["href"] if link_el else ""
            ads.append({
                "id":       f"avito_{ad_id}",
                "source":   "Avito",
                "title":    title_el.get_text(strip=True) if title_el else "—",
                "price":    price_el.get_text(strip=True) if price_el else "Цена не указана",
                "url":      (f"https://www.avito.ru{href}" if href.startswith("/") else href),
                "location": geo_el.get_text(strip=True)   if geo_el   else "",
                "found_at": datetime.now().isoformat(),
            })
        return ads

    # ────────────────────────────────────────────────────────────── #
    #  AUTO.RU                                                       #
    # ────────────────────────────────────────────────────────────── #
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
                logger.warning("[Auto.ru] Капча/блокировка. Ждём 40s...")
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
            logger.error(f"[Auto.ru] Ошибка: {e}")
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
            src   = tag.string or ""
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
        for sel in ["div.ListingItem", "article.ListingItem",
                    "div[class*='ListingItem_']", "div[class*='listing-item']"]:
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
                price_el = item.select_one(".ListingItem__priceValue, [class*='Price_'], [class*='price-value']")
                geo_el   = item.select_one(".MetroListPlace__regionName, [class*='Place_'], [class*='region']")
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
        price_str = (f"{price:,}".replace(",", "\u00a0") + "\u00a0\u20bd"
                     if price else "Цена не указана")
        region = loc.get("region_info", {}).get("name", "") or loc.get("city_name", "")
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
