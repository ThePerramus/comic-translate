"""Syllable-aware hyphenation for word-wrapping long words in rendered text.

Uses pyphen (Hunspell-style per-language hyphenation pattern dictionaries,
the same technology LibreOffice/TeX use) to insert invisible soft hyphens
(U+00AD) at valid syllable break points. Qt's own text layout already
understands soft hyphens natively - it only shows a "-" where it actually
breaks a line there, and they're otherwise invisible - so this composes
with the live word-wrap already used for rendered text boxes without
needing to know the box width here at all.
"""

import re

import pyphen

_dictionaries: dict[str, "pyphen.Pyphen | None"] = {}

# Below this length, hyphenating a word (even where technically possible)
# just adds visual noise for no real wrapping benefit.
_MIN_WORD_LEN = 5

_word_re = re.compile(r"\S+")


def _get_dictionary(lang_code: str | None):
    if not lang_code:
        return None
    if lang_code in _dictionaries:
        return _dictionaries[lang_code]

    normalized = lang_code.replace("-", "_")
    dic = None
    for candidate in (lang_code, normalized):
        try:
            resolved = pyphen.language_fallback(candidate)
        except Exception:
            resolved = None
        if resolved:
            try:
                dic = pyphen.Pyphen(lang=resolved)
            except Exception:
                dic = None
            break

    _dictionaries[lang_code] = dic
    return dic


def hyphenate_text(text: str, lang_code: str | None) -> str:
    """Inserts invisible soft hyphens at valid syllable breaks in long words.

    Best-effort only: returns the text completely unchanged if the language
    has no hyphenation dictionary available, or if anything goes wrong -
    this is a visual aid, never something that should be able to break
    rendering.
    """
    if not text:
        return text

    dic = _get_dictionary(lang_code)
    if dic is None:
        return text

    def _hyphenate_word(match: re.Match) -> str:
        word = match.group(0)
        if len(word) < _MIN_WORD_LEN:
            return word
        try:
            return dic.inserted(word, hyphen="­")
        except Exception:
            return word

    try:
        return _word_re.sub(_hyphenate_word, text)
    except Exception:
        return text
