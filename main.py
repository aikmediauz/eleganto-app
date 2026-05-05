#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ELEGANTO BOT — Professional Telegram + Instagram Smart Posting System
Telegram Mini App integration | CRM | Admin Panel
Server: 178.104.244.244 (Germany)
"""

import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InputMediaPhoto, BotCommand, WebAppInfo
)
import sqlite3
import requests
import json
import threading
import logging
import time
import os
from io import BytesIO
from datetime import datetime
from flask import Flask, request as freq, jsonify, send_file
from flask_cors import CORS

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('eleganto.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# KONFIGURATSIYA
# ============================================================
BOT_TOKEN       = "8535504410:AAEuoYejceti5s81TsbOeKSQvmifa2fR7i8"
IG_ACCESS_TOKEN = "EAARvTumZAhokBRSCZA7xkHh6vx3ZC0zutZC2brAVcT2s63x0saLBrk4X4tfshsya6wJd0YJZAtqkFLtr9JvzZCBDwGZAjLnxOYsr97cjLDONKS5r7NPPW59ZARaFSLZAVnDBhTEUZBTrpvw1Td1lBgf2ZASUhXkZBOCjlnrh9eIH9Lq6bolcuW4IxlND6iUl1MJPjTzXMwZDZD"
ADMIN_ID        = 5909461027
TG_CHANNEL_ID   = "@elegantoshop"
IG_USER_ID      = "17841438342515729"
FLASK_PORT      = 8080
IG_API_BASE     = "https://graph.facebook.com/v19.0"
DB_PATH         = "eleganto_business.db"

# ⚠️ Quyidagi ikkitasini Cloudflare Tunnel URL bilan almashtiring:
# cloudflared tunnel --url http://localhost:8080
# buyruqni ishga tushirgandan keyin beriladigan URL ni qo'ying.
# ⬇️ cloudflared tunnel --url http://localhost:8080  buyrug'ini ishga tushirib,
#    berilgan URL ni bu yerga qo'ying. Masalan:
#    SERVER_URL = "https://abc-xyz.trycloudflare.com"
SERVER_URL   = "https://YOUR_CLOUDFLARE_URL_HERE"   # ← O'zgartiring!
MINI_APP_URL = SERVER_URL + "/"                      # Flask index.html ni avtomatik beradi

# Default kategoriyalar va subkategoriyalar
CATEGORIES = {
    "👔 Erkaklar": [
        "Futbolka", "Kurtka", "Klassik ko'ylak", "Shim",
        "Sviter", "Jinsi", "Jaket", "Sport kiyim", "Trening"
    ],
    "👗 Ayollar": [
        "Ko'ylak", "Yubka", "Bluzka", "Platye",
        "Futbolka", "Kurtka", "Kardigan", "Shim"
    ],
    "👟 Oyoq kiyim": [
        "Klassik", "Sport", "Casual", "Botinka", "Sandal", "Krossovka"
    ],
    "👜 Aksessuarlar": [
        "Sumka", "Kamar", "Sharf", "Soat", "Qo'lqop", "Ko'zoynaklar", "Kepka"
    ]
}

# ============================================================
# BOT VA FLASK INIT
# ============================================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Admin holati (xotirada)
admin_states = {}

# ============================================================
# DATABASE
# ============================================================
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        telegram_id   INTEGER PRIMARY KEY,
        full_name     TEXT,
        phone         TEXT,
        state         TEXT DEFAULT 'idle',
        registered_at TEXT DEFAULT (datetime('now','localtime'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        sku          TEXT UNIQUE NOT NULL,
        category     TEXT,
        subcategory  TEXT DEFAULT '',
        name         TEXT,
        price        REAL,
        images       TEXT DEFAULT '[]',
        tg_msg_id    INTEGER,
        ig_media_id  TEXT,
        created_at   TEXT DEFAULT (datetime('now','localtime'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_telegram_id INTEGER,
        product_sku      TEXT,
        size             TEXT DEFAULT '-',
        color            TEXT DEFAULT '-',
        quantity         INTEGER DEFAULT 1,
        status           TEXT DEFAULT 'new',
        created_at       TEXT DEFAULT (datetime('now','localtime'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS wishlist (
        user_telegram_id INTEGER,
        product_sku      TEXT,
        PRIMARY KEY (user_telegram_id, product_sku)
    )''')

    conn.commit()
    conn.close()
    logger.info("✅ Database tayyor: %s", DB_PATH)


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================
def fmt_price(price):
    """150000 → 150 000 so'm"""
    try:
        return f"{int(float(price)):,} so'm".replace(",", " ")
    except Exception:
        return f"{price} so'm"


def get_user(tid):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (tid,)).fetchone()
    conn.close()
    return row


def save_user(tid, full_name=None, phone=None, state=None):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (tid,))
    if full_name is not None:
        conn.execute("UPDATE users SET full_name=? WHERE telegram_id=?", (full_name, tid))
    if phone is not None:
        conn.execute("UPDATE users SET phone=? WHERE telegram_id=?", (phone, tid))
    if state is not None:
        conn.execute("UPDATE users SET state=? WHERE telegram_id=?", (state, tid))
    conn.commit()
    conn.close()


def get_tg_file_url(file_id):
    """Telegram file_id → ochiq URL (Instagram uchun ham ishlatiladi)"""
    info = bot.get_file(file_id)
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info.file_path}"


# ============================================================
# RASM TAYYORLASH — Document → Photo muammosi yechimi
# ============================================================
def _reupload_as_photo(data: bytes) -> str:
    """Raw bytes → Telegram photo file_id"""
    buf = BytesIO(data)
    buf.name = "photo.jpg"
    msg = bot.send_photo(ADMIN_ID, buf)
    return msg.photo[-1].file_id


def upload_from_url(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return _reupload_as_photo(r.content)


def upload_from_file_id(file_id: str) -> str:
    """Document yoki xom file_id → photo file_id"""
    info = bot.get_file(file_id)
    data = bot.download_file(info.file_path)
    return _reupload_as_photo(data)


def prepare_photos(items: list) -> list:
    """
    items: [('url', 'https://...'), ('file_id', 'xxx'), ...]
    Returns: [photo_file_id, ...]
    """
    result = []
    for kind, val in items:
        try:
            if kind == 'url':
                pid = upload_from_url(val)
            else:
                pid = upload_from_file_id(val)
            result.append(pid)
            logger.info("Photo uploaded: %s → %s", val[:40], pid[:20])
        except Exception as e:
            logger.error("Photo upload failed (%s): %s", val[:40], e)
    return result


# ============================================================
# TELEGRAM KANAL POST
# ============================================================
def post_to_channel(photo_ids: list, caption: str) -> int | None:
    if not photo_ids:
        return None
    try:
        if len(photo_ids) == 1:
            msg = bot.send_photo(TG_CHANNEL_ID, photo_ids[0], caption=caption)
            return msg.message_id
        else:
            media = [
                InputMediaPhoto(pid, caption=caption if i == 0 else "")
                for i, pid in enumerate(photo_ids)
            ]
            msgs = bot.send_media_group(TG_CHANNEL_ID, media)
            return msgs[0].message_id
    except Exception as e:
        logger.error("Channel post error: %s", e)
        return None


# ============================================================
# INSTAGRAM API
# ============================================================
def _ig_create_single(image_url: str, caption: str) -> str:
    r = requests.post(
        f"{IG_API_BASE}/{IG_USER_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": IG_ACCESS_TOKEN
        },
        timeout=30
    )
    r.raise_for_status()
    cid = r.json().get("id")
    if not cid:
        raise ValueError(f"IG create media failed: {r.text}")
    return cid


def _ig_publish(creation_id: str) -> str:
    r = requests.post(
        f"{IG_API_BASE}/{IG_USER_ID}/media_publish",
        data={
            "creation_id": creation_id,
            "access_token": IG_ACCESS_TOKEN
        },
        timeout=30
    )
    r.raise_for_status()
    mid = r.json().get("id")
    if not mid:
        raise ValueError(f"IG publish failed: {r.text}")
    return mid


def ig_post_single(image_url: str, caption: str) -> str:
    cid = _ig_create_single(image_url, caption)
    time.sleep(3)
    return _ig_publish(cid)


def ig_post_carousel(image_urls: list, caption: str) -> str:
    children = []
    for url in image_urls:
        r = requests.post(
            f"{IG_API_BASE}/{IG_USER_ID}/media",
            data={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": IG_ACCESS_TOKEN
            },
            timeout=30
        )
        r.raise_for_status()
        cid = r.json().get("id")
        if cid:
            children.append(cid)
        time.sleep(1)

    if not children:
        raise ValueError("No carousel children")

    time.sleep(2)

    r2 = requests.post(
        f"{IG_API_BASE}/{IG_USER_ID}/media",
        data={
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
            "access_token": IG_ACCESS_TOKEN
        },
        timeout=30
    )
    r2.raise_for_status()
    carousel_id = r2.json().get("id")
    if not carousel_id:
        raise ValueError(f"Carousel create failed: {r2.text}")

    time.sleep(3)
    return _ig_publish(carousel_id)


def post_to_instagram(photo_ids: list, caption: str) -> str | None:
    try:
        urls = [get_tg_file_url(pid) for pid in photo_ids]
        if len(urls) == 1:
            return ig_post_single(urls[0], caption)
        else:
            return ig_post_carousel(urls, caption)
    except Exception as e:
        logger.error("Instagram post error: %s", e)
        return None


def delete_from_instagram(media_id: str) -> bool:
    try:
        r = requests.delete(
            f"{IG_API_BASE}/{media_id}",
            params={"access_token": IG_ACCESS_TOKEN},
            timeout=15
        )
        return r.status_code == 200
    except Exception as e:
        logger.error("Instagram delete error: %s", e)
        return False


# ============================================================
# CAPTION YARATISH
# ============================================================
def make_tg_caption(sku, category, name, price, subcategory=""):
    sub = f" · {subcategory}" if subcategory else ""
    return (
        f"✨ <b>ELEGANTO</b>\n\n"
        f"👗 <b>{name}</b>\n"
        f"🏷 {category}{sub}\n"
        f"💰 <b>{fmt_price(price)}</b>\n\n"
        f"🛍 Buyurtma: @ElegantoBot\n"
        f"📌 Artikul: <code>{sku}</code>"
    )


def make_ig_caption(sku, category, name, price, subcategory=""):
    sub = f" · {subcategory}" if subcategory else ""
    return (
        f"✨ ELEGANTO\n\n"
        f"{name}\n"
        f"{category}{sub}\n"
        f"{fmt_price(price)}\n\n"
        f"Buyurtma: @elegantoshop\n"
        f"Artikul: {sku}\n\n"
        f"#eleganto #fashion #uzbekistan #kiyim #style #outfit"
    )


# ============================================================
# KLAVIATURALAR
# ============================================================
def main_menu_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        "🛍 Do'konni ochish",
        web_app=WebAppInfo(url=MINI_APP_URL)
    ))
    kb.row(
        InlineKeyboardButton("📞 Bog'lanish", callback_data="contact"),
        InlineKeyboardButton("ℹ️ Haqida", callback_data="about")
    )
    return kb


def admin_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📊 Statistika",       callback_data="a_stats"),
        InlineKeyboardButton("👥 Mijozlar ro'yxati", callback_data="a_customers"),
        InlineKeyboardButton("🗑 Mahsulot o'chirish", callback_data="a_delete"),
        InlineKeyboardButton("📢 Xabar yuborish",   callback_data="a_broadcast"),
        InlineKeyboardButton("📦 Buyurtmalar",       callback_data="a_orders")
    )
    return kb


def phone_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("📞 Raqamni ulashish", request_contact=True))
    return kb


def back_admin_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("◀️ Orqaga", callback_data="a_back"))
    return kb


def cancel_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Bekor qilish", callback_data="a_cancel"))
    return kb


# ============================================================
# /start
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    uid = msg.from_user.id
    user = get_user(uid)

    if user and user['phone']:
        bot.send_message(
            uid,
            f"👋 Xush kelibsiz, <b>{user['full_name']}</b>!\n\n"
            f"✨ <b>ELEGANTO</b> — Premium kiyim koleksiyasi\n\n"
            f"Do'konimizga kirish uchun quyidagi tugmani bosing:",
            reply_markup=main_menu_kb()
        )
    else:
        save_user(uid, state='waiting_name')
        bot.send_message(
            uid,
            "👋 Xush kelibsiz <b>ELEGANTO</b>'ga!\n\n"
            "✨ Eksklyuziv kiyim koleksiyamiz bilan tanishing.\n\n"
            "Avval ro'yxatdan o'tamiz — <b>ismingizni yuboring:</b>",
            reply_markup=ReplyKeyboardRemove()
        )


# ============================================================
# /menu
# ============================================================
@bot.message_handler(commands=['menu'])
def cmd_menu(msg):
    uid = msg.from_user.id
    user = get_user(uid)
    name = (user['full_name'] or "Mehmon") if user else "Mehmon"
    bot.send_message(
        uid,
        f"🛍 <b>ELEGANTO Do'koni</b>\n\nSalom, {name}!",
        reply_markup=main_menu_kb()
    )


# ============================================================
# /add — Mahsulot qo'shish
# ============================================================
@bot.message_handler(commands=['add'])
def cmd_add(msg):
    if msg.from_user.id != ADMIN_ID:
        return

    text = msg.text[4:].strip()  # '/add' dan keyingi qism

    if not text:
        bot.send_message(
            ADMIN_ID,
            "📦 <b>Mahsulot qo'shish</b>\n\n"
            "<b>Format:</b>\n"
            "<code>SKU | Kategoriya | Nomi | Narx | URL1,URL2</code>\n\n"
            "<b>Misol:</b>\n"
            "<code>EL-001 | Erkaklar | Klassik Ko'ylak | 150000 | https://...</code>\n\n"
            "💡 URL ishlamasa yoki yo'q bo'lsa:\n"
            "<code>EL-001 | Erkaklar | Ko'ylak | 150000</code>\n"
            "— keyin rasmlarni yuboring va <b>/done</b> yozing."
        )
        return

    _parse_add(text)


def _parse_add(text: str):
    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 4:
        bot.send_message(
            ADMIN_ID,
            "❌ Kamida 4 bo'lim kerak:\n"
            "<code>SKU | Kategoriya | Nomi | Narx</code>"
        )
        return

    sku      = parts[0].upper()
    category = parts[1]
    name     = parts[2]
    price_s  = parts[3].replace(' ', '').replace(',', '').replace("'", "")
    urls_s   = parts[4] if len(parts) > 4 else ""

    try:
        price = float(price_s)
    except ValueError:
        bot.send_message(ADMIN_ID, f"❌ Narx noto'g'ri: <code>{price_s}</code>")
        return

    # SKU takrorlanmagan bo'lsin
    conn = get_db()
    if conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone():
        conn.close()
        bot.send_message(ADMIN_ID, f"❌ <code>{sku}</code> SKU allaqachon mavjud!")
        return
    conn.close()

    # Admin holatini sozlash
    admin_states[ADMIN_ID] = {
        'state':  'collecting_images',
        'data':   {'sku': sku, 'category': category, 'name': name,
                   'price': price, 'subcategory': ''},
        'images': []
    }

    if not urls_s:
        bot.send_message(
            ADMIN_ID,
            f"📸 <b>{name}</b> uchun rasmlarni yuboring.\n"
            f"Tugagach <b>/done</b> yozing."
        )
        return

    # URL'larni tekshirish
    urls = [u.strip() for u in urls_s.split(',') if u.strip()]
    wait = bot.send_message(ADMIN_ID, f"🔄 {len(urls)} ta URL tekshirilmoqda...")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    }
    valid, blocked = [], []
    for url in urls:
        try:
            r = requests.head(url, headers=headers, timeout=7, allow_redirects=True)
            if r.status_code == 403:
                blocked.append(url)
            elif r.status_code < 400:
                valid.append(('url', url))
            else:
                blocked.append(url)
        except Exception:
            blocked.append(url)

    try:
        bot.delete_message(ADMIN_ID, wait.message_id)
    except Exception:
        pass

    if blocked:
        bot.send_message(
            ADMIN_ID,
            f"⚠️ {len(blocked)} ta link bloklangan yoki ishlamadi.\n\n"
            f"Iltimos rasmlarni <b>galereya</b> orqali yoki "
            f"<b>fayl</b> ko'rinishida yuboring, so'ng <b>/done</b> yozing."
        )
        if valid:
            w2 = bot.send_message(ADMIN_ID, f"⏳ {len(valid)} ta rasm yuklanmoqda...")
            pids = prepare_photos(valid)
            admin_states[ADMIN_ID]['images'].extend(pids)
            try:
                bot.delete_message(ADMIN_ID, w2.message_id)
            except Exception:
                pass
            bot.send_message(ADMIN_ID, f"✅ {len(pids)} ta rasm saqlandi. Qolganlarni yuboring.")
        return

    # Hammasi ishlaydi
    w2 = bot.send_message(ADMIN_ID, f"⏳ {len(valid)} ta rasm yuklanmoqda...")
    pids = prepare_photos(valid)
    try:
        bot.delete_message(ADMIN_ID, w2.message_id)
    except Exception:
        pass

    if pids:
        admin_states[ADMIN_ID]['images'] = pids
        _finalize_product(pids)
    else:
        bot.send_message(
            ADMIN_ID,
            "❌ Rasmlar yuklanmadi. Galereya orqali yuboring, so'ng /done."
        )


def _finalize_product(photo_ids: list):
    st = admin_states.get(ADMIN_ID)
    if not st:
        return

    d        = st['data']
    sku      = d['sku']
    category = d['category']
    name     = d['name']
    price    = d['price']
    sub      = d.get('subcategory', '')

    wait = bot.send_message(ADMIN_ID, "📤 Post qilinmoqda, iltimos kuting…")

    tg_caption = make_tg_caption(sku, category, name, price, sub)
    ig_caption = make_ig_caption(sku, category, name, price, sub)

    tg_msg_id = post_to_channel(photo_ids, tg_caption)
    ig_id     = post_to_instagram(photo_ids, ig_caption)

    images_json = json.dumps(photo_ids)
    conn = get_db()
    conn.execute(
        '''INSERT OR REPLACE INTO products
           (sku, category, subcategory, name, price, images, tg_msg_id, ig_media_id)
           VALUES (?,?,?,?,?,?,?,?)''',
        (sku, category, sub, name, price, images_json, tg_msg_id, ig_id)
    )
    conn.commit()
    conn.close()

    try:
        bot.delete_message(ADMIN_ID, wait.message_id)
    except Exception:
        pass

    tg_s = f"✅ Telegram: #{tg_msg_id}" if tg_msg_id else "⚠️ Telegram: yuklanmadi"
    ig_s = f"✅ Instagram: {ig_id}" if ig_id else "⚠️ Instagram: yuklanmadi"

    bot.send_message(
        ADMIN_ID,
        f"✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"🏷 SKU: <code>{sku}</code>\n"
        f"👗 Nomi: {name}\n"
        f"🏷 Kategoriya: {category}\n"
        f"💰 Narx: {fmt_price(price)}\n"
        f"🖼 Rasmlar: {len(photo_ids)} ta\n\n"
        f"{tg_s}\n{ig_s}"
    )

    admin_states.pop(ADMIN_ID, None)


# ============================================================
# /done — Rasm yuborishni yakunlash
# ============================================================
@bot.message_handler(commands=['done'])
def cmd_done(msg):
    if msg.from_user.id != ADMIN_ID:
        return

    st = admin_states.get(ADMIN_ID)
    if not st:
        bot.send_message(ADMIN_ID, "❌ Aktiv jarayon yo'q.")
        return

    imgs = st.get('images', [])
    if not imgs:
        bot.send_message(ADMIN_ID, "❌ Hech qanday rasm yuklanmadi. Rasmlarni yuboring.")
        return

    _finalize_product(imgs)


# ============================================================
# /admin
# ============================================================
@bot.message_handler(commands=['admin'])
def cmd_admin(msg):
    if msg.from_user.id != ADMIN_ID:
        return

    conn = get_db()
    u = conn.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL").fetchone()[0]
    p = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    o = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()

    bot.send_message(
        ADMIN_ID,
        f"🎛 <b>ELEGANTO Admin Panel</b>\n\n"
        f"👥 Mijozlar: <b>{u}</b>\n"
        f"📦 Mahsulotlar: <b>{p}</b>\n"
        f"🛒 Buyurtmalar: <b>{o}</b>\n\n"
        f"Kerakli bo'limni tanlang:",
        reply_markup=admin_kb()
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================
@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    uid  = call.from_user.id
    data = call.data
    chat = call.message.chat.id
    mid  = call.message.message_id

    # ── Foydalanuvchi callbacklari ──────────────────────────
    if data == "contact":
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            "📞 <b>Bog'lanish</b>\n\n"
            "📱 Telegram: @elegantoshop\n"
            "📸 Instagram: @eleganto.shop\n"
            "🕐 Ish vaqti: 9:00 — 21:00"
        )
        return

    if data == "about":
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            "✨ <b>ELEGANTO haqida</b>\n\n"
            "Premium kiyim va aksessuarlar do'koni.\n"
            "Sifat va nafosatni birlashtiramiz.\n\n"
            "🌟 Eksklyuziv kolleksiyalar\n"
            "🚚 Tez yetkazib berish\n"
            "💎 Sifat kafolati"
        )
        return

    # ── Admin callbacklari ──────────────────────────────────
    if uid != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Ruxsat yo'q!")
        return

    if data == "a_back":
        bot.answer_callback_query(call.id)
        conn = get_db()
        u = conn.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL").fetchone()[0]
        p = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        o = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        conn.close()
        try:
            bot.edit_message_text(
                f"🎛 <b>ELEGANTO Admin Panel</b>\n\n"
                f"👥 Mijozlar: <b>{u}</b>\n"
                f"📦 Mahsulotlar: <b>{p}</b>\n"
                f"🛒 Buyurtmalar: <b>{o}</b>",
                chat, mid, reply_markup=admin_kb()
            )
        except Exception:
            pass
        return

    if data == "a_cancel":
        bot.answer_callback_query(call.id, "Bekor qilindi.")
        admin_states.pop(ADMIN_ID, None)
        try:
            bot.delete_message(chat, mid)
        except Exception:
            pass
        return

    # ── Statistika ──────────────────────────────────────────
    if data == "a_stats":
        bot.answer_callback_query(call.id)
        conn = get_db()
        u       = conn.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL").fetchone()[0]
        p       = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        o_all   = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        o_new   = conn.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
        o_today = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now','localtime')"
        ).fetchone()[0]
        conn.close()
        try:
            bot.edit_message_text(
                f"📊 <b>Statistika</b>\n\n"
                f"👥 Mijozlar: <b>{u}</b>\n"
                f"📦 Mahsulotlar: <b>{p}</b>\n"
                f"🛒 Jami buyurtmalar: <b>{o_all}</b>\n"
                f"🆕 Yangi buyurtmalar: <b>{o_new}</b>\n"
                f"📅 Bugungi buyurtmalar: <b>{o_today}</b>",
                chat, mid, reply_markup=back_admin_kb()
            )
        except Exception:
            pass
        return

    # ── Mijozlar ro'yxati ───────────────────────────────────
    if data == "a_customers":
        bot.answer_callback_query(call.id)
        conn = get_db()
        users = conn.execute(
            "SELECT telegram_id, full_name, phone, registered_at "
            "FROM users WHERE phone IS NOT NULL ORDER BY registered_at DESC"
        ).fetchall()
        conn.close()

        if not users:
            bot.answer_callback_query(call.id, "Hozircha mijozlar yo'q.")
            return

        lines = ["ELEGANTO — Mijozlar Ro'yxati", "=" * 50, ""]
        for u in users:
            lines.append(f"ID:   {u['telegram_id']}")
            lines.append(f"Ism:  {u['full_name'] or 'Noma\\'lum'}")
            lines.append(f"Tel:  {u['phone']}")
            lines.append(f"Sana: {u['registered_at']}")
            lines.append("-" * 30)
        lines.append(f"\nJami: {len(users)} ta mijoz")

        buf = BytesIO("\n".join(lines).encode('utf-8'))
        buf.name = f"eleganto_customers_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        bot.send_document(
            ADMIN_ID, buf,
            caption=f"👥 Jami <b>{len(users)}</b> ta mijoz"
        )
        return

    # ── Mahsulot o'chirish ──────────────────────────────────
    if data == "a_delete":
        bot.answer_callback_query(call.id)
        admin_states[ADMIN_ID] = {'state': 'waiting_delete_sku', 'data': {}, 'images': []}
        try:
            bot.edit_message_text(
                "🗑 <b>Mahsulot o'chirish</b>\n\n"
                "O'chirmoqchi bo'lgan mahsulotning <b>SKU</b> (Artikul) ni yuboring:\n\n"
                "Misol: <code>EL-001</code>",
                chat, mid, reply_markup=cancel_kb()
            )
        except Exception:
            pass
        return

    # ── Xabar yuborish (Broadcast) ──────────────────────────
    if data == "a_broadcast":
        bot.answer_callback_query(call.id)
        admin_states[ADMIN_ID] = {'state': 'waiting_broadcast', 'data': {}, 'images': []}
        try:
            bot.edit_message_text(
                "📢 <b>Xabar yuborish</b>\n\n"
                "Barcha mijozlarga yuboriladigan xabarni yozing:\n"
                "(Matn, rasm yoki ikkalasi ham bo'lishi mumkin)",
                chat, mid, reply_markup=cancel_kb()
            )
        except Exception:
            pass
        return

    # ── Buyurtmalar ─────────────────────────────────────────
    if data == "a_orders":
        bot.answer_callback_query(call.id)
        conn = get_db()
        rows = conn.execute(
            '''SELECT o.id, o.product_sku, o.size, o.color, o.quantity,
                      o.status, o.created_at, u.full_name, u.phone
               FROM orders o
               LEFT JOIN users u ON o.user_telegram_id = u.telegram_id
               ORDER BY o.created_at DESC LIMIT 20'''
        ).fetchall()
        conn.close()

        if not rows:
            bot.answer_callback_query(call.id, "Hozircha buyurtmalar yo'q.")
            return

        emoji = {"new": "🆕", "confirmed": "✅", "done": "📦"}
        text = "📦 <b>So'nggi 20 buyurtma:</b>\n\n"
        for r in rows:
            e = emoji.get(r['status'], "❓")
            text += (
                f"{e} #{r['id']} — <code>{r['product_sku']}</code>\n"
                f"   👤 {r['full_name'] or 'Noma\\'lum'} | 📞 {r['phone'] or '-'}\n"
                f"   📏 {r['size']} | 🎨 {r['color']} | x{r['quantity']}\n"
                f"   🕐 {r['created_at']}\n\n"
            )
        bot.send_message(ADMIN_ID, text, reply_markup=admin_kb())
        return

    # ── Buyurtma tasdiqlash / bekor qilish ─────────────────
    if data.startswith("confirm_order_"):
        oid = data.replace("confirm_order_", "")
        conn = get_db()
        conn.execute("UPDATE orders SET status='confirmed' WHERE id=?", (oid,))
        conn.commit()
        o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        conn.close()
        if o:
            try:
                bot.send_message(
                    o['user_telegram_id'],
                    "✅ <b>Buyurtmangiz tasdiqlandi!</b>\n\n"
                    "📞 Admin siz bilan tez orada bog'lanadi."
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id, "✅ Tasdiqlandi!")
        try:
            bot.edit_message_reply_markup(chat, mid, reply_markup=None)
        except Exception:
            pass
        return

    if data.startswith("cancel_order_"):
        oid = data.replace("cancel_order_", "")
        conn = get_db()
        conn.execute("UPDATE orders SET status='cancelled' WHERE id=?", (oid,))
        conn.commit()
        o = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        conn.close()
        if o:
            try:
                bot.send_message(
                    o['user_telegram_id'],
                    "❌ <b>Buyurtmangiz bekor qilindi.</b>\n\n"
                    "Savollar bo'lsa: @elegantoshop"
                )
            except Exception:
                pass
        bot.answer_callback_query(call.id, "❌ Bekor qilindi.")
        try:
            bot.edit_message_reply_markup(chat, mid, reply_markup=None)
        except Exception:
            pass
        return


# ============================================================
# MINI APP — web_app_data
# ============================================================
@bot.message_handler(content_types=['web_app_data'])
def on_web_app(msg):
    uid = msg.from_user.id
    try:
        payload = json.loads(msg.web_app_data.data)
        ptype   = payload.get('type', '')

        if ptype == 'ORDER':
            items    = payload.get('items', [])
            total    = payload.get('total', 0)
            user     = get_user(uid)

            conn = get_db()
            oids = []
            for item in items:
                conn.execute(
                    '''INSERT INTO orders
                       (user_telegram_id, product_sku, size, color, quantity)
                       VALUES (?,?,?,?,?)''',
                    (uid,
                     item.get('sku', '-'),
                     item.get('size', '-'),
                     item.get('color', '-'),
                     item.get('qty', 1))
                )
                oids.append(conn.lastrowid)
            conn.commit()
            conn.close()

            items_txt = ""
            for it in items:
                items_txt += (
                    f"  • <b>{it.get('name','-')}</b> "
                    f"(<code>{it.get('sku','-')}</code>)\n"
                    f"    📏 {it.get('size','-')} | "
                    f"🎨 {it.get('color','-')} | "
                    f"x{it.get('qty',1)}\n"
                    f"    💰 {fmt_price(it.get('price',0))}\n\n"
                )

            confirm_kb = InlineKeyboardMarkup(row_width=2)
            if oids:
                confirm_kb.add(
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{oids[0]}"),
                    InlineKeyboardButton("❌ Bekor",      callback_data=f"cancel_order_{oids[0]}")
                )

            bot.send_message(
                ADMIN_ID,
                f"🛒 <b>YANGI BUYURTMA!</b>\n\n"
                f"👤 Ism: <b>{user['full_name'] if user else 'Noma\\'lum'}</b>\n"
                f"📞 Tel: <b>{user['phone'] if user else '-'}</b>\n"
                f"🆔 Telegram: <code>{uid}</code>\n\n"
                f"📦 <b>Buyurtma:</b>\n{items_txt}"
                f"💰 <b>Jami: {fmt_price(total)}</b>",
                reply_markup=confirm_kb
            )

            bot.send_message(
                uid,
                "✅ <b>Buyurtmangiz qabul qilindi!</b>\n\n"
                "📞 Admin tez orada siz bilan bog'lanadi.\n"
                "🕐 Kutish vaqti: 10–30 daqiqa"
            )

    except Exception as e:
        logger.error("web_app_data error: %s", e)


# ============================================================
# UNIVERSAL XABAR HANDLERI (matn, kontakt, rasm, fayl)
# ============================================================
@bot.message_handler(content_types=['text', 'contact', 'photo', 'document'])
def on_message(msg):
    uid = msg.from_user.id

    # ── ADMIN holati ────────────────────────────────────────
    if uid == ADMIN_ID and uid in admin_states:
        st    = admin_states[uid]
        state = st['state']

        # Rasm to'plash
        if state == 'collecting_images':
            if msg.content_type == 'photo':
                pid = msg.photo[-1].file_id
                admin_states[uid]['images'].append(pid)
                n = len(admin_states[uid]['images'])
                bot.send_message(uid, f"✅ {n} ta rasm saqlandi. Davom eting yoki /done.")
                return

            if msg.content_type == 'document':
                mime = msg.document.mime_type or ''
                if 'image' in mime:
                    try:
                        pid = upload_from_file_id(msg.document.file_id)
                        admin_states[uid]['images'].append(pid)
                        n = len(admin_states[uid]['images'])
                        bot.send_message(
                            uid,
                            f"✅ {n} ta rasm saqlandi (fayl → photo). "
                            f"Davom eting yoki /done."
                        )
                    except Exception as e:
                        bot.send_message(uid, f"❌ Fayl yuklanmadi: {e}")
                else:
                    bot.send_message(uid, "❌ Faqat rasm fayllarini yuboring (JPG, PNG, WEBP).")
                return

        # SKU o'chirish
        if state == 'waiting_delete_sku' and msg.content_type == 'text':
            sku = msg.text.strip().upper()
            conn = get_db()
            prod = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
            if not prod:
                conn.close()
                bot.send_message(uid, f"❌ <code>{sku}</code> SKU topilmadi.")
                return

            wait = bot.send_message(uid, f"🗑 <code>{sku}</code> o'chirilmoqda…")

            tg_ok = False
            if prod['tg_msg_id']:
                try:
                    bot.delete_message(TG_CHANNEL_ID, prod['tg_msg_id'])
                    tg_ok = True
                except Exception as e:
                    logger.error("TG delete: %s", e)

            ig_ok = False
            if prod['ig_media_id']:
                ig_ok = delete_from_instagram(prod['ig_media_id'])

            conn.execute("DELETE FROM wishlist WHERE product_sku=?", (sku,))
            conn.execute("DELETE FROM products WHERE sku=?", (sku,))
            conn.commit()
            conn.close()

            admin_states.pop(uid, None)
            try:
                bot.delete_message(uid, wait.message_id)
            except Exception:
                pass

            bot.send_message(
                uid,
                f"✅ <b>{prod['name']}</b> (<code>{sku}</code>) o'chirildi!\n\n"
                f"📺 Telegram: {'✅ O\\'chirildi' if tg_ok else '⚠️ Xato'}\n"
                f"📸 Instagram: {'✅ O\\'chirildi' if ig_ok else '⚠️ Xato'}",
                reply_markup=admin_kb()
            )
            return

        # Broadcast
        if state == 'waiting_broadcast':
            conn = get_db()
            users = conn.execute(
                "SELECT telegram_id FROM users WHERE phone IS NOT NULL"
            ).fetchall()
            conn.close()

            if not users:
                bot.send_message(uid, "❌ Hozircha ro'yxatdan o'tgan mijozlar yo'q.")
                admin_states.pop(uid, None)
                return

            wait = bot.send_message(uid, f"📢 {len(users)} ta foydalanuvchiga yuborilmoqda…")
            sent = failed = 0

            for row in users:
                try:
                    if msg.content_type == 'text':
                        bot.send_message(row['telegram_id'], msg.text)
                    elif msg.content_type == 'photo':
                        bot.send_photo(
                            row['telegram_id'],
                            msg.photo[-1].file_id,
                            caption=msg.caption or ""
                        )
                    elif msg.content_type == 'document':
                        bot.send_document(
                            row['telegram_id'],
                            msg.document.file_id,
                            caption=msg.caption or ""
                        )
                    sent += 1
                except Exception as e:
                    logger.warning("Broadcast skip %s: %s", row['telegram_id'], e)
                    failed += 1
                time.sleep(0.05)   # ~20 msg/s, xavfsiz

            admin_states.pop(uid, None)
            try:
                bot.delete_message(uid, wait.message_id)
            except Exception:
                pass
            bot.send_message(
                uid,
                f"📢 <b>Xabar yuborildi!</b>\n\n"
                f"✅ Muvaffaqiyatli: <b>{sent}</b>\n"
                f"❌ Xato/blok: <b>{failed}</b>",
                reply_markup=admin_kb()
            )
            return

    # ── FOYDALANUVCHI holati ────────────────────────────────
    user  = get_user(uid)
    state = user['state'] if user else None

    if state is None or not user:
        save_user(uid, state='waiting_name')
        bot.send_message(uid, "📝 <b>Ismingizni yuboring:</b>", reply_markup=ReplyKeyboardRemove())
        return

    if state == 'waiting_name':
        if msg.content_type != 'text':
            return
        name = msg.text.strip()
        if len(name) < 2:
            bot.send_message(uid, "❌ Ism kamida 2 harf bo'lishi kerak.")
            return
        save_user(uid, full_name=name, state='waiting_phone')
        bot.send_message(
            uid,
            f"👋 Salom, <b>{name}</b>!\n\n"
            f"📞 Telefon raqamingizni ulashing:",
            reply_markup=phone_kb()
        )
        return

    if state == 'waiting_phone':
        if msg.content_type == 'contact':
            phone = msg.contact.phone_number
            if not phone.startswith('+'):
                phone = '+' + phone
            save_user(uid, phone=phone, state='idle')
            bot.send_message(uid, "✅ <b>Ro'yxatdan o'tdingiz!</b>",
                             reply_markup=ReplyKeyboardRemove())
            time.sleep(0.3)
            bot.send_message(
                uid,
                "🛍 <b>ELEGANTO Premium Boutique</b>\n\n"
                "Eksklyuziv kolleksiyamizni ko'ring:",
                reply_markup=main_menu_kb()
            )
        elif msg.content_type == 'text':
            ph = msg.text.strip().replace(' ', '')
            if ph.startswith('+') or ph.isdigit():
                if not ph.startswith('+'):
                    ph = '+' + ph
                save_user(uid, phone=ph, state='idle')
                bot.send_message(uid, "✅ <b>Ro'yxatdan o'tdingiz!</b>",
                                 reply_markup=ReplyKeyboardRemove())
                time.sleep(0.3)
                bot.send_message(uid,
                    "🛍 <b>ELEGANTO Premium Boutique</b>",
                    reply_markup=main_menu_kb()
                )
            else:
                bot.send_message(uid, "❌ Tugma orqali yuboring:", reply_markup=phone_kb())
        return

    if state == 'idle':
        bot.send_message(uid, "🛍 Do'konimizga xush kelibsiz!", reply_markup=main_menu_kb())


# ============================================================
# FLASK API
# ============================================================
@app.route('/api/products', methods=['GET'])
def api_products():
    category = freq.args.get('category', '').strip()
    search   = freq.args.get('search', '').strip()
    sort     = freq.args.get('sort', 'newest')
    page     = max(1, int(freq.args.get('page', 1)))
    limit    = min(40, max(1, int(freq.args.get('limit', 20))))
    offset   = (page - 1) * limit

    conn   = get_db()
    where  = ["1=1"]
    params = []

    if category:
        where.append("category LIKE ?")
        params.append(f"%{category}%")

    if search:
        where.append("(name LIKE ? OR sku LIKE ? OR category LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    base_q = f"SELECT * FROM products WHERE {' AND '.join(where)}"

    order_map = {
        'price_asc':  'price ASC',
        'price_desc': 'price DESC',
        'newest':     'created_at DESC',
        'oldest':     'created_at ASC',
    }
    base_q += f" ORDER BY {order_map.get(sort, 'created_at DESC')}"

    total = conn.execute(
        f"SELECT COUNT(*) FROM products WHERE {' AND '.join(where)}", params
    ).fetchone()[0]

    rows = conn.execute(base_q + " LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    conn.close()

    result = []
    for r in rows:
        imgs = json.loads(r['images']) if r['images'] else []
        urls = []
        for fid in imgs:
            try:
                urls.append(get_tg_file_url(fid))
            except Exception:
                pass
        result.append({
            'id':          r['id'],
            'sku':         r['sku'],
            'name':        r['name'],
            'category':    r['category'],
            'subcategory': r['subcategory'] or '',
            'price':       r['price'],
            'images':      urls,
            'created_at':  r['created_at'],
        })

    return jsonify({
        'products': result,
        'total':    total,
        'page':     page,
        'pages':    max(1, (total + limit - 1) // limit),
    })


@app.route('/api/categories', methods=['GET'])
def api_categories():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT category, subcategory FROM products ORDER BY category"
    ).fetchall()
    conn.close()

    cats: dict = {}
    for r in rows:
        c = r['category'] or ''
        s = r['subcategory'] or ''
        if c not in cats:
            cats[c] = set()
        if s:
            cats[c].add(s)

    return jsonify([
        {'name': k, 'subcategories': sorted(v)}
        for k, v in sorted(cats.items())
    ])


@app.route('/api/order', methods=['POST'])
def api_order():
    try:
        data  = freq.get_json(force=True) or {}
        uid   = data.get('telegram_id')
        items = data.get('items', [])
        total = data.get('total', 0)

        if not uid or not items:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        user = get_user(uid)
        conn = get_db()
        oids = []
        for item in items:
            conn.execute(
                '''INSERT INTO orders
                   (user_telegram_id, product_sku, size, color, quantity)
                   VALUES (?,?,?,?,?)''',
                (uid,
                 item.get('sku', '-'),
                 item.get('size', '-'),
                 item.get('color', '-'),
                 item.get('qty', 1))
            )
            oids.append(conn.lastrowid)
        conn.commit()
        conn.close()

        items_txt = ""
        for it in items:
            items_txt += (
                f"  • {it.get('name', '-')} (<code>{it.get('sku', '-')}</code>)\n"
                f"    📏 {it.get('size', '-')} | "
                f"🎨 {it.get('color', '-')} | "
                f"x{it.get('qty', 1)}\n"
                f"    💰 {fmt_price(it.get('price', 0))}\n\n"
            )

        ckb = InlineKeyboardMarkup(row_width=2)
        if oids:
            ckb.add(
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_order_{oids[0]}"),
                InlineKeyboardButton("❌ Bekor",      callback_data=f"cancel_order_{oids[0]}")
            )

        bot.send_message(
            ADMIN_ID,
            f"🛒 <b>YANGI BUYURTMA!</b> (Mini App)\n\n"
            f"👤 Ism: <b>{user['full_name'] if user else 'Noma\\'lum'}</b>\n"
            f"📞 Tel: <b>{user['phone'] if user else '-'}</b>\n"
            f"🆔 Telegram: <code>{uid}</code>\n\n"
            f"📦 <b>Buyurtma:</b>\n{items_txt}"
            f"💰 <b>Jami: {fmt_price(total)}</b>",
            reply_markup=ckb
        )

        return jsonify({'success': True, 'order_ids': oids})

    except Exception as e:
        logger.error("API /order error: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/wishlist', methods=['GET', 'POST', 'DELETE'])
def api_wishlist():
    if freq.method == 'GET':
        uid = freq.args.get('telegram_id', type=int)
        if not uid:
            return jsonify([])
        conn = get_db()
        rows = conn.execute(
            "SELECT product_sku FROM wishlist WHERE user_telegram_id=?", (uid,)
        ).fetchall()
        conn.close()
        return jsonify([r['product_sku'] for r in rows])

    data = freq.get_json(force=True) or {}
    uid  = data.get('telegram_id')
    sku  = data.get('sku')

    if not uid or not sku:
        return jsonify({'success': False}), 400

    conn = get_db()
    if freq.method == 'POST':
        conn.execute("INSERT OR IGNORE INTO wishlist VALUES (?,?)", (uid, sku))
    else:
        conn.execute("DELETE FROM wishlist WHERE user_telegram_id=? AND product_sku=?", (uid, sku))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/')
def serve_index():
    idx = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
    return send_file(idx)


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'eleganto-bot'})


# ============================================================
# FLASK RUN
# ============================================================
def run_flask():
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    logger.info("🚀 ELEGANTO Bot ishga tushmoqda…")

    init_db()

    # Bot buyruqlari
    try:
        bot.set_my_commands([
            BotCommand('/start', '🏠 Botni boshlash'),
            BotCommand('/menu',  '🛍 Asosiy menyu'),
            BotCommand('/add',   '📦 Mahsulot qo\'shish (Admin)'),
            BotCommand('/admin', '🎛 Admin panel'),
        ])
    except Exception as e:
        logger.warning("set_my_commands: %s", e)

    # Flask thread
    t = threading.Thread(target=run_flask, daemon=True, name="Flask")
    t.start()
    logger.info("✅ Flask API — port %s", FLASK_PORT)

    # Admin'ga xabar
    try:
        bot.send_message(
            ADMIN_ID,
            f"🟢 <b>ELEGANTO Bot ishga tushdi!</b>\n\n"
            f"🌐 Flask API: http://178.104.244.244:{FLASK_PORT}\n"
            f"📱 Mini App: {MINI_APP_URL}\n\n"
            f"⚠️ <b>Muhim:</b> Cloudflare Tunnel'ni ham ishga tushiring:\n"
            f"<code>cloudflared tunnel --url http://localhost:{FLASK_PORT}</code>\n"
            f"Keyin SERVER_URL va index.html dagi API_BASE ni yangilang."
        )
    except Exception:
        pass

    logger.info("✅ Bot polling boshlandi…")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
