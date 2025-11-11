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

# Your credentials
API_ID = int(os.environ.get("API_ID", 2819362))
API_HASH = os.environ.get("API_HASH", "578ce3d09fadd539544a327c45b55ee4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", -1003286196892))

# Storage
file_storage = {}
start_time = datetime.now()

# Initialize Pyrogram Client
bot = Client(
    "file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    max_concurrent_transmissions=2  # Prevent overload
)

# FastAPI App
app = FastAPI(
    title="Telegram File Stream Bot",
    docs_url=None,
    redoc_url=None
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

# Telegram Handlers
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
        
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://file-to-link-5haa.onrender.com")
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

# FastAPI Endpoints
@app.get("/")
async def root():
    return {"status": "operational", "bot": "listening"}

@app.get("/download/{link_id}")
async def download(link_id: str):
    file_info = file_storage.get(link_id)
    
    if not file_info or datetime.now() > file_info["expires"]:
        raise HTTPException(status_code=404, detail="File expired")
    
    try:
        message = await bot.get_messages(BIN_CHANNEL, file_info["message_id"])
        
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]
        
        async def stream():
            async for chunk in bot.stream_media(file, limit=256*1024):
                yield chunk
        
        return StreamingResponse(
            stream(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{file_info["file_name"]}"',
                "Content-Length": str(file_info["file_size"]),
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Stream error: {e}")
        raise HTTPException(status_code=500, detail="Streaming failed")

# PROPER ASYNC STRUCTURE - THE KEY FIX
async def main():
    """Run bot and web server concurrently without blocking"""
    
    # Start web server in background
    web_task = asyncio.create_task(run_web_server())
    logger.info("🌐 Web server task created")
    
    # Run bot with proper lifecycle
    async with bot:
        logger.info("🤖 Bot context entered - now listening")
        logger.info("="*50)
        logger.info("🔥 BOT IS ACTIVE - SEND /start NOW")
        logger.info("="*50)
        
        # Keep bot running and listening
        await idle()

async def run_web_server():
    """Run FastAPI server"""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info",
        workers=1  # Critical: 1 worker for async compatibility
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    print("🚀 Starting application...")
    asyncio.run(main())
