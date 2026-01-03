# EncodeSilent Ubuntu Bot

Telegram bot for video encoding with FFmpeg. Supports multiple upload destinations.

## Features

- Download from Google Drive, HTTP, FileBrowser
- FFmpeg encoding with subtitle burning
- Multi-resolution encoding (360p, 480p, 720p, 1080p)
- Upload to: GDrive, Seedbox, Gofile, Buzzheavier, Mirrored, FilePress, TurboVid, Abyss, VidHide
- Template system for encoding presets
- Job queue with async processing
- File caching for re-encoding

## Requirements

- Ubuntu 20.04+ or similar Linux
- Python 3.8+
- FFmpeg with libfdk_aac
- rclone (for Google Drive)
- yt-dlp

## Installation

### 1. Clone and setup

```bash
git clone https://github.com/YOUR_USERNAME/encode-ubuntu.git
cd encode-ubuntu
```

### 2. Install system dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg rclone

# Install yt-dlp
pip3 install yt-dlp
```

### 3. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
nano .env  # Fill in your credentials
```

### 5. Configure rclone (for Google Drive)

```bash
rclone config
# Create a remote named "gdrive" or match RCLONE_REMOTE in .env
```

### 6. Run the bot

```bash
python3 bot.py
```

## Running in Background

### Using screen

```bash
screen -S encodebot
python3 bot.py
# Press Ctrl+A then D to detach
# screen -r encodebot to reattach
```

### Using systemd

Create `/etc/systemd/system/encodebot.service`:

```ini
[Unit]
Description=EncodeSilent Telegram Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/encode-ubuntu
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable encodebot
sudo systemctl start encodebot
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start bot |
| `/status` | Check bot status |
| `/queue` | View job queue |
| `/template` | Manage encoding templates |
| `/files` | List cached files |
| `/encode [id]` | Encode from cache |
| `/clean` | Clear cache |
| `/links` | Get formatted download links |
| `/leech [url]` | Download and upload to Telegram |
| `/convert [url]` | GDrive to Seedbox transfer |
| `/up [url]` | Upload to multi-host |
| `/fp [gdrive_url]` | Mirror to FilePress |

## License

Private use only.
