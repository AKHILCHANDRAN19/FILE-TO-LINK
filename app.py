import os
import threading
import asyncio
import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import secrets
import logging

# Configure logging to see EVERYTHING
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Your credentials from render.yaml
API_ID = int(os.environ.get("API_ID", 2819362))
API_HASH = os.environ.get("API_HASH", "578ce3d09fadd539544a327c45b55ee4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", -1003286196892))
PORT = int(os.environ.get("PORT", 8000))

# Storage for files
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
    """Generate secure unique link ID"""
    return secrets.token_urlsafe(12)

# CRITICAL: Define handlers BEFORE starting bot

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    """Handle /start command"""
    logger.info(f"✅✅✅ START COMMAND RECEIVED FROM USER {message.from_user.id} ✅✅✅")
    await message.reply_text(
        "🎉 **BOT IS FULLY OPERATIONAL!**\n\n"
        "Send me any file up to 2GB and I'll generate a direct download link."
    )

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def file_handler(client, message):
    """Handle incoming files"""
    logger.info(f"✅✅✅ FILE RECEIVED FROM USER {message.from_user.id} ✅✅✅")
    
    status_msg = await message.reply_text("⏳ Processing your file...")
    
    try:
        # Get file object
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]  # Highest quality
        
        file_name = getattr(file, 'file_name', f'file_{secrets.token_hex(4)}')
        file_size = getattr(file, 'file_size', 0)
        
        # Forward to bin channel
        forwarded = await message.forward(BIN_CHANNEL)
        
        # Generate download link
        link_id = generate_link_id()
        file_storage[link_id] = {
            "message_id": forwarded.id,
            "file_name": file_name,
            "file_size": file_size
        }
        
        # Create download URL
        base_url = f"https://file-to-link-5haa.onrender.com"
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
        logger.error(f"❌ Error processing file: {e}")
        await status_msg.edit_text("❌ Error processing file.")

# Aiohttp Web Handlers
async def homepage(request):
    """Homepage endpoint"""
    return web.json_response({
        "status": "operational",
        "bot": "listening for messages",
        "service": "Telegram File to Link Bot"
    })

async def health_check(request):
    """Health check for Render"""
    return web.json_response({"status": "healthy"})

async def download_file(request):
    """Stream file from Telegram"""
    link_id = request.match_info['link_id']
    file_info = file_storage.get(link_id)
    
    if not file_info:
        return web.Response(status=404, text="File not found or expired")
    
    try:
        # Get message from bin channel
        message = await bot.get_messages(BIN_CHANNEL, file_info["message_id"])
        
        # Get file object
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]
        
        # Start streaming response
        response = web.StreamResponse(
            status=200,
            headers={
                'Content-Disposition': f'attachment; filename="{file_info["file_name"]}"',
                'Content-Length': str(file_info["file_size"]),
                'Content-Type': 'application/octet-stream',
                'Accept-Ranges': 'bytes',
            }
        )
        await response.prepare(request)
        
        # Stream in chunks (256KB for memory efficiency)
        async for chunk in bot.stream_media(file, limit=256 * 1024):
            await response.write(chunk)
        
        await response.write_eof()
        return response
        
    except Exception as e:
        logger.error(f"❌ Streaming error: {e}")
        return web.Response(status=500, text="Error streaming file")

def create_web_app():
    """Create aiohttp application"""
    app = web.Application()
    app.router.add_get('/', homepage)
    app.router.add_get('/health', health_check)
    app.router.add_get('/download/{link_id}', download_file)
    return app

# Web Server Thread (daemon keeps it alive)
def run_web_server():
    """Run web server in a separate daemon thread"""
    try:
        logger.info(f"🌐 Starting aiohttp web server on port {PORT}...")
        
        # Create event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Setup and start server
        app = create_web_app()
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        loop.run_until_complete(site.start())
        
        logger.info(f"✅ Web server is LIVE at https://file-to-link-5haa.onrender.com")
        
        # Keep thread running
        loop.run_forever()
        
    except Exception as e:
        logger.error(f"❌ Web server failed to start: {e}")

# MAIN ENTRY POINT
if __name__ == "__main__":
    logger.info("="*60)
    logger.info("🚀 INITIALIZING BOT AND WEB SERVER")
    logger.info("="*60)
    
    # Start web server in background thread
    logger.info("🔄 Starting web server in background thread...")
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Give web server a moment to start
    time.sleep(2)
    
    logger.info("🤖 Starting Pyrogram bot in MAIN THREAD...")
    logger.info("📡 Bot is connecting to Telegram and listening for updates...")
    
    # Run bot - THIS IS THE KEY: bot.run() manages its own event loop
    bot.run()
    
    logger.info("👋 Bot has stopped. Exiting...")
