"""Build a large Unicode emoji candidate pool.

The pool is intentionally broader than Telegram's per-chat allowed reactions.
At runtime the bot intersects it with getChat.available_reactions whenever
Telegram provides an explicit allow-list.
"""

from __future__ import annotations

import unicodedata

import regex

_EMOJI_PRESENTATION = regex.compile(r"\A\p{Emoji_Presentation}\Z")
_EXTENDED_PICTOGRAPHIC = regex.compile(r"\A\p{Extended_Pictographic}\Z")

# A compact set of common reactions is used only as a fallback when Telegram
# rejects an uncommon candidate in a chat where the API reports no allow-list.
SAFE_FALLBACK_EMOJIS = (
    "👍", "❤️", "🔥", "🎉", "😍", "👏", "😁", "😢", "😡", "🤔",
    "🤯", "🥰", "💯", "🙏", "🤝", "😎", "🥳", "🤩", "👀", "🫡",
)


def build_emoji_pool() -> tuple[str, ...]:
    """Return unique single-codepoint emoji-presentation characters.

    This uses Unicode properties rather than a hand-maintained list, which
    keeps the candidate set broad and adapts to the Unicode database bundled
    with the installed `regex` package. Skin-tone modifier characters are
    excluded because they are not valid standalone reactions.
    """
    candidates: set[str] = set()
    ranges = (
        (0x2300, 0x2400),
        (0x2600, 0x2800),
        (0x1F000, 0x1FB00),
    )

    for start, end in ranges:
        for codepoint in range(start, end):
            if 0x1F3FB <= codepoint <= 0x1F3FF:
                continue
            char = chr(codepoint)
            if unicodedata.category(char) == "Cn":
                continue
            if _EMOJI_PRESENTATION.fullmatch(char):
                candidates.add(char)
            elif _EXTENDED_PICTOGRAPHIC.fullmatch(char):
                # Some valid emoji characters default to text presentation;
                # append VS16 to request their emoji presentation form.
                candidates.add(char + "\ufe0f")

    # These fully-qualified flag sequences are emoji, even though each
    # regional-indicator character is not Emoji_Presentation on its own.
    regional_indicators = range(0x1F1E6, 0x1F200)
    for first in regional_indicators:
        for second in regional_indicators:
            candidates.add(chr(first) + chr(second))

    # Standard keycap emoji sequences.
    for key in "0123456789#*":
        candidates.add(key + "\ufe0f\u20e3")

    return tuple(sorted(candidates))


EMOJI_POOL = build_emoji_pool()

if len(EMOJI_POOL) < 500:  # Fail early if an unusual runtime lacks emoji data.
    raise RuntimeError(
        f"Unicode emoji pool is too small ({len(EMOJI_POOL)} candidates); "
        "upgrade the regex package / Python Unicode data."
    )
