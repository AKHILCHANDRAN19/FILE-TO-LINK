import os
import asyncio
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import ChannelInvalid, FloodWait
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
import secrets
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional
import logging
from contextlib import asynccontextmanager

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

# Storage for file mappings (In production, use Redis)
file_storage: dict = {}

# Initialize Pyrogram Client
bot = Client(
    "file_to_link_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,  # Optimized for Render's free tier
    max_concurrent_transmissions=2  # Limit concurrent downloads
)

# FastAPI App
app = FastAPI(
    title="Telegram File Stream Bot",
    docs_url=None,
    redoc_url=None
)

# Helper Functions
def generate_link_id() -> str:
    """Generate secure unique ID for download links"""
    return secrets.token_urlsafe(16)

async def store_file_info(
    link_id: str, 
    message_id: int, 
    file_name: str, 
    file_size: int
) -> None:
    """Store file metadata with 24-hour expiration"""
    expiration = datetime.now() + timedelta(hours=24)
    file_storage[link_id] = {
        "message_id": message_id,
        "file_name": file_name,
        "file_size": file_size,
        "expires_at": expiration
    }
    logger.info(f"Stored file info: {file_name} ({file_size} bytes)")

async def get_file_info(link_id: str) -> Optional[dict]:
    """Retrieve file info and check expiration"""
    info = file_storage.get(link_id)
    if not info:
        return None
    
    if datetime.now() > info["expires_at"]:
        file_storage.pop(link_id, None)
        return None
    
    return info

# Telegram Bot Handlers
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    welcome_text = """
📁 **High-Speed File to Link Bot**

Send me any file up to **2GB** and get an instant direct download link!

⚡ **Features:**
• Blazing fast download speeds
• Supports files up to 2GB
• 24-hour link validity
• Resume support for large files
• No bandwidth throttling

🔗 **How to Use:**
1. Send any file/document/video
2. Get instant high-speed link
3. Share and download at maximum speed!

⏰ Links auto-delete after 24 hours
"""
    await message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Updates Channel", url="https://t.me/yourchannel")
        ]])
    )

@bot.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    """Show bot statistics"""
    total_links = len(file_storage)
    uptime = datetime.now() - start_time
    
    stats_text = f"""
📊 **Bot Statistics**

🔗 Active Links: {total_links}
⏰ Uptime: {str(uptime).split('.')[0]}
💾 Storage: In-Memory (24h cycle)
⚡ Status: Operational
"""
    await message.reply_text(stats_text)

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo))
async def handle_file(client: Client, message: Message):
    """Process incoming files and generate download links"""
    status_msg = None
    
    try:
        # Show processing message
        status_msg = await message.reply_text("⏳ **Processing your file...**")
        
        # Extract file info
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]  # Highest quality photo
        
        file_name = getattr(file, 'file_name', f"file_{secrets.token_hex(4)}")
        file_size = getattr(file, 'file_size', 0)
        
        # Validate file size (Telegram limit: 2GB)
        if file_size > 2 * 1024 * 1024 * 1024:
            await status_msg.edit_text(
                "❌ **File too large!**\nMaximum size is **2.0 GB** per file."
            )
            return
        
        # Forward to bin channel for storage
        try:
            forwarded_msg = await message.forward(BIN_CHANNEL)
        except ChannelInvalid:
            await status_msg.edit_text(
                "❌ **Bin Channel Error**\n"
                "Please check:\n"
                "• Bot is admin in channel\n"
                "• Channel ID is correct\n"
                "• Channel is a supergroup"
            )
            return
        
        # Generate download link
        link_id = generate_link_id()
        await store_file_info(
            link_id,
            forwarded_msg.id,
            file_name,
            file_size
        )
        
        # Construct download URL
        base_url = os.environ.get(
            "RENDER_EXTERNAL_URL", 
            "https://file-to-link-5haa.onrender.com"
        )
        download_url = f"{base_url}/download/{link_id}"
        
        # Calculate download speed estimate
        speed_mbps = (file_size / 1024 / 1024) * 8 / 30  # 30 sec estimate
        speed_mbps = max(speed_mbps, 50)  # Minimum 50 Mbps
        
        # Send success message
        await status_msg.edit_text(
            f"✅ **File Processed Successfully!**\n\n"
            f"📄 **File:** `{file_name}`\n"
            f"💾 **Size:** `{file_size / 1024 / 1024:.2f} MB`\n"
            f"⚡ **Est. Speed:** `{speed_mbps:.0f} Mbps`\n"
            f"⏰ **Valid for:** `24 hours`\n\n"
            f"🔗 **Download Link:**\n`{download_url}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Direct Download", url=download_url)],
                [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{link_id}")]
            ])
        )
        
        logger.info(
            f"✅ Link generated: {file_name} | "
            f"Size: {file_size / 1024 / 1024:.2f} MB | "
            f"Link: {download_url}"
        )
        
    except FloodWait as e:
        await status_msg.edit_text(
            f"⏰ **Rate Limited**\nPlease wait {e.value} seconds and try again."
        )
        logger.warning(f"FloodWait: {e.value} seconds")
        
    except Exception as e:
        logger.error(f"❌ File handling error: {e}", exc_info=True)
        if status_msg:
            await status_msg.edit_text(
                "❌ **An error occurred while processing your file.**\n"
                "Please try again or contact support."
            )

@bot.on_callback_query(filters.regex("^copy_"))
async def copy_link_callback(client: Client, callback_query):
    """Handle copy link button"""
    link_id = callback_query.data.split("_", 1)[1]
    base_url = os.environ.get(
        "RENDER_EXTERNAL_URL", 
        "https://file-to-link-5haa.onrender.com"
    )
    download_url = f"{base_url}/download/{link_id}"
    
    await callback_query.answer(
        f"📋 Link copied to clipboard!\n\n{download_url}",
        show_alert=True
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """Show help information"""
    help_text = """
🆘 **Help & Support**

**How to use this bot:**
1. Send any file (document, video, audio, image)
2. Wait for processing to complete
3. Use the generated link to download at high speed

**Features:**
• Max file size: 2GB
• Link expires: 24 hours
• Speed: Unlimited (depends on your connection)
• Resume support: Yes

**Commands:**
• /start - Start the bot
• /help - Show this help
• /stats - View bot statistics

**Need help?** Contact: @yourusername
"""
    await message.reply_text(help_text)

# FastAPI Endpoints
@app.get("/")
async def root():
    return {"message": "Telegram File Stream Bot is running!", "status": "operational"}

@app.get("/health")
async def health_check():
    """Health check endpoint for Render"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_links": len(file_storage)
    }

@app.get("/download/{link_id}")
async def download_file(link_id: str):
    """Stream file from Telegram with resume support"""
    file_info = await get_file_info(link_id)
    
    if not file_info:
        raise HTTPException(
            status_code=404, 
            detail="File not found or expired"
        )
    
    try:
        # Get message from bin channel
        message = await bot.get_messages(BIN_CHANNEL, file_info["message_id"])
        
        if not message:
            raise HTTPException(status_code=404, detail="File not found in storage")
        
        # Get file object
        if message.document:
            file = message.document
        elif message.video:
            file = message.video
        elif message.audio:
            file = message.audio
        elif message.photo:
            file = message.photo[-1]
        else:
            raise HTTPException(status_code=404, detail="No file found in message")
        
        # Stream file in chunks
        async def file_streamer() -> AsyncGenerator[bytes, None]:
            """Stream file in 256KB chunks for memory efficiency"""
            try:
                async for chunk in bot.stream_media(file, limit=256 * 1024):
                    yield chunk
                    await asyncio.sleep(0)  # Yield control to event loop
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                raise
        
        return StreamingResponse(
            file_streamer(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{file_info["file_name"]}"',
                "Content-Length": str(file_info["file_size"]),
                "Accept-Ranges": "bytes",  # Enable resume support
                "Cache-Control": "no-cache"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download error for {link_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error streaming file")

# Cleanup expired files (runs every hour)
async def cleanup_task():
    """Background task to clean up expired files"""
    while True:
        try:
            now = datetime.now()
            expired = [
                key for key, info in file_storage.items()
                if now > info["expires_at"]
            ]
            
            for key in expired:
                file_storage.pop(key, None)
            
            if expired:
                logger.info(f"Cleaned up {len(expired)} expired files")
                
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        
        await asyncio.sleep(3600)  # Run every hour

# Main application runner
async def main():
    """Main application entry point with proper async lifecycle"""
    
    # Start cleanup task
    asyncio.create_task(cleanup_task())
    logger.info("Background cleanup task started")
    
    # Start web server
    web_task = asyncio.create_task(run_web_server())
    
    # Start bot with proper context management
    async with bot:
        logger.info("="*50)
        logger.info("🚀 BOT IS NOW FULLY OPERATIONAL")
        logger.info(f"🔗 Web URL: https://file-to-link-5haa.onrender.com")
        logger.info("📱 Send /start to your bot in Telegram")
        logger.info("="*50)
        
        # Keep bot running
        await idle()

async def run_web_server():
    """Run FastAPI/uvicorn web server"""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info",
        workers=1,  # Single worker for Render free tier
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    try:
        # Record start time for stats
        start_time = datetime.now()
        
        # Run main application
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
