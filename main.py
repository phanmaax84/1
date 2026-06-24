import os
import json
import logging
import asyncio
import re
import threading
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
API_URL = "https://grow-a-garden-2-tracker.onrender.com/api/stock"
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
AD_TEXT = """НАБОР ОТКРЫТ 3/20 (СКОРО БУДУТ РАСШИРЕНЫ СЛОТЫ) ✅

😀 Привет! 🤔 Ищешь гильдию которая старается быть лучше каждый день?🤑 Тогда тебе у нам!😏 

🗑️ УТИЛИЗАТОРЫ UTZ🗑️

🫡 ТРЕБОВАНИЯ ОТ ВАС:
1. ИМЕТЬ ФРУКТ НА 40-50+ КГ (НЕ СОБРАННЫЙ).
2. ПРОЯВЛЯТЬ АКТИВНОСЬ.
3. ПЫТАТСЯ ПОСТАВИТЬ НАШУ ГИЛЬДИЮ В ТОПЫ.
4. БЫТЬ АДЕКВАТНЫМ. 
🫡 ТРЕБОВАНИЯ ОТ НАС:
1. ИМЕЕМ ГРУППУ В ТГ.
2. АДЕКВАТНОЕ ОБЩЕНИЕ.
3. НАБИРАЕМ ХОРОШИХ УЧАСНИКОВ.

🫠 МЫ БУДЕМ ПОМАГАТЬ ВАМ В РАЗВИТИИ ВАШЕЙ ФЕРМЫ И НЕ ТОЛЬКО.

🫪 ЕСЛИ ВАС ЭТО ЗАИНТЕРЕСОВАЛО, ПИШИТЕ МНЕ В ЛС @p2w_ez"""

# ═══════════════════════════════════════
#             ПОГОДЫ
# ═══════════════════════════════════════
ALL_WEATHERS = [
    "Blood Moon",
    "Golden Moon",
    "Chain Moon",
    "Pizza Moon",
    "Rainbow Moon",
    "Solar Eclipse",
    "Meteor Shower",
    "Rainbow",
    "Snowfall",
    "Rain",
    "Thunderstorm",
    "Acid Rain",
    "Aurora",
    "Windy",
]

WEATHER_EMOJI = {
    "Blood Moon":     "🔴",
    "Golden Moon":    "🟡",
    "Chain Moon":     "⛓️",
    "Pizza Moon":     "🍕",
    "Rainbow Moon":   "🌈",
    "Solar Eclipse":  "🌑",
    "Meteor Shower":  "🌠",
    "Rainbow":        "🌈",
    "Snowfall":       "❄️",
    "Rain":           "🌧️",
    "Thunderstorm":   "⛈️",
    "Acid Rain":      "🧪",
    "Aurora":         "🌌",
    "Windy":          "🍃",
}

WEATHER_NAME_RU = {
    "Blood Moon":     "Кровавая луна",
    "Golden Moon":    "Золотая луна",
    "Chain Moon":     "Цепная луна",
    "Pizza Moon":     "Пицца-луна",
    "Rainbow Moon":   "Радужная луна",
    "Solar Eclipse":  "Солнечное затмение",
    "Meteor Shower":  "Звездопад",
    "Rainbow":        "Радуга",
    "Snowfall":       "Снегопад",
    "Rain":           "Дождь",
    "Thunderstorm":   "Гроза",
    "Acid Rain":      "Кислотный дождь",
    "Aurora":         "Аврора",
    "Windy":          "Ветрено",
}

PHASE_EMOJI = {
    "Day":     "☀️",
    "Sunset":  "🌅",
    "Night":   "🌙",
    "Sunrise": "🌄",
}

PHASE_NAME_RU = {
    "Day":     "День",
    "Sunset":  "Закат",
    "Night":   "Ночь",
    "Sunrise": "Рассвет",
}

# ═══════════════════════════════════════
#         ФИЛЬТРЫ АДМИНА (канал)
# ═══════════════════════════════════════
FILTERS_FILE = "filters.json"

def load_filters() -> dict:
    if os.path.exists(FILTERS_FILE):
        with open(FILTERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "seeds": [], "crates": [], "gear": []}

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
        users[uid] = {
            "enabled": True,
            "seeds": [],
            "crates": [],
            "gear": [],
            "weathers": [],
        }
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
#              РЕДКОСТИ
# ═══════════════════════════════════════
RARITY_EMOJI = {
    "Common":    "⬜",
    "Uncommon":  "🟩",
    "Rare":      "🟦",
    "Epic":      "🟪",
    "Legendary": "🟨",
    "Mythic":    "🔴",
    "Mythical":  "🔴",
    "Divine":    "🔱",
    "Prismatic": "🌈",
    "Celestial": "✨",
    "Exotic":    "💎",
    "Super":     "⭐",
}

def rarity_icon(rarity: str) -> str:
    return RARITY_EMOJI.get(rarity, "▪️")

# ═══════════════════════════════════════
#          ПАРСИНГ API — ПОЛНЫЙ
# ═══════════════════════════════════════
def fetch_raw_data() -> dict | None:
    """Получает полный JSON от API."""
    try:
        resp = requests.get(API_URL, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Ошибка запроса к API: {e}")
        return None


def parse_weather(data: dict) -> dict:
    """
    Парсит weather из API.
    Возвращает:
    {
      "night": bool,
      "phase": str,
      "phase_emoji": str,
      "phase_ru": str,
      "active_weathers": ["Rain", ...],
      "weather_end_time": int (unix),
      "night_started_at": int,
      "night_ended_at": int,
      "time_until_night": int (секунд, или None),
    }
    """
    weather = data.get("weather", {})

    night = weather.get("night", False)
    phase = weather.get("phase", "Day")
    weathers_dict = weather.get("weathers", {})
    end_time = weather.get("endTime", 0)
    night_started = weather.get("nightStartedAt", 0)
    night_ended = weather.get("nightEndedAt", 0)

    active_weathers = []
    if isinstance(weathers_dict, dict):
        for w_name, w_val in weathers_dict.items():
            active_weathers.append(w_name)
    elif isinstance(weathers_dict, list):
        active_weathers = weathers_dict

    # Время до ночи
    now_ts = int(time.time())
    time_until_night = None

    if not night and night_started > now_ts:
        time_until_night = night_started - now_ts
    elif not night and night_started > 0 and night_started <= now_ts:
        time_until_night = None

    return {
        "night": night,
        "phase": phase,
        "phase_emoji": PHASE_EMOJI.get(phase, "❓"),
        "phase_ru": PHASE_NAME_RU.get(phase, phase),
        "active_weathers": active_weathers,
        "weather_end_time": end_time,
        "night_started_at": night_started,
        "night_ended_at": night_ended,
        "time_until_night": time_until_night,
    }


def format_seconds(seconds: int) -> str:
    """Форматирует секунды в 'Xм Yс' или 'Xч Yм'."""
    if seconds <= 0:
        return "скоро"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}ч {minutes}м"
    elif minutes > 0:
        return f"{minutes}м {secs}с"
    else:
        return f"{secs}с"


def build_weather_block(weather_info: dict) -> str:
    """Строит блок погоды/времени для сообщения."""
    lines = []

    # Время суток
    phase_emoji = weather_info["phase_emoji"]
    phase_ru = weather_info["phase_ru"]
    lines.append(f"{phase_emoji} Время: {phase_ru}")

    # До ночи
    if weather_info["night"]:
        lines.append("🌙 Сейчас ночь")
    else:
        ttn = weather_info.get("time_until_night")
        if ttn and ttn > 0:
            lines.append(f"🌙 До ночи: {format_seconds(ttn)}")

    # Активные погоды
    active = weather_info["active_weathers"]
    if active:
        for w in active:
            emoji = WEATHER_EMOJI.get(w, "🌤️")
            name_ru = WEATHER_NAME_RU.get(w, w)
            lines.append(f"{emoji} {name_ru}")

        end_ts = weather_info.get("weather_end_time", 0)
        if end_ts > 0:
            now_ts = int(time.time())
            remaining = end_ts - now_ts
            if remaining > 0:
                lines.append(f"⏳ Погода закончится через: {format_seconds(remaining)}")
    else:
        lines.append("🌤️ Погода: Ясно")

    return "\n".join(lines)


# ═══════════════════════════════════════
#          ПАРСИНГ ПРЕДМЕТОВ
# ═══════════════════════════════════════
def parse_shops(data: dict) -> dict:
    """Парсит магазины, возвращает ВСЕ предметы."""
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

        if isinstance(value, list):
            items = value
        elif isinstance(value, dict):
            items = value.get("items", [])
        else:
            continue

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

            result[target].append({
                "name": name,
                "rarity": rarity,
                "price": price,
                "stock": stock_count,
            })

    return result


def fetch_all_items() -> dict:
    data = fetch_raw_data()
    if data is None:
        return {"seeds": [], "crates": [], "gear": []}
    return parse_shops(data)


def fetch_stock() -> dict:
    all_items = fetch_all_items()
    result = {"seeds": [], "crates": [], "gear": []}

    for category in ("seeds", "crates", "gear"):
        for item in all_items[category]:
            try:
                if item["stock"] is not None and int(item["stock"]) <= 0:
                    continue
            except (ValueError, TypeError):
                pass
            result[category].append(item)

    return result


def fetch_weather() -> dict:
    data = fetch_raw_data()
    if data is None:
        return {
            "night": False,
            "phase": "Unknown",
            "phase_emoji": "❓",
            "phase_ru": "Неизвестно",
            "active_weathers": [],
            "weather_end_time": 0,
            "night_started_at": 0,
            "night_ended_at": 0,
            "time_until_night": None,
        }
    return parse_weather(data)


def fetch_stock_and_weather() -> tuple:
    """Один запрос — и сток, и погода."""
    data = fetch_raw_data()
    if data is None:
        empty_stock = {"seeds": [], "crates": [], "gear": []}
        empty_weather = {
            "night": False, "phase": "Unknown", "phase_emoji": "❓",
            "phase_ru": "Неизвестно", "active_weathers": [],
            "weather_end_time": 0, "night_started_at": 0,
            "night_ended_at": 0, "time_until_night": None,
        }
        return empty_stock, empty_weather

    all_items = parse_shops(data)
    weather_info = parse_weather(data)

    stock = {"seeds": [], "crates": [], "gear": []}
    for category in ("seeds", "crates", "gear"):
        for item in all_items[category]:
            try:
                if item["stock"] is not None and int(item["stock"]) <= 0:
                    continue
            except (ValueError, TypeError):
                pass
            stock[category].append(item)

    return stock, weather_info
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

    def should_show(name: str, category: str) -> bool:
        if not filter_enabled:
            return True
        if category == "seeds":
            return name.lower() in allowed_seeds
        elif category == "crates":
            return name.lower() in allowed_crates
        elif category == "gear":
            return name.lower() in allowed_gear
        return True

    lines = [f"🕐 СТОК НА {now}", ""]

    # Погода и время
    lines.append(build_weather_block(weather_info))
    lines.append("")

    has_anything = False

    seed_lines = []
    for s in stock["seeds"]:
        if should_show(s["name"], "seeds"):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            seed_lines.append(f"  {r} {s['name']}{stock_txt}")
    if seed_lines:
        has_anything = True
        lines.append("🌱 Семена:")
        lines.extend(seed_lines)
        lines.append("")

    crate_lines = []
    for s in stock["crates"]:
        if should_show(s["name"], "crates"):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            crate_lines.append(f"  {r} {s['name']}{stock_txt}")
    if crate_lines:
        has_anything = True
        lines.append("📦 Крэйты:")
        lines.extend(crate_lines)
        lines.append("")

    gear_lines = []
    for s in stock["gear"]:
        if should_show(s["name"], "gear"):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            gear_lines.append(f"  {r} {s['name']}{stock_txt}")
    if gear_lines:
        has_anything = True
        lines.append("🚿 Инструменты:")
        lines.extend(gear_lines)

    if not has_anything:
        return None

    return "\n".join(lines)


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

    has_filter = bool(user_seeds or user_crates or user_gear or user_weathers)
    if not has_filter:
        return None

    now = datetime.now(MOSCOW_TZ).strftime("%H:%M %d.%m.%Y")
    lines = [f"🔔 УВЕДОМЛЕНИЕ — {now}", ""]

    has_anything = False

    # Проверяем погоду
    active = weather_info.get("active_weathers", [])
    matched_weathers = [w for w in active if w.lower() in user_weathers]

    if matched_weathers:
        has_anything = True
        lines.append("⚡ Интересная погода:")
        for w in matched_weathers:
            emoji = WEATHER_EMOJI.get(w, "🌤️")
            name_ru = WEATHER_NAME_RU.get(w, w)
            lines.append(f"  {emoji} {name_ru}")

        end_ts = weather_info.get("weather_end_time", 0)
        if end_ts > 0:
            remaining = end_ts - int(time.time())
            if remaining > 0:
                lines.append(f"  ⏳ Закончится через: {format_seconds(remaining)}")
        lines.append("")

    # Предметы
    seed_lines = []
    for s in stock["seeds"]:
        if s["name"].lower() in user_seeds:
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            seed_lines.append(f"  {r} {s['name']}{stock_txt}")
    if seed_lines:
        has_anything = True
        lines.append("🌱 Семена:")
        lines.extend(seed_lines)
        lines.append("")

    crate_lines = []
    for s in stock["crates"]:
        if s["name"].lower() in user_crates:
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            crate_lines.append(f"  {r} {s['name']}{stock_txt}")
    if crate_lines:
        has_anything = True
        lines.append("📦 Крэйты:")
        lines.extend(crate_lines)
        lines.append("")

    gear_lines = []
    for s in stock["gear"]:
        if s["name"].lower() in user_gear:
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            gear_lines.append(f"  {r} {s['name']}{stock_txt}")
    if gear_lines:
        has_anything = True
        lines.append("🚿 Инструменты:")
        lines.extend(gear_lines)

    if not has_anything:
        return None

    return "\n".join(lines)


# ═══════════════════════════════════════
#       ОТПРАВКА В КАНАЛ + ЮЗЕРАМ
# ═══════════════════════════════════════
async def send_stock_to_channel(bot):
    stock, weather_info = fetch_stock_and_weather()

    msg = build_channel_message(stock, weather_info)
    if msg:
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=msg)
            logger.info("Сток отправлен в канал")
        except Exception as e:
            logger.error(f"Ошибка отправки в канал: {e}")
    else:
        logger.info("Нечего отправлять — сток пуст")

    users = load_users()
    for uid, settings in users.items():
        if not settings.get("enabled", True):
            continue
        user_msg = build_user_message(stock, weather_info, int(uid))
        if user_msg:
            try:
                await bot.send_message(chat_id=int(uid), text=user_msg)
                logger.info(f"Уведомление юзеру {uid}")
            except Exception as e:
                logger.error(f"Ошибка юзеру {uid}: {e}")


async def send_ad_to_users(bot):
    users = load_users()
    for uid in users:
        try:
            await bot.send_message(chat_id=int(uid), text=AD_TEXT)
        except Exception as e:
            logger.error(f"Реклама юзеру {uid}: {e}")
        await asyncio.sleep(0.5)


# ═══════════════════════════════════════
#            ПЛАНИРОВЩИК
# ═══════════════════════════════════════
async def scheduler(bot):
    last_ad_time = datetime.now(MOSCOW_TZ) - timedelta(hours=AD_INTERVAL_HOURS)

    while True:
        now = datetime.now(MOSCOW_TZ)

        next_minute = ((now.minute // 5) + 1) * 5
        next_hour = now.hour
        next_day = now.date()

        if next_minute >= 60:
            next_minute = 0
            temp = now + timedelta(hours=1)
            next_hour = temp.hour
            next_day = temp.date()

        next_run = datetime(
            year=next_day.year,
            month=next_day.month,
            day=next_day.day,
            hour=next_hour,
            minute=next_minute,
            second=5,
            microsecond=0,
            tzinfo=MOSCOW_TZ,
        )

        wait = (next_run - now).total_seconds()
        if wait <= 0:
            wait = 305

        logger.info(f"Следующая отправка через {int(wait)} сек. {next_run.strftime('%H:%M:%S')}")
        await asyncio.sleep(wait)
        await send_stock_to_channel(bot)

        now2 = datetime.now(MOSCOW_TZ)
        if (now2 - last_ad_time).total_seconds() >= AD_INTERVAL_HOURS * 3600:
            await send_ad_to_users(bot)
            last_ad_time = now2
            # ═══════════════════════════════════════
#            ПРОВЕРКА АДМИНА
# ═══════════════════════════════════════
def is_admin(update: Update) -> bool:
    user = update.effective_user
    return (
        user is not None
        and user.username is not None
        and user.username.lower() == ADMIN_USERNAME.lower()
    )

def get_shop_emoji(shop: str) -> str:
    return {"seeds": "🌱", "crates": "📦", "gear": "🚿"}.get(shop, "")

def get_shop_name(shop: str) -> str:
    return {"seeds": "Семена", "crates": "Крэйты", "gear": "Инструменты"}.get(shop, "")


# ═══════════════════════════════════════
#              КОМАНДЫ
# ═══════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    get_user_settings(uid)

    if is_admin(update):
        await update.message.reply_text(
            "Привет, админ! 👋\n\n"
            "Команды админа:\n"
            "🌱 /stock — текущий сток\n"
            "📤 /send — отправить сток в канал\n"
            "🔧 /filter — фильтр канала\n"
            "🗑 /clearfilter — сбросить фильтр канала\n\n"
            "Команды юзера:\n"
            "🔔 /notify — настроить уведомления\n"
            "🌤️ /weather — текущая погода и время"
        )
        return

    settings = get_user_settings(uid)
    status = "🔔 Включены" if settings.get("enabled", True) else "🔕 Выключены"

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я бот для отслеживания стоков из Grow A Garden 2 🌱\n\n"
        f"Твои уведомления: {status}\n\n"
        f"📊 /stock — текущий сток\n"
        f"🌤️ /weather — погода и время в игре\n"
        f"🔔 /notify — настроить уведомления\n\n"
        f"Я пришлю сообщение когда нужные предметы или погода появятся!"
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_settings(uid)

    await update.message.reply_text("⏳ Получаю сток...")
    stock, weather_info = fetch_stock_and_weather()

    msg = build_channel_message(stock, weather_info)
    if msg:
        await update.message.reply_text(msg)
    else:
        # Всё равно покажем погоду
        weather_text = build_weather_block(weather_info)
        await update.message.reply_text(f"📭 Сейчас в стоке ничего нет.\n\n{weather_text}")


async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_settings(uid)

    await update.message.reply_text("⏳ Получаю погоду...")
    weather_info = fetch_weather()

    text = f"🌍 Погода и время в Grow A Garden 2\n\n{build_weather_block(weather_info)}"
    await update.message.reply_text(text)


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ Только для админа.")
        return

    await update.message.reply_text("⏳ Отправляю...")
    await send_stock_to_channel(context.bot)
    await update.message.reply_text("✅ Готово!")


async def cmd_clearfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
    await update.message.reply_text("🗑 Фильтр канала сброшен.")


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


# ═══════════════════════════════════════
#   /notify — УВЕДОМЛЕНИЯ ЮЗЕРА
# ═══════════════════════════════════════
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
async def send_filter_menu(target, context: ContextTypes.DEFAULT_TYPE, edit: bool):
    mode = context.user_data.get("f_mode", "user")
    all_items = context.user_data.get("f_all", {})

    seeds_sel = len(context.user_data.get("f_seeds", set()))
    crates_sel = len(context.user_data.get("f_crates", set()))
    gear_sel = len(context.user_data.get("f_gear", set()))

    total_seeds = len(all_items.get("seeds", []))
    total_crates = len(all_items.get("crates", []))
    total_gear = len(all_items.get("gear", []))

    buttons = [
        [InlineKeyboardButton(
            f"🌱 Семена ({seeds_sel}/{total_seeds})",
            callback_data="fshop|seeds|0"
        )],
        [InlineKeyboardButton(
            f"📦 Крэйты ({crates_sel}/{total_crates})",
            callback_data="fshop|crates|0"
        )],
        [InlineKeyboardButton(
            f"🚿 Инструменты ({gear_sel}/{total_gear})",
            callback_data="fshop|gear|0"
        )],
    ]

    # Погода — только для юзеров
    if mode == "user":
        weathers_sel = len(context.user_data.get("f_weathers", set()))
        buttons.append([InlineKeyboardButton(
            f"🌤️ Погода ({weathers_sel}/{len(ALL_WEATHERS)})",
            callback_data="fweather|0"
        )])

    buttons.append([
        InlineKeyboardButton("✅ Выбрать всё", callback_data="fall_select"),
        InlineKeyboardButton("☐ Снять всё", callback_data="fall_deselect"),
    ])

    if mode == "user":
        enabled = context.user_data.get("f_enabled", True)
        toggle_text = "🔕 Выключить уведомления" if enabled else "🔔 Включить уведомления"
        buttons.append([InlineKeyboardButton(toggle_text, callback_data="ftoggle_notif")])

    buttons.append([
        InlineKeyboardButton("💾 Сохранить", callback_data="fsave"),
        InlineKeyboardButton("🗑 Сбросить", callback_data="freset"),
    ])

    markup = InlineKeyboardMarkup(buttons)

    if mode == "admin":
        title = "🔧 Фильтр канала"
    else:
        enabled = context.user_data.get("f_enabled", True)
        status = "🔔 Вкл" if enabled else "🔕 Выкл"
        title = f"🔔 Настройка уведомлений [{status}]"

    text = (
        f"{title}\n\n"
        f"🌱 Семена: {seeds_sel}/{total_seeds}\n"
        f"📦 Крэйты: {crates_sel}/{total_crates}\n"
        f"🚿 Инструменты: {gear_sel}/{total_gear}\n"
    )

    if mode == "user":
        weathers_sel = len(context.user_data.get("f_weathers", set()))
        text += f"🌤️ Погода: {weathers_sel}/{len(ALL_WEATHERS)}\n"

    text += "\nВыбери раздел, затем нажми «Сохранить»."

    if edit:
        await target.edit_message_text(text=text, reply_markup=markup)
    else:
        await target.reply_text(text=text, reply_markup=markup)


# ═══════════════════════════════════════
#      СТРАНИЦА ПРЕДМЕТОВ МАГАЗИНА
# ═══════════════════════════════════════
async def send_shop_items(query, context: ContextTypes.DEFAULT_TYPE, shop: str, page: int):
    all_items = context.user_data.get("f_all", {})
    items = all_items.get(shop, [])

    key = f"f_{shop}"
    selected: set = context.user_data.get(key, set())

    total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = items[start:end]

    buttons = [
        [
            InlineKeyboardButton("✅ Все", callback_data=f"fshopall|{shop}|select"),
            InlineKeyboardButton("☐ Снять", callback_data=f"fshopall|{shop}|deselect"),
        ]
    ]

    for item in page_items:
        name = item["name"]
        rarity = item["rarity"]
        r = rarity_icon(rarity)
        check = "✅" if name in selected else "☐"
        buttons.append([InlineKeyboardButton(
            f"{check} {r} {name} [{rarity}]",
            callback_data=f"ftoggle|{shop}|{name}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"fshop|{shop}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="fnoop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"fshop|{shop}|{page + 1}"))
    buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="fmenu")])

    markup = InlineKeyboardMarkup(buttons)

    text = (
        f"{get_shop_emoji(shop)} {get_shop_name(shop)}\n\n"
        f"Выбрано: {len(selected)}/{len(items)}\n"
        f"Страница {page + 1}/{total_pages}\n\n"
        f"Нажми на предмет ✅"
    )

    await query.edit_message_text(text=text, reply_markup=markup)


# ═══════════════════════════════════════
#       СТРАНИЦА ПОГОДЫ (ЮЗЕР)
# ═══════════════════════════════════════
async def send_weather_items(query, context: ContextTypes.DEFAULT_TYPE, page: int):
    selected: set = context.user_data.get("f_weathers", set())

    total_pages = max(1, (len(ALL_WEATHERS) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_weathers = ALL_WEATHERS[start:end]

    buttons = [
        [
            InlineKeyboardButton("✅ Все погоды", callback_data="fweatherall|select"),
            InlineKeyboardButton("☐ Снять все", callback_data="fweatherall|deselect"),
        ]
    ]

    for w in page_weathers:
        emoji = WEATHER_EMOJI.get(w, "🌤️")
        name_ru = WEATHER_NAME_RU.get(w, w)
        check = "✅" if w in selected else "☐"
        buttons.append([InlineKeyboardButton(
            f"{check} {emoji} {name_ru}",
            callback_data=f"fwtoggle|{w}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"fweather|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="fnoop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"fweather|{page + 1}"))
    buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="fmenu")])

    markup = InlineKeyboardMarkup(buttons)

    text = (
        f"🌤️ Настройка погоды\n\n"
        f"Выбрано: {len(selected)}/{len(ALL_WEATHERS)}\n"
        f"Страница {page + 1}/{total_pages}\n\n"
        f"Выбери погоды для уведомлений ✅"
    )

    await query.edit_message_text(text=text, reply_markup=markup)
    # ═══════════════════════════════════════
#          ОБРАБОТКА CALLBACK
# ═══════════════════════════════════════
async def filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    uid = update.effective_user.id

    if data == "fmenu":
        await send_filter_menu(query, context, edit=True)

    elif data.startswith("fshop|"):
        parts = data.split("|")
        shop = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        await send_shop_items(query, context, shop, page)

    elif data.startswith("ftoggle|") and not data.startswith("ftoggle_"):
        parts = data.split("|")
        shop = parts[1]
        name = parts[2]
        key = f"f_{shop}"
        selected: set = context.user_data.get(key, set())

        if name in selected:
            selected.discard(name)
        else:
            selected.add(name)
        context.user_data[key] = selected

        items = context.user_data.get("f_all", {}).get(shop, [])
        names = [i["name"] for i in items]
        try:
            idx = names.index(name)
            page = idx // ITEMS_PER_PAGE
        except ValueError:
            page = 0
        await send_shop_items(query, context, shop, page)

    elif data.startswith("fshopall|"):
        parts = data.split("|")
        shop = parts[1]
        action = parts[2]
        key = f"f_{shop}"
        items = context.user_data.get("f_all", {}).get(shop, [])

        if action == "select":
            context.user_data[key] = {i["name"] for i in items}
        else:
            context.user_data[key] = set()
        await send_shop_items(query, context, shop, 0)

    # ── Погода ──
    elif data.startswith("fweather|"):
        page = int(data.split("|")[1])
        await send_weather_items(query, context, page)

    elif data.startswith("fwtoggle|"):
        w_name = data.split("|", 1)[1]
        selected: set = context.user_data.get("f_weathers", set())
        if w_name in selected:
            selected.discard(w_name)
        else:
            selected.add(w_name)
        context.user_data["f_weathers"] = selected

        try:
            idx = ALL_WEATHERS.index(w_name)
            page = idx // ITEMS_PER_PAGE
        except ValueError:
            page = 0
        await send_weather_items(query, context, page)

    elif data.startswith("fweatherall|"):
        action = data.split("|")[1]
        if action == "select":
            context.user_data["f_weathers"] = set(ALL_WEATHERS)
        else:
            context.user_data["f_weathers"] = set()
        await send_weather_items(query, context, 0)

    # ── Общие ──
    elif data == "fall_select":
        all_items = context.user_data.get("f_all", {})
        for shop in ("seeds", "crates", "gear"):
            context.user_data[f"f_{shop}"] = {i["name"] for i in all_items.get(shop, [])}
        if context.user_data.get("f_mode") == "user":
            context.user_data["f_weathers"] = set(ALL_WEATHERS)
        await send_filter_menu(query, context, edit=True)

    elif data == "fall_deselect":
        for shop in ("seeds", "crates", "gear"):
            context.user_data[f"f_{shop}"] = set()
        if context.user_data.get("f_mode") == "user":
            context.user_data["f_weathers"] = set()
        await send_filter_menu(query, context, edit=True)

    elif data == "ftoggle_notif":
        enabled = context.user_data.get("f_enabled", True)
        context.user_data["f_enabled"] = not enabled
        await send_filter_menu(query, context, edit=True)

    elif data == "fsave":
        mode = context.user_data.get("f_mode", "user")
        seeds = list(context.user_data.get("f_seeds", set()))
        crates = list(context.user_data.get("f_crates", set()))
        gear = list(context.user_data.get("f_gear", set()))
        total = len(seeds) + len(crates) + len(gear)

        if mode == "admin":
            if total == 0:
                save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
                await query.edit_message_text("⚠️ Ничего не выбрано — показываю всё.")
            else:
                save_filters({"enabled": True, "seeds": seeds, "crates": crates, "gear": gear})
                text = f"✅ Фильтр канала сохранён! ({total})\n\n"
                if seeds:
                    text += "🌱 " + ", ".join(sorted(seeds)) + "\n"
                if crates:
                    text += "📦 " + ", ".join(sorted(crates)) + "\n"
                if gear:
                    text += "🚿 " + ", ".join(sorted(gear))
                await query.edit_message_text(text)
        else:
            enabled = context.user_data.get("f_enabled", True)
            weathers = list(context.user_data.get("f_weathers", set()))
            total_all = total + len(weathers)

            save_user_settings(uid, {
                "enabled": enabled,
                "seeds": seeds,
                "crates": crates,
                "gear": gear,
                "weathers": weathers,
            })

            if not enabled:
                await query.edit_message_text("🔕 Уведомления выключены.\n/notify чтобы включить.")
            elif total_all == 0:
                await query.edit_message_text("⚠️ Уведомления вкл, но ничего не выбрано.\n/notify")
            else:
                text = f"✅ Сохранено! 🔔 Вкл\n\n"
                if seeds:
                    text += "🌱 " + ", ".join(sorted(seeds)) + "\n"
                if crates:
                    text += "📦 " + ", ".join(sorted(crates)) + "\n"
                if gear:
                    text += "🚿 " + ", ".join(sorted(gear)) + "\n"
                if weathers:
                    w_text = ", ".join(
                        f"{WEATHER_EMOJI.get(w, '')} {WEATHER_NAME_RU.get(w, w)}"
                        for w in sorted(weathers)
                    )
                    text += f"🌤️ {w_text}"
                await query.edit_message_text(text)

    elif data == "freset":
        mode = context.user_data.get("f_mode", "user")
        for shop in ("seeds", "crates", "gear"):
            context.user_data[f"f_{shop}"] = set()

        if mode == "admin":
            save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
        else:
            context.user_data["f_enabled"] = True
            context.user_data["f_weathers"] = set()
            save_user_settings(uid, {
                "enabled": True, "seeds": [], "crates": [], "gear": [], "weathers": []
            })
        await send_filter_menu(query, context, edit=True)

    elif data == "fnoop":
        pass


async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_settings(uid)

    if is_admin(update):
        await update.message.reply_text("Используй /start")
    else:
        await update.message.reply_text(
            "👋 Привет!\n\n"
            "📊 /stock — текущий сток\n"
            "🌤️ /weather — погода\n"
            "🔔 /notify — уведомления"
        )


# ═══════════════════════════════════════
#                 MAIN
# ═══════════════════════════════════════
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CommandHandler("clearfilter", cmd_clearfilter))
    app.add_handler(CommandHandler("notify", cmd_notify))
    app.add_handler(CommandHandler("weather", cmd_weather))
    app.add_handler(CallbackQueryHandler(filter_callback, pattern=r"^f"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("Бот запущен!")
    await scheduler(app.bot)


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    logger.info(f"Flask на порту {PORT}")
    asyncio.run(main())
