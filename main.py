import os
import json
import logging
import asyncio
import re
import threading
import time as time_module
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import Conflict

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
API_URL = "https://grow-a-garden-2-tracker.onrender.com/api/stock"
PREDICTIONS_URL = "https://grow-a-garden-2-tracker.onrender.com/api/predictions"
MOSCOW_TZ = timezone(timedelta(hours=3))
PORT = int(os.getenv("PORT", 10000))

ITEMS_PER_PAGE = 8
AD_INTERVAL_HOURS = 6

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
#          ДЕФОЛТНЫЙ ФИЛЬТР КАНАЛА
# ═══════════════════════════════════════
DEFAULT_FILTER = {
    "enabled": True,
    "seeds": [
        "Cherry", "Dragon's Breath", "Moon Bloom", "Poison Apple",
        "Pomegranate", "Sunflower", "Venom Spitter", "Venus Fly Trap",
    ],
    "crates": [
        "Bear Trap Crate", "Fence Crate", "Owner Door Crate",
        "Teleporter Pad Crate",
    ],
    "gear": [
        "Grappling Hook", "Invisibility Mushroom", "Legendary Sprinkler",
        "Player Magnet", "Strawberry Sniper", "Super Sprinkler",
        "Super Watering Can", "Wheelbarrow",
    ],
}

# ═══════════════════════════════════════
#              FLASK / HEALTH
# ═══════════════════════════════════════
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Bot is alive!", 200

@web_app.route("/health")
def health():
    return "OK", 200

def run_web():
    web_app.run(host="0.0.0.0", port=PORT)

# ═══════════════════════════════════════
#              РЕКЛАМА
# ═══════════════════════════════════════
AD_TEXT = """✅НАБОР ОТКРЫТ 3/20 (СКОРО БУДУТ РАСШИРЕНЫ СЛОТЫ) ✅

😀 Привет! 🤔 Ищешь гильдию которая старается быть лучше каждый день?🤑 Тогда тебе у нам!😏 

🗑️ УТИЛИЗАТОРЫ UTZ🗑️

🫡 ТРЕБОВАНИЯ ОТ ВАС:
1. ИМЕТЬ ИНВЕНТАРЬ ИЛИ ФРУКТ НА 25 И БОЛЕЕ МИЛИОНОВ.
2. ПРОЯВЛЯТЬ АКТИВНОСЬ.
3. ПЫТАТСЯ ПОСТАВИТЬ НАШУ ГИЛЬДИЮ В ТОПЫ.
4. БЫТЬ АДЕКВАТНЫМ. 
🫡 ТРЕБОВАНИЯ ОТ НАС:
1. АДЕКВАТНОЕ ОБЩЕНИЕ.
2. НАБИРАЕМ ХОРОШИХ УЧАСНИКОВ.

🫠 МЫ БУДЕМ ПОМАГАТЬ ВАМ В РАЗВИТИИ ВАШЕЙ ФЕРМЫ И НЕ ТОЛЬКО.

🫪 ЕСЛИ ВАС ЭТО ЗАИНТЕРЕСОВАЛО, ПИШИТЕ МНЕ В ЛС @p2w_ez"""

# ═══════════════════════════════════════
#             ПЕРЕВОДЫ
# ═══════════════════════════════════════
ITEM_NAME_RU = {
    # Семена
    "Carrot": "Морковь",
    "Strawberry": "Клубника",
    "Blueberry": "Черника",
    "Tulip": "Тюльпан",
    "Tomato": "Помидор",
    "Apple": "Яблоко",
    "Bamboo": "Бамбук",
    "Corn": "Кукуруза",
    "Cactus": "Кактус",
    "Pineapple": "Ананас",
    "Mushroom": "Гриб",
    "Green Bean": "Стручковая фасоль",
    "Banana": "Банан",
    "Grape": "Виноград",
    "Coconut": "Кокос",
    "Mango": "Манго",
    "Dragon Fruit": "Драконий фрукт",
    "Acorn": "Жёлудь",
    "Cherry": "Вишня",
    "Sunflower": "Подсолнух",
    "Venus Fly Trap": "Мухоловка",
    "Pomegranate": "Гранат",
    "Poison Apple": "Ядовитое яблоко",
    "Venom Spitter": "Ядовитый плевок",
    "Moon Bloom": "Лунный цветок",
    "Dragon's Breath": "Дыхание дракона",
    # Крейты
    "Ladder Crate": "Крейт лестниц",
    "Bench Crate": "Крейт скамеек",
    "Light Crate": "Крейт фонарей",
    "Sign Crate": "Крейт табличек",
    "Arch Crate": "Крейт арок",
    "Roleplay Crate": "Крейт ролеплея",
    "Bridge Crate": "Крейт мостов",
    "Spring Crate": "Крейт пружин",
    "Seesaw Crate": "Крейт качелей",
    "Conveyor Crate": "Крейт конвейеров",
    "Owner Door Crate": "Крейт дверей владельца",
    "Bear Trap Crate": "Крейт капканов",
    "Fence Crate": "Крейт заборов",
    "Teleporter Pad Crate": "Крейт телепортов",
    # Инструменты
    "Common Watering Can": "Обычная лейка",
    "Common Sprinkler": "Обычный разбрызгиватель",
    "Sign": "Табличка",
    "Uncommon Sprinkler": "Необычный разбрызгиватель",
    "Trowel": "Совок",
    "Rare Sprinkler": "Редкий разбрызгиватель",
    "Jump Mushroom": "Прыжковый гриб",
    "Speed Mushroom": "Скоростной гриб",
    "Megaphone": "Мегафон",
    "Lantern": "Фонарь",
    "Supersize Mushroom": "Гриб увеличения",
    "Shrink Mushroom": "Гриб уменьшения",
    "Gnome": "Гном",
    "Flashbang": "Светошумовая граната",
    "Basic Pot": "Базовый горшок",
    "Legendary Sprinkler": "Легендарный разбрызгиватель",
    "Invisibility Mushroom": "Гриб невидимости",
    "Wheelbarrow": "Тачка",
    "Player Magnet": "Магнит игроков",
    "Super Watering Can": "Супер лейка",
    "Super Sprinkler": "Супер разбрызгиватель",
    "Grappling Hook": "Крюк-кошка",
    "Strawberry Sniper": "Клубничный снайпер",
}

def get_ru_name(name: str) -> str:
    return ITEM_NAME_RU.get(name, name)

# ═══════════════════════════════════════
#             ПОГОДЫ
# ═══════════════════════════════════════
ALL_WEATHERS = [
    "Blood Moon", "Golden Moon", "Chain Moon", "Pizza Moon",
    "Rainbow Moon", "Solar Eclipse", "Meteor Shower", "Rainbow",
    "Snowfall", "Rain", "Thunderstorm", "Acid Rain", "Aurora", "Windy",
]

WEATHER_EMOJI = {
    "Blood Moon": "🔴", "Golden Moon": "🟡", "Chain Moon": "⛓️",
    "Pizza Moon": "🍕", "Rainbow Moon": "🌈", "Solar Eclipse": "🌑",
    "Meteor Shower": "🌠", "Rainbow": "🌈", "Snowfall": "❄️",
    "Rain": "🌧️", "Thunderstorm": "⛈️", "Acid Rain": "🧪",
    "Aurora": "🌌", "Windy": "🍃",
}

WEATHER_NAME_RU = {
    "Blood Moon": "Кровавая луна", "Golden Moon": "Золотая луна",
    "Chain Moon": "Цепная луна", "Pizza Moon": "Пицца-луна",
    "Rainbow Moon": "Радужная луна", "Solar Eclipse": "Солнечное затмение",
    "Meteor Shower": "Звездопад", "Rainbow": "Радуга",
    "Snowfall": "Снегопад", "Rain": "Дождь",
    "Thunderstorm": "Гроза", "Acid Rain": "Кислотный дождь",
    "Aurora": "Аврора", "Windy": "Ветрено",
}

PHASE_EMOJI = {"Day": "☀️", "Sunset": "🌅", "Night": "🌙", "Sunrise": "🌄"}
PHASE_NAME_RU = {"Day": "День", "Sunset": "Закат", "Night": "Ночь", "Sunrise": "Рассвет"}

RARITY_EMOJI = {
    "Common": "⬜", "Uncommon": "🟩", "Rare": "🟦", "Epic": "🟪",
    "Legendary": "🟨", "Mythic": "🔴", "Mythical": "🔴", "Divine": "🔱",
    "Prismatic": "🌈", "Celestial": "✨", "Exotic": "💎", "Super": "⭐",
}

RARITY_NAME_RU = {
    "Common": "Обычное", "Uncommon": "Необычное", "Rare": "Редкое",
    "Epic": "Эпическое", "Legendary": "Легендарное", "Mythic": "Мифическое",
    "Mythical": "Мифическое", "Divine": "Божественное", "Prismatic": "Призматическое",
    "Celestial": "Небесное", "Exotic": "Экзотическое", "Super": "Супер",
}

def rarity_icon(rarity: str) -> str:
    return RARITY_EMOJI.get(rarity, "▪️")

def rarity_ru(rarity: str) -> str:
    return RARITY_NAME_RU.get(rarity, rarity)
    # ═══════════════════════════════════════
#         ФИЛЬТРЫ АДМИНА (канал)
# ═══════════════════════════════════════
FILTERS_FILE = "filters.json"

def load_filters() -> dict:
    if os.path.exists(FILTERS_FILE):
        with open(FILTERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # При первом запуске / после перезагрузки — ставим дефолт
    save_filters(DEFAULT_FILTER)
    return DEFAULT_FILTER.copy()

def save_filters(data: dict):
    with open(FILTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ═══════════════════════════════════════
#     ФИЛЬТРЫ ПОЛЬЗОВАТЕЛЕЙ (личка)
# ═══════════════════════════════════════
USERS_FILE = "users.json"

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(data: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_settings(user_id: int) -> dict:
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"enabled": True, "seeds": [], "crates": [], "gear": [], "weathers": []}
        save_users(users)
    else:
        if "weathers" not in users[uid]:
            users[uid]["weathers"] = []
            save_users(users)
    return users[uid]

def save_user_settings(user_id: int, settings: dict):
    users = load_users()
    users[str(user_id)] = settings
    save_users(users)

# ═══════════════════════════════════════
#         КЛАВИАТУРА МЕНЮ КНОПОК
# ═══════════════════════════════════════
def get_main_keyboard(is_admin_user: bool) -> ReplyKeyboardMarkup:
    if is_admin_user:
        buttons = [
            [KeyboardButton("📊 Сток"), KeyboardButton("🌤️ Погода")],
            [KeyboardButton("🔮 Прогноз"), KeyboardButton("🔔 Уведомления")],
            [KeyboardButton("📤 Отправить в канал"), KeyboardButton("🔧 Фильтр канала")],
            [KeyboardButton("🗑 Сброс фильтра")],
        ]
    else:
        buttons = [
            [KeyboardButton("📊 Сток"), KeyboardButton("🌤️ Погода")],
            [KeyboardButton("🔮 Прогноз"), KeyboardButton("🔔 Уведомления")],
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# ═══════════════════════════════════════
#          ПАРСИНГ API
# ═══════════════════════════════════════
def fetch_raw_data() -> dict | None:
    try:
        resp = requests.get(API_URL, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        return None

def parse_weather(data: dict) -> dict:
    weather = data.get("weather", {})
    night = weather.get("night", False)
    phase = weather.get("phase", "Day")
    weathers_dict = weather.get("weathers", {})
    end_time = weather.get("endTime", 0)
    night_started = weather.get("nightStartedAt", 0)
    night_ended = weather.get("nightEndedAt", 0)

    active_weathers = []
    if isinstance(weathers_dict, dict):
        for w_name in weathers_dict:
            active_weathers.append(w_name)
    elif isinstance(weathers_dict, list):
        active_weathers = weathers_dict

    now_ts = int(time_module.time())
    time_until_night = None
    if not night and night_started > now_ts:
        time_until_night = night_started - now_ts

    return {
        "night": night, "phase": phase,
        "phase_emoji": PHASE_EMOJI.get(phase, "❓"),
        "phase_ru": PHASE_NAME_RU.get(phase, phase),
        "active_weathers": active_weathers,
        "weather_end_time": end_time,
        "night_started_at": night_started,
        "night_ended_at": night_ended,
        "time_until_night": time_until_night,
    }

def format_seconds(seconds: int) -> str:
    if seconds <= 0:
        return "скоро"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}ч {minutes}м"
    elif minutes > 0:
        return f"{minutes}м {secs}с"
    return f"{secs}с"

def build_weather_block(weather_info: dict) -> str:
    lines = []
    lines.append(f"{weather_info['phase_emoji']} Время: {weather_info['phase_ru']}")

    if weather_info["night"]:
        lines.append("🌙 Сейчас ночь")
    else:
        ttn = weather_info.get("time_until_night")
        if ttn and ttn > 0:
            lines.append(f"🌙 До ночи: {format_seconds(ttn)}")

    active = weather_info["active_weathers"]
    if active:
        for w in active:
            emoji = WEATHER_EMOJI.get(w, "🌤️")
            name_ru = WEATHER_NAME_RU.get(w, w)
            lines.append(f"{emoji} {name_ru}")
        end_ts = weather_info.get("weather_end_time", 0)
        if end_ts > 0:
            remaining = end_ts - int(time_module.time())
            if remaining > 0:
                lines.append(f"⏳ Погода закончится через: {format_seconds(remaining)}")
    else:
        lines.append("🌤️ Погода: Ясно")

    return "\n".join(lines)

def parse_shops(data: dict) -> dict:
    shops = data.get("shops") if isinstance(data, dict) else data
    if shops is None:
        shops = data
    result = {"seeds": [], "crates": [], "gear": []}
    if not isinstance(shops, dict):
        return result

    for key, value in shops.items():
        key_lower = key.lower()
        if "seed" in key_lower:
            target = "seeds"
        elif "crate" in key_lower:
            target = "crates"
        elif "gear" in key_lower or "tool" in key_lower:
            target = "gear"
        else:
            continue

        items = value if isinstance(value, list) else value.get("items", []) if isinstance(value, dict) else []

        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name") or "?"
            rarity = item.get("rarity") or item.get("Rarity") or ""
            price = item.get("price") or item.get("Price") or ""
            stock_count = None
            for skey in ("stock", "Stock", "quantity", "Quantity", "amount", "remaining"):
                if skey in item:
                    stock_count = item[skey]
                    break
            result[target].append({"name": name, "rarity": rarity, "price": price, "stock": stock_count})
    return result

def fetch_all_items() -> dict:
    data = fetch_raw_data()
    if data is None:
        return {"seeds": [], "crates": [], "gear": []}
    return parse_shops(data)

def fetch_stock() -> dict:
    all_items = fetch_all_items()
    result = {"seeds": [], "crates": [], "gear": []}
    for cat in ("seeds", "crates", "gear"):
        for item in all_items[cat]:
            try:
                if item["stock"] is not None and int(item["stock"]) <= 0:
                    continue
            except (ValueError, TypeError):
                pass
            result[cat].append(item)
    return result

def fetch_weather() -> dict:
    data = fetch_raw_data()
    if data is None:
        return {"night": False, "phase": "Unknown", "phase_emoji": "❓",
                "phase_ru": "Неизвестно", "active_weathers": [],
                "weather_end_time": 0, "night_started_at": 0,
                "night_ended_at": 0, "time_until_night": None}
    return parse_weather(data)

def fetch_stock_and_weather() -> tuple:
    data = fetch_raw_data()
    if data is None:
        empty_stock = {"seeds": [], "crates": [], "gear": []}
        empty_weather = {"night": False, "phase": "Unknown", "phase_emoji": "❓",
                         "phase_ru": "Неизвестно", "active_weathers": [],
                         "weather_end_time": 0, "night_started_at": 0,
                         "night_ended_at": 0, "time_until_night": None}
        return empty_stock, empty_weather

    all_items = parse_shops(data)
    weather_info = parse_weather(data)
    stock = {"seeds": [], "crates": [], "gear": []}
    for cat in ("seeds", "crates", "gear"):
        for item in all_items[cat]:
            try:
                if item["stock"] is not None and int(item["stock"]) <= 0:
                    continue
            except (ValueError, TypeError):
                pass
            stock[cat].append(item)
    return stock, weather_info
    # ═══════════════════════════════════════
#             ПРОГНОЗ
# ═══════════════════════════════════════
def fetch_predictions() -> str:
    try:
        resp = requests.get(PREDICTIONS_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Ошибка прогноза: {e}")
        return "❌ Не удалось получить прогноз."

    lines = ["🔮 Прогноз стока", ""]

    if isinstance(data, dict):
        for shop_key, items in data.items():
            if not isinstance(items, list) or not items:
                continue

            key_lower = shop_key.lower()
            if "seed" in key_lower:
                lines.append("🌱 Семена:")
            elif "crate" in key_lower:
                lines.append("📦 Крэйты:")
            elif "gear" in key_lower or "tool" in key_lower:
                lines.append("🚿 Инструменты:")
            else:
                lines.append(f"📋 {shop_key}:")

            for item in items:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("Name") or "?"
                    rarity = item.get("rarity") or item.get("Rarity") or ""
                    r = rarity_icon(rarity)
                    ru = get_ru_name(name)
                    display = f"{ru} ({name})" if ru != name else name

                    # Время
                    time_str = ""
                    for tkey in ("time", "Time", "predicted_time", "predictedTime",
                                 "restock_time", "restockTime", "timestamp", "eta"):
                        if tkey in item:
                            raw_time = item[tkey]
                            time_str = _format_prediction_time(raw_time)
                            break

                    if time_str:
                        lines.append(f"  {r} {display} — {time_str}")
                    else:
                        lines.append(f"  {r} {display}")
                elif isinstance(item, str):
                    ru = get_ru_name(item)
                    display = f"{ru} ({item})" if ru != item else item
                    lines.append(f"  ▪️ {display}")

            lines.append("")

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = item.get("name") or item.get("Name") or "?"
                rarity = item.get("rarity") or item.get("Rarity") or ""
                r = rarity_icon(rarity)
                ru = get_ru_name(name)
                display = f"{ru} ({name})" if ru != name else name

                time_str = ""
                for tkey in ("time", "Time", "predicted_time", "predictedTime",
                             "restock_time", "restockTime", "timestamp", "eta"):
                    if tkey in item:
                        raw_time = item[tkey]
                        time_str = _format_prediction_time(raw_time)
                        break

                if time_str:
                    lines.append(f"  {r} {display} — {time_str}")
                else:
                    lines.append(f"  {r} {display}")
        lines.append("")
    else:
        lines.append(str(data))

    lines.append("⚠️ Могут быть неточности, это только прогноз!")
    return "\n".join(lines)


def _format_prediction_time(raw_time) -> str:
    """Пытается преобразовать время в формат МСК."""
    if isinstance(raw_time, (int, float)):
        if raw_time > 1_000_000_000_000:
            raw_time = raw_time / 1000
        try:
            dt = datetime.fromtimestamp(raw_time, tz=MOSCOW_TZ)
            return dt.strftime("%H:%M МСК")
        except:
            return str(raw_time)
    elif isinstance(raw_time, str):
        # Попробуем распарсить ISO
        try:
            dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            dt_msk = dt.astimezone(MOSCOW_TZ)
            return dt_msk.strftime("%H:%M МСК")
        except:
            pass
        # Попробуем unix string
        try:
            ts = float(raw_time)
            if ts > 1_000_000_000_000:
                ts = ts / 1000
            dt = datetime.fromtimestamp(ts, tz=MOSCOW_TZ)
            return dt.strftime("%H:%M МСК")
        except:
            return raw_time
    return str(raw_time)

# ═══════════════════════════════════════
#      ФОРМИРОВАНИЕ СООБЩЕНИЯ (КАНАЛ)
# ═══════════════════════════════════════
def build_channel_message(stock: dict, weather_info: dict) -> str | None:
    now = datetime.now(MOSCOW_TZ).strftime("%H:%M %d.%m.%Y")
    filt = load_filters()
    filter_enabled = filt.get("enabled", False)
    allowed_seeds = set(i.lower() for i in filt.get("seeds", []))
    allowed_crates = set(i.lower() for i in filt.get("crates", []))
    allowed_gear = set(i.lower() for i in filt.get("gear", []))

    def should_show(name, category):
        if not filter_enabled:
            return True
        if category == "seeds": return name.lower() in allowed_seeds
        if category == "crates": return name.lower() in allowed_crates
        if category == "gear": return name.lower() in allowed_gear
        return True

    lines = [f"🕐 СТОК НА {now}", "", build_weather_block(weather_info), ""]
    has = False

    for cat, emoji, title in [("seeds", "🌱", "Семена"), ("crates", "📦", "Крэйты"), ("gear", "🚿", "Инструменты")]:
        cat_lines = []
        for s in stock[cat]:
            if should_show(s["name"], cat):
                r = rarity_icon(s["rarity"])
                ru = get_ru_name(s["name"])
                display = f"{ru}" if ru != s["name"] else s["name"]
                st = f" (x{s['stock']})" if s["stock"] is not None else ""
                cat_lines.append(f"  {r} {display}{st}")
        if cat_lines:
            has = True
            lines.append(f"{emoji} {title}:")
            lines.extend(cat_lines)
            lines.append("")

    return "\n".join(lines) if has else None

# ═══════════════════════════════════════
#   ФОРМИРОВАНИЕ СООБЩЕНИЯ (ПОЛЬЗОВАТЕЛЬ)
# ═══════════════════════════════════════
def build_user_message(stock: dict, weather_info: dict, user_id: int) -> str | None:
    settings = get_user_settings(user_id)
    if not settings.get("enabled", True):
        return None

    user_seeds = set(i.lower() for i in settings.get("seeds", []))
    user_crates = set(i.lower() for i in settings.get("crates", []))
    user_gear = set(i.lower() for i in settings.get("gear", []))
    user_weathers = set(i.lower() for i in settings.get("weathers", []))

    if not (user_seeds or user_crates or user_gear or user_weathers):
        return None

    now = datetime.now(MOSCOW_TZ).strftime("%H:%M %d.%m.%Y")
    lines = [f"🔔 УВЕДОМЛЕНИЕ — {now}", ""]
    has = False

    active = weather_info.get("active_weathers", [])
    matched = [w for w in active if w.lower() in user_weathers]
    if matched:
        has = True
        lines.append("⚡ Интересная погода:")
        for w in matched:
            lines.append(f"  {WEATHER_EMOJI.get(w, '🌤️')} {WEATHER_NAME_RU.get(w, w)}")
        end_ts = weather_info.get("weather_end_time", 0)
        if end_ts > 0:
            rem = end_ts - int(time_module.time())
            if rem > 0:
                lines.append(f"  ⏳ Через: {format_seconds(rem)}")
        lines.append("")

    for cat, emoji, title in [("seeds", "🌱", "Семена"), ("crates", "📦", "Крэйты"), ("gear", "🚿", "Инструменты")]:
        allowed = {"seeds": user_seeds, "crates": user_crates, "gear": user_gear}[cat]
        cat_lines = []
        for s in stock[cat]:
            if s["name"].lower() in allowed:
                r = rarity_icon(s["rarity"])
                ru = get_ru_name(s["name"])
                st = f" (x{s['stock']})" if s["stock"] is not None else ""
                cat_lines.append(f"  {r} {ru}{st}")
        if cat_lines:
            has = True
            lines.append(f"{emoji} {title}:")
            lines.extend(cat_lines)
            lines.append("")

    return "\n".join(lines) if has else None
    # ═══════════════════════════════════════
#       ОТПРАВКА В КАНАЛ + ЮЗЕРАМ
# ═══════════════════════════════════════
async def send_stock_to_channel(bot):
    stock, weather_info = fetch_stock_and_weather()
    msg = build_channel_message(stock, weather_info)
    if msg:
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=msg)
            logger.info("Сток в канал")
        except Exception as e:
            logger.error(f"Канал: {e}")
    else:
        logger.info("Сток пуст")

    users = load_users()
    for uid, settings in users.items():
        if not settings.get("enabled", True):
            continue
        user_msg = build_user_message(stock, weather_info, int(uid))
        if user_msg:
            try:
                await bot.send_message(chat_id=int(uid), text=user_msg)
            except Exception as e:
                logger.error(f"Юзер {uid}: {e}")

async def send_ad_to_users(bot):
    users = load_users()
    for uid in users:
        try:
            await bot.send_message(chat_id=int(uid), text=AD_TEXT)
        except:
            pass
        await asyncio.sleep(0.5)

# ═══════════════════════════════════════
#            ПЛАНИРОВЩИК
# ═══════════════════════════════════════
async def scheduler(bot):
    last_ad = datetime.now(MOSCOW_TZ) - timedelta(hours=AD_INTERVAL_HOURS)
    while True:
        now = datetime.now(MOSCOW_TZ)
        nm = ((now.minute // 5) + 1) * 5
        nh, nd = now.hour, now.date()
        if nm >= 60:
            nm = 0
            t = now + timedelta(hours=1)
            nh, nd = t.hour, t.date()
        nr = datetime(nd.year, nd.month, nd.day, nh, nm, 5, 0, tzinfo=MOSCOW_TZ)
        wait = (nr - now).total_seconds()
        if wait <= 0:
            wait = 305
        logger.info(f"Сток через {int(wait)}с ({nr.strftime('%H:%M:%S')})")
        await asyncio.sleep(wait)
        await send_stock_to_channel(bot)
        now2 = datetime.now(MOSCOW_TZ)
        if (now2 - last_ad).total_seconds() >= AD_INTERVAL_HOURS * 3600:
            await send_ad_to_users(bot)
            last_ad = now2

# ═══════════════════════════════════════
#            ПРОВЕРКА АДМИНА
# ═══════════════════════════════════════
def is_admin(update: Update) -> bool:
    u = update.effective_user
    return u and u.username and u.username.lower() == ADMIN_USERNAME.lower()

def get_shop_emoji(s): return {"seeds": "🌱", "crates": "📦", "gear": "🚿"}.get(s, "")
def get_shop_name(s): return {"seeds": "Семена", "crates": "Крэйты", "gear": "Инструменты"}.get(s, "")

# ═══════════════════════════════════════
#        КОМАНДЫ И КНОПКИ МЕНЮ
# ═══════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_settings(uid)
    adm = is_admin(update)
    kb = get_main_keyboard(adm)

    if adm:
        await update.message.reply_text(
            "Привет, админ! 👋\nИспользуй кнопки ниже.", reply_markup=kb)
    else:
        settings = get_user_settings(uid)
        status = "🔔 Вкл" if settings.get("enabled", True) else "🔕 Выкл"
        await update.message.reply_text(
            f"👋 Привет, {update.effective_user.first_name}!\n\n"
            f"Я бот для стоков Grow A Garden 2 🌱\n"
            f"Уведомления: {status}\n\n"
            f"Используй кнопки ниже!", reply_markup=kb)

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    get_user_settings(uid)
    adm = is_admin(update)

    if text == "📊 Сток":
        await update.message.reply_text("⏳ Получаю сток...")
        stock, weather = fetch_stock_and_weather()
        msg = build_channel_message(stock, weather)
        if msg:
            await update.message.reply_text(msg)
        else:
            wb = build_weather_block(weather)
            await update.message.reply_text(f"📭 Сток пуст.\n\n{wb}")

    elif text == "🌤️ Погода":
        await update.message.reply_text("⏳ Получаю погоду...")
        w = fetch_weather()
        await update.message.reply_text(f"🌍 Погода в GAG2\n\n{build_weather_block(w)}")

    elif text == "🔮 Прогноз":
        await update.message.reply_text("⏳ Получаю прогноз...")
        msg = fetch_predictions()
        await update.message.reply_text(msg)

    elif text == "🔔 Уведомления":
        await cmd_notify(update, context)

    elif text == "📤 Отправить в канал" and adm:
        await update.message.reply_text("⏳ Отправляю...")
        await send_stock_to_channel(context.bot)
        await update.message.reply_text("✅ Готово!")

    elif text == "🔧 Фильтр канала" and adm:
        await cmd_filter(update, context)

    elif text == "🗑 Сброс фильтра" and adm:
        save_filters(DEFAULT_FILTER.copy())
        await update.message.reply_text("🗑 Фильтр сброшен на стандартный.")

    else:
        kb = get_main_keyboard(adm)
        await update.message.reply_text("Используй кнопки ниже 👇", reply_markup=kb)

# ═══════════════════════════════════════
#     /filter — ФИЛЬТР КАНАЛА (АДМИН)
# ═══════════════════════════════════════
async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text("⏳ Загружаю...")
    all_items = fetch_all_items()
    context.user_data["f_all"] = all_items
    context.user_data["f_mode"] = "admin"
    filt = load_filters()
    context.user_data["f_seeds"] = set(filt.get("seeds", []))
    context.user_data["f_crates"] = set(filt.get("crates", []))
    context.user_data["f_gear"] = set(filt.get("gear", []))
    await send_filter_menu(update.message, context, edit=False)

async def cmd_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text("⏳ Загружаю...")
    all_items = fetch_all_items()
    context.user_data["f_all"] = all_items
    context.user_data["f_mode"] = "user"
    settings = get_user_settings(uid)
    context.user_data["f_seeds"] = set(settings.get("seeds", []))
    context.user_data["f_crates"] = set(settings.get("crates", []))
    context.user_data["f_gear"] = set(settings.get("gear", []))
    context.user_data["f_weathers"] = set(settings.get("weathers", []))
    context.user_data["f_enabled"] = settings.get("enabled", True)
    await send_filter_menu(update.message, context, edit=False)
    # ═══════════════════════════════════════
#        ОБЩЕЕ МЕНЮ ФИЛЬТРА
# ═══════════════════════════════════════
async def send_filter_menu(target, context, edit=False):
    mode = context.user_data.get("f_mode", "user")
    all_items = context.user_data.get("f_all", {})
    ss = len(context.user_data.get("f_seeds", set()))
    cs = len(context.user_data.get("f_crates", set()))
    gs = len(context.user_data.get("f_gear", set()))
    ts = len(all_items.get("seeds", []))
    tc = len(all_items.get("crates", []))
    tg = len(all_items.get("gear", []))

    buttons = [
        [InlineKeyboardButton(f"🌱 Семена ({ss}/{ts})", callback_data="fshop|seeds|0")],
        [InlineKeyboardButton(f"📦 Крэйты ({cs}/{tc})", callback_data="fshop|crates|0")],
        [InlineKeyboardButton(f"🚿 Инструменты ({gs}/{tg})", callback_data="fshop|gear|0")],
    ]
    if mode == "user":
        ws = len(context.user_data.get("f_weathers", set()))
        buttons.append([InlineKeyboardButton(f"🌤️ Погода ({ws}/{len(ALL_WEATHERS)})", callback_data="fweather|0")])

    buttons.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="fall_select"),
        InlineKeyboardButton("☐ Снять всё", callback_data="fall_deselect"),
    ])
    if mode == "user":
        en = context.user_data.get("f_enabled", True)
        buttons.append([InlineKeyboardButton(
            "🔕 Выключить" if en else "🔔 Включить", callback_data="ftoggle_notif")])

    buttons.append([
        InlineKeyboardButton("💾 Сохранить", callback_data="fsave"),
        InlineKeyboardButton("🗑 Сбросить", callback_data="freset"),
    ])

    title = "🔧 Фильтр канала" if mode == "admin" else (
        f"🔔 Уведомления [{'🔔 Вкл' if context.user_data.get('f_enabled', True) else '🔕 Выкл'}]")

    text = (f"{title}\n\n🌱 Семена: {ss}/{ts}\n📦 Крэйты: {cs}/{tc}\n🚿 Инструменты: {gs}/{tg}\n")
    if mode == "user":
        ws = len(context.user_data.get("f_weathers", set()))
        text += f"🌤️ Погода: {ws}/{len(ALL_WEATHERS)}\n"
    text += "\nВыбери раздел → Сохранить."

    mk = InlineKeyboardMarkup(buttons)
    if edit:
        await target.edit_message_text(text=text, reply_markup=mk)
    else:
        await target.reply_text(text=text, reply_markup=mk)

async def send_shop_items(query, context, shop, page):
    all_items = context.user_data.get("f_all", {})
    items = all_items.get(shop, [])
    selected = context.user_data.get(f"f_{shop}", set())
    tp = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, tp - 1))
    start, end = page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE
    pi = items[start:end]

    buttons = [[
        InlineKeyboardButton("✅ Все", callback_data=f"fshopall|{shop}|select"),
        InlineKeyboardButton("☐ Снять", callback_data=f"fshopall|{shop}|deselect"),
    ]]
    for item in pi:
        n, r = item["name"], item["rarity"]
        ru = get_ru_name(n)
        display = f"{ru} ({n})" if ru != n else n
        check = "✅" if n in selected else "☐"
        buttons.append([InlineKeyboardButton(
            f"{check} {rarity_icon(r)} {display} [{rarity_ru(r)}]",
            callback_data=f"ftoggle|{shop}|{n}")])

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"fshop|{shop}|{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{tp}", callback_data="fnoop"))
    if page < tp - 1: nav.append(InlineKeyboardButton("➡️", callback_data=f"fshop|{shop}|{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="fmenu")])

    text = (f"{get_shop_emoji(shop)} {get_shop_name(shop)}\n\n"
            f"Выбрано: {len(selected)}/{len(items)}\n"
            f"Страница {page+1}/{tp}")
    await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(buttons))

async def send_weather_items(query, context, page):
    selected = context.user_data.get("f_weathers", set())
    tp = max(1, (len(ALL_WEATHERS) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, tp - 1))
    start, end = page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE
    pw = ALL_WEATHERS[start:end]

    buttons = [[
        InlineKeyboardButton("✅ Все", callback_data="fweatherall|select"),
        InlineKeyboardButton("☐ Снять", callback_data="fweatherall|deselect"),
    ]]
    for w in pw:
        check = "✅" if w in selected else "☐"
        buttons.append([InlineKeyboardButton(
            f"{check} {WEATHER_EMOJI.get(w, '🌤️')} {WEATHER_NAME_RU.get(w, w)}",
            callback_data=f"fwtoggle|{w}")])

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"fweather|{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{tp}", callback_data="fnoop"))
    if page < tp - 1: nav.append(InlineKeyboardButton("➡️", callback_data=f"fweather|{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="fmenu")])

    text = f"🌤️ Погода\n\nВыбрано: {len(selected)}/{len(ALL_WEATHERS)}\nСтраница {page+1}/{tp}"
    await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(buttons))
    # ═══════════════════════════════════════
#          ОБРАБОТКА CALLBACK
# ═══════════════════════════════════════
async def filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = update.effective_user.id

    if d == "fmenu":
        await send_filter_menu(q, context, edit=True)

    elif d.startswith("fshop|"):
        p = d.split("|")
        await send_shop_items(q, context, p[1], int(p[2]) if len(p) > 2 else 0)

    elif d.startswith("ftoggle|") and not d.startswith("ftoggle_"):
        p = d.split("|")
        shop, name = p[1], p[2]
        key = f"f_{shop}"
        sel = context.user_data.get(key, set())
        sel.discard(name) if name in sel else sel.add(name)
        context.user_data[key] = sel
        items = context.user_data.get("f_all", {}).get(shop, [])
        names = [i["name"] for i in items]
        pg = names.index(name) // ITEMS_PER_PAGE if name in names else 0
        await send_shop_items(q, context, shop, pg)

    elif d.startswith("fshopall|"):
        p = d.split("|")
        shop, action = p[1], p[2]
        items = context.user_data.get("f_all", {}).get(shop, [])
        context.user_data[f"f_{shop}"] = {i["name"] for i in items} if action == "select" else set()
        await send_shop_items(q, context, shop, 0)

    elif d.startswith("fweather|"):
        await send_weather_items(q, context, int(d.split("|")[1]))

    elif d.startswith("fwtoggle|"):
        w = d.split("|", 1)[1]
        sel = context.user_data.get("f_weathers", set())
        sel.discard(w) if w in sel else sel.add(w)
        context.user_data["f_weathers"] = sel
        pg = ALL_WEATHERS.index(w) // ITEMS_PER_PAGE if w in ALL_WEATHERS else 0
        await send_weather_items(q, context, pg)

    elif d.startswith("fweatherall|"):
        action = d.split("|")[1]
        context.user_data["f_weathers"] = set(ALL_WEATHERS) if action == "select" else set()
        await send_weather_items(q, context, 0)

    elif d == "fall_select":
        ai = context.user_data.get("f_all", {})
        for s in ("seeds", "crates", "gear"):
            context.user_data[f"f_{s}"] = {i["name"] for i in ai.get(s, [])}
        if context.user_data.get("f_mode") == "user":
            context.user_data["f_weathers"] = set(ALL_WEATHERS)
        await send_filter_menu(q, context, edit=True)

    elif d == "fall_deselect":
        for s in ("seeds", "crates", "gear"):
            context.user_data[f"f_{s}"] = set()
        if context.user_data.get("f_mode") == "user":
            context.user_data["f_weathers"] = set()
        await send_filter_menu(q, context, edit=True)

    elif d == "ftoggle_notif":
        context.user_data["f_enabled"] = not context.user_data.get("f_enabled", True)
        await send_filter_menu(q, context, edit=True)

    elif d == "fsave":
        mode = context.user_data.get("f_mode", "user")
        seeds = list(context.user_data.get("f_seeds", set()))
        crates = list(context.user_data.get("f_crates", set()))
        gear = list(context.user_data.get("f_gear", set()))
        total = len(seeds) + len(crates) + len(gear)

        if mode == "admin":
            if total == 0:
                save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
                await q.edit_message_text("⚠️ Ничего не выбрано — показываю всё.")
            else:
                save_filters({"enabled": True, "seeds": seeds, "crates": crates, "gear": gear})
                t = f"✅ Фильтр канала сохранён! ({total})\n\n"
                if seeds: t += "🌱 " + ", ".join(sorted(seeds)) + "\n"
                if crates: t += "📦 " + ", ".join(sorted(crates)) + "\n"
                if gear: t += "🚿 " + ", ".join(sorted(gear))
                await q.edit_message_text(t)
        else:
            en = context.user_data.get("f_enabled", True)
            weathers = list(context.user_data.get("f_weathers", set()))
            total_all = total + len(weathers)
            save_user_settings(uid, {
                "enabled": en, "seeds": seeds, "crates": crates,
                "gear": gear, "weathers": weathers,
            })
            if not en:
                await q.edit_message_text("🔕 Уведомления выключены.\nНажми 🔔 Уведомления.")
            elif total_all == 0:
                await q.edit_message_text("⚠️ Вкл, но ничего не выбрано.")
            else:
                t = f"✅ Сохранено! 🔔\n\n"
                if seeds: t += "🌱 " + ", ".join(sorted(get_ru_name(s) for s in seeds)) + "\n"
                if crates: t += "📦 " + ", ".join(sorted(get_ru_name(s) for s in crates)) + "\n"
                if gear: t += "🚿 " + ", ".join(sorted(get_ru_name(s) for s in gear)) + "\n"
                if weathers:
                    t += "🌤️ " + ", ".join(WEATHER_NAME_RU.get(w, w) for w in sorted(weathers))
                await q.edit_message_text(t)

    elif d == "freset":
        mode = context.user_data.get("f_mode", "user")
        for s in ("seeds", "crates", "gear"):
            context.user_data[f"f_{s}"] = set()
        if mode == "admin":
            save_filters(DEFAULT_FILTER.copy())
        else:
            context.user_data["f_enabled"] = True
            context.user_data["f_weathers"] = set()
            save_user_settings(uid, {"enabled": True, "seeds": [], "crates": [], "gear": [], "weathers": []})
        await send_filter_menu(q, context, edit=True)

    elif d == "fnoop":
        pass

# ═══════════════════════════════════════
#                 MAIN
# ═══════════════════════════════════════
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("notify", cmd_notify))
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CallbackQueryHandler(filter_callback, pattern=r"^f"))

    # Кнопки меню
    app.add_handler(MessageHandler(
        filters.Regex(r"^(📊 Сток|🌤️ Погода|🔮 Прогноз|🔔 Уведомления|📤 Отправить в канал|🔧 Фильтр канала|🗑 Сброс фильтра)$"),
        handle_menu_buttons
    ))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_menu_buttons(u, c)))

    await app.initialize()
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except:
        pass
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("Бот запущен!")
    await scheduler(app.bot)

def run_bot():
    while True:
        try:
            asyncio.run(main())
        except Conflict:
            logger.warning("Конфликт — жду 15с...")
            time_module.sleep(15)
        except Exception as e:
            logger.exception(f"Ошибка: {e}")
            time_module.sleep(10)

if __name__ == "__main__":
    # Создаём дефолтный фильтр при старте если нет файла
    if not os.path.exists(FILTERS_FILE):
        save_filters(DEFAULT_FILTER.copy())

    threading.Thread(target=run_web, daemon=True).start()
    logger.info(f"Flask: {PORT}")
    run_bot()
