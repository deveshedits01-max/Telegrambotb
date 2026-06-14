#!/usr/bin/env python3
"""
Telegram Bot - Advanced Admin Panel Bot
Termux Hosting: python bot.py
Setup: pkg install python && pip install python-telegram-bot
"""

import asyncio
import json
import os
import sys
import signal
import shutil
import uuid
import sqlite3
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    BotCommand, InputMediaPhoto, InputMediaVideo, InputMediaDocument,
    constants as tg_constants
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
from telegram.error import TelegramError, Forbidden
import re

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8740913782:AAEAZZ1YY3RkADVoVhGhTZE1P70C7FOJkFE"
ADMIN_ID = 7227172211

# ==================== LOGGING ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE SETUP ====================
DB_PATH = "bot_data.db"
HOSTED_DIR = "hosted_bots"

# Ensure hosted bots directory exists
os.makedirs(HOSTED_DIR, exist_ok=True)

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            channel_name TEXT DEFAULT '',
            link TEXT DEFAULT '',
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_link TEXT NOT NULL,
            folder_name TEXT DEFAULT '',
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            content TEXT DEFAULT '[]',
            position INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );
        
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS button_clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            button_id INTEGER,
            user_id INTEGER,
            clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS broadcast_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_users INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            content_type TEXT DEFAULT '',
            broadcast_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS hosted_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            bot_token TEXT DEFAULT '',
            status TEXT DEFAULT 'stopped',
            pid INTEGER DEFAULT 0,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_started TIMESTAMP
        );
    """)
    
    # Insert default settings if not exist
    for key, val in [('restricted', 'off'), ('welcome_message', 'Welcome! 👋\nPlease join our channels to continue:')]:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

# Initialize DB
init_db()

# ==================== HELPER FUNCTIONS ====================

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def get_setting(key: str) -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else ''

def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def is_restricted() -> bool:
    return get_setting('restricted') == 'on'

def get_channels() -> List[Dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_folders() -> List[Dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM folders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_buttons() -> List[Dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM buttons ORDER BY position, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_button(button_id: int) -> Optional[Dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM buttons WHERE id=?", (button_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_channel_db(channel_id: str, name: str, link: str):
    conn = get_db()
    conn.execute("INSERT INTO channels (channel_id, channel_name, link) VALUES (?, ?, ?)",
                 (channel_id, name, link))
    conn.commit()
    conn.close()

def delete_channel_db(ch_id: int):
    conn = get_db()
    conn.execute("DELETE FROM channels WHERE id=?", (ch_id,))
    conn.commit()
    conn.close()

def add_folder_db(link: str, name: str):
    conn = get_db()
    conn.execute("INSERT INTO folders (folder_link, folder_name) VALUES (?, ?)", (link, name))
    conn.commit()
    conn.close()

def delete_folder_db(f_id: int):
    conn = get_db()
    conn.execute("DELETE FROM folders WHERE id=?", (f_id,))
    conn.commit()
    conn.close()

def add_button_db(name: str, content: str = '[]') -> int:
    conn = get_db()
    cursor = conn.execute("INSERT INTO buttons (name, content) VALUES (?, ?)", (name, content))
    conn.commit()
    bid = cursor.lastrowid
    conn.close()
    return bid

def update_button_db(button_id: int, name: str = None, content: str = None):
    conn = get_db()
    if name is not None:
        conn.execute("UPDATE buttons SET name=? WHERE id=?", (name, button_id))
    if content is not None:
        conn.execute("UPDATE buttons SET content=? WHERE id=?", (content, button_id))
    conn.commit()
    conn.close()

def delete_button_db(button_id: int):
    conn = get_db()
    conn.execute("DELETE FROM buttons WHERE id=?", (button_id,))
    conn.execute("DELETE FROM button_clicks WHERE button_id=?", (button_id,))
    conn.commit()
    conn.close()

def record_user(user_id: int, first_name: str = '', username: str = ''):
    conn = get_db()
    conn.execute("""
        INSERT INTO users (user_id, first_name, username, last_active) 
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET 
            first_name=COALESCE(?, first_name),
            username=COALESCE(?, username),
            last_active=CURRENT_TIMESTAMP
    """, (user_id, first_name, username, first_name, username))
    conn.commit()
    conn.close()

def record_button_click(button_id: int, user_id: int):
    conn = get_db()
    conn.execute("INSERT INTO button_clicks (button_id, user_id) VALUES (?, ?)", 
                 (button_id, user_id))
    conn.commit()
    conn.close()

def get_stats() -> Dict:
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
    total_buttons = conn.execute("SELECT COUNT(*) as c FROM buttons").fetchone()['c']
    total_channels = conn.execute("SELECT COUNT(*) as c FROM channels").fetchone()['c']
    total_folders = conn.execute("SELECT COUNT(*) as c FROM folders").fetchone()['c']
    today = datetime.now().strftime('%Y-%m-%d')
    today_users = conn.execute(
        "SELECT COUNT(*) as c FROM users WHERE date(joined_date)=?", (today,)
    ).fetchone()['c']
    total_clicks = conn.execute("SELECT COUNT(*) as c FROM button_clicks").fetchone()['c']
    
    # Per button stats
    button_stats = conn.execute("""
        SELECT b.name, COUNT(bc.id) as clicks 
        FROM buttons b LEFT JOIN button_clicks bc ON b.id=bc.button_id 
        GROUP BY b.id ORDER BY clicks DESC
    """).fetchall()
    
    # Broadcast stats
    total_broadcasts = conn.execute("SELECT COUNT(*) as c FROM broadcast_logs").fetchone()['c']
    total_broadcast_reach = conn.execute("SELECT COALESCE(SUM(success_count),0) as c FROM broadcast_logs").fetchone()['c']
    
    conn.close()
    return {
        'total_users': total_users,
        'today_users': today_users,
        'total_buttons': total_buttons,
        'total_channels': total_channels,
        'total_folders': total_folders,
        'total_clicks': total_clicks,
        'button_stats': [dict(r) for r in button_stats],
        'total_broadcasts': total_broadcasts,
        'total_broadcast_reach': total_broadcast_reach
    }

def get_all_users() -> List[int]:
    conn = get_db()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r['user_id'] for r in rows]

# ==================== HOSTED BOTS MANAGEMENT ====================

def get_hosted_bots() -> List[Dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM hosted_bots ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_hosted_bot(bot_id: int) -> Optional[Dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM hosted_bots WHERE id=?", (bot_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_hosted_bot_db(file_name: str, file_path: str, token: str = '') -> int:
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO hosted_bots (file_name, file_path, bot_token, status) VALUES (?, ?, ?, 'stopped')",
        (file_name, file_path, token)
    )
    conn.commit()
    bid = cursor.lastrowid
    conn.close()
    return bid

def update_hosted_bot_status(bot_id: int, status: str, pid: int = 0):
    conn = get_db()
    if status == 'running':
        conn.execute("UPDATE hosted_bots SET status=?, pid=?, last_started=CURRENT_TIMESTAMP WHERE id=?", 
                     (status, pid, bot_id))
    else:
        conn.execute("UPDATE hosted_bots SET status=?, pid=0 WHERE id=?", (status, bot_id))
    conn.commit()
    conn.close()

def update_hosted_bot_token(bot_id: int, token: str):
    conn = get_db()
    conn.execute("UPDATE hosted_bots SET bot_token=? WHERE id=?", (token, bot_id))
    conn.commit()
    conn.close()

def delete_hosted_bot_db(bot_id: int):
    conn = get_db()
    conn.execute("DELETE FROM hosted_bots WHERE id=?", (bot_id,))
    conn.commit()
    conn.close()

def is_bot_running(bot_id: int) -> bool:
    bot = get_hosted_bot(bot_id)
    if not bot or bot['pid'] <= 0:
        return False
    # Check if PID actually exists
    try:
        os.kill(bot['pid'], 0)
        return True
    except (OSError, ProcessLookupError):
        update_hosted_bot_status(bot_id, 'stopped', 0)
        return False

def start_hosted_bot(bot_id: int) -> tuple:
    """Start a hosted bot. Returns (success: bool, message: str, pid: int)"""
    bot = get_hosted_bot(bot_id)
    if not bot:
        return (False, "Bot not found in database", 0)
    
    if is_bot_running(bot_id):
        return (False, f"Bot '{bot['file_name']}' is already running (PID: {bot['pid']})", 0)
    
    file_path = bot['file_path']
    if not os.path.exists(file_path):
        return (False, f"File not found: {file_path}", 0)
    
    try:
        # Start bot as subprocess
        log_file = os.path.join(HOSTED_DIR, f"bot_{bot_id}.log")
        proc = subprocess.Popen(
            [sys.executable, file_path],
            stdout=open(log_file, 'a'),
            stderr=subprocess.STDOUT,
            cwd=HOSTED_DIR,
            preexec_fn=os.setpgrp if os.name != 'nt' else None  # Detach from parent
        )
        pid = proc.pid
        update_hosted_bot_status(bot_id, 'running', pid)
        return (True, f"Bot '{bot['file_name']}' started!\nPID: {pid}", pid)
    except Exception as e:
        return (False, f"Failed to start bot: {e}", 0)

def stop_hosted_bot(bot_id: int) -> tuple:
    """Stop a running hosted bot. Returns (success: bool, message: str)"""
    bot = get_hosted_bot(bot_id)
    if not bot:
        return (False, "Bot not found in database")
    
    if not is_bot_running(bot_id):
        update_hosted_bot_status(bot_id, 'stopped', 0)
        return (True, f"Bot '{bot['file_name']}' was already stopped")
    
    pid = bot['pid']
    try:
        # Try graceful shutdown first
        os.kill(pid, signal.SIGTERM)
        # If process group exists, kill that too
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except:
            pass
        update_hosted_bot_status(bot_id, 'stopped', 0)
        return (True, f"Bot '{bot['file_name']}' stopped (PID: {pid})")
    except ProcessLookupError:
        update_hosted_bot_status(bot_id, 'stopped', 0)
        return (True, f"Bot was already stopped (stale PID cleaned)")
    except Exception as e:
        # Force kill
        try:
            os.kill(pid, signal.SIGKILL)
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except:
                pass
            update_hosted_bot_status(bot_id, 'stopped', 0)
            return (True, f"Bot forcefully stopped")
        except:
            update_hosted_bot_status(bot_id, 'stopped', 0)
            return (True, f"Bot stopped with cleanup")

def restart_hosted_bot(bot_id: int) -> tuple:
    """Restart a hosted bot"""
    stop_result = stop_hosted_bot(bot_id)
    import asyncio as asyncio_mod
    # Small delay
    import time
    time.sleep(1)
    start_result = start_hosted_bot(bot_id)
    return (start_result[0], f"Stop: {stop_result[1]}\nStart: {start_result[1]}")

# ==================== CHANNEL CHECK ====================

async def check_user_joined_channels(bot, user_id: int) -> tuple:
    """Returns (all_joined: bool, not_joined: list)"""
    channels = get_channels()
    not_joined = []
    
    for ch in channels:
        channel_id = ch['channel_id'].strip()
        if not channel_id:
            continue
        try:
            # Try to check membership
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                not_joined.append(ch)
        except TelegramError as e:
            # If bot can't check (not in channel, etc.), skip verification
            logger.warning(f"Cannot check channel {channel_id}: {e}")
            # Still add to not_joined if we can't verify
            if "chat not found" not in str(e).lower():
                not_joined.append(ch)
        except Exception as e:
            logger.error(f"Error checking channel {channel_id}: {e}")
    
    return (len(not_joined) == 0 and len(channels) > 0, not_joined)

# ==================== KEYBOARD BUILDERS ====================

def build_join_keyboard(channels, folders):
    """Build keyboard for join verification"""
    keyboard = []
    
    for i, ch in enumerate(channels):
        channel_id = ch.get('channel_id', '')
        link = ch.get('link', '')
        name = ch.get('channel_name', '') or f"Channel {i+1}"
        
        # Build proper URL
        if link:
            url = link
        elif channel_id.startswith('@'):
            url = f"https://t.me/{channel_id.replace('@', '')}"
        elif channel_id.startswith('-100'):
            url = f"https://t.me/c/{channel_id.replace('-100', '')}"
        else:
            url = f"https://t.me/{channel_id}"
        
        if not url.startswith('http'):
            url = f"https://t.me/{url}"
        
        keyboard.append([InlineKeyboardButton(f"📢 Join {name}", url=url)])
    
    for i, fd in enumerate(folders):
        link = fd.get('folder_link', '')
        name = fd.get('folder_name', '') or f"Folder {i+1}"
        if link:
            if not link.startswith('http'):
                link = 'https://' + link
            keyboard.append([InlineKeyboardButton(f"📁 Join {name}", url=link)])
    
    keyboard.append([InlineKeyboardButton("✅ Joined", callback_data="verify_join")])
    
    return InlineKeyboardMarkup(keyboard) if keyboard else None

def build_main_buttons_keyboard():
    """Build ReplyKeyboardMarkup with user-facing buttons"""
    buttons = get_buttons()
    if not buttons:
        return None
    
    keyboard = []
    row = []
    for i, btn in enumerate(buttons):
        row.append(KeyboardButton(btn['name']))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def build_admin_panel_keyboard():
    """Build admin panel inline keyboard"""
    restricted = is_restricted()
    restricted_text = "🔒 Restricted: ON" if restricted else "🔓 Restricted: OFF"
    
    keyboard = [
        [InlineKeyboardButton("📢 Add Channel", callback_data="add_channel"),
         InlineKeyboardButton("📁 Add Folder", callback_data="add_folder")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_button"),
         InlineKeyboardButton("✏️ Edit Buttons", callback_data="edit_buttons")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="broadcast"),
         InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton(restricted_text, callback_data="toggle_restricted")],
        [InlineKeyboardButton("📋 Channel List", callback_data="channel_list"),
         InlineKeyboardButton("📁 Folder List", callback_data="folder_list")],
        [InlineKeyboardButton("🔄 Refresh Menu", callback_data="admin_refresh")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_buttons_list_keyboard(action: str = "edit"):
    """Build keyboard listing all buttons for editing"""
    buttons = get_buttons()
    keyboard = []
    
    for btn in buttons:
        content_data = json.loads(btn.get('content', '[]'))
        content_count = len(content_data)
        label = f"{btn['name']} ({content_count} items)"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{action}_btn_{btn['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_channel_list_keyboard():
    """Build keyboard listing channels with delete option"""
    channels = get_channels()
    keyboard = []
    for ch in channels:
        name = ch.get('channel_name', '') or ch.get('channel_id', 'Unknown')
        channel_id = ch.get('channel_id', '')
        link = ch.get('link', '')
        
        # Build URL for the channel
        if link:
            url = link
        elif channel_id.startswith('@'):
            url = f"https://t.me/{channel_id.replace('@', '')}"
        elif channel_id.startswith('-100'):
            url = f"https://t.me/c/{channel_id.replace('-100', '')}"
        else:
            url = None
        
        if url:
            keyboard.append([
                InlineKeyboardButton(f"📢 {name}", url=url),
                InlineKeyboardButton("❌ Delete", callback_data=f"delete_ch_{ch['id']}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(f"📢 {name} (no link)", callback_data="noop"),
                InlineKeyboardButton("❌ Delete", callback_data=f"delete_ch_{ch['id']}")
            ])
    
    if not channels:
        keyboard.append([InlineKeyboardButton("📭 No channels", callback_data="noop")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_folder_list_keyboard():
    """Build keyboard listing folders with delete option"""
    folders = get_folders()
    keyboard = []
    for fd in folders:
        name = fd.get('folder_name', '') or fd.get('folder_link', 'Unknown')
        keyboard.append([
            InlineKeyboardButton(f"📁 {name}", url=fd.get('folder_link', '')),
            InlineKeyboardButton("❌ Delete", callback_data=f"delete_fld_{fd['id']}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def build_edit_button_keyboard(button_id: int):
    """Build keyboard for editing a specific button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Rename Button", callback_data=f"rename_btn_{button_id}")],
        [InlineKeyboardButton("📎 Add Content", callback_data=f"addcontent_btn_{button_id}")],
        [InlineKeyboardButton("🗑 Clear All Content", callback_data=f"clear_btn_{button_id}")],
        [InlineKeyboardButton("❌ Delete Button", callback_data=f"delete_btn_{button_id}")],
        [InlineKeyboardButton("🔙 Back to Button List", callback_data="edit_buttons")],
    ])

def build_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_menu")]])

# ==================== SEND CONTENT TO USER ====================

async def send_button_content_to_user(bot, user_id: int, button: Dict, chat_id: int = None):
    """Send all content of a button to a user"""
    target = chat_id or user_id
    content_list = json.loads(button.get('content', '[]'))
    
    if not content_list:
        await bot.send_message(chat_id=target, text=f"📭 No content available for '{button['name']}'")
        return
    
    success = 0
    for item in content_list:
        try:
            item_type = item.get('type', 'text')
            caption = item.get('caption', '')
            file_id = item.get('file_id', '')
            text = item.get('text', '')
            
            if item_type == 'text':
                await bot.send_message(chat_id=target, text=text)
            elif item_type == 'photo':
                await bot.send_photo(chat_id=target, photo=file_id, caption=caption or None)
            elif item_type == 'video':
                await bot.send_video(chat_id=target, video=file_id, caption=caption or None)
            elif item_type == 'document':
                await bot.send_document(chat_id=target, document=file_id, caption=caption or None)
            elif item_type == 'audio':
                await bot.send_audio(chat_id=target, audio=file_id, caption=caption or None)
            elif item_type == 'voice':
                await bot.send_voice(chat_id=target, voice=file_id, caption=caption or None)
            elif item_type == 'animation':
                await bot.send_animation(chat_id=target, animation=file_id, caption=caption or None)
            elif item_type == 'video_note':
                await bot.send_video_note(chat_id=target, video_note=file_id)
            elif item_type == 'sticker':
                await bot.send_sticker(chat_id=target, sticker=file_id)
            else:
                await bot.send_message(chat_id=target, text=f"📦 Unknown content type: {item_type}")
            
            success += 1
            await asyncio.sleep(0.05)  # Small delay to avoid flooding
        except Forbidden:
            logger.info(f"User {user_id} blocked the bot")
            break
        except Exception as e:
            logger.error(f"Error sending content type {item_type} to {target}: {e}")
            try:
                await bot.send_message(chat_id=target, text=f"⚠️ Error sending one item: {e}")
            except:
                pass
    
    return success

# ==================== COMMAND HANDLERS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    
    # Record user
    record_user(user_id, user.first_name or '', user.username or '')
    
    channels = get_channels()
    folders = get_folders()
    
    if not channels and not folders:
        # No force join needed, show buttons directly
        await show_main_menu(update, context)
        return
    
    # Show join verification
    welcome_msg = get_setting('welcome_message') or "Welcome! 👋\nPlease join our channels to continue:"
    
    keyboard = build_join_keyboard(channels, folders)
    
    if update.message:
        await update.message.reply_text(welcome_msg, reply_markup=keyboard, disable_web_page_preview=True)
    else:
        await context.bot.send_message(chat_id=chat_id, text=welcome_msg, reply_markup=keyboard, disable_web_page_preview=True)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu with buttons"""
    chat_id = update.effective_chat.id
    
    buttons = get_buttons()
    if not buttons:
        msg = "✅ You're verified! But there are no buttons available yet.\nPlease check back later."
        if update.message:
            await update.message.reply_text(msg)
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        return
    
    keyboard = build_main_buttons_keyboard()
    if update.message:
        await update.message.reply_text("✅ Verified! Choose an option below:", reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=chat_id, text="✅ Verified! Choose an option below:", reply_markup=keyboard)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command - open admin panel"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_admin(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return ConversationHandler.END
    
    record_user(user_id, update.effective_user.first_name or '', update.effective_user.username or '')
    
    keyboard = build_admin_panel_keyboard()
    await update.message.reply_text(
        "🛡️ <b>Admin Panel</b>\n\n"
        f"Welcome, {update.effective_user.first_name}!\n"
        "Manage your bot from here.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# ==================== CONVERSATION STATES ====================
(
    ADMIN_MENU,
    ADDING_CHANNEL,
    ADDING_FOLDER,
    ADDING_BUTTON_NAME,
    ADDING_BUTTON_CONTENT,
    EDITING_BUTTON_SELECT,
    RENAMING_BUTTON,
    ADDING_CONTENT_TO_BUTTON,
    BROADCASTING,
    BROADCAST_CONFIRM,
) = range(10)

# Store temporary data during conversations
temp_data = {}

# ==================== ADMIN PANEL CALLBACK HANDLERS ====================

async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin menu callbacks"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await query.edit_message_text("⛔ Unauthorized!")
        return ConversationHandler.END
    
    # Clear temp data
    temp_data.pop(user_id, None)
    
    keyboard = build_admin_panel_keyboard()
    await query.edit_message_text(
        "🛡️ <b>Admin Panel</b>\n\nManage your bot from here.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def admin_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh admin panel"""
    query = update.callback_query
    await query.answer("Refreshed!")
    keyboard = build_admin_panel_keyboard()
    await query.edit_message_text(
        "🛡️ <b>Admin Panel</b>\n\nManage your bot from here.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- CHANNEL MANAGEMENT ---------------

async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start add channel flow"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    await query.edit_message_text(
        "📢 <b>Add Channel</b>\n\n"
        "Send me the channel details:\n\n"
        "<b>Format:</b>\n"
        "<code>@channel_username</code> or <code>-100xxxxx</code>\n"
        "or <code>@username | Channel Name | https://t.me/username</code>\n\n"
        "Examples:\n"
        "<code>@my_channel</code>\n"
        "<code>@my_channel | My Channel | https://t.me/my_channel</code>\n\n"
        "Send /cancel to abort.",
        reply_markup=build_back_keyboard(),
        parse_mode='HTML'
    )
    return ADDING_CHANNEL

async def add_channel_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new channel"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    text = update.message.text.strip()
    
    # Parse input: @username | Name | link
    parts = [p.strip() for p in text.split('|')]
    
    channel_id = parts[0]
    channel_name = parts[1] if len(parts) > 1 else channel_id.replace('@', '')
    channel_link = parts[2] if len(parts) > 2 else ''
    
    # Auto-generate link if not provided and it's a username
    if not channel_link and channel_id.startswith('@'):
        channel_link = f"https://t.me/{channel_id.replace('@', '')}"
    
    # Validate
    if not channel_id:
        await update.message.reply_text("❌ Invalid channel ID. Try again or /cancel")
        return ADDING_CHANNEL
    
    add_channel_db(channel_id, channel_name, channel_link)
    
    keyboard = build_admin_panel_keyboard()
    await update.message.reply_text(
        f"✅ Channel <b>{channel_name}</b> added successfully!\nID: <code>{channel_id}</code>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- FOLDER MANAGEMENT ---------------

async def add_folder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start add folder flow"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    await query.edit_message_text(
        "📁 <b>Add Folder</b>\n\n"
        "Send me the folder details:\n\n"
        "<b>Format:</b>\n"
        "<code>https://t.me/addlist/xxxxx</code>\n"
        "or <code>https://t.me/addlist/xxxxx | Folder Name</code>\n\n"
        "Send /cancel to abort.",
        reply_markup=build_back_keyboard(),
        parse_mode='HTML'
    )
    return ADDING_FOLDER

async def add_folder_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new folder"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    text = update.message.text.strip()
    parts = [p.strip() for p in text.split('|')]
    
    folder_link = parts[0]
    folder_name = parts[1] if len(parts) > 1 else 'Folder'
    
    if not folder_link.startswith('https://t.me/addlist/') and not folder_link.startswith('t.me/addlist/'):
        await update.message.reply_text(
            "❌ Invalid folder link! Must start with <code>https://t.me/addlist/</code>\nTry again or /cancel",
            parse_mode='HTML'
        )
        return ADDING_FOLDER
    
    if folder_link.startswith('t.me/'):
        folder_link = 'https://' + folder_link
    
    add_folder_db(folder_link, folder_name)
    
    keyboard = build_admin_panel_keyboard()
    await update.message.reply_text(
        f"✅ Folder <b>{folder_name}</b> added successfully!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- BUTTON MANAGEMENT ---------------

async def add_button_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start add button flow"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    temp_data[user_id] = {'new_button_content': []}
    
    await query.edit_message_text(
        "➕ <b>Add Button</b>\n\n"
        "Send me the button name.\n"
        "This name will appear as a button for users.\n\n"
        "Send /cancel to abort.",
        reply_markup=build_back_keyboard(),
        parse_mode='HTML'
    )
    return ADDING_BUTTON_NAME

async def add_button_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get button name and ask for content"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    name = update.message.text.strip()
    
    if len(name) > 50:
        await update.message.reply_text("❌ Name too long! Max 50 characters. Try again:")
        return ADDING_BUTTON_NAME
    
    temp_data.setdefault(user_id, {})['new_button_name'] = name
    temp_data[user_id]['new_button_content'] = []
    
    await update.message.reply_text(
        f"✅ Button name: <b>{name}</b>\n\n"
        "Now send me the content for this button.\n"
        "You can send:\n"
        "• 📝 Text messages\n"
        "• 🖼️ Photos\n"
        "• 🎬 Videos\n"
        "• 📄 Documents/Files\n"
        "• 🎵 Audio\n"
        "• 🎤 Voice messages\n"
        "• 🎞️ GIFs/Animations\n"
        "• 🎯 Stickers\n\n"
        "<b>Send multiple items one by one.</b>\n"
        "When done, send <b>/done</b> to publish the button.\n"
        "Send /cancel to abort.",
        parse_mode='HTML'
    )
    return ADDING_BUTTON_CONTENT

async def add_button_get_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect content for button"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    msg = update.message
    
    if not msg:
        return ADDING_BUTTON_CONTENT
    
    content_item = None
    
    if msg.text and not msg.text.startswith('/'):
        content_item = {'type': 'text', 'text': msg.text, 'caption': ''}
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        caption = msg.caption or ''
        content_item = {'type': 'photo', 'file_id': file_id, 'caption': caption}
    elif msg.video:
        file_id = msg.video.file_id
        caption = msg.caption or ''
        content_item = {'type': 'video', 'file_id': file_id, 'caption': caption}
    elif msg.document:
        file_id = msg.document.file_id
        caption = msg.caption or ''
        content_item = {'type': 'document', 'file_id': file_id, 'caption': caption}
    elif msg.audio:
        file_id = msg.audio.file_id
        caption = msg.caption or ''
        content_item = {'type': 'audio', 'file_id': file_id, 'caption': caption}
    elif msg.voice:
        file_id = msg.voice.file_id
        content_item = {'type': 'voice', 'file_id': file_id, 'caption': ''}
    elif msg.animation:
        file_id = msg.animation.file_id
        caption = msg.caption or ''
        content_item = {'type': 'animation', 'file_id': file_id, 'caption': caption}
    elif msg.video_note:
        file_id = msg.video_note.file_id
        content_item = {'type': 'video_note', 'file_id': file_id, 'caption': ''}
    elif msg.sticker:
        file_id = msg.sticker.file_id
        content_item = {'type': 'sticker', 'file_id': file_id, 'caption': ''}
    
    if content_item:
        temp_data.setdefault(user_id, {})
        temp_data[user_id].setdefault('new_button_content', [])
        temp_data[user_id]['new_button_content'].append(content_item)
        
        count = len(temp_data[user_id]['new_button_content'])
        type_name = content_item['type']
        await update.message.reply_text(
            f"✅ Added ({count}) - Type: <b>{type_name}</b>\n\n"
            "Send more content or <b>/done</b> to finish.\n"
            "/cancel to abort.",
            parse_mode='HTML'
        )
    
    return ADDING_BUTTON_CONTENT

async def add_button_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish adding button and publish"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    name = temp_data.get(user_id, {}).get('new_button_name', 'Unnamed Button')
    content = temp_data.get(user_id, {}).get('new_button_content', [])
    
    if not content:
        await update.message.reply_text(
            "❌ No content added! Send at least one item or /cancel to abort."
        )
        return ADDING_BUTTON_CONTENT
    
    content_json = json.dumps(content, ensure_ascii=False)
    button_id = add_button_db(name, content_json)
    
    # Clean up
    temp_data.pop(user_id, None)
    
    keyboard = build_admin_panel_keyboard()
    await update.message.reply_text(
        f"✅ Button <b>\"{name}\"</b> published successfully!\n"
        f"📎 Content items: <b>{len(content)}</b>\n"
        f"🆔 Button ID: <code>{button_id}</code>\n\n"
        f"It's now live for users!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def edit_buttons_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of buttons for editing"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    buttons = get_buttons()
    if not buttons:
        await query.edit_message_text(
            "📭 No buttons found!\n\nUse '➕ Add Button' to create one.",
            reply_markup=build_back_keyboard()
        )
        return ADMIN_MENU
    
    keyboard = build_buttons_list_keyboard("edit")
    await query.edit_message_text(
        "✏️ <b>Edit Buttons</b>\n\nSelect a button to edit:",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def edit_button_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button selection for editing"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    # Extract button ID from callback data
    match = re.search(r'edit_btn_(\d+)', query.data)
    if not match:
        return ADMIN_MENU
    
    button_id = int(match.group(1))
    button = get_button(button_id)
    
    if not button:
        await query.answer("Button not found!")
        return ADMIN_MENU
    
    content_list = json.loads(button.get('content', '[]'))
    
    # Show content preview
    content_preview = ""
    for i, item in enumerate(content_list[:5], 1):
        item_type = item.get('type', 'text')
        if item_type == 'text':
            preview = item.get('text', '')[:50]
            content_preview += f"  {i}. 📝 Text: {preview}...\n" if len(item.get('text', '')) > 50 else f"  {i}. 📝 Text: {preview}\n"
        else:
            cap = item.get('caption', '')[:30]
            content_preview += f"  {i}. 📎 {item_type.upper()}"
            if cap:
                content_preview += f" - {cap}"
            content_preview += "\n"
    
    if len(content_list) > 5:
        content_preview += f"  ... and {len(content_list) - 5} more items\n"
    
    temp_data[user_id] = {'editing_button_id': button_id}
    
    keyboard = build_edit_button_keyboard(button_id)
    await query.edit_message_text(
        f"✏️ <b>Edit Button</b>\n\n"
        f"<b>Name:</b> {button['name']}\n"
        f"<b>ID:</b> <code>{button['id']}</code>\n"
        f"<b>Content Items:</b> {len(content_list)}\n\n"
        f"{content_preview}\n"
        f"Choose an action:",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def rename_button_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start rename button flow"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'rename_btn_(\d+)', query.data)
    if not match:
        return ADMIN_MENU
    
    button_id = int(match.group(1))
    temp_data[user_id] = {'renaming_button_id': button_id}
    
    await query.edit_message_text(
        "✏️ Send me the new name for this button.\n\n"
        "Send /cancel to abort.",
        reply_markup=build_back_keyboard()
    )
    return RENAMING_BUTTON

async def rename_button_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new button name"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    new_name = update.message.text.strip()
    button_id = temp_data.get(user_id, {}).get('renaming_button_id')
    
    if not button_id:
        await update.message.reply_text("❌ Error. Please try again.")
        return ADMIN_MENU
    
    update_button_db(button_id, name=new_name)
    temp_data.pop(user_id, None)
    
    keyboard = build_admin_panel_keyboard()
    await update.message.reply_text(
        f"✅ Button renamed to <b>{new_name}</b>!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def add_content_to_button_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding content to existing button"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'addcontent_btn_(\d+)', query.data)
    if not match:
        return ADMIN_MENU
    
    button_id = int(match.group(1))
    button = get_button(button_id)
    
    if not button:
        await query.answer("Button not found!")
        return ADMIN_MENU
    
    temp_data[user_id] = {
        'adding_content_to': button_id,
        'new_button_content': []
    }
    
    await query.edit_message_text(
        f"📎 <b>Add Content to:</b> {button['name']}\n\n"
        "Send me photos, videos, files, text, audio, etc.\n"
        "Send multiple items one by one.\n"
        "When done, send <b>/done</b>.\n"
        "/cancel to abort.",
        reply_markup=build_back_keyboard(),
        parse_mode='HTML'
    )
    return ADDING_CONTENT_TO_BUTTON

async def add_content_to_button_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect content for existing button"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    msg = update.message
    if not msg:
        return ADDING_CONTENT_TO_BUTTON
    
    content_item = None
    
    if msg.text and not msg.text.startswith('/'):
        content_item = {'type': 'text', 'text': msg.text, 'caption': ''}
    elif msg.photo:
        content_item = {'type': 'photo', 'file_id': msg.photo[-1].file_id, 'caption': msg.caption or ''}
    elif msg.video:
        content_item = {'type': 'video', 'file_id': msg.video.file_id, 'caption': msg.caption or ''}
    elif msg.document:
        content_item = {'type': 'document', 'file_id': msg.document.file_id, 'caption': msg.caption or ''}
    elif msg.audio:
        content_item = {'type': 'audio', 'file_id': msg.audio.file_id, 'caption': msg.caption or ''}
    elif msg.voice:
        content_item = {'type': 'voice', 'file_id': msg.voice.file_id, 'caption': ''}
    elif msg.animation:
        content_item = {'type': 'animation', 'file_id': msg.animation.file_id, 'caption': msg.caption or ''}
    elif msg.video_note:
        content_item = {'type': 'video_note', 'file_id': msg.video_note.file_id, 'caption': ''}
    elif msg.sticker:
        content_item = {'type': 'sticker', 'file_id': msg.sticker.file_id, 'caption': ''}
    
    if content_item:
        temp_data.setdefault(user_id, {})
        temp_data[user_id].setdefault('new_button_content', [])
        temp_data[user_id]['new_button_content'].append(content_item)
        
        count = len(temp_data[user_id]['new_button_content'])
        await update.message.reply_text(
            f"✅ Added ({count}) - Type: <b>{content_item['type']}</b>\n"
            "Send more or <b>/done</b> to save.",
            parse_mode='HTML'
        )
    
    return ADDING_CONTENT_TO_BUTTON

async def add_content_to_button_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save added content to button"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    button_id = temp_data.get(user_id, {}).get('adding_content_to')
    new_content = temp_data.get(user_id, {}).get('new_button_content', [])
    
    if not button_id or not new_content:
        await update.message.reply_text("❌ Error. No content to add.")
        return ADMIN_MENU
    
    # Get existing content and append new
    button = get_button(button_id)
    existing = json.loads(button.get('content', '[]')) if button else []
    existing.extend(new_content)
    
    update_button_db(button_id, content=json.dumps(existing, ensure_ascii=False))
    
    temp_data.pop(user_id, None)
    
    keyboard = build_admin_panel_keyboard()
    await update.message.reply_text(
        f"✅ <b>{len(new_content)}</b> new items added to button!\n"
        f"Total content: <b>{len(existing)}</b> items.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def clear_button_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all content from a button"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'clear_btn_(\d+)', query.data)
    if not match:
        return ADMIN_MENU
    
    button_id = int(match.group(1))
    update_button_db(button_id, content='[]')
    
    keyboard = build_admin_panel_keyboard()
    await query.edit_message_text(
        "🗑 All content cleared from the button!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def delete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a button"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'delete_btn_(\d+)', query.data)
    if not match:
        return ADMIN_MENU
    
    button_id = int(match.group(1))
    button = get_button(button_id)
    name = button['name'] if button else 'Unknown'
    
    delete_button_db(button_id)
    
    keyboard = build_admin_panel_keyboard()
    await query.edit_message_text(
        f"❌ Button <b>\"{name}\"</b> deleted!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- BROADCAST ---------------

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast flow"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    await query.edit_message_text(
        "📣 <b>Broadcast Mode</b>\n\n"
        "Send me the message you want to broadcast to <b>all users</b>.\n\n"
        "You can send:\n"
        "• 📝 Text\n"
        "• 🖼️ Photo\n"
        "• 🎬 Video\n"
        "• 📄 Document/File\n"
        "• 🎵 Audio\n"
        "• 🎤 Voice\n"
        "• Forward any message\n\n"
        "After sending, you'll be asked to confirm.\n"
        "Send /cancel to abort.",
        reply_markup=build_back_keyboard(),
        parse_mode='HTML'
    )
    return BROADCASTING

async def broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive broadcast content"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    msg = update.message
    if not msg:
        return BROADCASTING
    
    broadcast_data = {
        'type': 'text',
        'text': None,
        'file_id': None,
        'caption': None,
        'from_chat_id': None,
        'message_id': None,
        'is_forward': False,
    }
    
    # Check if it's a forwarded message
    if msg.forward_origin or msg.forward_from or msg.forward_from_chat:
        broadcast_data['is_forward'] = True
        # Get source chat info
        if msg.forward_from_chat:
            broadcast_data['from_chat_id'] = msg.forward_from_chat.id
        elif msg.forward_from:
            broadcast_data['from_chat_id'] = msg.forward_from.id
        else:
            # For forward_origin, use original message chat
            broadcast_data['from_chat_id'] = msg.chat.id
        broadcast_data['message_id'] = msg.message_id
    
    if msg.text and not msg.text.startswith('/'):
        broadcast_data['type'] = 'text'
        broadcast_data['text'] = msg.text
    elif msg.photo:
        broadcast_data['type'] = 'photo'
        broadcast_data['file_id'] = msg.photo[-1].file_id
        broadcast_data['caption'] = msg.caption or ''
    elif msg.video:
        broadcast_data['type'] = 'video'
        broadcast_data['file_id'] = msg.video.file_id
        broadcast_data['caption'] = msg.caption or ''
    elif msg.document:
        broadcast_data['type'] = 'document'
        broadcast_data['file_id'] = msg.document.file_id
        broadcast_data['caption'] = msg.caption or ''
    elif msg.audio:
        broadcast_data['type'] = 'audio'
        broadcast_data['file_id'] = msg.audio.file_id
        broadcast_data['caption'] = msg.caption or ''
    elif msg.voice:
        broadcast_data['type'] = 'voice'
        broadcast_data['file_id'] = msg.voice.file_id
    elif msg.animation:
        broadcast_data['type'] = 'animation'
        broadcast_data['file_id'] = msg.animation.file_id
        broadcast_data['caption'] = msg.caption or ''
    elif msg.video_note:
        broadcast_data['type'] = 'video_note'
        broadcast_data['file_id'] = msg.video_note.file_id
    elif msg.sticker:
        broadcast_data['type'] = 'sticker'
        broadcast_data['file_id'] = msg.sticker.file_id
    else:
        await update.message.reply_text("❌ Unsupported content type. Try again or /cancel")
        return BROADCASTING
    
    temp_data[user_id] = {'broadcast_data': broadcast_data}
    
    # Show preview and confirmation
    preview = f"Type: <b>{broadcast_data['type'].upper()}</b>"
    if broadcast_data.get('is_forward'):
        preview += "\n📤 This will be forwarded"
    if broadcast_data.get('caption'):
        preview += f"\nCaption: {broadcast_data['caption'][:100]}"
    if broadcast_data.get('text'):
        preview += f"\n\n{broadcast_data['text'][:200]}"
    
    users_count = len(get_all_users())
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Send", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_menu")],
    ])
    
    await update.message.reply_text(
        f"📣 <b>Broadcast Preview</b>\n\n"
        f"{preview}\n\n"
        f"📊 Will be sent to: <b>{users_count}</b> users\n\n"
        f"Confirm?",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return BROADCAST_CONFIRM

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and execute broadcast"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    broadcast_data = temp_data.get(user_id, {}).get('broadcast_data')
    if not broadcast_data:
        await query.edit_message_text("❌ Broadcast data lost. Please try again.")
        return ADMIN_MENU
    
    users = get_all_users()
    total = len(users)
    success = 0
    fail = 0
    
    progress_msg = await query.edit_message_text(f"📣 Broadcasting... 0/{total}")
    
    for i, uid in enumerate(users):
        try:
            if broadcast_data['is_forward'] and broadcast_data.get('from_chat_id') and broadcast_data.get('message_id'):
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=broadcast_data['from_chat_id'],
                    message_id=broadcast_data['message_id']
                )
            elif broadcast_data['type'] == 'text':
                await context.bot.send_message(chat_id=uid, text=broadcast_data['text'])
            elif broadcast_data['type'] == 'photo':
                await context.bot.send_photo(chat_id=uid, photo=broadcast_data['file_id'],
                                            caption=broadcast_data.get('caption') or None)
            elif broadcast_data['type'] == 'video':
                await context.bot.send_video(chat_id=uid, video=broadcast_data['file_id'],
                                            caption=broadcast_data.get('caption') or None)
            elif broadcast_data['type'] == 'document':
                await context.bot.send_document(chat_id=uid, document=broadcast_data['file_id'],
                                               caption=broadcast_data.get('caption') or None)
            elif broadcast_data['type'] == 'audio':
                await context.bot.send_audio(chat_id=uid, audio=broadcast_data['file_id'],
                                            caption=broadcast_data.get('caption') or None)
            elif broadcast_data['type'] == 'voice':
                await context.bot.send_voice(chat_id=uid, voice=broadcast_data['file_id'])
            elif broadcast_data['type'] == 'animation':
                await context.bot.send_animation(chat_id=uid, animation=broadcast_data['file_id'],
                                                caption=broadcast_data.get('caption') or None)
            elif broadcast_data['type'] == 'video_note':
                await context.bot.send_video_note(chat_id=uid, video_note=broadcast_data['file_id'])
            elif broadcast_data['type'] == 'sticker':
                await context.bot.send_sticker(chat_id=uid, sticker=broadcast_data['file_id'])
            else:
                await context.bot.send_message(chat_id=uid, text="📢 New content available! Check the bot.")
            
            success += 1
        except Forbidden:
            fail += 1
            logger.info(f"User {uid} blocked the bot")
        except Exception as e:
            fail += 1
            logger.error(f"Broadcast error for {uid}: {e}")
        
        # Update progress every 10 users
        if (i + 1) % 10 == 0 or (i + 1) == total:
            try:
                await progress_msg.edit_text(f"📣 Broadcasting... {i+1}/{total}")
            except:
                pass
        
        await asyncio.sleep(0.05)  # Rate limit protection
    
    # Log broadcast
    conn = get_db()
    conn.execute("INSERT INTO broadcast_logs (total_users, success_count, fail_count, content_type) VALUES (?, ?, ?, ?)",
                 (total, success, fail, broadcast_data['type']))
    conn.commit()
    conn.close()
    
    # Clean up
    temp_data.pop(user_id, None)
    
    keyboard = build_admin_panel_keyboard()
    await progress_msg.edit_text(
        f"📣 <b>Broadcast Complete!</b>\n\n"
        f"📊 Total Users: <b>{total}</b>\n"
        f"✅ Success: <b>{success}</b>\n"
        f"❌ Failed: <b>{fail}</b>\n"
        f"📝 Type: <b>{broadcast_data['type'].upper()}</b>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- STATISTICS ---------------

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    stats = get_stats()
    restricted = "🔒 ON" if is_restricted() else "🔓 OFF"
    
    button_stats_text = ""
    for bs in stats['button_stats']:
        if bs['name']:
            button_stats_text += f"• {bs['name']}: {bs['clicks']} clicks\n"
    
    if not button_stats_text:
        button_stats_text = "No button data yet\n"
    
    text = (
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"🆕 New Today: <b>{stats['today_users']}</b>\n"
        f"🔘 Total Buttons: <b>{stats['total_buttons']}</b>\n"
        f"📢 Channels: <b>{stats['total_channels']}</b>\n"
        f"📁 Folders: <b>{stats['total_folders']}</b>\n"
        f"👆 Total Clicks: <b>{stats['total_clicks']}</b>\n"
        f"📣 Broadcasts Sent: <b>{stats['total_broadcasts']}</b>\n"
        f"📤 Broadcast Reach: <b>{stats['total_broadcast_reach']}</b>\n"
        f"🔒 Restricted Mode: <b>{restricted}</b>\n\n"
        f"<b>Per-Button Clicks:</b>\n{button_stats_text}"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Stats", callback_data="stats")],
        [InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_menu")],
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
    return ADMIN_MENU

# --------------- RESTRICTED TOGGLE ---------------

async def toggle_restricted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle restricted mode"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    current = is_restricted()
    new_val = 'off' if current else 'on'
    set_setting('restricted', new_val)
    
    keyboard = build_admin_panel_keyboard()
    status = "🔒 ON - Content is BLOCKED" if new_val == 'on' else "🔓 OFF - Content is available"
    await query.edit_message_text(
        f"🛡️ <b>Restricted Mode:</b> {status}\n\n"
        "When ON, users cannot access button content.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- CHANNEL/FOLDER LISTS ---------------

async def channel_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show channel list"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    channels = get_channels()
    if not channels:
        await query.edit_message_text(
            "📭 No channels added yet.",
            reply_markup=build_back_keyboard()
        )
        return ADMIN_MENU
    
    keyboard = build_channel_list_keyboard()
    await query.edit_message_text(
        f"📢 <b>Channel List</b> ({len(channels)})\n\nClick ❌ to delete a channel.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a channel"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'delete_ch_(\d+)', query.data)
    if match:
        ch_id = int(match.group(1))
        delete_channel_db(ch_id)
        await query.answer("Channel deleted!")
    
    # Refresh channel list
    channels = get_channels()
    if not channels:
        keyboard = build_admin_panel_keyboard()
        await query.edit_message_text(
            "📭 All channels deleted.",
            reply_markup=keyboard
        )
        return ADMIN_MENU
    
    keyboard = build_channel_list_keyboard()
    await query.edit_message_text(
        f"📢 <b>Channel List</b> ({len(channels)})\n\nClick ❌ to delete.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def folder_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show folder list"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    folders = get_folders()
    if not folders:
        await query.edit_message_text(
            "📭 No folders added yet.",
            reply_markup=build_back_keyboard()
        )
        return ADMIN_MENU
    
    keyboard = build_folder_list_keyboard()
    await query.edit_message_text(
        f"📁 <b>Folder List</b> ({len(folders)})\n\nClick ❌ to delete a folder.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

async def delete_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a folder"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'delete_fld_(\d+)', query.data)
    if match:
        f_id = int(match.group(1))
        delete_folder_db(f_id)
        await query.answer("Folder deleted!")
    
    folders = get_folders()
    if not folders:
        keyboard = build_admin_panel_keyboard()
        await query.edit_message_text(
            "📭 All folders deleted.",
            reply_markup=keyboard
        )
        return ADMIN_MENU
    
    keyboard = build_folder_list_keyboard()
    await query.edit_message_text(
        f"📁 <b>Folder List</b> ({len(folders)})\n\nClick ❌ to delete.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return ADMIN_MENU

# --------------- CANCEL HANDLER ---------------

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel admin operation"""
    user_id = update.effective_user.id
    temp_data.pop(user_id, None)
    
    keyboard = build_admin_panel_keyboard()
    if update.message:
        await update.message.reply_text(
            "❌ Operation cancelled.",
            reply_markup=keyboard
        )
    else:
        query = update.callback_query
        if query:
            await query.answer()
            await query.edit_message_text(
                "❌ Operation cancelled.",
                reply_markup=keyboard
            )
    return ADMIN_MENU

# ==================== USER CALLBACK HANDLERS ====================

async def verify_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle joined button click - verify user has joined channels"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    record_user(user_id, update.effective_user.first_name or '', update.effective_user.username or '')
    
    channels = get_channels()
    folders = get_folders()
    
    if not channels and not folders:
        await show_main_menu(update, context)
        return
    
    # Check channel membership
    all_joined, not_joined = await check_user_joined_channels(context.bot, user_id)
    
    if not all_joined and not_joined:
        # User hasn't joined all channels
        not_joined_names = [ch.get('channel_name', ch.get('channel_id', 'Unknown')) for ch in not_joined]
        names_text = "\n".join([f"• {n}" for n in not_joined_names])
        
        keyboard = build_join_keyboard(channels, folders)
        await query.edit_message_text(
            f"❌ <b>You haven't joined the following channels:</b>\n\n"
            f"{names_text}\n\n"
            f"Please join them first, then click '✅ Joined' again.",
            reply_markup=keyboard,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        return
    
    # All joined - show main menu
    buttons = get_buttons()
    if not buttons:
        await query.edit_message_text(
            "✅ <b>Verified!</b>\n\nBut there are no buttons available yet. Please check back later.",
            parse_mode='HTML'
        )
        return
    
    keyboard = build_main_buttons_keyboard()
    await query.edit_message_text(
        "✅ <b>Verified!</b> Choose an option below:",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user clicking a content button"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    match = re.search(r'btn_(\d+)', query.data)
    if not match:
        return
    
    button_id = int(match.group(1))
    button = get_button(button_id)
    
    if not button:
        await query.answer("Button not found!")
        return
    
    # Check restricted mode
    if is_restricted():
        await query.answer("⚠️ Content is temporarily unavailable (Restricted Mode ON)", show_alert=True)
        return
    
    # Record click
    record_button_click(button_id, user_id)
    
    # Notify user
    await query.answer(f"Loading: {button['name']}...")
    
    # Send content
    content_list = json.loads(button.get('content', '[]'))
    
    if not content_list:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📭 No content available for '{button['name']}'"
        )
        return
    
    # Send a header
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📦 <b>{button['name']}</b>",
        parse_mode='HTML'
    )
    
    # Send each content item
    for item in content_list:
        try:
            item_type = item.get('type', 'text')
            caption = item.get('caption', '')
            file_id = item.get('file_id', '')
            text = item.get('text', '')
            
            if item_type == 'text':
                await context.bot.send_message(chat_id=user_id, text=text)
            elif item_type == 'photo':
                await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=caption or None)
            elif item_type == 'video':
                await context.bot.send_video(chat_id=user_id, video=file_id, caption=caption or None)
            elif item_type == 'document':
                await context.bot.send_document(chat_id=user_id, document=file_id, caption=caption or None)
            elif item_type == 'audio':
                await context.bot.send_audio(chat_id=user_id, audio=file_id, caption=caption or None)
            elif item_type == 'voice':
                await context.bot.send_voice(chat_id=user_id, voice=file_id)
            elif item_type == 'animation':
                await context.bot.send_animation(chat_id=user_id, animation=file_id, caption=caption or None)
            elif item_type == 'video_note':
                await context.bot.send_video_note(chat_id=user_id, video_note=file_id)
            elif item_type == 'sticker':
                await context.bot.send_sticker(chat_id=user_id, sticker=file_id)
            
            await asyncio.sleep(0.03)
        except Forbidden:
            logger.info(f"User {user_id} blocked the bot")
            break
        except Exception as e:
            logger.error(f"Error sending content to {user_id}: {e}")

async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle noop callback"""
    query = update.callback_query
    await query.answer()

# ==================== REPLY KEYBOARD BUTTON HANDLER ====================

async def handle_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user pressing a ReplyKeyboard button"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    
    record_user(user_id, update.effective_user.first_name or '', update.effective_user.username or '')
    
    # Check restricted mode
    if is_restricted():
        await update.message.reply_text("⚠️ Content is temporarily unavailable (Restricted Mode ON)")
        return
    
    # Find matching button by name
    buttons = get_buttons()
    matched_button = None
    for btn in buttons:
        if btn['name'].strip().lower() == text.lower():
            matched_button = btn
            break
    
    if not matched_button:
        return  # Not a button press, ignore
    
    # Record click
    record_button_click(matched_button['id'], user_id)
    
    # Send content
    content_list = json.loads(matched_button.get('content', '[]'))
    
    if not content_list:
        await update.message.reply_text(f"📭 No content available for '{matched_button['name']}'")
        return
    
    # Send header
    await update.message.reply_text(f"📦 <b>{matched_button['name']}</b>", parse_mode='HTML')
    
    # Send each content item
    for item in content_list:
        try:
            item_type = item.get('type', 'text')
            caption = item.get('caption', '')
            file_id = item.get('file_id', '')
            text_content = item.get('text', '')
            
            if item_type == 'text':
                await context.bot.send_message(chat_id=chat_id, text=text_content)
            elif item_type == 'photo':
                await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption or None)
            elif item_type == 'video':
                await context.bot.send_video(chat_id=chat_id, video=file_id, caption=caption or None)
            elif item_type == 'document':
                await context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption or None)
            elif item_type == 'audio':
                await context.bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption or None)
            elif item_type == 'voice':
                await context.bot.send_voice(chat_id=chat_id, voice=file_id)
            elif item_type == 'animation':
                await context.bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption or None)
            elif item_type == 'video_note':
                await context.bot.send_video_note(chat_id=chat_id, video_note=file_id)
            elif item_type == 'sticker':
                await context.bot.send_sticker(chat_id=chat_id, sticker=file_id)
            
            await asyncio.sleep(0.03)
        except Forbidden:
            logger.info(f"User {user_id} blocked the bot")
            break
        except Exception as e:
            logger.error(f"Error sending content to {user_id}: {e}")

# ==================== UPLOAD / FILE HOSTING SYSTEM ====================

# Upload conversation states
(
    UPLOAD_MAIN,
    UPLOAD_RECEIVE_FILE,
    UPLOAD_TOKEN_INPUT,
    MANAGE_BOT,
    REPLACE_FILE,
) = range(10, 15)

def build_upload_keyboard():
    """Build keyboard for /upload command"""
    bots = get_hosted_bots()
    keyboard = []
    
    keyboard.append([InlineKeyboardButton("📤 Upload New Bot File", callback_data="upload_new_file")])
    
    for bot in bots:
        status_emoji = "🟢" if bot['status'] == 'running' else "🔴"
        name = bot['file_name']
        keyboard.append([
            InlineKeyboardButton(f"{status_emoji} {name}", callback_data=f"manage_bot_{bot['id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Close", callback_data="upload_close")])
    return InlineKeyboardMarkup(keyboard)

def build_manage_bot_keyboard(bot_id: int):
    """Build keyboard for managing a specific hosted bot"""
    bot = get_hosted_bot(bot_id)
    is_running = bot['status'] == 'running' if bot else False
    
    keyboard = [
        [InlineKeyboardButton("📤 Replace/Upload File", callback_data=f"replace_file_{bot_id}")],
    ]
    
    if is_running:
        keyboard.append([
            InlineKeyboardButton("⏹️ Stop Bot", callback_data=f"stop_bot_{bot_id}"),
            InlineKeyboardButton("🔄 Restart Bot", callback_data=f"restart_bot_{bot_id}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("▶️ Start Bot", callback_data=f"start_bot_{bot_id}"),
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔑 Update Token", callback_data=f"update_token_{bot_id}"),
        InlineKeyboardButton("🗑 Delete Bot", callback_data=f"delete_bot_{bot_id}")
    ])
    keyboard.append([InlineKeyboardButton("🔙 Back to Upload List", callback_data="upload_menu")])
    return InlineKeyboardMarkup(keyboard)

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload command"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Unauthorized!")
        return ConversationHandler.END
    
    keyboard = build_upload_keyboard()
    bots = get_hosted_bots()
    
    running = sum(1 for b in bots if b['status'] == 'running')
    stopped = sum(1 for b in bots if b['status'] == 'stopped')
    
    await update.message.reply_text(
        f"📁 <b>Bot File Hosting Panel</b>\n\n"
        f"🟢 Running: <b>{running}</b>\n"
        f"🔴 Stopped: <b>{stopped}</b>\n"
        f"📊 Total: <b>{len(bots)}</b>\n\n"
        f"Select an action:",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def upload_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to upload main menu"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    keyboard = build_upload_keyboard()
    bots = get_hosted_bots()
    running = sum(1 for b in bots if b['status'] == 'running')
    stopped = sum(1 for b in bots if b['status'] == 'stopped')
    
    await query.edit_message_text(
        f"📁 <b>Bot File Hosting Panel</b>\n\n"
        f"🟢 Running: <b>{running}</b> | 🔴 Stopped: <b>{stopped}</b> | 📊 Total: <b>{len(bots)}</b>\n\n"
        f"Select an action:",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def upload_new_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new file upload flow"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    await query.edit_message_text(
        "📤 <b>Upload New Bot File</b>\n\n"
        "Send me the Python (.py) bot file.\n"
        "You can also send other files.\n\n"
        "Send /cancel to abort.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back", callback_data="upload_menu")
        ]]),
        parse_mode='HTML'
    )
    return UPLOAD_RECEIVE_FILE

async def upload_receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and save the uploaded file"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    msg = update.message
    if not msg or not msg.document:
        await update.message.reply_text("❌ Please send a file (document). /cancel to abort.")
        return UPLOAD_RECEIVE_FILE
    
    doc = msg.document
    file_name = doc.file_name or f"bot_{uuid.uuid4().hex[:8]}.py"
    
    # Download file
    file = await context.bot.get_file(doc.file_id)
    file_path = os.path.join(HOSTED_DIR, file_name)
    
    # Handle duplicate names
    counter = 1
    base, ext = os.path.splitext(file_name)
    while os.path.exists(file_path):
        file_name = f"{base}_{counter}{ext}"
        file_path = os.path.join(HOSTED_DIR, file_name)
        counter += 1
    
    await file.download_to_drive(file_path)
    
    # Save to DB
    bot_id = add_hosted_bot_db(file_name, file_path)
    
    temp_data[user_id] = {'uploaded_bot_id': bot_id, 'uploaded_file_path': file_path}
    
    # Check if it's a .py bot file
    if file_name.endswith('.py'):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Skip (No Token)", callback_data="skip_token")],
            [InlineKeyboardButton("🔙 Back", callback_data="upload_menu")],
        ])
        await update.message.reply_text(
            f"✅ File <b>{file_name}</b> saved!\n\n"
            f"🆔 Bot ID: <code>{bot_id}</code>\n\n"
            f"This is a Python file. Send me the <b>Bot Token</b> to run it as a Telegram bot.\n\n"
            f"Format: <code>123456:ABCdef...</code>\n"
            f"Or click 'Skip' to save without token.",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return UPLOAD_TOKEN_INPUT
    else:
        keyboard = build_upload_keyboard()
        await update.message.reply_text(
            f"✅ File <b>{file_name}</b> saved!\n🆔 Bot ID: <code>{bot_id}</code>",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        temp_data.pop(user_id, None)
        return UPLOAD_MAIN

async def upload_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive bot token and start the bot"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    token = update.message.text.strip()
    bot_id = temp_data.get(user_id, {}).get('uploaded_bot_id')
    
    if not bot_id:
        await update.message.reply_text("❌ Session expired. Use /upload again.")
        return ConversationHandler.END
    
    # Validate token format
    if ':' not in token or len(token) < 20:
        await update.message.reply_text("❌ Invalid token format. Send again or /cancel")
        return UPLOAD_TOKEN_INPUT
    
    update_hosted_bot_token(bot_id, token)
    
    # Let user know - but DON'T auto-start (security, let them start manually)
    keyboard = build_manage_bot_keyboard(bot_id)
    bot = get_hosted_bot(bot_id)
    await update.message.reply_text(
        f"🔑 Token saved for <b>{bot['file_name']}</b>!\n\n"
        f"🆔 Bot ID: <code>{bot_id}</code>\n"
        f"Use the buttons below to manage:",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    temp_data.pop(user_id, None)
    return UPLOAD_MAIN

async def upload_skip_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip token input"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    bot_id = temp_data.get(user_id, {}).get('uploaded_bot_id')
    temp_data.pop(user_id, None)
    
    keyboard = build_upload_keyboard()
    await query.edit_message_text(
        "✅ File saved without token.\nYou can add a token later.",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def manage_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle managing a specific bot"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'manage_bot_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    bot = get_hosted_bot(bot_id)
    if not bot:
        await query.answer("Bot not found!")
        return UPLOAD_MAIN
    
    # Check actual running status
    actual_running = is_bot_running(bot_id)
    if actual_running != (bot['status'] == 'running'):
        # Sync status
        pass
    
    bot = get_hosted_bot(bot_id)  # Refresh after status check
    
    keyboard = build_manage_bot_keyboard(bot_id)
    
    status_emoji = "🟢" if actual_running else "🔴"
    status_text = "RUNNING" if actual_running else "STOPPED"
    
    # Get log snippet
    log_file = os.path.join(HOSTED_DIR, f"bot_{bot_id}.log")
    log_snippet = ""
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()[-5:]
                log_snippet = ''.join(lines)
            if log_snippet:
                log_snippet = f"\n\n<b>📋 Recent Log:</b>\n<code>{log_snippet[:300]}</code>"
        except:
            pass
    
    await query.edit_message_text(
        f"🤖 <b>{bot['file_name']}</b>\n\n"
        f"🆔 ID: <code>{bot_id}</code>\n"
        f"📊 Status: {status_emoji} <b>{status_text}</b>\n"
        f"🔑 Token: {'✅ Set' if bot.get('bot_token') else '❌ Not set'}\n"
        f"📁 Path: <code>{bot['file_path']}</code>\n"
        f"📅 Uploaded: {bot.get('uploaded_at', 'Unknown')}"
        f"{log_snippet}",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def start_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a hosted bot"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'start_bot_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    bot = get_hosted_bot(bot_id)
    
    if not bot.get('bot_token'):
        await query.answer("⚠️ Set bot token first!", show_alert=True)
        # Ask for token
        temp_data[user_id] = {'uploaded_bot_id': bot_id}
        await query.edit_message_text(
            f"🔑 Send the Bot Token for <b>{bot['file_name']}</b>:\n\n"
            f"Format: <code>123456:ABCdef...</code>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data=f"manage_bot_{bot_id}")
            ]]),
            parse_mode='HTML'
        )
        return UPLOAD_TOKEN_INPUT
    
    success, msg, pid = start_hosted_bot(bot_id)
    
    if success:
        keyboard = build_manage_bot_keyboard(bot_id)
        await query.edit_message_text(
            f"▶️ {msg}",
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    else:
        await query.answer(f"❌ {msg}", show_alert=True)
    
    return UPLOAD_MAIN

async def stop_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop a hosted bot"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'stop_bot_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    success, msg = stop_hosted_bot(bot_id)
    
    keyboard = build_manage_bot_keyboard(bot_id)
    await query.edit_message_text(
        f"⏹️ {msg}",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def restart_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart a hosted bot"""
    query = update.callback_query
    await query.answer("Restarting...")
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'restart_bot_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    success, msg = restart_hosted_bot(bot_id)
    
    keyboard = build_manage_bot_keyboard(bot_id)
    await query.edit_message_text(
        f"🔄 {msg}",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def delete_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a hosted bot"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'delete_bot_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    bot = get_hosted_bot(bot_id)
    
    # Stop if running
    if is_bot_running(bot_id):
        stop_hosted_bot(bot_id)
    
    # Delete file
    if bot and os.path.exists(bot['file_path']):
        try:
            os.remove(bot['file_path'])
        except:
            pass
    
    # Delete log
    log_file = os.path.join(HOSTED_DIR, f"bot_{bot_id}.log")
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except:
            pass
    
    name = bot['file_name'] if bot else 'Unknown'
    delete_hosted_bot_db(bot_id)
    
    keyboard = build_upload_keyboard()
    await query.edit_message_text(
        f"🗑 <b>{name}</b> deleted successfully!",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def update_token_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update bot token"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'update_token_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    bot = get_hosted_bot(bot_id)
    temp_data[user_id] = {'uploaded_bot_id': bot_id}
    
    await query.edit_message_text(
        f"🔑 Send new Bot Token for <b>{bot['file_name']}</b>:\n\n"
        f"Current: {'✅ Set' if bot.get('bot_token') else '❌ Not set'}\n"
        f"Format: <code>123456:ABCdef...</code>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back", callback_data=f"manage_bot_{bot_id}")
        ]]),
        parse_mode='HTML'
    )
    return UPLOAD_TOKEN_INPUT

async def replace_file_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start replacing bot file"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    match = re.search(r'replace_file_(\d+)', query.data)
    if not match:
        return UPLOAD_MAIN
    
    bot_id = int(match.group(1))
    bot = get_hosted_bot(bot_id)
    temp_data[user_id] = {'replacing_bot_id': bot_id}
    
    await query.edit_message_text(
        f"📤 <b>Replace File</b>\n\n"
        f"Current: <b>{bot['file_name']}</b>\n\n"
        f"Send me the new file to replace it.\n"
        f"/cancel to abort.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back", callback_data=f"manage_bot_{bot_id}")
        ]]),
        parse_mode='HTML'
    )
    return REPLACE_FILE

async def replace_file_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive replacement file"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    msg = update.message
    if not msg or not msg.document:
        await update.message.reply_text("❌ Please send a file. /cancel to abort.")
        return REPLACE_FILE
    
    bot_id = temp_data.get(user_id, {}).get('replacing_bot_id')
    if not bot_id:
        return ConversationHandler.END
    
    bot = get_hosted_bot(bot_id)
    if not bot:
        return ConversationHandler.END
    
    # Stop if running
    if is_bot_running(bot_id):
        stop_hosted_bot(bot_id)
    
    # Delete old file
    if os.path.exists(bot['file_path']):
        try:
            os.remove(bot['file_path'])
        except:
            pass
    
    # Save new file
    doc = msg.document
    file_name = doc.file_name or f"bot_{uuid.uuid4().hex[:8]}.py"
    file_path = os.path.join(HOSTED_DIR, file_name)
    
    file = await context.bot.get_file(doc.file_id)
    await file.download_to_drive(file_path)
    
    # Update DB - keep the same record but new file
    conn = get_db()
    conn.execute("UPDATE hosted_bots SET file_name=?, file_path=? WHERE id=?", 
                 (file_name, file_path, bot_id))
    conn.commit()
    conn.close()
    
    temp_data.pop(user_id, None)
    
    keyboard = build_manage_bot_keyboard(bot_id)
    await update.message.reply_text(
        f"✅ File replaced!\nNew: <b>{file_name}</b>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return UPLOAD_MAIN

async def upload_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close upload panel"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📁 Upload panel closed.")
    return ConversationHandler.END

async def upload_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel upload operation"""
    user_id = update.effective_user.id
    temp_data.pop(user_id, None)
    
    keyboard = build_upload_keyboard()
    if update.message:
        await update.message.reply_text("❌ Cancelled.", reply_markup=keyboard, parse_mode='HTML')
    else:
        query = update.callback_query
        if query:
            await query.answer()
            await query.edit_message_text("❌ Cancelled.", reply_markup=keyboard, parse_mode='HTML')
    return UPLOAD_MAIN

# ==================== ERROR HANDLER ====================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors"""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    
    if update and hasattr(update, 'effective_chat'):
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ An error occurred. Please try again later."
            )
        except:
            pass

# ==================== MAIN ====================

def main() -> None:
    """Start the bot"""
    logger.info("Starting bot...")
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ===== ADMIN CONVERSATION HANDLER =====
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_command)],
        states={
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
                CallbackQueryHandler(admin_refresh, pattern='^admin_refresh$'),
                CallbackQueryHandler(add_channel_start, pattern='^add_channel$'),
                CallbackQueryHandler(add_folder_start, pattern='^add_folder$'),
                CallbackQueryHandler(add_button_start, pattern='^add_button$'),
                CallbackQueryHandler(edit_buttons_list, pattern='^edit_buttons$'),
                CallbackQueryHandler(edit_button_selected, pattern=r'^edit_btn_\d+$'),
                CallbackQueryHandler(rename_button_start, pattern=r'^rename_btn_\d+$'),
                CallbackQueryHandler(add_content_to_button_start, pattern=r'^addcontent_btn_\d+$'),
                CallbackQueryHandler(clear_button_content, pattern=r'^clear_btn_\d+$'),
                CallbackQueryHandler(delete_button, pattern=r'^delete_btn_\d+$'),
                CallbackQueryHandler(broadcast_start, pattern='^broadcast$'),
                CallbackQueryHandler(show_stats, pattern='^stats$'),
                CallbackQueryHandler(toggle_restricted, pattern='^toggle_restricted$'),
                CallbackQueryHandler(channel_list, pattern='^channel_list$'),
                CallbackQueryHandler(delete_channel, pattern=r'^delete_ch_\d+$'),
                CallbackQueryHandler(folder_list, pattern='^folder_list$'),
                CallbackQueryHandler(delete_folder, pattern=r'^delete_fld_\d+$'),
                CallbackQueryHandler(noop_handler, pattern='^noop$'),
            ],
            ADDING_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_channel_save),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            ADDING_FOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_folder_save),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            ADDING_BUTTON_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_button_get_name),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            ADDING_BUTTON_CONTENT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, add_button_get_content),
                CommandHandler('done', add_button_done),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            RENAMING_BUTTON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_button_save),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            ADDING_CONTENT_TO_BUTTON: [
                MessageHandler(filters.ALL & ~filters.COMMAND, add_content_to_button_collect),
                CommandHandler('done', add_content_to_button_done),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            BROADCASTING: [
                MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_receive),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(broadcast_confirm, pattern='^broadcast_confirm$'),
                CallbackQueryHandler(admin_menu_handler, pattern='^admin_menu$'),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', admin_cancel),
            CommandHandler('admin', admin_command),
        ],
        per_user=True,
        per_chat=False,
    )
    
    app.add_handler(admin_conv)
    
    # ===== USER HANDLERS =====
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CallbackQueryHandler(verify_join_handler, pattern='^verify_join$'))
    app.add_handler(CallbackQueryHandler(button_click_handler, pattern=r'^btn_\d+$'))
    
    # ===== ERROR HANDLER =====
    app.add_error_handler(error_handler)
    
    # ===== SET BOT COMMANDS =====
    async def set_commands(app):
        commands = [
            BotCommand('start', '🚀 Start the bot'),
            BotCommand('admin', '🛡️ Admin panel (admin only)'),
        ]
        await app.bot.set_my_commands(commands)
    
    app.post_init = set_commands
    
    # ===== START BOT =====
    logger.info("Bot is running... Press Ctrl+C to stop.")
    print("\n" + "="*50)
    print("🤖 Bot is now running!")
    print(f"📊 Database: {DB_PATH}")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print("📝 Send /start to test the bot")
    print("🛡️ Send /admin to open admin panel")
    print("Press Ctrl+C to stop")
    print("="*50 + "\n")
    
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        print(f"\n❌ Fatal error: {e}")
