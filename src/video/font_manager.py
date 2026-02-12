"""Font manager — downloads and caches Montserrat Bold from Google Fonts."""

import os
from pathlib import Path

import httpx

_FONT_REGISTRY: dict[str, str] = {
    "Montserrat-Bold": (
        "https://fonts.gstatic.com/s/montserrat/v31/"
        "JTUHjIg1_i6t8kCHKm4532VJOt5-QNFgpCuM70w-.ttf"
    ),
    "LibreBaskerville-Regular": (
        "https://fonts.gstatic.com/s/librebaskerville/v16/"
        "kmKnZrc3Hgbbcjq75U4uslyuy4kn0pNeYRI4CN2V.ttf"
    ),
    "PlayfairDisplay-Regular": (
        "https://fonts.gstatic.com/s/playfairdisplay/v37/"
        "nuFiD-vYSZviVYUb_rj3ij__anPXDTzYgEM86xQ.ttf"
    ),
    "NotoSans-Bold": (
        "https://fonts.gstatic.com/s/notosans/v42/"
        "o-0mIpQlx3QUlC5A4PNB6Ryti20_6n1iPHjcz6L1SoM-jCpoiyAaBN9d.ttf"
    ),
}

# Locales that require non-Latin glyph coverage (Cyrillic, etc.)
_CYRILLIC_LOCALES = {"ru-RU"}

# Fonts known to support Cyrillic — NotoSans covers Latin + Cyrillic + more
_CYRILLIC_FALLBACK = "NotoSans-Bold"

_GOOGLE_FONTS_URL = _FONT_REGISTRY["Montserrat-Bold"]
_FONT_FILENAME = "Montserrat-Bold.ttf"

# The variable font file is ~745KB; static Bold is ~90-120KB.
# If the cached file exceeds this, it's the old variable font.
_MAX_STATIC_FONT_SIZE = 500_000

_SYSTEM_FONTS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]

_DEFAULT_CACHE_DIR = os.path.expanduser("~/.cache/creative_master/fonts")


def get_font_for_locale(font_name: str, locale: str) -> str:
    """Return a font name that supports the locale's script.

    For Cyrillic locales (e.g. ru-RU), substitutes with NotoSans-Bold
    since the gstatic Latin-subset fonts lack Cyrillic glyphs.
    For Latin-script locales, returns the original font_name unchanged.
    """
    if locale in _CYRILLIC_LOCALES:
        return _CYRILLIC_FALLBACK
    return font_name


def _find_system_font() -> str:
    """Find a suitable system font as fallback."""
    for path in _SYSTEM_FONTS:
        if os.path.exists(path):
            return path
    return "arial"


async def ensure_font(
    font_name: str = _FONT_FILENAME,
    cache_dir: str = _DEFAULT_CACHE_DIR,
) -> str:
    """Download font if not cached, return path.

    Looks up the download URL from _FONT_REGISTRY by font_name
    (without .ttf extension). Falls back to system font on failure.
    """
    cache_path = Path(cache_dir)

    # Ensure the file has a .ttf extension for caching
    file_name = font_name if font_name.endswith(".ttf") else f"{font_name}.ttf"
    font_path = cache_path / file_name

    if font_path.exists() and font_path.stat().st_size < _MAX_STATIC_FONT_SIZE:
        return str(font_path)

    # Remove stale cache (e.g. old variable font)
    if font_path.exists():
        font_path.unlink()

    cache_path.mkdir(parents=True, exist_ok=True)

    # Look up URL from registry (strip .ttf if present for lookup)
    registry_key = font_name.removesuffix(".ttf")
    url = _FONT_REGISTRY.get(registry_key, _GOOGLE_FONTS_URL)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            font_path.write_bytes(response.content)
        return str(font_path)
    except Exception:
        return _find_system_font()


def get_font_path(cache_dir: str = _DEFAULT_CACHE_DIR) -> str:
    """Synchronous check: return cached font path or system fallback."""
    font_path = Path(cache_dir) / _FONT_FILENAME
    if font_path.exists():
        return str(font_path)
    return _find_system_font()
