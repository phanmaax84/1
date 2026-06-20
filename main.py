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
    if os.path.exists(FILTERS_FILE):
        with open(FILTERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "items": []}

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
    "Mythical":  "🔴",
    "Divine":    "🔱",
    "Prismatic": "🌈",
    "Celestial": "✨",
    "Exotic":    "💎",
}

def rarity_icon(rarity: str) -> str:
    return RARITY_EMOJI.get(rarity, "▪️")

# ═══════════════════════════════════════
#              ПАРСИНГ API
# ═══════════════════════════════════════
def fetch_stock() -> dict | None:
    try:
        resp = requests.get(API_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Ошибка запроса к API: {e}")
        return None

    shops = data.get("shops") if isinstance(data, dict) else data
    if shops is None:
        shops = data

    result = {"seeds": [], "crates": [], "gear": []}

    if not isinstance(shops, dict):
        logger.error(f"Неожиданный формат shops: {type(shops)}")
        return result

    for key, value in shops.items():
        key_lower = key.lower()

        if "seed" in key_lower:
            target = "seeds"
        elif "crate" in key_lower or "egg" in key_lower:
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

            # Ищем количество в стоке
            stock_count = None
            for skey in ("stock", "Stock", "quantity", "Quantity", "amount", "remaining"):
                if skey in item:
                    stock_count = item[skey]
                    break

            # Ищем в описании если не нашли
            if stock_count is None:
                desc = str(item.get("description", "") or "")
                m = re.search(r"stock\s*[:\-]?\s*(\d+)", desc, re.IGNORECASE)
                if m:
                    stock_count = int(m.group(1))

            # Пропускаем если нет в наличии
            try:
                if stock_count is not None and int(stock_count) <= 0:
                    continue
            except (ValueError, TypeError):
                pass

            name = item.get("name") or item.get("Name") or "?"
            rarity = item.get("rarity") or item.get("Rarity") or ""
            price = item.get("price") or item.get("Price") or ""

            result[target].append({
                "name": name,
                "rarity": rarity,
                "price": price,
                "stock": stock_count,
            })

    return result

# ═══════════════════════════════════════
#          ФОРМИРОВАНИЕ СООБЩЕНИЯ
# ═══════════════════════════════════════
def build_message(stock: dict) -> str:
    now = datetime.now(MOSCOW_TZ).strftime("%H:%M %d.%m.%Y")
    lines = [f"🕐 СТОК НА {now}", ""]

    filt = load_filters()
    filter_enabled = filt.get("enabled", False)
    allowed_items = set(i.lower() for i in filt.get("items", []))

    def should_show(name: str) -> bool:
        if not filter_enabled:
            return True
        return name.lower() in allowed_items

    # ── Семена ──
    lines.append("🌱 Семена:")
    seed_lines = []
    for s in stock["seeds"]:
        if should_show(s["name"]):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            seed_lines.append(f"  {r} {s['name']}{stock_txt}")
    lines.extend(seed_lines if seed_lines else ["  — пусто —"])
    lines.append("")

    # ── Крэйты ──
    lines.append("📦 Крэйты:")
    crate_lines = []
    for s in stock["crates"]:
        if should_show(s["name"]):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (x{s['stock']})" if s["stock"] is not None else ""
            crate_lines.append(f"  {r} {s['name']}{stock_txt}")
    lines.extend(crate_lines if crate_lines else ["  — пусто —"])
    lines.append("")

    # ── Инструменты ──
    lines.append("🚿 Инструменты:")
    gear_lines = []
    for s in stock["gear"]:
        if should_show(s["name"]):
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
    if stock is None:
        logger.warning("Не удалось получить сток — пропускаю")
        return

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
            tzinfo=MOSCOW_TZ
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
        "🔧 /filter — выбрать предметы для оповещений\n"
        "🗑 /clearfilter — сбросить фильтр (показывать всё)"
    )

async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(NOT_ADMIN_TEXT)
        return

    await update.message.reply_text("⏳ Получаю сток...")
    stock = fetch_stock()

    if stock is None:
        await update.message.reply_text("❌ Не удалось получить данные от API.")
        return

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

    save_filters({"enabled": False, "items": []})
    await update.message.reply_text("🗑 Фильтр сброшен — показываются все предметы.")

async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    await update.message.reply_text("⏳ Получаю список предметов...")
    stock = fetch_stock()

    if stock is None:
        await update.message.reply_text("❌ Не удалось получить данные — попробуй позже.")
        return

    all_items = sorted({
        item["name"]
        for category in ("seeds", "crates", "gear")
        for item in stock[category]
    })

    if not all_items:
        await update.message.reply_text("Сейчас предметов в стоке нет.")
        return

    filt = load_filters()
    current = set(i.lower() for i in filt.get("items", []))

    context.user_data["filter_all_items"] = all_items
    context.user_data["filter_selected"] = {
        name for name in all_items if name.lower() in current
    }

    await _send_filter_keyboard(update.message, context, edit=False)

# ═══════════════════════════════════════
#           ФИЛЬТР — КЛАВИАТУРА
# ═══════════════════════════════════════
async def _send_filter_keyboard(target, context: ContextTypes.DEFAULT_TYPE, edit: bool):
    all_items = context.user_data["filter_all_items"]
    selected = context.user_data["filter_selected"]

    buttons = [
        [InlineKeyboardButton(
            f"{'✅' if name in selected else '☐'} {name}",
            callback_data=f"ftoggle|{name}"
        )]
        for name in all_items
    ]
    buttons.append([
        InlineKeyboardButton("💾 Применить фильтр", callback_data="fapply"),
        InlineKeyboardButton("🗑 Показывать всё", callback_data="fclear"),
    ])

    markup = InlineKeyboardMarkup(buttons)
    text = (
        "Выбери предметы для оповещения в канале.\n"
        "Нажми на предмет чтобы вкл/выкл ✅\n"
        "Затем нажми «Применить фильтр»."
    )

    if edit:
        await target.edit_message_text(text=text, reply_markup=markup)
    else:
        await target.reply_text(text=text, reply_markup=markup)

async def filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        return

    data = query.data

    if data.startswith("ftoggle|"):
        name = data.split("|", 1)[1]
        selected: set = context.user_data.get("filter_selected", set())

        if name in selected:
            selected.discard(name)
        else:
            selected.add(name)

        context.user_data["filter_selected"] = selected
        await _send_filter_keyboard(query, context, edit=True)

    elif data == "fapply":
        selected = context.user_data.get("filter_selected", set())
        if not selected:
            save_filters({"enabled": False, "items": []})
            await query.edit_message_text(
                "⚠️ Ни один предмет не выбран — показываю всё."
            )
        else:
            save_filters({"enabled": True, "items": list(selected)})
            items_list = "\n".join(f"  • {n}" for n in sorted(selected))
            await query.edit_message_text(
                f"✅ Фильтр сохранён!\n\nОповещаю только о:\n{items_list}"
            )

    elif data == "fclear":
        save_filters({"enabled": False, "items": []})
        context.user_data["filter_selected"] = set()
        await query.edit_message_text(
            "🗑 Фильтр сброшен — показываются все предметы."
        )

async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text(
            "Используй /start чтобы увидеть список команд."
        )
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
    # Запускаем Flask в отдельном потоке
    threading.Thread(target=run_web, daemon=True).start()
    logger.info(f"Flask запущен на порту {PORT}")

    # Запускаем бота
    asyncio.run(main())
