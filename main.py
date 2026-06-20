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
#              ФИЛЬТРЫ
# ═══════════════════════════════════════
FILTERS_FILE = "filters.json"

def load_filters() -> dict:
    """
    Формат:
    {
      "enabled": true/false,
      "seeds": ["Carrot", "Bamboo", ...],
      "crates": ["Ladder Crate", ...],
      "gear": ["Trowel", ...]
    }
    """
    if os.path.exists(FILTERS_FILE):
        with open(FILTERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "seeds": [], "crates": [], "gear": []}

def save_filters(data: dict):
    with open(FILTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
    """
    Возвращает ВСЕ предметы (даже stock=0).
    {"seeds": [...], "crates": [...], "gear": [...]}
    """
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
    """Возвращает только предметы со stock >= 1."""
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
#          ФОРМИРОВАНИЕ СООБЩЕНИЯ
# ═══════════════════════════════════════
def build_message(stock: dict) -> str:
    now = datetime.now(MOSCOW_TZ).strftime("%H:%M %d.%m.%Y")
    lines = [f"🕐 СТОК НА {now}", ""]

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

    # ── Семена ──
    lines.append("🌱 Семена:")
    seed_lines = []
    for s in stock["seeds"]:
        if should_show(s["name"], "seeds"):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            seed_lines.append(f"  {r} {s['name']}{stock_txt}")
    lines.extend(seed_lines if seed_lines else ["  — пусто —"])
    lines.append("")

    # ── Крэйты ──
    lines.append("📦 Крэйты:")
    crate_lines = []
    for s in stock["crates"]:
        if should_show(s["name"], "crates"):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            crate_lines.append(f"  {r} {s['name']}{stock_txt}")
    lines.extend(crate_lines if crate_lines else ["  — пусто —"])
    lines.append("")

    # ── Инструменты ──
    lines.append("🚿 Инструменты:")
    gear_lines = []
    for s in stock["gear"]:
        if should_show(s["name"], "gear"):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            gear_lines.append(f"  {r} {s['name']}{stock_txt}")
    lines.extend(gear_lines if gear_lines else ["  — пусто —"])

    return "\n".join(lines)

# ═══════════════════════════════════════
#          ОТПРАВКА В КАНАЛ
# ═══════════════════════════════════════
async def send_stock_to_channel(bot):
    stock = fetch_stock()
    msg = build_message(stock)

    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=msg)
        logger.info("Сток отправлен в канал")
    except Exception as e:
        logger.error(f"Ошибка отправки в канал: {e}")

# ═══════════════════════════════════════
#            ПЛАНИРОВЩИК
# ═══════════════════════════════════════
async def scheduler(bot):
    """
    Отправка в минуты, кратные 5, с задержкой 5 секунд:
    00:05, 05:05, 10:05, 15:05 и т.д.
    """
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

NOT_ADMIN_TEXT = (
    "Привет! Я бот для показа стоков из Grow A Garden 2, "
    "к сожалению пока-что лично я не общаюсь, "
    "общаюсь только в нашем ТГ канале!"
)

# ═══════════════════════════════════════
#              КОМАНДЫ
# ═══════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(NOT_ADMIN_TEXT)
        return

    await update.message.reply_text(
        "Привет, админ! 👋\n\n"
        "Доступные команды:\n"
        "🌱 /stock — посмотреть текущий сток в личке\n"
        "📤 /send — отправить сток в канал прямо сейчас\n"
        "🔧 /filter — настроить фильтр предметов\n"
        "🗑 /clearfilter — сбросить фильтр (показывать всё)"
    )

async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(NOT_ADMIN_TEXT)
        return

    await update.message.reply_text("⏳ Получаю сток...")
    stock = fetch_stock()
    await update.message.reply_text(build_message(stock))

async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(NOT_ADMIN_TEXT)
        return

    await update.message.reply_text("⏳ Отправляю сток в канал...")
    await send_stock_to_channel(context.bot)
    await update.message.reply_text("✅ Сток отправлен в канал!")

async def cmd_clearfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
    await update.message.reply_text("🗑 Фильтр сброшен — показываются все предметы.")

# ═══════════════════════════════════════
#      ФИЛЬТР — ГЛАВНОЕ МЕНЮ МАГАЗИНОВ
# ═══════════════════════════════════════
async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    await update.message.reply_text("⏳ Загружаю список предметов...")

    all_items = fetch_all_items()

    context.user_data["filter_all_items"] = all_items

    # Загружаем текущий фильтр
    filt = load_filters()
    context.user_data["filter_seeds"] = set(filt.get("seeds", []))
    context.user_data["filter_crates"] = set(filt.get("crates", []))
    context.user_data["filter_gear"] = set(filt.get("gear", []))

    await send_shop_menu(update.message, context, edit=False)


async def send_shop_menu(target, context: ContextTypes.DEFAULT_TYPE, edit: bool):
    seeds_count = len(context.user_data.get("filter_seeds", set()))
    crates_count = len(context.user_data.get("filter_crates", set()))
    gear_count = len(context.user_data.get("filter_gear", set()))

    all_items = context.user_data.get("filter_all_items", {})
    total_seeds = len(all_items.get("seeds", []))
    total_crates = len(all_items.get("crates", []))
    total_gear = len(all_items.get("gear", []))

    buttons = [
        [InlineKeyboardButton(
            f"🌱 Семена ({seeds_count}/{total_seeds})",
            callback_data="fshop|seeds|0"
        )],
        [InlineKeyboardButton(
            f"📦 Крэйты ({crates_count}/{total_crates})",
            callback_data="fshop|crates|0"
        )],
        [InlineKeyboardButton(
            f"🚿 Инструменты ({gear_count}/{total_gear})",
            callback_data="fshop|gear|0"
        )],
        [
            InlineKeyboardButton("✅ Выбрать все", callback_data="fall_select"),
            InlineKeyboardButton("☐ Снять все", callback_data="fall_deselect"),
        ],
        [
            InlineKeyboardButton("💾 Сохранить фильтр", callback_data="fsave"),
            InlineKeyboardButton("🗑 Сбросить", callback_data="freset"),
        ],
    ]

    markup = InlineKeyboardMarkup(buttons)
    text = (
        "🔧 Настройка фильтра\n\n"
        "Выбери магазин для настройки.\n"
        "Затем нажми «Сохранить фильтр».\n\n"
        f"🌱 Семена: {seeds_count} из {total_seeds}\n"
        f"📦 Крэйты: {crates_count} из {total_crates}\n"
        f"🚿 Инструменты: {gear_count} из {total_gear}"
    )

    if edit:
        await target.edit_message_text(text=text, reply_markup=markup)
    else:
        await target.reply_text(text=text, reply_markup=markup)


# ═══════════════════════════════════════
#     ФИЛЬТР — СПИСОК ПРЕДМЕТОВ МАГАЗИНА
# ═══════════════════════════════════════
def get_shop_emoji(shop: str) -> str:
    return {"seeds": "🌱", "crates": "📦", "gear": "🚿"}.get(shop, "")

def get_shop_name(shop: str) -> str:
    return {"seeds": "Семена", "crates": "Крэйты", "gear": "Инструменты"}.get(shop, "")

def get_selected_set_key(shop: str) -> str:
    return f"filter_{shop}"


async def send_shop_items(query, context: ContextTypes.DEFAULT_TYPE, shop: str, page: int):
    all_items = context.user_data.get("filter_all_items", {})
    items = all_items.get(shop, [])
    selected: set = context.user_data.get(get_selected_set_key(shop), set())

    total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    if page < 0:
        page = 0
    if page >= total_pages:
        page = total_pages - 1

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_items = items[start:end]

    buttons = []

    # Кнопки выбрать все / снять все для этого магазина
    buttons.append([
        InlineKeyboardButton(
            "✅ Выбрать все в магазине",
            callback_data=f"fshopall|{shop}|select"
        ),
        InlineKeyboardButton(
            "☐ Снять все в магазине",
            callback_data=f"fshopall|{shop}|deselect"
        ),
    ])

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

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("⬅️ Назад", callback_data=f"fshop|{shop}|{page - 1}")
        )
    nav_buttons.append(
        InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="fnoop")
    )
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton("Вперёд ➡️", callback_data=f"fshop|{shop}|{page + 1}")
        )
    buttons.append(nav_buttons)

    # Кнопка назад в меню
    buttons.append([
        InlineKeyboardButton("🔙 Назад в меню", callback_data="fmenu")
    ])

    markup = InlineKeyboardMarkup(buttons)

    emoji = get_shop_emoji(shop)
    shop_name = get_shop_name(shop)
    text = (
        f"{emoji} {shop_name}\n\n"
        f"Выбрано: {len(selected)} из {len(items)}\n"
        f"Страница {page + 1}/{total_pages}\n\n"
        "Нажми на предмет чтобы вкл/выкл ✅"
    )

    await query.edit_message_text(text=text, reply_markup=markup)


# ═══════════════════════════════════════
#          ОБРАБОТКА CALLBACK
# ═══════════════════════════════════════
async def filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        return

    data = query.data

    # ── Назад в главное меню ──
    if data == "fmenu":
        await send_shop_menu(query, context, edit=True)

    # ── Открыть магазин ──
    elif data.startswith("fshop|"):
        parts = data.split("|")
        shop = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        await send_shop_items(query, context, shop, page)

    # ── Переключить предмет ──
    elif data.startswith("ftoggle|"):
        parts = data.split("|")
        shop = parts[1]
        name = parts[2]
        key = get_selected_set_key(shop)
        selected: set = context.user_data.get(key, set())

        if name in selected:
            selected.discard(name)
        else:
            selected.add(name)

        context.user_data[key] = selected

        # Определяем текущую страницу
        all_items = context.user_data.get("filter_all_items", {})
        items = all_items.get(shop, [])
        names = [i["name"] for i in items]
        try:
            idx = names.index(name)
            page = idx // ITEMS_PER_PAGE
        except ValueError:
            page = 0

        await send_shop_items(query, context, shop, page)

    # ── Выбрать / снять все в магазине ──
    elif data.startswith("fshopall|"):
        parts = data.split("|")
        shop = parts[1]
        action = parts[2]
        key = get_selected_set_key(shop)
        all_items = context.user_data.get("filter_all_items", {})
        items = all_items.get(shop, [])

        if action == "select":
            context.user_data[key] = {i["name"] for i in items}
        else:
            context.user_data[key] = set()

        await send_shop_items(query, context, shop, 0)

    # ── Выбрать ВСЕ во всех магазинах ──
    elif data == "fall_select":
        all_items = context.user_data.get("filter_all_items", {})
        for shop in ("seeds", "crates", "gear"):
            items = all_items.get(shop, [])
            context.user_data[get_selected_set_key(shop)] = {i["name"] for i in items}
        await send_shop_menu(query, context, edit=True)

    # ── Снять ВСЕ во всех магазинах ──
    elif data == "fall_deselect":
        for shop in ("seeds", "crates", "gear"):
            context.user_data[get_selected_set_key(shop)] = set()
        await send_shop_menu(query, context, edit=True)

    # ── Сохранить фильтр ──
    elif data == "fsave":
        seeds = list(context.user_data.get("filter_seeds", set()))
        crates = list(context.user_data.get("filter_crates", set()))
        gear = list(context.user_data.get("filter_gear", set()))

        total = len(seeds) + len(crates) + len(gear)

        if total == 0:
            save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
            await query.edit_message_text(
                "⚠️ Ни один предмет не выбран — показываю всё."
            )
        else:
            save_filters({
                "enabled": True,
                "seeds": seeds,
                "crates": crates,
                "gear": gear,
            })

            text = f"✅ Фильтр сохранён!\n\nВсего выбрано: {total}\n\n"
            if seeds:
                text += "🌱 Семена:\n" + "\n".join(f"  • {n}" for n in sorted(seeds)) + "\n\n"
            if crates:
                text += "📦 Крэйты:\n" + "\n".join(f"  • {n}" for n in sorted(crates)) + "\n\n"
            if gear:
                text += "🚿 Инструменты:\n" + "\n".join(f"  • {n}" for n in sorted(gear))

            await query.edit_message_text(text)

    # ── Сбросить фильтр ──
    elif data == "freset":
        save_filters({"enabled": False, "seeds": [], "crates": [], "gear": []})
        for shop in ("seeds", "crates", "gear"):
            context.user_data[get_selected_set_key(shop)] = set()
        await send_shop_menu(query, context, edit=True)

    # ── Заглушка ──
    elif data == "fnoop":
        pass


# ═══════════════════════════════════════
#           ОБЫЧНЫЕ СООБЩЕНИЯ
# ═══════════════════════════════════════
async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text("Используй /start чтобы увидеть список команд.")
    else:
        await update.message.reply_text(NOT_ADMIN_TEXT)

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
