"""Ways to put right-to-left Arabic into a game's text renderer.

The nine reference targets proved three strategies; they are a starting set,
not a closed list. Engines on other platforms will call for other ways (a
variable-width font streamed into tiles, a texture font, a system text
service...). A strategy is registered by id with what it needs from the
game's text engine, what the toolkit's core offers for it and what it costs;
new ones come in through ``StrategyRegistry.register`` or, from another
package, the ``classic_retro.strategies.v1`` entry point group. A strategy
starts ``experimental`` and becomes ``proven`` once a target ships with it.

Every proven strategy turns the text right to left at one point of the game's
renderer. Eight of the nine targets keep the game's pen advancing left to right
and mirror only where each glyph (or cell) is drawn, so measuring, wrapping, the
typewriter and scrolling keep working; FireRed, changed from its source, starts
the pen at the line's right edge and moves it leftwards instead.
docs/ARABIC_STRATEGIES.md describes both and the techniques that come with them.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from importlib.metadata import entry_points
from inspect import isclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode

STRATEGY_ENTRY_POINT_GROUP = "classic_retro.strategies.v1"
STATUSES = ("proven", "experimental")


@dataclass(frozen=True, slots=True)
class RenderingStrategy:
    """One way of drawing Arabic through a game's renderer."""

    id: str
    title: str
    summary: str
    # What the game's text engine must allow for the strategy to fit.
    engine_needs: tuple[str, ...]
    # Reusable toolkit modules the strategy is built from.
    core: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    status: str = "experimental"

    def describe(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "engine_needs": list(self.engine_needs),
            "core": list(self.core),
            "tradeoffs": list(self.tradeoffs),
            "status": self.status,
        }


GLYPH_FONT = RenderingStrategy(
    id="glyph-font",
    title="Right-to-left glyph font",
    summary=(
        "Every contextual form of the letters is drawn from the reference font into the "
        "game's own font format; translated text is stored as those glyphs in right-to-left "
        "paint order, and the renderer places them from the right edge of the line."
    ),
    engine_needs=(
        "glyphs of their own width (a proportional font, or cells the forms fit)",
        "spare character codes, or a way to add a font next to the game's",
        "one place that decides where a glyph is drawn",
    ),
    core=(
        "classic_retro.arabic.repertoire",
        "classic_retro.arabic.paint",
        "classic_retro.font.arabic_outline",
    ),
    tradeoffs=(
        "no ligatures (lam and alef stay separate forms) and no kerning",
        "the game's own measuring sizes boxes and centres lines",
        "small: one glyph per form, text stays text",
    ),
    status="proven",
)

LINE_CELLS = RenderingStrategy(
    id="line-cells",
    title="Pre-drawn line cells",
    summary=(
        "Every translated line is shaped with HarfBuzz and drawn whole, then cut into the "
        "engine's fixed cells from its right end; the cells get codes of their own (a bank "
        "per page or one for the whole script) and a hook draws a line's n-th cell in the "
        "mirrored column."
    ),
    engine_needs=(
        "fixed-width cells (a monospace font)",
        "enough codes and tile memory for the distinct cells of a page or a script",
        "one place that decides a character's column",
    ),
    core=("classic_retro.font.shaped_text",),
    tradeoffs=(
        "full HarfBuzz shaping: ligatures, kerning, joined letters across cells",
        "text cannot change at run time; names are islands drawn with the game's glyphs",
        "cells cost ROM space and codes per distinct cell",
    ),
    status="proven",
)

TEXT_IMAGES = RenderingStrategy(
    id="text-images",
    title="Pre-drawn text images",
    summary=(
        "Text the game shows as pictures (subtitles, title cards, legends) is shaped with "
        "HarfBuzz and drawn into the game's own image format and palette."
    ),
    engine_needs=("the text is an image the game decodes (tiles, a tile map, a palette)",),
    core=("classic_retro.font.shaped_text",),
    tradeoffs=(
        "no hook needed: the images replace the originals",
        "every image must fit the original's budget (size, colours, VRAM)",
    ),
    status="proven",
)


def builtin_strategies() -> tuple[RenderingStrategy, ...]:
    return (GLYPH_FONT, LINE_CELLS, TEXT_IMAGES)


class StrategyRegistry:
    """Strategies by id, in registration order."""

    def __init__(self) -> None:
        self._strategies: dict[str, RenderingStrategy] = {}

    def register(self, strategy: RenderingStrategy) -> None:
        if not strategy.id:
            raise ClassicRetroError(ErrorCode.ADAPTER_TYPE_ERROR, "Strategy id cannot be empty")
        if strategy.status not in STATUSES:
            raise ClassicRetroError(
                ErrorCode.ADAPTER_TYPE_ERROR,
                f"Strategy {strategy.id}: status must be one of {', '.join(STATUSES)}",
            )
        if strategy.id in self._strategies:
            raise ClassicRetroError(
                ErrorCode.ADAPTER_ID_CONFLICT, f"Duplicate strategy id: {strategy.id}"
            )
        self._strategies[strategy.id] = strategy

    def get(self, strategy_id: str) -> RenderingStrategy:
        try:
            return self._strategies[strategy_id]
        except KeyError:
            raise ClassicRetroError(
                ErrorCode.INVALID_REFERENCE, f"Unknown rendering strategy: {strategy_id}"
            ) from None

    def __contains__(self, strategy_id: object) -> bool:
        return strategy_id in self._strategies

    def __iter__(self) -> Iterator[RenderingStrategy]:
        return iter(self._strategies.values())

    def load_entry_points(self) -> None:
        for entry_point in entry_points(group=STRATEGY_ENTRY_POINT_GROUP):
            try:
                loaded = entry_point.load()
                strategy = loaded() if isclass(loaded) or callable(loaded) else loaded
            except Exception as exc:
                raise ClassicRetroError(
                    ErrorCode.ADAPTER_LOAD_FAILED,
                    f"Failed to load {STRATEGY_ENTRY_POINT_GROUP}:{entry_point.name}: {exc}",
                ) from exc
            if not isinstance(strategy, RenderingStrategy):
                raise ClassicRetroError(
                    ErrorCode.ADAPTER_TYPE_ERROR,
                    f"{STRATEGY_ENTRY_POINT_GROUP}:{entry_point.name} did not provide "
                    "a RenderingStrategy",
                )
            self.register(strategy)


def build_strategy_registry(*, load_external: bool = True) -> StrategyRegistry:
    registry = StrategyRegistry()
    for strategy in builtin_strategies():
        registry.register(strategy)
    if load_external:
        registry.load_entry_points()
    return registry
