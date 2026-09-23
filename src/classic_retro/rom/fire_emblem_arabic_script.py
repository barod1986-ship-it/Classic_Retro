"""Arabic translation of the *Fire Emblem: The Sacred Stones* (USA) new-game opening.

Messages are indices of the game's message table: the world map's narration
of Magvel (0x8DB) and the throne room of Castle Renais, from the soldier's
report to King Fado's last words (0x903..0x906). For each one the original is
identified by the SHA-256 of its decoded bytes and by its command skeleton
(commands with their arguments, no text), so the translation can be checked
without the ROM and the ROM build can refuse a different script.

Translations are logical Unicode Arabic in the engine's bracket notation.
Commands keep their original order; only ``[LF]`` and ``[.]`` may move, and
``[CR][LF]`` stays one unit (the narration box skips the byte after ``[CR]``).

The legend shown before a new game is seven images, not messages; its Arabic
lines are drawn into new images (``engines.fire_emblem_legend``).
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.fire_emblem import split_notation
from classic_retro.engines.fire_emblem_arabic import TalkBox, fire_emblem_stream
from classic_retro.text.tokens import TokenStream


@dataclass(frozen=True, slots=True)
class FireEmblemArabicMessage:
    index: int
    speakers: str
    box: TalkBox
    source_sha256: str
    source_skeleton: tuple[bytes, ...]
    stream: TokenStream


def _skeleton(notation: str) -> tuple[bytes, ...]:
    pieces = split_notation(notation)
    if any(isinstance(piece, str) for piece in pieces):
        raise ValueError(f"a skeleton holds commands only: {notation!r}")
    return tuple(piece for piece in pieces if isinstance(piece, bytes))


def _message(
    index: int,
    speakers: str,
    box: TalkBox,
    source_sha256: str,
    skeleton: str,
    *lines: str,
) -> FireEmblemArabicMessage:
    return FireEmblemArabicMessage(
        index=index,
        speakers=speakers,
        box=box,
        source_sha256=source_sha256,
        source_skeleton=_skeleton(skeleton),
        stream=fire_emblem_stream("".join(lines), prefix=f"m{index:x}_"),
    )


def fire_emblem_arabic_messages() -> tuple[FireEmblemArabicMessage, ...]:
    """Magvel's narration, then the fall of Castle Renais' throne room."""
    return (
        _message(
            0x8DB,
            "Narrator",
            TalkBox.WORLD_MAP,
            "b6b83ffa3f5e924a678bed03c49d16d25330f1c531972a5978571aa54465a168",
            "[A][A][A][A][CR][LF][BreakTalk][A][CR][LF][BreakTalk][A][CR][LF][BreakTalk][A]"
            "[CR][LF][BreakTalk][A][CR][LF][BreakTalk][A][CR][LF][BreakTalk][A][BreakTalk][A]"
            "[CR][LF][BreakTalk][A][A][CR][LF][BreakTalk][A][BreakTalk][A][BreakTalk][A]"
            "[BreakTalk][A][BreakTalk][A][BreakTalk][A][BreakTalk][A][CR][LF][BreakTalk][A]"
            "[BreakTalk][A][BreakTalk][X]",
            "القارة ماغفيل.[A][LF]",
            "منذ نحو 800 عام، ساد سلام هادئ[.][LF]",
            "في غياب الظلام الرهيب.[.][A][LF]",
            "وتوارثت الأجيال الأحجار المقدسة[LF]",
            "جيلا بعد جيل.[.][A][LF]",
            "وقامت الأمم على قوتها[.][LF]",
            "وإرثها.[.][A][CR][LF]",
            "[BreakTalk]مملكة رينيه، يحكمها فادو،[LF]",
            "الملك المحارب الذي لا يضاهى.[A][CR][LF]",
            "[BreakTalk]مملكة فريليا، يحكمها هايدن،[LF]",
            "الملك الحكيم الموقر.[A][CR][LF]",
            "[BreakTalk]مملكة جيهانا، تحكمها إسمير،[LF]",
            "ملكة الكثبان البيضاء.[.][A][CR][LF]",
            "[BreakTalk]دولة راوستن الدينية، يحكمها مانسل،[.][LF]",
            "الإمبراطور المقدس.[.][A][CR][LF]",
            "[BreakTalk]إمبراطورية غرادو، يحكمها فيغارد،[LF]",
            "الإمبراطور الصامت الراسخ.[A][CR][LF]",
            "[BreakTalk]هذه الدول الخمس تحتضن قوة[LF]",
            "الأحجار المقدسة.[A][LF]",
            "[BreakTalk]وتنضم إليها جمهورية كاركينو[.][LF]",
            "التجارية الناشئة.[A][CR][LF]",
            "[BreakTalk]في زمن السلام هذا، صارت حكايات[LF]",
            "حروب الماضي أساطير،[A][LF]",
            "وتلاشت ذكريات فنون الظلام القديمة[.][LF]",
            "أو كادت.[A][CR][LF]",
            "[BreakTalk]نحن الآن في عام 803...[.][A][LF]",
            "[BreakTalk]وفي لحظة، باتت ماغفيل كلها[LF]",
            "مهددة بفاجعة لم يتوقعها أحد.[.][A][LF]",
            "[BreakTalk]فإمبراطورية غرادو، أكبر دول[.][LF]",
            "الأحجار المقدسة،[.][A][LF]",
            "[BreakTalk]غزت مملكة رينيه بأمر من[LF]",
            "الإمبراطور فيغارد.[A][LF]",
            "[BreakTalk]باغت الهجوم رينيه، حليفة غرادو القديمة،[LF]",
            "فعجزت عن إبداء أي مقاومة.[A][LF]",
            "[BreakTalk]تقدمت قوات غرادو بسرعة،[LF]",
            "تستولي على الأقاليم واحدا تلو الآخر.[A][LF]",
            "[BreakTalk]ومما زاد هموم الملك فادو أن ابنه،[.][LF]",
            "الأمير إفرايم، قد اختفى.[.][A][CR][LF]",
            "[BreakTalk]ويمضي زحف غرادو بجيوشها حتى[.][LF]",
            "أبواب قلعة رينيه نفسها.[A][LF]",
            "[BreakTalk]ستسقط رينيه...[.][LF]",
            "لا مفر من ذلك.[.][A][LF]",
            "[BreakTalk][X]",
        ),
        _message(
            0x903,
            "Soldier, Fado",
            TalkBox.BUBBLE,
            "0b2aa719098dab4e73e5c4c334c791bbf40f05c2f32c56c7611c434001ac811d",
            "[OpenMidLeft][LoadFace 51 01][OpenFarFarRight][LoadFace 6A 01][OpenFarFarRight]"
            "[MoveMidRight][OpenMidRight][A][CloseSpeechSlow][OpenMidRight][A][A][OpenMidLeft][A]"
            "[OpenMidRight][A][A][A][OpenMidLeft][ToggleMouthMove][ToggleMouthMove][A][A][X]",
            "[OpenMidLeft][LoadFace 51 01][OpenFarFarRight][LoadFace 6A 01]",
            "[OpenFarFarRight][MoveMidRight]",
            "[OpenMidRight]مولاي، أحمل إليك أنباء سيئة.[A][CloseSpeechSlow]",
            "[OpenMidRight]لقد اخترق العدو بوابة القلعة.[A][LF]",
            "قوات الإمبراطور فيغارد صارت[.][LF]",
            "داخل أسوار القلعة.[.][A]",
            "[OpenMidLeft]فهمت.[.][A]",
            "[OpenMidRight]لقد سقطت الحامية.[A][LF]",
            "انقطع اتصالنا بالأمير إفرايم،[LF]",
            "ولا أمل لنا في عون من رجاله.[.][A][LF]",
            "مولاي، ماذا نفعل؟[A]",
            "[OpenMidLeft][ToggleMouthMove]...[.][ToggleMouthMove]وماذا عسانا نفعل؟[A][LF]",
            "مر رجالك بأن يلقوا[.][LF]",
            "أسلحتهم.[A][X]",
        ),
        _message(
            0x904,
            "Eirika, Fado, Seth",
            TalkBox.BUBBLE,
            "a0602e19bbd6e7d17fa4424f6ce2e38c8087c7ee041f76299d8bee0fd0ea5fa7",
            "[OpenMidLeft][LoadFace 51 01][OpenMidRight][LoadFace 02 01][OpenMidRight][MoveRight]"
            "[OpenRight][ToggleMouthMove][ToggleMouthMove][A][OpenMidLeft][A][A][OpenRight][A]"
            "[OpenMidLeft][A][CloseSpeechSlow][OpenMidLeft][A][OpenFarRight][LoadFace 04 01]"
            "[OpenFarRight][A][OpenMidLeft][A][A][OpenFarRight][A][A][OpenMidLeft][A][A][A]"
            "[CloseSpeechSlow][OpenMidLeft][A][ToggleMouthMove][ToggleMouthMove][A][SendToBack]"
            "[OpenRight][MoveRight][OpenRight][A][A][OpenMidLeft][A][X]",
            "[OpenMidLeft][LoadFace 51 01][OpenMidRight][LoadFace 02 01]",
            "[OpenMidRight][MoveRight]",
            "[OpenRight]أبي[ToggleMouthMove]...[.][ToggleMouthMove][A]",
            "[OpenMidLeft]إيريكا.[.][A][LF]",
            "هل ترتدين السوار[.][LF]",
            "الذي أهديتك إياه؟[A]",
            "[OpenRight]نعم، إنه معي هنا.[A]",
            "[OpenMidLeft]حسنا.[.][A][CloseSpeechSlow]",
            "[OpenMidLeft]سيث.[.][A]",
            "[OpenFarRight][LoadFace 04 01][OpenFarRight]نعم يا مولاي؟[A]",
            "[OpenMidLeft]خذ إيريكا واتجها إلى فريليا.[A][LF]",
            "الملك هايدن رجل شريف،[LF]",
            "وأثق أنه سيحميكما.[A]",
            "[OpenFarRight]سمعا وطاعة.[.][A][LF]",
            "وماذا عنك يا مولاي؟[.][A]",
            "[OpenMidLeft]أنا؟ سأبقى هنا.[A][LF]",
            "لطالما عددنا غرادو من أعز[.][LF]",
            "حلفائنا، والآن يهاجموننا؟[.][A][LF]",
            "لا بد أن أعرف السبب.[A][CloseSpeechSlow]",
            "[OpenMidLeft]هل أنا المسؤول عن هذا بطريقة ما؟[LF]",
            "هل أخطأت في قيادتي؟[A][LF]",
            "رينيه أمانة في عنقي[.][ToggleMouthMove]... [ToggleMouthMove]كيف[.][LF]",
            "خذلتها هكذا؟[.][A][SendToBack]",
            "[OpenRight][MoveRight]",
            "[OpenRight]أبي، لا يمكنك البقاء! لا يجوز![A][LF]",
            "إن بقيت هنا، فسأبقى معك![A]",
            "[OpenMidLeft]اذهب الآن يا سيث! انطلق![.][LF]",
            "خذها إلى بر الأمان![.][A][X]",
        ),
        _message(
            0x905,
            "Eirika, Seth",
            TalkBox.BUBBLE,
            "5ab13694d94b39b927cf71b7d8b2e67dd3518f20cc5ea3a1eddb30cb7f55afe8",
            "[OpenRight][LoadFace 02 01][OpenFarRight][LoadFace 04 01][OpenRight][A][SendToBack]"
            "[OpenFarRight][A][X]",
            "[OpenRight][LoadFace 02 01][OpenFarRight][LoadFace 04 01]",
            "[OpenRight]أبي![.][A][SendToBack]",
            "[OpenFarRight]سامحيني،[.][LF]",
            "يا صاحبة السمو.[A][X]",
        ),
        _message(
            0x906,
            "Fado",
            TalkBox.BUBBLE,
            "a73122ba03a03b93af51c2809002388bf0edd942dddeb941dfb8dbfa3523d9ed",
            "[OpenMidLeft][LoadFace 51 01][OpenMidLeft][ToggleMouthMove][ToggleMouthMove][A][X]",
            "[OpenMidLeft][LoadFace 51 01]",
            "[OpenMidLeft]إفرايم، إيريكا[.][ToggleMouthMove]...[.][ToggleMouthMove][LF]",
            "يجب أن تنجوا.[.][A][X]",
        ),
    )


@dataclass(frozen=True, slots=True)
class FireEmblemArabicSubtitle:
    """One legend image (``gOpSubtitleGfxLut`` entry): its English text and Arabic lines."""

    index: int
    english: str
    lines: tuple[str, ...]


def fire_emblem_arabic_legend() -> tuple[FireEmblemArabicSubtitle, ...]:
    """The legend of the Sacred Stones, one entry per subtitle image."""
    return (
        FireEmblemArabicSubtitle(
            0,
            "In an age long past... evil flooded over the land. Creatures awash in the dark "
            "tide ran wild, pushing mankind to the brink of annihilation.",
            (
                "في زمن غابر...",
                "طغى الشر على الأرض.",
                "وعاثت مخلوقات المد المظلم",
                "فسادا، ودفعت البشرية",
                "إلى حافة الفناء.",
            ),
        ),
        FireEmblemArabicSubtitle(
            1,
            "In its despair, mankind appealed to the heavens, and from a blinding light came hope.",
            ("وفي يأسها، تضرعت البشرية", "إلى السماء، فانبثق الأمل", "من نور يخطف الأبصار."),
        ),
        FireEmblemArabicSubtitle(2, "The Sacred Stones", ("الأحجار المقدسة",)),
        FireEmblemArabicSubtitle(
            3,
            "These five glorious treasures held the power to dispel evil.",
            ("هذه الكنوز الخمسة المجيدة", "حملت قوة تبدد الشر."),
        ),
        FireEmblemArabicSubtitle(
            4,
            "The hero Grado and his warriors used the Sacred Stones to combat evil's "
            "darkness. They defeated the Demon King and sealed his soul away within the "
            "stones.",
            (
                "استخدم البطل غرادو ومحاربوه",
                "الأحجار المقدسة لمحاربة ظلام الشر،",
                "فهزموا ملك الشياطين،",
                "وحبسوا روحه",
                "داخل الأحجار.",
            ),
        ),
        FireEmblemArabicSubtitle(
            5,
            "With the darkness imprisoned, peace returned to Magvel.",
            ("وبعد أن غدا الظلام سجينا،", "عاد السلام إلى ماغفيل."),
        ),
        FireEmblemArabicSubtitle(
            6, "But this peace would not last...", ("لكن هذا السلام لم يكن ليدوم...",)
        ),
    )
