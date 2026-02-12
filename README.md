# Creative Master v2

Video ad generator from URLs and Telegram posts.

## Directory Structure

```
creative_master_v2/
├── ad-generator/              # React frontend (Vite)
│   └── src/App.jsx           # Single-file UI
│
├── scripts/
│   └── preview_api.py        # FastAPI backend (THE MAIN APP)
│
├── src/
│   ├── video/                # Video rendering pipeline
│   │   ├── compositor.py     # FFmpeg video composition
│   │   ├── subtitle_generator.py
│   │   ├── music_library.py  # Background music tracks
│   │   ├── voice_catalog.py  # TTS voice selection
│   │   └── workflows/        # Preset configurations
│   │
│   ├── providers/            # External service integrations
│   │   ├── tts/              # Text-to-speech (Edge, OpenAI)
│   │   ├── stock/            # Stock video (Pexels, local)
│   │   └── llm/              # LLM providers
│   │
│   ├── telegram/             # Telegram-specific features
│   │   ├── telegram_screen_recorder.py  # Records channel preview
│   │   ├── telegram_cta_compositor.py   # iPhone frame + finger overlay
│   │   └── telegram_stats.py            # Channel post fetching
│   │
│   ├── prompts/              # LLM prompt templates
│   │   └── telegram_video.py # Open Loop framework for video scripts
│   │
│   └── assets/               # Static files
│       └── telegram_cta/     # iPhone frame, finger images
│
└── tests/
```

## How It Works

1. **User enters URL or Telegram channel** → frontend
2. **Selects post, language, duration** → frontend
3. **Clicks generate** → backend streams:
   - Music (instant, local file)
   - Video shots (instant, local files)
   - Subtitles (as LLM generates)
   - Audio (as TTS completes, ~1-2s per shot)
4. **User sees/hears progressively** - no waiting for all shots
5. **Save** → renders final MP4 with burned subtitles

## Running Locally

```bash
# Backend
python3 scripts/preview_api.py

# Frontend (separate terminal)
cd ad-generator && npm install && npm run dev
```

## Deployment

```bash
docker compose up -d
```

Access at http://localhost:8899
