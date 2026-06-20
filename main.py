import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
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
CHANNEL_ID = os.getenv("CHANNEL_ID")          # например @myChannel или -100xxxxxxxxxx
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")   # без @, например mellfreezy
API_URL = "https://grow-a-garden-2-tracker.onrender.com/api/stock"

MOSCOW_TZ = timezone(timedelta(hours=3))       # UTC+3, поменяй если нужно

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ───────────── файл с фильтрами ─────────────
FILTERS_FILE = "filters.json"

def load_filters() -> dict:
    """Загружает фильтр предметов. Если файла нет — пустой (показывать всё)."""
    if os.path.exists(FILTERS_FILE):
        with open(FILTERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"enabled": False, "items": []}

def save_filters(data: dict):
    with open(FILTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ───────────── Рарности → эмодзи ─────────────
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
    # добавь ещё если будут новые
}

def rarity_icon(rarity: str) -> str:
    return RARITY_EMOJI.get(rarity, "▪️")

# ───────────── парсинг API ─────────────
def fetch_stock() -> dict | None:
    """Получает JSON из API и возвращает dict с тремя списками."""
    try:
        resp = requests.get(API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"Ошибка запроса к API: {e}")
        return None

    shops = data.get("shops") or data  # на случай разных форматов

    result = {"seeds": [], "crates": [], "gear": []}

    # ---- определяем ключи (API может менять регистр / формат) ----
    for key, value in (shops.items() if isinstance(shops, dict) else []):
        key_lower = key.lower()
        if "seed" in key_lower:
            target = "seeds"
        elif "crate" in key_lower or "egg" in key_lower:
            target = "crates"
        elif "gear" in key_lower or "tool" in key_lower:
            target = "gear"
        else:
            continue

        items = value if isinstance(value, list) else value.get("items", [])
        for item in items:
            # ---------- определяем количество в стоке ----------
            stock_count = None
            # вариант 1: поле stock / Stock / quantity
            for skey in ("stock", "Stock", "quantity", "Quantity", "amount", "remaining"):
                if skey in item:
                    stock_count = item[skey]
                    break

            # если не нашли — пробуем в конце описания "stock 5"
            if stock_count is None:
                desc = item.get("description", "") or ""
                import re
                m = re.search(r"stock\s*[:\-]?\s*(\d+)", desc, re.IGNORECASE)
                if m:
                    stock_count = int(m.group(1))

            # если так и не нашли — считаем что в стоке (показываем)
            if stock_count is not None and int(stock_count) <= 0:
                continue  # нет в наличии — пропускаем

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


# ───────────── формирование сообщения ─────────────
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

    # --- Семена ---
    lines.append("🌱 Семена:")
    seed_lines = []
    for s in stock["seeds"]:
        if should_show(s["name"]):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (×{s['stock']})" if s["stock"] is not None else ""
            seed_lines.append(f"  {r} {s['name']}{stock_txt}")
    if seed_lines:
        lines.extend(seed_lines)
    else:
        lines.append("  — пусто —")
    lines.append("")

    # --- Крейты ---
    lines.append("📦 Крейты:")
    crate_lines = []
    for s in stock["crates"]:
        if should_show(s["name"]):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (×{s['stock']})" if s["stock"] is not None else ""
            crate_lines.append(f"  {r} {s['name']}{stock_txt}")
    if crate_lines:
        lines.extend(crate_lines)
    else:
        lines.append("  — пусто —")
    lines.append("")

    # --- Инструменты ---
    lines.append("🚿 Инструменты:")
    gear_lines = []
    for s in stock["gear"]:
        if should_show(s["name"]):
            r = rarity_icon(s["rarity"])
            stock_txt = f" (×{s['stock']})" if s["stock"] is not None else ""
            gear_lines.append(f"  {r} {s['name']}{stock_txt}")
    if gear_lines:
        lines.extend(gear_lines)
    else:
        lines.append("  — пусто —")

    return "\n".join(lines)


# ───────────── отправка в канал ─────────────
async def send_stock_to_channel(context: ContextTypes.DEFAULT_TYPE):
    stock = fetch_stock()
    if stock is None:
        logger.warning("Не удалось получить сток — пропускаю отправку")
        return
    msg = build_message(stock)
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
        logger.info("Сток отправлен в канал")
    except Exception as e:
        logger.error(f"Ошибка отправки в канал: {e}")


# ───────────── планировщик «кратно 5 мин» ─────────────
async def scheduler(app: Application):
    """Бесконечный цикл: спит до ближайшего момента, кратного 5 мин, затем отправляет."""
    while True:
        now = datetime.now(MOSCOW_TZ)
        # вычисляем следующую «круглую» отметку
        minutes_to_next = 5 - (now.minute % 5)
        if minutes_to_next == 5 and now.second == 0:
            minutes_to_next = 0
        next_run = now.replace(second=0, microsecond=0) + timedelta(minutes=minutes_to_next)
        wait = (next_run - now).total_seconds()
        if wait < 0:
            wait = 0
        logger.info(f"Следующая отправка через {wait:.0f} сек ({next_run.strftime('%H:%M')})")
        await asyncio.sleep(wait)

        # отправляем
        await send_stock_to_channel(app)

        # маленькая пауза, чтобы не сработало дважды
        await asyncio.sleep(2)


# ───────────── хелпер: проверка админа ─────────────
def is_admin(update: Update) -> bool:
    user = update.effective_user
    return user and user.username and user.username.lower() == ADMIN_USERNAME.lower()


# ───────────── команды бота (личка) ─────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            "Привет! Я бот для показа стоков из Grow A Garden 2. "
            "К сожалению, пока что лично я не общаюсь — общаюсь только в нашем ТГ канале!"
        )
        return
    await update.message.reply_text(
        "Привет, админ! 👋\n\n"
        "Доступные команды:\n"
        "/stock — получить текущий сток прямо сейчас\n"
        "/filter — настроить фильтр предметов\n"
        "/clearfilter — сбросить фильтр (показывать всё)\n"
        "/send — принудительно отправить сток в канал"
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            "Привет! Я бот для показа стоков из Grow A Garden 2. "
            "К сожалению, пока что лично я не общаюсь — общаюсь только в нашем ТГ канале!"
        )
        return
    stock = fetch_stock()
    if stock is None:
        await update.message.reply_text("❌ Не удалось получить данные от API.")
        return
    msg = build_message(stock)
    await update.message.reply_text(msg)


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    stock = fetch_stock()
    if stock is None:
        await update.message.reply_text("❌ Не удалось получить данные от API.")
        return
    msg = build_message(stock)
    await context.bot.send_message(chat_id=CHANNEL_ID, text=msg)
    await update.message.reply_text("✅ Отправлено в канал!")


async def cmd_clearfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    save_filters({"enabled": False, "items": []})
    await update.message.reply_text("🗑 Фильтр сброшен — показываются все предметы.")


# ───────── /filter — интерактивная настройка ─────────
async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    stock = fetch_stock()
    if stock is None:
        await update.message.reply_text("❌ Не удалось получить данные — попробуй позже.")
        return

    # собираем все предметы
    all_items = []
    for category in ("seeds", "crates", "gear"):
        for item in stock[category]:
            all_items.append(item["name"])
    all_items = sorted(set(all_items))

    if not all_items:
        await update.message.reply_text("Сейчас в стоке ничего нет.")
        return

    filt = load_filters()
    current = set(i.lower() for i in filt.get("items", []))

    # Сохраняем список во временные данные
    context.user_data["filter_all_items"] = all_items
    context.user_data["filter_selected"] = set(
        name for name in all_items if name.lower() in current
    )

    await _send_filter_keyboard(update, context)


async def _send_filter_keyboard(update_or_query, context: ContextTypes.DEFAULT_TYPE, edit=False):
    all_items = context.user_data["filter_all_items"]
    selected = context.user_data["filter_selected"]

    buttons = []
    for name in all_items:
        check = "✅" if name in selected else "☐"
        buttons.append(
            [InlineKeyboardButton(f"{check} {name}", callback_data=f"ftoggle|{name}")]
        )
    buttons.append([
        InlineKeyboardButton("✅ Применить фильтр", callback_data="fapply"),
        InlineKeyboardButton("🗑 Показывать всё", callback_data="fclear"),
    ])

    markup = InlineKeyboardMarkup(buttons)
    text = (
        "Выбери предметы, о которых нужно оповещать.\n"
        "Нажми на предмет чтобы вкл/выкл, затем «Применить»."
    )

    if edit:
        await update_or_query.edit_message_text(text=text, reply_markup=markup)
    else:
        if hasattr(update_or_query, "message") and update_or_query.message:
            await update_or_query.message.reply_text(text=text, reply_markup=markup)
        else:
            await update_or_query.edit_message_text(text=text, reply_markup=markup)


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
            await query.edit_message_text("Фильтр пуст — буду показывать всё.")
        else:
            save_filters({"enabled": True, "items": list(selected)})
            await query.edit_message_text(
                f"✅ Фильтр сохранён!\nОповещаю только о:\n" +
                "\n".join(f"• {n}" for n in sorted(selected))
            )

    elif data == "fclear":
        save_filters({"enabled": False, "items": []})
        context.user_data["filter_selected"] = set()
        await query.edit_message_text("🗑 Фильтр сброшен — показываются все предметы.")


# ───────── обработка любого другого сообщения ─────────
async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_text("Используй /start чтобы увидеть команды.")
        return
    await update.message.reply_text(
        "Привет! Я бот для показа стоков из Grow A Garden 2. "
        "К сожалению, пока что лично я не общаюсь — общаюсь только в нашем ТГ канале!"
    )


# ───────────── MAIN ─────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CommandHandler("clearfilter", cmd_clearfilter))
    app.add_handler(CallbackQueryHandler(filter_callback, pattern=r"^f"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_message))

    # Запускаем фоновый планировщик
    loop = asyncio.get_event_loop()

    async def post_init(application: Application):
        asyncio.create_task(scheduler(application))

    app.post_init = post_init

    logger.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
