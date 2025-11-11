import os
import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChannelInvalid
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn
import secrets
from datetime import datetime, timedelta
from typing import AsyncGenerator
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Your credentials (unchanged)
API_ID = int(os.environ.get("API_ID", 2819362))
API_HASH = os.environ.get("API_HASH", "578ce3d09fadd539544a327c45b55ee4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", -1003286196892))

# Storage (unchanged)
file_storage = {}
start_time = datetime.now()

# Initialize Pyrogram Client (unchanged)
bot = Client(
    "file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    max_concurrent_transmissions=2  # Prevent overload
)

# FastAPI App (unchanged)
app = FastAPI(
    title="Telegram File Stream Bot",
    docs_url=None,
    redoc_url=None
)

# Helper Functions (unchanged)
def generate_link_id():
    return secrets.token_urlsafe(12)

async def store_file(link_id, message_id, file_name, file_size):
    file_storage[link_id] = {
        "message_id": message_id,
        "file_name": file_name,
        "file_size": file_size,
        "expires": datetime.now() + timedelta(hours=24)
    }

# Telegram Handlers (unchanged)
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    logger.info(f"✅ START COMMAND from {message.from_user.id}")
    await message.reply_text("🚀 Bot is ONLINE! Send me any file.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def handle_file(client, message):
    logger.info(f"📁 FILE RECEIVED from {message.from_user.id}")
    
    status_msg = await message.reply_text("⏳ Processing...")
    
    try:
        # Get file info
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f"file_{secrets.token_hex(4)}")
        file_size = getattr(file, 'file_size', 0)
        
        # Forward to bin channel
        forwarded = await message.forward(BIN_CHANNEL)
        
        # Generate link
        link_id = generate_link_id()
        await store_file(link_id, forwarded.id, file_name, file_size)
        
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://your-render-app-name.onrender.com")
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

# FastAPI Endpoints (unchanged)
@app.get("/")
async def root():
    return {"status": "operational", "bot": "listening"}

@app.get("/download/{link_id}")
async def download(link_id: str):
    file_info = file_storage.get(link_id)
    
    if not file_info or datetime.now() > file_info["expires"]:
        raise HTTPException(status_code=404, detail="File expired or not found")
    
    try:
        # This part remains the same as your original logic
        async def stream_generator():
            async for chunk in bot.stream_media(
                message=await bot.get_messages(BIN_CHANNEL, file_info["message_id"]),
                limit=256*1024
            ):
                yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{file_info["file_name"]}"',
                "Content-Length": str(file_info["file_size"]),
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Stream error: {e}")
        raise HTTPException(status_code=500, detail="Streaming failed")

# --- NEW PRODUCTION-READY STARTUP LOGIC ---

async def run_bot():
    """Run the Pyrogram bot in the background."""
    async with bot:
        logger.info("="*50)
        logger.info("🔥 BOT IS ACTIVE - LISTENING FOR MESSAGES")
        logger.info("="*50)
        await idle()

@app.on_event("startup")
async def startup_event():
    """Create a background task to run the bot when the web server starts."""
    logger.info("🚀 Web server started. Initializing bot in the background...")
    asyncio.create_task(run_bot())
    logger.info("🤖 Bot startup task has been created.")

@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully stop the bot when the web server shuts down."""
    logger.info("🛑 Web server is shutting down. Stopping bot...")
    await bot.stop()
