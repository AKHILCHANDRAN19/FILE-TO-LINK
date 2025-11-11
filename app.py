import os
import asyncio
import aiohttp
import uvicorn
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors.exceptions.bad_request_400 import ChannelInvalid
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Optional, Dict
import secrets
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Your credentials
API_ID = 2819362
API_HASH = "578ce3d09fadd539544a327c45b55ee4"
BOT_TOKEN = "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8"
BIN_CHANNEL = -1003286196892

# Storage for file mappings (in production, use Redis)
file_storage: Dict[str, dict] = {}

# Initialize Pyrogram Client
bot = Client(
    "file_to_link_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    workers=4  # Optimize for Render's limited resources
)

# Initialize FastAPI app
app = FastAPI(
    title="Telegram File Stream Bot",
    docs_url=None,  # Disable docs for security
    redoc_url=None
)

# Helper functions
def generate_unique_id() -> str:
    """Generate a secure unique ID for file links"""
    return secrets.token_urlsafe(16)

async def get_file_info(file_id: str) -> Optional[dict]:
    """Retrieve file information from storage"""
    return file_storage.get(file_id)

async def store_file_info(file_id: str, message_id: int, file_name: str, file_size: int):
    """Store file information with expiration (24 hours)"""
    expiration = datetime.now() + timedelta(hours=24)
    file_storage[file_id] = {
        "message_id": message_id,
        "file_name": file_name,
        "file_size": file_size,
        "expires_at": expiration
    }

# Telegram Bot Handlers
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Handle start command"""
    welcome_text = """
📁 **File to Link Bot**

Send me any file and I'll generate a high-speed direct download link!

✨ **Features:**
• Supports files up to 2GB
• High-speed streaming downloads
• 24-hour link validity
• No file size limits on download

🔗 **How to use:**
1. Send any file/document
2. Get instant download link
3. Share and download at high speed!
"""
    await message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Updates", url="https://t.me/yourchannel")
        ]])
    )

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    """Show bot statistics"""
    total_files = len(file_storage)
    await message.reply_text(f"📊 **Statistics**\n\nTotal active links: {total_files}")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def handle_file(client: Client, message: Message):
    """Handle incoming files and generate download links"""
    try:
        # Show processing status
        status_msg = await message.reply_text("⏳ Processing your file...")
        
        # Get file details
        file = message.document or message.video or message.audio or message.photo
        
        # For photos, get the highest quality
        if message.photo:
            file = message.photo[-1]
        
        file_name = getattr(file, 'file_name', f"file_{file.file_unique_id}")
        file_size = getattr(file, 'file_size', 0)
        
        # Check file size (Telegram bot limit is 2GB = 2*1024*1024*1024 bytes)
        if file_size > 2 * 1024 * 1024 * 1024:
            await status_msg.edit_text("❌ File too large! Maximum size is 2GB.")
            return
        
        # Forward to bin channel
        try:
            forwarded_msg = await message.forward(BIN_CHANNEL)
        except ChannelInvalid:
            await status_msg.edit_text("❌ Bin channel is invalid. Please check the channel ID and bot permissions.")
            return
        except Exception as e:
            logger.error(f"Failed to forward message: {e}")
            await status_msg.edit_text("❌ Failed to store file. Please try again.")
            return
        
        # Generate unique link
        unique_id = generate_unique_id()
        await store_file_info(
            unique_id,
            forwarded_msg.id,
            file_name,
            file_size
        )
        
        # Construct download URL (use your Render URL)
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
        download_url = f"{base_url}/download/{unique_id}"
        
        # Send success message with buttons
        await status_msg.edit_text(
            f"✅ **File Ready!**\n\n"
            f"📄 **File:** {file_name}\n"
            f"💾 **Size:** {file_size / (1024*1024):.2f} MB\n"
            f"⏰ **Valid for:** 24 hours\n\n"
            f"🔗 **Download Link:** `{download_url}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Download", url=download_url)],
                [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{unique_id}")]
            ])
        )
        
        logger.info(f"Generated link for file: {file_name} (Size: {file_size})")
        
    except Exception as e:
        logger.error(f"Error handling file: {e}", exc_info=True)
        try:
            await status_msg.edit_text("❌ An error occurred while processing your file.")
        except:
            await message.reply_text("❌ An error occurred while processing your file.")

@bot.on_callback_query(filters.regex("^copy_"))
async def copy_link(client: Client, callback_query):
    """Copy link to clipboard (just shows alert)"""
    unique_id = callback_query.data.split("_", 1)[1]
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")
    download_url = f"{base_url}/download/{unique_id}"
    
    await callback_query.answer(
        f"Link copied to clipboard!\n\n{download_url}",
        show_alert=True
    )

# Web Server for File Streaming
@app.get("/")
async def root():
    return {"message": "Telegram File Stream Bot is running!"}

@app.get("/download/{file_id}")
async def download_file(file_id: str):
    """Stream file from Telegram to client"""
    file_info = await get_file_info(file_id)
    
    if not file_info:
        raise HTTPException(status_code=404, detail="File not found or expired")
    
    # Check expiration
    if datetime.now() > file_info["expires_at"]:
        # Clean up expired file
        file_storage.pop(file_id, None)
        raise HTTPException(status_code=410, detail="Link has expired")
    
    try:
        # Stream file from Telegram
        return StreamingResponse(
            stream_from_telegram(file_info),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{file_info["file_name"]}"',
                "Content-Length": str(file_info["file_size"]),
            }
        )
    except Exception as e:
        logger.error(f"Error streaming file {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Error streaming file")

async def stream_from_telegram(file_info: dict) -> AsyncGenerator[bytes, None]:
    """Stream file from Telegram in chunks"""
    message_id = file_info["message_id"]
    
    try:
        # Get message from bin channel
        message = await bot.get_messages(BIN_CHANNEL, message_id)
        
        if not message or not (message.document or message.video or message.audio or message.photo):
            raise Exception("File not found in storage channel")
        
        # Get the file object
        file = message.document or message.video or message.audio or message.photo
        
        # For photos, get the highest quality
        if message.photo:
            file = message.photo[-1]
        
        # Stream file in chunks (256KB chunks for optimal memory usage)
        chunk_size = 256 * 1024
        
        # Use Pyrogram's stream_media method for efficient downloading
        async for chunk in bot.stream_media(file, limit=chunk_size):
            yield chunk
            await asyncio.sleep(0)  # Allow other tasks to run
            
    except Exception as e:
        logger.error(f"Error in stream_from_telegram: {e}")
        raise

# Cleanup expired files
async def cleanup_expired_files():
    """Periodic cleanup of expired file links"""
    while True:
        try:
            now = datetime.now()
            expired_keys = [
                key for key, info in file_storage.items()
                if now > info["expires_at"]
            ]
            
            for key in expired_keys:
                file_storage.pop(key, None)
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired files")
            
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")
        
        # Run cleanup every hour
        await asyncio.sleep(3600)

# Health check endpoint for Render
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Startup event
@app.on_event("startup")
async def startup_event():
    """Start background tasks when web server starts"""
    asyncio.create_task(cleanup_expired_files())
    logger.info("Bot and web server started successfully")

# Combine bot and web server
async def run_bot():
    """Run Pyrogram bot"""
    await bot.start()
    logger.info("Pyrogram bot started")
    await asyncio.Event().wait()  # Keep bot running

async def run_web():
    """Run FastAPI web server"""
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        workers=1  # Use single worker for Render free tier
    )
    
    server = uvicorn.Server(config)
    await server.serve()

# Main entry point
if __name__ == "__main__":
    # Start both bot and web server concurrently
    async def main():
        await asyncio.gather(
            run_bot(),
            run_web()
        )
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down bot...")
        bot.stop()
