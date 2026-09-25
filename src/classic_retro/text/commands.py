"""Engine commands inside a translation.

A translation keeps the commands of the original message: waits, colours, page
breaks, names. Engines pass them to the text model as ordered inline tokens,
each carrying the command's codes in hex (``args["codes"]``). An engine may let
a translation add a page break; such a token is marked ``inserted``. Every
engine holds a translation's commands against the original's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import InlineToken, TokenKind, TokenMovement

_Command = TypeVar("_Command")


def command_token(
    token_id: str,
    kind: TokenKind,
    codes: str,
    *,
    name: str | None = None,
    inserted: bool = False,
) -> InlineToken:
    """An ordered command carrying ``codes`` (hex, space separated)."""
    args: dict[str, str | bool] = {"codes": codes}
    if inserted:
        args["inserted"] = True
    return InlineToken(id=token_id, kind=kind, movement=TokenMovement.ORDERED, name=name, args=args)


def command_codes(token: InlineToken, engine: str) -> tuple[int, ...]:
    codes = token.args.get("codes")
    if not isinstance(codes, str) or not codes:
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TOKEN, f"{engine} token {token.id} carries no command codes"
        )
    return tuple(int(code, 16) for code in codes.split())


def is_inserted(token: InlineToken) -> bool:
    """Whether the translation added this command (a page break) to the original's."""
    return bool(token.args.get("inserted", False))


def require_same_commands(
    engine: str,
    source: Sequence[_Command],
    target: Sequence[_Command],
    notation: Callable[[Sequence[_Command]], str],
) -> None:
    """The translation's commands (``target``) must equal the original's."""
    if tuple(target) != tuple(source):
        raise ClassicRetroError(
            ErrorCode.TOKEN_ORDER_VIOLATION,
            f"{engine} commands differ from the original: {notation(source)} != {notation(target)}",
        )
