"""Arabic translation of the Final Fantasy VI Advance (USA) new-game opening.

Messages are dialogue-bank indices. For each one the original is identified by
the SHA-256 of its bytes and by its command skeleton (commands with their
arguments, no text), so the translation can be checked without the ROM and
the ROM build can refuse a different script.

Pages keep the original commands; only the layout commands (newline, centre)
may move. Arabic lines are 16 pixels high, so a window holds two lines and the
window-less narration band four. A page that needs a third Arabic line in a
window is split with an inserted page of the kind the message already uses: a
timed ``PAUSE, PAGE`` in the automatic cutscene, a ``KEY_PAGE`` in button
dialogue. Message 9 is shown in the top band without a window frame, which has
the window's two-line height.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.ff6a import (
    CENTER,
    CLOSE,
    END,
    KEY_PAGE,
    NARRATION,
    NEWLINE,
    PAGE,
    PAUSE,
    TIMED_CLOSE,
)
from classic_retro.engines.ff6a_arabic import Ff6aLayout, ff6a_command, ff6a_newline
from classic_retro.text.tokens import TextToken, Token, TokenStream


@dataclass(frozen=True, slots=True)
class Ff6aArabicMessage:
    index: int
    layout: str
    source_sha256: str
    source_skeleton: tuple[int, ...]
    stream: TokenStream


@dataclass(frozen=True, slots=True)
class _Command:
    codes: tuple[int, ...]
    inserted: bool = False


NL = _Command((NEWLINE,))
PAGE_BREAK = _Command((PAGE, NEWLINE))
KEY = _Command((KEY_PAGE,))
CENTERED = _Command((CENTER,))
NARRATED = _Command((NARRATION,))
CLOSED = _Command((CLOSE,))
ENDED = _Command((END,))


def _pause(value: int) -> _Command:
    return _Command((PAUSE, value))


def _timed_close(value: int) -> _Command:
    return _Command((TIMED_CLOSE, value))


def _inserted_timed_page(value: int) -> _Command:
    return _Command((PAUSE, value, PAGE, NEWLINE), inserted=True)


INSERTED_KEY_PAGE = _Command((KEY_PAGE,), inserted=True)

# Waits are VALUE + n: n * 15 frames.
_2S, _4S, _6S = 0x14C, 0x154, 0x15C
_NARRATION_HOLD = 0x243


def _message(
    index: int,
    layout: str,
    source_sha256: str,
    source_skeleton: tuple[int, ...],
    *parts: str | _Command,
) -> Ff6aArabicMessage:
    tokens: list[Token] = []
    for number, part in enumerate(parts):
        token_id = f"m{index}_{number}"
        if isinstance(part, str):
            tokens.append(TextToken(part))
        elif part.codes == (NEWLINE,) and not part.inserted:
            tokens.append(ff6a_newline(token_id))
        else:
            tokens.append(ff6a_command(token_id, *part.codes, inserted=part.inserted))
    return Ff6aArabicMessage(
        index, layout, source_sha256, source_skeleton, TokenStream(tuple(tokens))
    )


_NARRATION_SKELETON = (NARRATION, TIMED_CLOSE, _NARRATION_HOLD, CLOSE, END)

D = Ff6aLayout.DIALOGUE
N = Ff6aLayout.NARRATION


def ff6a_arabic_messages() -> tuple[Ff6aArabicMessage, ...]:
    """The new-game opening: the narration, the cliff above Narshe and the way to the mines."""
    return (
        _message(
            6,
            N,
            "dccdea3d4fe048963130f0f1490f09f1e78c021802eca95ba5042b545001a270",
            _NARRATION_SKELETON,
            NARRATED,
            CENTERED,
            "حرب السحرة القديمة...",
            NL,
            CENTERED,
            "وحين خمدت نيرانها أخيرا،",
            NL,
            CENTERED,
            "لم يبق من العالم سوى هيكل متفحم.",
            NL,
            CENTERED,
            "حتى قوة السحر نفسها ضاعت...",
            _timed_close(_NARRATION_HOLD),
            CLOSED,
            ENDED,
        ),
        _message(
            7,
            N,
            "03f40d12ea79b3e8bc7e2fcf250d57acb0775dccb79f0f2671c965da7e4c9624",
            _NARRATION_SKELETON,
            NARRATED,
            CENTERED,
            "وفي الألف عام التي تلت ذلك،",
            NL,
            CENTERED,
            "حل الحديد والبارود والمحركات البخارية",
            NL,
            CENTERED,
            "محل السحر، وعادت الحياة رويدا رويدا",
            NL,
            CENTERED,
            "إلى الأرض القاحلة...",
            _timed_close(_NARRATION_HOLD),
            CLOSED,
            ENDED,
        ),
        _message(
            8,
            N,
            "cb883421c0199aeb976045b09844f94dad9d108c307eda3646de5002c85baeaf",
            _NARRATION_SKELETON,
            NARRATED,
            CENTERED,
            "لكن ثمة الآن من يسعى",
            NL,
            CENTERED,
            "إلى إيقاظ سحر العصور الغابرة،",
            NL,
            CENTERED,
            "واستخدام قوته المرعبة وسيلة",
            NL,
            CENTERED,
            "لغزو العالم بأسره...",
            _timed_close(_NARRATION_HOLD),
            CLOSED,
            ENDED,
        ),
        _message(
            9,
            D,
            "d52ebd77c4d6659c2883cfcc818e94eb4006e919ff26613a373a9902eb990e62",
            (TIMED_CLOSE, 0x16E, CLOSE, END),
            CENTERED,
            "...هل يعقل أن يكون أحد بهذه الحماقة",
            NL,
            CENTERED,
            "ليكرر ذلك الخطأ؟",
            _timed_close(0x16E),
            CLOSED,
            ENDED,
        ),
        _message(
            1,
            D,
            "722b527d4b2e091c0fe2204ab84de674fc195090f0c217a260c67867003b30bc",
            (PAUSE, _2S, PAGE, PAUSE, _6S, CLOSE, END),
            "ويدج: ها هي المدينة...",
            _pause(_2S),
            PAGE_BREAK,
            "بيغز: يصعب تصديق أنهم وجدوا هناك إسبر",
            NL,
            "متجمدا منذ ألف عام، منذ حرب السحرة...",
            _pause(_6S),
            CLOSED,
            ENDED,
        ),
        _message(
            2,
            D,
            "bf748dba87a9cbf09fd145b295a22c113a521166f30ace03f3b74aea5dbc5078",
            (PAUSE, _4S, PAGE, PAUSE, _2S, PAGE, PAUSE, _6S, CLOSE, END),
            "بيغز: هه! على الأرجح أنها مجرد",
            NL,
            "مطاردة عبثية أخرى...",
            _pause(_4S),
            PAGE_BREAK,
            "ويدج: لا أدري...",
            _pause(_2S),
            PAGE_BREAK,
            "ما كانوا ليسمحوا لنا باستخدامها",
            NL,
            "لو لم يكونوا واثقين من صحة المعلومات.",
            _pause(_6S),
            CLOSED,
            ENDED,
        ),
        _message(
            3,
            D,
            "bec16f289739fd338b54a4dd809c588f59c17c9bb8f659a26bb9515d969f354b",
            (PAUSE, _2S, PAGE, PAUSE, _6S, CLOSE, END),
            "بيغز: آه، صحيح... ساحرتنا.",
            _pause(_2S),
            PAGE_BREAK,
            "سمعت أنها أحرقت خمسين من جنودنا",
            NL,
            "بدروع الماجيتك في ثلاث دقائق...",
            _inserted_timed_page(_4S),
            "أمر يقشعر له البدن، أليس كذلك؟",
            _pause(_6S),
            CLOSED,
            ENDED,
        ),
        _message(
            4,
            D,
            "42b28e1c492b875e92b432d03628da0978469fd98e5cd9704f7e2980d3d29534",
            (PAUSE, _4S, PAGE, PAUSE, _4S, CLOSE, END),
            "ويدج: اطمئن. مع ذلك الشيء على رأسها",
            NL,
            "ليست سوى دمية بلا عقل.",
            _pause(_4S),
            PAGE_BREAK,
            "لن تتنفس الفتاة حتى",
            NL,
            "ما لم نأمرها بذلك.",
            _pause(_4S),
            CLOSED,
            ENDED,
        ),
        _message(
            5,
            D,
            "b9b16ff054c040024bf2069954736f5c64dd6bf347ee4594d8d0798cbb2e98d7",
            (PAUSE, _4S, CLOSE, END),
            "ويدج: سنقترب من جهة الشرق.",
            NL,
            "تحركوا!",
            _pause(_4S),
            CLOSED,
            ENDED,
        ),
        _message(
            11,
            D,
            "ae6c6750a5de320b230763cac24ebc8384ffa81348c2cb5a4655ee71597d5f29",
            (END,),
            "ويدج: الفتاة في المقدمة. ولا تضيعوا",
            NL,
            "الوقت مع الرعاع! تذكروا سبب مجيئنا. هيا بنا!",
            ENDED,
        ),
        _message(
            12,
            D,
            "60b7c633a730889bb6100cf76beec7e5ccf3af7224718080e684e4ed48a32f80",
            (END,),
            "ويدج: لا بد أن الإسبر هنا.",
            NL,
            "لنواصل البحث!",
            ENDED,
        ),
        _message(
            13,
            D,
            "7fc97350d5dda51267f9011d5a38c6312c442b75670f99e9e56102d54288c832",
            (END,),
            "حارس: دروع ماجيتك إمبراطورية؟!",
            NL,
            "حتى نارشي لم تعد آمنة!",
            ENDED,
        ),
        _message(
            14,
            D,
            "fa1f3ded32235330c5945fccb0964efcdab41a0a52779c331445bb21e580aeb7",
            (END,),
            "حارس: ليس للإمبراطورية أي شأن",
            NL,
            "في هذا المكان!",
            ENDED,
        ),
        _message(
            15,
            D,
            "a03f1ba1f8efe7d5893e3a5cf2063277929f8bb58d536c9626c8891819793b50",
            (END,),
            "حارس: من أجل نارشي!",
            ENDED,
        ),
        _message(
            16,
            D,
            "7e1a812ca1d6680ebf87327abc376556062f13a72e0a11b4fa0d0087f26a22e0",
            (KEY_PAGE, END),
            "ويدج: حسب مصدرنا، عثروا على الإسبر",
            NL,
            "المتجمد في منجم جديد كانوا يحفرونه...",
            KEY,
            "لا بد أنه هنا.",
            ENDED,
        ),
        _message(
            17,
            D,
            "721124866cea71b55b2fa044616469efb30da3ffa45cacf6011282fe56ae043f",
            (END,),
            "بيغز: سأتولى الأمر. تراجعوا!",
            ENDED,
        ),
        _message(
            18,
            D,
            "d9bf37251c8c49acbfaabfb60e404cf40932e0ef24f0d21f17e3d8444c596dee",
            (END,),
            "حارس: لقد حاصرناهم الآن!",
            ENDED,
        ),
        _message(
            19,
            D,
            "51f8daa817ff5d6867cfc81daafa564e8fa54ca79dc36820dc64f1642fcd6edb",
            (END,),
            "حارس: دافعوا عن المناجم!",
            ENDED,
        ),
        _message(
            20,
            D,
            "28d066cb6eb529615f7cf9d9b42f6702d42b0a185c94680b52afdbfc9e89e0ec",
            (END,),
            NL,
            CENTERED,
            "إنه مقفل.",
            ENDED,
        ),
    )
