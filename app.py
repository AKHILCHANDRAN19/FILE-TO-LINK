import os
import threading
import asyncio
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    CallbackQuery
)
from aiohttp import web
import secrets
import logging

# ==================== CONFIGURATION ====================
API_ID = int(os.environ.get("API_ID", 2819362))
API_HASH = os.environ.get("API_HASH", "578ce3d09fadd539544a327c45b55ee4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", -1001854240817))
PORT = int(os.environ.get("PORT", 8000))
OWNER_ID = 6219290068
PRO_USERS_FILE = "pro_users.txt"
REPO_STICKER_ID = "CAACAgUAAxkBAAE9tahpE-Oz4dCOfweAKQE_KU3zO6YzKgACMQADsx6IFV2DVIFED1oBNgQ"

file_storage = {}
pro_users = set()
start_time = datetime.now()

bot = Client(
    "file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    parse_mode=enums.ParseMode.MARKDOWN
)

# ==================== LOGGING & UTILS ====================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
LOGGER = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

def generate_link_id():
    return secrets.token_urlsafe(12)

def generate_aria2_command(url: str, filename: str) -> str:
    """Generate aria2c command with MAX 16 connections (aria2 limit)"""
    return (
        f'aria2c --header="User-Agent: Mozilla/5.0" --continue=true --summary-interval=1 '
        f'--dir=/storage/emulated/0/Download --out="{filename}" --console-log-level=error '
        # FIXED: Changed from 32 to 16 (aria2 max limit)
        f'--max-connection-per-server=16 --split=16 --min-split-size=512K '
        f'--max-concurrent-downloads=8 --max-tries=10 --retry-wait=5 --timeout=60 '
        f'--check-certificate=false --async-dns=false --max-overall-download-limit=0 "{url}"'
    )

def generate_beautiful_response(file_name: str, download_url: str, aria2_cmd: str) -> str:
    """Professional response with blue clickable URL and code box"""
    return (
        f"✨ **Download Ready!** ✨\n\n"
        f"📂 **File:** `{file_name}`\n"
        f"⏱️ **Expires:** `24 hours`\n\n"
        f"🔗 **Direct Download URL:**\n"
        f"[{download_url}]({download_url})\n\n"
        f"⚡ **Aria2 Command:**\n"
        f"```bash\n{aria2_cmd}\n```"
    )

def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in pro_users

def load_pro_users():
    try:
        with open(PRO_USERS_FILE, 'r') as f:
            return set(int(line.strip()) for line in f if line.strip())
    except FileNotFoundError:
        return set()

def save_pro_users():
    with open(PRO_USERS_FILE, 'w') as f:
        for user_id in sorted(pro_users):
            f.write(f"{user_id}\n")

pro_users = load_pro_users()

# ==================== COMMAND HANDLERS ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user = message.from_user
    is_auth = is_authorized(user.id)
    
    welcome_text = (
        f"👋 **Welcome {user.first_name}!**\n\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"✅ **Status:** `{'Authorized ✓' if is_auth else 'Not Authorized ✗'}`\n\n"
        f"📤 **Send any file** to generate download link\n\n"
        f"📣 **Channel:** Forward files to bin channel for auto-links\n\n"
        f"💡 **Max Size:** 4GB per file\n"
        f"⏰ **Link Duration:** 24 hours"
    )
    
    # Horizontal button layout
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👑 Owner", url="https://t.me/FILMWORLDOFFICIA"),
            InlineKeyboardButton("📢 Updates", url="https://t.me/FILMWORLDOFFI")
        ],
        [
            InlineKeyboardButton("📦 Repo", callback_data="repo"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return
        
    help_text = (
        "📖 **Help Guide**\n\n"
        "**1. Direct Bot:**\n   Send file privately → Get instant links\n\n"
        "**2. Channel Auto-Link:**\n   Forward to bin channel → Bot auto-generates\n\n"
        "**Admin Commands:**\n"
        "`/adduser <id>` `/removeuser <id>`\n"
        "`/listusers` `/stats` `/broadcast <msg>`"
    )
    
    await message.reply_text(help_text)

@bot.on_message(filters.command("id") & filters.private)
async def get_id_command(client: Client, message: Message):
    user = message.from_user
    username_text = f"**Username:** `@{user.username}`\n" if user.username else ""
    
    await message.reply_text(
        f"🆔 **Your Telegram Details**\n\n"
        f"**User ID:** `{user.id}`\n"
        f"{username_text}\n"
        f"💡 Use this ID to be added as authorized user"
    )

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("⛔ **Owner only!**")
        return
    
    uptime = datetime.now() - start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    stats_text = (
        f"📊 **Bot Statistics**\n\n"
        f"⏱️ **Uptime:** `{hours}h {minutes}m {seconds}s`\n"
        f"🔗 **Active Links:** `{len(file_storage)}`\n"
        f"👑 **Pro Users:** `{len(pro_users)}`\n"
        f"🤖 **Status:** `Operational ✓`"
    )
    
    await message.reply_text(stats_text)

@bot.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("❌ **Usage:** `/broadcast Your message`")
        return
    
    broadcast_text = message.text.split(' ', 1)[1]
    all_users = pro_users | {OWNER_ID}
    success = failed = 0
    
    status_msg = await message.reply_text("📢 Broadcasting...")
    
    for user_id in all_users:
        try:
            await client.send_message(user_id, f"📢 **Broadcast:**\n\n{broadcast_text}")
            success += 1
        except:
            failed += 1
    
    await status_msg.edit_text(f"✅ Complete!\n📤 Sent: {success}\n❌ Failed: {failed}")

@bot.on_message(filters.command("adduser") & filters.user(OWNER_ID))
async def add_pro_user(client: Client, message: Message):
    try:
        user_id = int(message.command[1])
        pro_users.add(user_id)
        save_pro_users()
        await message.reply_text(f"✅ **Authorized:** `{user_id}`")
    except (IndexError, ValueError):
        await message.reply_text("❌ **Usage:** `/adduser 123456789`")

@bot.on_message(filters.command("removeuser") & filters.user(OWNER_ID))
async def remove_pro_user(client: Client, message: Message):
    try:
        user_id = int(message.command[1])
        if user_id in pro_users:
            pro_users.remove(user_id)
            save_pro_users()
            await message.reply_text(f"✅ **Removed:** `{user_id}`")
        else:
            await message.reply_text("❌ User not found!")
    except (IndexError, ValueError):
        await message.reply_text("❌ **Usage:** `/removeuser 123456789`")

@bot.on_message(filters.command("listusers") & filters.user(OWNER_ID))
async def list_pro_users(client: Client, message: Message):
    if not pro_users:
        await message.reply_text("📋 **No authorized users.**")
        return
    
    user_list = "\n".join([f"• `{uid}`" for uid in sorted(pro_users)])
    await message.reply_text(f"📊 **Authorized Users:**\n\n{user_list}")

# ==================== CALLBACK HANDLERS ====================
@bot.on_callback_query(filters.regex("^help"))
async def help_callback(client: Client, query: CallbackQuery):
    await query.answer()
    
    help_text = (
        "📖 **Quick Help**\n\n"
        "**How to use:**\n"
        "1. Forward files to bin channel\n"
        "2. Bot auto-generates links\n\n"
        "**Features:**\n"
        "✓ 4GB file support\n"
        "✓ 16 connections (aria2 max)\n"
        "✓ 24-hour links\n\n"
        "👑 Owner: @FILMWORLDOFFICIA"
    )
    
    await query.message.reply_text(help_text)

@bot.on_callback_query(filters.regex("^repo"))
async def repo_callback(client: Client, query: CallbackQuery):
    await query.answer()
    await query.message.reply_sticker(sticker=REPO_STICKER_ID)
    await query.message.reply_text("📦 **Repository Sticker!**")

# ==================== FILE HANDLERS ====================
@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def private_file_handler(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        await message.reply_text("⛔ **Access Denied!**\n\n👑 Contact owner: @FILMWORLDOFFICIA")
        return
    
    LOGGER.info(f"📁 File from authorized user {user_id}")
    status_msg = await message.reply_text("⏳ **Processing...**")
    
    try:
        file = message.document or message.video or message.audio or message.photo
        if message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f'file_{secrets.token_hex(4)}')
        file_size = getattr(file, 'file_size', 0)
        
        forwarded = await message.forward(BIN_CHANNEL)
        
        link_id = generate_link_id()
        file_storage[link_id] = {
            "message_id": forwarded.id,
            "file_name": file_name,
            "file_size": file_size
        }
        
        base_url = f"https://file-to-link-5haa.onrender.com"
        download_url = f"{base_url}/download/{link_id}"
        aria2_cmd = generate_aria2_command(download_url, file_name)
        
        await status_msg.edit_text(
            generate_beautiful_response(file_name, download_url, aria2_cmd)
        )
        
    except Exception as e:
        LOGGER.error(f"❌ Error: {e}")
        await status_msg.edit_text("❌ **Error processing file!**")

@bot.on_message(filters.chat(BIN_CHANNEL) & (filters.document | filters.video | filters.audio | filters.photo))
async def channel_auto_link(client: Client, message: Message):
    if message.from_user and message.from_user.is_bot:
        return
    
    LOGGER.info(f"📤 Auto-link for channel file (ID: {message.id})")
    
    try:
        file = message.document or message.video or message.audio or message.photo
        if message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f'file_{secrets.token_hex(4)}')
        
        link_id = generate_link_id()
        file_storage[link_id] = {
            "message_id": message.id,
            "file_name": file_name,
            "file_size": getattr(file, 'file_size', 0)
        }
        
        base_url = f"https://file-to-link-5haa.onrender.com"
        download_url = f"{base_url}/download/{link_id}"
        aria2_cmd = generate_aria2_command(download_url, file_name)
        
        await message.reply_text(
            generate_beautiful_response(file_name, download_url, aria2_cmd)
        )
        
    except Exception as e:
        LOGGER.error(f"❌ Auto-link error: {e}")

# ==================== WEB SERVER ====================
async def homepage(request):
    return web.json_response({"status": "operational"})

async def health_check(request):
    return web.json_response({"status": "healthy"})

async def wake_bot(request):
    """Keep-alive endpoint to prevent Render sleep"""
    return web.json_response({
        "status": "awake",
        "message": "Bot is alive",
        "timestamp": datetime.now().isoformat()
    })

async def download_file(request):
    link_id = request.match_info['link_id']
    file_info = file_storage.get(link_id)
    
    if not file_info:
        return web.Response(status=404, text="File not found or expired")
    
    try:
        message = await bot.get_messages(BIN_CHANNEL, file_info["message_id"])
        
        file = message.document or message.video or message.audio or message.photo
        if message.photo:
            file = message.photo[-1]
        
        response = web.StreamResponse(
            status=200,
            headers={
                'Content-Disposition': f'attachment; filename="{file_info["file_name"]}"',
                'Content-Length': str(file_info["file_size"]),
                'Accept-Ranges': 'bytes',
            }
        )
        await response.prepare(request)
        
        async for chunk in bot.stream_media(file, limit=256 * 1024):
            await response.write(chunk)
        
        await response.write_eof()
        return response
        
    except Exception as e:
        LOGGER.error(f"Stream error: {e}")
        return web.Response(status=500, text="Streaming failed")

def create_web_app():
    app = web.Application()
    app.router.add_get('/', homepage)
    app.router.add_get('/health', health_check)
    app.router.add_get('/wake', wake_bot)
    app.router.add_get('/download/{link_id}', download_file)
    return app

def run_web_server():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = create_web_app()
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        loop.run_until_complete(site.start())
        LOGGER.info(f"Web server running on port {PORT}")
        loop.run_forever()
    except Exception as e:
        LOGGER.error(f"Web server error: {e}")

# ==================== MAIN ====================
if __name__ == "__main__":
    LOGGER.info("="*60)
    LOGGER.info("🚀 BOT STARTING")
    LOGGER.info(f"👑 Owner: @FILMWORLDOFFICIA")
    LOGGER.info(f"📊 Pro Users: {len(pro_users)}")
    LOGGER.info("="*60)
    
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    time.sleep(2)
    
    bot.run()
