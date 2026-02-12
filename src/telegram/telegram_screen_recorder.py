"""Telegram channel screen recorder using Playwright.

Records a scrolling view of a Telegram channel's public preview,
optimized for iPhone 16 Pro Max viewport.
"""

import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright

# iPhone 16 Pro Max logical resolution (CSS pixels / points)
IPHONE_16_PRO_MAX_WIDTH = 430
IPHONE_16_PRO_MAX_HEIGHT = 932


class TelegramScreenRecorder:
    """Records Telegram channel public preview with smooth scrolling."""

    def __init__(self, channel: str, duration_seconds: float = 4.0):
        """Initialize recorder.

        Args:
            channel: Telegram channel (e.g., "@durov", "https://t.me/durov")
            duration_seconds: Recording duration in seconds
        """
        self.channel = self._parse_channel(channel)
        self.duration_seconds = duration_seconds

    def _parse_channel(self, channel: str) -> str:
        """Extract channel name from various input formats."""
        channel = channel.strip()

        # Strip @ prefix
        if channel.startswith("@"):
            return channel[1:]

        # Strip t.me URL formats
        patterns = [
            r"^https?://t\.me/s/([^/\?]+)",  # https://t.me/s/channel
            r"^https?://t\.me/([^/\?]+)",  # https://t.me/channel
            r"^t\.me/s/([^/\?]+)",  # t.me/s/channel
            r"^t\.me/([^/\?]+)",  # t.me/channel
        ]

        for pattern in patterns:
            match = re.match(pattern, channel, re.IGNORECASE)
            if match:
                return match.group(1)

        return channel

    @property
    def preview_url(self) -> str:
        """Get public preview URL for the channel."""
        return f"https://t.me/s/{self.channel}"

    async def record(self, output_dir: Path) -> Path:
        """Record the channel's public preview with scrolling.

        Args:
            output_dir: Directory to save the recording

        Returns:
            Path to the recorded video file
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=True)

            # Create context with mobile viewport and video recording
            context = await browser.new_context(
                viewport={
                    "width": IPHONE_16_PRO_MAX_WIDTH,
                    "height": IPHONE_16_PRO_MAX_HEIGHT,
                },
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                ),
                device_scale_factor=3,  # Retina display
                is_mobile=True,
                has_touch=True,
                ignore_https_errors=True,  # Fix SSL cert issues
                record_video_dir=str(output_dir),
                record_video_size={
                    "width": IPHONE_16_PRO_MAX_WIDTH,
                    "height": IPHONE_16_PRO_MAX_HEIGHT,
                },
            )

            page = await context.new_page()

            # Navigate to channel preview
            await page.goto(self.preview_url, wait_until="networkidle")

            # Hide the blue "View in Telegram" CTA button at bottom
            await page.add_style_tag(content="""
                .tgme_channel_join_telegram,
                .tgme_action_button_new,
                .tgme_footer,
                a[href*="tg://resolve"] {
                    display: none !important;
                }
            """)

            # Wait for content to load
            await page.wait_for_timeout(500)

            # Perform smooth scrolling
            await self._smooth_scroll(page)

            # Close context to finalize video
            await context.close()
            await browser.close()

            # Get the video path
            video_path = await page.video.path()
            return Path(video_path)

    async def _smooth_scroll(self, page) -> None:
        """Perform smooth scrolling animation."""
        # Calculate scroll parameters
        total_duration_ms = int(self.duration_seconds * 1000)
        scroll_interval_ms = 50  # Scroll every 50ms for smoothness
        num_scrolls = total_duration_ms // scroll_interval_ms

        # Scroll amount per interval (pixels) - adjust for natural feel
        scroll_per_interval = 15

        for _ in range(num_scrolls):
            await page.mouse.wheel(0, scroll_per_interval)
            await page.wait_for_timeout(scroll_interval_ms)
