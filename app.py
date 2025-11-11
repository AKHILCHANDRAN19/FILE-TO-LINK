import os
import threading
import asyncio
import time
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

# Initialize
file_storage = {}
pro_users = set()

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
    return (
        f'aria2c --header="User-Agent: Mozilla/5.0" --continue=true --summary-interval=1 '
        f'--dir=/storage/emulated/0/Download --out="{filename}" --console-log-level=error '
        f'--max-connection-per-server=16 --split=16 --min-split-size=1M '
        f'--max-concurrent-downloads=8 --max-tries=10 --retry-wait=5 --timeout=60 '
        f'--check-certificate=false --async-dns=false "{url}"'
    )

def generate_beautiful_response(file_name: str, download_url: str, aria2_cmd: str) -> str:
    """Generate professional response with full URL and code box"""
    return (
        f"✨ **Download Ready!** ✨\n\n"
        f"📂 **File:** `{file_name}`\n"
        f"⏱️ **Expires:** `24 hours`\n\n"
        f"🔗 **Direct Download URL:**\n"
        f"`{download_url}`\n\n"
        f"⚡ **Aria2 Command:**\n"
        f"```bash\n{aria2_cmd}\n```"
    )

# ==================== PRO USER MANAGEMENT ====================
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

def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in pro_users

pro_users = load_pro_users()

# ==================== COMMAND HANDLERS ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Professional /start command"""
    user = message.from_user
    
    welcome_text = (
        f"👋 **Welcome {user.first_name}!**\n\n"
        f"🆔 **User ID:** `{user.id}`\n\n"
        f"✅ **Authorization Status:** {'Authorized ✓' if is_authorized(user.id) else 'Not Authorized ✗'}\n\n"
        f"📤 **Send any file** to generate a download link\n\n"
        f"📣 **Channel Feature:** Forward files to bin channel for auto-links\n\n"
        f"💡 **Supports:** Documents, Videos, Audios, Photos up to 4GB"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Owner", url="https://t.me/FILMWORLDOFFICIA")],
        [InlineKeyboardButton("📢 Updates", url="https://t.me/FILMWORLDOFFI")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    if not is_authorized(message.from_user.id):
        return
        
    help_text = (
        "📖 **Help Guide**\n\n"
        "**1. Direct Bot Usage:**\n   • Send file directly to bot\n   • Get instant download + Aria2 link\n\n"
        "**2. Channel Auto-Link:**\n   • Forward files to bin channel\n   • Bot auto-generates links\n\n"
        "**3. Admin Commands:**\n   • `/adduser 123456` - Add pro user\n   • `/removeuser 123456` - Remove pro user\n   • `/listusers` - List all pro users"
    )
    
    await message.reply_text(help_text)

@bot.on_message(filters.command("adduser") & filters.user(OWNER_ID))
async def add_pro_user(client: Client, message: Message):
    try:
        user_id = int(message.command[1])
        pro_users.add(user_id)
        save_pro_users()
        await message.reply_text(f"✅ **Pro User Added:** `{user_id}`")
    except:
        await message.reply_text("❌ **Usage:** `/adduser 123456789`")

@bot.on_message(filters.command("removeuser") & filters.user(OWNER_ID))
async def remove_pro_user(client: Client, message: Message):
    try:
        user_id = int(message.command[1])
        if user_id in pro_users:
            pro_users.remove(user_id)
            save_pro_users()
            await message.reply_text(f"✅ **Removed Pro User:** `{user_id}`")
        else:
            await message.reply_text("❌ User not found!")
    except:
        await message.reply_text("❌ **Usage:** `/removeuser 123456789`")

@bot.on_message(filters.command("listusers") & filters.user(OWNER_ID))
async def list_pro_users(client: Client, message: Message):
    if not pro_users:
        await message.reply_text("📋 **No pro users added.**")
        return
    
    user_list = "\n".join([f"• `{uid}`" for uid in sorted(pro_users)])
    await message.reply_text(f"📊 **Pro Users:**\n\n{user_list}")

# ==================== FILE HANDLERS ====================
@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def private_file_handler(client: Client, message: Message):
    """Handle files sent directly to bot (owner/pro users only)"""
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        await message.reply_text(
            "⛔ **Access Denied!**\n\n"
            "👑 Contact owner: @FILMWORLDOFFICIA"
        )
        return
    
    LOGGER.info(f"📁 File from authorized user {user_id}")
    status_msg = await message.reply_text("⏳ **Processing...**")
    
    try:
        # Get file
        file = message.document or message.video or message.audio or message.photo
        if message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f'file_{secrets.token_hex(4)}')
        file_size = getattr(file, 'file_size', 0)
        
        # Forward to bin channel
        forwarded = await message.forward(BIN_CHANNEL)
        
        # Generate link
        link_id = generate_link_id()
        file_storage[link_id] = {
            "message_id": forwarded.id,
            "file_name": file_name,
            "file_size": file_size
        }
        
        base_url = f"https://file-to-link-5haa.onrender.com"
        download_url = f"{base_url}/download/{link_id}"
        aria2_cmd = generate_aria2_command(download_url, file_name)
        
        # Send beautiful response WITHOUT buttons
        await status_msg.edit_text(
            generate_beautiful_response(file_name, download_url, aria2_cmd)
        )
        
        LOGGER.info(f"✅ Link generated: {file_name}")
        
    except Exception as e:
        LOGGER.error(f"❌ Error: {e}")
        await status_msg.edit_text("❌ **Error processing file!**")

# ==================== CHANNEL AUTO-LINK ====================
@bot.on_message(filters.chat(BIN_CHANNEL) & (filters.document | filters.video | filters.audio | filters.photo))
async def channel_auto_link(client: Client, message: Message):
    """Auto-generate link when file is forwarded to bin channel"""
    if message.from_user and message.from_user.is_bot:
        return
    
    LOGGER.info(f"📤 Auto-link for channel file (ID: {message.id})")
    
    try:
        file = message.document or message.video or message.audio or message.photo
        if message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f'file_{secrets.token_hex(4)}')
        
        # Generate link
        link_id = generate_link_id()
        file_storage[link_id] = {
            "message_id": message.id,
            "file_name": file_name,
            "file_size": getattr(file, 'file_size', 0)
        }
        
        base_url = f"https://file-to-link-5haa.onrender.com"
        download_url = f"{base_url}/download/{link_id}"
        aria2_cmd = generate_aria2_command(download_url, file_name)
        
        # Send response to channel
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
        LOGGER.info(f"🌐 Web server running on port {PORT}")
        loop.run_forever()
    except Exception as e:
        LOGGER.error(f"Web server error: {e}")

# ==================== MAIN ====================
if __name__ == "__main__":
    LOGGER.info("="*60)
    LOGGER.info("🚀 BOT STARTING")
    LOGGER.info(f"👑 Owner: {OWNER_ID} | 📊 Pro Users: {len(pro_users)}")
    LOGGER.info("="*60)
    
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    time.sleep(2)
    
    bot.run()
