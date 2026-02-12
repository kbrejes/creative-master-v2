"""TTS text preprocessor — converts written text to speech-friendly form.

Expands numbers, dates, abbreviations, and symbols so TTS engines
produce natural-sounding speech while the original text is preserved
for subtitles.
"""

import re

_ONES = [
    "", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety",
]

_ORDINAL_MAP = {
    "1st": "first",
    "2nd": "second",
    "3rd": "third",
}


def _number_to_words(n: int) -> str:
    """Convert an integer (0–9999) to English words."""
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + _number_to_words(-n)

    parts: list[str] = []

    if n >= 1000:
        parts.append(_number_to_words(n // 1000) + " thousand")
        n %= 1000

    if n >= 100:
        parts.append(_ones_word(n // 100) + " hundred")
        n %= 100

    if n >= 20:
        tens_word = _TENS[n // 10]
        ones = n % 10
        if ones:
            parts.append(f"{tens_word}-{_ones_word(ones)}")
        else:
            parts.append(tens_word)
    elif n > 0:
        parts.append(_ones_word(n))

    return " ".join(parts)


def _ones_word(n: int) -> str:
    return _ONES[n] if 0 <= n < len(_ONES) else str(n)


def _expand_year(year: int) -> str:
    """Expand a 4-digit year to natural speech."""
    if year == 2000:
        return "two thousand"
    if 2001 <= year <= 2009:
        return f"two thousand {_ones_word(year - 2000)}"
    if 2010 <= year <= 2099:
        hi = year // 100  # 20
        lo = year % 100   # 10-99
        return f"{_number_to_words(hi)} {_number_to_words(lo)}"
    # Generic: split into two halves
    hi = year // 100
    lo = year % 100
    if lo == 0:
        return _number_to_words(hi) + " hundred"
    return f"{_number_to_words(hi)} {_number_to_words(lo)}"


def _is_url_context(text: str, match_start: int) -> bool:
    """Check if a number is inside a URL-like context."""
    # Look back for common URL patterns
    before = text[:match_start]
    # If preceded by . or / or :// it's likely a URL/path
    stripped = before.rstrip()
    if stripped and stripped[-1] in "./:":
        return True
    # Check for common URL prefixes
    for prefix in ("http", "www.", ".co", ".com", ".io"):
        if prefix in before[max(0, match_start - 30):match_start]:
            return True
    return False


def prepare_for_tts(text: str, locale: str = "en-US") -> str:
    """Prepare text for TTS by expanding numbers and symbols.

    For non-English locales, skips number expansion since Edge TTS
    handles native number reading for supported languages.

    Args:
        text: Human-readable text (e.g. "In 2024, AI changed.")
        locale: BCP-47 locale code (default "en-US").

    Returns:
        TTS-friendly text (e.g. "In twenty twenty-four, AI changed.")
    """
    if not text:
        return text

    # Skip English-specific expansion for non-English locales
    if not locale.startswith("en"):
        return text

    result = text

    # 1. Expand ordinals (1st, 2nd, 3rd, 4th–9th)
    def _replace_ordinal(m: re.Match) -> str:
        full = m.group(0).lower()
        if full in _ORDINAL_MAP:
            return _ORDINAL_MAP[full]
        num = int(m.group(1))
        return _number_to_words(num) + "th"

    result = re.sub(r"\b(\d+)(st|nd|rd|th)\b", _replace_ordinal, result, flags=re.IGNORECASE)

    # 2. Expand 4-digit years (1900–2099) that aren't in URLs
    def _replace_year(m: re.Match) -> str:
        if _is_url_context(result, m.start()):
            return m.group(0)
        year = int(m.group(0))
        expanded = _expand_year(year)
        # Preserve capitalization if at start of sentence
        if m.start() == 0 or result[m.start() - 1] in ".!?\n" or m.start() >= 2 and result[m.start() - 2:m.start()] in (". ", "! ", "? "):
            expanded = expanded[0].upper() + expanded[1:]
        return expanded

    result = re.sub(r"\b(19|20)\d{2}\b", _replace_year, result)

    # 3. Expand standalone numbers (1–999) not in URLs
    def _replace_number(m: re.Match) -> str:
        if _is_url_context(result, m.start()):
            return m.group(0)
        num = int(m.group(0))
        return _number_to_words(num)

    result = re.sub(r"\b\d{1,3}\b", _replace_number, result)

    # 4. Expand symbols
    result = re.sub(r"\s\+\s", " plus ", result)

    return result
