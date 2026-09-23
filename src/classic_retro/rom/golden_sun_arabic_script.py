"""Arabic translation of the Golden Sun (USA, Europe) new-game opening.

Messages are string indices of the game's text bank: the storm night in Vale,
from Dora waking Isaac to Kyle sending him to the plaza (3666..3686). For
each one the original is identified by the SHA-256 of its codes and by its
command skeleton (commands with their arguments, no text), so the translation
can be checked without the ROM and the ROM build can refuse a different
script.

The hero's name (``{11 01}``) is typed by the player in Latin letters; it
stays a runtime command and is drawn left to right inside the Arabic line.
Pages keep the original commands; only newlines may move, and the em dash
command may be dropped (Arabic punctuation replaces it). Messages ending in
``QUESTION`` are followed by the game's Yes/No menu, which stays English.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.golden_sun import (
    CHARACTER_NAME,
    DASH,
    KEY_END,
    NEWLINE,
    QUESTION,
)
from classic_retro.engines.golden_sun_arabic import golden_sun_command, golden_sun_newline
from classic_retro.text.tokens import TextToken, Token, TokenStream


@dataclass(frozen=True, slots=True)
class GoldenSunArabicMessage:
    index: int
    speaker: str
    source_sha256: str
    source_skeleton: tuple[int, ...]
    stream: TokenStream


@dataclass(frozen=True, slots=True)
class _Command:
    codes: tuple[int, ...]


NL = _Command((NEWLINE,))
NAME = _Command((CHARACTER_NAME, 0x01))
ENDED = _Command((KEY_END,))
ASKED = _Command((QUESTION,))

_NAME_END = (CHARACTER_NAME, 0x01, KEY_END)
_NAME_QUESTION = (CHARACTER_NAME, 0x01, QUESTION)


def _message(
    index: int,
    speaker: str,
    source_sha256: str,
    source_skeleton: tuple[int, ...],
    *parts: str | _Command,
) -> GoldenSunArabicMessage:
    tokens: list[Token] = []
    for number, part in enumerate(parts):
        token_id = f"m{index}_{number}"
        if isinstance(part, str):
            tokens.append(TextToken(part))
        elif part.codes == (NEWLINE,):
            tokens.append(golden_sun_newline(token_id))
        else:
            tokens.append(golden_sun_command(token_id, *part.codes))
    return GoldenSunArabicMessage(
        index, speaker, source_sha256, source_skeleton, TokenStream(tuple(tokens))
    )


def golden_sun_arabic_messages() -> tuple[GoldenSunArabicMessage, ...]:
    """The storm night: Dora wakes Isaac, Kyle sends them to the plaza."""
    return (
        _message(
            3666,
            "Dora",
            "bbfa0920a7eb12a2d889b3dbcb05712e32cdea87d220c71ace15b3bc5fecd9b4",
            _NAME_END,
            NAME,
            "، استيقظ!",
            ENDED,
        ),
        _message(
            3667,
            "Dora",
            "6fd995502b2ee2bed11fbbbb0488b78f4e0a8ed24f5e34a8b8548cf6e63f0ca4",
            (KEY_END,),
            "أرجوك يا عزيزي، استيقظ!",
            ENDED,
        ),
        _message(
            3668,
            "Dora",
            "c67d60eac8187f15a2318ba754621ba62aecee19474567949f49f270163e8da6",
            (KEY_END,),
            "صخرة جبل أليف",
            NL,
            "على وشك السقوط!",
            ENDED,
        ),
        _message(
            3669,
            "Dora",
            "3845da9d9e49e3c902973e94a82becb50add70dbbdda4d55453185e60ed0951a",
            (CHARACTER_NAME, 0x01, DASH, KEY_END),
            "هيا يا ",
            NAME,
            ".",
            NL,
            "علينا أن نذهب الآن!",
            ENDED,
        ),
        _message(
            3670,
            "Dora",
            "c0d59f691b220d597740f30ff02683714be385801ef0bcefad26ccba75ffcd04",
            _NAME_END,
            NAME,
            "! لقد نسيت شيئا ما!",
            ENDED,
        ),
        _message(
            3671,
            "Dora",
            "35b0c6d65696f5b1d684745e9f0f416cc2b734b05d41e083169623fd056dc8a8",
            (KEY_END,),
            "المطر ينهمر في الخارج!",
            NL,
            "لا تخرج من دون سترتك!",
            ENDED,
        ),
        _message(
            3672,
            "Dora",
            "4eb459c57eadf6fce06b4efeac8a66cf656e7d923ba01d55cb2a857136abae8f",
            (QUESTION,),
            "هل أخذت كل ما تحتاج إليه؟",
            ASKED,
        ),
        _message(
            3673,
            "Dora",
            "e5421b7d806209493200af16e269e3aaa28939410a54c89eb4be3caad2322341",
            (KEY_END,),
            "آسفة، لكن لا وقت لدينا...",
            NL,
            "سيكون عليك أن تتركه خلفك.",
            ENDED,
        ),
        _message(
            3674,
            "Dora",
            "637b2131490143e91df8ee6353db242fb3a34e66cbfa2b62991be871a63c3626",
            _NAME_END,
            "أحسنت يا ",
            NAME,
            ".",
            NL,
            "ما يضيع من المتاع يعوض،",
            NL,
            "أما الحياة فلا تعوض.",
            ENDED,
        ),
        _message(
            3675,
            "Kyle",
            "9e934fe806579fa4e2c714a0aa9f8f448c0dc8a09288efe04ff5a3137497afd6",
            _NAME_END,
            NAME,
            "، دورا، أسرعا!",
            NL,
            "قد تسقط الصخرة",
            NL,
            "في أي لحظة!",
            ENDED,
        ),
        _message(
            3676,
            "Dora",
            "5f5bf3edb7f48bcc3d7c0d63da336a86cf01485cbaa82019e9127fe869cefa9b",
            (KEY_END,),
            "كايل... هل سيتمكنون",
            NL,
            "من إيقاف الصخرة؟",
            ENDED,
        ),
        _message(
            3677,
            "Kyle",
            "af7be25495c6936dc318eb588c11a4732185e35bee51c254118247c116806b6d",
            (KEY_END,),
            "لا أظن ذلك...",
            NL,
            "ليس لوقت طويل على أي حال...",
            ENDED,
        ),
        _message(
            3678,
            "Kyle",
            "f38d5ded2c728c0b0296d21bcaf34be6fb5777f87629ba1e234054ab1e0871f9",
            (KEY_END,),
            "اذهبا أنتما أولا",
            NL,
            "واحتميا في الساحة.",
            ENDED,
        ),
        _message(
            3679,
            "Dora",
            "7ba5f219987f456c86236a5153ee3d9ef6496911adc7eb119e919ab04d292838",
            (KEY_END,),
            "ألن تأتي معنا؟",
            ENDED,
        ),
        _message(
            3680,
            "Kyle",
            "8fe28ef2f913445c1d37a54ab523c206bacef5f5221b0814d90c3a0eefd5b0df",
            (KEY_END,),
            "علي أن أساعد في إجلاء",
            NL,
            "بقية أهل القرية.",
            ENDED,
        ),
        _message(
            3681,
            "Dora",
            "f6e9d53c2f3509bfe94f25cb7e01c35d86a7934c0d98893b9787d3ea428e164c",
            (KEY_END,),
            "دعني أساعدك يا كايل!",
            ENDED,
        ),
        _message(
            3682,
            "Kyle",
            "945c5ca6b09c984fc5287faf1a87483b935d1c3499954c098a6552ded977d70b",
            _NAME_END,
            "الأمر بالغ الخطورة يا دورا.",
            NL,
            "أرجوك، اعتني جيدا",
            NL,
            "بابننا ",
            NAME,
            "!",
            ENDED,
        ),
        _message(
            3683,
            "Kyle",
            "699908eebfad2c3c0d8c9aa661842846aeedb9a4002dd3fc100e1b0e9b6ccdf2",
            _NAME_END,
            NAME,
            " كبير بما يكفي",
            NL,
            "ليصل إلى الساحة وحده.",
            ENDED,
        ),
        _message(
            3684,
            "Kyle",
            "cce7955d6dc9272566f3b0b9c3b109fa6c3958712e972f1cb355510640926bbf",
            _NAME_QUESTION,
            "تستطيع أن تجد طريقك بنفسك،",
            NL,
            "أليس كذلك يا ",
            NAME,
            "؟",
            ASKED,
        ),
        _message(
            3685,
            "Kyle",
            "fb7c7c3f5a70eb61dc04b6003ffab3d6d1692d5c2e46623a1126dbff323b7acb",
            _NAME_QUESTION,
            "لقد صرت كبيرا الآن",
            NL,
            "يا ",
            NAME,
            ". لم لا تذهب وحدك؟",
            ASKED,
        ),
        _message(
            3686,
            "Kyle",
            "7a0b1e1299bb0ca3619a2ab438168dc379170a3c5b612bd236f3cb692c185d63",
            (DASH, KEY_END),
            "أنت تعرف الطريق...",
            NL,
            "اتجه جنوبا لتصل إلى الساحة.",
            NL,
            "انتبه لنفسك!",
            ENDED,
        ),
    )
