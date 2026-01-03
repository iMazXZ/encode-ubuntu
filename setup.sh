#!/bin/bash
# ================================================
# EncodeSilent VPS Setup Script
# Run: chmod +x setup.sh && ./setup.sh
# ================================================

set -e  # Exit on error

echo "=========================================="
echo "   EncodeSilent VPS Setup Script"
echo "=========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo -e "${RED}Please don't run as root. Use a regular user with sudo.${NC}"
    exit 1
fi

echo -e "${YELLOW}[1/6] Updating system...${NC}"
sudo apt update && sudo apt upgrade -y

echo -e "${YELLOW}[2/6] Installing system dependencies...${NC}"
sudo apt install -y \
    python3 python3-pip git curl \
    build-essential yasm pkg-config \
    libx264-dev libfdk-aac-dev \
    libfreetype-dev libfontconfig1-dev libass-dev

echo -e "${YELLOW}[3/6] Installing Python packages...${NC}"
pip3 install --upgrade pip
pip3 install pyrofork tgcrypto requests psutil python-dotenv
pip3 install --pre yt-dlp

# Add local bin to PATH if not already
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    export PATH="$HOME/.local/bin:$PATH"
fi

echo -e "${YELLOW}[4/6] Installing rclone...${NC}"
if ! command -v rclone &> /dev/null; then
    curl https://rclone.org/install.sh | sudo bash
else
    echo "rclone already installed"
fi

echo -e "${YELLOW}[5/6] Compiling FFmpeg with all filters...${NC}"
if ! ffmpeg -filters 2>/dev/null | grep -q "drawtext"; then
    cd ~
    if [ ! -d "ffmpeg-src" ]; then
        git clone --depth 1 https://git.ffmpeg.org/ffmpeg.git ffmpeg-src
    fi
    cd ffmpeg-src
    
    ./configure \
        --enable-gpl \
        --enable-nonfree \
        --enable-libx264 \
        --enable-libfdk-aac \
        --enable-libfreetype \
        --enable-libfontconfig \
        --enable-libass
    
    make -j$(nproc)
    sudo make install
    
    echo -e "${GREEN}FFmpeg compiled successfully!${NC}"
else
    echo "FFmpeg already has required filters"
fi

echo -e "${YELLOW}[6/6] Setting up encode-ubuntu...${NC}"
cd ~
if [ ! -d "encode-ubuntu" ]; then
    git clone https://github.com/iMazXZ/encode-ubuntu.git
fi
cd encode-ubuntu

# Create .env if not exists
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}Please edit .env with your credentials:${NC}"
    echo "  nano .env"
fi

# Create required folders
mkdir -p data raw_cache output manual tools

echo ""
echo -e "${GREEN}=========================================="
echo "   Setup Complete!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env: nano ~/encode-ubuntu/.env"
echo "  2. Setup rclone: rclone config"
echo "  3. Run bot: cd ~/encode-ubuntu && python3 bot.py"
echo ""

# Verify installations
echo "Verification:"
ffmpeg -version 2>/dev/null | head -1
echo "yt-dlp: $(yt-dlp --version 2>/dev/null || echo 'not found')"
echo "rclone: $(rclone --version 2>/dev/null | head -1 || echo 'not found')"
echo ""
echo "FFmpeg filters:"
ffmpeg -filters 2>/dev/null | grep -E "drawtext|subtitles|libass" || echo "Filters not found"
