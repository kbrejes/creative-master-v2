"""Telegram channel analyzer - post classification and theme detection.

Analyzes Telegram channel posts to:
1. Detect channel themes and topics
2. Classify posts as evergreen vs time-sensitive
3. Filter promotional and self-promotional content
4. Score video potential for content repurposing
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ChannelTheme:
    """Detected theme/topic profile for a Telegram channel."""

    primary_topic: str
    subtopics: list[str] = field(default_factory=list)
    tone: str = "educational"  # educational, casual, professional, mixed
    target_audience: str = ""


@dataclass
class PostClassification:
    """Classification result for a single post."""

    post_id: int
    is_evergreen: bool
    is_promotional: bool
    is_about_channel: bool
    theme_relevance: float  # 0-1 score
    video_potential: float  # 0-1 score


# ---------------------------------------------------------------------------
# Time-sensitive patterns (NOT evergreen)
# ---------------------------------------------------------------------------

_TIME_PATTERNS = [
    r"\btomorrow\b",
    r"\btoday\b",
    r"\byesterday\b",
    r"\bthis week\b",
    r"\bnext week\b",
    r"\bthis month\b",
    r"\blast week\b",
    r"\btonight\b",
    r"\bthis morning\b",
    r"\bthis evening\b",
    # Specific dates
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}",
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)",
    # Year references with dates
    r"\b20\d{2}\b",
    # Time references
    r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)\b",
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)\b",
    # Live events
    r"\blive\s+(?:session|event|q&a|webinar)\b",
    r"\bjoin\s+us\s+(?:on|at)\b",
]

_TIME_REGEX = re.compile("|".join(_TIME_PATTERNS), re.IGNORECASE)


def is_evergreen(text: str) -> bool:
    """Check if post content is evergreen (no time-sensitive references).

    Returns True for how-tos, frameworks, insights, etc.
    Returns False for posts with dates, events, "tomorrow", etc.
    """
    if not text:
        return False
    return not bool(_TIME_REGEX.search(text))


# ---------------------------------------------------------------------------
# Promotional patterns (external products/services)
# ---------------------------------------------------------------------------

_PROMO_PATTERNS = [
    r"\blimited\s+(?:spots?|seats?|availability|time|offer)\b",
    r"\bregister\s+now\b",
    r"\bsign\s+up\s+now\b",
    r"\benroll\s+(?:now|today)\b",
    r"\bjoin\s+(?:our|the)\s+(?:course|masterclass|workshop|program|webinar)\b",
    r"\bonly\s+\$\d+",
    r"\$\d+\s*[-–]\s*(?:enroll|register|sign up|get|buy)",
    r"\buse\s+code\b",
    r"\blink\s+in\s+bio\b",
    r"\bfree\s+(?:webinar|masterclass|workshop)\b",
    r"\bsecure\s+your\s+(?:seat|spot|place)\b",
    r"\bget\s+access\b",
    r"\bearly\s+bird\b",
    r"\bdiscount\s+(?:code|link)\b",
]

_PROMO_REGEX = re.compile("|".join(_PROMO_PATTERNS), re.IGNORECASE)


def is_promotional(text: str) -> bool:
    """Check if post is promoting external products/services.

    Returns True for course promos, affiliate links, webinar signups, etc.
    Returns False for pure educational content.
    """
    if not text:
        return False
    return bool(_PROMO_REGEX.search(text))


# ---------------------------------------------------------------------------
# Channel self-promotion patterns
# ---------------------------------------------------------------------------

_CHANNEL_PATTERNS = [
    r"\b\d+[,.]?\d*\s*(?:k|K)?\s*(?:subscribers?|followers?)\b",
    r"\bwe\s+hit\b",
    r"\bthank\s+you\s+(?:all|for)\b",
    r"\bshare\s+with\s+(?:a\s+)?friends?\b",
    r"\bsubscribe\s+for\b",
    r"\bdon't\s+forget\s+to\s+subscribe\b",
    r"\bif\s+you\s+(?:found|find)\s+this\s+helpful\b",
    r"\bfound\s+this\s+useful\b",
    r"\bone\s+year\s+of\b",
    r"\banniversary\b",
    r"\bmilestone\b",
]

_CHANNEL_REGEX = re.compile("|".join(_CHANNEL_PATTERNS), re.IGNORECASE)


def is_about_channel(text: str) -> bool:
    """Check if post is about the channel itself (milestones, subscribe asks).

    Returns True for subscriber milestones, share requests, etc.
    Returns False for content-focused posts.
    """
    if not text:
        return False
    return bool(_CHANNEL_REGEX.search(text))


# ---------------------------------------------------------------------------
# Video Potential Scoring
# ---------------------------------------------------------------------------


def score_video_potential(
    text: str,
    views: int = 0,
    forwards: int = 0,
    reactions: int = 0,
    avg_views: float = 1000,
) -> float:
    """Score a post's potential for video repurposing (0-1).

    Formula: (engagement * 0.3) + (theme_relevance * 0.4) + (evergreen * 0.3)

    - Promotional content gets heavily penalized
    - Channel self-promo gets heavily penalized
    - Evergreen educational content scores highest
    """
    # Immediate disqualifiers
    if is_promotional(text):
        return 0.1
    if is_about_channel(text):
        return 0.15

    # Base score from content type
    base_score = 0.7 if is_evergreen(text) else 0.4

    # Engagement component (normalized)
    engagement = views + forwards * 3 + reactions * 2
    expected_engagement = avg_views + avg_views * 0.1 * 3 + avg_views * 0.05 * 2
    engagement_ratio = min(engagement / max(expected_engagement, 1), 2.0)
    engagement_score = min(engagement_ratio / 2, 1.0)  # Cap at 1.0

    # Combine: 30% engagement, 70% content quality
    score = engagement_score * 0.3 + base_score * 0.7

    return round(min(max(score, 0.0), 1.0), 2)


# ---------------------------------------------------------------------------
# Post Classification
# ---------------------------------------------------------------------------


def classify_post(
    post_id: int,
    text: str,
    views: int = 0,
    forwards: int = 0,
    reactions: int = 0,
    channel_theme: str = "",
) -> PostClassification:
    """Classify a single post for video potential.

    Args:
        post_id: Telegram message ID
        text: Post text content
        views: View count
        forwards: Forward count
        reactions: Total reaction count
        channel_theme: Optional theme keyword for relevance scoring

    Returns:
        PostClassification with flags and scores
    """
    evergreen = is_evergreen(text)
    promotional = is_promotional(text)
    about_channel = is_about_channel(text)

    # Theme relevance (simple keyword match for now)
    theme_relevance = 0.5  # Default neutral
    if channel_theme and text:
        text_lower = text.lower()
        theme_lower = channel_theme.lower()
        if theme_lower in text_lower:
            theme_relevance = 0.8
        # Check for related words
        theme_words = {
            "sales": ["selling", "deal", "close", "prospect", "pipeline", "cold email"],
            "marketing": ["brand", "audience", "content", "social", "ads", "campaign"],
            "productivity": ["efficiency", "time", "focus", "habit", "routine", "workflow"],
        }
        related = theme_words.get(theme_lower, [])
        if any(word in text_lower for word in related):
            theme_relevance = 0.7

    video_potential = score_video_potential(text, views, forwards, reactions)

    return PostClassification(
        post_id=post_id,
        is_evergreen=evergreen,
        is_promotional=promotional,
        is_about_channel=about_channel,
        theme_relevance=theme_relevance,
        video_potential=video_potential,
    )


# ---------------------------------------------------------------------------
# Channel Theme Detection
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS = {
    "sales": [
        "sales", "selling", "close", "prospect", "deal",
        "pipeline", "cold email", "b2b", "objection",
    ],
    "marketing": [
        "marketing", "brand", "audience", "content",
        "social media", "ads", "campaign", "growth",
    ],
    "productivity": [
        "productivity", "efficiency", "time management",
        "focus", "habit", "routine", "workflow",
    ],
    "leadership": ["leadership", "management", "team", "culture", "hiring", "people"],
    "entrepreneurship": ["startup", "founder", "business", "entrepreneur", "scale", "revenue"],
    "psychology": ["psychology", "mindset", "behavior", "cognitive", "bias", "decision"],
    "finance": ["finance", "money", "investing", "wealth", "income", "budget"],
    "technology": ["tech", "software", "ai", "automation", "data", "code", "developer"],
}


def detect_channel_theme(texts: list[str]) -> ChannelTheme:
    """Detect the primary theme/topic of a channel from post texts.

    Analyzes multiple posts to identify:
    - Primary topic (sales, marketing, productivity, etc.)
    - Subtopics covered
    - Overall tone
    - Target audience

    Args:
        texts: List of post text contents

    Returns:
        ChannelTheme with detected profile
    """
    if not texts:
        return ChannelTheme(
            primary_topic="general",
            subtopics=[],
            tone="mixed",
            target_audience="general audience",
        )

    # Count topic keyword matches
    topic_counts: Counter = Counter()
    combined_text = " ".join(texts).lower()

    for topic, keywords in _TOPIC_KEYWORDS.items():
        count = sum(combined_text.count(kw.lower()) for kw in keywords)
        if count > 0:
            topic_counts[topic] = count

    # Determine primary topic
    if topic_counts:
        primary_topic = topic_counts.most_common(1)[0][0]
        # Get top 3 subtopics (excluding primary)
        subtopics = [t for t, _ in topic_counts.most_common(4)[1:] if t != primary_topic]
    else:
        primary_topic = "general"
        subtopics = []

    # Detect tone
    tone = "educational"  # Default
    casual_markers = ["lol", "haha", "btw", "tbh", "ngl", "!!"]
    professional_markers = ["analysis", "framework", "methodology", "strategic", "implement"]

    casual_count = sum(combined_text.count(m) for m in casual_markers)
    prof_count = sum(combined_text.count(m) for m in professional_markers)

    if casual_count > prof_count * 2:
        tone = "casual"
    elif prof_count > casual_count * 2:
        tone = "professional"
    elif casual_count > 0 and prof_count > 0:
        tone = "mixed"

    # Infer target audience
    audience_map = {
        "sales": "sales professionals and business development reps",
        "marketing": "marketers and brand managers",
        "productivity": "professionals looking to optimize their workflow",
        "leadership": "managers and team leaders",
        "entrepreneurship": "founders and business owners",
        "psychology": "people interested in human behavior and decision-making",
        "finance": "investors and finance professionals",
        "technology": "developers and tech enthusiasts",
        "general": "general audience",
    }
    target_audience = audience_map.get(primary_topic, "general audience")

    return ChannelTheme(
        primary_topic=primary_topic,
        subtopics=subtopics,
        tone=tone,
        target_audience=target_audience,
    )
