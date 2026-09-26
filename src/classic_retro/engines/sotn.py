"""Text engine of *Castlevania: Symphony of the Night* (PlayStation): cutscene scripts.

A stage's dialogue is a script its cutscene entity reads a byte at a time
(the sotn-decomp decompilation names it ``EntityCutscene``). Bytes below
``GLYPH_START`` are commands, followed by their arguments:

- ``00`` ends the cutscene and ``01`` ends a line;
- ``02 xx`` sets the typewriter's speed (frames a glyph), ``03 xx`` waits
  ``xx`` frames;
- ``04`` hides the box, ``05 cc ss`` shows a portrait (its palette and side)
  and draws the speaker's name, ``06`` ends a speaker's dialogue, ``07 xx yy``
  opens the box at (``xx``, ``yy``) and ``08`` closes it;
- ``09 hh ll`` plays sound ``hh << 4 | ll`` (a voice), ``0A`` waits for it to
  end and ``0B`` waits on the sound driver too; ``0D`` does nothing;
- ``0C`` and ``0F`` take an address (a list of events, a jump) in four bytes,
  which the routine reads as ``value = value << 4 | byte`` (sotn-decomp's
  ``script_word`` writes them); ``0E``, a switch, takes one and a table;
- ``10 xx`` waits for flag ``xx`` and ``11 xx`` sets it: the flags start the
  animations the text is timed with; ``12`` stops the events;
- ``13`` loads a portrait's image (an address and a slot) and ``14 hh ll``
  plays a sound.

Every other byte is a glyph: code ``c`` is the cell of the game's 8x8 font at
x ``896 + 2 * (c % 16)``, y ``240 + 8 * (c // 16)`` in VRAM (in halfwords),
which the routine copies into the line it types, the line ``n`` of the box at
row ``384 + 12 * n``; ``20`` is a space that only moves the pen 8 pixels.

A *message* is what one speaker says: the glyphs and the commands inside the
text (``01``, ``02``, ``03``, ``10`` and ``11``) that follow the ``0A``
waiting for the voice, up to the next other command. Its notation writes the
glyphs as ASCII text, ``01`` as a line end and the others as ``{speed N}``,
``{wait N}``, ``{wait-flag N}`` and ``{flag N}`` (decimal).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode

END = 0x00
LINE_BREAK = 0x01
SET_SPEED = 0x02
SET_WAIT = 0x03
WAIT_FOR_SOUND = 0x0A
WAIT_FOR_FLAG = 0x10
SET_FLAG = 0x11
# The commands and how many argument bytes each takes (``0E`` is followed by
# its table and does not occur in the scripts this engine reads).
ARGUMENTS = {
    0x00: 0, 0x01: 0, 0x02: 1, 0x03: 1, 0x04: 0, 0x05: 2, 0x06: 0, 0x07: 2,
    0x08: 0, 0x09: 2, 0x0A: 0, 0x0B: 0, 0x0C: 4, 0x0D: 0, 0x0F: 4, 0x10: 1,
    0x11: 1, 0x12: 0, 0x13: 5, 0x14: 2,
}  # fmt: skip
# The first byte the routine draws: ST0's reads 00..14 as commands.
GLYPH_START = 0x15
# The commands a message's text holds, by notation name.
TEXT_COMMANDS = {
    SET_SPEED: "speed",
    SET_WAIT: "wait",
    WAIT_FOR_FLAG: "wait-flag",
    SET_FLAG: "flag",
}
_BY_NAME = {name: code for code, name in TEXT_COMMANDS.items()}
_NOTATION_COMMAND = re.compile(r"\{([a-z-]+) (\d{1,3})\}")


class SotnEngineAdapter(EngineAdapter):
    id = "ps1.sotn-cutscene"
    display_name = "Castlevania: Symphony of the Night cutscene scripts"
    platform_ids = ("ps1",)


@dataclass(frozen=True, slots=True)
class SotnCommand:
    """A command with its argument bytes."""

    code: int
    arguments: bytes = b""

    def __post_init__(self) -> None:
        if self.code not in ARGUMENTS or len(self.arguments) != ARGUMENTS[self.code]:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{self.data.hex(' ')} is not a command"
            )

    @property
    def data(self) -> bytes:
        return bytes((self.code,)) + self.arguments

    @property
    def is_line_break(self) -> bool:
        return self.code == LINE_BREAK

    @property
    def in_text(self) -> bool:
        """A command a message's text holds."""
        return self.is_line_break or self.code in TEXT_COMMANDS

    @property
    def notation(self) -> str:
        if self.is_line_break:
            return "\n"
        name = TEXT_COMMANDS.get(self.code)
        if name is None:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"{self.data.hex(' ')} is not text"
            )
        return f"{{{name} {self.arguments[0]}}}"


Piece = str | SotnCommand


def split_script(data: bytes, start: int = 0, end: int | None = None) -> list[tuple[int, Piece]]:
    """Glyph runs and commands of ``data[start:end]``, each with its offset."""
    end = len(data) if end is None else end
    pieces: list[tuple[int, Piece]] = []
    run_start = None
    index = start
    while index < end:
        code = data[index]
        if code >= GLYPH_START:
            if run_start is None:
                run_start = index
            index += 1
            continue
        if run_start is not None:
            pieces.append((run_start, data[run_start:index].decode("latin-1")))
            run_start = None
        count = ARGUMENTS.get(code)
        if count is None or index + 1 + count > end:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unreadable command {code:02X} at {index:#x}"
            )
        pieces.append((index, SotnCommand(code, bytes(data[index + 1 : index + 1 + count]))))
        index += 1 + count
    if run_start is not None:
        pieces.append((run_start, data[run_start:end].decode("latin-1")))
    return pieces


def script_messages(data: bytes, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """The messages of a script: each one's (start, end) offsets.

    A message follows a ``0A`` and runs over glyphs and text commands.
    """
    messages: list[tuple[int, int]] = []
    opened: int | None = None
    pieces = split_script(data, start, end)
    for number, (offset, piece) in enumerate(pieces):
        is_text = isinstance(piece, str) or piece.in_text
        if opened is not None and not is_text:
            messages.append((opened, offset))
            opened = None
        if isinstance(piece, SotnCommand) and piece.code == WAIT_FOR_SOUND:
            following = pieces[number + 1][0] if number + 1 < len(pieces) else None
            opened = following
    if opened is not None:
        messages.append((opened, len(data) if end is None else end))
    return [(first, last) for first, last in messages if first is not None and first < last]


def message_pieces(data: bytes) -> tuple[Piece, ...]:
    """A message's bytes as text runs and text commands."""
    pieces = tuple(piece for _, piece in split_script(data))
    for piece in pieces:
        if isinstance(piece, SotnCommand) and not piece.in_text:
            raise ClassicRetroError(
                ErrorCode.UNSUPPORTED_CONTROL_CODE,
                f"{piece.data.hex(' ')} is not a command of a message's text",
            )
    return pieces


def text_notation(data: bytes) -> str:
    return "".join(
        piece if isinstance(piece, str) else piece.notation for piece in message_pieces(data)
    )


def parse_notation(text: str) -> tuple[Piece, ...]:
    """Notation as text runs and commands."""
    pieces: list[Piece] = []
    run: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\n":
            command = SotnCommand(LINE_BREAK)
            index += 1
        elif character == "{":
            match = _NOTATION_COMMAND.match(text, index)
            if match is None or match.group(1) not in _BY_NAME or int(match.group(2)) > 0xFF:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE, f"Unknown command at {text[index:]!r}"
                )
            command = SotnCommand(_BY_NAME[match.group(1)], bytes((int(match.group(2)),)))
            index = match.end()
        elif character == "}":
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "Unmatched '}'")
        else:
            run.append(character)
            index += 1
            continue
        if run:
            pieces.append("".join(run))
            run.clear()
        pieces.append(command)
    if run:
        pieces.append("".join(run))
    return tuple(pieces)


def notation_skeleton(pieces: Iterable[Piece]) -> tuple[str, ...]:
    """The commands in order, without the line ends: a translation lays its own lines out."""
    return tuple(
        piece.notation
        for piece in pieces
        if isinstance(piece, SotnCommand) and not piece.is_line_break
    )


def command_skeleton(data: bytes) -> tuple[str, ...]:
    return notation_skeleton(message_pieces(data))


def encode_latin(text: str) -> bytes:
    """A text run in the game's own font: printable ASCII, the space included."""
    if any(not 0x20 <= ord(character) < 0x7F for character in text):
        raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, f"The SOTN font has no {text!r}")
    return text.encode("ascii")


def pieces_bytes(pieces: Iterable[Piece]) -> bytes:
    """The bytes of text runs in the game's font and commands: ``message_pieces`` reversed."""
    return b"".join(
        encode_latin(piece) if isinstance(piece, str) else piece.data for piece in pieces
    )
