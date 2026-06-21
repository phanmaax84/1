import os
import json
import logging
import asyncio
import re
import threading
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
    """
    {
      "123456": {
        "enabled": true,
        "seeds": ["Carrot"],
        "crates": [],
        "gear": ["Trowel"]
      }
    }
    """
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
        users[uid] = {"enabled": True, "seeds": [], "crates": [], "gear": []}
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
#              ПАРСИНГ API
# ═══════════════════════════════════════
def fetch_all_items() -> dict:
    try:
        resp = requests.get(API_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Ошибка запроса к API: {e}")
        return {"seeds": [], "crates": [], "gear": []}

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
    # ═══════════════════════════════════════
#      ФОРМИРОВАНИЕ СООБЩЕНИЯ (КАНАЛ)
# ═══════════════════════════════════════
def build_channel_message(stock: dict) -> str | None:
    """Возвращает None если ничего нет в стоке."""
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

    has_anything = False

    # Семена
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

    # Крэйты
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

    # Инструменты
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
def build_user_message(stock: dict, user_id: int) -> str | None:
    """Возвращает None если нет подходящих предметов для юзера."""
    settings = get_user_settings(user_id)

    if not settings.get("enabled", True):
        return None

    user_seeds = set(i.lower() for i in settings.get("seeds", []))
    user_crates = set(i.lower() for i in settings.get("crates", []))
    user_gear = set(i.lower() for i in settings.get("gear", []))

    has_filter = bool(user_seeds or user_crates or user_gear)

    if not has_filter:
        return None

    now = datetime.now(MOSCOW_TZ).strftime("%H:%M %d.%m.%Y")
    lines = [f"🔔 УВЕДОМЛЕНИЕ О СТОКЕ — {now}", ""]

    has_anything = False

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
    stock = fetch_stock()

    # Канал
    msg = build_channel_message(stock)
    if msg:
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=msg)
            logger.info("Сток отправлен в канал")
        except Exception as e:
            logger.error(f"Ошибка отправки в канал: {e}")
    else:
        logger.info("Нечего отправлять в канал — сток пуст")

    # Пользователям
    users = load_users()
    for uid, settings in users.items():
        if not settings.get("enabled", True):
            continue
        user_msg = build_user_message(stock, int(uid))
        if user_msg:
            try:
                await bot.send_message(chat_id=int(uid), text=user_msg)
                logger.info(f"Уведомление отправлено юзеру {uid}")
            except Exception as e:
                logger.error(f"Ошибка отправки юзеру {uid}: {e}")


# ═══════════════════════════════════════
#           РЕКЛАМА ЮЗЕРАМ
# ═══════════════════════════════════════
async def send_ad_to_users(bot):
    users = load_users()
    for uid in users:
        try:
            await bot.send_message(chat_id=int(uid), text=AD_TEXT)
            logger.info(f"Реклама отправлена юзеру {uid}")
        except Exception as e:
            logger.error(f"Ошибка отправки рекламы юзеру {uid}: {e}")
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

        logger.info(
            f"Следующая отправка через {int(wait)} сек. "
            f"Время: {next_run.strftime('%H:%M:%S')}"
        )

        await asyncio.sleep(wait)
        await send_stock_to_channel(bot)

        # Реклама раз в N часов
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

# ═══════════════════════════════════════
#         ХЕЛПЕРЫ ДЛЯ ФИЛЬТРА
# ═══════════════════════════════════════
def get_shop_emoji(shop: str) -> str:
    return {"seeds": "🌱", "crates": "📦", "gear": "🚿"}.get(shop, "")

def get_shop_name(shop: str) -> str:
    return {"seeds": "Семена", "crates": "Крэйты", "gear": "Инструменты"}.get(shop, "")

# ═══════════════════════════════════════
#        КОМАНДЫ — ОБЫЧНЫЕ ЮЗЕРЫ
# ═══════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    # Регистрируем юзера
    get_user_settings(uid)

    if is_admin(update):
        await update.message.reply_text(
            "Привет, админ! 👋\n\n"
            "Команды админа:\n"
            "🌱 /stock — посмотреть текущий сток\n"
            "📤 /send — отправить сток в канал\n"
            "🔧 /filter — фильтр канала\n"
            "🗑 /clearfilter — сбросить фильтр канала\n\n"
            "Команды юзера:\n"
            "🔔 /notify — настроить уведомления\n"
            "📊 /stock — текущий сток"
        )
        return

    settings = get_user_settings(uid)
    status = "🔔 Включены" if settings.get("enabled", True) else "🔕 Выключены"

    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я бот для отслеживания стоков из Grow A Garden 2 🌱\n\n"
        f"Твои уведомления: {status}\n\n"
        f"📊 /stock — посмотреть текущий сток\n"
        f"🔔 /notify — настроить уведомления\n\n"
        f"Я буду присылать тебе сообщение когда нужные предметы появятся в стоке!"
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_settings(uid)

    await update.message.reply_text("⏳ Получаю сток...")
    stock = fetch_stock()

    msg = build_channel_message(stock)
    if msg:
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("📭 Сейчас в стоке ничего нет.")


# ═══════════════════════════════════════
#        КОМАНДЫ — ТОЛЬКО АДМИН
# ═══════════════════════════════════════
async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ Только для админа.")
        return

    await update.message.reply_text("⏳ Отправляю сток в канал...")
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

    await update.message.reply_text("⏳ Загружаю предметы...")

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

    await update.message.reply_text("⏳ Загружаю предметы...")

    all_items = fetch_all_items()
    context.user_data["f_all"] = all_items
    context.user_data["f_mode"] = "user"

    settings = get_user_settings(uid)
    context.user_data["f_seeds"] = set(settings.get("seeds", []))
    context.user_data["f_crates"] = set(settings.get("crates", []))
    context.user_data["f_gear"] = set(settings.get("gear", []))
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
        [
            InlineKeyboardButton("✅ Выбрать всё", callback_data="fall_select"),
            InlineKeyboardButton("☐ Снять всё", callback_data="fall_deselect"),
        ],
    ]

    # Кнопка вкл/выкл уведомлений для юзеров
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
        f"Выбери магазин для настройки:\n\n"
        f"🌱 Семена: {seeds_sel} из {total_seeds}\n"
        f"📦 Крэйты: {crates_sel} из {total_crates}\n"
        f"🚿 Инструменты: {gear_sel} из {total_gear}\n\n"
        f"Настрой каждый магазин, затем нажми «Сохранить»."
    )

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
            InlineKeyboardButton("✅ Все в магазине", callback_data=f"fshopall|{shop}|select"),
            InlineKeyboardButton("☐ Снять в магазине", callback_data=f"fshopall|{shop}|deselect"),
        ]
    ]

    for item in page_items:
        name = item["name"]
        rarity = item["rarity"]
        r = rarity_icon(rarity)
        check = "✅" if name in selected else "☐"
        buttons.append([
            InlineKeyboardButton(
                f"{check} {r} {name} [{rarity}]",
                callback_data=f"ftoggle|{shop}|{name}"
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"fshop|{shop}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="fnoop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"fshop|{shop}|{page + 1}"))
    buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="fmenu")])

    markup = InlineKeyboardMarkup(buttons)

    emoji = get_shop_emoji(shop)
    shop_name = get_shop_name(shop)

    text = (
        f"{emoji} {shop_name}\n\n"
        f"Выбрано: {len(selected)} из {len(items)}\n"
        f"Страница {page + 1}/{total_pages}\n\n"
        f"Нажми на предмет чтобы вкл/выкл ✅"
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

    # ── Назад в меню ──
    if data == "fmenu":
        await send_filter_menu(query, context, edit=True)

    # ── Открыть магазин ──
    elif data.startswith("fshop|"):
        parts = data.split("|")
        shop = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        await send_shop_items(query, context, shop, page)

    # ── Переключить предмет ──
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

    # ── Все / снять в магазине ──
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

    # ── Все во всех магазинах ──
    elif data == "fall_select":
        all_items = context.user_data.get("f_all", {})
        for shop in ("seeds", "crates", "gear"):
            context.user_data[f"f_{shop}"] = {i["name"] for i in all_items.get(shop, [])}
        await send_filter_menu(query, context, edit=True)

    elif data == "fall_deselect":
        for shop in ("seeds", "crates", "gear"):
            context.user_data[f"f_{shop}"] = set()
        await send_filter_menu(query, context, edit=True)

    # ── Вкл/выкл уведомления (юзер) ──
    elif data == "ftoggle_notif":
        enabled = context.user_data.get("f_enabled", True)
        context.user_data["f_enabled"] = not enabled
        await send_filter_menu(query, context, edit=True)

    # ── Сохранить ──
    elif data == "fsave":
        mode = context.user_data.get("f_mode", "user")
        seeds = list(context.user_data.get("f_seeds", set()))
        crates = list(context.user_data.get("f_crates", set()))
        gear = list(context.user_data.get("f_gear", set()))
        total = len(seeds) + len(crates) + len(gear)

        if mode == "admin":
            if total == 0:
                save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
                await query.edit_message_text("⚠️ Ничего не выбрано — показываю всё в канале.")
            else:
                save_filters({"enabled": True, "seeds": seeds, "crates": crates, "gear": gear})
                text = f"✅ Фильтр канала сохранён!\nВыбрано: {total}\n\n"
                if seeds:
                    text += "🌱 " + ", ".join(sorted(seeds)) + "\n"
                if crates:
                    text += "📦 " + ", ".join(sorted(crates)) + "\n"
                if gear:
                    text += "🚿 " + ", ".join(sorted(gear))
                await query.edit_message_text(text)
        else:
            enabled = context.user_data.get("f_enabled", True)
            save_user_settings(uid, {
                "enabled": enabled,
                "seeds": seeds,
                "crates": crates,
                "gear": gear,
            })

            if not enabled:
                await query.edit_message_text("🔕 Уведомления выключены.\nНажми /notify чтобы включить.")
            elif total == 0:
                await query.edit_message_text(
                    "⚠️ Уведомления включены, но ничего не выбрано.\n"
                    "Выбери предметы через /notify чтобы получать оповещения."
                )
            else:
                text = f"✅ Настройки сохранены!\n🔔 Уведомления включены\nВыбрано: {total}\n\n"
                if seeds:
                    text += "🌱 " + ", ".join(sorted(seeds)) + "\n"
                if crates:
                    text += "📦 " + ", ".join(sorted(crates)) + "\n"
                if gear:
                    text += "🚿 " + ", ".join(sorted(gear))
                await query.edit_message_text(text)

    # ── Сбросить ──
    elif data == "freset":
        mode = context.user_data.get("f_mode", "user")
        for shop in ("seeds", "crates", "gear"):
            context.user_data[f"f_{shop}"] = set()

        if mode == "admin":
            save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
        else:
            context.user_data["f_enabled"] = True
            save_user_settings(uid, {"enabled": True, "seeds": [], "crates": [], "gear": []})

        await send_filter_menu(query, context, edit=True)

    elif data == "fnoop":
        pass


# ═══════════════════════════════════════
#           ОБЫЧНЫЕ СООБЩЕНИЯ
# ═══════════════════════════════════════
async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_user_settings(uid)

    if is_admin(update):
        await update.message.reply_text("Используй /start чтобы увидеть команды.")
    else:
        await update.message.reply_text(
            "👋 Привет! Используй команды:\n\n"
            "📊 /stock — текущий сток\n"
            "🔔 /notify — настроить уведомления"
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
    app.add_handler(CallbackQueryHandler(filter_callback, pattern=r"^f"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("Бот запущен! Планировщик стартует...")
    await scheduler(app.bot)


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    logger.info(f"Flask запущен на порту {PORT}")
    asyncio.run(main())
