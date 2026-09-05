# ByteTunnelBot
# Full version:
# - Forced Join @ByteTunnel
# - Top 100 pagination (10 per page)
# - All configs download
# - Countries
# - Protocols
# - MTProto Proxy manager
# - Proxy TCP testing
# - Admin panel
# - Statistics
# - Broadcast
# - Database export
# - Auto update
# - Clean Telegram UI

import asyncio
import html
import io
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

CHANNEL = "@ByteTunnel"

BASE_RAW = (
    "https://raw.githubusercontent.com/"
    "0xRadikal/Free-v2ray-Configs/main"
)

VERIFIED_URL = f"{BASE_RAW}/verified/configs.txt"
ALL_URL = f"{BASE_RAW}/all/configs.txt"
TOP100_URL = f"{BASE_RAW}/top100.txt"

DB_FILE = "byte_tunnel.db"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

log = logging.getLogger("ByteTunnelBot")

client: httpx.AsyncClient | None = None

verified_configs: list[str] = []
all_configs: list[str] = []
top100_configs: list[str] = []

last_update = None
update_lock = asyncio.Lock()


# ============================================================
# DATABASE
# ============================================================

# ================= COUNTRY LIST =================

COUNTRIES = [
    "Iran",
    "The_Netherlands",
    "Germany",
    "France",
    "United_States",
    "United_Kingdom",
    "Canada",
    "Turkey",
    "Russia",
    "Finland",
    "Sweden",
    "Singapore",
    "Japan",
    "Australia",
]

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            joined_at TEXT,
            last_seen TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mtproto_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server TEXT NOT NULL,
            port INTEGER NOT NULL,
            secret TEXT NOT NULL,
            country TEXT DEFAULT 'Unknown',
            enabled INTEGER DEFAULT 1,
            latency INTEGER DEFAULT 0,
            added_at TEXT
        )
    """)

    con.commit()
    con.close()


def set_setting(key: str, value: str):
    con = db()
    con.execute(
        """
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    con.commit()
    con.close()


def get_setting(key: str, default: str):
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ).fetchone()
    con.close()

    return row[0] if row else default


def register_user(user):
    now = datetime.now(timezone.utc).isoformat()

    con = db()

    con.execute(
        """
        INSERT INTO users(
            user_id,
            first_name,
            username,
            joined_at,
            last_seen
        )
        VALUES(?,?,?,?,?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            username=excluded.username,
            last_seen=excluded.last_seen
        """,
        (
            user.id,
            user.first_name or "",
            user.username or "",
            now,
            now,
        ),
    )

    con.commit()
    con.close()


def user_count():
    con = db()
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    return n


def proxy_count():
    con = db()
    n = con.execute(
        "SELECT COUNT(*) FROM mtproto_proxies"
    ).fetchone()[0]
    con.close()
    return n


# ============================================================
# HTTP
# ============================================================

async def fetch_text(url: str):
    global client

    if client is None:
        client = httpx.AsyncClient(
            timeout=25,
            follow_redirects=True,
        )

    try:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.error("Fetch failed %s: %s", url, e)
        return None


def parse_configs(text: str | None):
    if not text:
        return []

    result = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if "://" not in line:
            continue

        result.append(line)

    return result


async def update_configs():
    global verified_configs
    global all_configs
    global top100_configs
    global last_update

    async with update_lock:
        log.info("[UPDATE] Downloading configs...")

        verified_text, all_text, top100_text = await asyncio.gather(
            fetch_text(VERIFIED_URL),
            fetch_text(ALL_URL),
            fetch_text(TOP100_URL),
        )

        new_verified = parse_configs(verified_text)
        new_all = parse_configs(all_text)
        new_top100 = parse_configs(top100_text)

        if new_verified:
            verified_configs = new_verified

        if new_all:
            all_configs = new_all

        if new_top100:
            top100_configs = new_top100[:100]

        last_update = datetime.now(timezone.utc)

        log.info(
            "[UPDATE] verified=%d all=%d top100=%d",
            len(verified_configs),
            len(all_configs),
            len(top100_configs),
        )


async def auto_update(application):
    while True:
        try:
            minutes = int(
                get_setting("update_interval", "15")
            )

            await asyncio.sleep(max(60, minutes * 60))

            await update_configs()

        except asyncio.CancelledError:
            break

        except Exception as e:
            log.exception("Auto update error: %s", e)
            await asyncio.sleep(60)


# ============================================================
# FORCED JOIN
# ============================================================

async def is_joined(bot, user_id: int):
    try:
        member = await bot.get_chat_member(
            CHANNEL,
            user_id,
        )

        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }

    except Exception as e:
        log.warning("Join check failed: %s", e)

        # If Telegram doesn't allow checking, don't lock everyone out.
        return True


def join_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 عضویت در کانال",
                url="https://t.me/ByteTunnel",
            )
        ],
        [
            InlineKeyboardButton(
                "✅ بررسی عضویت",
                callback_data="check_join",
            )
        ],
    ])


async def require_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user:
        return False

    if user.id in ADMIN_IDS:
        return True

    if await is_joined(context.bot, user.id):
        return True

    text = (
        "🔒 <b>دسترسی محدود است</b>\n\n"
        "برای استفاده از ByteTunnel ابتدا عضو کانال شوید.\n\n"
        "بعد از عضویت روی «بررسی عضویت» بزنید."
    )

    if update.callback_query:
        await update.callback_query.answer()

        try:
            await update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=join_keyboard(),
            )
        except Exception:
            pass

    elif update.message:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(),
        )

    return False


# ============================================================
# MENUS
# ============================================================

def user_menu():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("⚡ دریافت کانفیگ"),
                KeyboardButton("📦 دریافت همه"),
            ],
            [
                KeyboardButton("🌐 Proxy"),
                KeyboardButton("🏆 بهترین 100"),
            ],
            [
                KeyboardButton("🌍 کشورها"),
                KeyboardButton("🔌 پروتکل‌ها"),
            ],
            [
                KeyboardButton("📊 آمار"),
            ],
        ],
        resize_keyboard=True,
    )


def admin_menu():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("📊 آمار سیستم"),
                KeyboardButton("🔄 آپدیت دستی"),
            ],
            [
                KeyboardButton("📦 دریافت دیتابیس"),
                KeyboardButton("🏆 Top 100"),
            ],
            [
                KeyboardButton("🌍 مدیریت کشورها"),
                KeyboardButton("🔌 مدیریت پروتکل‌ها"),
            ],
            [
                KeyboardButton("🌐 مدیریت Proxy"),
                KeyboardButton("⚙️ تنظیمات"),
            ],
            [
                KeyboardButton("📢 ارسال همگانی"),
            ],
            [
                KeyboardButton("🏠 منوی کاربر"),
            ],
        ],
        resize_keyboard=True,
    )


# ============================================================
# CONFIG HELPERS
# ============================================================

def protocol_of(config: str):
    x = config.lower()

    if x.startswith("vless://"):
        return "VLESS"
    if x.startswith("vmess://"):
        return "VMess"
    if x.startswith("trojan://"):
        return "Trojan"
    if x.startswith("ss://"):
        return "Shadowsocks"
    if x.startswith("hysteria2://"):
        return "Hysteria2"
    if x.startswith("hy2://"):
        return "Hysteria2"
    if x.startswith("tuic://"):
        return "TUIC"

    return "Unknown"


def country_of(config: str):
    """
    Extract only the country flag from the config fragment.
    Examples:
      #US 🇺🇸 | @Raydikalx | 4A3857 -> 🇺🇸
      #NL 🇳🇱 | @something | ABC123 -> 🇳🇱
    """

    if "#" not in config:
        return "🌐"

    fragment = config.rsplit("#", 1)[1].strip()

    # Country flag is represented by two regional indicator symbols.
    flags = re.findall(
        r"[\U0001F1E6-\U0001F1FF]{2}",
        fragment
    )

    if flags:
        return flags[0]

    return "🌐"


def clean_config(config: str):
    config = config.strip()

    if "#" not in config:
        return config

    base, fragment = config.rsplit("#", 1)

    flags = re.findall(
        r"[\U0001F1E6-\U0001F1FF]{2}",
        fragment
    )

    if flags:
        return base + "#" + flags[0]

    return base


def config_card(number: int, config: str):
    config = clean_config(config)
    return f"#{number}\n{config}"


def top_page_keyboard(page: int):
    total_pages = max(
        1,
        (len(top100_configs) + 9) // 10,
    )

    buttons = []

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=f"top:{page-1}",
            )
        )

    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "➡️ صفحه بعد",
                callback_data=f"top:{page+1}",
            )
        )

    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    return InlineKeyboardMarkup(buttons)


async def send_top_page(update: Update, context, page=0):
    if not top100_configs:
        msg = "⏳ هنوز لیست کانفیگ‌ها آماده نشده."

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(msg)
        else:
            await update.effective_message.reply_text(msg)

        return

    total_pages = max(1, (len(top100_configs) + 9) // 10)
    page = max(0, min(page, total_pages - 1))

    start_index = page * 10
    items = top100_configs[start_index:start_index + 10]

    lines = [
        "⚡ <b>ByteTunnel</b>",
        "",
        f"🟢 موجود: <b>{len(verified_configs)}</b>",
        f"📦 ارسال: <b>{len(items)}</b>",
        "",
    ]

    for i, config in enumerate(items, start=start_index + 1):
        lines.append(config_card(i, config))
        lines.append("")

    lines.append(f"📄 صفحه {page + 1}/{total_pages}")

    text = "\n".join(lines)
    markup = top_page_keyboard(page)

    if update.callback_query:
        await update.callback_query.answer()

        try:
            await update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception:
            pass
    else:
        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )


async def country_menu(update, context):
    buttons = []

    for country in COUNTRIES:
        label = country.replace("_", " ")

        buttons.append([
            InlineKeyboardButton(
                f"🌍 {label}",
                callback_data=f"country:{country}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await update.effective_message.reply_text(
        "🌍 <b>کشورها</b>\n\n"
        "کشور موردنظر را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def send_country(update, context, country):
    url = f"{BASE_RAW}/Countries/{country}.txt"

    text = await fetch_text(url)
    configs = parse_configs(text)

    if not configs:
        await update.callback_query.edit_message_text(
            "❌ کانفیگی برای این کشور پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="countries",
                    )
                ]
            ]),
        )
        return

    amount = int(
        get_setting("amount", "10")
    )

    configs = configs[:amount]

    body = [
        f"🌍 <b>{html.escape(country.replace('_', ' '))}</b>",
        f"📦 تعداد: <b>{len(configs)}</b>",
        "",
    ]

    for i, config in enumerate(configs, 1):
        body.append(
            config_card(i, config)
        )
        body.append("")

    await update.callback_query.edit_message_text(
        "\n".join(body),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 کشورها",
                    callback_data="countries",
                ),
                InlineKeyboardButton(
                    "🏠 خانه",
                    callback_data="home",
                ),
            ]
        ]),
    )


# ============================================================
# PROTOCOLS
# ============================================================

PROTOCOLS = [
    "vless",
    "vmess",
    "trojan",
    "shadowsocks",
    "hysteria2",
    "tuic",
]


async def protocol_menu(update, context):
    buttons = []

    for proto in PROTOCOLS:
        buttons.append([
            InlineKeyboardButton(
                f"🔌 {proto.upper()}",
                callback_data=f"protocol:{proto}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home",
        )
    ])

    await update.effective_message.reply_text(
        "🔌 <b>پروتکل‌ها</b>\n\n"
        "پروتکل موردنظر را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def send_protocol(update, context, protocol):
    url = f"{BASE_RAW}/protocols/{protocol}.txt"

    text = await fetch_text(url)
    configs = parse_configs(text)

    if not configs:
        await update.callback_query.edit_message_text(
            "❌ کانفیگی برای این پروتکل پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 برگشت",
                        callback_data="protocols",
                    )
                ]
            ]),
        )
        return

    amount = int(
        get_setting("amount", "10")
    )

    configs = configs[:amount]

    body = [
        f"🔌 <b>{protocol.upper()}</b>",
        f"📦 تعداد: <b>{len(configs)}</b>",
        "",
    ]

    for i, config in enumerate(configs, 1):
        body.append(
            config_card(i, config)
        )
        body.append("")

    await update.callback_query.edit_message_text(
        "\n".join(body),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پروتکل‌ها",
                    callback_data="protocols",
                ),
                InlineKeyboardButton(
                    "🏠 خانه",
                    callback_data="home",
                ),
            ]
        ]),
    )


# ============================================================
# MTPROTO PROXY
# ============================================================

def proxy_link(server, port, secret):
    return (
        "tg://proxy?"
        f"server={quote(str(server), safe='')}"
        f"&port={int(port)}"
        f"&secret={quote(str(secret), safe='')}"
    )


def get_proxies(enabled_only=True):
    con = db()

    if enabled_only:
        rows = con.execute(
            """
            SELECT id,server,port,secret,country,
                   enabled,latency
            FROM mtproto_proxies
            WHERE enabled=1
            ORDER BY id DESC
            """
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT id,server,port,secret,country,
                   enabled,latency
            FROM mtproto_proxies
            ORDER BY id DESC
            """
        ).fetchall()

    con.close()
    return rows


async def user_proxy_menu(update, context):
    proxies = get_proxies(True)

    if not proxies:
        await update.effective_message.reply_text(
            "🌐 <b>Proxy</b>\n\n"
            "فعلاً Proxy فعالی ثبت نشده.",
            parse_mode=ParseMode.HTML,
        )
        return

    for pid, server, port, secret, country, enabled, latency in proxies:
        status = (
            f"🟢 فعال • {latency}ms"
            if latency
            else "🟢 فعال"
        )

        text = (
            f"🌐 <b>Proxy #{pid}</b>\n\n"
            f"🌍 <b>کشور:</b> {html.escape(country)}\n"
            f"⚡ <b>نوع:</b> MTProto\n"
            f"📡 <b>سرور:</b> <code>{html.escape(server)}</code>\n"
            f"🔌 <b>پورت:</b> <code>{port}</code>\n"
            f"{status}"
        )

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔗 اتصال به Proxy",
                    url=proxy_link(
                        server,
                        port,
                        secret,
                    ),
                )
            ]
        ])

        await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )


# ============================================================
# ADMIN PROXY
# ============================================================

def admin_proxy_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ افزودن Proxy",
                callback_data="ap:add",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 لیست Proxyها",
                callback_data="ap:list",
            )
        ],
        [
            InlineKeyboardButton(
                "🧪 تست Proxyها",
                callback_data="ap:test",
            )
        ],
        [
            InlineKeyboardButton(
                "🟢/🔴 فعال/غیرفعال",
                callback_data="ap:toggle",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 حذف Proxy",
                callback_data="ap:delete",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی ادمین",
                callback_data="admin_home",
            )
        ],
    ])


async def admin_proxy(update, context):
    await update.effective_message.reply_text(
        "🌐 <b>مدیریت MTProto Proxy</b>\n\n"
        "از گزینه‌های زیر استفاده کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_proxy_menu(),
    )


async def proxy_add_start(update, context):
    context.user_data["proxy_add"] = {}

    await update.callback_query.edit_message_text(
        "➕ <b>افزودن MTProto Proxy</b>\n\n"
        "1️⃣ IP یا Host را ارسال کنید:",
        parse_mode=ParseMode.HTML,
    )

    context.user_data["proxy_add_step"] = "server"


async def proxy_add_message(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return

    step = context.user_data.get("proxy_add_step")

    if not step:
        return

    data = context.user_data.setdefault(
        "proxy_add",
        {},
    )

    value = update.message.text.strip()

    if step == "server":
        data["server"] = value
        context.user_data["proxy_add_step"] = "port"

        await update.message.reply_text(
            "2️⃣ پورت را ارسال کنید:\n\n"
            "مثلاً: <code>443</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if step == "port":
        if not value.isdigit():
            await update.message.reply_text(
                "❌ پورت باید عدد باشد."
            )
            return

        port = int(value)

        if not 1 <= port <= 65535:
            await update.message.reply_text(
                "❌ پورت باید بین 1 تا 65535 باشد."
            )
            return

        data["port"] = port
        context.user_data["proxy_add_step"] = "secret"

        await update.message.reply_text(
            "3️⃣ Secret را ارسال کنید:"
        )
        return

    if step == "secret":
        data["secret"] = value
        context.user_data["proxy_add_step"] = "country"

        await update.message.reply_text(
            "4️⃣ کشور Proxy را ارسال کنید:\n\n"
            "مثلاً: <code>Netherlands 🇳🇱</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if step == "country":
        data["country"] = value

        con = db()

        con.execute(
            """
            INSERT INTO mtproto_proxies(
                server,
                port,
                secret,
                country,
                enabled,
                latency,
                added_at
            )
            VALUES(?,?,?,?,1,0,?)
            """,
            (
                data["server"],
                data["port"],
                data["secret"],
                data["country"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        con.commit()
        con.close()

        context.user_data.pop("proxy_add", None)
        context.user_data.pop("proxy_add_step", None)

        await update.message.reply_text(
            "✅ <b>Proxy با موفقیت اضافه شد.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu(),
        )


async def proxy_list(update, context):
    rows = get_proxies(False)

    if not rows:
        await update.callback_query.edit_message_text(
            "📋 هیچ Proxyای ثبت نشده.",
            reply_markup=admin_proxy_menu(),
        )
        return

    body = ["📋 <b>لیست Proxyها</b>", ""]

    for pid, server, port, secret, country, enabled, latency in rows:
        status = "🟢 فعال" if enabled else "🔴 غیرفعال"

        body.append(
            f"<b>#{pid}</b> • "
            f"{status}\n"
            f"🌍 {html.escape(country)}\n"
            f"📡 <code>{html.escape(server)}:{port}</code>\n"
            f"📶 {latency}ms\n"
        )

    await update.callback_query.edit_message_text(
        "\n".join(body),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_proxy_menu(),
    )


async def test_single_proxy(pid, server, port):
    start = time.perf_counter()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port),
            timeout=7,
        )

        writer.close()

        try:
            await writer.wait_closed()
        except Exception:
            pass

        latency = int(
            (time.perf_counter() - start) * 1000
        )

        return latency

    except Exception:
        return -1


async def proxy_test(update, context):
    rows = get_proxies(False)

    if not rows:
        await update.callback_query.edit_message_text(
            "🧪 Proxyای برای تست وجود ندارد.",
            reply_markup=admin_proxy_menu(),
        )
        return

    await update.callback_query.edit_message_text(
        "🧪 در حال تست TCP Proxyها..."
    )

    results = []

    for pid, server, port, secret, country, enabled, latency in rows:
        new_latency = await test_single_proxy(
            pid,
            server,
            port,
        )

        con = db()

        if new_latency >= 0:
            con.execute(
                """
                UPDATE mtproto_proxies
                SET latency=?
                WHERE id=?
                """,
                (new_latency, pid),
            )
        else:
            con.execute(
                """
                UPDATE mtproto_proxies
                SET latency=0
                WHERE id=?
                """,
                (pid,),
            )

        con.commit()
        con.close()

        if new_latency >= 0:
            results.append(
                f"🟢 #{pid} • {new_latency}ms • "
                f"{html.escape(country)}"
            )
        else:
            results.append(
                f"🔴 #{pid} • اتصال TCP ناموفق • "
                f"{html.escape(country)}"
            )

    await update.callback_query.edit_message_text(
        "🧪 <b>نتیجه تست Proxyها</b>\n\n"
        + "\n".join(results)
        + "\n\n"
        "⚠️ این تست فقط دسترسی TCP به IP:Port را بررسی می‌کند؛ "
        "اعتبار کامل MTProto Secret را تأیید نمی‌کند.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_proxy_menu(),
    )


async def proxy_toggle_menu(update, context):
    rows = get_proxies(False)

    if not rows:
        await update.callback_query.edit_message_text(
            "هیچ Proxyای وجود ندارد.",
            reply_markup=admin_proxy_menu(),
        )
        return

    buttons = []

    for pid, server, port, secret, country, enabled, latency in rows:
        status = "🟢" if enabled else "🔴"

        buttons.append([
            InlineKeyboardButton(
                f"{status} #{pid} {country}",
                callback_data=f"toggle:{pid}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="ap:menu",
        )
    ])

    await update.callback_query.edit_message_text(
        "🟢🔴 <b>فعال/غیرفعال کردن Proxy</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def proxy_toggle(update, context, pid):
    con = db()

    row = con.execute(
        "SELECT enabled FROM mtproto_proxies WHERE id=?",
        (pid,),
    ).fetchone()

    if row:
        new_status = 0 if row[0] else 1

        con.execute(
            """
            UPDATE mtproto_proxies
            SET enabled=?
            WHERE id=?
            """,
            (new_status, pid),
        )

        con.commit()

    con.close()

    await proxy_toggle_menu(
        update,
        context,
    )


async def proxy_delete_menu(update, context):
    rows = get_proxies(False)

    if not rows:
        await update.callback_query.edit_message_text(
            "هیچ Proxyای وجود ندارد.",
            reply_markup=admin_proxy_menu(),
        )
        return

    buttons = []

    for pid, server, port, secret, country, enabled, latency in rows:
        buttons.append([
            InlineKeyboardButton(
                f"🗑 #{pid} {country}",
                callback_data=f"delete:{pid}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="ap:menu",
        )
    ])

    await update.callback_query.edit_message_text(
        "🗑 <b>حذف Proxy</b>\n\n"
        "Proxy موردنظر را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def proxy_delete(update, context, pid):
    con = db()

    con.execute(
        "DELETE FROM mtproto_proxies WHERE id=?",
        (pid,),
    )

    con.commit()
    con.close()

    await proxy_delete_menu(
        update,
        context,
    )


# ============================================================
# GENERAL USER HANDLERS
# ============================================================

async def start(update, context):
    register_user(update.effective_user)

    if not await require_join(update, context):
        return

    await update.message.reply_text(
        "⚡ <b>ByteTunnel</b>\n\n"
        "به ربات کانفیگ خوش اومدی ❤️\n\n"
        "از منوی زیر انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=user_menu(),
    )


async def stats(update, context):
    if not await require_join(update, context):
        return

    last = (
        last_update.strftime("%Y-%m-%d %H:%M UTC")
        if last_update
        else "نامشخص"
    )

    await update.message.reply_text(
        "📊 <b>آمار ByteTunnel</b>\n\n"
        f"👤 کاربران: <b>{user_count()}</b>\n"
        f"⚡ کانفیگ Verified: <b>{len(verified_configs)}</b>\n"
        f"📦 کل کانفیگ‌ها: <b>{len(all_configs)}</b>\n"
        f"🏆 Top 100: <b>{len(top100_configs)}</b>\n"
        f"🌐 Proxy فعال: <b>{len(get_proxies(True))}</b>\n"
        f"🔄 آخرین آپدیت: <code>{last}</code>",
        parse_mode=ParseMode.HTML,
    )


async def send_all(update, context):
    if not await require_join(update, context):
        return

    if not all_configs:
        await update.message.reply_text(
            "⏳ لیست کانفیگ‌ها آماده نیست."
        )
        return

    text = "\n".join(clean_config(x) for x in all_configs)

    data = io.BytesIO(
        text.encode("utf-8")
    )

    data.name = "ByteTunnel_all_configs.txt"

    await update.message.reply_document(
        document=data,
        caption=(
            "📦 <b>همه کانفیگ‌ها</b>\n\n"
            f"تعداد: <b>{len(all_configs)}</b>"
        ),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADMIN
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت ByteTunnel</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


async def admin_stats(update, context):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "📊 <b>آمار سیستم</b>\n\n"
        f"👤 کاربران: <b>{user_count()}</b>\n"
        f"⚡ Verified: <b>{len(verified_configs)}</b>\n"
        f"📦 All: <b>{len(all_configs)}</b>\n"
        f"🏆 Top100: <b>{len(top100_configs)}</b>\n"
        f"🌐 Proxy: <b>{proxy_count()}</b>",
        parse_mode=ParseMode.HTML,
    )


async def admin_update(update, context):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "🔄 در حال آپدیت..."
    )

    await update_configs()

    await update.message.reply_text(
        "✅ آپدیت انجام شد.\n\n"
        f"Verified: {len(verified_configs)}\n"
        f"All: {len(all_configs)}\n"
        f"Top100: {len(top100_configs)}"
    )


async def admin_db(update, context):
    if not is_admin(update.effective_user.id):
        return

    with open(DB_FILE, "rb") as f:
        data = io.BytesIO(f.read())

    data.name = "byte_tunnel.db"

    await update.message.reply_document(
        document=data,
        caption="📦 دیتابیس ByteTunnel"
    )


async def admin_top100(update, context):
    if not is_admin(update.effective_user.id):
        return

    await send_top_page(update, context, 0)


async def admin_settings(update, context):
    if not is_admin(update.effective_user.id):
        return

    interval = get_setting(
        "update_interval",
        "15",
    )

    amount = get_setting(
        "amount",
        "10",
    )

    await update.message.reply_text(
        "⚙️ <b>تنظیمات</b>\n\n"
        f"🔄 فاصله آپدیت: <b>{interval} دقیقه</b>\n"
        f"📦 تعداد نمایش: <b>{amount}</b>\n\n"
        "برای تغییر:\n"
        "<code>/setinterval 15</code>\n"
        "<code>/setamount 10</code>",
        parse_mode=ParseMode.HTML,
    )


async def set_interval(update, context):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "مثال:\n/setinterval 15"
        )
        return

    value = int(context.args[0])

    if value < 1:
        await update.message.reply_text(
            "❌ حداقل 1 دقیقه."
        )
        return

    set_setting(
        "update_interval",
        str(value),
    )

    await update.message.reply_text(
        f"✅ فاصله آپدیت روی {value} دقیقه تنظیم شد."
    )


async def set_amount(update, context):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "مثال:\n/setamount 10"
        )
        return

    value = int(context.args[0])

    if not 1 <= value <= 100:
        await update.message.reply_text(
            "❌ عدد باید بین 1 تا 100 باشد."
        )
        return

    set_setting(
        "amount",
        str(value),
    )

    await update.message.reply_text(
        f"✅ تعداد روی {value} تنظیم شد."
    )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["broadcast"] = True

    await update.message.reply_text(
        "📢 متن پیام همگانی را ارسال کنید.\n\n"
        "برای لغو: /cancel"
    )


async def broadcast_message(update, context):
    if not is_admin(update.effective_user.id):
        return

    if not context.user_data.get("broadcast"):
        return

    context.user_data.pop("broadcast", None)

    con = db()

    users = [
        x[0]
        for x in con.execute(
            "SELECT user_id FROM users"
        ).fetchall()
    ]

    con.close()

    ok = 0
    fail = 0

    await update.message.reply_text(
        f"📢 شروع ارسال به {len(users)} کاربر..."
    )

    for uid in users:
        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )

            ok += 1

        except Exception:
            fail += 1

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"✅ ارسال تمام شد.\n\n"
        f"🟢 موفق: {ok}\n"
        f"🔴 ناموفق: {fail}"
    )


async def cancel(update, context):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=admin_menu()
        if is_admin(update.effective_user.id)
        else user_menu(),
    )


# ============================================================
# CALLBACKS
# ============================================================

async def callbacks(update, context):
    q = update.callback_query

    data = q.data

    if data == "check_join":
        if await is_joined(
            context.bot,
            q.from_user.id,
        ):
            await q.answer(
                "✅ عضویت تأیید شد!",
                show_alert=True,
            )

            await q.message.reply_text(
                "✅ دسترسی فعال شد.",
                reply_markup=user_menu(),
            )
        else:
            await q.answer(
                "❌ هنوز عضو کانال نیستید.",
                show_alert=True,
            )

        return

    if data == "home":
        if not await require_join(update, context):
            return

        await q.answer()

        await q.message.reply_text(
            "🏠 <b>منوی اصلی</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu(),
        )
        return

    if data.startswith("top:"):
        if not await require_join(update, context):
            return

        await q.answer()

        page = int(
            data.split(":")[1]
        )

        await send_top_page(
            update,
            context,
            page,
        )

        return

    if data == "countries":
        if not await require_join(update, context):
            return

        await q.answer()

        buttons = []

        for country in COUNTRIES:
            buttons.append([
                InlineKeyboardButton(
                    f"🌍 {country.replace('_', ' ')}",
                    callback_data=f"country:{country}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🏠 خانه",
                callback_data="home",
            )
        ])

        await q.edit_message_text(
            "🌍 <b>کشورها</b>\n\n"
            "یک کشور را انتخاب کنید:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    if data.startswith("country:"):
        if not await require_join(update, context):
            return

        await q.answer()

        await send_country(
            update,
            context,
            data.split(":", 1)[1],
        )

        return

    if data == "protocols":
        if not await require_join(update, context):
            return

        await q.answer()

        buttons = []

        for proto in PROTOCOLS:
            buttons.append([
                InlineKeyboardButton(
                    f"🔌 {proto.upper()}",
                    callback_data=f"protocol:{proto}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🏠 خانه",
                callback_data="home",
            )
        ])

        await q.edit_message_text(
            "🔌 <b>پروتکل‌ها</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    if data.startswith("protocol:"):
        if not await require_join(update, context):
            return

        await q.answer()

        await send_protocol(
            update,
            context,
            data.split(":", 1)[1],
        )

        return

    # --------------------------------------------------------
    # USER PROXY
    # --------------------------------------------------------

    if data == "user_proxy":
        if not await require_join(update, context):
            return

        await q.answer()

        await user_proxy_menu(
            update,
            context,
        )

        return

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if not is_admin(q.from_user.id):
        await q.answer(
            "⛔ دسترسی ندارید.",
            show_alert=True,
        )
        return

    if data == "admin_home":
        await q.answer()

        await q.message.reply_text(
            "🛠 <b>پنل مدیریت</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu(),
        )

        return

    if data == "ap:menu":
        await q.answer()

        await q.edit_message_text(
            "🌐 <b>مدیریت MTProto Proxy</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_proxy_menu(),
        )

        return

    if data == "ap:add":
        await q.answer()

        await proxy_add_start(
            update,
            context,
        )

        return

    if data == "ap:list":
        await q.answer()

        await proxy_list(
            update,
            context,
        )

        return

    if data == "ap:test":
        await q.answer()

        await proxy_test(
            update,
            context,
        )

        return

    if data == "ap:toggle":
        await q.answer()

        await proxy_toggle_menu(
            update,
            context,
        )

        return

    if data == "ap:delete":
        await q.answer()

        await proxy_delete_menu(
            update,
            context,
        )

        return

    if data.startswith("toggle:"):
        await q.answer()

        pid = int(
            data.split(":")[1]
        )

        await proxy_toggle(
            update,
            context,
            pid,
        )

        return

    if data.startswith("delete:"):
        await q.answer()

        pid = int(
            data.split(":")[1]
        )

        await proxy_delete(
            update,
            context,
            pid,
        )

        return


# ============================================================
# TEXT ROUTER
# ============================================================

async def text_router(update, context):
    if not update.message:
        return

    register_user(
        update.effective_user
    )

    text = update.message.text.strip()

    # Proxy adding has priority.
    if (
        is_admin(update.effective_user.id)
        and context.user_data.get("proxy_add_step")
    ):
        await proxy_add_message(
            update,
            context,
        )
        return

    # Broadcast has priority.
    if (
        is_admin(update.effective_user.id)
        and context.user_data.get("broadcast")
    ):
        await broadcast_message(
            update,
            context,
        )
        return

    # Admin menu first.
    if is_admin(update.effective_user.id):

        if text == "📊 آمار سیستم":
            await admin_stats(update, context)
            return

        if text == "🔄 آپدیت دستی":
            await admin_update(update, context)
            return

        if text == "📦 دریافت دیتابیس":
            await admin_db(update, context)
            return

        if text == "🏆 Top 100":
            await admin_top100(update, context)
            return

        if text == "🌐 مدیریت Proxy":
            await admin_proxy(update, context)
            return

        if text == "⚙️ تنظیمات":
            await admin_settings(update, context)
            return

        if text == "📢 ارسال همگانی":
            await broadcast_start(update, context)
            return

        if text == "🏠 منوی کاربر":
            await update.message.reply_text(
                "🏠 منوی کاربر:",
                reply_markup=user_menu(),
            )
            return

    # User gate.
    if not await require_join(
        update,
        context,
    ):
        return

    if text == "⚡ دریافت کانفیگ":
        await send_top_page(
            update,
            context,
            0,
        )
        return

    if text == "📦 دریافت همه":
        await send_all(
            update,
            context,
        )
        return

    if text == "🏆 بهترین 100":
        await send_top_page(
            update,
            context,
            0,
        )
        return

    if text == "🌐 Proxy":
        await user_proxy_menu(
            update,
            context,
        )
        return

    if text == "🌍 کشورها":
        await country_menu(
            update,
            context,
        )
        return

    if text == "🔌 پروتکل‌ها":
        await protocol_menu(
            update,
            context,
        )
        return

    if text == "📊 آمار":
        await stats(
            update,
            context,
        )
        return


# ============================================================
# LIFECYCLE
# ============================================================

async def post_init(application):
    init_db()

    if not get_setting(
        "update_interval",
        "",
    ):
        set_setting(
            "update_interval",
            "15",
        )

    if not get_setting(
        "amount",
        "",
    ):
        set_setting(
            "amount",
            "10",
        )

    await update_configs()

    application.bot_data["update_task"] = asyncio.create_task(
        auto_update(application)
    )


async def post_shutdown(application):
    task = application.bot_data.get(
        "update_task"
    )

    if task:
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

    global client

    if client:
        await client.aclose()
        client = None


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN داخل .env تنظیم نشده."
        )

    log.info("ByteTunnelBot starting...")
    log.info("Admin IDs: %s", ADMIN_IDS)

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "setinterval",
            set_interval,
        )
    )

    application.add_handler(
        CommandHandler(
            "setamount",
            set_amount,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callbacks
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        )
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
