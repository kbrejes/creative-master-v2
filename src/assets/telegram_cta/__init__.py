"""Telegram CTA final shot generator.

Creates a final frame for Telegram channel promotional videos:
- iPhone frame with Telegram UI showing channel + post preview
- Pointing finger directing attention to the channel

The output is a 1080x1920 PNG suitable for use as the final shot
in a TikTok/Reels style video.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


@dataclass
class CTAConfig:
    """Configuration for CTA frame generation."""

    channel_name: str
    post_preview: str
    width: int = 1080
    height: int = 1920
    show_finger: bool = True
    background_color: tuple[int, int, int] = (24, 24, 27)  # Dark gray


def get_finger_asset_path() -> Path:
    """Get the path to the pointing finger asset."""
    return Path(__file__).parent / "finger_pointing.png"


def _get_font(size: int):
    """Load a font with fallback to default."""
    from PIL import ImageFont

    font_candidates = [
        "/Library/Fonts/SF-Pro-Display-Bold.otf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for font_path in font_candidates:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_telegram_ui(config: CTAConfig) -> PILImage:
    """Render a mock Telegram channel UI.

    Creates an image that looks like the Telegram app showing:
    - Channel header with name and avatar
    - Post preview text
    - Blue/Telegram-style theme

    Args:
        config: CTAConfig with channel name and post preview

    Returns:
        PIL Image object with the rendered UI
    """
    from PIL import Image, ImageDraw

    # Telegram UI dimensions (will be scaled to fit in phone frame)
    ui_width = 390
    ui_height = 600

    # Create base image with Telegram dark theme
    img = Image.new("RGBA", (ui_width, ui_height), (17, 17, 17, 255))
    draw = ImageDraw.Draw(img)

    # Telegram header (channel name bar)
    header_height = 56
    draw.rectangle([0, 0, ui_width, header_height], fill=(30, 30, 33, 255))

    # Channel avatar (circle with first letter)
    avatar_size = 40
    avatar_x = 16
    avatar_y = 8
    avatar_color = (60, 140, 255)  # Telegram blue
    draw.ellipse(
        [avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
        fill=avatar_color,
    )

    # Avatar letter
    font_avatar = _get_font(20)
    letter = config.channel_name[0].upper() if config.channel_name else "T"
    bbox = draw.textbbox((0, 0), letter, font=font_avatar)
    letter_w = bbox[2] - bbox[0]
    letter_h = bbox[3] - bbox[1]
    draw.text(
        (avatar_x + (avatar_size - letter_w) // 2, avatar_y + (avatar_size - letter_h) // 2 - 2),
        letter,
        font=font_avatar,
        fill=(255, 255, 255, 255),
    )

    # Channel name
    font_name = _get_font(18)
    draw.text(
        (avatar_x + avatar_size + 12, avatar_y + 2),
        f"@{config.channel_name}",
        font=font_name,
        fill=(255, 255, 255, 255),
    )

    # Subscriber count (fake)
    font_sub = _get_font(13)
    draw.text(
        (avatar_x + avatar_size + 12, avatar_y + 24),
        "10.2K subscribers",
        font=font_sub,
        fill=(150, 150, 150, 255),
    )

    # Post message bubble
    bubble_margin = 16
    bubble_y = header_height + 20
    bubble_width = ui_width - bubble_margin * 2
    bubble_height = 120
    bubble_radius = 12

    # Draw rounded rectangle for message bubble
    draw.rounded_rectangle(
        [bubble_margin, bubble_y, bubble_margin + bubble_width, bubble_y + bubble_height],
        radius=bubble_radius,
        fill=(30, 30, 33, 255),
    )

    # Post text (truncated with ellipsis)
    font_post = _get_font(15)
    post_text = config.post_preview
    if len(post_text) > 100:
        post_text = post_text[:97] + "..."

    # Word wrap the text
    words = post_text.split()
    lines = []
    current_line = []
    max_width = bubble_width - 24

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font_post)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    # Draw post text lines
    text_y = bubble_y + 12
    for line in lines[:4]:  # Max 4 lines
        draw.text(
            (bubble_margin + 12, text_y),
            line,
            font=font_post,
            fill=(255, 255, 255, 255),
        )
        text_y += 22

    # Time stamp
    font_time = _get_font(11)
    draw.text(
        (bubble_margin + bubble_width - 45, bubble_y + bubble_height - 20),
        "12:34",
        font=font_time,
        fill=(100, 100, 100, 255),
    )

    return img


def render_cta_frame(config: CTAConfig, output_path: Path) -> None:
    """Render the complete CTA frame with iPhone and optional finger.

    Creates a 1080x1920 PNG with:
    - Gradient background
    - iPhone frame with Telegram UI
    - Optional pointing finger above the phone

    Args:
        config: CTAConfig with settings
        output_path: Where to save the rendered PNG
    """
    from PIL import Image, ImageDraw

    # Create base image with gradient background
    img = Image.new("RGBA", (config.width, config.height), config.background_color + (255,))
    draw = ImageDraw.Draw(img)

    # Add subtle gradient overlay
    for y in range(config.height):
        alpha = int(30 * (y / config.height))
        draw.line([(0, y), (config.width, y)], fill=(0, 0, 0, alpha))

    # Render Telegram UI
    telegram_ui = render_telegram_ui(config)

    # Scale and position the UI (simulating it inside a phone frame)
    phone_scale = 1.8
    scaled_ui = telegram_ui.resize(
        (int(telegram_ui.width * phone_scale), int(telegram_ui.height * phone_scale)),
        Image.Resampling.LANCZOS,
    )

    # Center horizontally, position in lower half
    ui_x = (config.width - scaled_ui.width) // 2
    ui_y = config.height // 2 - 100

    # Add rounded corners mask for phone screen effect
    mask = Image.new("L", scaled_ui.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(
        [0, 0, scaled_ui.width - 1, scaled_ui.height - 1],
        radius=40,
        fill=255,
    )

    # Paste UI with mask
    img.paste(scaled_ui, (ui_x, ui_y), mask)

    # Add phone frame border
    border_padding = 8
    draw.rounded_rectangle(
        [
            ui_x - border_padding,
            ui_y - border_padding,
            ui_x + scaled_ui.width + border_padding,
            ui_y + scaled_ui.height + border_padding,
        ],
        radius=48,
        outline=(60, 60, 60, 255),
        width=4,
    )

    # Add "Read more" CTA text above
    font_cta = _get_font(42)
    cta_text = f"@{config.channel_name}"
    bbox = draw.textbbox((0, 0), cta_text, font=font_cta)
    text_w = bbox[2] - bbox[0]
    draw.text(
        ((config.width - text_w) // 2, ui_y - 100),
        cta_text,
        font=font_cta,
        fill=(255, 255, 255, 255),
    )

    # Add pointing indicator (arrow or finger) if enabled
    if config.show_finger:
        # Draw a simple down arrow if no finger asset
        finger_path = get_finger_asset_path()
        if finger_path.exists():
            try:
                finger = Image.open(finger_path).convert("RGBA")
                # Scale finger
                finger_scale = 0.3
                finger = finger.resize(
                    (int(finger.width * finger_scale), int(finger.height * finger_scale)),
                    Image.Resampling.LANCZOS,
                )
                finger_x = (config.width - finger.width) // 2
                finger_y = ui_y - 180
                img.paste(finger, (finger_x, finger_y), finger)
            except Exception:
                # Fallback: draw arrow
                _draw_down_arrow(draw, config.width // 2, ui_y - 140, size=40)
        else:
            # Draw arrow indicator
            _draw_down_arrow(draw, config.width // 2, ui_y - 140, size=40)

    # Save output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")


def _draw_down_arrow(draw, x: int, y: int, size: int = 40):
    """Draw a simple down-pointing arrow."""
    # Triangle pointing down
    points = [
        (x - size, y - size // 2),
        (x + size, y - size // 2),
        (x, y + size // 2),
    ]
    draw.polygon(points, fill=(255, 255, 255, 255))
