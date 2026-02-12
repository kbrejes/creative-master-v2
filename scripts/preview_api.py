"""FastAPI backend for instant video preview.

Generates scene JSONs from a URL:
- Fetches page content
- Generates multiple briefs via OpenRouter using the same prompt structure as the bot
- Gets Pexels streaming video URLs (no download)
- Generates VO audio via Edge TTS
- Returns everything as scene JSONs for the frontend player
- Exposes workflow, music, and format metadata for the UI
"""

import asyncio
import json
import logging
import os
import platform
import random
import re
import sys
import traceback
import uuid
from pathlib import Path

# Platform-specific video encoder
VIDEO_ENCODER = "h264_videotoolbox" if platform.system() == "Darwin" else "libx264"
VIDEO_ENCODER_OPTS = ["-b:v", "5M"] if platform.system() == "Darwin" else ["-preset", "fast", "-crf", "23"]

import edge_tts
import httpx
import trafilatura
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Add project root to path so we can import src.agents
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.video.music_library import _DEFAULT_TRACKS, MusicMood  # noqa: E402
from src.video.platform_specs import (  # noqa: E402
    BOT_DURATIONS,
    get_format_duration,
)
from src.video.schemas import LANGUAGE_LOCALE_MAP  # noqa: E402
from src.video.voice_catalog import list_voices  # noqa: E402
from src.video.workflows import list_workflows  # noqa: E402
from src.providers.stock.local_videos import LocalVideoLibrary  # noqa: E402
from src.providers.tts import OpenAITTSProvider, TTSRequest  # noqa: E402
from src.telegram.telegram_stats import SortBy, TelegramAnalyzer  # noqa: E402

app = FastAPI()

# Local video library (optional - for instant video loading)
LOCAL_VIDEO_DIR = os.environ.get("LOCAL_VIDEO_DIR", "")
_local_video_library: LocalVideoLibrary | None = None

def get_local_video_library() -> LocalVideoLibrary | None:
    """Get the local video library if configured."""
    global _local_video_library
    if LOCAL_VIDEO_DIR and _local_video_library is None:
        try:
            _local_video_library = LocalVideoLibrary(LOCAL_VIDEO_DIR, "/local-videos")
            count = _local_video_library.load()
            logger.info(f"Loaded {count} local videos from {LOCAL_VIDEO_DIR}")
        except Exception as e:
            logger.warning(f"Failed to load local videos: {e}")
            return None
    return _local_video_library
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

VO_DIR = Path("/tmp/creative_master/preview_vo")
VO_DIR.mkdir(parents=True, exist_ok=True)

# Serve VO audio files
app.mount("/vo", StaticFiles(directory=str(VO_DIR)), name="vo")

# Serve local videos if directory is configured
if LOCAL_VIDEO_DIR and Path(LOCAL_VIDEO_DIR).exists():
    app.mount("/local-videos", StaticFiles(directory=LOCAL_VIDEO_DIR), name="local_videos")
    logger.info(f"Mounted local videos from {LOCAL_VIDEO_DIR} at /local-videos")

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "31816963"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "84f692a3d27f0a4170fedc5449836ff1")

if not DEEPSEEK_API_KEY:
    logger.warning("DEEPSEEK_API_KEY not set — brief generation will fail")
if not PEXELS_API_KEY:
    logger.warning("PEXELS_API_KEY not set — video search will use local library only")
if not TELEGRAM_API_HASH:
    logger.warning("TELEGRAM_API_HASH not set — Telegram features will fail")

# OpenAI TTS provider (singleton, lazy init)
_openai_tts_provider: OpenAITTSProvider | None = None


def get_openai_tts_provider() -> OpenAITTSProvider | None:
    """Get the OpenAI TTS provider if API key is configured."""
    global _openai_tts_provider
    if OPENAI_API_KEY and _openai_tts_provider is None:
        try:
            _openai_tts_provider = OpenAITTSProvider(
                api_key=OPENAI_API_KEY,
                output_dir=str(VO_DIR),
                default_voice="onyx",  # Deep male voice, good for ads
                model="tts-1",  # Standard quality, $0.015/1K chars
            )
            logger.info("OpenAI TTS provider initialized")
        except Exception as e:
            logger.warning(f"Failed to init OpenAI TTS: {e}")
            return None
    return _openai_tts_provider


# Log provider status
if OPENAI_API_KEY:
    logger.info("OpenAI TTS enabled (primary voice provider)")
else:
    logger.info("OpenAI TTS disabled — using Edge TTS (free)")

if LOCAL_VIDEO_DIR:
    logger.info(f"Local videos enabled: {LOCAL_VIDEO_DIR}")
else:
    logger.info("Local videos disabled — using Pexels API")

_LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "ru": "Русский",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "pt": "Português",
    "it": "Italiano",
}

VOICE_MAP = {
    "en": "en-US-ChristopherNeural",
    "ru": "ru-RU-DmitryNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural",
    "it": "it-IT-DiegoNeural",
}


# =============================================================================
# Helpers
# =============================================================================


def _subtitle_style_from_workflow(wf) -> dict:
    """Extract CSS-friendly subtitle style info from a WorkflowConfig."""
    sc = wf.subtitle_config
    return {
        "bg_enabled": sc.bg_enabled,
        "bg_color": list(sc.bg_color),
        "text_color": list(sc.text_color),
        "outline_width": sc.outline_width,
        "shadow_blur_radius": sc.shadow_blur_radius,
        "shadow_color": list(sc.shadow_color),
        "font_name": sc.font_name,
    }


async def fetch_page_content(url: str) -> str:
    """Fetch page text using trafilatura for proper content extraction."""
    downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
    if downloaded:
        text = trafilatura.extract(downloaded)
        if text and len(text.strip()) > 50:
            return text[:10000]
    # Fallback: raw HTML tag stripping
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    text = re.sub(r"<[^>]+>", " ", resp.text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:10000]


def build_brief_prompt(
    content: str,
    duration_seconds: int,
    language: str,
    num_videos: int = 3,
) -> str:
    """Build the LLM prompt for brief generation, matching the bot's structure."""
    fmt = get_format_duration(duration_seconds)
    shot_duration = round(duration_seconds / fmt.min_shots, 1)

    lang_label = _LANGUAGE_LABELS.get(language, "English")
    lang_instruction = ""
    if language != "en":
        lang_instruction = (
            f"\n\nIMPORTANT: All voiceover text MUST be written in {lang_label}. "
            f"Translate the content and write natural {lang_label} voiceover scripts. "
            "Stock video search terms should remain in English for best results."
        )

    return f"""You are a video content strategist. Given the following page content, create {num_videos} short-form video briefs.

Each video should:
- Be {duration_seconds} seconds long with {fmt.min_shots} to {fmt.max_shots} shots (~{shot_duration}s each)
- Target TikTok (9:16, 1080x1920)
- Have a different angle/hook
- Include voiceover text (~{fmt.vo_words} words total) and stock video descriptions
- Follow this structure: {fmt.structure}

Output a JSON array of briefs. Each brief must follow this exact schema:
{{
    "brief_id": "brief-N",
    "shot_list": [
        {{
            "shot_number": 1,
            "duration_seconds": {shot_duration},
            "visual": {{
                "type": "stock",
                "description": "description for stock search",
                "search_terms": ["keyword1", "keyword2", "keyword3"]
            }},
            "audio": {{
                "voiceover": {{
                    "text": "Voiceover text for this shot",
                    "tone": "conversational"
                }}
            }},
            "text_overlay": {{
                "text": "Short overlay text",
                "position": "bottom_center",
                "start_time": 0.5,
                "duration": {shot_duration - 1.0}
            }}
        }}
    ],
    "specifications": {{
        "total_duration": {duration_seconds},
        "aspect_ratio": "9:16",
        "resolution": "1080x1920",
        "fps": 30,
        "platforms": ["tiktok"]
    }}
}}

Valid voiceover tones: conversational, professional, energetic, warm, authoritative, young.
Each video MUST have exactly {fmt.min_shots} shots.{lang_instruction}

PAGE CONTENT:
{content}

Respond with ONLY a JSON array, no markdown fences or explanation."""


async def generate_briefs(
    content: str,
    language: str = "en",
    duration: int = 30,
    num_briefs: int = 3,
) -> list[dict]:
    """Generate multiple video briefs via DeepSeek API."""
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
    prompt = build_brief_prompt(content, duration, language, num_briefs)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    raw = data["choices"][0]["message"]["content"].strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    parsed = _parse_json_lenient(raw)
    # Ensure it's a list
    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed


async def generate_briefs_stream(
    content: str,
    language: str = "en",
    duration: int = 30,
    num_briefs: int = 1,
):
    """Stream brief generation via DeepSeek SSE. Yields raw LLM tokens."""
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY environment variable is not set")
    prompt = build_brief_prompt(content, duration, language, num_briefs)

    async with httpx.AsyncClient(timeout=120.0) as client, client.stream(
        "POST",
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": True,
        },
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                delta = chunk["choices"][0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    yield token
            except (json.JSONDecodeError, KeyError, IndexError):
                continue


def _parse_json_lenient(raw: str):
    """Parse JSON from LLM output, tolerating common issues.

    Tries strict parse first, then falls back to extracting
    the first valid JSON array or object from the text.
    """
    # Try direct parse
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        pass
    # Try to find the outermost JSON array
    start = raw.find("[")
    if start >= 0:
        # Walk forward to find matching bracket
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "[":
                depth += 1
            elif raw[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1], strict=False)
                    except json.JSONDecodeError:
                        break
    # Try to find the outermost JSON object
    start = raw.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1], strict=False)
                    except json.JSONDecodeError:
                        break
    # Last resort: raise
    return json.loads(raw, strict=False)


async def search_pexels_videos_multi(query: str, duration_hint: int = 5, max_results: int = 5) -> list[dict]:
    """Search Pexels for portrait videos, return up to max_results with thumbnails."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.pexels.com/videos/search",
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": max_results,
            },
            headers={"Authorization": PEXELS_API_KEY},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    results = []
    for video in data.get("videos", []):
        # Pick the best HD portrait file
        best_file = None
        for vf in video.get("video_files", []):
            if vf.get("height", 0) >= 720 and vf.get("width", 0) < vf.get("height", 0):
                best_file = vf
                break
        if not best_file and video.get("video_files"):
            best_file = video["video_files"][0]
        if best_file:
            results.append({
                "pexels_id": video.get("id"),
                "thumbnail": video.get("image", ""),
                "stream_url": best_file["link"],
                "width": best_file.get("width", 1080),
                "height": best_file.get("height", 1920),
                "duration": video.get("duration", duration_hint),
            })
    return results


async def search_pexels_video(query: str, duration_hint: int = 5) -> dict | None:
    """Search Pexels for a portrait video, return streaming URL + metadata."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.pexels.com/videos/search",
            params={
                "query": query,
                "orientation": "portrait",
                "per_page": 5,
            },
            headers={"Authorization": PEXELS_API_KEY},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()

    for video in data.get("videos", []):
        # Pick the best HD file
        for vf in video.get("video_files", []):
            if vf.get("height", 0) >= 720 and vf.get("width", 0) < vf.get("height", 0):
                return {
                    "url": vf["link"],
                    "width": vf["width"],
                    "height": vf["height"],
                    "duration": video.get("duration", duration_hint),
                }
    # Fallback: first file
    if data.get("videos") and data["videos"][0].get("video_files"):
        vf = data["videos"][0]["video_files"][0]
        return {
            "url": vf["link"],
            "width": vf.get("width", 1080),
            "height": vf.get("height", 1920),
            "duration": data["videos"][0].get("duration", duration_hint),
        }
    return None


async def generate_vo(text: str, voice: str = "en-US-ChristopherNeural") -> dict | None:
    """Generate VO audio, return local file path and estimated duration.

    Returns None if Edge TTS is unreachable (e.g. no network).
    """
    try:
        audio_id = str(uuid.uuid4())[:8]
        output_path = VO_DIR / f"vo_{audio_id}.mp3"
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(output_path))
        # Estimate duration from word count
        word_count = len(text.split())
        duration = max(2.0, (word_count / 150) * 60)
        return {"file": f"vo_{audio_id}.mp3", "duration": duration}
    except Exception:
        return None


def _select_music_track(mood: str | None = None) -> dict:
    """Pick a music track, optionally filtered by mood."""
    candidates = [t for t in _DEFAULT_TRACKS if t.mood == mood] if mood else list(_DEFAULT_TRACKS)
    if not candidates:
        candidates = [t for t in _DEFAULT_TRACKS if t.mood == MusicMood.CHILL]
    track = random.choice(candidates)
    return {"name": track.name, "url": track.url, "mood": track.mood}


# =============================================================================
# API Endpoints
# =============================================================================


@app.get("/api/workflows")
async def get_workflows():
    """Return all available workflow presets."""
    workflows = list_workflows()
    return [
        {
            "version": wf.version,
            "name": wf.name,
            "description": wf.description,
            "subtitle_style": _subtitle_style_from_workflow(wf),
            "ugc_enabled": wf.ugc_enabled,
        }
        for wf in workflows
    ]


@app.get("/api/music")
async def get_music():
    """Return music tracks grouped by mood."""
    by_mood: dict[str, list[dict]] = {}
    for track in _DEFAULT_TRACKS:
        mood = track.mood
        if mood not in by_mood:
            by_mood[mood] = []
        by_mood[mood].append({
            "name": track.name,
            "url": track.url,
            "duration_seconds": track.duration_seconds,
        })
    return by_mood


@app.get("/api/local-videos")
async def get_local_videos():
    """Return list of available local videos."""
    library = get_local_video_library()
    if not library:
        return {"enabled": False, "videos": [], "count": 0}

    return {
        "enabled": True,
        "count": library.count,
        "videos": [
            {
                "id": v.id,
                "filename": v.filename,
                "url": v.url,
                "width": v.width,
                "height": v.height,
            }
            for v in library.videos
        ],
    }


@app.get("/api/local-videos/random")
async def get_random_local_videos(count: int = 5):
    """Get random local videos for preview options."""
    library = get_local_video_library()
    if not library:
        return {"enabled": False, "videos": []}

    videos = library.get_random(count)
    return {
        "enabled": True,
        "videos": [
            {
                "id": v.id,
                "filename": v.filename,
                "url": v.url,
                "stream_url": v.url,  # Alias for compatibility
                "width": v.width,
                "height": v.height,
            }
            for v in videos
        ],
    }


@app.get("/api/local-videos/for-shots")
async def get_local_videos_for_shots(total_shots: int = 5, options_per_shot: int = 5):
    """Get local video options for each shot in a video."""
    library = get_local_video_library()
    if not library:
        return {"enabled": False, "shots": []}

    shots = []
    for i in range(total_shots):
        options = library.get_options_for_shot(i, options_per_shot)
        shots.append({
            "shot": i,
            "options": [
                {
                    "id": v.id,
                    "pexels_id": v.id,  # Compatibility alias
                    "filename": v.filename,
                    "url": v.url,
                    "stream_url": v.url,
                    "thumbnail": v.url,  # Use video as thumbnail (browser will show first frame)
                    "width": v.width,
                    "height": v.height,
                }
                for v in options
            ],
        })
    return {"enabled": True, "shots": shots}


@app.get("/api/formats")
async def get_formats():
    """Return available format durations for the UI picker."""
    return [
        {
            "duration_seconds": get_format_duration(d).duration_seconds,
            "min_shots": get_format_duration(d).min_shots,
            "max_shots": get_format_duration(d).max_shots,
            "vo_words": get_format_duration(d).vo_words,
            "structure": get_format_duration(d).structure,
        }
        for d in BOT_DURATIONS
    ]


@app.post("/api/generate")
async def generate_scene(body: dict):
    """Generate a full preview scene from a URL.

    Request: {
        "url": "https://...",
        "language": "en",
        "duration": 30,
        "workflow": 0,
        "num_briefs": 3,
        "music_mood": null
    }
    Response: {
        "briefs": [...],
        "music": {...},
        "workflow": {...}
    }
    """
    try:
        return await _do_generate(body)
    except Exception:
        logger.exception("generate_scene failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


async def _do_generate(body: dict):
    url = body.get("url", "")
    language = body.get("language", "en")
    duration = body.get("duration", 30)
    workflow_version = body.get("workflow", 0)
    num_briefs = body.get("num_briefs", 3)
    music_mood = body.get("music_mood")

    # 1. Fetch page
    content = await fetch_page_content(url)

    # 2. Generate briefs (multiple)
    raw_briefs = await generate_briefs(content, language, duration, num_briefs)

    # 3. For each brief, process shots in parallel
    voice = VOICE_MAP.get(language, "en-US-ChristopherNeural")

    async def process_shot(shot: dict, index: int):
        visual = shot.get("visual", {})
        audio = shot.get("audio", {})
        vo_info = audio.get("voiceover", {})
        query = " ".join(visual.get("search_terms", [visual.get("description", "")]))
        vo_text = vo_info.get("text", "")
        vo_tone = vo_info.get("tone", "conversational")

        video_task = search_pexels_video(query, int(shot.get("duration_seconds", 5)))
        vo_task = generate_vo(vo_text, voice) if vo_text else None

        video = await video_task
        vo = await vo_task if vo_task else None

        return {
            "index": index,
            "description": visual.get("description", ""),
            "voiceover_text": vo_text,
            "tone": vo_tone,
            "duration": shot.get("duration_seconds", 5),
            "video": video,
            "vo": vo,
        }

    async def process_brief(brief: dict):
        shots = brief.get("shot_list", [])
        scene_shots = await asyncio.gather(
            *(process_shot(s, i) for i, s in enumerate(shots))
        )
        scene_shots = sorted(scene_shots, key=lambda s: s["index"])
        return {
            "title": brief.get("brief_id", "Untitled"),
            "shots": scene_shots,
        }

    briefs = await asyncio.gather(*(process_brief(b) for b in raw_briefs))

    # 4. Pick music track
    music = _select_music_track(music_mood)

    # 5. Get workflow info
    workflows = list_workflows()
    wf = next((w for w in workflows if w.version == workflow_version), workflows[0])

    return {
        "briefs": list(briefs),
        "music": music,
        "workflow": {
            "version": wf.version,
            "name": wf.name,
            "description": wf.description,
            "subtitle_style": _subtitle_style_from_workflow(wf),
        },
        "language": language,
    }


# =============================================================================
# Wizard Step Endpoints
# =============================================================================

_STYLE_LABELS = {
    0: "Pill",
    1: "Serif",
    2: "Serif + PIP",
}


@app.post("/api/briefs/generate")
async def briefs_generate(body: dict):
    """Step 1: Fetch URL and generate raw briefs (no video/VO)."""
    try:
        url = body.get("url", "")
        language = body.get("language", "en")
        duration = body.get("duration", 30)
        num_briefs = body.get("num_briefs", 3)

        page_content = await fetch_page_content(url)
        briefs = await generate_briefs(page_content, language, duration, num_briefs)
        return {"page_content": page_content, "briefs": briefs}
    except Exception:
        logger.exception("briefs_generate failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.post("/api/briefs/generate-stream")
async def briefs_generate_stream(body: dict):
    """Step 1 (streaming): Fetch URL or use provided content, then stream LLM tokens via SSE."""
    url = body.get("url", "")
    content = body.get("content", "")
    language = body.get("language", "en")
    duration = body.get("duration", 30)
    num_briefs = body.get("num_briefs", 1)

    async def event_stream():
        try:
            # Use provided content directly, or fetch from URL
            page_content = content if content else await fetch_page_content(url)
            # Send page_content first so frontend has it
            yield f"data: {json.dumps({'type': 'page_content', 'content': page_content})}\n\n"
            # Stream LLM tokens
            full_text = ""
            async for token in generate_briefs_stream(
                page_content, language, duration, num_briefs
            ):
                full_text += token
                yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
            # Parse final result and send complete briefs
            raw = full_text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            parsed = _parse_json_lenient(raw)
            if isinstance(parsed, dict):
                parsed = [parsed]
            yield f"data: {json.dumps({'type': 'done', 'briefs': parsed})}\n\n"
        except Exception:
            logger.exception("briefs_generate_stream failed")
            msg = traceback.format_exc().splitlines()[-1]
            yield f"data: {json.dumps({'type': 'error', 'error': msg})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/briefs/regenerate")
async def briefs_regenerate(body: dict):
    """Step 1b: Regenerate briefs from existing page content (no URL fetch)."""
    try:
        page_content = body.get("page_content", "")
        language = body.get("language", "en")
        duration = body.get("duration", 30)
        num_briefs = body.get("num_briefs", 3)

        briefs = await generate_briefs(page_content, language, duration, num_briefs)
        return {"briefs": briefs}
    except Exception:
        logger.exception("briefs_regenerate failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.post("/api/videos/search")
async def videos_search(body: dict):
    """Step 2: Search Pexels for multiple video options per shot."""
    try:
        shots = body.get("shots", [])
        results = []
        for shot in shots:
            query = " ".join(shot.get("search_terms", []))
            duration_hint = shot.get("duration_hint", 5)
            options = await search_pexels_videos_multi(query, duration_hint)
            results.append({
                "shot_index": shot.get("shot_index", 0),
                "options": options,
            })
        return {"results": results}
    except Exception:
        logger.exception("videos_search failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.post("/api/videos/refresh")
async def videos_refresh(body: dict):
    """Step 2b: Refresh video options for a single shot."""
    try:
        shot_index = body.get("shot_index", 0)
        query = " ".join(body.get("search_terms", []))
        duration_hint = body.get("duration_hint", 5)
        options = await search_pexels_videos_multi(query, duration_hint)
        return {"shot_index": shot_index, "options": options}
    except Exception:
        logger.exception("videos_refresh failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.get("/api/voices")
async def get_voices(language: str = "en"):
    """Step 3: List available voices for a language.

    Returns OpenAI voices when OpenAI TTS is enabled (better quality),
    otherwise returns Edge TTS voices (free).
    """
    # If OpenAI TTS is available, return OpenAI voices (works for all languages)
    if OPENAI_API_KEY:
        from src.providers.tts.openai_tts import OPENAI_VOICES

        return {
            "voices": [
                {
                    "voice_id": vid,
                    "name": vinfo["name"],
                    "gender": vinfo["gender"],
                    "tone": vinfo["style"],
                    "description": f"{vinfo['name']} - {vinfo['style']} {vinfo['gender']} voice",
                    "provider": "openai",
                }
                for vid, vinfo in OPENAI_VOICES.items()
            ],
            "provider": "openai",
        }

    # Fallback: Edge TTS voices (language-specific)
    locale = LANGUAGE_LOCALE_MAP.get(language, "en-US")
    voices = list_voices(locale=locale)
    return {
        "voices": [
            {
                "voice_id": v.voice_id,
                "name": v.name,
                "gender": v.gender,
                "tone": v.tone,
                "description": v.description,
                "edge_tts_name": v.edge_tts_name,
                "provider": "edge",
            }
            for v in voices
        ],
        "provider": "edge",
    }


@app.post("/api/voices/audition")
async def voices_audition(body: dict):
    """Step 3b: Generate a VO sample for auditioning a voice."""
    edge_tts_name = body.get("edge_tts_name", "")
    text = body.get("text", "")
    result = await generate_vo(text, edge_tts_name)
    if result is None:
        return JSONResponse(
            status_code=500,
            content={"error": "Voice synthesis failed"},
        )
    return {"audio_file": result["file"], "duration": result["duration"]}


@app.get("/api/subtitle-styles")
async def get_subtitle_styles():
    """Step 4: List subtitle style presets from workflows."""
    workflows = list_workflows()
    return {
        "styles": [
            {
                "version": wf.version,
                "label": _STYLE_LABELS.get(wf.version, wf.name),
                "description": wf.description,
                "subtitle_style": _subtitle_style_from_workflow(wf),
                "has_pip": wf.ugc_enabled and wf.ugc_overlay,
            }
            for wf in workflows
        ]
    }


@app.post("/api/telegram/top-posts")
async def telegram_top_posts(body: dict):
    """Fetch top posts from a Telegram channel for the post picker."""
    try:
        channel = body.get("channel", "")
        page_size = body.get("page_size", 20)
        offset_id = body.get("offset_id")

        if not TELEGRAM_API_HASH:
            return JSONResponse(
                status_code=500,
                content={"error": "TELEGRAM_API_HASH not configured"},
            )

        # Use absolute path to session file in project root
        session_path = str(Path(__file__).resolve().parent.parent / "tg_stats_session")
        analyzer = TelegramAnalyzer(
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
            session_name=session_path,
        )

        # Only pass offset_id if it's a valid positive integer
        fetch_kwargs = {
            "channel_input": channel,
            "limit": page_size,
            "sort_by": SortBy.ENGAGEMENT,
            "max_scan": page_size,
        }
        if offset_id and isinstance(offset_id, int) and offset_id > 0:
            fetch_kwargs["offset_id"] = offset_id

        result = await analyzer.fetch_top_posts(**fetch_kwargs)

        posts = [
            {
                "message_id": p.message_id,
                "text": p.text,
                "date": p.date.isoformat() if p.date else None,
                "views": p.views,
                "forwards": p.forwards,
                "total_reactions": p.total_reactions,
                "reactions_breakdown": p.reactions_breakdown,
                "engagement_score": p.engagement_score,
                "link": p.link,
                "has_media": p.has_media,
            }
            for p in result.top_posts
        ]

        return {
            "posts": posts,
            "channel": result.stats.channel,
            "has_more": len(result.top_posts) == page_size,
            "next_offset_id": result.last_message_id,
        }
    except Exception:
        logger.exception("telegram_top_posts failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.post("/api/telegram/analyze-channel")
async def telegram_analyze_channel(body: dict):
    """Analyze a Telegram channel to identify themes and classify posts.

    Request: {"channel": "@username", "max_posts": 100}
    Response: {
        "channel": "username",
        "theme": {primary_topic, subtopics, tone, target_audience},
        "sample_posts": [{post_id, is_evergreen, is_promotional, video_potential, ...}]
    }
    """
    try:
        from src.telegram.telegram_channel_analyzer import (
            classify_post,
            detect_channel_theme,
        )

        channel = body.get("channel", "")
        max_posts = body.get("max_posts", 100)

        if not TELEGRAM_API_HASH:
            return JSONResponse(
                status_code=500,
                content={"error": "TELEGRAM_API_HASH not configured"},
            )

        session_path = str(Path(__file__).resolve().parent.parent / "tg_stats_session")
        analyzer = TelegramAnalyzer(
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
            session_name=session_path,
        )

        result = await analyzer.fetch_top_posts(
            channel_input=channel,
            limit=max_posts,
            sort_by=SortBy.ENGAGEMENT,
            max_scan=max_posts,
        )

        # Detect channel theme from post texts
        texts = [p.text for p in result.top_posts if p.text]
        theme = detect_channel_theme(texts)

        # Classify each post
        classified_posts = []
        for post in result.top_posts:
            if not post.text:
                continue
            classification = classify_post(
                post_id=post.message_id,
                text=post.text,
                views=post.views,
                forwards=post.forwards,
                reactions=post.total_reactions,
                channel_theme=theme.primary_topic,
            )
            classified_posts.append({
                "message_id": post.message_id,
                "text": post.text[:200] + "..." if len(post.text) > 200 else post.text,
                "date": post.date.isoformat() if post.date else None,
                "views": post.views,
                "forwards": post.forwards,
                "engagement_score": post.engagement_score,
                "link": post.link,
                "is_evergreen": classification.is_evergreen,
                "is_promotional": classification.is_promotional,
                "is_about_channel": classification.is_about_channel,
                "theme_relevance": classification.theme_relevance,
                "video_potential": classification.video_potential,
            })

        return {
            "channel": result.stats.channel,
            "theme": {
                "primary_topic": theme.primary_topic,
                "subtopics": theme.subtopics,
                "tone": theme.tone,
                "target_audience": theme.target_audience,
            },
            "sample_posts": classified_posts,
        }
    except Exception:
        logger.exception("telegram_analyze_channel failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.post("/api/telegram/select-posts")
async def telegram_select_posts(body: dict):
    """Select best posts for video creation based on scoring.

    Request: {"channel": "@username", "count": 5, "exclude_ids": []}
    Response: {posts sorted by video potential score, filtered for evergreen content}
    """
    try:
        from src.telegram.telegram_channel_analyzer import (
            classify_post,
            detect_channel_theme,
        )

        channel = body.get("channel", "")
        count = body.get("count", 5)
        exclude_ids = set(body.get("exclude_ids", []))

        if not TELEGRAM_API_HASH:
            return JSONResponse(
                status_code=500,
                content={"error": "TELEGRAM_API_HASH not configured"},
            )

        session_path = str(Path(__file__).resolve().parent.parent / "tg_stats_session")
        analyzer = TelegramAnalyzer(
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
            session_name=session_path,
        )

        # Fetch more posts than needed to filter
        result = await analyzer.fetch_top_posts(
            channel_input=channel,
            limit=count * 5,  # Fetch 5x to account for filtering
            sort_by=SortBy.ENGAGEMENT,
            max_scan=500,
        )

        # Detect theme for relevance scoring
        texts = [p.text for p in result.top_posts if p.text]
        theme = detect_channel_theme(texts)

        # Classify and score each post
        scored_posts = []
        for post in result.top_posts:
            if not post.text or post.message_id in exclude_ids:
                continue
            classification = classify_post(
                post_id=post.message_id,
                text=post.text,
                views=post.views,
                forwards=post.forwards,
                reactions=post.total_reactions,
                channel_theme=theme.primary_topic,
            )
            # Skip promotional and channel self-promo
            if classification.is_promotional or classification.is_about_channel:
                continue
            scored_posts.append({
                "message_id": post.message_id,
                "text": post.text,
                "date": post.date.isoformat() if post.date else None,
                "views": post.views,
                "engagement_score": post.engagement_score,
                "link": post.link,
                "is_evergreen": classification.is_evergreen,
                "video_potential": classification.video_potential,
            })

        # Sort by video_potential and take top N
        scored_posts.sort(key=lambda p: p["video_potential"], reverse=True)

        return {
            "channel": result.stats.channel,
            "posts": scored_posts[:count],
            "total_scanned": len(result.top_posts),
            "filtered_out": len(result.top_posts) - len(scored_posts),
        }
    except Exception:
        logger.exception("telegram_select_posts failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


@app.post("/api/telegram/generate-video")
async def telegram_generate_video(body: dict):
    """Generate a video from a Telegram post using Open Loop framework.

    Request: {
        "channel": "@username",
        "post_text": "...",
        "language": "en",
        "duration": 60,
        "cta_type": "read_post"
    }
    Response: SSE stream (same format as /api/generate-live)
    """
    from src.prompts.telegram_video import (
        TelegramVideoConfig,
        build_telegram_video_prompt,
    )

    channel = body.get("channel", "").lstrip("@")
    post_text = body.get("post_text", "")
    language = body.get("language", "en")
    duration = body.get("duration", 60)
    cta_type = body.get("cta_type", "read_post")
    selected_voice = body.get("voice")

    async def event_stream():
        try:
            # 1. Send music immediately
            music = _select_music_track()
            yield f"data: {json.dumps({'type': 'music', 'track': music})}\n\n"

            # 2. Build Telegram-specific prompt
            config = TelegramVideoConfig(
                post_text=post_text,
                channel_name=channel,
                language=language,
                duration_seconds=duration,
                num_phrases=8,  # 60s = 8 phrases
                cta_type=cta_type,
            )
            prompt = build_telegram_video_prompt(config)
            voice = VOICE_MAP.get(language, "en-US-ChristopherNeural")

            # Track parallel tasks
            audio_tasks: dict[int, asyncio.Task] = {}
            video_tasks: dict[int, asyncio.Task] = {}
            total_shots = 0

            # 3. Stream LLM response
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "https://api.deepseek.com/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2048,
                        "temperature": 0.7,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    buffer = ""

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break

                        try:
                            chunk = json.loads(payload)
                            token = chunk["choices"][0].get("delta", {}).get("content", "")
                            if not token:
                                continue

                            buffer += token

                            while "\n" in buffer:
                                line_text, buffer = buffer.split("\n", 1)
                                line_text = line_text.strip()
                                if not line_text:
                                    continue

                                try:
                                    phrase_data = json.loads(line_text)
                                    shot_idx = phrase_data.get("phrase", total_shots + 1) - 1
                                    total_shots = max(total_shots, shot_idx + 1)

                                    # Send subtitle
                                    sub_text = phrase_data.get("sub", "")
                                    if sub_text:
                                        yield f"data: {json.dumps({'type': 'sub', 'shot': shot_idx, 'text': sub_text})}\n\n"

                                    # Start TTS
                                    tts_text = phrase_data.get("tts", sub_text)
                                    if tts_text and shot_idx not in audio_tasks:
                                        audio_tasks[shot_idx] = asyncio.create_task(
                                            generate_tts_processed(tts_text, voice, shot_idx, language, selected_voice)
                                        )

                                    # Start video search
                                    video_desc = phrase_data.get("video", "")
                                    if video_desc and shot_idx not in video_tasks:
                                        video_tasks[shot_idx] = asyncio.create_task(
                                            search_video_for_shot(video_desc, shot_idx)
                                        )
                                except json.JSONDecodeError:
                                    continue
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

            # Process remaining buffer
            if buffer.strip():
                try:
                    phrase_data = json.loads(buffer.strip())
                    shot_idx = phrase_data.get("phrase", total_shots + 1) - 1
                    total_shots = max(total_shots, shot_idx + 1)

                    sub_text = phrase_data.get("sub", "")
                    if sub_text:
                        yield f"data: {json.dumps({'type': 'sub', 'shot': shot_idx, 'text': sub_text})}\n\n"

                    tts_text = phrase_data.get("tts", sub_text)
                    if tts_text and shot_idx not in audio_tasks:
                        audio_tasks[shot_idx] = asyncio.create_task(
                            generate_tts_processed(tts_text, voice, shot_idx, language, selected_voice)
                        )

                    video_desc = phrase_data.get("video", "")
                    if video_desc and shot_idx not in video_tasks:
                        video_tasks[shot_idx] = asyncio.create_task(
                            search_video_for_shot(video_desc, shot_idx)
                        )
                except json.JSONDecodeError:
                    pass

            # 4. Yield results as tasks complete
            pending_audio = set(audio_tasks.values())
            pending_video = set(video_tasks.values())

            while pending_audio or pending_video:
                done, pending = await asyncio.wait(
                    pending_audio | pending_video,
                    timeout=0.1,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    result = task.result()
                    if result:
                        if "file" in result:
                            yield f"data: {json.dumps({'type': 'audio', **result})}\n\n"
                        elif "options" in result:
                            yield f"data: {json.dumps({'type': 'video', **result})}\n\n"

                pending_audio -= done
                pending_video -= done

            # 5. Done
            yield f"data: {json.dumps({'type': 'done', 'total_shots': total_shots, 'channel': channel})}\n\n"

        except Exception:
            logger.exception("telegram_generate_video failed")
            msg = traceback.format_exc().splitlines()[-1]
            yield f"data: {json.dumps({'type': 'error', 'error': msg})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/preview/assemble")
async def preview_assemble(body: dict):
    """Step 6: Assemble final preview with selected options."""
    try:
        brief = body.get("brief", {})
        selected_videos = body.get("selected_videos", [])
        voice_info = body.get("voice", {})
        subtitle_version = body.get("subtitle_style_version", 0)
        music = body.get("music", {})
        language = body.get("language", "en")

        edge_tts_name = voice_info.get("edge_tts_name", VOICE_MAP.get(language, "en-US-ChristopherNeural"))

        # Build video lookup by shot_index
        video_by_index = {v["shot_index"]: v for v in selected_videos}

        shots = brief.get("shot_list", [])
        processed_shots = []
        for i, shot in enumerate(shots):
            vo_text = shot.get("audio", {}).get("voiceover", {}).get("text", "")
            vo = await generate_vo(vo_text, edge_tts_name) if vo_text else None

            # Use selected video or fallback
            sel_video = video_by_index.get(i)
            video = None
            if sel_video:
                video = {
                    "url": sel_video["stream_url"],
                    "width": sel_video.get("width", 1080),
                    "height": sel_video.get("height", 1920),
                    "duration": sel_video.get("duration", shot.get("duration_seconds", 5)),
                }

            processed_shots.append({
                "index": i,
                "description": shot.get("visual", {}).get("description", ""),
                "voiceover_text": vo_text,
                "tone": shot.get("audio", {}).get("voiceover", {}).get("tone", "conversational"),
                "duration": shot.get("duration_seconds", 5),
                "video": video,
                "vo": vo,
            })

        # Get workflow info
        workflows = list_workflows()
        wf = next((w for w in workflows if w.version == subtitle_version), workflows[0])

        return {
            "briefs": [
                {
                    "title": brief.get("brief_id", "Untitled"),
                    "shots": processed_shots,
                }
            ],
            "music": music,
            "workflow": {
                "version": wf.version,
                "name": wf.name,
                "description": wf.description,
                "subtitle_style": _subtitle_style_from_workflow(wf),
            },
            "language": language,
        }
    except Exception:
        logger.exception("preview_assemble failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


# =============================================================================
# Live Generation Endpoint (Parallel Pipeline)
# =============================================================================


def build_live_prompt(content: str, duration_seconds: int, language: str) -> str:
    """Build prompt for live generation that outputs phrase-by-phrase."""
    fmt = get_format_duration(duration_seconds)
    num_phrases = fmt.min_shots

    lang_label = _LANGUAGE_LABELS.get(language, "English")
    lang_note = ""
    if language != "en":
        lang_note = f"\nIMPORTANT: Write all subtitle and TTS text in {lang_label}. Video descriptions stay in English for search."

    # Structure guide based on number of phrases
    if num_phrases <= 3:
        structure = "Hook (grab attention) → Key insight → Call to action"
    elif num_phrases <= 5:
        structure = "Hook → Problem/Context → Solution/Insight → Benefit → Call to action"
    else:
        structure = "Hook → Problem → Agitate → Solution → Proof/Example → Call to action"

    return f"""You are a viral video scriptwriter creating a {duration_seconds}-second TikTok/Reels script.

CONTENT TO ADAPT:
{content[:4000]}

SCRIPT REQUIREMENTS:
- Exactly {num_phrases} phrases, ~{fmt.vo_words // num_phrases} words each
- Structure: {structure}
- Tone: Conversational, energetic, direct. Talk TO the viewer, not AT them.
- Start with a powerful hook that stops the scroll
- Each phrase should flow naturally to the next
- End with clear value or call to action
{lang_note}

OUTPUT FORMAT (NDJSON - one JSON object per line):
{{"phrase": 1, "sub": "Display text", "tts": "Spoken version", "video": "stock footage description"}}

FIELD RULES:
- "sub": Short, punchy. Numbers as digits ("$5M", "2024", "100%"). Max 10 words.
- "tts": Same meaning but speakable. Numbers spelled out ("five million dollars"). Natural speech.
- "video": Cinematic stock footage description in English. Be specific: "aerial drone shot of Manhattan skyline at sunset" not just "city"

Output ONLY {num_phrases} JSON lines. No explanations. Start with phrase 1 NOW:"""


def _preprocess_tts_text(text: str, language: str) -> str:
    """Preprocess TTS text for proper pronunciation.

    Handles common abbreviations and number patterns that TTS engines
    mispronounce, especially in Russian.
    """
    if language == "ru":
        # Russian-specific expansions (English business terms in Cyrillic)
        ru_expansions = {
            # Business terms - use phonetic Russian spelling of English pronunciation
            "б2б": "би-ту-би",
            "Б2Б": "Би-ту-би",
            "b2b": "би-ту-би",
            "B2B": "Би-ту-би",
            "б2с": "би-ту-си",
            "Б2С": "Би-ту-си",
            "b2c": "би-ту-си",
            "B2C": "Би-ту-си",
            # Common tech terms
            "AI": "эй-ай",
            "ИИ": "искусственный интеллект",
            "API": "эй-пи-ай",
            "CEO": "си-и-о",
            "PR": "пи-ар",
            "IT": "ай-ти",
            "ИТ": "ай-ти",
            # Numbers in common contexts
            "24/7": "двадцать четыре на семь",
            # Social media
            "TikTok": "Тик-Ток",
            "Instagram": "Инстаграм",
            "YouTube": "Ютуб",
        }
        for abbr, expansion in ru_expansions.items():
            text = text.replace(abbr, expansion)

        # Russian stress corrections for commonly mispronounced words
        # Format: word -> word with stress mark (combining acute accent U+0301)
        # The accent goes AFTER the stressed vowel
        ru_stress_fixes = {
            # Homographs - disambiguate by context (use most common meaning)
            "замок": "замо́к",  # lock (more common than castle)
            "Замок": "Замо́к",
            "мука": "му́ка",  # flour (more common than torment)
            "Мука": "Му́ка",
            "стоит": "сто́ит",  # costs/worth (more common than stands)
            # Commonly mispronounced words
            "звонит": "звони́т",
            "звонишь": "звони́шь",
            "звоним": "звони́м",
            "включит": "включи́т",
            "включишь": "включи́шь",
            "договор": "догово́р",
            "договоры": "догово́ры",
            "каталог": "катало́г",
            "квартал": "кварта́л",
            "красивее": "краси́вее",
            "обеспечение": "обеспе́чение",
            "средства": "сре́дства",
            "средств": "сре́дств",
            "торты": "то́рты",
            "тортов": "то́ртов",
            "банты": "ба́нты",
            "шарфы": "ша́рфы",
            "свекла": "свёкла",
            "творог": "творо́г",
            "щавель": "щаве́ль",
            "эксперт": "экспе́рт",
            "эксперты": "экспе́рты",
            "маркетинг": "ма́ркетинг",
            "жалюзи": "жалюзи́",
            "феномен": "фено́мен",
            "ходатайство": "хода́тайство",
            "облегчить": "облегчи́ть",
            "углубить": "углуби́ть",
            "баловать": "балова́ть",
            "избалованный": "избало́ванный",
        }

        # Apply stress fixes (case-sensitive)
        for word, stressed in ru_stress_fixes.items():
            # Use word boundaries to avoid partial matches
            import re
            text = re.sub(rf"\b{word}\b", stressed, text)

    return text


async def generate_tts_processed(
    text: str,
    voice: str,
    shot_idx: int,
    language: str = "en",
    openai_voice: str | None = None,
) -> dict | None:
    """Generate TTS audio with silence trimming and speed up.

    Uses OpenAI TTS if available (better quality), falls back to Edge TTS (free).

    Args:
        text: Text to synthesize
        voice: Edge TTS voice name (used as fallback)
        shot_idx: Shot index for logging
        language: Language code
        openai_voice: OpenAI voice ID (alloy, echo, fable, onyx, nova, shimmer)
    """
    try:
        # Preprocess text for better pronunciation
        text = _preprocess_tts_text(text, language)
        audio_id = str(uuid.uuid4())[:8]
        processed_path = VO_DIR / f"vo_{audio_id}.m4a"

        # Try OpenAI TTS first (better quality)
        openai_provider = get_openai_tts_provider()
        if openai_provider:
            try:
                # Use provided OpenAI voice, or default based on language
                if not openai_voice:
                    default_voices = {
                        "en": "onyx",  # Deep male, authoritative
                        "ru": "onyx",  # Works well for Russian too
                        "es": "nova",  # Warm female
                        "fr": "nova",
                        "de": "onyx",
                        "pt": "nova",
                        "it": "nova",
                    }
                    openai_voice = default_voices.get(language, "onyx")

                request = TTSRequest(text=text, voice_id=openai_voice)
                response = await openai_provider.synthesize(request, language)
                raw_path = Path(response.audio_path)

                # Process: trim silence + speed up 10% (OpenAI is already good quality)
                process = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-af", "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-40dB,atempo=1.10",
                    "-c:a", "aac", "-b:a", "192k",
                    str(processed_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()

                if process.returncode == 0:
                    raw_path.unlink(missing_ok=True)
                else:
                    # Use raw OpenAI output without processing
                    processed_path = raw_path

                # Get actual duration
                probe = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(processed_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await probe.communicate()
                duration = float(stdout.decode().strip()) if stdout else response.duration_seconds

                logger.info(f"Shot {shot_idx}: OpenAI TTS, {duration:.1f}s, ${response.cost:.4f}")
                return {
                    "shot": shot_idx,
                    "file": processed_path.name,
                    "duration": duration,
                    "provider": "openai",
                    "cost": response.cost,
                }
            except Exception as e:
                logger.warning(f"OpenAI TTS failed, falling back to Edge TTS: {e}")
                # Fall through to Edge TTS

        # Fallback: Edge TTS (free)
        raw_path = VO_DIR / f"vo_raw_{audio_id}.mp3"
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(raw_path))

        # Process: trim leading silence + speed up 15%
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(raw_path),
            "-af", "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-40dB,atempo=1.15",
            "-c:a", "aac", "-b:a", "192k",
            str(processed_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg failed: {stderr.decode()}")
            processed_path = raw_path

        # Get duration
        probe = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(processed_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await probe.communicate()
        duration = float(stdout.decode().strip()) if stdout else 2.0

        if processed_path != raw_path:
            raw_path.unlink(missing_ok=True)

        logger.info(f"Shot {shot_idx}: Edge TTS, {duration:.1f}s")
        return {
            "shot": shot_idx,
            "file": processed_path.name,
            "duration": duration,
            "provider": "edge",
            "cost": 0.0,
        }
    except Exception as e:
        logger.exception(f"TTS generation failed for shot {shot_idx}: {e}")
        return None


async def search_video_for_shot(description: str, shot_idx: int, total_shots: int = 5) -> dict:
    """Get video options for a shot.

    Uses local video library if available (instant, free), falls back to Pexels API.
    """
    # Try local videos first (instant, free, no API calls)
    library = get_local_video_library()
    if library and library.count > 0:
        local_options = library.get_options_for_shot(shot_idx, count=5)
        options = [
            {
                "pexels_id": v.id,  # Compatibility
                "thumbnail": v.url,  # Browser shows first frame
                "stream_url": v.url,
                "width": v.width,
                "height": v.height,
                "duration": 10,  # Assume 10s, will be trimmed
                "source": "local",
            }
            for v in local_options
        ]
        logger.info(f"Shot {shot_idx}: {len(options)} local videos")
        return {"shot": shot_idx, "options": options}

    # Fallback: Pexels API
    if PEXELS_API_KEY:
        options = await search_pexels_videos_multi(description, duration_hint=5, max_results=5)
        for opt in options:
            opt["source"] = "pexels"
        logger.info(f"Shot {shot_idx}: {len(options)} Pexels videos")
        return {"shot": shot_idx, "options": options}

    # No video source available
    logger.warning(f"Shot {shot_idx}: No video source available")
    return {"shot": shot_idx, "options": []}


@app.post("/api/generate-live")
async def generate_live(body: dict):
    """Live generation endpoint: streams subs, audio, and videos in parallel.

    Request: {
        url: string, content?: string, language: string, duration: int, voice?: string,
        telegram_channel?: string (uses Open Loop prompt when provided)
    }
    SSE Response:
        { type: "music", track: {...} }
        { type: "sub", shot: 0, text: "..." }
        { type: "audio", shot: 0, file: "...", duration: 2.3 }
        { type: "video", shot: 0, options: [...] }
        { type: "done", total_shots: N, telegram_channel?: string }
    """
    url = body.get("url", "")
    content = body.get("content", "")
    language = body.get("language", "en")
    duration = body.get("duration", 30)
    selected_voice = body.get("voice")  # OpenAI voice ID (alloy, echo, fable, onyx, nova, shimmer)
    telegram_channel = body.get("telegram_channel", "")  # For Telegram posts - uses Open Loop prompt

    async def event_stream():
        try:
            # 1. Use provided content directly, or fetch from URL
            page_content = content if content else await fetch_page_content(url)

            # 2. Send music immediately
            music = _select_music_track()
            yield f"data: {json.dumps({'type': 'music', 'track': music})}\n\n"

            # 3. Build prompt - use Open Loop for Telegram, generic otherwise
            if telegram_channel:
                from src.prompts.telegram_video import (
                    TelegramVideoConfig,
                    build_telegram_video_prompt,
                )
                config = TelegramVideoConfig(
                    post_text=page_content,
                    channel_name=telegram_channel.lstrip("@"),
                    language=language,
                    duration_seconds=duration,
                    num_phrases=8 if duration >= 60 else 5,
                )
                prompt = build_telegram_video_prompt(config)
                logger.info(f"Using Open Loop prompt for @{telegram_channel}")
            else:
                prompt = build_live_prompt(page_content, duration, language)

            voice = VOICE_MAP.get(language, "en-US-ChristopherNeural")

            # Track parallel tasks
            audio_tasks: dict[int, asyncio.Task] = {}
            video_tasks: dict[int, asyncio.Task] = {}
            total_shots = 0

            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "https://api.deepseek.com/chat/completions",
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2048,
                        "temperature": 0.7,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    buffer = ""

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break

                        try:
                            chunk = json.loads(payload)
                            token = chunk["choices"][0].get("delta", {}).get("content", "")
                            if not token:
                                continue

                            buffer += token

                            # Try to parse complete JSON lines
                            while "\n" in buffer:
                                line_text, buffer = buffer.split("\n", 1)
                                line_text = line_text.strip()
                                if not line_text:
                                    continue

                                try:
                                    phrase_data = json.loads(line_text)
                                    shot_idx = phrase_data.get("phrase", total_shots + 1) - 1
                                    total_shots = max(total_shots, shot_idx + 1)

                                    # Send subtitle immediately
                                    sub_text = phrase_data.get("sub", "")
                                    if sub_text:
                                        yield f"data: {json.dumps({'type': 'sub', 'shot': shot_idx, 'text': sub_text})}\n\n"

                                    # Start TTS generation in background
                                    tts_text = phrase_data.get("tts", sub_text)
                                    if tts_text and shot_idx not in audio_tasks:
                                        audio_tasks[shot_idx] = asyncio.create_task(
                                            generate_tts_processed(tts_text, voice, shot_idx, language, selected_voice)
                                        )

                                    # Start video search in background
                                    video_desc = phrase_data.get("video", "")
                                    if video_desc and shot_idx not in video_tasks:
                                        video_tasks[shot_idx] = asyncio.create_task(
                                            search_video_for_shot(video_desc, shot_idx)
                                        )

                                except json.JSONDecodeError:
                                    continue

                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

            # Process remaining buffer
            if buffer.strip():
                try:
                    phrase_data = json.loads(buffer.strip())
                    shot_idx = phrase_data.get("phrase", total_shots + 1) - 1
                    total_shots = max(total_shots, shot_idx + 1)

                    sub_text = phrase_data.get("sub", "")
                    if sub_text:
                        yield f"data: {json.dumps({'type': 'sub', 'shot': shot_idx, 'text': sub_text})}\n\n"

                    tts_text = phrase_data.get("tts", sub_text)
                    if tts_text and shot_idx not in audio_tasks:
                        audio_tasks[shot_idx] = asyncio.create_task(
                            generate_tts_processed(tts_text, voice, shot_idx, language, selected_voice)
                        )

                    video_desc = phrase_data.get("video", "")
                    if video_desc and shot_idx not in video_tasks:
                        video_tasks[shot_idx] = asyncio.create_task(
                            search_video_for_shot(video_desc, shot_idx)
                        )
                except json.JSONDecodeError:
                    pass

            # 4. Yield results as tasks complete
            pending_audio = set(audio_tasks.values())
            pending_video = set(video_tasks.values())

            while pending_audio or pending_video:
                done, pending = await asyncio.wait(
                    pending_audio | pending_video,
                    timeout=0.1,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    result = task.result()
                    if result:
                        if "file" in result:
                            yield f"data: {json.dumps({'type': 'audio', **result})}\n\n"
                        elif "options" in result:
                            yield f"data: {json.dumps({'type': 'video', **result})}\n\n"

                pending_audio -= done
                pending_video -= done

            # 5. Generate CTA video if telegram_channel provided
            cta_video_url = None
            if telegram_channel:
                yield f"data: {json.dumps({'type': 'cta', 'status': 'generating'})}\n\n"
                try:
                    from src.telegram.telegram_cta_compositor import TelegramCTACompositor
                    from src.telegram.telegram_screen_recorder import TelegramScreenRecorder

                    # Create work directory for CTA
                    cta_id = str(uuid.uuid4())[:8]
                    cta_dir = OUTPUT_DIR / f"cta_{cta_id}"
                    cta_dir.mkdir(parents=True, exist_ok=True)

                    # Record the channel
                    print(f"[DEBUG] Recording CTA for {telegram_channel}")
                    recorder = TelegramScreenRecorder(channel=telegram_channel, duration_seconds=4.0)
                    recording = await recorder.record(output_dir=cta_dir)

                    # Composite into iPhone frame
                    cta_output = cta_dir / "cta.mp4"
                    compositor = TelegramCTACompositor(recording, cta_output, show_finger=True)
                    await compositor.compose()

                    if cta_output.exists():
                        cta_video_url = f"/rendered/cta_{cta_id}/cta.mp4"
                        yield f"data: {json.dumps({'type': 'cta', 'status': 'ready', 'video_url': cta_video_url})}\n\n"
                        print(f"[DEBUG] CTA ready: {cta_video_url}")
                    else:
                        yield f"data: {json.dumps({'type': 'cta', 'status': 'error'})}\n\n"
                except Exception as e:
                    print(f"[DEBUG] CTA error: {e}")
                    yield f"data: {json.dumps({'type': 'cta', 'status': 'error', 'message': str(e)})}\n\n"

            # 6. Done - include telegram_channel and CTA info
            done_data = {'type': 'done', 'total_shots': total_shots}
            if telegram_channel:
                done_data['telegram_channel'] = telegram_channel
            if cta_video_url:
                done_data['cta_video_url'] = cta_video_url
            yield f"data: {json.dumps(done_data)}\n\n"

        except Exception:
            logger.exception("generate_live failed")
            msg = traceback.format_exc().splitlines()[-1]
            yield f"data: {json.dumps({'type': 'error', 'error': msg})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


OUTPUT_DIR = Path("/tmp/creative_master/rendered")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Serve rendered videos
app.mount("/rendered", StaticFiles(directory=str(OUTPUT_DIR)), name="rendered")


def _strip_emojis(text: str) -> str:
    """Remove emojis from text to avoid rendering issues.

    PIL/Pillow can't render color emojis properly, so we strip them
    from subtitle text to avoid showing squares.
    """
    import unicodedata

    result = []
    for char in text:
        # Skip emoji characters (category starts with 'So' = Symbol, Other)
        # Also skip variation selectors and zero-width joiners used in emoji
        cat = unicodedata.category(char)
        if cat in ("So", "Mn", "Cf"):  # Symbol Other, Mark Nonspacing, Format
            continue
        # Skip specific emoji-related code points
        code = ord(char)
        if (
            0x1F300 <= code <= 0x1F9FF  # Misc Symbols, Emoticons, etc.
            or 0x2600 <= code <= 0x26FF  # Misc symbols
            or 0x2700 <= code <= 0x27BF  # Dingbats
            or 0xFE00 <= code <= 0xFE0F  # Variation selectors
            or code == 0x200D  # Zero-width joiner
        ):
            continue
        result.append(char)
    return "".join(result).strip()


def _render_subtitle_image(text: str, output_path: Path, y_ratio: float = 0.75):
    """Render subtitle text as a transparent PNG overlay (1080x1920).

    Matches the preview styling: black pill background, white text, centered.
    """
    # Strip emojis to avoid rendering squares
    text = _strip_emojis(text)
    if not text:
        return  # Nothing to render

    width, height = 1080, 1920
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Scale factor: preview is ~280px wide, video is 1080px
    # Preview uses fontSize 14, so video should use ~54
    font_size = 54
    max_text_width = int(width * 0.90)  # 90% max width like preview
    padding_h = 24  # horizontal padding
    padding_v = 12  # vertical padding

    # Try to load a font with good Unicode/Cyrillic support
    font = None
    font_candidates = [
        # Linux - NotoSans has excellent Unicode coverage
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
        # Linux - DejaVu also has good coverage
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        # macOS
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for font_path in font_candidates:
        if Path(font_path).exists():
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Word wrap if text is too wide
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_text_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    if not lines:
        lines = [text]

    # Calculate dimensions for all lines
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    max_line_width = max(line_widths)
    line_spacing = 8
    total_text_height = sum(line_heights) + line_spacing * (len(lines) - 1)

    # Calculate background pill dimensions
    bg_width = max_line_width + padding_h * 2
    bg_height = total_text_height + padding_v * 2

    # Center horizontally, position vertically by y_ratio
    bg_x = (width - bg_width) // 2
    bg_y = int(height * y_ratio) - bg_height // 2

    # Draw background pill
    bg_rect = [bg_x, bg_y, bg_x + bg_width, bg_y + bg_height]
    draw.rounded_rectangle(bg_rect, radius=16, fill=(0, 0, 0, 180))

    # Draw each line of text, centered
    current_y = bg_y + padding_v
    for i, line in enumerate(lines):
        line_width = line_widths[i]
        line_x = (width - line_width) // 2
        draw.text((line_x, current_y), line, font=font, fill=(255, 255, 255, 255))
        current_y += line_heights[i] + line_spacing

    img.save(output_path, "PNG")


async def _render_cta_clip(channel: str, post_preview: str, work_dir: Path, duration: float = 4.0) -> Path | None:
    """Render CTA clip with screen recording of Telegram channel in iPhone frame.

    Records the channel's public preview with scrolling, composites into
    iPhone frame with pointing finger animation.
    """
    from src.telegram.telegram_cta_compositor import TelegramCTACompositor
    from src.telegram.telegram_screen_recorder import TelegramScreenRecorder

    try:
        # Step 1: Record the channel's public preview
        logger.info(f"Recording Telegram channel: {channel}")
        recorder = TelegramScreenRecorder(channel=channel, duration_seconds=duration)
        recording_path = await recorder.record(output_dir=work_dir)

        if not recording_path.exists():
            logger.warning("Screen recording not created")
            return None

        logger.info(f"Screen recording created: {recording_path}")

        # Step 2: Composite into iPhone frame with pointing finger
        cta_clip = work_dir / "cta_clip.mp4"
        compositor = TelegramCTACompositor(
            screen_recording=recording_path,
            output_path=cta_clip,
            show_finger=True,
        )
        result = await compositor.compose()

        if not result.exists():
            logger.warning("CTA composition failed")
            return None

        # Step 3: Scale to target resolution (1080x1920)
        final_clip = work_dir / "cta_final.mp4"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(cta_clip),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", VIDEO_ENCODER, *VIDEO_ENCODER_OPTS,
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(final_clip),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"CTA scaling failed: {stderr.decode()[-200:]}")
            # Fall back to unscaled version
            return cta_clip

        logger.info(f"CTA clip created: {final_clip}")
        return final_clip
    except Exception as e:
        logger.exception(f"CTA clip error: {e}")
        return None


@app.post("/api/save-video")
async def save_video(body: dict):
    """Render final video from assembled preview data.

    Request: {
        shots: [{ sub, audio_file, video_url, duration }],
        music: { url, name },
        language: string,
        telegram_channel: string (optional - adds CTA frame at end)
    }
    Response: { video_url: string }
    """
    try:
        shots = body.get("shots", [])
        music_info = body.get("music", {})
        subtitle_y = body.get("subtitle_y", 0.75)  # 0-1, default 75% from top
        telegram_channel = body.get("telegram_channel", "")

        print(f"[DEBUG] save_video: shots={len(shots)}, telegram_channel='{telegram_channel}'")
        for i, s in enumerate(shots):
            logger.info(f"  Shot {i}: video_url={s.get('video_url', 'NONE')[:50] if s.get('video_url') else 'NONE'}, audio={s.get('audio_file')}")

        if not shots:
            return JSONResponse(status_code=400, content={"error": "No shots provided"})

        video_id = str(uuid.uuid4())[:8]
        work_dir = OUTPUT_DIR / video_id
        work_dir.mkdir(exist_ok=True)

        # Download and trim each video clip
        clip_paths = []
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            for i, shot in enumerate(shots):
                video_url = shot.get("video_url")
                duration = shot.get("duration", 3)
                audio_file = shot.get("audio_file")

                if not video_url:
                    print(f"Shot {i}: No video URL")
                    continue

                try:
                    # Download video
                    print(f"Shot {i}: Downloading {video_url[:60]}...")
                    raw_clip = work_dir / f"clip_{i}_raw.mp4"
                    resp = await client.get(video_url)
                    resp.raise_for_status()
                    raw_clip.write_bytes(resp.content)
                    print(f"Shot {i}: Downloaded {len(resp.content)} bytes")

                    # Trim to duration and scale
                    trimmed_clip = work_dir / f"clip_{i}.mp4"
                    sub_text = shot.get("sub", "")
                    print(f"Shot {i}: Trimming to {duration}s...")

                    # First: trim and scale the video
                    scaled_clip = work_dir / f"clip_{i}_scaled.mp4"
                    trim_proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", str(raw_clip),
                        "-t", str(duration),
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
                        "-c:v", VIDEO_ENCODER, *VIDEO_ENCODER_OPTS,
                        "-an",
                        str(scaled_clip),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr = await trim_proc.communicate()

                    if trim_proc.returncode != 0 or not scaled_clip.exists():
                        print(f"Shot {i}: Scale failed: {stderr.decode()[-200:]}")
                        continue

                    # Second: burn subtitle if present
                    if sub_text:
                        sub_img = work_dir / f"sub_{i}.png"
                        _render_subtitle_image(sub_text, sub_img, subtitle_y)

                        # Overlay subtitle on video
                        overlay_proc = await asyncio.create_subprocess_exec(
                            "ffmpeg", "-y",
                            "-i", str(scaled_clip),
                            "-i", str(sub_img),
                            "-filter_complex", "[0:v][1:v]overlay=0:0",
                            "-c:v", VIDEO_ENCODER, *VIDEO_ENCODER_OPTS,
                            "-an",
                            str(trimmed_clip),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        _, stderr = await overlay_proc.communicate()

                        if overlay_proc.returncode != 0:
                            print(f"Shot {i}: Overlay failed, using scaled: {stderr.decode()[-100:]}")
                            scaled_clip.rename(trimmed_clip)
                        else:
                            scaled_clip.unlink(missing_ok=True)
                            print(f"Shot {i}: Subtitle overlay OK")
                    else:
                        scaled_clip.rename(trimmed_clip)

                    # Add to clip list
                    if trimmed_clip.exists():
                        print(f"Shot {i}: Done")
                        clip_paths.append((trimmed_clip, audio_file, sub_text))
                        raw_clip.unlink(missing_ok=True)
                    else:
                        print(f"Shot {i}: Final clip not found")
                except Exception as e:
                    print(f"Shot {i}: Error - {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        if not clip_paths:
            return JSONResponse(status_code=400, content={"error": "No valid video clips"})

        # Add CTA clip at the end if telegram_channel is provided
        print(f"[DEBUG] telegram_channel check: '{telegram_channel}', will_add_cta={bool(telegram_channel)}")
        if telegram_channel:
            print(f"[DEBUG] Generating CTA clip for {telegram_channel}")
            # Get first shot's text for preview
            first_shot_text = shots[0].get("sub", "") if shots else ""
            cta_clip = await _render_cta_clip(telegram_channel, first_shot_text, work_dir, duration=4.0)
            if cta_clip and cta_clip.exists():
                clip_paths.append((cta_clip, None, None))  # No audio for CTA
                logger.info(f"Added CTA clip for @{telegram_channel}")

        # Create concat file
        concat_file = work_dir / "concat.txt"
        with open(concat_file, "w") as f:
            for clip_path, _, _ in clip_paths:
                f.write(f"file '{clip_path}'\n")

        # Concatenate videos
        concat_video = work_dir / "concat.mp4"
        concat_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", str(concat_video),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await concat_proc.communicate()

        # Concatenate all audio files
        audio_concat = work_dir / "audio_concat.txt"
        with open(audio_concat, "w") as f:
            for _, audio_file, _ in clip_paths:
                if audio_file:
                    audio_path = VO_DIR / audio_file
                    if audio_path.exists():
                        f.write(f"file '{audio_path}'\n")

        concat_audio = work_dir / "vo_concat.m4a"
        audio_concat_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(audio_concat),
            "-c", "copy", str(concat_audio),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await audio_concat_proc.communicate()

        # Final mix: video + VO audio + optional music
        final_output = work_dir / "final.mp4"

        if music_info.get("url"):
            # Download music
            music_path = work_dir / "music.mp3"
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(music_info["url"])
                music_path.write_bytes(resp.content)

            # Mix with music (sidechain ducked - music ducks when VO plays)
            # Music volume: 0.08 (was 0.15, reduced by ~45%)
            # Sidechain: threshold=0.02, ratio=8, attack=30ms, release=400ms
            mix_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", str(concat_video),
                "-i", str(concat_audio),
                "-i", str(music_path),
                "-filter_complex",
                "[1:a]asplit=2[vo][voref];"
                "[2:a]volume=0.08,aloop=loop=-1:size=2e+09[music];"
                "[music][voref]sidechaincompress=threshold=0.02:ratio=8:attack=30:release=400[musicduck];"
                "[vo][musicduck]amix=inputs=2:duration=first:normalize=0[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(final_output),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await mix_proc.communicate()
            if mix_proc.returncode != 0:
                logger.error(f"Mix failed: {stderr.decode()}")
        else:
            # Just combine video + VO
            mix_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", str(concat_video),
                "-i", str(concat_audio),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(final_output),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await mix_proc.communicate()

        if not final_output.exists():
            return JSONResponse(status_code=500, content={"error": "Video rendering failed"})

        # Move to output dir with clean name
        output_file = OUTPUT_DIR / f"video_{video_id}.mp4"
        final_output.rename(output_file)

        # Cleanup work dir
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)

        return {"video_url": f"/rendered/video_{video_id}.mp4"}

    except Exception:
        logger.exception("save_video failed")
        return JSONResponse(
            status_code=500,
            content={"error": traceback.format_exc().splitlines()[-1]},
        )


# =============================================================================
# Serve Frontend (production build)
# =============================================================================

# Check for built frontend (Docker or local build)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "ad-generator" / "dist"
if FRONTEND_DIR.exists():
    from fastapi.responses import FileResponse

    # Serve static assets
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="frontend_assets")

    @app.get("/")
    async def serve_frontend():
        """Serve the React app."""
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{path:path}")
    async def serve_frontend_fallback(path: str):
        """Fallback for client-side routing - serve index.html for non-API routes."""
        # Don't intercept API routes or static files
        if path.startswith(("api/", "vo/", "rendered/", "local-videos/")):
            return JSONResponse(status_code=404, content={"error": "Not found"})
        # Check if it's a static file
        file_path = FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html for client-side routing
        return FileResponse(FRONTEND_DIR / "index.html")

    logger.info(f"Serving frontend from {FRONTEND_DIR}")
else:
    logger.info("No frontend build found - API only mode (run 'npm run build' in ad-generator/)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8899)
