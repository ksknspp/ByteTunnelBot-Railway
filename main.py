import asyncio
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8394607974"))

CHANNEL = "@ByteTunnel"

SCRIPT = Path(__file__).with_name("bytetunnel.sh")
DB_FILE = Path(os.getenv("DB_FILE", str(Path(__file__).with_name("bytetunnel_bot.db")))

CF_SIGNUP = "https://dash.cloudflare.com/sign-up"

API_URL = (
    "https://dash.cloudflare.com/profile/api-tokens?"
    "permissionGroupKeys=%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22d1%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22workers_routes%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22zone%22%2C%22type%22%3A%22read%22%7D%2C"
    "%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%5D"
    "&accountId=*&zoneId=all&name=Apex-Bot-8394607974"
)

REFERRAL_REWARD = 3
DAILY_REWARD = 1

states = {}
build_queue = None


# ============================================================
# DATABASE
# ============================================================

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            banned INTEGER DEFAULT 0,
            referral_by INTEGER,
            referral_rewarded INTEGER DEFAULT 0,
            balance INTEGER DEFAULT 0,
            last_daily TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            worker_name TEXT NOT NULL,
            panel_url TEXT NOT NULL,
            db_id TEXT,
            account_id TEXT,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'active'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER UNIQUE NOT NULL,
            reward_given INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def ensure_user(user):
    conn = connect()

    row = conn.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if row:
        conn.execute("""
            UPDATE users
            SET username=?, first_name=?, last_seen=?
            WHERE user_id=?
        """, (
            user.username,
            user.first_name,
            now(),
            user.id,
        ))
    else:
        conn.execute("""
            INSERT INTO users
            (user_id, username, first_name, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username,
            user.first_name,
            now(),
            now(),
        ))

    conn.commit()
    conn.close()


def is_banned(user_id):
    conn = connect()
    row = conn.execute(
        "SELECT banned FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()

    return bool(row and row["banned"])


def add_balance(user_id, amount):
    conn = connect()
    conn.execute(
        "UPDATE users SET balance=balance+? WHERE user_id=?",
        (amount, user_id)
    )
    conn.commit()
    conn.close()


# ============================================================
# KEYBOARDS
# ============================================================

def user_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🪐 ساخت پنل", "📋 پنل‌های من"],
            ["🔗 آخرین پنل", "📊 وضعیت پنل"],
            ["🗑️ حذف پنل", "🎁 دعوت دوستان"],
            ["💰 امتیاز من", "🎁 پاداش روزانه"],
            ["🔄 شروع دوباره"],
        ],
        resize_keyboard=True,
    )


def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📊 آمار", "👥 کاربران"],
            ["🪐 پنل‌ها", "📢 ارسال همگانی"],
            ["🚫 بن کاربر", "✅ آن‌بن کاربر"],
            ["🪐 ساخت پنل", "📋 پنل‌های من"],
            ["💰 امتیاز من", "🎁 دعوت دوستان"],
            ["🔄 شروع دوباره"],
        ],
        resize_keyboard=True,
    )


def join_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 عضویت در @ByteTunnel",
                url="https://t.me/ByteTunnel"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ بررسی عضویت",
                callback_data="check_join"
            )
        ],
    ])


def api_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔑 دریافت API",
                url=API_URL
            )
        ]
    ])


# ============================================================
# FORCE JOIN
# ============================================================

async def check_membership(context, user_id):
    if user_id == ADMIN_ID:
        return True

    try:
        member = await context.bot.get_chat_member(
            CHANNEL,
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception:
        return False


async def send_join_required(update, context):
    text = (
        "برای استفاده از بات ابتدا باید در کانال عضو بشی 👇\n\n"
        "بعد از عضویت روی «✅ بررسی عضویت» بزن."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=join_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=join_keyboard()
        )


# ============================================================
# TUTORIAL
# ============================================================

TUTORIAL = """آموزش رو کامل بخون تا جایی رو اشتباه نکنی 🤓💕

⚠️ اول از همه وقتی آموزش رو خوندی، دکمه ثبت‌نام Cloudflare میاد که باید با ایمیل اصلی خودت ثبت‌نام کنی. استفاده از ایمیل فیک ممکنه در مراحل ساخت پنل باعث خطا بشه و حتی محدودیت‌هایی برای حساب ایجاد کنه.

2️⃣ وقتی ثبت‌نام کردی، بزن «ثبت نام کردم» و بعد بزن «دریافت API». سپس لینک رو باز کن؛ به چیزی دست نزن، تنظیمات خودش به‌صورت خودکار آماده شده. بعد روی این دو گزینه بزن:

Continue to summary

و بعد:

Create Token

3️⃣ توکن ساخته‌شده رو کپی کن و همینجا برام بفرست.

سپس فقط صبر کن تا بات مستقیم کارهای ساخت پنل رو انجام بده و لینک پنل رو برات بفرسته ⭐

We love you ramin 🌹"""


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    if is_banned(user.id):
        await update.message.reply_text(
            "🚫 دسترسی شما به بات مسدود شده است."
        )
        return

    # Referral
    if context.args:
        try:
            referrer_id = int(context.args[0])

            if referrer_id != user.id:
                conn = connect()

                existing = conn.execute(
                    "SELECT referred_id FROM referrals WHERE referred_id=?",
                    (user.id,)
                ).fetchone()

                if not existing:
                    conn.execute("""
                        INSERT INTO referrals
                        (referrer_id, referred_id, reward_given, created_at)
                        VALUES (?, ?, 0, ?)
                    """, (
                        referrer_id,
                        user.id,
                        now(),
                    ))

                    conn.execute("""
                        UPDATE users
                        SET referral_by=?
                        WHERE user_id=?
                    """, (
                        referrer_id,
                        user.id,
                    ))

                    conn.commit()

                conn.close()

        except Exception:
            pass

    if not await check_membership(context, user.id):
        await send_join_required(update, context)
        return

    states.pop(user.id, None)

    await update.message.reply_text(
        TUTORIAL,
        reply_markup=ReplyKeyboardMarkup(
            [["🤓 خوندم"]],
            resize_keyboard=True
        )
    )


# ============================================================
# CLOUDFLARE FLOW
# ============================================================

async def show_first_step(update):
    await update.message.reply_text(
        """مرحله اول 👇

وارد صفحه‌ی Cloudflare شو و روی دکمه‌ی Sign Up کلیک کن، سپس حساب جیمیل خودت رو انتخاب کن.

وقتی ثبت‌نام با موفقیت انجام شد، برگرد به بات و روی دکمه‌ی «ثبت نام کردم» بزن.""",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["☁️ ثبت‌نام Cloudflare"],
                ["✅ ثبت نام کردم"],
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
    )


async def request_api(update):
    states[update.effective_user.id] = "waiting_token"

    await update.message.reply_text(
        """حالا وارد صفحه‌ی API Token شو 👇

طبق آموزش، در قسمت آبی‌رنگ ابتدا روی «Continue to summary» بزن و سپس در صفحه‌ی بعد روی «Create Token» کلیک کن.

🔐 بعد از ساخت Token، کد ساخته‌شده را همینجا ارسال کن.

بعد از اینکه ثبت‌نام کردی، این دکمه رو بزن:""",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["🔑 دریافت API"],
                ["🔄 شروع دوباره"],
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )
    )

    await update.message.reply_text(
        "برای ساخت API Token روی دکمه زیر بزن:",
        reply_markup=api_keyboard()
    )


# ============================================================
# CLOUDFLARE API
# ============================================================

def cf_request(token, method, url):
    command = [
        "curl",
        "-sS",
        "-X",
        method,
        "-H",
        f"Authorization: Bearer {token}",
        "-H",
        "Content-Type: application/json",
        url,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
    )

    return result.returncode, result.stdout, result.stderr


def get_account_id(token):
    code, out, err = cf_request(
        token,
        "GET",
        "https://api.cloudflare.com/client/v4/accounts"
    )

    if code != 0:
        return None

    import json

    try:
        data = json.loads(out)
        result = data.get("result", [])

        if result:
            return result[0].get("id")

    except Exception:
        pass

    return None


# ============================================================
# BUILD QUEUE
# ============================================================

async def queue_build(update, context, token):
    global build_queue

    if build_queue is None:
        build_queue = asyncio.Queue()

    user_id = update.effective_user.id

    position = build_queue.qsize() + 1

    await update.message.reply_text(
        f"⏳ درخواست شما در صف ساخت قرار گرفت.\n\n"
        f"شماره در صف: {position}\n\n"
        f"لطفاً تا پایان ساخت منتظر بمانید.",
        reply_markup=ReplyKeyboardMarkup(
            [["🔄 شروع دوباره"]],
            resize_keyboard=True
        )
    )

    await build_queue.put({
        "update": update,
        "context": context,
        "token": token,
    })


async def build_worker():
    while True:
        job = await build_queue.get()

        try:
            await create_panel(
                job["update"],
                job["context"],
                job["token"]
            )
        except Exception as e:
            try:
                await job["update"].effective_message.reply_text(
                    f"❌ خطای غیرمنتظره در ساخت پنل:\n\n{str(e)[:2000]}"
                )
            except Exception:
                pass
        finally:
            build_queue.task_done()


# ============================================================
# CREATE PANEL
# ============================================================

def run_script(script_path, token):
    try:
        result = subprocess.run(
            [
                "bash",
                str(script_path),
            ],
            input=token.strip() + "\n",
            capture_output=True,
            text=True,
            timeout=900,
        )

        return result.returncode, result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        return -1, "", "Script timed out after 15 minutes."

    except Exception as e:
        return -2, "", str(e)


def redact(text, token):
    if not text:
        return ""

    if token:
        text = text.replace(token, "[REDACTED]")

    return text


def extract_panel_url(text):
    matches = re.findall(
        r"https://[A-Za-z0-9._-]+\.workers\.dev/[^\s\"'<>]+",
        text
    )

    if not matches:
        return None

    return matches[-1].rstrip(".,)")


def extract_worker(text):
    match = re.search(
        r"✓\s*Worker:\s*([A-Za-z0-9_-]+)",
        text
    )

    if match:
        return match.group(1)

    url = extract_panel_url(text)

    if url:
        host = url.split("/")[2]
        return host.split(".")[0]

    return None


def extract_db(text):
    match = re.search(
        r"✓\s*DB\s+([a-fA-F0-9-]{36})",
        text
    )

    if match:
        return match.group(1)

    return None


async def create_panel(update, context, token):
    user_id = update.effective_user.id

    if not SCRIPT.exists():
        await update.effective_message.reply_text(
            "❌ فایل bytetunnel.sh پیدا نشد."
        )
        return

    status_message = await update.effective_message.reply_text(
        "پنل درحال ساخت برای شما 🪐\n\n"
        "⬜⬜⬜⬜🟩"
    )

    temp_dir = None

    steps = [
        "⬜⬜⬜⬜🟩",
        "⬜⬜⬜🟩🟩",
        "⬜⬜🟩🟩🟩",
        "⬜🟩🟩🟩🟩",
    ]

    progress_task = None

    async def progress():
        for index, step in enumerate(steps):
            if index == 0:
                continue

            await asyncio.sleep(8)

            try:
                await status_message.edit_text(
                    "پنل درحال ساخت برای شما 🪐\n\n" + step
                )
            except Exception:
                pass

    try:
        temp_dir = tempfile.mkdtemp(prefix="bytetunnel_")

        script_copy = Path(temp_dir) / "bytetunnel.sh"

        shutil.copy2(
            SCRIPT,
            script_copy
        )

        os.chmod(
            script_copy,
            os.stat(script_copy).st_mode | 0o111
        )

        progress_task = asyncio.create_task(progress())

        returncode, stdout, stderr = await asyncio.to_thread(
            run_script,
            script_copy,
            token
        )

        if progress_task:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

        output = redact(
            (stdout or "") + "\n" + (stderr or ""),
            token
        )

        if returncode != 0:
            await status_message.edit_text(
                "❌ ساخت پنل ناموفق بود.\n\n"
                "خروجی خطا:\n"
                f"{output[-2500:]}"
            )
            return

        panel_url = extract_panel_url(output)
        worker_name = extract_worker(output)
        db_id = extract_db(output)

        if not panel_url:
            await status_message.edit_text(
                "❌ اسکریپت اجرا شد اما لینک پنل پیدا نشد.\n\n"
                f"{output[-2500:]}"
            )
            return

        account_id = await asyncio.to_thread(
            get_account_id,
            token
        )

        conn = connect()

        conn.execute("""
            INSERT INTO panels
            (
                user_id,
                worker_name,
                panel_url,
                db_id,
                account_id,
                created_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (
            user_id,
            worker_name or "unknown",
            panel_url,
            db_id,
            account_id,
            now(),
        ))

        conn.commit()
        conn.close()

        await status_message.edit_text(
            "پنل درحال ساخت برای شما 🪐\n\n"
            "🟩🟩🟩🟩🟩"
        )

        await asyncio.sleep(1)

        await status_message.edit_text(
            f"""🎉 پنل با موفقیت ساخته شد 🥳

🌍 پنل شما دارای مولتی‌لوکیشن است.

🔐 لطفاً هنگام ورود، رمز موردنظر خود را طوری انتخاب کنید که بعداً هم به خاطر داشته باشید.

🔗 لینک پنل:
{panel_url}

💙 امیدوارم از خدمات رایگان چنل لذت ببری 🌹✨"""
        )

        await update.effective_message.reply_text(
            "منوی پنل:",
            reply_markup=user_keyboard()
        )

    finally:
        if temp_dir:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )


# ============================================================
# PANELS
# ============================================================

def get_user_panels(user_id):
    conn = connect()

    rows = conn.execute("""
        SELECT *
        FROM panels
        WHERE user_id=?
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    conn.close()
    return rows


async def show_panels(update):
    rows = get_user_panels(
        update.effective_user.id
    )

    if not rows:
        await update.message.reply_text(
            "📋 هنوز هیچ پنلی برای شما ساخته نشده است.",
            reply_markup=user_keyboard()
        )
        return

    buttons = []

    for row in rows[:20]:
        buttons.append([
            InlineKeyboardButton(
                f"🪐 پنل #{row['id']}",
                callback_data=f"panel:{row['id']}"
            )
        ])

    await update.message.reply_text(
        f"📋 پنل‌های شما: {len(rows)}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def show_last_panel(update):
    conn = connect()

    row = conn.execute("""
        SELECT *
        FROM panels
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 1
    """, (
        update.effective_user.id,
    )).fetchone()

    conn.close()

    if not row:
        await update.message.reply_text(
            "❌ هنوز پنلی ندارید."
        )
        return

    await update.message.reply_text(
        f"""🔗 آخرین پنل شما

🪐 Worker:
{row['worker_name']}

📅 تاریخ ساخت:
{row['created_at']}

📌 وضعیت ثبت‌شده:
{row['status']}

🔗 لینک:
{row['panel_url']}""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🌍 باز کردن پنل",
                    url=row["panel_url"]
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 بررسی وضعیت",
                    callback_data=f"status:{row['id']}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑️ حذف",
                    callback_data=f"delete:{row['id']}"
                )
            ],
        ])
    )


async def panel_details(update, panel_id):
    query = update.callback_query

    conn = connect()

    row = conn.execute("""
        SELECT *
        FROM panels
        WHERE id=? AND user_id=?
    """, (
        panel_id,
        update.effective_user.id,
    )).fetchone()

    conn.close()

    if not row:
        await query.edit_message_text(
            "❌ پنل پیدا نشد."
        )
        return

    await query.edit_message_text(
        f"""🪐 پنل #{row['id']}

Worker:
{row['worker_name']}

Database:
{row['db_id'] or 'نامشخص'}

تاریخ:
{row['created_at']}

وضعیت:
{row['status']}

🔗 {row['panel_url']}""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🌍 باز کردن",
                    url=row["panel_url"]
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 بررسی وضعیت",
                    callback_data=f"status:{row['id']}"
                ),
                InlineKeyboardButton(
                    "🗑️ حذف",
                    callback_data=f"delete:{row['id']}"
                )
            ]
        ])
    )


# ============================================================
# STATUS
# ============================================================

async def ask_status(update):
    rows = get_user_panels(
        update.effective_user.id
    )

    if not rows:
        await update.message.reply_text(
            "❌ پنلی ندارید."
        )
        return

    buttons = []

    for row in rows[:20]:
        buttons.append([
            InlineKeyboardButton(
                f"📊 پنل #{row['id']}",
                callback_data=f"status:{row['id']}"
            )
        ])

    await update.message.reply_text(
        "پنلی که می‌خواهی وضعیتش بررسی شود را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def request_status_token(update, panel_id):
    states[update.effective_user.id] = (
        f"status_token:{panel_id}"
    )

    await update.effective_message.reply_text(
        "🔑 برای بررسی واقعی وضعیت پنل، API Token همان حساب Cloudflare را ارسال کن."
    )


async def check_panel_status(update, panel_id, token):
    user_id = update.effective_user.id

    conn = connect()

    row = conn.execute("""
        SELECT *
        FROM panels
        WHERE id=? AND user_id=?
    """, (
        panel_id,
        user_id,
    )).fetchone()

    conn.close()

    if not row:
        await update.message.reply_text(
            "❌ پنل پیدا نشد."
        )
        return

    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{row['account_id']}/workers/scripts/{row['worker_name']}"
    )

    code, out, err = await asyncio.to_thread(
        cf_request,
        token,
        "GET",
        url
    )

    if code == 0 and '"success":true' in out.replace(" ", ""):
        status = "active"

        conn = connect()
        conn.execute(
            "UPDATE panels SET status=? WHERE id=?",
            (status, panel_id)
        )
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"""🟢 پنل فعال است

🪐 Worker:
{row['worker_name']}

🔗 {row['panel_url']}"""
        )
    else:
        await update.message.reply_text(
            "🔴 وضعیت پنل قابل تأیید نیست.\n\n"
            "ممکن است Worker حذف شده باشد یا Token دسترسی لازم را نداشته باشد."
        )


# ============================================================
# DELETE PANEL
# ============================================================

async def ask_delete(update):
    rows = get_user_panels(
        update.effective_user.id
    )

    if not rows:
        await update.message.reply_text(
            "❌ پنلی برای حذف ندارید."
        )
        return

    buttons = []

    for row in rows[:20]:
        buttons.append([
            InlineKeyboardButton(
                f"🗑️ پنل #{row['id']}",
                callback_data=f"delete:{row['id']}"
            )
        ])

    await update.message.reply_text(
        "⚠️ پنلی که می‌خواهی حذف شود را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def request_delete_token(update, panel_id):
    states[update.effective_user.id] = (
        f"delete_token:{panel_id}"
    )

    await update.effective_message.reply_text(
        "⚠️ حذف پنل دائمی است.\n\n"
        "برای ادامه، API Token همان حساب Cloudflare را ارسال کن."
    )


async def delete_panel(update, panel_id, token):
    user_id = update.effective_user.id

    conn = connect()

    row = conn.execute("""
        SELECT *
        FROM panels
        WHERE id=? AND user_id=?
    """, (
        panel_id,
        user_id,
    )).fetchone()

    conn.close()

    if not row:
        await update.message.reply_text(
            "❌ پنل پیدا نشد."
        )
        return

    if not row["account_id"]:
        await update.message.reply_text(
            "❌ شناسه حساب Cloudflare برای این پنل ثبت نشده است."
        )
        return

    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{row['account_id']}/workers/scripts/{row['worker_name']}"
    )

    code, out, err = await asyncio.to_thread(
        cf_request,
        token,
        "DELETE",
        url
    )

    if code != 0:
        await update.message.reply_text(
            "❌ ارتباط با Cloudflare برقرار نشد."
        )
        return

    if '"success":true' not in out.replace(" ", ""):
        await update.message.reply_text(
            "❌ حذف Worker انجام نشد.\n\n"
            "ممکن است API Token دسترسی لازم را نداشته باشد."
        )
        return

    conn = connect()

    conn.execute(
        "UPDATE panels SET status='deleted' WHERE id=?",
        (panel_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ پنل #{panel_id} با موفقیت حذف شد."
    )


# ============================================================
# REFERRAL / REWARDS
# ============================================================

async def referral_info(update):
    user_id = update.effective_user.id

    bot = await update.get_bot()
    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}?start={user_id}"
    )

    conn = connect()

    count = conn.execute("""
        SELECT COUNT(*)
        FROM referrals
        WHERE referrer_id=?
    """, (user_id,)).fetchone()[0]

    balance = conn.execute("""
        SELECT balance
        FROM users
        WHERE user_id=?
    """, (user_id,)).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"""🎁 دعوت دوستان

👥 تعداد دعوت‌شده:
{count}

💰 امتیاز شما:
{balance}

🎁 پاداش هر دعوت:
{REFERRAL_REWARD} امتیاز

🔗 لینک دعوت شما:
{link}

لینک را برای دوستانت بفرست."""
    )


async def show_balance(update):
    conn = connect()

    row = conn.execute("""
        SELECT balance
        FROM users
        WHERE user_id=?
    """, (
        update.effective_user.id,
    )).fetchone()

    conn.close()

    balance = row["balance"] if row else 0

    await update.message.reply_text(
        f"💰 موجودی امتیاز شما: {balance}"
    )


async def daily_reward(update):
    user_id = update.effective_user.id
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conn = connect()

    row = conn.execute("""
        SELECT last_daily
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if row and row["last_daily"] == today:
        conn.close()

        await update.message.reply_text(
            "⏳ پاداش امروزت رو قبلاً گرفتی.\n\n"
            "فردا دوباره امتحان کن."
        )
        return

    conn.execute("""
        UPDATE users
        SET balance=balance+?,
            last_daily=?
        WHERE user_id=?
    """, (
        DAILY_REWARD,
        today,
        user_id,
    ))

    conn.commit()

    balance = conn.execute("""
        SELECT balance
        FROM users
        WHERE user_id=?
    """, (user_id,)).fetchone()["balance"]

    conn.close()

    await update.message.reply_text(
        f"🎁 پاداش روزانه دریافت شد!\n\n"
        f"➕ {DAILY_REWARD} امتیاز\n"
        f"💰 موجودی فعلی: {balance}"
    )


# ============================================================
# ADMIN
# ============================================================

def admin_only(user_id):
    return user_id == ADMIN_ID


async def admin_stats(update):
    if not admin_only(update.effective_user.id):
        return

    conn = connect()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    banned = conn.execute(
        "SELECT COUNT(*) FROM users WHERE banned=1"
    ).fetchone()[0]

    panels = conn.execute(
        "SELECT COUNT(*) FROM panels"
    ).fetchone()[0]

    active = conn.execute(
        "SELECT COUNT(*) FROM panels WHERE status='active'"
    ).fetchone()[0]

    referrals = conn.execute(
        "SELECT COUNT(*) FROM referrals"
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"""📊 آمار بات

👥 کاربران: {users}
🚫 کاربران بن‌شده: {banned}

🪐 کل پنل‌ها: {panels}
🟢 پنل‌های فعال: {active}

🎁 دعوت‌ها: {referrals}"""
    )


async def admin_users(update):
    if not admin_only(update.effective_user.id):
        return

    conn = connect()

    rows = conn.execute("""
        SELECT user_id, username, first_name, balance, banned
        FROM users
        ORDER BY last_seen DESC
        LIMIT 30
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "کاربری ثبت نشده."
        )
        return

    text = "👥 آخرین کاربران:\n\n"

    for row in rows:
        name = row["first_name"] or "-"
        username = (
            f"@{row['username']}"
            if row["username"]
            else "-"
        )

        text += (
            f"🆔 {row['user_id']}\n"
            f"👤 {name} {username}\n"
            f"💰 {row['balance']}\n"
            f"{'🚫 بن' if row['banned'] else '🟢 فعال'}\n\n"
        )

    await update.message.reply_text(text[:4000])


async def admin_panels(update):
    if not admin_only(update.effective_user.id):
        return

    conn = connect()

    rows = conn.execute("""
        SELECT id, user_id, worker_name, status, created_at
        FROM panels
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "🪐 هنوز پنلی ثبت نشده."
        )
        return

    text = "🪐 آخرین پنل‌ها:\n\n"

    for row in rows:
        text += (
            f"#{row['id']} | "
            f"user={row['user_id']}\n"
            f"Worker: {row['worker_name']}\n"
            f"Status: {row['status']}\n"
            f"{row['created_at']}\n\n"
        )

    await update.message.reply_text(text[:4000])


async def ask_ban(update):
    if not admin_only(update.effective_user.id):
        return

    states[update.effective_user.id] = "admin_ban"

    await update.message.reply_text(
        "🆔 آیدی عددی کاربر را ارسال کن:"
    )


async def ask_unban(update):
    if not admin_only(update.effective_user.id):
        return

    states[update.effective_user.id] = "admin_unban"

    await update.message.reply_text(
        "🆔 آیدی عددی کاربر را ارسال کن:"
    )


async def do_ban(update, user_id):
    if not admin_only(update.effective_user.id):
        return

    conn = connect()

    conn.execute(
        "UPDATE users SET banned=1 WHERE user_id=?",
        (user_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 کاربر {user_id} بن شد."
    )


async def do_unban(update, user_id):
    if not admin_only(update.effective_user.id):
        return

    conn = connect()

    conn.execute(
        "UPDATE users SET banned=0 WHERE user_id=?",
        (user_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ کاربر {user_id} آن‌بن شد."
    )


async def ask_broadcast(update):
    if not admin_only(update.effective_user.id):
        return

    states[update.effective_user.id] = "admin_broadcast"

    await update.message.reply_text(
        "📢 متن پیام همگانی را ارسال کن:"
    )


async def do_broadcast(update):
    if not admin_only(update.effective_user.id):
        return

    text = update.message.text

    conn = connect()

    rows = conn.execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()

    conn.close()

    success = 0
    failed = 0

    for row in rows:
        try:
            await context_bot.send_message(
                chat_id=row["user_id"],
                text=text
            )
            success += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"📢 ارسال همگانی تمام شد.\n\n"
        f"✅ موفق: {success}\n"
        f"❌ ناموفق: {failed}"
    )


context_bot = None


# ============================================================
# CALLBACKS
# ============================================================

async def callbacks(update, context):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if query.data == "check_join":
        if not await check_membership(context, user_id):
            await query.answer(
                "❌ هنوز عضو کانال نیستی.",
                show_alert=True
            )
            return

        await query.message.reply_text(
            TUTORIAL,
            reply_markup=ReplyKeyboardMarkup(
                [["🤓 خوندم"]],
                resize_keyboard=True
            )
        )
        return

    if query.data.startswith("panel:"):
        panel_id = int(query.data.split(":")[1])
        await panel_details(update, panel_id)
        return

    if query.data.startswith("status:"):
        panel_id = int(query.data.split(":")[1])

        if user_id == ADMIN_ID or await check_membership(
            context,
            user_id
        ):
            states[user_id] = f"status_token:{panel_id}"

            await query.message.reply_text(
                "🔑 API Token حساب Cloudflare را ارسال کن."
            )
        return

    if query.data.startswith("delete:"):
        panel_id = int(query.data.split(":")[1])

        states[user_id] = f"delete_token:{panel_id}"

        await query.message.reply_text(
            "⚠️ این عملیات Worker را از Cloudflare حذف می‌کند.\n\n"
            "برای ادامه API Token را ارسال کن."
        )


# ============================================================
# MESSAGE ROUTER
# ============================================================

async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global context_bot

    context_bot = context.bot

    user = update.effective_user
    text = (update.message.text or "").strip()

    ensure_user(user)

    if is_banned(user.id):
        await update.message.reply_text(
            "🚫 دسترسی شما به بات مسدود شده است."
        )
        return

    state = states.get(user.id)

    # -------------------------
    # API TOKEN
    # -------------------------

    if state == "waiting_token":
        states.pop(user.id, None)

        if len(text) < 20:
            await update.message.reply_text(
                "❌ مقدار API Token معتبر به نظر نمی‌رسد."
            )
            return

        await queue_build(
            update,
            context,
            text
        )
        return

    if state and state.startswith("status_token:"):
        panel_id = int(state.split(":")[1])

        states.pop(user.id, None)

        await check_panel_status(
            update,
            panel_id,
            text
        )
        return

    if state and state.startswith("delete_token:"):
        panel_id = int(state.split(":")[1])

        states.pop(user.id, None)

        await delete_panel(
            update,
            panel_id,
            text
        )
        return

    # -------------------------
    # ADMIN STATES
    # -------------------------

    if state == "admin_ban":
        states.pop(user.id, None)

        try:
            target = int(text)
            await do_ban(update, target)
        except Exception:
            await update.message.reply_text(
                "❌ آیدی نامعتبر است."
            )
        return

    if state == "admin_unban":
        states.pop(user.id, None)

        try:
            target = int(text)
            await do_unban(update, target)
        except Exception:
            await update.message.reply_text(
                "❌ آیدی نامعتبر است."
            )
        return

    if state == "admin_broadcast":
        states.pop(user.id, None)

        await do_broadcast(update)
        return

    # -------------------------
    # JOIN
    # -------------------------

    if text == "🤓 خوندم":
        if not await check_membership(context, user.id):
            await send_join_required(update, context)
            return

        await show_first_step(update)
        return

    if text == "☁️ ثبت‌نام Cloudflare":
        await update.message.reply_text(
            """☁️ برای ثبت‌نام وارد صفحه Cloudflare شو.

بعد از اینکه ثبت‌نام کردی، برگرد به بات و دکمه‌ی زیر رو بزن:""",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "☁️ Sign Up",
                        url=CF_SIGNUP
                    )
                ]
            ])
        )

        await update.message.reply_text(
            "بعد از اینکه ثبت‌نام کردی، این دکمه رو بزن:",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["✅ ثبت نام کردم"],
                    ["🔄 شروع دوباره"],
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
        )
        return

    if text == "✅ ثبت نام کردم":
        await request_api(update)
        return

    if text == "🔑 دریافت API":
        states[user.id] = "waiting_token"

        await update.message.reply_text(
            """🔐 بعد از ساخت Token، کد ساخته‌شده را همینجا ارسال کن.

فقط خود Token را بفرست؛ هیچ متن اضافه‌ای لازم نیست.""",
            reply_markup=ReplyKeyboardMarkup(
                [
                    ["🔄 شروع دوباره"],
                ],
                resize_keyboard=True,
                one_time_keyboard=False
            )
        )
        return

    # -------------------------
    # USER MENU
    # -------------------------

    if text == "🪐 ساخت پنل":
        await request_api(update)
        return

    if text == "📋 پنل‌های من":
        await show_panels(update)
        return

    if text == "🔗 آخرین پنل":
        await show_last_panel(update)
        return

    if text == "📊 وضعیت پنل":
        await ask_status(update)
        return

    if text == "🗑️ حذف پنل":
        await ask_delete(update)
        return

    if text == "🎁 دعوت دوستان":
        await referral_info(update)
        return

    if text == "💰 امتیاز من":
        await show_balance(update)
        return

    if text == "🎁 پاداش روزانه":
        await daily_reward(update)
        return

    if text == "🔄 شروع دوباره":
        states.pop(user.id, None)

        if not await check_membership(context, user.id):
            await send_join_required(update, context)
            return

        await update.message.reply_text(
            TUTORIAL,
            reply_markup=ReplyKeyboardMarkup(
                [["🤓 خوندم"]],
                resize_keyboard=True
            )
        )
        return

    # -------------------------
    # ADMIN MENU
    # -------------------------

    if user.id == ADMIN_ID:

        if text == "📊 آمار":
            await admin_stats(update)
            return

        if text == "👥 کاربران":
            await admin_users(update)
            return

        if text == "🪐 پنل‌ها":
            await admin_panels(update)
            return

        if text == "🚫 بن کاربر":
            await ask_ban(update)
            return

        if text == "✅ آن‌بن کاربر":
            await ask_unban(update)
            return

        if text == "📢 ارسال همگانی":
            await ask_broadcast(update)
            return


# ============================================================
# POST INIT
# ============================================================

async def post_init(application):
    global build_queue

    init_db()

    build_queue = asyncio.Queue()

    asyncio.create_task(
        build_worker()
    )


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(callbacks)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message
        )
    )

    print("ByteTunnelBot is running...")
    print(f"Database: {DB_FILE}")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
