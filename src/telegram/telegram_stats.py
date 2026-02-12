"""Telegram channel statistics connector using Telethon (MTProto API).

Fetches top-performing posts from any public Telegram channel by username or link.
Provides views, forwards, reactions breakdown, and engagement scoring.

Requirements:
    - telethon >= 1.36
    - api_id + api_hash from https://my.telegram.org
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SortBy(StrEnum):
    """Sorting criteria for top posts."""

    VIEWS = "views"
    FORWARDS = "forwards"
    REACTIONS = "reactions"
    ENGAGEMENT = "engagement"


@dataclass
class ChannelPost:
    """A single Telegram channel post with engagement metrics."""

    message_id: int
    text: str | None
    date: datetime
    views: int
    forwards: int
    total_reactions: int
    reactions_breakdown: dict[str, int]
    reply_count: int
    has_media: bool
    channel_username: str = ""

    @classmethod
    def from_message(cls, msg: Any) -> ChannelPost:
        """Build a ChannelPost from a Telethon Message object."""
        reactions_breakdown: dict[str, int] = {}
        total_reactions = 0
        if msg.reactions and msg.reactions.results:
            for r in msg.reactions.results:
                emoji = getattr(r.reaction, "emoticon", "?")
                reactions_breakdown[emoji] = r.count
                total_reactions += r.count

        reply_count = 0
        if msg.replies:
            reply_count = msg.replies.replies or 0

        return cls(
            message_id=msg.id,
            text=msg.text or msg.message,
            date=msg.date,
            views=msg.views or 0,
            forwards=msg.forwards or 0,
            total_reactions=total_reactions,
            reactions_breakdown=reactions_breakdown,
            reply_count=reply_count,
            has_media=msg.media is not None,
        )

    @property
    def engagement_score(self) -> int:
        """Weighted engagement: views + forwards*3 + reactions*2."""
        return self.views + self.forwards * 3 + self.total_reactions * 2

    @property
    def link(self) -> str:
        """Direct link to the post."""
        return f"https://t.me/{self.channel_username}/{self.message_id}"


@dataclass
class ChannelStats:
    """Aggregate statistics for a channel's scanned posts."""

    channel: str
    total_posts: int
    avg_views: float
    avg_forwards: float
    avg_reactions: float
    top_posts: list[ChannelPost] = field(default_factory=list)

    @classmethod
    def from_posts(cls, channel: str, posts: list[ChannelPost]) -> ChannelStats:
        if not posts:
            return cls(
                channel=channel,
                total_posts=0,
                avg_views=0,
                avg_forwards=0,
                avg_reactions=0,
            )
        n = len(posts)
        return cls(
            channel=channel,
            total_posts=n,
            avg_views=sum(p.views for p in posts) / n,
            avg_forwards=sum(p.forwards for p in posts) / n,
            avg_reactions=sum(p.total_reactions for p in posts) / n,
        )


@dataclass
class FetchResult:
    """Result of fetch_top_posts: stats + sorted top posts."""

    stats: ChannelStats
    top_posts: list[ChannelPost]
    last_message_id: int | None = None


_T_ME_PATTERN = re.compile(r"https?://t\.me/([^/?]+)/?")


class TelegramAnalyzer:
    """Fetches and analyzes posts from public Telegram channels via Telethon."""

    def __init__(self, api_id: int, api_hash: str, session_name: str = "tg_stats"):
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_name = session_name

    def parse_channel_input(self, raw: str) -> str:
        """Extract a clean channel username from user input.

        Accepts: @username, username, https://t.me/username, https://t.me/username/
        """
        raw = raw.strip()
        if not raw:
            raise ValueError("Channel input cannot be empty")

        m = _T_ME_PATTERN.match(raw)
        if m:
            return m.group(1)

        return raw.lstrip("@")

    def _get_client(self):
        """Create a Telethon TelegramClient. Overridden in tests."""
        from telethon import TelegramClient

        return TelegramClient(self._session_name, self._api_id, self._api_hash)

    def sort_posts(
        self,
        posts: list[ChannelPost],
        sort_by: SortBy,
        limit: int = 20,
    ) -> list[ChannelPost]:
        """Sort posts by the given criteria and return top N."""
        if not posts:
            return []

        key_map = {
            SortBy.VIEWS: lambda p: p.views,
            SortBy.FORWARDS: lambda p: p.forwards,
            SortBy.REACTIONS: lambda p: p.total_reactions,
            SortBy.ENGAGEMENT: lambda p: p.engagement_score,
        }
        key_fn = key_map[sort_by]
        return sorted(posts, key=key_fn, reverse=True)[:limit]

    async def fetch_top_posts(
        self,
        channel_input: str,
        limit: int = 20,
        sort_by: SortBy = SortBy.VIEWS,
        max_scan: int = 500,
        offset_id: int | None = None,
    ) -> FetchResult:
        """Fetch and rank top posts from a public Telegram channel.

        Args:
            channel_input: Channel username, @username, or t.me link.
            limit: Number of top posts to return.
            sort_by: Sorting criteria.
            max_scan: Maximum number of recent messages to scan.
            offset_id: Message ID to start scanning from (for pagination).

        Returns:
            FetchResult with stats, sorted top posts, and last_message_id for pagination.
        """
        username = self.parse_channel_input(channel_input)
        client = self._get_client()

        async with client:
            entity = await client.get_entity(username)
            channel_name = getattr(entity, "username", None) or username

            posts: list[ChannelPost] = []
            last_message_id: int | None = None
            iter_kwargs = {"limit": max_scan}
            if offset_id is not None:
                iter_kwargs["offset_id"] = offset_id
            async for msg in client.iter_messages(entity, **iter_kwargs):
                last_message_id = msg.id
                if msg.views is None:
                    continue
                post = ChannelPost.from_message(msg)
                post.channel_username = channel_name
                posts.append(post)

        stats = ChannelStats.from_posts(channel_name, posts)
        top = self.sort_posts(posts, sort_by, limit)
        stats.top_posts = top

        return FetchResult(stats=stats, top_posts=top, last_message_id=last_message_id)

    async def fetch_posts_by_ids(
        self,
        channel_input: str,
        message_ids: list[int],
    ) -> list[ChannelPost]:
        """Fetch specific posts by their message IDs.

        Args:
            channel_input: Channel username, @username, or t.me link.
            message_ids: List of message IDs to fetch.

        Returns:
            List of ChannelPost objects for the requested IDs.
            Service messages (without views) are filtered out.
        """
        if not message_ids:
            return []

        username = self.parse_channel_input(channel_input)
        client = self._get_client()

        async with client:
            entity = await client.get_entity(username)
            channel_name = getattr(entity, "username", None) or username

            # get_messages can fetch multiple messages by ID
            messages = await client.get_messages(entity, ids=message_ids)

            posts: list[ChannelPost] = []
            for msg in messages:
                if msg is None or msg.views is None:
                    continue
                post = ChannelPost.from_message(msg)
                post.channel_username = channel_name
                posts.append(post)

        return posts
