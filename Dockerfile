# Multi-stage build for Creative Master Preview API
# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY ad-generator/package*.json ./
RUN npm ci
COPY ad-generator/ ./
RUN npm run build

# Stage 2: Python backend with all dependencies
FROM python:3.11-slim

# Install system dependencies: ffmpeg, fonts (including Cyrillic support), playwright deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-core \
    fonts-dejavu-core \
    curl \
    # Playwright browser dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    edge-tts \
    trafilatura \
    pillow \
    telethon \
    pydantic \
    playwright

# Install Playwright browser (Chromium only, for smaller image)
RUN playwright install chromium

# Copy source code
COPY src/ ./src/
COPY scripts/preview_api.py ./scripts/

# Copy assets (may be empty, that's ok)
COPY assets/ ./assets/

# Copy built frontend (includes iPhone frame in assets/)
COPY --from=frontend-builder /app/frontend/dist ./ad-generator/dist
COPY --from=frontend-builder /app/frontend/src/assets ./ad-generator/src/assets

# Create directories for runtime data
RUN mkdir -p /tmp/creative_master/preview_vo /tmp/creative_master/rendered

# Expose port
EXPOSE 8899

# Environment variables (to be overridden at runtime)
ENV PEXELS_API_KEY=""
ENV DEEPSEEK_API_KEY=""
ENV OPENAI_API_KEY=""
ENV LOCAL_VIDEO_DIR=""
ENV TELEGRAM_API_ID="31816963"
ENV TELEGRAM_API_HASH=""

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8899/api/workflows || exit 1

# Run the API server
CMD ["python3", "scripts/preview_api.py"]
