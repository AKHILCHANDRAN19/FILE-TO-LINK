import os
import threading
import asyncio
import time
import re
import tempfile
import subprocess
import shutil
import math
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    CallbackQuery, 
    InputMediaPhoto
)
from aiohttp import web, ClientSession
import aiohttp
import secrets
import logging

# ==================== CONFIGURATION ====================
API_ID = int(os.environ.get("API_ID", 2819362))
API_HASH = os.environ.get("API_HASH", "578ce3d09fadd539544a327c45b55ee4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8203006611:AAHJf1Dc5jjIiPW0--AGgbUfK8H-QgVamt8")
BIN_CHANNEL = int(os.environ.get("BIN_CHANNEL", -1001854240817))
PORT = int(os.environ.get("PORT", 8000))
OWNER_ID = int(os.environ.get("OWNER_ID", 6219290068))
PRO_USERS_FILE = "pro_users.txt"
REPO_STICKER_ID = "CAACAgUAAxkBAAE9tahpE-Oz4dCOfweAKQE_KU3zO6YzKgACMQADsx6IFV2DVIFED1oBNgQ"
THUMBNAIL_FILE_ID = "AgACAgUAAxkBAAE9vJdpFKHL4lIezMqiAhL4U86UBU9HFAACcg5rGxoHoVRR8Xe3Z3RrUwEAAwIAA3gAAzYE"

file_storage = {}
pro_users = set()
start_time = datetime.now()
thumbnail_path = None

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

def format_file_size(bytes_val):
    if bytes_val == 0:
        return "0 B"
    sizes = ['B', 'KB', 'MB', 'GB']
    i = int(math.floor(math.log(bytes_val, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_val / p, 2)
    return f"{s} {sizes[i]}"

def format_duration(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds/60)}m {int(seconds%60)}s"
    else:
        hours = int(seconds/3600)
        minutes = int((seconds%3600)/60)
        return f"{hours}h {minutes}m"

def create_progress_bar(percentage, length=20):
    filled = int(length * percentage / 100)
    return "█" * filled + "░" * (length - filled)

def format_speed(bps):
    if bps > 10**6:
        return f"{bps/10**6:.1f} MB/s"
    elif bps > 10**3:
        return f"{bps/10**3:.1f} KB/s"
    else:
        return f"{bps:.0f} B/s"

class ProgressTracker:
    def __init__(self, message: Message, file_name: str, operation_name: str):
        self.message = message
        self.file_name = file_name
        self.operation_name = operation_name
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.last_current = 0
    
    async def callback(self, current: int, total: int):
        current_time = time.time()
        if current_time - self.last_update_time < 0.5:
            return
        
        percentage = (current / total) * 100
        speed = (current - self.last_current) / (current_time - self.last_update_time)
        eta = (total - current) / speed if speed > 0 else 0
        
        progress_bar = create_progress_bar(percentage)
        progress_text = (
            f"{self.operation_name}\n\n"
            f"📄 **File:** `{self.file_name}`\n"
            f"{progress_bar} `{percentage:.1f}%`\n\n"
            f"💾 **Size:** `{format_file_size(current)}/{format_file_size(total)}`\n"
            f"⚡ **Speed:** `{format_speed(speed)}`\n"
            f"⏱️ **ETA:** `{format_duration(eta)}`"
        )
        
        try:
            await self.message.edit_text(progress_text)
        except:
            pass
        
        self.last_update_time = current_time
        self.last_current = current

async def get_thumbnail(client: Client):
    global thumbnail_path
    if thumbnail_path and os.path.exists(thumbnail_path):
        return thumbnail_path
    
    temp_dir = tempfile.gettempdir()
    thumbnail_path = os.path.join(temp_dir, "custom_thumbnail.jpg")
    
    try:
        await client.download_media(THUMBNAIL_FILE_ID, file_name=thumbnail_path)
        LOGGER.info(f"Thumbnail cached to {thumbnail_path}")
        return thumbnail_path
    except Exception as e:
        LOGGER.error(f"Thumbnail download error: {e}")
        return None

async def download_with_progress(url: str, file_path: str, status_msg: Message, file_name: str):
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=30, sock_connect=30)
    connector = aiohttp.TCPConnector(
        limit=16,
        ttl_dns_cache=300,
        use_dns_cache=True,
        enable_cleanup_closed=True
    )
    
    async with ClientSession(connector=connector, timeout=timeout) as session:
        async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}: Failed to fetch URL")
            
            total_size = int(response.headers.get('content-length', 0))
            if total_size == 0:
                raise Exception("Could not determine file size")
            
            downloaded = 0
            start_time = time.time()
            last_update_time = time.time()
            
            with open(file_path, 'wb') as f:
                async for chunk in response.content.iter_chunked(512*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        current_time = time.time()
                        if current_time - last_update_time >= 0.5:
                            percentage = (downloaded / total_size) * 100
                            speed = downloaded / (current_time - start_time)
                            eta = (total_size - downloaded) / speed if speed > 0 else 0
                            
                            progress_bar = create_progress_bar(percentage)
                            progress_text = (
                                f"📥 **Downloading:**\n\n"
                                f"📄 **File:** `{file_name}`\n"
                                f"{progress_bar} `{percentage:.1f}%`\n\n"
                                f"💾 **Size:** `{format_file_size(downloaded)}/{format_file_size(total_size)}`\n"
                                f"⚡ **Speed:** `{format_speed(speed)}`\n"
                                f"⏱️ **ETA:** `{format_duration(eta)}`"
                            )
                            await status_msg.edit_text(progress_text)
                            last_update_time = current_time
            
            final_text = (
                f"✅ **Download Complete!**\n\n"
                f"📂 **File:** `{file_name}`\n"
                f"💾 **Size:** `{format_file_size(total_size)}`"
            )
            await status_msg.edit_text(final_text)

def generate_screenshots(video_path: str, output_dir: str, file_name: str):
    try:
        duration_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        duration = float(subprocess.check_output(duration_cmd, shell=True).decode().strip())
        
        screenshot_times = [duration * (i+1)/10 for i in range(8)]
        screenshot_paths = []
        
        for i, timestamp in enumerate(screenshot_times):
            ss_path = os.path.join(output_dir, f"ss_{i+1:03d}.jpg")
            cmd = f'ffmpeg -ss {timestamp} -i "{video_path}" -frames:v 1 -q:v 1 -vf "scale=1280:-1" "{ss_path}" -y'
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            screenshot_paths.append(ss_path)
        
        return screenshot_paths
    except Exception as e:
        LOGGER.error(f"Screenshot generation error: {e}")
        raise Exception(f"Failed to generate screenshots: {str(e)}")

def detect_video_file(file_path: str) -> bool:
    """Detect if file is video using ffprobe"""
    try:
        cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{file_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and float(result.stdout.strip()) > 0
    except:
        return False

# ==================== COMMAND HANDLERS ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user = message.from_user
    
    welcome_text = (
        f"👋 **Welcome {user.first_name}!**\n\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"✅ **Status:** `{'Authorized ✓' if is_authorized(user.id) else 'Not Authorized ✗'}`\n\n"
        f"📤 **Send any file** to generate download link\n\n"
        f"🌐 **URL Upload:** Send direct link or use `/uploadurl <link>` (Max 2GB)\n\n"
        f"📣 **Channel:** Forward files to bin channel for auto-links\n\n"
        f"💡 **Max Size:** 4GB per file | 2GB per URL\n"
        f"⏰ **Link Duration:** 24 hours"
    )
    
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
        "**Auto URL Detection:**\n   Just send a direct download link\n\n"
        "**Manual Command:**\n   `/uploadurl <direct_link>`\n\n"
        "**Features:**\n"
        "✓ Auto-detects URLs in messages\n"
        "✓ Auto-detects video files (even without extension)\n"
        "✓ Max speed downloads\n"
        "✓ 8 screenshots for videos\n"
        "✓ Custom thumbnail support\n"
        "✓ 2GB per URL limit"
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

# ==================== URL DETECTION & PROCESSING ====================
URL_PATTERN = re.compile(r'https?://[^\s]+')

@bot.on_message(filters.private & filters.text & filters.regex(URL_PATTERN) & ~filters.command())
async def auto_url_handler(client: Client, message: Message):
    """Automatically detect and process URLs in messages"""
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        await message.reply_text("⛔ **Access Denied!**\n\n👑 Contact owner: @FILMWORLDOFFICIA")
        return
    
    url_match = URL_PATTERN.search(message.text)
    if not url_match:
        return
    
    url = url_match.group(0)
    
    if any(url.startswith(cmd) for cmd in ['/start', '/help', '/uploadurl', '/stats', '/adduser', '/removeuser', '/listusers', '/broadcast', '/id']):
        return
    
    file_name = url.split('/')[-1].split('?')[0] or f"file_{secrets.token_hex(4)}"
    file_name = re.sub(r'[^\w\-.]', '_', file_name)
    
    video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.mpeg', '.ts']
    has_video_extension = any(file_name.lower().endswith(ext) for ext in video_extensions)
    
    ffmpeg_available = True
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=10)
    except:
        ffmpeg_available = False
    
    mode_text = (
        f"📥 **URL Detected:** `{file_name}`\n\n"
        f"🎬 **Video Extension:** `{'Yes' if has_video_extension else 'No (Will Auto-Detect)'}`\n\n"
        f"**How would you like to upload this?**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📄 As File", callback_data=f"upload_mode|file|{url}|{file_name}|0"),
            InlineKeyboardButton("🎬 As Video", callback_data=f"upload_mode|video|{url}|{file_name}|{int(has_video_extension)}")
        ]
    ])
    
    await message.reply_text(mode_text, reply_markup=keyboard)

# ==================== CALLBACK HANDLER FOR UPLOAD MODE ====================
@bot.on_callback_query(filters.regex("^upload_mode"))
async def upload_mode_callback(client: Client, query: CallbackQuery):
    await query.answer()
    
    data = query.data.split('|', 4)
    if len(data) != 5:
        await query.message.edit_text("❌ Invalid selection data")
        return
    
    mode = data[1]
    url = data[2]
    file_name = data[3]
    has_video_extension = bool(int(data[4]))
    
    await query.message.edit_text("⏳ **Preparing upload...**")
    
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        file_path = os.path.join(temp_dir, file_name)
        
        await download_with_progress(url, file_path, query.message, file_name)
        
        file_size = os.path.getsize(file_path)
        if file_size > 2 * 1024 * 1024 * 1024:
            await query.message.edit_text("❌ **File size exceeds 2GB limit!**")
            return
        
        is_video = has_video_extension
        if not has_video_extension and detect_video_file(file_path):
            is_video = True
            await query.message.reply_text("🎬 **Auto-detected as video file!**")
        
        ffmpeg_available = True
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=10)
        except:
            ffmpeg_available = False
        
        if is_video and ffmpeg_available:
            await query.message.edit_text("📸 **Generating 8 screenshots...**")
            screenshots_dir = os.path.join(temp_dir, "screenshots")
            os.makedirs(screenshots_dir)
            
            try:
                screenshot_paths = generate_screenshots(file_path, screenshots_dir, file_name)
                
                if screenshot_paths:
                    media_group = []
                    for idx, ss_path in enumerate(screenshot_paths):
                        if os.path.exists(ss_path):
                            media_group.append(
                                InputMediaPhoto(
                                    media=ss_path,
                                    caption=f"📸 Screenshot {idx+1}/8"
                                )
                            )
                    
                    if media_group:
                        await client.send_media_group(
                            chat_id=query.message.chat.id,
                            media=media_group
                        )
            except Exception as e:
                LOGGER.error(f"Screenshot error: {e}")
                await query.message.reply_text("⚠️ **Failed to generate screenshots**")
        
        await query.message.edit_text(f"📤 **Uploading as {mode}...**")
        
        thumb_path = None
        if mode == "video":
            thumb_path = await get_thumbnail(client)
        
        progress_tracker = ProgressTracker(query.message, file_name, "📤 Uploading")
        
        if mode == "video":
            forwarded = await client.send_video(
                chat_id=BIN_CHANNEL,
                video=file_path,
                file_name=file_name,
                thumb=thumb_path,
                supports_streaming=True,
                progress=progress_tracker.callback
            )
        else:
            forwarded = await client.send_document(
                chat_id=BIN_CHANNEL,
                document=file_path,
                file_name=file_name,
                force_document=True,
                progress=progress_tracker.callback
            )
        
        await query.message.edit_text("✅ **Upload Complete!**")
        
        link_id = generate_link_id()
        file_storage[link_id] = {
            "message_id": forwarded.id,
            "file_name": file_name,
            "file_size": file_size
        }
        
        base_url = f"https://file-to-link-5haa.onrender.com"
        download_url = f"{base_url}/download/{link_id}"
        aria2_cmd = generate_aria2_command(download_url, file_name)
        
        await query.message.reply_text(
            generate_beautiful_response(file_name, download_url, aria2_cmd)
        )
        
    except Exception as e:
        LOGGER.error(f"URL upload error: {e}")
        await query.message.edit_text(f"❌ **Error:** `{str(e)}`\n\n**Common Fixes:**\n• Ensure URL is accessible\n• Check if link is expired\n• Verify file size < 2GB")
    
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                LOGGER.error(f"Cleanup error: {e}")

# ==================== CALLBACK HANDLERS ====================
@bot.on_callback_query(filters.regex("^help"))
async def help_callback(client: Client, query: CallbackQuery):
    await query.answer()
    
    help_text = (
        "📖 **Quick Help**\n\n"
        "**Auto URL Detection:**\n   Just send a direct download link\n\n"
        "**Manual Command:**\n   `/uploadurl <direct_link>`\n\n"
        "**Features:**\n"
        "✓ Auto-detects URLs in messages\n"
        "✓ Auto-detects video files (even without extension)\n"
        "✓ Max speed downloads\n"
        "✓ 8 screenshots for videos\n"
        "✓ Custom thumbnail support\n"
        "✓ 2GB per URL limit"
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
