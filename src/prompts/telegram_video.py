"""Telegram video prompt generator using Open Loop framework.

Creates 60+ second educational/entertaining videos from Telegram posts.
Uses Open Loop (Zeigarnik Effect) structure:
- Teach 2 valuable insights from the post
- Leave 3rd insight unresolved ("the third piece changes everything...")
- Natural CTA: "Read the full breakdown at @channel"

Philosophy (from content_marketing.py):
- The ad IS the product. Teach something real.
- NO pain-poking, NO "are you tired of..."
- NO hype words ("amazing", "game-changing", "revolutionary")
- Deliver real value before asking for anything
"""

from __future__ import annotations

from dataclasses import dataclass

_LANGUAGE_LABELS = {
    "en": "English",
    "ru": "Russian",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
}


@dataclass
class TelegramVideoConfig:
    """Configuration for Telegram video prompt generation."""

    post_text: str
    channel_name: str
    language: str = "en"
    duration_seconds: int = 60
    num_phrases: int = 8
    cta_type: str = "read_post"  # "read_post" or "more_like_this"


def build_telegram_video_prompt(config: TelegramVideoConfig) -> str:
    """Build LLM prompt for Telegram video script generation.

    Uses Open Loop framework for 60s (8 phrases):
    1. HOOK - Surprising fact from the post
    2. CONTEXT - Why this matters to audience
    3. INSIGHT 1A - First valuable insight (begin)
    4. INSIGHT 1B - Complete first insight
    5. INSIGHT 2A - Second insight (begin)
    6. INSIGHT 2B - Complete second insight
    7. OPEN LOOP - "The third piece changes everything..." (don't reveal)
    8. CTA - "Read the full breakdown at @channel"

    Args:
        config: TelegramVideoConfig with post content and settings

    Returns:
        Prompt string for LLM to generate video script
    """
    lang_label = _LANGUAGE_LABELS.get(config.language, "English")
    lang_instruction = ""
    if config.language != "en":
        lang_instruction = f"""
LANGUAGE: Write all subtitle and TTS text in {lang_label}.
Video descriptions should remain in English for stock footage search."""

    cta_text = f"@{config.channel_name}"
    if config.cta_type == "more_like_this":
        cta_text = f"@{config.channel_name} for more like this"

    return f"""You are creating a viral educational video script from a Telegram post.

## SOURCE POST (from @{config.channel_name}):
{config.post_text}

## YOUR TASK:
Create a {config.duration_seconds}-second script with exactly {config.num_phrases} phrases.
Each phrase will be one shot in the video.

## FRAMEWORK: Open Loop (Zeigarnik Effect)
The brain cannot let go of an incomplete idea. You will:
1. Teach TWO valuable insights from this post (deliver real value)
2. Leave the THIRD insight unresolved - just hint at it
3. End with natural CTA: "Read the full breakdown at {cta_text}"

## STRUCTURE ({config.num_phrases} phrases):

1. **HOOK** - Start with a surprising fact or counterintuitive insight from the post
   - NOT "Are you tired of..." or "Do you struggle with..."
   - Use specific numbers or observations that make viewers curious

2. **CONTEXT** - Why this matters to the viewer's life/work
   - Connect to real problems they recognize
   - Build genuine interest, not manufactured urgency

3-4. **INSIGHT 1** - First valuable teaching from the post
   - Actually teach something useful
   - Be specific - use examples, numbers, concrete steps
   - The viewer should learn something real they can apply

5-6. **INSIGHT 2** - Second valuable teaching
   - Deepen understanding with another genuine insight
   - Show expertise through specificity and nuance

7. **OPEN LOOP** - Hint at the third piece WITHOUT revealing it
   - "But the third one changes everything..."
   - "The final piece is what separates beginners from experts..."
   - Create genuine curiosity, not clickbait

8. **CTA** - Natural invitation to learn more
   - "Read the full breakdown at {cta_text}"
   - NOT salesy, NOT "click now", NOT "don't miss out"
   - Just a simple "here's where to continue learning"

## CONTENT RULES (CRITICAL):
- NO hype words: "amazing", "incredible", "game-changing", "revolutionary", "secret"
- NO pain-poking: "Are you tired of...", "Frustrated by...", "Struggling with..."
- NO fake urgency: "Limited time", "Only today", "Don't miss out"
- NO empty promises: "This will change your life", "You won't believe..."
- YES: Specific numbers, concrete examples, genuine insights
- YES: Value-first - teach before asking for anything
{lang_instruction}

## OUTPUT FORMAT (NDJSON - one JSON object per line):
{{"phrase": 1, "sub": "Display text", "tts": "Spoken version", "video": "Stock description"}}

## FIELD RULES:
- "sub": Short for display. Numbers as digits ("$5M", "2024", "100%"). Max 10 words.
- "tts": Same meaning but speakable. Numbers spelled out ("five million").
- "video": Cinematic stock footage. Be specific: "drone shot of Manhattan at sunset"

Output ONLY {config.num_phrases} JSON lines. No markdown, no explanation. Start now:"""
