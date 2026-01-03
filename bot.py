import os
import sys
import time
import subprocess
import logging
import asyncio
import re
import urllib.parse
import json
import html
import copy
import psutil
import signal
import requests
from datetime import timedelta
from typing import Dict, Union, Optional

# LIBRARY PYROFORK (Instal: pip install pyrofork tgcrypto)
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
    ForceReply
)
from pyrogram.errors import FloodWait

# =========================
# LOAD CONFIG FROM .env
# =========================
from config import (
    API_ID, API_HASH, BOT_TOKEN, OWNER_ID,
    RCLONE_REMOTE, RCLONE_FOLDER,
    SEEDBOX_ENABLED, SEEDBOX_USER, SEEDBOX_PASS, SEEDBOX_FB_URL, SEEDBOX_FB_SHARE_HASH,
    MIRRORED_ENABLED, MIRRORED_API_KEY, MIRRORED_MIRRORS,
    BUZZHEAVIER_ENABLED, BUZZHEAVIER_ACCOUNT_ID,
    GOFILE_ENABLED, GOFILE_TOKEN,
    FILEPRESS_ENABLED, FILEPRESS_DOMAIN, FILEPRESS_API_KEY,
    TURBOVID_ENABLED, TURBOVID_API_KEY,
    ABYSS_ENABLED, ABYSS_API_KEY,
    VIDHIDE_ENABLED, VIDHIDE_API_KEY, VIDHIDE_DOMAIN,
    DEFAULT_FONT_SIZE, DEFAULT_MARGIN_V, SUB_FONT_NAME, SUB_IS_BOLD, CRF_VALUE,
    WATERMARK_ENABLED, WATERMARK_TEXT, WATERMARK_FONTSIZE, WATERMARK_DURATION, WATERMARK_FONT,
    HEAUDIO_MAP, AACLCAUDIO_MAP, VIDEO_2PASS_MAP,
    DATA_FOLDER, CACHE_FOLDER, MANUAL_FOLDER, TOOLS_FOLDER, OUTPUT_FOLDER,
    DOWNLOAD_TIMEOUT
)

# Encoding Templates (dari file JSON)
TEMPLATES_FILE = os.path.join(DATA_FOLDER, "templates.json")
DEFAULT_TEMPLATES = {
    "t1": {"name": "1080p CRF24 F16", "res": "1080p", "audio": "he", "mode": "crf", "crf": "24", "font": 16, "margin": 25},
    "t2": {"name": "1080p CRF24 F15 M40", "res": "1080p", "audio": "he", "mode": "crf", "crf": "24", "font": 15, "margin": 40},
    "t3": {"name": "720p CRF24 F15", "res": "720p", "audio": "he", "mode": "crf", "crf": "24", "font": 15, "margin": 25},
    "t4": {"name": "720p CRF24 F15 M40", "res": "720p", "audio": "he", "mode": "crf", "crf": "24", "font": 15, "margin": 40},
    "t5": {"name": "360p 2Pass F16", "res": "360p", "audio": "he", "mode": "2pass", "crf": "26", "font": 16, "margin": 25},
}

def load_templates():
    if os.path.exists(TEMPLATES_FILE):
        with open(TEMPLATES_FILE, "r") as f:
            return json.load(f)
    # Jika file tidak ada, buat folder data dulu lalu simpan default
    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)
    save_templates(DEFAULT_TEMPLATES)
    return DEFAULT_TEMPLATES.copy()

def save_templates(data):
    with open(TEMPLATES_FILE, "w") as f:
        json.dump(data, f, indent=2)

TEMPLATES = load_templates()

# Download timeout (detik) - 30 menit
DOWNLOAD_TIMEOUT = 1800

# =========================
# LOGGING
# =========================
# Ensure data folder exists before logging
if not os.path.exists("data"):
    os.makedirs("data")

# Migrate old config files to data folder (one-time migration)
_OLD_FILES_TO_MIGRATE = [
    ("auth_users.json", "auth_users.json"),
    ("templates.json", "templates.json"),
    ("file_cache.json", "file_cache.json"),
    ("bot_log.txt", "bot_log.txt"),
    ("bot_encode_session.session", "bot_encode_session.session"),
]
for old_name, new_name in _OLD_FILES_TO_MIGRATE:
    old_path = old_name
    new_path = os.path.join("data", new_name)
    if os.path.exists(old_path) and not os.path.exists(new_path):
        try:
            import shutil
            shutil.move(old_path, new_path)
            print(f"[Migration] Moved {old_name} → data/{new_name}")
        except Exception as e:
            print(f"[Migration] Failed to move {old_name}: {e}")

# Migrate tools files to tools folder
if not os.path.exists("tools"):
    os.makedirs("tools")
_TOOLS_TO_MIGRATE = ["link_formatter.py"]
for tool_file in _TOOLS_TO_MIGRATE:
    old_path = tool_file
    new_path = os.path.join("tools", tool_file)
    if os.path.exists(old_path) and not os.path.exists(new_path):
        try:
            import shutil
            shutil.move(old_path, new_path)
            print(f"[Migration] Moved {tool_file} → tools/{tool_file}")
        except Exception as e:
            print(f"[Migration] Failed to move {tool_file}: {e}")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    filename=os.path.join("data", "bot_log.txt"),
)
logger = logging.getLogger(__name__)

# =========================
# SYSTEM STATE & AUTH
# =========================
JOB_QUEUE = []
IS_WORKING = False
CURRENT_JOB = None
ACTIVE_PROCESSES = {}
STATUS_DASHBOARD = {}
USER_DATA = {}
PENDING_SRT_JOBS = {}  # {chat_id: [{"job": job, "file": downloaded_file_path, "msg_id": msg_id}, ...]}
BOT_START_TIME = time.time()

# FILE CACHE SYSTEM
CACHE_FOLDER = "raw_cache"
MANUAL_FOLDER = "manual"  # Folder untuk file yang ditambahkan manual
TOOLS_FOLDER = "tools"    # Folder untuk script tools (link_formatter, dll)
OUTPUT_FOLDER = "output"  # Folder untuk file hasil encode (hidden)
CACHE_REGISTRY_FILE = os.path.join(DATA_FOLDER, "file_cache.json")
FILE_CACHE = {}  # {id: {"path": filepath, "name": realname, "size": bytes, "added": timestamp}}

# ENCODE HISTORY SYSTEM (for /links command)
ENCODE_HISTORY_FILE = os.path.join(DATA_FOLDER, "encode_history.json")
ENCODE_HISTORY = []  # List of encode results: [{filename, quality, timestamp, links, meta}, ...]

def ensure_cache_folder():
    """Create cache folders (Linux version - no hidden folders)."""
    for folder in [CACHE_FOLDER, MANUAL_FOLDER, DATA_FOLDER, TOOLS_FOLDER, OUTPUT_FOLDER]:
        os.makedirs(folder, exist_ok=True)

def load_file_cache():
    global FILE_CACHE
    if os.path.exists(CACHE_REGISTRY_FILE):
        try:
            with open(CACHE_REGISTRY_FILE, 'r') as f:
                FILE_CACHE = json.load(f)
            # Clean up entries with missing files
            FILE_CACHE = {k: v for k, v in FILE_CACHE.items() if os.path.exists(v.get('path', ''))}
            save_file_cache()
        except:
            FILE_CACHE = {}

def save_file_cache():
    with open(CACHE_REGISTRY_FILE, 'w') as f:
        json.dump(FILE_CACHE, f, indent=2)

def load_encode_history():
    """Load encode history from file"""
    global ENCODE_HISTORY
    if os.path.exists(ENCODE_HISTORY_FILE):
        try:
            with open(ENCODE_HISTORY_FILE, 'r') as f:
                ENCODE_HISTORY = json.load(f)
        except:
            ENCODE_HISTORY = []

def save_encode_history():
    """Save encode history to file"""
    with open(ENCODE_HISTORY_FILE, 'w') as f:
        json.dump(ENCODE_HISTORY, f, indent=2, ensure_ascii=False)

def add_to_encode_history(filename: str, quality: str, links: dict, meta: dict = None):
    """Add encode result to history"""
    from datetime import datetime
    entry = {
        "filename": filename,
        "quality": quality,
        "timestamp": datetime.now().isoformat(),
        "links": links,
        "meta": meta or {}
    }
    ENCODE_HISTORY.append(entry)
    save_encode_history()
    return entry

def clear_encode_history():
    """Clear all encode history"""
    global ENCODE_HISTORY
    ENCODE_HISTORY = []
    save_encode_history()


def get_next_cache_id():
    if not FILE_CACHE:
        return "1"
    return str(max(int(k) for k in FILE_CACHE.keys()) + 1)

def add_to_cache(filepath, realname):
    """Add file to cache and return ID"""
    ensure_cache_folder()
    cache_id = get_next_cache_id()
    size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    FILE_CACHE[cache_id] = {
        "path": filepath,
        "name": realname,
        "size": size,
        "added": time.time()
    }
    save_file_cache()
    return cache_id

# Load cache on start
ensure_cache_folder()
load_file_cache()
load_encode_history()

# AUTHENTICATION SYSTEM
AUTH_FILE = os.path.join(DATA_FOLDER, "auth_users.json")
AUTH_USERS = set()

def load_auth():
    global AUTH_USERS
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, 'r') as f:
                data = json.load(f)
                AUTH_USERS = set(data)
        except:
            AUTH_USERS = set()

def save_auth():
    with open(AUTH_FILE, 'w') as f:
        json.dump(list(AUTH_USERS), f)

def check_auth(user_id):
    """Cek apakah user boleh menggunakan bot"""
    return user_id == OWNER_ID or user_id in AUTH_USERS

# Load saat start
load_auth()

# Enums untuk State
S_RES = 1
S_AUDIO = 2
S_MODE = 3
S_FONT = 4
S_MARGIN = 5
S_SUB = 6
S_WAIT_SRT = 7


# =====================================================
# UTILS & HELPERS
# =====================================================

def get_hidden_params():
    """Linux version - no params needed (no console hiding)."""
    return {}

def create_progress_bar(percent: float, length: int = 20) -> str:
    if percent < 0: percent = 0
    if percent > 100: percent = 100
    filled = int(length * percent / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"<code>{bar}</code> <b>{percent:5.1f}%</b>"

def get_cancel_markup(other_rows=None) -> InlineKeyboardMarkup:
    cancel_btn = [InlineKeyboardButton("❌ BATAL / STOP", callback_data="cancel")]
    rows = other_rows[:] if other_rows else []
    rows.append(cancel_btn)
    return InlineKeyboardMarkup(rows)

def build_template_keyboard() -> InlineKeyboardMarkup:
    """Build dynamic template buttons from TEMPLATES dict"""
    rows = []
    for key, tpl in TEMPLATES.items():
        # Build detailed label
        res_crf = tpl.get('res_crf', {})
        if res_crf:
            # Multi-res: "360p(28)+1080p(22)"
            parts = [f"{r}({c})" for r, c in res_crf.items()]
            res_info = "+".join(parts)
        else:
            # Single-res: "1080p CRF24"
            res_info = f"{tpl['res']} CRF{tpl.get('crf', '26')}"
        
        # Format: "⚡ 360p(28)+1080p(22) | F16 M25"
        label = f"⚡ {res_info} | F{tpl['font']} M{tpl['margin']}"
        if len(label) > 40:
            label = label[:37] + "..."
        
        btn = InlineKeyboardButton(label, f"tpl_{key}")
        rows.append([btn])  # 1 per baris untuk lebih jelas
    
    # Add manual option
    rows.append([InlineKeyboardButton("─── Manual ───", "ignore")])
    rows.append([InlineKeyboardButton("🎛️ Pilih Manual", "manual_mode")])
    rows.append([InlineKeyboardButton("❌ Tutup", "close_menu")])
    return InlineKeyboardMarkup(rows)

def time_str_to_seconds(time_str: str) -> float:
    try:
        h, m, s = time_str.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except:
        return 0.0

def human_readable_size(size: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def force_kill_process(proc):
    try:
        if os.name == 'nt':
            # Gunakan params tersembunyi juga untuk taskkill
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)], 
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            **get_hidden_params())
        else:
            os.kill(proc.pid, signal.SIGKILL)
    except:
        pass

def filebrowser_upload_file(local_path: str, chat_id: int = None, res: str = None) -> str:
    """Upload file ke seedbox via FileBrowser API (HTTP). Returns: download URL atau None jika gagal."""
    if not SEEDBOX_ENABLED:
        return None
    
    try:
        filename = os.path.basename(local_path)
        file_size = os.path.getsize(local_path)
        
        # 1. Login ke FileBrowser untuk dapat token
        login_url = f"{SEEDBOX_FB_URL}/api/login"
        login_resp = requests.post(login_url, json={
            "username": SEEDBOX_USER,
            "password": SEEDBOX_PASS
        }, timeout=30)
        
        if login_resp.status_code != 200:
            logger.error(f"FileBrowser login failed: {login_resp.status_code}")
            return None
        
        token = login_resp.text
        headers = {"X-Auth": token}
        
        # 2. Upload file via API
        # FileBrowser API: POST /api/resources/{path}
        encoded_filename = urllib.parse.quote(filename)
        upload_url = f"{SEEDBOX_FB_URL}/api/resources/downloads/upload/{encoded_filename}"
        
        # Upload dengan progress tracking
        uploaded = [0]
        last_update = [time.time()]
        
        def file_reader_with_progress():
            chunk_size = 1024 * 1024  # 1MB chunks
            with open(local_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    uploaded[0] += len(chunk)
                    
                    # Update progress setiap 1 detik
                    if chat_id and res and time.time() - last_update[0] > 1:
                        pct = (uploaded[0] / file_size) * 100
                        if chat_id in STATUS_DASHBOARD and res in STATUS_DASHBOARD[chat_id].get("resolutions", {}):
                            STATUS_DASHBOARD[chat_id]["resolutions"][res]["pct"] = pct
                        last_update[0] = time.time()
                    
                    yield chunk
        
        # POST dengan streaming body
        upload_resp = requests.post(
            upload_url,
            headers=headers,
            data=file_reader_with_progress(),
            timeout=3600  # 1 hour timeout for large files
        )
        
        if upload_resp.status_code not in [200, 201]:
            logger.error(f"FileBrowser upload failed: {upload_resp.status_code} - {upload_resp.text}")
            return None
        
        # 3. Generate download URL
        fb_link = f"{SEEDBOX_FB_URL}/api/public/dl/{SEEDBOX_FB_SHARE_HASH}/{encoded_filename}"
        logger.info(f"FileBrowser Upload Success: {filename}")
        return fb_link
        
    except Exception as e:
        logger.error(f"FileBrowser Upload Error: {e}")
        return None

def mirrored_upload_file(local_path: str) -> str:
    """Upload file ke Mirrored.to. Returns: mir.cr short link atau None jika gagal."""
    if not MIRRORED_ENABLED:
        return None
    
    try:
        filename = os.path.basename(local_path)
        file_size_mb = os.path.getsize(local_path) / (1024 * 1024)
        
        # Step 1: Get Upload Info (POST required)
        resp1 = requests.post(
            "https://www.mirrored.to/api/v1/get_upload_info",
            data={"api_key": MIRRORED_API_KEY},
            timeout=30
        ).json()
        
        if "message" not in resp1 or "upload_id" not in resp1.get("message", {}):
            logger.error(f"Mirrored get_upload_info failed: {resp1}")
            return None
        
        msg = resp1["message"]
        upload_id = msg["upload_id"]
        file_upload_url = msg["file_upload_url"]
        max_filesize = msg.get("max_filesize", 500)
        
        # Check file size
        if file_size_mb > max_filesize:
            logger.error(f"File too large for Mirrored.to: {file_size_mb:.1f}MB > {max_filesize}MB")
            return None
        
        logger.info(f"Mirrored upload_id: {upload_id}")
        
        # Step 2: Upload File
        with open(local_path, 'rb') as f:
            resp2 = requests.post(
                file_upload_url,
                data={"api_key": MIRRORED_API_KEY, "upload_id": upload_id},
                files={"Filedata": (filename, f)},
                timeout=3600  # 1 hour for large files
            ).json()
        
        if "message" not in resp2 or "success" not in resp2.get("message", "").lower():
            logger.error(f"Mirrored file upload failed: {resp2}")
            return None
        
        logger.info(f"Mirrored file uploaded, generating links...")
        
        # Step 3: Generate Download Links (POST required)
        resp3 = requests.post(
            "https://www.mirrored.to/api/v1/finish_upload",
            data={
                "api_key": MIRRORED_API_KEY,
                "upload_id": upload_id,
                "mirrors": MIRRORED_MIRRORS
            },
            timeout=60
        ).json()
        
        msg3 = resp3.get("message", {})
        if isinstance(msg3, dict) and "short_url" in msg3:
            logger.info(f"Mirrored upload success: {msg3['short_url']}")
            return msg3["short_url"]
        elif isinstance(msg3, dict) and "full_url" in msg3:
            return msg3["full_url"]
        else:
            logger.error(f"Mirrored finish_upload failed: {resp3}")
            return None
        
    except Exception as e:
        logger.error(f"Mirrored Upload Error: {e}")
        return None

def buzzheavier_upload_file(local_path: str) -> str:
    """Upload file ke Buzzheavier (to user directory). Returns: download URL atau None jika gagal."""
    if not BUZZHEAVIER_ENABLED:
        return None
    
    try:
        filename = os.path.basename(local_path)
        headers = {"Authorization": f"Bearer {BUZZHEAVIER_ACCOUNT_ID}"}
        
        # Step 1: Get root directory ID
        root_resp = requests.get(
            "https://buzzheavier.com/api/fs",
            headers=headers,
            timeout=30
        )
        
        if root_resp.status_code != 200:
            logger.error(f"Buzzheavier get root dir failed: {root_resp.status_code}")
            return None
        
        root_data = root_resp.json()
        # Get the root directory ID from response
        parent_id = None
        if "data" in root_data and isinstance(root_data["data"], dict):
            parent_id = root_data["data"].get("id")
        elif "id" in root_data:
            parent_id = root_data["id"]
        
        if not parent_id:
            logger.error(f"Buzzheavier: cannot find root dir ID: {root_data}")
            return None
        
        logger.info(f"Buzzheavier root dir ID: {parent_id}")
        
        # Step 2: Upload to user directory with parentId
        upload_url = f"https://w.buzzheavier.com/{parent_id}/{urllib.parse.quote(filename)}"
        
        with open(local_path, 'rb') as f:
            resp = requests.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {BUZZHEAVIER_ACCOUNT_ID}",
                    "Content-Type": "application/octet-stream"
                },
                data=f,
                timeout=7200
            )
        
        logger.info(f"Buzzheavier response: {resp.status_code} - {resp.text[:500]}")
        
        if resp.status_code in [200, 201, 202]:
            try:
                resp_data = resp.json()
                
                # Handle nested response: {"code":201,"data":{"id":"xxx",...}}
                if "data" in resp_data and isinstance(resp_data["data"], dict):
                    file_data = resp_data["data"]
                    if "id" in file_data:
                        link = f"https://buzzheavier.com/{file_data['id']}"
                        logger.info(f"Buzzheavier Upload Success: {link}")
                        return link
                
                # Fallback: direct id in response
                if "id" in resp_data:
                    link = f"https://buzzheavier.com/{resp_data['id']}"
                    logger.info(f"Buzzheavier Upload Success: {link}")
                    return link
                    
            except Exception as parse_err:
                logger.error(f"Buzzheavier parse error: {parse_err}")
        
        logger.error(f"Buzzheavier upload failed: {resp.status_code} - {resp.text[:300]}")
        return None
        
    except Exception as e:
        logger.error(f"Buzzheavier Upload Error: {e}")
        return None

def gofile_upload_file(local_path: str) -> str:
    """Upload file ke Gofile.io. Returns: download URL atau None jika gagal."""
    if not GOFILE_ENABLED:
        return None
    
    try:
        filename = os.path.basename(local_path)
        
        # Step 1: Get best server
        server_resp = requests.get("https://api.gofile.io/servers", timeout=30).json()
        if server_resp.get("status") != "ok":
            logger.error(f"Gofile get server failed: {server_resp}")
            return None
        
        server = server_resp["data"]["servers"][0]["name"]
        
        # Step 2: Upload file
        with open(local_path, 'rb') as f:
            resp = requests.post(
                f"https://{server}.gofile.io/contents/uploadfile",
                headers={"Authorization": f"Bearer {GOFILE_TOKEN}"},
                files={"file": (filename, f)},
                timeout=3600
            )
        
        data = resp.json()
        if data.get("status") == "ok":
            download_page = data["data"]["downloadPage"]
            logger.info(f"Gofile Upload Success: {download_page}")
            return download_page
        
        logger.error(f"Gofile upload failed: {data}")
        return None
        
    except Exception as e:
        logger.error(f"Gofile Upload Error: {e}")
        return None

def extract_gdrive_file_id(url_or_id: str) -> str:
    """Extract Google Drive file ID from URL or return as-is if already an ID"""
    if not url_or_id:
        return None
    
    # Already an ID (no slashes or dots)
    if "/" not in url_or_id and "." not in url_or_id:
        return url_or_id
    
    # Extract from various GDrive URL formats
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",  # /file/d/ID
        r"id=([a-zA-Z0-9_-]+)",        # ?id=ID
        r"/open\?id=([a-zA-Z0-9_-]+)", # /open?id=ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    
    return None

def filepress_mirror(gdrive_url_or_id: str, quality: int = None) -> str:
    """Mirror Google Drive file to FilePress. Returns FilePress link or None."""
    if not FILEPRESS_ENABLED:
        return None
    
    try:
        file_id = extract_gdrive_file_id(gdrive_url_or_id)
        if not file_id:
            logger.error(f"FilePress: Could not extract GDrive file ID from: {gdrive_url_or_id}")
            return None
        
        payload = {
            "key": FILEPRESS_API_KEY,
            "id": file_id
        }
        
        # Add quality if provided
        if quality:
            payload["quality"] = quality
        
        resp = requests.post(
            f"{FILEPRESS_DOMAIN}/api/v1/file/add",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60
        )
        
        logger.info(f"FilePress response: {resp.status_code} - {resp.text[:500]}")
        
        if resp.status_code == 200:
            data = resp.json()
            # Response should contain file ID or link
            if data.get("_id"):
                link = f"{FILEPRESS_DOMAIN}/file/{data['_id']}"
                logger.info(f"FilePress Mirror Success: {link}")
                return link
            elif data.get("id"):
                link = f"{FILEPRESS_DOMAIN}/file/{data['id']}"
                logger.info(f"FilePress Mirror Success: {link}")
                return link
            elif data.get("link"):
                logger.info(f"FilePress Mirror Success: {data['link']}")
                return data["link"]
            else:
                # Log keys for debugging
                logger.info(f"FilePress response keys: {data.keys()}")
                # Try to find any ID-like value
                for key in ["fileId", "file_id", "data"]:
                    if key in data:
                        val = data[key]
                        if isinstance(val, str):
                            return f"{FILEPRESS_DOMAIN}/file/{val}"
                        elif isinstance(val, dict) and "_id" in val:
                            return f"{FILEPRESS_DOMAIN}/file/{val['_id']}"
        
        logger.error(f"FilePress mirror failed: {resp.status_code} - {resp.text[:300]}")
        return None
        
    except Exception as e:
        logger.error(f"FilePress Mirror Error: {e}")
        return None

def turbovid_remote_upload(seedbox_url: str, filename: str) -> str:
    """Remote upload to TurboVidHLS via Seedbox direct link. Returns embed URL."""
    if not TURBOVID_ENABLED or not seedbox_url:
        return None
    
    try:
        # API: https://api.turboviplay.com/uploadUrl?keyApi={key}&url={url}&newTitle={title}
        resp = requests.get(
            "https://api.turboviplay.com/uploadUrl",
            params={
                "keyApi": TURBOVID_API_KEY,
                "url": seedbox_url,
                "newTitle": filename
            },
            timeout=120
        )
        
        data = resp.json()
        logger.info(f"TurboVid response: {data}")
        
        # Check for videoID in response (actual API returns videoID directly)
        if data.get("videoID"):
            video_id = data["videoID"]
            embed_url = f"https://turbovidhls.com/t/{video_id}"
            logger.info(f"TurboVid Upload Success: {embed_url}")
            return embed_url
        
        # Fallback: check old format
        if data.get("msg") == "OK" and data.get("status") == 200:
            if data.get("result") and "turbovidhls.com/t/" in str(data["result"]):
                return data["result"]
        
        logger.error(f"TurboVid upload failed: {data}")
        return None
        
    except Exception as e:
        logger.error(f"TurboVid Remote Upload Error: {e}")
        return None

def abyss_remote_upload(gdrive_url: str) -> str:
    """Remote upload to Abyss.to via GDrive file ID. Returns short URL."""
    if not ABYSS_ENABLED or not gdrive_url:
        return None
    
    try:
        file_id = extract_gdrive_file_id(gdrive_url)
        if not file_id:
            logger.error(f"Abyss: Could not extract GDrive file ID from: {gdrive_url}")
            return None
        
        logger.info(f"Abyss: Uploading file_id={file_id}")
        
        # API: POST https://api.abyss.to/v1/remote/{fileId}
        resp = requests.post(
            f"https://api.abyss.to/v1/remote/{file_id}",
            headers={
                "Authorization": f"Bearer {ABYSS_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=120
        )
        
        # Log raw response for debugging
        logger.info(f"Abyss HTTP Status: {resp.status_code}")
        logger.info(f"Abyss Raw Response: {resp.text[:500] if resp.text else 'EMPTY'}")
        
        # Check if response is empty
        if not resp.text or len(resp.text.strip()) == 0:
            logger.error(f"Abyss API returned empty response")
            return None
        
        # Try to parse JSON
        try:
            data = resp.json()
        except Exception as json_err:
            logger.error(f"Abyss JSON parse error: {json_err}, Response: {resp.text[:200]}")
            return None
        
        logger.info(f"Abyss response: {data}")
        
        # Check for success
        if data.get("slug"):
            short_url = f"https://short.icu/{data['slug']}"
            logger.info(f"Abyss Remote Upload Success: {short_url}")
            return short_url
        elif data.get("id"):
            short_url = f"https://short.icu/{data['id']}"
            logger.info(f"Abyss Remote Upload Success: {short_url}")
            return short_url
        elif data.get("error"):
            logger.error(f"Abyss API Error: {data.get('error')}")
            return None
        
        logger.error(f"Abyss upload failed - unexpected response: {data}")
        return None
        
    except requests.exceptions.Timeout:
        logger.error(f"Abyss Remote Upload Timeout (120s)")
        return None
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Abyss Request Error: {req_err}")
        return None
    except Exception as e:
        logger.error(f"Abyss Remote Upload Error: {e}")
        return None

def vidhide_remote_upload(seedbox_url: str, filename: str) -> str:
    """Remote upload to VidHide via Seedbox direct link. Returns download URL."""
    if not VIDHIDE_ENABLED or not seedbox_url:
        return None
    
    try:
        logger.info(f"VidHide: Uploading from {seedbox_url[:50]}...")
        
        # API: GET https://earnvidsapi.com/api1/upload/url?key={key}&url={url}
        resp = requests.get(
            "https://earnvidsapi.com/api1/upload/url",
            params={
                "key": VIDHIDE_API_KEY,
                "url": seedbox_url,
                "file_title": filename
            },
            timeout=180
        )
        
        # Log raw response for debugging
        logger.info(f"VidHide HTTP Status: {resp.status_code}")
        logger.info(f"VidHide Raw Response: {resp.text[:500] if resp.text else 'EMPTY'}")
        
        # Check if response is empty
        if not resp.text or len(resp.text.strip()) == 0:
            logger.error(f"VidHide API returned empty response")
            return None
        
        # Try to parse JSON
        try:
            data = resp.json()
        except Exception as json_err:
            logger.error(f"VidHide JSON parse error: {json_err}, Response: {resp.text[:200]}")
            return None
        
        logger.info(f"VidHide response: {data}")
        
        # Response: {"msg":"OK","status":200,"result":{"filecode":"fb5asfuj2snh"}}
        if data.get("status") == 200 and data.get("result"):
            filecode = data["result"].get("filecode")
            if filecode:
                download_url = f"https://{VIDHIDE_DOMAIN}/download/{filecode}"
                logger.info(f"VidHide Upload Success: {download_url}")
                return download_url
        
        # Check for error message
        if data.get("msg") and data.get("msg") != "OK":
            logger.error(f"VidHide API Error: {data.get('msg')}")
            return None
        
        logger.error(f"VidHide upload failed - unexpected response: {data}")
        return None
        
    except requests.exceptions.Timeout:
        logger.error(f"VidHide Remote Upload Timeout (180s)")
        return None
    except requests.exceptions.RequestException as req_err:
        logger.error(f"VidHide Request Error: {req_err}")
        return None
    except Exception as e:
        logger.error(f"VidHide Remote Upload Error: {e}")
        return None

def clean_filename(original_name: str, res_tag: str) -> str:
    original_name = os.path.basename(original_name)
    original_name = urllib.parse.unquote(original_name)
    if "?" in original_name: original_name = original_name.split("?")[0]
    
    match = re.search(r"(.+?)[\.\s][sS](\d+)[eE](\d+)", original_name)
    if match:
        title = ".".join(match.group(1).replace(".", " ").replace("_", " ").strip().split())
        s, e = int(match.group(2)), int(match.group(3))
        return f"{title}.E{e:02d}.{res_tag}.mp4" if s == 1 else f"{title}.S{s:02d}E{e:02d}.{res_tag}.mp4"

    base = os.path.splitext(original_name)[0]
    for tag in ["1080p","720p","480p","360p","WEB-DL","WEBRip","H.264","H264","x264","HEVC","AAC","mkv","mp4"]:
        base = re.sub(re.escape(tag), "", base, flags=re.IGNORECASE)
    base = ".".join(base.replace("_", ".").strip(".").split())
    if len(base) < 2: base = "Video_Unknown"
    return f"{base}.{res_tag}.mp4"

def get_real_filename(url: str) -> str:
    try:
        # UPDATE: Coba ambil title, bukan filename, agar lebih bersih dari GDrive
        out = subprocess.check_output(
            ["yt-dlp", "--get-filename", "-o", "%(title)s.%(ext)s", "--no-warnings", url],
            text=True, timeout=20, **get_hidden_params()
        )
        name = out.strip().split("\n")[0]
        
        # FIX: Double Extension (misal .mp4.mp4)
        if name.lower().endswith(".mp4.mp4"): name = name[:-4]
        if name.lower().endswith(".mkv.mkv"): name = name[:-4]
        
        if name and "NA" not in name and len(name) > 3:
            return name
            
    except:
        pass
        
    # --- FALLBACK JIKA GAGAL / NA ---
    gdrive_match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
    if gdrive_match:
        return f"GDrive_Video_{gdrive_match.group(1)}.mp4"
        
    basename = os.path.basename(urllib.parse.urlparse(url).path)
    if len(basename) > 3:
        return basename
        
    return "Video_Unknown.mp4"

def get_video_metadata(filename: str) -> dict:
    """Mendapatkan detail video (durasi, lebar, tinggi) untuk Telegram"""
    meta = {"width": 0, "height": 0, "duration": 0, "str": "Info Unavailable"}
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_name", "-of", "json", filename]
        out = subprocess.check_output(cmd, text=True, **get_hidden_params())
        data = json.loads(out)
        
        # Get Video Stream
        streams = data.get("streams", [])
        v = next((s for s in streams if s.get("codec_name") not in ["aac", "mp3", "opus"]), {})
        a = next((s for s in streams if s.get("codec_name") in ["aac", "mp3", "opus"]), {})
        
        meta["width"] = int(v.get("width", 0))
        meta["height"] = int(v.get("height", 0))
        meta["duration"] = int(float(data.get("format", {}).get("duration", 0)))
        meta["str"] = f"{meta['width']}x{meta['height']} | {v.get('codec_name', 'unk')} | {a.get('codec_name', 'unk')}"
    except:
        pass
    return meta

def get_indo_subtitle_index(filename: str) -> Optional[int]:
    """Mencari index subtitle Indonesia (matching bash script logic)"""
    try:
        # ffprobe -v error -select_streams s -show_entries stream_tags=language -of csv=p=0
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "s",
            "-show_entries", "stream_tags=language",
            "-of", "csv=p=0", filename,
        ]
        out = subprocess.check_output(cmd, text=True, **get_hidden_params())
        
        # Output: satu bahasa per line, e.g.:
        # eng
        # ind
        # chi
        lines = out.strip().split("\n") if out.strip() else []
        
        logger.info(f"Subtitle detection - found {len(lines)} streams: {lines[:10]}")
        
        # Cari line yang mengandung 'ind' atau 'indonesian'
        for i, lang in enumerate(lines):
            lang_lower = lang.lower().strip()
            if "ind" in lang_lower or "indonesian" in lang_lower:
                logger.info(f"Found Indonesian subtitle at stream index {i}: {lang}")
                return i  # Subtitle stream index (0-based)
        
        logger.warning("No Indonesian subtitle found")
        return None
    except Exception as e:
        logger.error(f"Error detecting subtitle: {e}")
        return None

# =====================================================
# FILEBROWSER HELPERS
# =====================================================

def parse_filebrowser_url(url: str) -> Optional[dict]:
    """Parse FileBrowser share URL dan extract domain + hash"""
    try:
        if "/filebrowser/share/" not in url and "/share/" not in url:
            return None
        
        parsed = urllib.parse.urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        # Detect path prefix
        path_prefix = "/filebrowser" if "/filebrowser/" in parsed.path else ""
        
        # Extract hash
        if "/share/" in url:
            share_hash = url.split("/share/")[-1].strip("/")
        else:
            return None
            
        return {
            "domain": domain,
            "prefix": path_prefix,
            "hash": share_hash,
            "api_base": f"{domain}{path_prefix}/api/public/share/{share_hash}"
        }
    except:
        return None

def fetch_filebrowser_files(fb_info: dict) -> list:
    """Fetch list of files from FileBrowser API"""
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        }
        r = requests.get(fb_info["api_base"], headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        # Normalize response
        items = []
        if 'files' in data: items = data['files']
        elif 'items' in data: items = data['items']
        elif isinstance(data, list): items = data
        
        # Filter only video files
        video_exts = ('.mkv', '.mp4', '.avi', '.mov', '.webm')
        files = [f for f in items if not f.get('isDir', False) and f.get('name', '').lower().endswith(video_exts)]
        
        # Sort by name
        files.sort(key=lambda x: x.get('name', ''))
        
        return files
    except Exception as e:
        logger.error(f"FileBrowser API Error: {e}")
        return []

def build_filebrowser_download_url(fb_info: dict, filename: str) -> str:
    """Build direct download URL for a file"""
    encoded_name = urllib.parse.quote(filename)
    return f"{fb_info['domain']}{fb_info['prefix']}/api/public/dl/{fb_info['hash']}/{encoded_name}"

# =====================================================
# PYROGRAM APP INIT
# =====================================================

app = Client(
    os.path.join(DATA_FOLDER, "bot_encode_session"), 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    max_concurrent_transmissions=8, 
    # ipv6=True 
)

# =====================================================
# WORKER FUNCTIONS
# =====================================================

async def update_status_message(client, chat_id, msg_id, status_data):
    """Fungsi tunggal untuk update pesan status agar tidak flicker/flood"""
    try:
        text = "⚙️ <b>STATUS PROSES</b>\n━━━━━━━━━━━━━━━━━━\n"
        fname = html.escape(status_data.get("filename", "Unknown"))
        
        job_type = status_data.get("type", "encode")
        
        if job_type == "leech":
            text += (f"🎬 <b>File:</b> <code>{fname}</code>\n"
                     f"🚀 <b>Mode:</b> Direct Leech (No Encode)\n\n")
        else:
            # Header Info Encode
            mode_disp = status_data.get("mode", "")
            if mode_disp == "mixed": mode_disp = "⚡ Hybrid"
            elif mode_disp == "crf": mode_disp = "🚀 CRF"
            elif mode_disp == "2pass": mode_disp = "🎯 2-Pass"
            
            text += (f"🎬 <b>File:</b> <code>{fname}</code>\n"
                     f"🔧 <b>Mode:</b> {mode_disp} | <b>Font:</b> {status_data.get('font',15)} | <b>Mar:</b> {status_data.get('margin',25)}\n\n")

        # Download Progress
        if status_data.get("phase") == "dl":
            dl = status_data.get("dl", {})
            dl_type = dl.get('type', 'Direct')
            text += (f"📥 <b>Downloading ({dl_type})...</b>\n"
                     f"{create_progress_bar(dl.get('pct', 0))}\n"
                     f"📦 {dl.get('total','?')} | 🚀 {dl.get('speed','?')} | ⏳ {dl.get('eta','?')}\n")
        
        # Process Progress (Encode/Upload)
        if job_type == "leech" and status_data.get("phase") == "upload":
             up = status_data.get("upload", {})
             text += (f"✈️ <b>Uploading to Telegram...</b>\n"
                      f"{create_progress_bar(up.get('pct', 0))}\n"
                      f"🚀 Speed: {up.get('speed', 'Calculating...')}\n" 
                      f"⏳ {up.get('status', 'Uploading')}")
        else:
            # Encode & Upload Progress Loop
            for res, info in status_data.get("resolutions", {}).items():
                status = info['status']
                
                icon = "⏳"
                bar_pct = info.get('pct', 0)
                extra_txt = ""

                if "Encoding" in status:
                    icon = "⚙️"
                elif status == "Up-Seedbox": # Upload ke Seedbox
                    icon = "📦"
                elif status == "Up-Drive": # Upload ke GDrive
                    icon = "☁️"
                elif status == "Up-Mirror": # Upload ke Mirrored.to
                    icon = "🪞"
                elif status == "Up-Tele": # Upload ke Telegram
                    icon = "✈️"
                    bar_pct = info.get('up_tele_pct', 0)
                elif status == "Done":
                    icon = "✅"
                elif status == "Error":
                    icon = "❌"

                if info.get('eta'): extra_txt = f"({info['eta']})"
                
                text += f"<b>{res}</b>: {icon} {status} {extra_txt}\n{create_progress_bar(bar_pct)}\n"

        # System Resource
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        text += f"\n🧠 CPU: {cpu}% | 💾 RAM: {ram}%"

        # MENAMPILKAN TOMBOL CANCEL
        await client.edit_message_text(
            chat_id, 
            msg_id, 
            text, 
            parse_mode=None, 
            reply_markup=get_cancel_markup() # <-- TOMBOL CANCEL DISINI
        ) 
    except Exception as e:
        pass # Ignore edit errors

async def reporter_loop(client, chat_id, msg_id):
    """Loop untuk update status setiap 3-4 detik"""
    while IS_WORKING and chat_id in STATUS_DASHBOARD:
        await update_status_message(client, chat_id, msg_id, STATUS_DASHBOARD[chat_id])
        await asyncio.sleep(4)

def sync_ffmpeg_worker(chat_id, res, input_file, output_file, mode, font, margin, srt_file, audio_prof, sub_track, crf_value="26"):
    """Fungsi FFmpeg Synchronous"""
    # 1. Tentukan Bitrate & Codec (dengan downmix ke stereo untuk compatibility)
    if audio_prof == "he":
        a_opts = ["-c:a", "libfdk_aac", "-profile:a", "aac_he_v2", "-ac", "2", "-b:a", HEAUDIO_MAP.get(res, "48k")]
    else:
        a_opts = ["-c:a", "aac", "-ac", "2", "-b:a", AACLCAUDIO_MAP.get(res, "128k")]
    
    # 2. Filter Subtitle - escape commas in force_style value
    # Note: colons between options should NOT be escaped, only within values
    style_escaped = f"FontName={SUB_FONT_NAME}\\,FontSize={font}\\,Bold={SUB_IS_BOLD}\\,MarginV={margin}\\,BorderStyle=1\\,Outline=1\\,PrimaryColour=&H00FFFFFF"
    
    if res == "360p": h=360; b="300k"
    elif res == "480p": h=480; b="540k"
    elif res == "720p": h=720; b="850k"
    else: h=1080; b="2100k"
    
    # Update VF with correct height
    # Escape colons WITHIN the path (if any), but NOT between options
    if srt_file:
        sub_path = srt_file.replace("\\", "/").replace(":", "\\\\:")
        vf = f"scale=-2:{h},subtitles={sub_path}:force_style={style_escaped}"
    elif sub_track is not None:
        clean_input = input_file.replace("\\", "/").replace(":", "\\\\:")
        vf = f"scale=-2:{h},subtitles={clean_input}:si={sub_track}:force_style={style_escaped}"
    else:
        # Tidak ada subtitle - skip filter subtitle (scale only)
        vf = f"scale=-2:{h}"
    
    # Tambah Watermark jika enabled
    if WATERMARK_ENABLED:
        # Escape karakter khusus untuk drawtext (FFmpeg) - simpler escaping for Linux
        wm_text = WATERMARK_TEXT.replace("'", "'\\''").replace(":", "\\:").replace("(", "\\(").replace(")", "\\)")
        
        # Dynamic font size based on resolution
        wm_fontsize = {360: 14, 480: 18, 720: 24, 1080: 30}.get(h, 20)
        
        # Fade in/out effect: fade in 0-1s, fade out di detik 28-30
        alpha_expr = f"if(lt(t\\,1)\\,t\\,if(gt(t\\,{WATERMARK_DURATION-2})\\,({WATERMARK_DURATION}-t)/2\\,1))"
        
        # Filter: Arial Bold, kuning dengan outline hitam tipis
        watermark_filter = (
            f"drawtext=text='{wm_text}'"
            f":fontfile='{WATERMARK_FONT}'"
            f":fontsize={wm_fontsize}"
            f":fontcolor=yellow"
            f":borderw=1"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=20"
            f":alpha='{alpha_expr}'"
            f":enable='lt(t\\,{WATERMARK_DURATION})'"
        )
        vf = f"{vf},{watermark_filter}"
    
    # 3. Encoding Logic
    is_2pass = (mode == "2pass") or (mode == "mixed" and res == "360p")
    
    log_prefix = f"ff_{chat_id}_{res}"

    def run_ff(cmd_list):
        # GANTI: Pakai **get_hidden_params()
        p = subprocess.Popen(cmd_list, stderr=subprocess.PIPE, encoding='utf-8', errors='ignore', **get_hidden_params())
        if chat_id not in ACTIVE_PROCESSES: ACTIVE_PROCESSES[chat_id] = []
        ACTIVE_PROCESSES[chat_id].append(p)
        
        dur = 0
        try:
            # Get duration
            probe = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_file], **get_hidden_params())
            dur = float(probe)
        except: pass

        stderr_lines = []  # Capture stderr for error reporting
        
        while True:
            # CEK CANCEL - break jika sudah di-cancel
            if chat_id in STATUS_DASHBOARD and STATUS_DASHBOARD.get(chat_id, {}).get('is_cancelled'):
                force_kill_process(p)
                break
                
            line = p.stderr.readline()
            if not line and p.poll() is not None: break
            if not line: continue
            
            stderr_lines.append(line)  # Capture stderr
            
            # Parse progress
            if dur > 0 and "time=" in line:
                m = re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d+)", line)
                if m and chat_id in STATUS_DASHBOARD:
                    secs = time_str_to_seconds(m.group(1))
                    pct = (secs / dur) * 100
                    STATUS_DASHBOARD[chat_id]["resolutions"][res]["pct"] = pct
        
        if chat_id in ACTIVE_PROCESSES and p in ACTIVE_PROCESSES[chat_id]: 
            ACTIVE_PROCESSES[chat_id].remove(p)
        if p.poll() != 0 and p.poll() is not None:
            # Get last few lines of stderr for error info
            error_detail = "".join(stderr_lines[-20:])[-500:] if stderr_lines else "No stderr"
            logger.error(f"FFmpeg Error: {error_detail}")
            raise Exception(f"FFmpeg Error:\n{error_detail}")

    common_opts = ["ffmpeg", "-y", "-i", input_file, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast"]
    
    if is_2pass:
        # Pass 1
        if chat_id in STATUS_DASHBOARD: STATUS_DASHBOARD[chat_id]["resolutions"][res]["status"] = "Encoding (Pass 1/2)"
        run_ff(common_opts + ["-b:v", b, "-pass", "1", "-passlogfile", log_prefix, "-an", "-f", "mp4", "/dev/null"])
        
        # Pass 2
        if chat_id in STATUS_DASHBOARD: STATUS_DASHBOARD[chat_id]["resolutions"][res]["status"] = "Encoding (Pass 2/2)"
        run_ff(common_opts + ["-b:v", b, "-pass", "2", "-passlogfile", log_prefix] + a_opts + [output_file])
        
        # Cleanup
        for f in os.listdir("."):
            if f.startswith(log_prefix): os.remove(f)
    else:
        # CRF
        if chat_id in STATUS_DASHBOARD: STATUS_DASHBOARD[chat_id]["resolutions"][res]["status"] = f"Encoding (CRF {crf_value})"
        run_ff(common_opts + ["-crf", crf_value] + a_opts + [output_file])


async def process_job(client, job):
    global IS_WORKING, CURRENT_JOB
    chat_id = job['chat_id']
    msg_id = job['msg_id']
    job_type = job.get('type', 'encode')
    
    # 1. DOWNLOAD PHASE (Shared for both)
    initial_status = {
        "filename": job['real_name'], "type": job_type,
        "phase": "dl", "dl": {"pct": 0, "type": "Direct"}
    }
    
    if job_type == "encode":
        initial_status.update({
            "mode": job['mode'], "font": job['font'], "margin": job['margin'],
            "resolutions": {r: {"status": "Waiting", "pct": 0} for r in job['queue']}
        })
    else: # Leech
        initial_status.update({
            "upload": {"pct": 0, "status": "Waiting", "speed": "0 MB/s"}
        })

    STATUS_DASHBOARD[chat_id] = initial_status
    
    # Jalankan Reporter (Background Task)
    reporter = asyncio.create_task(reporter_loop(client, chat_id, msg_id))

    downloaded_file = job['filename']
    download_error_msg = None  # Untuk capture error details

    try:
        # CEK: Job ini resume dari pending SRT? (file sudah didownload)
        if job.get('downloaded_file') and os.path.exists(job['downloaded_file']):
            downloaded_file = job['downloaded_file']
            STATUS_DASHBOARD[chat_id]["dl"]["status"] = "Done (Cached)"
            STATUS_DASHBOARD[chat_id]["dl"]["pct"] = 100
        else:
            # Download via YT-DLP (HTTP/Direct only)
            STATUS_DASHBOARD[chat_id]["dl"]["type"] = "Direct/HTTP"
        
            def dl_wrapper():
                nonlocal download_error_msg
                cmd = ["yt-dlp", "-o", job['filename'], "--newline", "--force-overwrites", "--no-continue", job['url']]
                logger.info(f"Download URL: {job['url']}")
                
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='ignore', **get_hidden_params())
                if chat_id not in ACTIVE_PROCESSES: ACTIVE_PROCESSES[chat_id] = []
                ACTIVE_PROCESSES[chat_id].append(p)
                
                stderr_output = []
                
                while True:
                    # CEK CANCEL
                    if job.get('is_cancelled'):
                        force_kill_process(p)
                        break
                        
                    line = p.stdout.readline()
                    if not line and p.poll() is not None: break
                    
                    # Parse yt-dlp progress: [download]  55.6% of 2.00GiB at  5.2MiB/s ETA 00:08
                    if "[download]" in line and chat_id in STATUS_DASHBOARD:
                        # Match percentage
                        pct_match = re.search(r"(\d+\.?\d*)%", line)
                        if pct_match:
                            STATUS_DASHBOARD[chat_id]["dl"]["pct"] = float(pct_match.group(1))
                        
                        # Match size: "of 2.00GiB" or "of 500.5MiB"
                        size_match = re.search(r"of\s+([\d.]+\s*[KMGT]?i?B)", line)
                        if size_match:
                            STATUS_DASHBOARD[chat_id]["dl"]["size"] = size_match.group(1)
                        
                        # Match speed: "at 5.2MiB/s" or "at 500KiB/s"
                        speed_match = re.search(r"at\s+([\d.]+\s*[KMGT]?i?B/s)", line)
                        if speed_match:
                            STATUS_DASHBOARD[chat_id]["dl"]["speed"] = speed_match.group(1)
                        
                        # Match ETA: "ETA 00:08"
                        eta_match = re.search(r"ETA\s+(\d+:\d+)", line)
                        if eta_match:
                            STATUS_DASHBOARD[chat_id]["dl"]["eta"] = eta_match.group(1)
                
                # Capture stderr
                if p.stderr:
                    stderr_output = p.stderr.read()
                
                if chat_id in ACTIVE_PROCESSES and p in ACTIVE_PROCESSES[chat_id]: 
                    ACTIVE_PROCESSES[chat_id].remove(p)
                
                if p.poll() != 0 and p.poll() is not None and not job.get('is_cancelled'):
                    download_error_msg = f"Exit code: {p.poll()}\nURL: {job['url'][:100]}...\nError: {stderr_output[:500] if stderr_output else 'No stderr'}"
                    raise Exception(f"Download Failed")

            # Download dengan timeout
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(dl_wrapper), 
                    timeout=DOWNLOAD_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Kill proses jika timeout
                if chat_id in ACTIVE_PROCESSES:
                    for p in ACTIVE_PROCESSES[chat_id]:
                        force_kill_process(p)
                raise Exception(f"Download Timeout ({DOWNLOAD_TIMEOUT//60} menit)")
            
            downloaded_file = job['filename']
        
        # Update real filename jika sebelumnya unknown
        if job['real_name'] == "Video_Unknown.mp4" or "NA" in job['real_name']:
            try:
                new_name = get_real_filename(job['url'])
                if new_name and new_name != "Video_Unknown.mp4":
                    job['real_name'] = new_name
                    STATUS_DASHBOARD[chat_id]["filename"] = new_name
            except: pass

        # ===========================
        # LOGIKA CABANG: LEECH vs ENCODE
        # ===========================
        
        if job_type == "leech":
            # === MODE LEECH: LANGSUNG UPLOAD ===
            STATUS_DASHBOARD[chat_id]["phase"] = "upload"
            STATUS_DASHBOARD[chat_id]["upload"]["status"] = "Uploading..."
            
            clean_name = clean_filename(job['real_name'], "Leech")
            if os.path.exists(clean_name): os.remove(clean_name)
            os.rename(downloaded_file, clean_name)
            
            # Variable untuk hitung speed manual
            upload_start_time = time.time()
            
            async def leech_progress(current, total):
                pct = (current / total) * 100
                STATUS_DASHBOARD[chat_id]["upload"]["pct"] = pct
                
                # Hitung speed
                elapsed = time.time() - upload_start_time
                if elapsed > 0:
                    speed = current / elapsed # bytes per second
                    STATUS_DASHBOARD[chat_id]["upload"]["speed"] = f"{human_readable_size(speed)}/s"
                
                # UPDATE PENTING: UBAH STATUS SAAT 100%
                if pct >= 99.9:
                    STATUS_DASHBOARD[chat_id]["upload"]["status"] = "Finalizing (Telegram Processing)..."
            
            # AMBIL METADATA VIDEO (Width, Height, Duration)
            meta = get_video_metadata(clean_name)
            
            caption = (
                f"🎬 <b>{clean_name}</b>\n\n"
                f"ℹ️ {meta['str']}\n"
                f"📥 <b>Leech Success!</b>"
            )
            
            try:
                await client.send_video(
                    chat_id=chat_id,
                    video=clean_name,
                    caption=caption,
                    supports_streaming=True,
                    progress=leech_progress,
                    # INI PENTING AGAR VIDEO TIDAK KOTAK & ADA DURASI
                    width=meta['width'],
                    height=meta['height'],
                    duration=meta['duration']
                )
                STATUS_DASHBOARD[chat_id]["upload"]["status"] = "Done"
                STATUS_DASHBOARD[chat_id]["upload"]["pct"] = 100
                
                # Hapus pesan progress bar setelah sukses
                try:
                    await client.delete_messages(chat_id, msg_id)
                except: pass
                
            except Exception as e:
                logger.error(f"Tele Upload Fail: {e}")
                STATUS_DASHBOARD[chat_id]["upload"]["status"] = "Error"
                await client.send_message(chat_id, f"❌ Upload Gagal: {e}")

            if os.path.exists(clean_name): os.remove(clean_name)

        else:
            # === MODE ENCODE (EXISTING LOGIC) ===
            STATUS_DASHBOARD[chat_id]["phase"] = "encode" # Pindah fase
            
            # === DETEKSI SUBTITLE INDONESIA SEBELUM ENCODE ===
            sub_track_index = None
            if not job.get('srt'):
                sub_track_index = await asyncio.to_thread(get_indo_subtitle_index, downloaded_file)
                
                # Jika tidak ada subtitle Indonesia, simpan job dan tunggu SRT upload
                if sub_track_index is None:
                    # TAMBAHKAN KE CACHE agar muncul di /files
                    cache_id = add_to_cache(downloaded_file, job['real_name'])
                    
                    # Simpan pending job dengan file yang sudah didownload (append ke list)
                    if chat_id not in PENDING_SRT_JOBS:
                        PENDING_SRT_JOBS[chat_id] = []
                    
                    PENDING_SRT_JOBS[chat_id].append({
                        "job": job,
                        "file": downloaded_file,
                        "msg_id": msg_id,
                        "cache_id": cache_id  # Simpan cache ID untuk referensi
                    })
                    
                    pending_count = len(PENDING_SRT_JOBS[chat_id])
                    
                    # Hapus status dashboard message
                    try:
                        await client.delete_messages(chat_id, msg_id)
                    except: pass
                    
                    await client.send_message(
                        chat_id,
                        f"⚠️ <b>Subtitle Indonesia tidak ditemukan!</b>\n\n"
                        f"🎬 <code>{job['real_name']}</code>\n\n"
                        f"📂 File sudah didownload (ID: #{cache_id}). Silakan upload file <b>.srt</b> untuk melanjutkan encoding.\n"
                        f"📊 <b>{pending_count} file</b> menunggu subtitle.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batalkan", "cancel_pending_srt")]])
                    )
                    raise Exception("WAITING_SRT")

            for res in job['queue']:
                # Cek cancel
                if not IS_WORKING: break 
                if job.get('is_cancelled'): break

                out_file = os.path.join(OUTPUT_FOLDER, clean_filename(job['real_name'], res))
                
                # Get input file size and start timer
                input_size = os.path.getsize(downloaded_file) if os.path.exists(downloaded_file) else 0
                encode_start = time.time()
                
                # --- A. ENCODE ---
                # Get CRF for this specific resolution (per-res or fallback to global)
                res_crf_map = job.get('res_crf', {})
                current_crf = res_crf_map.get(res, job.get('crf', '26'))
                
                await asyncio.to_thread(
                    sync_ffmpeg_worker, 
                    chat_id, res, downloaded_file, out_file, 
                    job['mode'], job['font'], job['margin'], job['srt'], job['audio'], sub_track_index,
                    current_crf
                )
                
                # Calculate encode time and output size
                encode_time = time.time() - encode_start
                encode_time_str = str(timedelta(seconds=int(encode_time)))
                output_size = os.path.getsize(out_file) if os.path.exists(out_file) else 0

                # --- RUN UPLOADS IN BACKGROUND (don't wait) ---
                async def background_upload_task(
                    _client, _chat_id, _res, _out_file, _meta, _duration_str, 
                    _input_size, _output_size, _encode_time_str
                ):
                    """Background task for parallel uploads - runs independently"""
                    try:
                        try:
                            STATUS_DASHBOARD[_chat_id]["resolutions"][_res]["status"] = "Uploading"
                            STATUS_DASHBOARD[_chat_id]["resolutions"][_res]["pct"] = 0
                        except KeyError:
                            pass  # Dashboard may not exist for this chat
                        
                        # Shared state for live updates
                        upload_status = {
                            "seedbox": "⏳" if SEEDBOX_ENABLED else "⭕",
                            "gdrive": "⏳",
                            "filepress": "⏳" if FILEPRESS_ENABLED else "⭕",
                            "buzzheavier": "⏳" if BUZZHEAVIER_ENABLED else "⭕",
                            "gofile": "⏳" if GOFILE_ENABLED else "⭕",
                            "mirrored": "⏳" if MIRRORED_ENABLED else "⭕",
                            "turbovid": "⏳" if TURBOVID_ENABLED else "⭕",
                            "abyss": "⏳" if ABYSS_ENABLED else "⭕",
                            "vidhide": "⏳" if VIDHIDE_ENABLED else "⭕",
                        }
                        upload_links = {
                            "seedbox": None, "gdrive": None, "filepress": None,
                            "buzzheavier": None, "gofile": None, "mirrored": None,
                            "turbovid": None, "abyss": None, "vidhide": None
                        }
                        result_msg_id = [None]
                        
                        def build_progress_msg():
                            msg = (
                                f"⬆️ <b>Uploading {_res}</b>\n\n"
                                f"🎬 <code>{os.path.basename(_out_file)}</code>\n"
                                f"📦 {human_readable_size(_output_size)}\n\n"
                            )
                            if upload_links["seedbox"]:
                                msg += f"📦 Seedbox: ✅\n{upload_links['seedbox']}\n\n"
                            else:
                                msg += f"📦 Seedbox: {upload_status['seedbox']}\n"
                            if upload_links["gdrive"]:
                                msg += f"☁️ GDrive: ✅\n{upload_links['gdrive']}\n\n"
                            else:
                                msg += f"☁️ GDrive: {upload_status['gdrive']}\n"
                            if upload_links["buzzheavier"]:
                                msg += f"🐝 Buzzheavier: ✅\n{upload_links['buzzheavier']}\n\n"
                            else:
                                msg += f"🐝 Buzzheavier: {upload_status['buzzheavier']}\n"
                            if upload_links["gofile"]:
                                msg += f"📁 Gofile: ✅\n{upload_links['gofile']}\n\n"
                            else:
                                msg += f"📁 Gofile: {upload_status['gofile']}\n"
                            if upload_links["filepress"]:
                                msg += f"🎬 FilePress: ✅\n{upload_links['filepress']}\n\n"
                            else:
                                msg += f"🎬 FilePress: {upload_status['filepress']}\n"
                            if upload_links["mirrored"]:
                                msg += f"🪞 Mirrored: ✅\n{upload_links['mirrored']}\n\n"
                            else:
                                msg += f"🪞 Mirrored: {upload_status['mirrored']}\n"
                            if upload_links["turbovid"]:
                                msg += f"📺 TurboVid: ✅\n{upload_links['turbovid']}\n\n"
                            else:
                                msg += f"📺 TurboVid: {upload_status['turbovid']}\n"
                            if upload_links["abyss"]:
                                msg += f"🌀 Abyss: ✅\n{upload_links['abyss']}\n\n"
                            else:
                                msg += f"🌀 Abyss: {upload_status['abyss']}\n"
                            if upload_links["vidhide"]:
                                msg += f"🎬 VidHide: ✅\n{upload_links['vidhide']}\n"
                            else:
                                msg += f"🎬 VidHide: {upload_status['vidhide']}\n"
                            return msg
                        
                        async def update_msg():
                            try:
                                if result_msg_id[0]:
                                    await _client.edit_message_text(_chat_id, result_msg_id[0], build_progress_msg())
                            except: pass
                        
                        try:
                            prog_msg = await _client.send_message(_chat_id, build_progress_msg(), disable_notification=True)
                            result_msg_id[0] = prog_msg.id
                        except: pass
                        
                        async def do_seedbox():
                            if not SEEDBOX_ENABLED: return None
                            try:
                                link = await asyncio.to_thread(filebrowser_upload_file, _out_file, _chat_id, _res)
                                upload_status["seedbox"] = "✅" if link else "❌"
                                upload_links["seedbox"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["seedbox"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_gdrive():
                            try:
                                def rclone_up():
                                    cmd = ["rclone", "copy", _out_file, f"{RCLONE_REMOTE}:{RCLONE_FOLDER}", "-v"]
                                    p = subprocess.Popen(cmd, stderr=subprocess.PIPE, encoding='utf-8', errors='ignore', **get_hidden_params())
                                    if _chat_id not in ACTIVE_PROCESSES: ACTIVE_PROCESSES[_chat_id] = []
                                    ACTIVE_PROCESSES[_chat_id].append(p)
                                    p.wait()
                                    if _chat_id in ACTIVE_PROCESSES and p in ACTIVE_PROCESSES[_chat_id]:
                                        ACTIVE_PROCESSES[_chat_id].remove(p)
                                
                                await asyncio.to_thread(rclone_up)
                                # Use basename for lsjson since rclone uploads to remote folder directly
                                out_basename = os.path.basename(_out_file)
                                ls = subprocess.check_output(["rclone", "lsjson", f"{RCLONE_REMOTE}:{RCLONE_FOLDER}/{out_basename}"], text=True, **get_hidden_params())
                                fid = json.loads(ls)[0]["ID"]
                                link = f"https://drive.google.com/file/d/{fid}/view?usp=drivesdk"
                                upload_status["gdrive"] = "✅"
                                upload_links["gdrive"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["gdrive"] = "❌"
                                await update_msg()
                                return "Error Link"
                        
                        async def do_mirrored():
                            if not MIRRORED_ENABLED: return None
                            try:
                                link = await asyncio.to_thread(mirrored_upload_file, _out_file)
                                upload_status["mirrored"] = "✅" if link else "❌"
                                upload_links["mirrored"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["mirrored"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_buzzheavier():
                            if not BUZZHEAVIER_ENABLED: return None
                            try:
                                link = await asyncio.to_thread(buzzheavier_upload_file, _out_file)
                                upload_status["buzzheavier"] = "✅" if link else "❌"
                                upload_links["buzzheavier"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["buzzheavier"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_gofile():
                            if not GOFILE_ENABLED: return None
                            try:
                                link = await asyncio.to_thread(gofile_upload_file, _out_file)
                                upload_status["gofile"] = "✅" if link else "❌"
                                upload_links["gofile"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["gofile"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_filepress():
                            """FilePress mirrors from GDrive, so wait for GDrive first"""
                            if not FILEPRESS_ENABLED: return None
                            # Wait for GDrive to finish
                            while upload_links["gdrive"] is None and upload_status["gdrive"] == "⏳":
                                await asyncio.sleep(0.5)
                            if not upload_links["gdrive"]:
                                upload_status["filepress"] = "❌"
                                await update_msg()
                                return None
                            try:
                                # Extract quality from resolution
                                quality = int(_res.replace("p", "")) if _res else None
                                link = await asyncio.to_thread(filepress_mirror, upload_links["gdrive"], quality)
                                upload_status["filepress"] = "✅" if link else "❌"
                                upload_links["filepress"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["filepress"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_turbovid():
                            """TurboVid remote upload from Seedbox, wait for Seedbox first (1080p only)"""
                            if not TURBOVID_ENABLED: return None
                            if _res != "1080p":  # Only for 1080p
                                upload_status["turbovid"] = "⭕"
                                return None
                            # Wait for Seedbox to finish
                            while upload_links["seedbox"] is None and upload_status["seedbox"] == "⏳":
                                await asyncio.sleep(0.5)
                            if not upload_links["seedbox"]:
                                upload_status["turbovid"] = "❌"
                                await update_msg()
                                return None
                            try:
                                filename = os.path.basename(_out_file)
                                link = await asyncio.to_thread(turbovid_remote_upload, upload_links["seedbox"], filename)
                                upload_status["turbovid"] = "✅" if link else "❌"
                                upload_links["turbovid"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["turbovid"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_abyss():
                            """Abyss remote upload from GDrive, wait for GDrive first (1080p only)"""
                            if not ABYSS_ENABLED: return None
                            if _res != "1080p":  # Only for 1080p
                                upload_status["abyss"] = "⭕"
                                return None
                            # Wait for GDrive to finish
                            while upload_links["gdrive"] is None and upload_status["gdrive"] == "⏳":
                                await asyncio.sleep(0.5)
                            if not upload_links["gdrive"]:
                                upload_status["abyss"] = "❌"
                                await update_msg()
                                return None
                            try:
                                link = await asyncio.to_thread(abyss_remote_upload, upload_links["gdrive"])
                                upload_status["abyss"] = "✅" if link else "❌"
                                upload_links["abyss"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["abyss"] = "❌"
                                await update_msg()
                                return None
                        
                        async def do_vidhide():
                            """VidHide remote upload from Seedbox, wait for Seedbox first (1080p only)"""
                            if not VIDHIDE_ENABLED: return None
                            if _res != "1080p":  # Only for 1080p
                                upload_status["vidhide"] = "⭕"
                                return None
                            # Wait for Seedbox to finish
                            while upload_links["seedbox"] is None and upload_status["seedbox"] == "⏳":
                                await asyncio.sleep(0.5)
                            if not upload_links["seedbox"]:
                                upload_status["vidhide"] = "❌"
                                await update_msg()
                                return None
                            try:
                                filename = os.path.basename(_out_file)
                                link = await asyncio.to_thread(vidhide_remote_upload, upload_links["seedbox"], filename)
                                upload_status["vidhide"] = "✅" if link else "❌"
                                upload_links["vidhide"] = link
                                await update_msg()
                                return link
                            except:
                                upload_status["vidhide"] = "❌"
                                await update_msg()
                                return None
                        
                        # Run ALL uploads in parallel
                        await asyncio.gather(
                            do_seedbox(), do_gdrive(), do_mirrored(), 
                            do_buzzheavier(), do_gofile(), do_filepress(),
                            do_turbovid(), do_abyss(), do_vidhide(),
                            return_exceptions=True
                        )
                        
                        # Final message
                        try:
                            STATUS_DASHBOARD[_chat_id]["resolutions"][_res]["status"] = "Done"
                            STATUS_DASHBOARD[_chat_id]["resolutions"][_res]["pct"] = 100
                        except KeyError:
                            pass  # Dashboard may have been cleared
                        
                        text_msg = (
                            f"✅ <b>Selesai {_res}</b>\n\n"
                            f"🎬 <code>{os.path.basename(_out_file)}</code>\n"
                            f"ℹ️ {_meta['str']}\n"
                            f"🎞️ Durasi: {_duration_str}\n"
                            f"📦 {human_readable_size(_input_size)} → {human_readable_size(_output_size)}\n"
                            f"⏱️ Encode: {_encode_time_str}\n\n"
                        )
                        
                        if upload_links["seedbox"]:
                            text_msg += f"📦 <b>Seedbox:</b>\n{upload_links['seedbox']}\n\n"
                        if upload_links["gdrive"]:
                            text_msg += f"🔗 <b>GDrive:</b>\n{upload_links['gdrive']}\n\n"
                        if upload_links["buzzheavier"]:
                            text_msg += f"🐝 <b>Buzzheavier:</b>\n{upload_links['buzzheavier']}\n\n"
                        if upload_links["gofile"]:
                            text_msg += f"📁 <b>Gofile:</b>\n{upload_links['gofile']}\n\n"
                        if upload_links["filepress"]:
                            text_msg += f"🎬 <b>FilePress:</b>\n{upload_links['filepress']}\n\n"
                        if upload_links["mirrored"]:
                            text_msg += f"🪞 <b>Mirrored:</b>\n{upload_links['mirrored']}\n\n"
                        if upload_links["turbovid"]:
                            text_msg += f"📺 <b>TurboVid:</b>\n{upload_links['turbovid']}\n\n"
                        if upload_links["abyss"]:
                            text_msg += f"🌀 <b>Abyss:</b>\n{upload_links['abyss']}\n\n"
                        if upload_links["vidhide"]:
                            text_msg += f"🎬 <b>VidHide:</b>\n{upload_links['vidhide']}"
                        
                        # Save to encode history for /links command
                        add_to_encode_history(
                            filename=os.path.basename(_out_file),
                            quality=_res,
                            links={
                                "seedbox": upload_links.get("seedbox"),
                                "gdrive": upload_links.get("gdrive"),
                                "buzzheavier": upload_links.get("buzzheavier"),
                                "mirrored": upload_links.get("mirrored"),
                                "gofile": upload_links.get("gofile"),
                                "filepress": upload_links.get("filepress"),
                                "turbovid": upload_links.get("turbovid"),
                                "abyss": upload_links.get("abyss"),
                                "vidhide": upload_links.get("vidhide"),
                            },
                            meta={
                                "duration": _duration_str,
                                "input_size": human_readable_size(_input_size),
                                "output_size": human_readable_size(_output_size),
                                "encode_time": _encode_time_str
                            }
                        )
                        
                        try:
                            if result_msg_id[0]:
                                await _client.edit_message_text(_chat_id, result_msg_id[0], text_msg)
                            else:
                                await _client.send_message(_chat_id, text_msg, disable_notification=True)
                        except Exception as msg_err:
                            logger.warning(f"Failed to edit final message: {msg_err}")
                            # Fallback: delete old "Uploading" message and send new one
                            try:
                                if result_msg_id[0]:
                                    await _client.delete_messages(_chat_id, result_msg_id[0])
                                await _client.send_message(_chat_id, text_msg, disable_notification=True)
                            except:
                                logger.error(f"Fallback message also failed for {_out_file}")
                            
                    except Exception as e:
                        import traceback
                        logger.error(f"Background upload error: {e}\n{traceback.format_exc()}")
                    finally:
                        # Always delete encoded file after task completes (success or error)
                        try:
                            if os.path.exists(_out_file): 
                                os.remove(_out_file)
                                logger.info(f"Deleted encoded file: {_out_file}")
                        except Exception as del_err:
                            logger.error(f"Failed to delete {_out_file}: {del_err}")
                
                # Get metadata before starting background task
                meta = get_video_metadata(out_file)
                duration_str = str(timedelta(seconds=meta['duration']))
                
                # Start upload as background task (don't await!)
                asyncio.create_task(background_upload_task(
                    client, chat_id, res, out_file, meta, duration_str,
                    input_size, output_size, encode_time_str
                ))
                
                # Continue to next resolution immediately!

            # Add file to cache instead of delete (untuk re-encode)
            if downloaded_file and os.path.exists(downloaded_file):
                cache_id = add_to_cache(downloaded_file, job['real_name'])
                logger.info(f"Added to cache: #{cache_id} - {job['real_name']}")
            
            # Hapus status dashboard setelah selesai semua encode
            try:
                await client.delete_messages(chat_id, msg_id)
            except: pass

    except Exception as e:
        if not job.get('is_cancelled') and str(e) not in ["NO_SUBTITLE", "WAITING_SRT"]:
            logger.error(f"Job Failed: {e}")
            error_detail = str(e)
            # Jika ada download error detail
            if download_error_msg:
                error_detail = f"{str(e)}\n\n<code>{download_error_msg}</code>"
            await client.send_message(chat_id, f"❌ <b>Error:</b> {error_detail}")

    finally:
        reporter.cancel()
        
        # Cleanup STATUS_DASHBOARD untuk mencegah memory leak
        if chat_id in STATUS_DASHBOARD:
            del STATUS_DASHBOARD[chat_id]
        
        # Cleanup USER_DATA
        if chat_id in USER_DATA:
            del USER_DATA[chat_id]
        
        # Keep downloaded file for cache (jangan hapus, biar bisa re-encode)
        # File akan dihapus manual via /clean command
        if downloaded_file and os.path.exists(downloaded_file):
            # Add to cache jika belum (untuk error/cancel case)
            if not any(v.get('path') == downloaded_file for v in FILE_CACHE.values()):
                add_to_cache(downloaded_file, job.get('real_name', 'Unknown'))
        
        # Cleanup SRT file jika ada
        if job.get('srt') and os.path.exists(job['srt']): 
            try:
                os.remove(job['srt'])
            except: pass
        
        # Reset state global (penting untuk queue lanjut)
        IS_WORKING = False
        CURRENT_JOB = None
        
        # Proses job selanjutnya di queue
        await check_queue()

# =====================================================
# HANDLERS
# =====================================================

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    if not check_auth(message.from_user.id):
        return
    await message.reply("Halo! Kirim link video untuk mulai.")

# --- HANDLER /template ---
@app.on_message(filters.command("template") & filters.private)
async def template_cmd(client, message):
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    global TEMPLATES
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    # /template (list)
    if not args:
        if not TEMPLATES:
            return await message.reply("📋 Belum ada template. Gunakan <code>/template add</code>")
        
        text = "📋 <b>Daftar Template:</b>\n\n"
        for key, tpl in TEMPLATES.items():
            text += f"<b>{key}</b>: {tpl['name']}\n"
            
            # Show per-res CRF if available
            res_crf = tpl.get('res_crf', {})
            if res_crf:
                crf_parts = [f"{r}:CRF{c}" for r, c in res_crf.items()]
                text += f"  📺 {' | '.join(crf_parts)}\n"
            else:
                text += f"  📺 {tpl['res']} | CRF {tpl.get('crf', '26')}\n"
            
            text += f"  🔊 {tpl['audio'].upper()} | 🎯 {tpl['mode'].upper()}\n"
            text += f"  🅰️ Font: {tpl['font']} | 📏 Margin: {tpl['margin']}\n\n"
        text += "<i>Hapus: /template del [key]</i>\n"
        text += "<i>Tambah: /template add</i>"
        return await message.reply(text)
    
    # /template del [key]
    if args[0] == "del" and len(args) > 1:
        key = args[1]
        if key not in TEMPLATES:
            return await message.reply(f"❌ Template <code>{key}</code> tidak ditemukan.")
        del TEMPLATES[key]
        save_templates(TEMPLATES)
        return await message.reply(f"✅ Template <code>{key}</code> berhasil dihapus.")
    
    # /template add
    if args[0] == "add":
        USER_DATA[chat_id] = {
            "adding_template": True, 
            "new_tpl": {},
            "selected_res": [],  # Multi-select resolusi
            "res_crf": {},       # CRF per resolusi
            "crf_pending": []    # Resolusi yang belum diset CRF-nya
        }
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", "newtpl_toggle_360p"), InlineKeyboardButton("480p", "newtpl_toggle_480p")],
            [InlineKeyboardButton("720p", "newtpl_toggle_720p"), InlineKeyboardButton("1080p", "newtpl_toggle_1080p")],
            [InlineKeyboardButton("✅ Selesai Pilih Resolusi", "newtpl_resdone")]
        ])
        return await message.reply("➕ <b>Tambah Template Baru</b>\n\n🎯 Pilih Resolusi (bisa pilih lebih dari satu):", reply_markup=kb)

# --- HANDLER /files (List Cached Files + Manual Files) ---
@app.on_message(filters.command("files") & filters.private)
async def files_cmd(client, message):
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    load_file_cache()  # Refresh cache
    ensure_cache_folder()
    
    # Scan manual folder for new files and add to cache
    manual_files_added = 0
    if os.path.exists(MANUAL_FOLDER):
        video_exts = ['.mkv', '.mp4', '.avi', '.mov', '.webm', '.ts', '.m2ts']
        for filename in os.listdir(MANUAL_FOLDER):
            filepath = os.path.join(MANUAL_FOLDER, filename)
            if os.path.isfile(filepath) and os.path.splitext(filename)[1].lower() in video_exts:
                # Check if already in cache
                already_exists = False
                for fid, info in FILE_CACHE.items():
                    if info.get('path') == filepath:
                        already_exists = True
                        break
                
                if not already_exists:
                    # Add to cache with new ID
                    new_id = str(max([int(k) for k in FILE_CACHE.keys()] + [0]) + 1)
                    FILE_CACHE[new_id] = {
                        "path": filepath,
                        "name": filename,
                        "size": os.path.getsize(filepath),
                        "added": time.time(),
                        "source": "manual"
                    }
                    manual_files_added += 1
        
        if manual_files_added > 0:
            save_file_cache()
    
    if not FILE_CACHE:
        return await message.reply(
            "📂 <b>Cache kosong.</b>\n\n"
            f"• Download video untuk menambah ke cache\n"
            f"• Atau taruh file di folder <code>{MANUAL_FOLDER}/</code>"
        )
    
    text = "📂 <b>Cached Files:</b>\n\n"
    total_size = 0
    
    # Sort by ID
    sorted_ids = sorted(FILE_CACHE.keys(), key=lambda x: int(x))
    
    for fid in sorted_ids:
        info = FILE_CACHE[fid]
        size = info.get('size', 0)
        total_size += size
        size_str = human_readable_size(size)
        source_tag = "📁" if info.get('source') == 'manual' else "⬇️"
        text += f"<b>#{fid}</b> {source_tag} {info['name'][:40]}...\n"
        text += f"    📦 {size_str}\n\n"
    
    text += f"<b>Total:</b> {human_readable_size(total_size)}\n\n"
    text += "<i>/encode [id] - Encode dari cache</i>\n"
    text += "<i>/clean - Hapus semua cache</i>\n\n"
    text += f"<i>📁 = dari folder {MANUAL_FOLDER}/</i>"
    await message.reply(text)

# --- HANDLER /clean (Clear Cache) ---
@app.on_message(filters.command("clean") & filters.private)
async def clean_cmd(client, message):
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    global FILE_CACHE
    count = len(FILE_CACHE)
    
    # Delete all cached files
    for fid, info in FILE_CACHE.items():
        try:
            if os.path.exists(info['path']):
                os.remove(info['path'])
        except: pass
    
    FILE_CACHE = {}
    save_file_cache()
    
    await message.reply(f"🗑️ <b>{count} file</b> berhasil dihapus dari cache.")

# --- HANDLER /encode [id] (Encode from Cache) ---
@app.on_message(filters.command("encode") & filters.private)
async def encode_from_cache_cmd(client, message):
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    # Parse arguments - support: /encode 5 6 7 8 or /encode 5,6,7,8
    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    
    if not raw_args:
        return await message.reply("❌ Format: <code>/encode [id]</code> atau <code>/encode 5,6,7,8</code>\n\nGunakan /files untuk melihat daftar cache.")
    
    # Parse IDs (support comma or space separated)
    raw_args = raw_args.replace(",", " ")
    file_ids = [x.strip() for x in raw_args.split() if x.strip().isdigit()]
    
    if not file_ids:
        return await message.reply("❌ ID tidak valid. Gunakan angka.\n\nContoh: <code>/encode 5</code> atau <code>/encode 5,6,7,8</code>")
    
    load_file_cache()
    
    # Validate all IDs first
    valid_files = []
    invalid_ids = []
    for file_id in file_ids:
        if file_id not in FILE_CACHE:
            invalid_ids.append(file_id)
        elif not os.path.exists(FILE_CACHE[file_id]['path']):
            del FILE_CACHE[file_id]
            save_file_cache()
            invalid_ids.append(file_id)
        else:
            valid_files.append((file_id, FILE_CACHE[file_id]))
    
    if invalid_ids:
        await message.reply(f"⚠️ ID tidak valid: {', '.join(invalid_ids)}")
    
    if not valid_files:
        return await message.reply("❌ Tidak ada file valid untuk di-encode.")
    
    # Single file - show template picker
    if len(valid_files) == 1:
        file_id, cached_file = valid_files[0]
        USER_DATA[chat_id] = {
            "cached_file_id": file_id,
            "cached_file_path": cached_file['path'],
            "cached_file_name": cached_file['name'],
            "res": "all", "audio": "he", "mode": "crf",
            "font": DEFAULT_FONT_SIZE, "margin": DEFAULT_MARGIN_V, "srt": None,
            "crf": "26"
        }
        
        kb = build_template_keyboard()
        return await message.reply(
            f"📂 <b>Encode dari Cache</b>\n\n"
            f"🎬 <code>{cached_file['name']}</code>\n"
            f"📦 {human_readable_size(cached_file.get('size', 0))}\n\n"
            f"🎯 Pilih Template:",
            reply_markup=kb
        )
    
    # Multiple files - store for batch and show template picker
    USER_DATA[chat_id] = {
        "batch_cache_files": valid_files,
        "res": "all", "audio": "he", "mode": "crf",
        "font": DEFAULT_FONT_SIZE, "margin": DEFAULT_MARGIN_V, "srt": None,
        "crf": "26"
    }
    
    file_list = "\n".join([f"  #{fid} - {f['name'][:40]}..." for fid, f in valid_files])
    total_size = sum(f.get('size', 0) for _, f in valid_files)
    
    kb = build_template_keyboard()
    await message.reply(
        f"📂 <b>Batch Encode dari Cache</b>\n\n"
        f"📋 <b>{len(valid_files)} files:</b>\n{file_list}\n\n"
        f"📦 Total: {human_readable_size(total_size)}\n\n"
        f"🎯 Pilih Template (akan dipakai untuk semua file):",
        reply_markup=kb
    )

# --- HANDLER /auth & /unauth ---
@app.on_message(filters.command("auth") & filters.user(OWNER_ID))
async def auth_cmd(client, message):
    try:
        user_id = int(message.command[1])
        AUTH_USERS.add(user_id)
        save_auth()
        await message.reply(f"✅ User <code>{user_id}</code> berhasil diizinkan.")
    except:
        await message.reply("❌ Format salah. Gunakan: <code>/auth 12345678</code>")

@app.on_message(filters.command("unauth") & filters.user(OWNER_ID))
async def unauth_cmd(client, message):
    try:
        user_id = int(message.command[1])
        if user_id in AUTH_USERS:
            AUTH_USERS.remove(user_id)
            save_auth()
            await message.reply(f"✅ User <code>{user_id}</code> dihapus dari daftar izin.")
        else:
            await message.reply("❌ User ID tidak ditemukan di daftar.")
    except:
        await message.reply("❌ Format salah. Gunakan: <code>/unauth 12345678</code>")

@app.on_message(filters.command("users") & filters.user(OWNER_ID))
async def users_cmd(client, message):
    if not AUTH_USERS:
        return await message.reply("📂 Belum ada user terdaftar.")
    text = "👥 <b>Daftar User Ter-Auth:</b>\n\n" + "\n".join([f"• <code>{uid}</code>" for uid in AUTH_USERS])
    await message.reply(text)

# --- HANDLER /log (Send bot log file) ---
@app.on_message(filters.command("log") & filters.user(OWNER_ID))
async def log_cmd(client, message):
    """Send bot log file for debugging"""
    log_file = os.path.join(DATA_FOLDER, "bot_log.txt")
    
    if not os.path.exists(log_file):
        return await message.reply("📋 Log file tidak ditemukan.")
    
    file_size = os.path.getsize(log_file)
    
    # If file too large, send last 100KB
    if file_size > 100 * 1024:
        # Read last 100KB
        with open(log_file, 'rb') as f:
            f.seek(-100 * 1024, 2)  # Seek from end
            content = f.read().decode('utf-8', errors='ignore')
        
        # Save to temp file
        temp_log = os.path.join(DATA_FOLDER, "bot_log_tail.txt")
        with open(temp_log, 'w', encoding='utf-8') as f:
            f.write(content)
        
        await client.send_document(
            message.chat.id,
            temp_log,
            caption=f"📋 <b>Bot Log (last 100KB)</b>\n📦 Full size: {human_readable_size(file_size)}"
        )
        
        try:
            os.remove(temp_log)
        except:
            pass
    else:
        await client.send_document(
            message.chat.id,
            log_file,
            caption=f"📋 <b>Bot Log</b>\n📦 Size: {human_readable_size(file_size)}"
        )

# --- HANDLER /tools (List tools in tools folder) ---
@app.on_message(filters.command("tools") & filters.user(OWNER_ID))
async def tools_cmd(client, message):
    """List all tools in tools folder"""
    if not os.path.exists(TOOLS_FOLDER):
        os.makedirs(TOOLS_FOLDER)
    
    files = [f for f in os.listdir(TOOLS_FOLDER) if f.endswith(('.py', '.pyw'))]
    
    if not files:
        return await message.reply(
            f"📂 <b>Folder tools kosong.</b>\n\n"
            f"Kirim file .py dan reply dengan <code>/update</code> untuk menambahkan."
        )
    
    text = "🛠️ <b>Tools Available:</b>\n\n"
    for f in files:
        fpath = os.path.join(TOOLS_FOLDER, f)
        size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
        text += f"• <code>{f}</code> ({human_readable_size(size)})\n"
    
    text += f"\n<i>Reply file .py dengan /update untuk update</i>"
    await message.reply(text)

# --- HANDLER /update (Update tool script via Telegram) ---
@app.on_message(filters.command("update") & filters.user(OWNER_ID))
async def update_tool_cmd(client, message):
    """Update/add tool script by replying to a .py file"""
    # Check if replying to document
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply(
            "❌ <b>Reply ke file .py untuk update!</b>\n\n"
            "Cara pakai:\n"
            "1. Kirim file Python (.py) ke chat\n"
            "2. Reply file tersebut dengan <code>/update</code>"
        )
    
    doc = message.reply_to_message.document
    
    # Check file extension
    if not doc.file_name.endswith(('.py', '.pyw')):
        return await message.reply("❌ Hanya file <b>.py</b> atau <b>.pyw</b> yang bisa di-update!")
    
    # Download file
    status_msg = await message.reply("⏳ Downloading...")
    
    try:
        # Determine target path based on filename
        # script.pyw goes to root folder, other .py files go to tools
        if doc.file_name == "script.pyw":
            target_path = doc.file_name  # Root folder
        else:
            # Ensure tools folder exists
            if not os.path.exists(TOOLS_FOLDER):
                os.makedirs(TOOLS_FOLDER)
            target_path = os.path.join(TOOLS_FOLDER, doc.file_name)
        
        # Backup old file if exists
        backup_path = None
        if os.path.exists(target_path):
            backup_path = target_path + ".bak"
            import shutil
            shutil.copy2(target_path, backup_path)
            # Delete original so download can replace it
            os.remove(target_path)
        
        # Download new file (use absolute path to prevent Pyrogram creating downloads folder)
        abs_target_path = os.path.abspath(target_path)
        await message.reply_to_message.download(file_name=abs_target_path)
        
        # Get file size
        new_size = os.path.getsize(target_path)
        
        # Different message for main script vs tools
        if doc.file_name == "script.pyw":
            result_text = (
                f"✅ <b>Script Updated!</b>\n\n"
                f"📁 <code>{doc.file_name}</code>\n"
                f"📦 {human_readable_size(new_size)}\n"
                f"📂 Path: <code>{target_path}</code>\n\n"
                f"🔄 <i>Restarting bot...</i>"
            )
            if backup_path:
                result_text += f"\n\n💾 <i>Backup: {doc.file_name}.bak</i>"
            
            await status_msg.edit_text(result_text)
            
            # Auto-restart the bot
            await asyncio.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            result_text = (
                f"✅ <b>Tool Updated!</b>\n\n"
                f"📁 <code>{doc.file_name}</code>\n"
                f"📦 {human_readable_size(new_size)}\n"
                f"📂 Path: <code>{target_path}</code>"
            )
        
            if backup_path:
                result_text += f"\n\n💾 <i>Backup: {doc.file_name}.bak</i>"
        
            await status_msg.edit_text(result_text)
        
    except Exception as e:
        logger.error(f"Update tool error: {e}")
        await status_msg.edit_text(f"❌ Error: {e}")

# --- HANDLER /links (Format download links from encode history) ---
def format_links_by_title(history):
    """Format encode history grouped by TITLE, returns dict {title: formatted_content}
    Output format:
    - TurboVid links at top: url - filename
    - Abyss links: filename|url
    - Download links grouped by episode/quality
    """
    from collections import defaultdict
    
    # Group by title
    titles = defaultdict(lambda: {
        'turbovid': [],  # [(filename, url), ...]
        'abyss': [],     # [(filename, url), ...]
        'episodes': defaultdict(lambda: defaultdict(dict))  # episode -> quality -> server -> url
    })
    
    for item in history:
        filename = item['filename']
        quality = item['quality']
        links = item.get('links', {})
        
        # Extract title and episode
        match = re.match(r'(.+?)\.E(\d+)\.(\d+p)\.mp4', filename)
        if match:
            title = match.group(1)
            episode_num = f"E{int(match.group(2)):02d}"
            episode_base = f"{title}.{episode_num}"
        else:
            title = filename.rsplit('.', 3)[0] if '.' in filename else filename
            episode_base = filename.rsplit('.', 2)[0] if '.' in filename else filename
        
        # Collect TurboVid and Abyss links
        if links.get('turbovid'):
            titles[title]['turbovid'].append((filename, links['turbovid']))
        if links.get('abyss'):
            titles[title]['abyss'].append((filename, links['abyss']))
        
        # Collect download links (4 servers only)
        for server, url in links.items():
            if url and server in ['buzzheavier', 'mirrored', 'gofile', 'filepress']:
                titles[title]['episodes'][episode_base][quality][server.title()] = url
    
    if not titles:
        return {}
    
    result = {}
    server_order = ['Buzzheavier', 'Mirrored', 'Filepress', 'Gofile']
    
    for title in sorted(titles.keys()):
        output_lines = []
        
        # TurboVid links section (format: url - filename)
        turbovid_links = titles[title]['turbovid']
        if turbovid_links:
            # Sort by filename
            turbovid_links.sort(key=lambda x: x[0])
            for fname, url in turbovid_links:
                output_lines.append(f"{url} - {fname}")
            output_lines.append("")
        
        # Abyss links section (format: filename|url)
        abyss_links = titles[title]['abyss']
        if abyss_links:
            # Sort by filename
            abyss_links.sort(key=lambda x: x[0])
            for fname, url in abyss_links:
                output_lines.append(f"{fname}|{url}")
            output_lines.append("")
        
        # Download links section
        output_lines.append("Download Link")
        
        def sort_key(ep):
            match = re.search(r'E(\d+)', ep)
            return int(match.group(1)) if match else 0
        
        for episode in sorted(titles[title]['episodes'].keys(), key=sort_key):
            output_lines.append(f"\n{episode}")
            
            quality_order = {'1080p': 0, '720p': 1, '480p': 2, '360p': 3}
            for quality in sorted(titles[title]['episodes'][episode].keys(), 
                                  key=lambda x: quality_order.get(x, 99)):
                output_lines.append(quality)
                
                for server in server_order:
                    if server in titles[title]['episodes'][episode][quality]:
                        output_lines.append(titles[title]['episodes'][episode][quality][server])
        
        result[title] = '\n'.join(output_lines)
    
    return result

def create_telegraph_page(title: str, content: str) -> str:
    """Create Telegraph page using direct HTTP API"""
    try:
        # Step 1: Create account
        acc_response = requests.get(
            "https://api.telegra.ph/createAccount",
            params={"short_name": "EncodeBot", "author_name": "Encode Bot"}
        ).json()
        
        if not acc_response.get("ok"):
            logger.error(f"Telegraph account error: {acc_response}")
            return None
        
        access_token = acc_response["result"]["access_token"]
        
        # Step 2: Build content as node list (Telegraph format)
        lines = content.split('\n')
        nodes = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check line type
            if line.startswith('http'):
                # Link
                nodes.append({
                    "tag": "p",
                    "children": [{"tag": "a", "attrs": {"href": line}, "children": [line]}]
                })
            elif re.match(r'^\d+p$', line):
                # Quality header (bold)
                nodes.append({
                    "tag": "p", 
                    "children": [{"tag": "b", "children": [line]}]
                })
            elif 'Download Link' in line:
                # Main header
                nodes.append({"tag": "h3", "children": [line]})
            elif re.match(r'.+\.E\d+', line):
                # Episode header
                nodes.append({"tag": "h4", "children": [line]})
            else:
                nodes.append({"tag": "p", "children": [line]})
        
        if not nodes:
            nodes = [{"tag": "p", "children": ["No content"]}]
        
        # Step 3: Create page
        page_response = requests.post(
            "https://api.telegra.ph/createPage",
            json={
                "access_token": access_token,
                "title": title,
                "author_name": "Encode Bot",
                "content": nodes,
                "return_content": False
            }
        ).json()
        
        if not page_response.get("ok"):
            logger.error(f"Telegraph page error: {page_response}")
            return None
        
        return page_response["result"]["url"]
        
    except Exception as e:
        logger.error(f"Telegraph error: {e}")
        return None

@app.on_message(filters.command("links") & filters.private)
async def links_cmd(client, message):
    """Generate formatted download links from encode history"""
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    load_encode_history()  # Refresh
    
    if not ENCODE_HISTORY:
        return await message.reply(
            "📂 <b>Encode history kosong.</b>\n\n"
            "<i>Encode video dulu untuk generate links.</i>"
        )
    
    status_msg = await message.reply("⏳ <b>Generating links...</b>")
    
    try:
        # Format links grouped by title
        titles_content = format_links_by_title(ENCODE_HISTORY)
        
        if not titles_content:
            return await status_msg.edit_text("❌ Tidak ada links di history.")
        
        await status_msg.delete()
        
        # Send separate file for each title
        for title, content in titles_content.items():
            # Clean title for filename
            safe_title = re.sub(r'[^\w\-_.]', '_', title)
            filename = f"{safe_title}.txt"
            filepath = os.path.join(DATA_FOLDER, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            await client.send_document(
                chat_id,
                filepath,
                caption=f"📋 <b>{title.replace('.', ' ')}</b>"
            )
            
            try:
                os.remove(filepath)
            except:
                pass
        
    except Exception as e:
        logger.error(f"Links command error: {e}")
        await status_msg.edit_text(f"❌ Error: {e}")

@app.on_message(filters.command("clearhistory") & filters.private)
async def clearhistory_cmd(client, message):
    """Clear encode history"""
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    count = len(ENCODE_HISTORY)
    clear_encode_history()
    
    await message.reply(f"🗑️ <b>{count} encode records</b> dihapus dari history.")

def format_single_server_links(history, server_key):
    """Format links for a single server (gdrive/seedbox) grouped by title with episode range - 1080p only"""
    from collections import defaultdict
    
    # Group by title (series name without episode number)
    titles = defaultdict(list)
    
    for item in history:
        filename = item['filename']
        quality = item.get('quality', '')
        
        # Only include 1080p
        if quality != '1080p':
            continue
        
        link = item.get('links', {}).get(server_key)
        if not link:
            continue
        
        # Extract title and episode number
        # Pattern: Title.Name.E01.1080p.mp4
        match = re.match(r'(.+?)\.E(\d+)\.(\d+p)\.mp4', filename)
        if match:
            title = match.group(1).replace('.', ' ')
            episode = int(match.group(2))
        else:
            # Fallback
            title = filename.rsplit('.', 2)[0].replace('.', ' ')
            episode = 0
        
        titles[title].append({
            'episode': episode,
            'quality': quality,
            'link': link
        })
    
    if not titles:
        return None
    
    output_lines = []
    
    for title in sorted(titles.keys()):
        items = titles[title]
        # Sort by episode
        items.sort(key=lambda x: x['episode'])
        
        # Get episode range
        eps = [i['episode'] for i in items if i['episode'] > 0]
        if eps:
            ep_range = f"E{min(eps):02d}-E{max(eps):02d}" if min(eps) != max(eps) else f"E{min(eps):02d}"
        else:
            ep_range = ""
        
        # Get qualities
        qualities = sorted(set(i['quality'] for i in items), key=lambda x: int(x.replace('p', '')) if x.replace('p', '').isdigit() else 0, reverse=True)
        
        # Header
        output_lines.append(f"\n{title}")
        if ep_range:
            output_lines.append(f"{ep_range} | {', '.join(qualities)}")
        output_lines.append("")
        
        # Links
        for item in items:
            output_lines.append(item['link'])
    
    return '\n'.join(output_lines)

@app.on_message(filters.command("linksdrive") & filters.private)
async def linksdrive_cmd(client, message):
    """Generate Google Drive links from encode history"""
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    load_encode_history()
    
    if not ENCODE_HISTORY:
        return await message.reply("📂 <b>Encode history kosong.</b>")
    
    status_msg = await message.reply("⏳ <b>Generating GDrive links...</b>")
    
    try:
        formatted = format_single_server_links(ENCODE_HISTORY, "gdrive")
        
        if not formatted:
            return await status_msg.edit_text("❌ Tidak ada GDrive links di history.")
        
        # Save to txt file
        from datetime import datetime
        filename = f"gdrive_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(DATA_FOLDER, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("Google Drive Links\n")
            f.write(formatted)
        
        await status_msg.delete()
        
        await client.send_document(
            chat_id,
            filepath,
            caption=f"☁️ <b>Google Drive Links</b>"
        )
        
        try:
            os.remove(filepath)
        except:
            pass
        
    except Exception as e:
        logger.error(f"LinksDrive command error: {e}")
        await status_msg.edit_text(f"❌ Error: {e}")

@app.on_message(filters.command("linksbox") & filters.private)
async def linksbox_cmd(client, message):
    """Generate Seedbox links from encode history"""
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    load_encode_history()
    
    if not ENCODE_HISTORY:
        return await message.reply("📂 <b>Encode history kosong.</b>")
    
    status_msg = await message.reply("⏳ <b>Generating Seedbox links...</b>")
    
    try:
        formatted = format_single_server_links(ENCODE_HISTORY, "seedbox")
        
        if not formatted:
            return await status_msg.edit_text("❌ Tidak ada Seedbox links di history.")
        
        # Save to txt file
        from datetime import datetime
        filename = f"seedbox_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(DATA_FOLDER, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("Seedbox Links\n")
            f.write(formatted)
        
        await status_msg.delete()
        
        await client.send_document(
            chat_id,
            filepath,
            caption=f"📦 <b>Seedbox Links</b>"
        )
        
        try:
            os.remove(filepath)
        except:
            pass
        
    except Exception as e:
        logger.error(f"LinksBox command error: {e}")
        await status_msg.edit_text(f"❌ Error: {e}")

# --- HANDLER /addlist (Manually add to encode history by replying to upload message) ---
@app.on_message(filters.command("addlist") & filters.private)
async def addlist_cmd(client, message):
    """Add encode result to history by replying to upload message"""
    chat_id = message.from_user.id
    if not check_auth(chat_id): return
    
    # Check if replying to a message
    if not message.reply_to_message or not message.reply_to_message.text:
        return await message.reply(
            "❌ <b>Reply ke pesan hasil upload!</b>\n\n"
            "Cara pakai: Reply pesan hasil encode dengan <code>/addlist</code>"
        )
    
    text = message.reply_to_message.text
    
    # Parse filename and quality from message
    # Pattern: 🎬 Filename.E01.1080p.mp4 or 🎬 <code>Filename.mp4</code>
    filename_match = re.search(r'🎬\s*(?:<code>)?([^\n<]+\.mp4)(?:</code>)?', text)
    if not filename_match:
        return await message.reply("❌ Tidak dapat menemukan nama file dalam pesan.")
    
    filename = filename_match.group(1).strip()
    
    # Extract quality from filename
    quality_match = re.search(r'(\d+p)', filename)
    quality = quality_match.group(1) if quality_match else "unknown"
    
    # Parse links from message
    links = {
        "seedbox": None,
        "gdrive": None,
        "buzzheavier": None,
        "mirrored": None,
        "gofile": None,
        "filepress": None,
    }
    
    # Seedbox (format: 📦 Seedbox: ✅\nhttps://... OR Seedbox:\nhttps://...)
    seedbox_match = re.search(r'Seedbox[:\s]*[✅❌⏳]?\s*\n?(https://[^\s]+)', text)
    if seedbox_match:
        links["seedbox"] = seedbox_match.group(1)
    
    # GDrive (format: ☁️ GDrive: ✅\nhttps://...)
    gdrive_match = re.search(r'GDrive[:\s]*[✅❌⏳]?\s*\n?(https://drive\.google\.com/[^\s]+)', text)
    if gdrive_match:
        links["gdrive"] = gdrive_match.group(1)
    
    # Buzzheavier (format: 🐝 Buzzheavier: ✅\nhttps://...)
    buzz_match = re.search(r'Buzzheavier[:\s]*[✅❌⏳]?\s*\n?(https://buzzheavier\.com/\S+)', text)
    if buzz_match:
        links["buzzheavier"] = buzz_match.group(1)
    
    # Mirrored (format: 🪞 Mirrored: ✅\nhttps://...)
    mir_match = re.search(r'Mirrored[:\s]*[✅❌⏳]?\s*\n?(https://mir\.cr/\S+)', text)
    if mir_match:
        links["mirrored"] = mir_match.group(1)
    
    # Gofile (format: 📁 Gofile: ✅\nhttps://...)
    gofile_match = re.search(r'Gofile[:\s]*[✅❌⏳]?\s*\n?(https://gofile\.io/\S+)', text)
    if gofile_match:
        links["gofile"] = gofile_match.group(1)
    
    # FilePress (format: 🎬 FilePress: ✅\nhttps://...)
    fp_match = re.search(r'FilePress[:\s]*[✅❌⏳]?\s*\n?(https://[^\s]+filepress[^\s]+)', text)
    if fp_match:
        links["filepress"] = fp_match.group(1)
    
    # Check if any links found
    found_links = {k: v for k, v in links.items() if v}
    if not found_links:
        return await message.reply("❌ Tidak dapat menemukan link dalam pesan.")
    
    # Add to history
    add_to_encode_history(
        filename=filename,
        quality=quality,
        links=links,
        meta={"source": "manual_addlist"}
    )
    
    link_list = "\n".join([f"• {k.title()}: ✅" for k, v in found_links.items()])
    await message.reply(
        f"✅ <b>Added to history!</b>\n\n"
        f"🎬 <code>{filename}</code>\n"
        f"📺 Quality: {quality}\n\n"
        f"🔗 Links:\n{link_list}"
    )


@app.on_message(filters.command("status"))
async def status_cmd(client, message):
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    text = "📊 <b>STATUS BOT</b>\n━━━━━━━━━━━━━━━━━━\n"
    
    # Current job
    if CURRENT_JOB:
        job_type = CURRENT_JOB.get('type', 'encode')
        fname = CURRENT_JOB.get('real_name', 'Unknown')[:40]
        text += f"🔄 <b>Job Aktif:</b> {job_type.upper()}\n"
        text += f"📁 <code>{fname}</code>\n\n"
    else:
        text += "💤 <b>Tidak ada job aktif</b>\n\n"
    
    # Queue
    text += f"📋 <b>Antrian:</b> {len(JOB_QUEUE)} job\n"
    
    # System
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    text += f"\n🧠 CPU: {cpu}% | 💾 RAM: {ram}%"
    
    await message.reply(text)

# --- HANDLER /fb (Browse Seedbox FileBrowser) ---
@app.on_message(filters.command("fb"))
async def fb_cmd(client, message):
    """Browse seedbox files via FileBrowser dan pilih untuk encode"""
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    if not SEEDBOX_ENABLED:
        return await message.reply("❌ Seedbox tidak dikonfigurasi.")
    
    status_msg = await message.reply("⏳ <b>Mengambil daftar file dari Seedbox...</b>")
    
    try:
        # Build FileBrowser info dari config
        fb_info = {
            "base_url": SEEDBOX_FB_URL,
            "hash": SEEDBOX_FB_SHARE_HASH,
            "path_prefix": "/filebrowser" if "/filebrowser" in SEEDBOX_FB_URL else ""
        }
        
        # Fetch file list
        files = await asyncio.to_thread(fetch_filebrowser_files, fb_info)
        
        if not files:
            return await status_msg.edit("❌ Tidak ada file di folder share seedbox.")
        
        # Filter hanya video files
        video_exts = ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.ts', '.m2ts']
        video_files = [f for f in files if any(f['name'].lower().endswith(ext) for ext in video_exts)]
        
        if not video_files:
            return await status_msg.edit("❌ Tidak ada file video di folder share seedbox.")
        
        # Sort by modified time (newest first)
        video_files.sort(key=lambda x: x.get('modified', ''), reverse=True)
        
        # Limit to 20 files for display
        display_files = video_files[:20]
        
        # Save to USER_DATA
        USER_DATA[chat_id] = USER_DATA.get(chat_id, {})
        USER_DATA[chat_id]["fb_info"] = fb_info
        USER_DATA[chat_id]["fb_files"] = video_files
        USER_DATA[chat_id]["fb_selected"] = set()
        USER_DATA[chat_id]["fb_page"] = 0
        
        # Build message
        text = f"📂 <b>Seedbox Files</b>\n"
        text += f"📋 {len(video_files)} video files\n\n"
        text += "Pilih file untuk encode:\n"
        
        # Build buttons (show first 10)
        buttons = []
        for i, f in enumerate(display_files[:10]):
            name = f['name'][:35] + "..." if len(f['name']) > 35 else f['name']
            size_mb = f.get('size', 0) / 1024 / 1024
            btn_text = f"📁 {name} ({size_mb:.0f}MB)"
            buttons.append([InlineKeyboardButton(btn_text, f"fb_sel_{i}")])
        
        # Navigation buttons
        nav_row = []
        if len(video_files) > 10:
            nav_row.append(InlineKeyboardButton("➡️ Lanjut", "fb_page_1"))
        buttons.append(nav_row if nav_row else [InlineKeyboardButton("─────", "ignore")])
        
        # Action buttons
        buttons.append([
            InlineKeyboardButton("✅ Encode Terpilih", "fb_encode_selected"),
            InlineKeyboardButton("🔄 Refresh", "fb_refresh")
        ])
        buttons.append([InlineKeyboardButton("❌ Tutup", "close_menu")])
        
        await status_msg.edit(text, reply_markup=InlineKeyboardMarkup(buttons))
        
    except Exception as e:
        logger.error(f"FB Browse Error: {e}")
        await status_msg.edit(f"❌ Error: {e}")

# --- HANDLER /queue ---
@app.on_message(filters.command("queue"))
async def queue_cmd(client, message):
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    if not JOB_QUEUE:
        return await message.reply("📭 <b>Antrian kosong.</b>")
    
    text = "📋 <b>ANTRIAN JOB</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    for i, job in enumerate(JOB_QUEUE, 1):
        job_type = job.get('type', 'encode')
        fname = job.get('real_name', 'Unknown')[:35]
        
        # Build config info for encode jobs
        if job_type == 'encode':
            # Resolutions
            queue_res = job.get('queue', [])
            res_str = "+".join(queue_res) if queue_res else "?"
            
            # CRF info
            res_crf = job.get('res_crf', {})
            if res_crf:
                crf_str = "/".join([res_crf.get(r, job.get('crf', '26')) for r in queue_res])
            else:
                crf_str = job.get('crf', '26')
            
            mode = job.get('mode', 'crf').upper()
            font = job.get('font', '?')
            margin = job.get('margin', '?')
            
            config = f"📺 {res_str} | CRF:{crf_str} | {mode} | F{font} M{margin}"
            text += f"{i}. <code>{fname}</code>\n   {config}\n\n"
        else:
            # Non-encode jobs (leech, convert, etc)
            text += f"{i}. [{job_type.upper()}] <code>{fname}</code>\n\n"
    
    await message.reply(text)

# --- HANDLER /clearqueue ---
@app.on_message(filters.command("clearqueue"))
async def clearqueue_cmd(client, message):
    """Clear semua antrian tanpa menghentikan proses yang sedang berjalan"""
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    if not JOB_QUEUE:
        return await message.reply("📭 <b>Antrian sudah kosong.</b>")
    
    count = len(JOB_QUEUE)
    JOB_QUEUE.clear()
    
    await message.reply(
        f"🗑️ <b>Queue Cleared!</b>\n\n"
        f"✅ {count} job dihapus dari antrian.\n"
        f"⚙️ Proses yang sedang berjalan TIDAK dihentikan."
    )

# --- HANDLER /leech ---
@app.on_message(filters.command("leech"))
async def leech_cmd(client, message):
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    # Cek argumen: /leech <link>
    if len(message.command) > 1:
        url = message.text.split(maxsplit=1)[1]
    # Cek reply: reply link
    elif message.reply_to_message:
        if message.reply_to_message.text:
            url = message.reply_to_message.text
        else:
            return await message.reply("❌ Reply link!")
    else:
        return await message.reply("❌ Format: <code>/leech link</code> atau reply link.")

    # Validasi link
    if not url.startswith("http"):
        return await message.reply("❌ Link tidak valid.")

    status_msg = await message.reply("⏳ <b>Menambahkan ke antrian Leech...</b>")
    
    # Determine filename (async)
    real_name = await asyncio.to_thread(get_real_filename, url)
    
    job = {
        "chat_id": chat_id, "msg_id": status_msg.id,
        "url": url, "filename": f"leech_{chat_id}_in.mkv", "real_name": real_name,
        "type": "leech",  # TIPE JOB: LEECH
        "queue": [], # Tidak ada queue resolusi
        "is_cancelled": False
    }
    
    JOB_QUEUE.append(job)
    await message.reply(f"📥 <b>Leech Job Added!</b>\nPosisi antrian: {len(JOB_QUEUE)}")
    await check_queue()

# --- HANDLER /convert (GDrive to Seedbox) ---
@app.on_message(filters.command("convert"))
async def convert_cmd(client, message):
    """Download dari GDrive dan upload ke Seedbox (tanpa encode) - support multiple URLs"""
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    if not SEEDBOX_ENABLED:
        return await message.reply("❌ Seedbox tidak aktif.")
    
    # Parse URLs - support: /convert url1, url2, url3 atau /convert url1 url2 url3
    if len(message.command) > 1:
        raw_urls = message.text.split(maxsplit=1)[1]
    elif message.reply_to_message and message.reply_to_message.text:
        raw_urls = message.reply_to_message.text
    else:
        return await message.reply("❌ Format: <code>/convert link</code> atau <code>/convert link1, link2, link3</code>")
    
    # Split by comma or whitespace for multiple URLs
    raw_urls = raw_urls.replace(",", " ")
    urls = [u.strip() for u in raw_urls.split() if u.strip().startswith("http")]
    
    if not urls:
        return await message.reply("❌ Link tidak valid.")
    
    # Single URL - original flow
    if len(urls) == 1:
        url = urls[0]
        status_msg = await message.reply("⏳ <b>Memulai Convert GDrive → Seedbox...</b>")
        
        # Shared state untuk progress
        convert_state = {
            "phase": "init",
            "filename": "Unknown",
            "dl_pct": 0, "dl_speed": "0 MB/s", "dl_size": "?",
            "up_pct": 0
        }
        
        async def update_progress():
            """Background task untuk update pesan status"""
            last_text = ""
            while convert_state["phase"] not in ["done", "error"]:
                try:
                    if convert_state["phase"] == "download":
                        text = (
                            f"📥 <b>Downloading:</b>\n"
                            f"<code>{convert_state['filename']}</code>\n\n"
                            f"{create_progress_bar(convert_state['dl_pct'])}\n"
                            f"📦 {convert_state['dl_size']} | 🚀 {convert_state['dl_speed']}"
                        )
                    elif convert_state["phase"] == "upload":
                        text = (
                            f"📤 <b>Uploading to Seedbox:</b>\n"
                            f"<code>{convert_state['filename']}</code>\n\n"
                            f"{create_progress_bar(convert_state['up_pct'])}"
                        )
                    else:
                        text = f"⏳ <b>{convert_state['phase']}</b>"
                    
                    if text != last_text:
                        await client.edit_message_text(chat_id, status_msg.id, text)
                        last_text = text
                except:
                    pass
                await asyncio.sleep(2)
        
        # Start progress updater
        progress_task = asyncio.create_task(update_progress())
        
        try:
            # 1. Get filename
            convert_state["phase"] = "Mengambil info file..."
            real_name = await asyncio.to_thread(get_real_filename, url)
            filename = f"convert_{chat_id}_{int(time.time())}.tmp"
            convert_state["filename"] = real_name
            
            # 2. Download with progress
            convert_state["phase"] = "download"
            
            def dl_file_with_progress():
                cmd = ["yt-dlp", "-o", filename, "--newline", "--force-overwrites", url]
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='ignore', **get_hidden_params())
                
                while True:
                    line = p.stdout.readline()
                    if not line and p.poll() is not None:
                        break
                    
                    if "[download]" in line:
                        # Parse percentage
                        pct_match = re.search(r"(\d+\.?\d*)%", line)
                        if pct_match:
                            convert_state["dl_pct"] = float(pct_match.group(1))
                        
                        # Parse size
                        size_match = re.search(r"of\s+([\d.]+\s*[KMGT]?i?B)", line)
                        if size_match:
                            convert_state["dl_size"] = size_match.group(1)
                        
                        # Parse speed
                        speed_match = re.search(r"at\s+([\d.]+\s*[KMGT]?i?B/s)", line)
                        if speed_match:
                            convert_state["dl_speed"] = speed_match.group(1)
                
                if p.returncode != 0:
                    raise Exception(f"Download failed")
            
            await asyncio.to_thread(dl_file_with_progress)
            
            if not os.path.exists(filename):
                raise Exception("File tidak ditemukan setelah download")
            
            # Rename to real name
            clean_name = os.path.basename(urllib.parse.unquote(real_name))
            # Sanitize filename
            clean_name = re.sub(r'[<>:"/\\|?*]', '_', clean_name)
            if os.path.exists(clean_name): os.remove(clean_name)
            os.rename(filename, clean_name)
            convert_state["filename"] = clean_name
            
            # 3. Upload to Seedbox with progress
            convert_state["phase"] = "upload"
            convert_state["up_pct"] = 0
            file_size = os.path.getsize(clean_name)
            
            seedbox_link = await asyncio.to_thread(filebrowser_upload_file, clean_name, chat_id, convert_state)
            
            # 4. Cleanup & Send result
            convert_state["phase"] = "done"
            progress_task.cancel()
            
            if os.path.exists(clean_name): os.remove(clean_name)
            
            if seedbox_link:
                await client.edit_message_text(
                    chat_id, status_msg.id,
                    f"✅ <b>Convert Selesai!</b>\n\n"
                    f"🎬 <code>{clean_name}</code>\n"
                    f"📦 Size: {human_readable_size(file_size)}\n\n"
                    f"📦 <b>Seedbox:</b>\n{seedbox_link}"
                )
            else:
                await client.edit_message_text(chat_id, status_msg.id, "❌ Upload ke Seedbox gagal!")
                
        except Exception as e:
            convert_state["phase"] = "error"
            progress_task.cancel()
            logger.error(f"Convert Error: {e}")
            await client.edit_message_text(chat_id, status_msg.id, f"❌ <b>Error:</b> {str(e)[:200]}")
        return
    
    # Multiple URLs - PARALLEL batch mode
    status_msg = await message.reply(
        f"📋 <b>Batch Convert: {len(urls)} files</b>\n\n"
        f"⬇️ Downloading all files in parallel..."
    )
    
    results = {}  # {index: {"name": ..., "link": ...}}
    
    async def process_one(idx, url):
        """Download and upload one file"""
        try:
            real_name = await asyncio.to_thread(get_real_filename, url)
            temp_file = f"batch_{chat_id}_{idx}_{int(time.time())}.tmp"
            
            def dl():
                cmd = ["yt-dlp", "-o", temp_file, "--force-overwrites", url]
                subprocess.run(cmd, capture_output=True, **get_hidden_params())
            
            await asyncio.to_thread(dl)
            
            if not os.path.exists(temp_file):
                results[idx] = {"status": "❌", "name": f"#{idx}", "link": "Download gagal"}
                return
            
            clean_name = re.sub(r'[<>:"/\\|?*]', '_', os.path.basename(urllib.parse.unquote(real_name)))
            final_name = f"batch_{idx}_{clean_name}"
            if os.path.exists(final_name): os.remove(final_name)
            os.rename(temp_file, final_name)
            
            seedbox_link = await asyncio.to_thread(filebrowser_upload_file, final_name, chat_id, None)
            
            if os.path.exists(final_name): os.remove(final_name)
            
            if seedbox_link:
                results[idx] = {"status": "✅", "name": clean_name[:40], "link": seedbox_link}
            else:
                results[idx] = {"status": "❌", "name": clean_name[:40], "link": "Upload gagal"}
                
        except Exception as e:
            results[idx] = {"status": "❌", "name": f"#{idx}", "link": str(e)[:40]}
    
    # Run ALL downloads+uploads in parallel
    await asyncio.gather(*[process_one(i, url) for i, url in enumerate(urls, 1)], return_exceptions=True)
    
    # Build final result
    result_lines = []
    for i in range(1, len(urls) + 1):
        r = results.get(i, {"status": "❌", "name": f"#{i}", "link": "Unknown error"})
        result_lines.append(f"{r['status']} #{i} - {r['name']}\n{r['link']}")
    
    await client.edit_message_text(
        chat_id, status_msg.id,
        f"📋 <b>Batch Convert Selesai!</b>\n\n" + "\n\n".join(result_lines)
    )

# --- HANDLER /fp (FilePress Mirror from GDrive) ---
@app.on_message(filters.command("fp"))
async def filepress_cmd(client, message):
    """Mirror GDrive links to FilePress - support multiple URLs"""
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    if not FILEPRESS_ENABLED:
        return await message.reply("❌ FilePress tidak aktif.")
    
    # Parse URLs
    if len(message.command) > 1:
        raw_urls = message.text.split(maxsplit=1)[1]
    elif message.reply_to_message and message.reply_to_message.text:
        raw_urls = message.reply_to_message.text
    else:
        return await message.reply(
            "❌ Format: <code>/fp gdrive_link</code> atau <code>/fp link1, link2, link3</code>\n\n"
            "Mirror Google Drive ke FilePress"
        )
    
    # Split by comma or whitespace
    raw_urls = raw_urls.replace(",", " ")
    urls = [u.strip() for u in raw_urls.split() if "drive.google.com" in u.strip() or (len(u.strip()) > 20 and "/" not in u.strip())]
    
    if not urls:
        return await message.reply("❌ Link GDrive tidak valid.")
    
    # Single URL
    if len(urls) == 1:
        url = urls[0]
        status_msg = await message.reply("🎬 <b>Mirroring to FilePress...</b>")
        
        try:
            link = await asyncio.to_thread(filepress_mirror, url)
            
            if link:
                await client.edit_message_text(
                    chat_id, status_msg.id,
                    f"✅ <b>FilePress Mirror Selesai!</b>\n\n"
                    f"🔗 GDrive: <code>{url[:50]}...</code>\n\n"
                    f"🎬 <b>FilePress:</b>\n{link}"
                )
            else:
                await client.edit_message_text(chat_id, status_msg.id, "❌ FilePress mirror gagal!")
                
        except Exception as e:
            logger.error(f"FP Error: {e}")
            await client.edit_message_text(chat_id, status_msg.id, f"❌ <b>Error:</b> {str(e)[:200]}")
        return
    
    # Multiple URLs - PARALLEL
    status_msg = await message.reply(f"🎬 <b>Batch FilePress: {len(urls)} links</b>\n\n⏳ Mirroring all in parallel...")
    
    results = {}
    
    async def mirror_one(idx, url):
        try:
            # Get filename from GDrive
            filename = await asyncio.to_thread(get_real_filename, url)
            if filename:
                filename = os.path.basename(urllib.parse.unquote(filename))
                filename = filename[:40] + "..." if len(filename) > 40 else filename
            else:
                filename = f"File #{idx}"
            
            link = await asyncio.to_thread(filepress_mirror, url)
            if link:
                results[idx] = {"status": "✅", "name": filename, "link": link}
            else:
                results[idx] = {"status": "❌", "name": filename, "link": "Mirror gagal"}
        except Exception as e:
            results[idx] = {"status": "❌", "name": f"File #{idx}", "link": str(e)[:30]}
    
    await asyncio.gather(*[mirror_one(i, url) for i, url in enumerate(urls, 1)], return_exceptions=True)
    
    # Build result - sort by filename A-Z
    sorted_results = sorted(results.values(), key=lambda x: x.get("name", "").lower())
    
    result_lines = []
    for r in sorted_results:
        result_lines.append(f"{r['name']}\n{r['link']}")
    
    await client.edit_message_text(
        chat_id, status_msg.id,
        f"🎬 <b>Batch FilePress Selesai!</b>\n\n" + "\n\n".join(result_lines)
    )

# --- HANDLER /up (Download → Multi-Host Upload) ---
@app.on_message(filters.command("up"))
async def up_cmd(client, message):
    """Download dari link dan upload ke Buzzheavier, Mirrored, Gofile - support multiple URLs"""
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    # Parse URLs - support: /up url1, url2, url3
    if len(message.command) > 1:
        raw_urls = message.text.split(maxsplit=1)[1]
    elif message.reply_to_message and message.reply_to_message.text:
        raw_urls = message.reply_to_message.text
    else:
        return await message.reply(
            "❌ Format: <code>/up link</code> atau <code>/up link1, link2, link3</code>\n\n"
            "Upload ke: 🐝 Buzzheavier | 📁 Gofile | 🪞 Mirrored"
        )
    
    # Split by comma or whitespace
    raw_urls = raw_urls.replace(",", " ")
    urls = [u.strip() for u in raw_urls.split() if u.strip().startswith("http")]
    
    if not urls:
        return await message.reply("❌ Link tidak valid.")
    
    # Single URL - detailed progress
    if len(urls) == 1:
        url = urls[0]
        status_msg = await message.reply("⏳ <b>Memulai proses upload...</b>")
        
        try:
            await client.edit_message_text(chat_id, status_msg.id, "📋 <b>Mengambil info file...</b>")
            real_name = await asyncio.to_thread(get_real_filename, url)
            temp_file = f"up_{chat_id}_{int(time.time())}.tmp"
            
            await client.edit_message_text(
                chat_id, status_msg.id, 
                f"📥 <b>Downloading:</b>\n<code>{real_name}</code>"
            )
            
            def download_file():
                cmd = ["yt-dlp", "-o", temp_file, "--force-overwrites", url]
                result = subprocess.run(cmd, capture_output=True, text=True, **get_hidden_params())
                if result.returncode != 0:
                    raise Exception(f"Download failed")
            
            await asyncio.to_thread(download_file)
            
            if not os.path.exists(temp_file):
                raise Exception("File tidak ditemukan")
            
            clean_name = os.path.basename(urllib.parse.unquote(real_name))
            clean_name = re.sub(r'[<>:"/\\|?*]', '_', clean_name)
            if os.path.exists(clean_name): os.remove(clean_name)
            os.rename(temp_file, clean_name)
            
            file_size = os.path.getsize(clean_name)
            
            upload_status = {"buzzheavier": "⏳", "gofile": "⏳", "mirrored": "⏳"}
            upload_links = {"buzzheavier": None, "gofile": None, "mirrored": None}
            
            def build_up_msg():
                return (
                    f"⬆️ <b>Uploading:</b>\n<code>{clean_name}</code>\n"
                    f"📦 {human_readable_size(file_size)}\n\n"
                    f"🐝 Buzzheavier: {upload_status['buzzheavier']}\n"
                    f"📁 Gofile: {upload_status['gofile']}\n"
                    f"🪞 Mirrored: {upload_status['mirrored']}"
                )
            
            await client.edit_message_text(chat_id, status_msg.id, build_up_msg())
            
            async def update_up_msg():
                try: await client.edit_message_text(chat_id, status_msg.id, build_up_msg())
                except: pass
            
            async def up_buzzheavier():
                if not BUZZHEAVIER_ENABLED: upload_status["buzzheavier"] = "⭕"; return None
                try:
                    link = await asyncio.to_thread(buzzheavier_upload_file, clean_name)
                    upload_status["buzzheavier"] = "✅" if link else "❌"
                    upload_links["buzzheavier"] = link
                    await update_up_msg()
                    return link
                except: upload_status["buzzheavier"] = "❌"; await update_up_msg(); return None
            
            async def up_gofile():
                if not GOFILE_ENABLED: upload_status["gofile"] = "⭕"; return None
                try:
                    link = await asyncio.to_thread(gofile_upload_file, clean_name)
                    upload_status["gofile"] = "✅" if link else "❌"
                    upload_links["gofile"] = link
                    await update_up_msg()
                    return link
                except: upload_status["gofile"] = "❌"; await update_up_msg(); return None
            
            async def up_mirrored():
                if not MIRRORED_ENABLED: upload_status["mirrored"] = "⭕"; return None
                try:
                    link = await asyncio.to_thread(mirrored_upload_file, clean_name)
                    upload_status["mirrored"] = "✅" if link else "❌"
                    upload_links["mirrored"] = link
                    await update_up_msg()
                    return link
                except: upload_status["mirrored"] = "❌"; await update_up_msg(); return None
            
            await asyncio.gather(up_buzzheavier(), up_gofile(), up_mirrored(), return_exceptions=True)
            
            if os.path.exists(clean_name): os.remove(clean_name)
            
            result_msg = f"✅ <b>Upload Selesai!</b>\n\n🎬 <code>{clean_name}</code>\n📦 {human_readable_size(file_size)}\n\n"
            if upload_links["buzzheavier"]: result_msg += f"🐝 <b>Buzzheavier:</b>\n{upload_links['buzzheavier']}\n\n"
            if upload_links["gofile"]: result_msg += f"📁 <b>Gofile:</b>\n{upload_links['gofile']}\n\n"
            if upload_links["mirrored"]: result_msg += f"🪞 <b>Mirrored:</b>\n{upload_links['mirrored']}"
            
            await client.edit_message_text(chat_id, status_msg.id, result_msg)
            
        except Exception as e:
            logger.error(f"UP Error: {e}")
            await client.edit_message_text(chat_id, status_msg.id, f"❌ <b>Error:</b> {str(e)[:200]}")
        return
    
    # Multiple URLs - PARALLEL batch mode
    status_msg = await message.reply(f"📋 <b>Batch Upload: {len(urls)} files</b>\n\n⬇️ Downloading & uploading all in parallel...")
    
    results = {}  # {idx: {"name": ..., "links": {...}}}
    
    async def process_one(idx, url):
        """Download and upload to all hosts"""
        try:
            real_name = await asyncio.to_thread(get_real_filename, url)
            temp_file = f"batch_up_{chat_id}_{idx}_{int(time.time())}.tmp"
            
            def dl(): subprocess.run(["yt-dlp", "-o", temp_file, "--force-overwrites", url], capture_output=True, **get_hidden_params())
            await asyncio.to_thread(dl)
            
            if not os.path.exists(temp_file):
                results[idx] = {"status": "❌", "name": f"#{idx}", "links": "Download gagal"}
                return
            
            clean_name = re.sub(r'[<>:"/\\|?*]', '_', os.path.basename(urllib.parse.unquote(real_name)))
            final_name = f"batch_{idx}_{clean_name}"
            if os.path.exists(final_name): os.remove(final_name)
            os.rename(temp_file, final_name)
            
            # Upload to 3 hosts in parallel
            links = {}
            async def up_b(): links["buzz"] = await asyncio.to_thread(buzzheavier_upload_file, final_name) if BUZZHEAVIER_ENABLED else None
            async def up_g(): links["gofile"] = await asyncio.to_thread(gofile_upload_file, final_name) if GOFILE_ENABLED else None
            async def up_m(): links["mir"] = await asyncio.to_thread(mirrored_upload_file, final_name) if MIRRORED_ENABLED else None
            
            await asyncio.gather(up_b(), up_g(), up_m(), return_exceptions=True)
            
            if os.path.exists(final_name): os.remove(final_name)
            
            results[idx] = {"status": "✅", "name": clean_name[:35], "links": links}
            
        except Exception as e:
            results[idx] = {"status": "❌", "name": f"#{idx}", "links": str(e)[:30]}
    
    # Run ALL in parallel
    await asyncio.gather(*[process_one(i, url) for i, url in enumerate(urls, 1)], return_exceptions=True)
    
    # Build result
    result_lines = []
    for i in range(1, len(urls) + 1):
        r = results.get(i, {"status": "❌", "name": f"#{i}", "links": "Error"})
        line = f"{r['status']} #{i} - {r['name']}\n"
        if isinstance(r["links"], dict):
            if r["links"].get("buzz"): line += f"🐝 {r['links']['buzz']}\n"
            if r["links"].get("gofile"): line += f"📁 {r['links']['gofile']}\n"
            if r["links"].get("mir"): line += f"🪞 {r['links']['mir']}"
        else:
            line += r["links"]
        result_lines.append(line)
    
    await client.edit_message_text(chat_id, status_msg.id, f"📋 <b>Batch Upload Selesai!</b>\n\n" + "\n\n".join(result_lines))

@app.on_message(filters.command("kill") & filters.user(OWNER_ID))
async def kill_cmd(client, message):
    await message.reply("💀 <b>FORCE KILL ALL PROCESSES...</b>")
    for chat_id, procs in ACTIVE_PROCESSES.items():
        for p in procs: force_kill_process(p)
    os._exit(0)

# --- FITUR BARU: /update (SELF-RESTART) ---
@app.on_message(filters.command("update") & filters.user(OWNER_ID))
async def update_cmd(client, message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply("❌ <b>Cara Update:</b>\nKirim file script (.py/.pyw) baru, lalu reply file itu dengan perintah <code>/update</code>.")
    
    doc = message.reply_to_message.document
    # Support .pyw untuk ghost mode
    if not doc.file_name.endswith((".py", ".pyw")):
        return await message.reply("❌ Itu bukan file Python (.py/.pyw)!")

    msg = await message.reply("🔄 <b>Mendownload update...</b>")
    
    try:
        # Mendapatkan path script yang sedang berjalan
        current_file = os.path.abspath(__file__)
        
        # Download file baru dan timpa file lama (nama file tetap sama seperti yang berjalan)
        await message.reply_to_message.download(file_name=current_file)
        
        await msg.edit("✅ <b>Update Berhasil!</b>\nMerestart sistem bot (Ghost Mode)...")
        
        # Restart Script
        await asyncio.sleep(2)
        # os.execl akan menggantikan proses saat ini dengan proses baru
        # sys.executable (pythonw.exe) memastikan tetap jalan tanpa console jika awalnya begitu
        os.execl(sys.executable, sys.executable, *sys.argv)
        
    except Exception as e:
        await msg.edit(f"❌ <b>Gagal Update:</b>\n{str(e)}")

# --- FITUR BARU: /cancel COMMAND ---
@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message):
    chat_id = message.chat.id
    
    # Izinkan user ter-auth membatalkan prosesnya sendiri
    if not check_auth(chat_id): return
    
    global IS_WORKING, CURRENT_JOB
    
    # Cek apakah user ini punya job yang sedang berjalan
    is_owner = (CURRENT_JOB and CURRENT_JOB['chat_id'] == chat_id)
    
    # Jika tidak ada job aktif milik user ini, cek antrian
    if not is_owner:
        # Cek apakah ada di antrian pending (JOB_QUEUE)
        # (Opsional: bisa ditambahkan fitur hapus dari antrian, tapi saat ini kita fokus kill active process)
        if chat_id not in ACTIVE_PROCESSES:
            return await message.reply("❌ Tidak ada proses berjalan yang bisa dibatalkan.")

    # Lakukan pembatalan
    if is_owner:
        CURRENT_JOB['is_cancelled'] = True
    
    # Matikan semua proses background milik user ini (ffmpeg/yt-dlp/rclone)
    if chat_id in ACTIVE_PROCESSES:
        proc_count = len(ACTIVE_PROCESSES[chat_id])
        for p in ACTIVE_PROCESSES[chat_id]: 
            force_kill_process(p)
        # Cleanup list setelah kill
        ACTIVE_PROCESSES[chat_id].clear()
        
        # Reset IS_WORKING jika ini job aktif
        if is_owner:
            IS_WORKING = False
            CURRENT_JOB = None
        
        await message.reply(f"🛑 <b>Proses Dibatalkan.</b>\nMematikan {proc_count} sub-proses...")
    else:
        await message.reply("❌ Tidak ada proses berjalan yang bisa dibatalkan.")

# Regex match http links
@app.on_message(filters.regex(r"^https?://") & filters.private)
async def incoming_link(client, message):
    chat_id = message.chat.id
    if not check_auth(chat_id): return

    # Ambil URL
    match = re.search(r"https?://\S+", message.text)
    if not match:
        return await message.reply("Link tidak valid.")
    
    url = match.group(0)
    
    # === CEK FILEBROWSER SHARE LINK ===
    fb_info = parse_filebrowser_url(url)
    if fb_info:
        files = await asyncio.to_thread(fetch_filebrowser_files, fb_info)
        
        if not files:
            return await message.reply("❌ Folder kosong atau gagal mengambil data.")
        
        # Simpan data FileBrowser ke USER_DATA
        USER_DATA[chat_id] = {
            "fb_info": fb_info,
            "fb_files": files,
            "fb_selected": [],  # Index file yang dipilih
            "res": "all", "audio": "aac", "mode": "mixed",
            "font": DEFAULT_FONT_SIZE, "margin": DEFAULT_MARGIN_V, "srt": None,
            "crf": "26"
        }
        
        # Build tombol episode
        buttons = [[InlineKeyboardButton("🚀 ENCODE SEMUA", "fb_all")]]
        
        # Buat tombol per-episode (max 4 per row)
        row = []
        for i, f in enumerate(files):
            # Extract episode number jika ada
            ep_match = re.search(r'[eE](\d+)', f['name'])
            label = f"E{ep_match.group(1)}" if ep_match else f"#{i+1}"
            row.append(InlineKeyboardButton(label, f"fb_sel_{i}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        
        buttons.append([InlineKeyboardButton("✅ SELESAI PILIH", "fb_done")])
        
        text = f"📂 <b>FileBrowser Folder</b>\n"
        text += f"📋 Ditemukan <b>{len(files)}</b> file video\n\n"
        text += "<i>Klik episode untuk toggle pilih, atau ENCODE SEMUA</i>"
        
        await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons))
        return
    
    # === LINK BIASA (Bukan FileBrowser folder) ===
    USER_DATA[chat_id] = {
        "url": url, "res": "all", "audio": "aac", "mode": "mixed",
        "font": DEFAULT_FONT_SIZE, "margin": DEFAULT_MARGIN_V, "srt": None,
        "crf": "26"
    }
    
    # TOMBOL TEMPLATE + MANUAL (dinamis dari TEMPLATES)
    kb = build_template_keyboard()
    await message.reply("🎬 <b>Pilih Template atau Setting Manual:</b>", reply_markup=kb)

@app.on_message(filters.document & filters.private)
async def document_handler(client, message):
    chat_id = message.chat.id
    if not check_auth(chat_id): return
    
    # Handle SRT subtitle file
    if message.document.file_name.endswith(".srt"):
        # CEK: Ada pending job yang menunggu SRT?
        if chat_id in PENDING_SRT_JOBS and len(PENDING_SRT_JOBS[chat_id]) > 0:
            # Ambil JOB PERTAMA (paling lama menunggu) saja
            pending = PENDING_SRT_JOBS[chat_id].pop(0)
            remaining = len(PENDING_SRT_JOBS[chat_id])
            
            # Cleanup jika list kosong
            if remaining == 0:
                del PENDING_SRT_JOBS[chat_id]
            
            job = pending["job"]
            downloaded_file = pending["file"]
            
            # Download SRT file
            srt_path = await message.download(file_name=f"sub_{chat_id}_{int(time.time())}.srt")
            job["srt"] = srt_path
            
            if remaining > 0:
                await message.reply(
                    f"✅ SRT untuk <b>{job['real_name'][:40]}</b> diterima!\n\n"
                    f"📊 <b>{remaining} file lagi</b> menunggu subtitle.\n"
                    f"Upload SRT berikutnya untuk file selanjutnya."
                )
            else:
                await message.reply(f"✅ SRT diterima! Melanjutkan encoding...")
            
            # Re-add job ke queue dengan SRT
            status_msg = await client.send_message(chat_id, f"⏳ <b>Resuming:</b> {job['real_name'][:50]}...")
            job["msg_id"] = status_msg.id
            job["downloaded_file"] = downloaded_file
            JOB_QUEUE.insert(0, job)  # Insert di depan queue
            
            await check_queue()
            return
        
        # Untuk flow normal (waiting_srt dari manual mode)
        if USER_DATA.get(chat_id, {}).get("waiting_srt"):
            srt_path = await message.download(file_name=f"sub_{chat_id}.srt")
            USER_DATA[chat_id]["srt"] = srt_path
            USER_DATA[chat_id]["waiting_srt"] = False
            await finalize_job(client, message, chat_id)
        else:
            await message.reply("ℹ️ Tidak ada job yang menunggu subtitle. Kirim link video dulu.")

@app.on_callback_query()
async def callback_handler(client, query):
    data = query.data
    chat_id = query.message.chat.id
    
    if not check_auth(chat_id): 
        return await query.answer("❌ Anda tidak memiliki akses.", show_alert=True)
    
    if data == "cancel":
        global IS_WORKING, CURRENT_JOB, TEMPLATES
        
        # Set cancel flag di job DAN STATUS_DASHBOARD
        if CURRENT_JOB and CURRENT_JOB['chat_id'] == chat_id:
            CURRENT_JOB['is_cancelled'] = True
        if chat_id in STATUS_DASHBOARD:
            STATUS_DASHBOARD[chat_id]['is_cancelled'] = True
        
        # Kill semua proses aktif
        if chat_id in ACTIVE_PROCESSES:
            for p in ACTIVE_PROCESSES[chat_id]: 
                force_kill_process(p)
            # Cleanup list setelah kill
            ACTIVE_PROCESSES[chat_id].clear()
        
        # Reset IS_WORKING jika job yang dibatalkan adalah job aktif
        if CURRENT_JOB and CURRENT_JOB['chat_id'] == chat_id:
            IS_WORKING = False
            CURRENT_JOB = None
        
        await query.message.edit("🛑 Dibatalkan.")
        return

    if chat_id not in USER_DATA:
        return await query.message.edit("Sesi habis.")

    # === FILEBROWSER CALLBACKS ===
    if data == "fb_all":
        # Select semua file
        files = USER_DATA[chat_id].get("fb_files", [])
        USER_DATA[chat_id]["fb_selected"] = list(range(len(files)))
        
        # Langsung ke pilih template
        kb = build_template_keyboard()
        await query.message.edit(f"✅ <b>{len(files)} file dipilih</b>\n\n🎬 Pilih Template:", reply_markup=kb)
        return
    
    elif data.startswith("fb_sel_"):
        # Toggle select episode
        idx = int(data.replace("fb_sel_", ""))
        selected = USER_DATA[chat_id].get("fb_selected", [])
        
        if idx in selected:
            selected.remove(idx)
        else:
            selected.append(idx)
        
        USER_DATA[chat_id]["fb_selected"] = selected
        
        # Rebuild buttons dengan tanda ✓
        files = USER_DATA[chat_id].get("fb_files", [])
        buttons = [[InlineKeyboardButton("🚀 ENCODE SEMUA", "fb_all")]]
        
        row = []
        for i, f in enumerate(files):
            ep_match = re.search(r'[eE](\d+)', f['name'])
            label = f"E{ep_match.group(1)}" if ep_match else f"#{i+1}"
            if i in selected:
                label = f"✓{label}"
            row.append(InlineKeyboardButton(label, f"fb_sel_{i}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        
        buttons.append([InlineKeyboardButton(f"✅ SELESAI ({len(selected)} dipilih)", "fb_done")])
        
        await query.message.edit(
            f"📂 <b>FileBrowser Folder</b>\n📋 {len(files)} file | <b>{len(selected)} dipilih</b>",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    
    elif data == "fb_done":
        selected = USER_DATA[chat_id].get("fb_selected", [])
        if not selected:
            return await query.answer("⚠️ Pilih minimal 1 file!", show_alert=True)
        
        # Lanjut ke pilih template
        kb = build_template_keyboard()
        await query.message.edit(f"✅ <b>{len(selected)} file dipilih</b>\n\n🎬 Pilih Template:", reply_markup=kb)
        return

    # === TEMPLATE HANDLERS ===
    if data == "ignore":
        return  # Divider button, do nothing
    
    elif data == "close_menu":
        # Close/delete the menu message
        try:
            await query.message.delete()
        except: pass
        USER_DATA.pop(chat_id, None)
        return
    
    elif data == "back_to_template":
        # Kembali ke pilihan template
        kb = build_template_keyboard()
        await query.message.edit("🎬 <b>Pilih Template atau Setting Manual:</b>", reply_markup=kb)
        return
    
    elif data == "cancel_pending_srt":
        # Cancel ALL pending SRT jobs for this chat
        if chat_id in PENDING_SRT_JOBS:
            pending_list = PENDING_SRT_JOBS.pop(chat_id)
            # Cleanup downloaded files
            for pending in pending_list:
                if pending.get("file") and os.path.exists(pending["file"]):
                    try:
                        os.remove(pending["file"])
                    except: pass
            cancelled_count = len(pending_list)
        else:
            cancelled_count = 0
        try:
            await query.message.delete()
        except: pass
        await client.send_message(chat_id, f"❌ {cancelled_count} job dibatalkan.")
        return
    
    elif data == "manual_mode":
        # Show manual resolution selection
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", "res_360p"), InlineKeyboardButton("480p", "res_480p"), InlineKeyboardButton("720p", "res_720p")],
            [InlineKeyboardButton("1080p", "res_1080p"), InlineKeyboardButton("360+480", "res_360_480"), InlineKeyboardButton("360+720", "res_360_720")],
            [InlineKeyboardButton("480+720", "res_480_720"), InlineKeyboardButton("360+1080", "res_360_1080"), InlineKeyboardButton("480+1080", "res_480_1080")],
            [InlineKeyboardButton("720+1080", "res_720_1080"), InlineKeyboardButton("360+480+720", "res_360_480_720"), InlineKeyboardButton("480+720+1080", "res_480_720_1080")],
            [InlineKeyboardButton("🚀 ALL (Semua)", "res_all")],
            [InlineKeyboardButton("❌ Tutup", "close_menu")]
        ])
        await query.message.edit("🎯 <b>Pilih Resolusi:</b>", reply_markup=kb)
        return
    
    elif data.startswith("tpl_"):
        # Apply template
        tpl_key = data.replace("tpl_", "")
        if tpl_key not in TEMPLATES:
            return await query.answer("Template tidak ditemukan!", show_alert=True)
        
        tpl = TEMPLATES[tpl_key]
        USER_DATA[chat_id]["res"] = tpl["res"]
        USER_DATA[chat_id]["audio"] = tpl["audio"]
        USER_DATA[chat_id]["mode"] = tpl["mode"]
        USER_DATA[chat_id]["crf"] = tpl.get("crf", "26")
        USER_DATA[chat_id]["font"] = tpl["font"]
        USER_DATA[chat_id]["margin"] = tpl["margin"]
        
        # Support multi-res CRF
        if "res_crf" in tpl:
            USER_DATA[chat_id]["res_crf"] = tpl["res_crf"]
        
        if "custom_bitrate" in tpl:
            USER_DATA[chat_id]["custom_bitrate"] = tpl["custom_bitrate"]
        
        # Build display text
        res_crf = tpl.get("res_crf", {})
        if res_crf:
            crf_display = " | ".join([f"{r}: CRF{c}" for r, c in res_crf.items()])
        else:
            crf_display = f"{tpl['res']} | CRF {tpl.get('crf', '26')}"
        
        # Langsung ke subtitle selection (dengan tombol kembali)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Internal (Auto)", "sub_int"), InlineKeyboardButton("📝 Upload Manual", "sub_ext")],
            [InlineKeyboardButton("⬅️ Kembali", "back_to_template")]
        ])
        await query.message.edit(
            f"⚡ <b>Template: {tpl['name']}</b>\n\n"
            f"📺 {crf_display}\n"
            f"🔊 {tpl['audio'].upper()} | 🎯 {tpl['mode'].upper()}\n"
            f"🅰️ Font: {tpl['font']} | 📏 Margin: {tpl['margin']}\n\n"
            f"📝 <b>Pilih Subtitle:</b>",
            reply_markup=kb
        )
        return


    # === NEW TEMPLATE CREATION HANDLERS (Multi-Res with Per-Res CRF) ===
    
    # Toggle resolusi (multi-select)
    elif data.startswith("newtpl_toggle_"):
        res = data.replace("newtpl_toggle_", "")
        selected = USER_DATA[chat_id].get("selected_res", [])
        
        if res in selected:
            selected.remove(res)
        else:
            selected.append(res)
        
        USER_DATA[chat_id]["selected_res"] = selected
        
        # Rebuild buttons dengan checkmarks
        def res_label(r):
            return f"✅ {r}" if r in selected else r
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(res_label("360p"), "newtpl_toggle_360p"), InlineKeyboardButton(res_label("480p"), "newtpl_toggle_480p")],
            [InlineKeyboardButton(res_label("720p"), "newtpl_toggle_720p"), InlineKeyboardButton(res_label("1080p"), "newtpl_toggle_1080p")],
            [InlineKeyboardButton(f"✅ Selesai ({len(selected)} dipilih)", "newtpl_resdone")]
        ])
        selected_str = ", ".join(sorted(selected, key=lambda x: int(x.replace('p','')))) if selected else "Belum ada"
        await query.message.edit(f"➕ <b>Tambah Template Baru</b>\n\n🎯 Pilih Resolusi: <b>{selected_str}</b>", reply_markup=kb)
        return
    
    # Selesai pilih resolusi, mulai CRF per resolusi
    elif data == "newtpl_resdone":
        selected = USER_DATA[chat_id].get("selected_res", [])
        if not selected:
            return await query.answer("⚠️ Pilih minimal 1 resolusi!", show_alert=True)
        
        # Sort resolusi dari kecil ke besar
        selected = sorted(selected, key=lambda x: int(x.replace('p','')))
        USER_DATA[chat_id]["selected_res"] = selected
        USER_DATA[chat_id]["crf_pending"] = selected.copy()
        USER_DATA[chat_id]["res_crf"] = {}
        
        # Mulai minta CRF untuk resolusi pertama
        first_res = USER_DATA[chat_id]["crf_pending"][0]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("22", f"newtpl_setcrf_{first_res}_22"), InlineKeyboardButton("23", f"newtpl_setcrf_{first_res}_23"), InlineKeyboardButton("24", f"newtpl_setcrf_{first_res}_24")],
            [InlineKeyboardButton("25", f"newtpl_setcrf_{first_res}_25"), InlineKeyboardButton("26", f"newtpl_setcrf_{first_res}_26"), InlineKeyboardButton("28", f"newtpl_setcrf_{first_res}_28")]
        ])
        res_str = "+".join(selected)
        await query.message.edit(f"➕ <b>Template:</b> {res_str}\n\n🎚️ Pilih CRF untuk <b>{first_res}</b>:", reply_markup=kb)
        return
    
    # Set CRF untuk resolusi tertentu
    elif data.startswith("newtpl_setcrf_"):
        # Format: newtpl_setcrf_360p_24
        parts = data.replace("newtpl_setcrf_", "").rsplit("_", 1)
        res = parts[0]
        crf = parts[1]
        
        USER_DATA[chat_id]["res_crf"][res] = crf
        USER_DATA[chat_id]["crf_pending"].remove(res)
        
        # Cek apakah masih ada resolusi yang perlu CRF
        pending = USER_DATA[chat_id]["crf_pending"]
        if pending:
            next_res = pending[0]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("22", f"newtpl_setcrf_{next_res}_22"), InlineKeyboardButton("23", f"newtpl_setcrf_{next_res}_23"), InlineKeyboardButton("24", f"newtpl_setcrf_{next_res}_24")],
                [InlineKeyboardButton("25", f"newtpl_setcrf_{next_res}_25"), InlineKeyboardButton("26", f"newtpl_setcrf_{next_res}_26"), InlineKeyboardButton("28", f"newtpl_setcrf_{next_res}_28")]
            ])
            
            # Show progress
            res_crf = USER_DATA[chat_id]["res_crf"]
            progress = " | ".join([f"{r}:CRF{c}" for r, c in res_crf.items()])
            await query.message.edit(f"➕ <b>Template:</b> {progress}\n\n🎚️ Pilih CRF untuk <b>{next_res}</b>:", reply_markup=kb)
        else:
            # Semua CRF sudah diset, lanjut ke Audio
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("AAC LC", "newtpl_aud_aac"), InlineKeyboardButton("HE-AAC", "newtpl_aud_he")]
            ])
            res_crf = USER_DATA[chat_id]["res_crf"]
            progress = " | ".join([f"{r}:CRF{c}" for r, c in res_crf.items()])
            await query.message.edit(f"➕ <b>Template:</b> {progress}\n\n🔊 Pilih Audio:", reply_markup=kb)
        return
    
    # Old single-res handler (backward compat, tapi redirect ke flow baru)
    elif data.startswith("newtpl_res_"):
        res = data.replace("newtpl_res_", "")
        USER_DATA[chat_id]["selected_res"] = [res]
        USER_DATA[chat_id]["crf_pending"] = [res]
        USER_DATA[chat_id]["res_crf"] = {}
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("22", f"newtpl_setcrf_{res}_22"), InlineKeyboardButton("23", f"newtpl_setcrf_{res}_23"), InlineKeyboardButton("24", f"newtpl_setcrf_{res}_24")],
            [InlineKeyboardButton("25", f"newtpl_setcrf_{res}_25"), InlineKeyboardButton("26", f"newtpl_setcrf_{res}_26"), InlineKeyboardButton("28", f"newtpl_setcrf_{res}_28")]
        ])
        await query.message.edit(f"➕ <b>Template:</b> {res}\n\n🎚️ Pilih CRF:", reply_markup=kb)
        return
    
    elif data.startswith("newtpl_aud_"):
        aud = data.replace("newtpl_aud_", "")
        USER_DATA[chat_id]["new_tpl"]["audio"] = aud
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("CRF", "newtpl_mode_crf"), InlineKeyboardButton("2-Pass", "newtpl_mode_2pass")]
        ])
        res_crf = USER_DATA[chat_id].get("res_crf", {})
        progress = " | ".join([f"{r}:CRF{c}" for r, c in res_crf.items()])
        await query.message.edit(f"➕ <b>Template:</b> {progress} | {aud.upper()}\n\n🎯 Pilih Mode Encode:", reply_markup=kb)
        return
    
    elif data.startswith("newtpl_mode_"):
        mode = data.replace("newtpl_mode_", "")
        USER_DATA[chat_id]["new_tpl"]["mode"] = mode
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("14", "newtpl_font_14"), InlineKeyboardButton("15", "newtpl_font_15"), InlineKeyboardButton("16", "newtpl_font_16")],
            [InlineKeyboardButton("17", "newtpl_font_17"), InlineKeyboardButton("18", "newtpl_font_18"), InlineKeyboardButton("19", "newtpl_font_19"), InlineKeyboardButton("20", "newtpl_font_20")]
        ])
        res_crf = USER_DATA[chat_id].get("res_crf", {})
        progress = " | ".join([f"{r}:CRF{c}" for r, c in res_crf.items()])
        await query.message.edit(f"➕ <b>Template:</b> {progress}\n\n🅰️ Pilih Font Size:", reply_markup=kb)
        return
    
    # Old CRF handler (skip, handled by newtpl_setcrf_)
    elif data.startswith("newtpl_crf_"):
        return
    
    elif data.startswith("newtpl_font_"):
        font = int(data.replace("newtpl_font_", ""))
        USER_DATA[chat_id]["new_tpl"]["font"] = font
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("8", "newtpl_mar_8"), InlineKeyboardButton("10", "newtpl_mar_10"), InlineKeyboardButton("15", "newtpl_mar_15")],
            [InlineKeyboardButton("20", "newtpl_mar_20"), InlineKeyboardButton("25", "newtpl_mar_25"), InlineKeyboardButton("40", "newtpl_mar_40")]
        ])
        res_crf = USER_DATA[chat_id].get("res_crf", {})
        progress = " | ".join([f"{r}:CRF{c}" for r, c in res_crf.items()])
        await query.message.edit(f"➕ <b>Template:</b> {progress} | F{font}\n\n📏 Pilih Margin:", reply_markup=kb)
        return
    
    elif data.startswith("newtpl_mar_"):
        margin = int(data.replace("newtpl_mar_", ""))
        USER_DATA[chat_id]["new_tpl"]["margin"] = margin
        tpl = USER_DATA[chat_id]["new_tpl"]
        
        # Get multi-res data
        selected_res = USER_DATA[chat_id].get("selected_res", [])
        res_crf = USER_DATA[chat_id].get("res_crf", {})
        
        # Generate key dan name
        key = f"t{len(TEMPLATES) + 1}"
        while key in TEMPLATES:
            key = f"t{int(key[1:]) + 1}"
        
        # Build template data
        res_str = "+".join(selected_res)
        crf_str = "/".join([res_crf.get(r, "26") for r in selected_res])
        name = f"{res_str} CRF{crf_str} F{tpl['font']}"
        
        tpl["name"] = name
        tpl["res"] = res_str
        tpl["res_crf"] = res_crf  # Per-res CRF mapping
        tpl["crf"] = res_crf.get(selected_res[0], "26")  # Fallback CRF (first res)
        
        # Save
        TEMPLATES[key] = tpl
        save_templates(TEMPLATES)
        
        # Build display
        crf_display = " | ".join([f"{r}: CRF {c}" for r, c in res_crf.items()])
        
        await query.message.edit(
            f"✅ <b>Template berhasil ditambahkan!</b>\n\n"
            f"<b>Key:</b> {key}\n"
            f"<b>Name:</b> {name}\n"
            f"📺 {crf_display}\n"
            f"🔊 {tpl['audio'].upper()} | 🎯 {tpl['mode'].upper()}\n"
            f"🅰️ Font: {tpl['font']} | 📏 Margin: {margin}"
        )
        USER_DATA.pop(chat_id, None)
        return


    if data.startswith("res_"):
        USER_DATA[chat_id]["res"] = data.replace("res_", "")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("AAC LC", "aud_aac"), InlineKeyboardButton("HE-AAC", "aud_he")]])
        await query.message.edit("🔊 <b>Pilih Audio:</b>", reply_markup=kb)
    
    elif data.startswith("aud_"):
        USER_DATA[chat_id]["audio"] = data.replace("aud_", "")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Hybrid (360 2pass)", "mode_mixed")],
            [InlineKeyboardButton("🚀 CRF Only", "mode_crf"), InlineKeyboardButton("🎯 2-Pass All", "mode_2pass")]
        ])
        await query.message.edit("🔧 <b>Pilih Mode:</b>", reply_markup=kb)

    elif data.startswith("mode_"):
        mode = data.replace("mode_", "")
        USER_DATA[chat_id]["mode"] = mode
        
        # Jika CRF, tanya nilai CRF
        if mode == "crf":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("CRF 22", "crf_22"), InlineKeyboardButton("CRF 23", "crf_23"), InlineKeyboardButton("CRF 24", "crf_24")],
                [InlineKeyboardButton("CRF 25", "crf_25"), InlineKeyboardButton("CRF 26", "crf_26")]
            ])
            await query.message.edit("🎯 <b>Pilih CRF Value:</b>\n<i>Semakin kecil = kualitas lebih bagus, file lebih besar</i>", reply_markup=kb)
        else:
            # Langsung ke font size
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("14", "font_14"), InlineKeyboardButton("15", "font_15"), InlineKeyboardButton("16", "font_16")],
                [InlineKeyboardButton("17", "font_17"), InlineKeyboardButton("18", "font_18"), InlineKeyboardButton("19", "font_19"), InlineKeyboardButton("20", "font_20")]
            ])
            await query.message.edit("🅰️ <b>Font Size:</b>", reply_markup=kb)

    elif data.startswith("crf_"):
        USER_DATA[chat_id]["crf"] = data.replace("crf_", "")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("14", "font_14"), InlineKeyboardButton("15", "font_15"), InlineKeyboardButton("16", "font_16")],
            [InlineKeyboardButton("17", "font_17"), InlineKeyboardButton("18", "font_18"), InlineKeyboardButton("19", "font_19"), InlineKeyboardButton("20", "font_20")]
        ])
        await query.message.edit("🅰️ <b>Font Size:</b>", reply_markup=kb)

    elif data.startswith("font_"):
        USER_DATA[chat_id]["font"] = int(data.replace("font_", ""))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("8", "mar_8"), InlineKeyboardButton("10", "mar_10"), InlineKeyboardButton("15", "mar_15")],
            [InlineKeyboardButton("20", "mar_20"), InlineKeyboardButton("25", "mar_25"), InlineKeyboardButton("40", "mar_40")]
        ])
        await query.message.edit("📏 <b>Margin Subtitle:</b>", reply_markup=kb)

    elif data.startswith("mar_"):
        USER_DATA[chat_id]["margin"] = int(data.replace("mar_", ""))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📂 Internal (Auto)", "sub_int"), InlineKeyboardButton("📝 Upload Manual", "sub_ext")]])
        await query.message.edit("📝 <b>Subtitle:</b>", reply_markup=kb)

    elif data == "sub_int":
        # Hapus pesan template sebelum mulai encode
        try:
            await query.message.delete()
        except: pass
        await finalize_job(client, query.message, chat_id)
    
    elif data == "sub_ext":
        await query.message.edit("📂 <b>Kirim file .SRT sekarang.</b>")
        USER_DATA[chat_id]["waiting_srt"] = True

async def finalize_job(client, message, chat_id):
    cfg = USER_DATA[chat_id]
    res_key = cfg['res']
    res_crf = cfg.get('res_crf', {})
    
    # LOGIKA KOMBINASI RESOLUSI
    queue = []
    
    # PRIORITAS 1: Gunakan res_crf jika ada (multi-res template)
    if res_crf:
        # Urutkan resolusi dari kecil ke besar
        res_order = ["360p", "480p", "720p", "1080p"]
        queue = [r for r in res_order if r in res_crf]
    
    # PRIORITAS 2: Pattern matching dari res_key
    if not queue:
        # Single
        if res_key == "360p": queue = ["360p"]
        elif res_key == "480p": queue = ["480p"]
        elif res_key == "720p": queue = ["720p"]
        elif res_key == "1080p": queue = ["1080p"]
        
        # Dual
        elif res_key == "360_480": queue = ["360p", "480p"]
        elif res_key == "360_720": queue = ["360p", "720p"]
        elif res_key == "480_720": queue = ["480p", "720p"]
        elif res_key == "360_1080": queue = ["360p", "1080p"]
        elif res_key == "480_1080": queue = ["480p", "1080p"]
        elif res_key == "720_1080": queue = ["720p", "1080p"]
        
        # Triple
        elif res_key == "360_480_720": queue = ["360p", "480p", "720p"]
        elif res_key == "480_720_1080": queue = ["480p", "720p", "1080p"]
        
        # All
        elif res_key == "all": queue = ["360p", "480p", "720p", "1080p"]
    
    # Fallback
    if not queue: queue = ["360p"]

    # === CEK FILEBROWSER BATCH MODE ===
    if cfg.get('fb_files') and cfg.get('fb_selected'):
        fb_info = cfg['fb_info']
        fb_files = cfg['fb_files']
        selected_indices = cfg['fb_selected']
        
        for idx in sorted(selected_indices):
            file_info = fb_files[idx]
            filename = file_info['name']
            download_url = build_filebrowser_download_url(fb_info, filename)
            
            status_msg = await client.send_message(chat_id, f"⏳ <b>Queue:</b> {filename[:50]}...", disable_notification=True)
            
            job = {
                "chat_id": chat_id, "msg_id": status_msg.id,
                "url": download_url, "filename": os.path.join(CACHE_FOLDER, f"vid_{chat_id}_{idx}_input.mkv"), 
                "real_name": filename,
                "type": "encode",
                "queue": queue, "mode": cfg['mode'], "font": cfg['font'], 
                "margin": cfg['margin'], "audio": cfg['audio'], "srt": cfg['srt'],
                "crf": cfg.get('crf', '26'),
                "res_crf": cfg.get('res_crf', {}),
                "is_cancelled": False
            }
            JOB_QUEUE.append(job)
        
        await check_queue()
        return

    # === BATCH CACHED FILES MODE (dari /encode 5,6,7,8) ===
    if cfg.get('batch_cache_files'):
        batch_files = cfg['batch_cache_files']
        status_msg = await client.send_message(
            chat_id, 
            f"⏳ <b>Menambahkan {len(batch_files)} file ke antrian...</b>",
            disable_notification=True
        )
        
        for file_id, cached_file in batch_files:
            job = {
                "chat_id": chat_id, "msg_id": status_msg.id,
                "downloaded_file": cached_file['path'],
                "url": None, "filename": cached_file['path'], 
                "real_name": cached_file['name'],
                "type": "encode",
                "queue": queue, "mode": cfg['mode'], "font": cfg['font'], 
                "margin": cfg['margin'], "audio": cfg['audio'], "srt": cfg['srt'],
                "crf": cfg.get('crf', '26'),
                "res_crf": cfg.get('res_crf', {}),
                "is_cancelled": False
            }
            JOB_QUEUE.append(job)
        
        await client.edit_message_text(
            chat_id, status_msg.id,
            f"✅ <b>{len(batch_files)} job ditambahkan ke antrian!</b>\n\n"
            f"📋 Posisi: #{len(JOB_QUEUE) - len(batch_files) + 1} - #{len(JOB_QUEUE)}"
        )
        
        await check_queue()
        return

    # === CACHED FILE MODE (dari /encode [id]) ===
    if cfg.get('cached_file_path'):
        status_msg = await client.send_message(chat_id, "⏳ <b>Mempersiapkan dari cache...</b>", disable_notification=True)
        
        job = {
            "chat_id": chat_id, "msg_id": status_msg.id,
            "downloaded_file": cfg['cached_file_path'],  # File sudah ada
            "url": None, "filename": cfg['cached_file_path'], 
            "real_name": cfg['cached_file_name'],
            "type": "encode",
            "queue": queue, "mode": cfg['mode'], "font": cfg['font'], 
            "margin": cfg['margin'], "audio": cfg['audio'], "srt": cfg['srt'],
            "crf": cfg.get('crf', '26'),
            "res_crf": cfg.get('res_crf', {}),
            "is_cancelled": False
        }
        
        JOB_QUEUE.append(job)
        await check_queue()
        return

    # === SINGLE FILE MODE (Normal) ===
    status_msg = await client.send_message(chat_id, "⏳ <b>Mempersiapkan...</b>", disable_notification=True)
    
    real_name = await asyncio.to_thread(get_real_filename, cfg['url'])
    filename = os.path.join(CACHE_FOLDER, f"vid_{chat_id}_input.mkv")
    
    job = {
        "chat_id": chat_id, "msg_id": status_msg.id,
        "url": cfg['url'], "filename": filename, "real_name": real_name,
        "type": "encode",
        "queue": queue, "mode": cfg['mode'], "font": cfg['font'], 
        "margin": cfg['margin'], "audio": cfg['audio'], "srt": cfg['srt'],
        "crf": cfg.get('crf', '26'),
        "res_crf": cfg.get('res_crf', {}),
        "is_cancelled": False
    }
    
    JOB_QUEUE.append(job)
    
    # Feedback posisi antrian
    queue_pos = len(JOB_QUEUE)
    if queue_pos > 1 or IS_WORKING:
        await client.send_message(
            chat_id, 
            f"📋 <b>Job ditambahkan ke antrian</b>\nPosisi: #{queue_pos}" + 
            (" (menunggu job sebelumnya)" if IS_WORKING else ""),
            disable_notification=True
        )
    
    await check_queue()

async def check_queue():
    global IS_WORKING, CURRENT_JOB
    if IS_WORKING or not JOB_QUEUE: return
    
    IS_WORKING = True
    CURRENT_JOB = JOB_QUEUE.pop(0)
    
    # Track start time for batch summary
    if not hasattr(check_queue, '_batch_start'):
        check_queue._batch_start = time.time()
        check_queue._batch_count = 0
    
    await process_job(app, CURRENT_JOB)
    check_queue._batch_count += 1
    
    IS_WORKING = False
    CURRENT_JOB = None
    
    # Check if this was the last job
    if not JOB_QUEUE:
        # All jobs completed! Send summary notification
        total_time = time.time() - check_queue._batch_start
        hours, remainder = divmod(int(total_time), 3600)
        minutes, seconds = divmod(remainder, 60)
        time_str = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        
        chat_id = CURRENT_JOB['chat_id'] if CURRENT_JOB else None
        if not chat_id and check_queue._batch_count > 0:
            chat_id = OWNER_ID
        
        if chat_id:
            try:
                await app.send_message(
                    chat_id,
                    f"🎉 <b>SEMUA JOB SELESAI!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ Total job: <b>{check_queue._batch_count}</b>\n"
                    f"⏱️ Total waktu: <b>{time_str}</b>\n\n"
                    f"📋 Antrian kosong, siap menerima job baru."
                )
            except:
                pass
        
        # Reset batch tracking
        del check_queue._batch_start
        del check_queue._batch_count
    else:
        await check_queue()

if __name__ == "__main__":
    print("🤖 Bot Started (PyroFork Version)")
    app.run()
