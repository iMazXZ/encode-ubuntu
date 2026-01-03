# ================================================
# EncodeSilent Docker Setup
# Build: docker build -t encodebot .
# Run: docker-compose up -d
# ================================================

FROM ubuntu:22.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip git curl \
    build-essential yasm pkg-config \
    libx264-dev libfdk-aac-dev \
    libfreetype-dev libfontconfig1-dev libass-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install rclone
RUN curl https://rclone.org/install.sh | bash

# Compile FFmpeg with all required filters
WORKDIR /tmp
RUN git clone --depth 1 https://git.ffmpeg.org/ffmpeg.git ffmpeg-src \
    && cd ffmpeg-src \
    && ./configure \
        --enable-gpl \
        --enable-nonfree \
        --enable-libx264 \
        --enable-libfdk-aac \
        --enable-libfreetype \
        --enable-libfontconfig \
        --enable-libass \
    && make -j$(nproc) \
    && make install \
    && cd / \
    && rm -rf /tmp/ffmpeg-src

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    pyrofork tgcrypto requests psutil python-dotenv

# Install yt-dlp nightly
RUN pip3 install --no-cache-dir --pre yt-dlp

# Create app directory
WORKDIR /app

# Copy application files
COPY bot.py config.py requirements.txt ./
COPY tools/ ./tools/

# Create data directories
RUN mkdir -p data raw_cache output manual

# Volume for persistent data and config
VOLUME ["/app/data", "/app/.env", "/root/.config/rclone"]

# Run bot
CMD ["python3", "bot.py"]
