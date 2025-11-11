import os
import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChannelInvalid
from aiohttp import web
import secrets
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Your credentials
API_ID = int(os.environ.get("API_ID", 2819362))
API_HASH = os.environ.get("API_HASH", "578ce3d09fadd539544a327c45b55ee4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", -1003286196892))
PORT = int(os.environ.get("PORT", 8000))

# Storage
file_storage = {}

# Initialize Pyrogram Client
bot = Client(
    "file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4
)

def generate_link_id():
    return secrets.token_urlsafe(12)

async def store_file(link_id, message_id, file_name, file_size):
    file_storage[link_id] = {
        "message_id": message_id,
        "file_name": file_name,
        "file_size": file_size,
        "expires": datetime.now() + timedelta(hours=24)
    }

# Telegram Handlers (CRITICAL: Defined BEFORE startup)
@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    logger.info(f"✅ START FROM USER {message.from_user.id}")
    await message.reply_text(
        "🎉 **Bot is ONLINE!**\n\nSend me any file to generate a high-speed download link."
    )

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def file_handler(client, message):
    logger.info(f"📁 FILE RECEIVED from {message.from_user.id}")
    
    status_msg = await message.reply_text("⏳ Processing your file...")
    
    try:
        # Get file details
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f'file_{secrets.token_hex(4)}')
        file_size = getattr(file, 'file_size', 0)
        
        # Forward to bin channel
        forwarded = await message.forward(BIN_CHANNEL)
        
        # Generate link
        link_id = generate_link_id()
        await store_file(link_id, forwarded.id, file_name, file_size)
        
        # Create download URL
        base_url = os.environ.get("RENDER_EXTERNAL_URL", f"https://file-to-link-5haa.onrender.com")
        download_url = f"{base_url}/download/{link_id}"
        
        await status_msg.edit_text(
            f"✅ **File Ready!**\n\n"
            f"📄 **Name:** `{file_name}`\n"
            f"💾 **Size:** `{file_size / 1024 / 1024:.2f} MB`\n"
            f"🔗 **Link:** `{download_url}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Download", url=download_url)]
            ])
        )
        
        logger.info(f"🔗 Link generated: {download_url}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        await status_msg.edit_text("❌ Error processing file.")

# Aiohttp Web Server
async def homepage(request):
    return web.json_response({
        "status": "operational",
        "bot": "listening",
        "url": "https://file-to-link-5haa.onrender.com"
    })

async def health_check(request):
    return web.json_response({"status": "healthy"})

async def download_file(request):
    link_id = request.match_info['link_id']
    file_info = file_storage.get(link_id)
    
    if not file_info or datetime.now() > file_info["expires"]:
        return web.Response(status=404, text="File not found or expired")
    
    try:
        # Get message from bin channel
        message = await bot.get_messages(BIN_CHANNEL, file_info["message_id"])
        
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]
        
        # Stream file
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
        logger.error(f"❌ Stream error: {e}")
        return web.Response(status=500, text="Streaming error")

# Aiohttp App Setup
async def web_server():
    """Create and return aiohttp app"""
    app = web.Application()
    app.router.add_get('/', homepage)
    app.router.add_get('/health', health_check)
    app.router.add_get('/download/{link_id}', download_file)
    return app

# MAIN STARTUP FUNCTION (Like the Working Bot)
async def start_bot_and_server():
    """
    EXACT pattern from Auto_Filter_Bot-DreamXBotz:
    1. Start and bind web server FIRST
    2. Call idle() AFTER server is live
    """
    
    logger.info("="*60)
    logger.info("🚀 Starting Bot and Web Server...")
    logger.info("="*60)
    
    # STEP 1: Start web server (this completes BEFORE idle)
    logger.info(f"🌐 Starting aiohttp web server on port {PORT}...")
    runner = web.AppRunner(await web_server())
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Web server is LIVE at https://file-to-link-5haa.onrender.com")
    
    # STEP 2: Start Pyrogram bot
    logger.info("🤖 Starting Pyrogram bot...")
    await bot.start()
    logger.info("✅ Pyrogram bot started and listening for messages")
    
    # STEP 3: Call idle() ONLY after both are running
    logger.info("⏳ Bot is now idle and processing updates...")
    await idle()
    
    # Cleanup on shutdown
    await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(start_bot_and_server())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
