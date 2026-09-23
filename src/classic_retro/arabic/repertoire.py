"""Arabic glyph repertoire for renderers that need one glyph per presentation form."""

from __future__ import annotations

from functools import lru_cache

from classic_retro.arabic.pipeline import ArabicPipeline, ArabicPipelineConfig
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import TextToken, TokenStream

STANDARD_ARABIC_LETTERS = "ءآأؤإئابتثجحخدذرزسشصضطظعغفقكلمنهويىة"
ARABIC_STATIC_CHARACTERS = "،؛؟ـ٠١٢٣٤٥٦٧٨٩"


def legacy_renderer_pipeline() -> ArabicPipeline:
    """Shaping profile for fixed-glyph game fonts: no ligatures, nothing silently dropped."""
    return ArabicPipeline(
        ArabicPipelineConfig(
            support_ligatures=False,
            preserve_harakat=True,
            preserve_tatweel=True,
            support_zwj=True,
        )
    )


@lru_cache(maxsize=1)
def arabic_presentation_repertoire() -> tuple[str, ...]:
    """Every contextual form the shared shaper can emit for standard Arabic letters.

    The result is ordered by code point so that slot assignments are stable.
    """
    pipeline = legacy_renderer_pipeline()
    characters: set[str] = set(ARABIC_STATIC_CHARACTERS)

    for letter in STANDARD_ARABIC_LETTERS:
        for prefix, suffix in (("", ""), ("ب", ""), ("", "ب"), ("ب", "ب")):
            source = prefix + letter + suffix
            shaped = pipeline.process(TokenStream((TextToken(source),))).shaped.visible_text
            index = len(prefix)
            if index >= len(shaped):
                raise ClassicRetroError(
                    ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                    f"Could not derive shaped form for Arabic letter {letter!r}",
                )
            characters.add(shaped[index])

    return tuple(sorted(characters, key=ord))
