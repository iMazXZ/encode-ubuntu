"""
Configuration loader for EncodeSilent Ubuntu Bot
All sensitive credentials are loaded from .env file
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==========================
# TELEGRAM CONFIG
# ==========================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# ==========================
# RCLONE CONFIG (Google Drive)
# ==========================
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "gdrive")
RCLONE_FOLDER = os.getenv("RCLONE_FOLDER", "Encode")

# ==========================
# SEEDBOX FILEBROWSER CONFIG
# ==========================
SEEDBOX_ENABLED = os.getenv("SEEDBOX_ENABLED", "false").lower() == "true"
SEEDBOX_USER = os.getenv("SEEDBOX_USER", "")
SEEDBOX_PASS = os.getenv("SEEDBOX_PASS", "")
SEEDBOX_FB_URL = os.getenv("SEEDBOX_FB_URL", "")
SEEDBOX_FB_SHARE_HASH = os.getenv("SEEDBOX_FB_SHARE_HASH", "")

# ==========================
# MIRRORED.TO CONFIG
# ==========================
MIRRORED_ENABLED = os.getenv("MIRRORED_ENABLED", "false").lower() == "true"
MIRRORED_API_KEY = os.getenv("MIRRORED_API_KEY", "")
MIRRORED_MIRRORS = os.getenv("MIRRORED_MIRRORS", "megaupnet,buzzheavier,krakenfiles,gofileio,onefichier,mixdropag,hexupload,sendnow,streamtape,voesx,doodstream,filemoonto,streamwish")

# ==========================
# BUZZHEAVIER CONFIG
# ==========================
BUZZHEAVIER_ENABLED = os.getenv("BUZZHEAVIER_ENABLED", "false").lower() == "true"
BUZZHEAVIER_ACCOUNT_ID = os.getenv("BUZZHEAVIER_ACCOUNT_ID", "")

# ==========================
# GOFILE CONFIG
# ==========================
GOFILE_ENABLED = os.getenv("GOFILE_ENABLED", "false").lower() == "true"
GOFILE_TOKEN = os.getenv("GOFILE_TOKEN", "")

# ==========================
# FILEPRESS CONFIG (Mirror from GDrive)
# ==========================
FILEPRESS_ENABLED = os.getenv("FILEPRESS_ENABLED", "false").lower() == "true"
FILEPRESS_DOMAIN = os.getenv("FILEPRESS_DOMAIN", "https://new3.filepress.cloud")
FILEPRESS_API_KEY = os.getenv("FILEPRESS_API_KEY", "")

# ==========================
# TURBOVID CONFIG (Embed Player)
# ==========================
TURBOVID_ENABLED = os.getenv("TURBOVID_ENABLED", "false").lower() == "true"
TURBOVID_API_KEY = os.getenv("TURBOVID_API_KEY", "")

# ==========================
# ABYSS.TO CONFIG (Embed Player)
# ==========================
ABYSS_ENABLED = os.getenv("ABYSS_ENABLED", "false").lower() == "true"
ABYSS_API_KEY = os.getenv("ABYSS_API_KEY", "")

# ==========================
# VIDHIDE CONFIG (Download/Embed)
# ==========================
VIDHIDE_ENABLED = os.getenv("VIDHIDE_ENABLED", "false").lower() == "true"
VIDHIDE_API_KEY = os.getenv("VIDHIDE_API_KEY", "")
VIDHIDE_DOMAIN = os.getenv("VIDHIDE_DOMAIN", "minochinos.com")

# ==========================
# ENCODING DEFAULTS
# ==========================
DEFAULT_FONT_SIZE = int(os.getenv("DEFAULT_FONT_SIZE", "15"))
DEFAULT_MARGIN_V = int(os.getenv("DEFAULT_MARGIN_V", "25"))
SUB_FONT_NAME = os.getenv("SUB_FONT_NAME", "Arial")
SUB_IS_BOLD = int(os.getenv("SUB_IS_BOLD", "1"))
CRF_VALUE = os.getenv("CRF_VALUE", "26")

# ==========================
# WATERMARK CONFIG
# ==========================
WATERMARK_ENABLED = os.getenv("WATERMARK_ENABLED", "true").lower() == "true"
WATERMARK_TEXT = os.getenv("WATERMARK_TEXT", "Nonton dan Download di NUNASTREAM (ketik di google)")
WATERMARK_FONTSIZE = int(os.getenv("WATERMARK_FONTSIZE", "30"))
WATERMARK_DURATION = int(os.getenv("WATERMARK_DURATION", "30"))
# Linux font path (Ubuntu default)
WATERMARK_FONT = os.getenv("WATERMARK_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

# ==========================
# BITRATE MAPS
# ==========================
HEAUDIO_MAP = {"360p": "40k", "480p": "48k", "720p": "112k", "1080p": "128k"}
AACLCAUDIO_MAP = {"360p": "64k", "480p": "96k", "720p": "128k", "1080p": "160k"}
VIDEO_2PASS_MAP = {"360p": "300k", "480p": "540k", "720p": "850k", "1080p": "2100k"}

# ==========================
# FOLDERS & PATHS
# ==========================
DATA_FOLDER = "data"
CACHE_FOLDER = "raw_cache"
MANUAL_FOLDER = "manual"
TOOLS_FOLDER = "tools"
OUTPUT_FOLDER = "output"

# ==========================
# DOWNLOAD TIMEOUT (seconds)
# ==========================
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "1800"))  # 30 minutes
