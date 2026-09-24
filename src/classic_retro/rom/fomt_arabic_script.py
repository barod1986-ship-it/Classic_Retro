"""Arabic translation of the *Harvest Moon: Friends of Mineral Town* (USA) opening.

A new game starts, after the naming screens, on the farm:

- Thomas, the mayor, stops the stranger on the late owner's farm, hears that
  the newcomer knew him, tells of the will, and asks how they met (event
  script 867, strings 0-4);
- the flashback of that summer: the family's trip to the country, the child
  lost and found by the old farmer, the invitation to his farm, the girl who
  wakes the child, the farewell and the promise to write (a story scene: 23
  strings and five speaker names, reached through the literal pools of its
  code);
- Thomas again: the letters, the farm handed over, and the next day (script
  867, strings 5-9).

For each string the original is pinned by its address (the script's string
index, or the story string's address and every literal that points to it),
the SHA-256 of its bytes and its command skeleton (``{wait}``, ``{clear}``,
``{name}`` in order; line ends excluded), so the translation can be checked
without the ROM and the ROM build can refuse a different script.

Translations are logical Unicode Arabic in the engine's notation
(``engines.fomt``): ``\\n`` ends a line, ``{wait}`` waits for a key, ``{clear}``
empties the box and ``{name}`` is the player's name. They keep every command
of the original, in order; line ends may move (a fourth line scrolls the box,
so it follows a ``{wait}`` that shows the first).
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.fomt import Piece, PlaceholderStyle, command_skeleton, parse_notation

# The event script table: 1329 pointers to RIFF "SCR " files.
SCRIPT_TABLE = 0x080F89D4
SCRIPT_COUNT = 1329
# Thomas meets the newcomer on the farm: the first script of a new game.
OPENING_SCRIPT = 867
OPENING_SCRIPT_ADDRESS = 0x08379B58
OPENING_SCRIPT_SHA256 = "88efbaacbb70c89979a3fd63245256567cb444d8cde9f305122cc82d119ce393"
OPENING_SCRIPT_STRINGS = 10


@dataclass(frozen=True, slots=True)
class FomtArabicString:
    """A translated string: where the original is and what it must match."""

    key: str
    style: PlaceholderStyle
    # The script string's index, or None for a story string.
    index: int | None
    # The story string's address and the literals that point to it.
    address: int | None
    literals: tuple[int, ...]
    speaker: str
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation, self.style)


@dataclass(frozen=True, slots=True)
class FomtArabicName:
    """A speaker name of the story scene, for the name tag."""

    key: str
    address: int
    literals: tuple[int, ...]
    source_sha256: str
    arabic: str


def _skeleton(notation: str) -> tuple[str, ...]:
    return command_skeleton(parse_notation(notation, PlaceholderStyle.SCRIPT))


# key: (string index, speaker, SHA-256 of the original, its commands)
# fmt: off
_SCRIPT_SOURCES: dict[str, tuple[int, str, str, str]] = {
    "thomas_owner": (
        0, "Thomas", "8e1ebdd021637057095942e1da05ca9e16d0e7af152c4f625d7bde3d46134df3",
        "{wait}{clear}{wait}",
    ),
    "thomas_knew": (
        1, "Thomas", "dbe2bdaf42537f124f3a29fb4d774efceff2a9ad1f2a2d4032a080af1541704c",
        "{wait}{clear}{wait}",
    ),
    "thomas_will": (
        2, "Thomas", "03058916fa98a3267f888a10b807189c878851fad88aaa4247207bfb062f545f",
        "{wait}{clear}{wait}{clear}{name}{wait}{clear}{wait}",
    ),
    "thomas_you": (
        3, "Thomas", "dd2446b6f1ef4a4048d56f397b951c8a7d4b63536f7bc6941e97d15f3881fb34",
        "{name}{wait}",
    ),
    "thomas_tell": (
        4, "Thomas", "8855ea0186941ab8f8ea76212526bb75934bf9ffbb5754e75aa615b803072fc8",
        "{wait}",
    ),
    "thomas_letters": (
        5, "Thomas", "1358415f6a0491114aecc887852a50cc8151bf75b3bd00510e811ca0a6073bd4",
        "{wait}{clear}{wait}",
    ),
    "thomas_yours": (
        6, "Thomas", "ed641b07136108306735c5d8f785316519a969620bff8672dcc316d18eb71adf",
        "{wait}{clear}{wait}",
    ),
    "thomas_great": (
        7, "Thomas", "b375b1f56642b72c53c9ae0162a56b00364106215f1fe06017beb0ccc0991323",
        "{wait}",
    ),
    "thomas_proud": (
        8, "Thomas", "72e5e7baa1ab294631f84b0bda514277abec6d941d90b4d8f6dea9ac118d1672",
        "{wait}",
    ),
    "next_day": (
        9, "narration", "7ede1584931be5ce9ca72a23d1c052ea95cdfebaa11bee88583fa66132a7887c",
        "{wait}",
    ),
}

# key: (address, literals, speaker, SHA-256 of the original, its commands)
_STORY_SOURCES: dict[str, tuple[int, tuple[int, ...], str, str, str]] = {
    "mother_trip": (
        0x080FB23C, (0x0805F78C,), "mother",
        "c1731f254b9877336c52025a5b29530ca5c3a3555e9921ff7fa912f36725ccd3",
        "{clear}{name}{wait}",
    ),
    "father_fishing": (
        0x080FB284, (0x0805F7C8,), "father",
        "318122fdd373f9ad57c433785ba75132fb55061de94d8af54353fd59b8ba337c",
        "{clear}{wait}",
    ),
    "mother_lost": (
        0x080FB2D0, (0x0805F804,), "mother",
        "e9b64d734feea34fa50ca567d27aef523d28bf1b9d67879e212702a48c18d88d",
        "{clear}{name}{wait}{clear}{name}{wait}",
    ),
    "father_what": (
        0x080FB2F4, (0x0805F828,), "father",
        "cab5e888e9de55af88d0363a01edeb6387005f33ae92d5c19922f5b2da7e1dba",
        "{clear}{wait}",
    ),
    "old_man_crying": (
        0x080FB308, (0x0805F840,), "old_man",
        "9b41a4db371c5a043f1d9aa654047c3c373b7a53060798450c022f3566b1f890",
        "{clear}{wait}{wait}{wait}",
    ),
    "mother_thanks": (
        0x080FB398, (0x0805F86C,), "mother",
        "6f77cb4a4a1eae138bdcdaf6a328786c328a2a4f5bdd1272833d86dea0fa13e8",
        "{clear}{wait}",
    ),
    "father_city": (
        0x080FB3CC, (0x0805F8A8,), "father",
        "5bc6f732e0a9c72566bef8a6e0ada928b8dd51b6caf85c9575b7656fe5f40a35",
        "{clear}{wait}",
    ),
    "old_man_farm": (
        0x080FB420, (0x0805F8E4,), "old_man",
        "53a9ace9bce0fe69f57d2ad0e33ab08afd70036a5bbda9d2cea380a7e6d46305",
        "{clear}{wait}{clear}{wait}",
    ),
    "father_mean_it": (
        0x080FB46C, (0x0805F920,), "father",
        "da9071078f22d8911cd12a8e460c472f1f1181d44583cfd36baf21bd538993d6",
        "{clear}{wait}",
    ),
    "old_man_alone": (
        0x080FB484, (0x0805F95C,), "old_man",
        "6a6d7bc32909a16e162d9935088ff019d220481efd794d9406bce4b6d910cf43",
        "{clear}{wait}",
    ),
    "mother_great": (
        0x080FB4D4, (0x0805F980,), "mother",
        "b89b9159d70a4bdebc513b46922fe72a2ecf61ae27ab998f820674f2cf200801",
        "{clear}{name}{wait}{wait}",
    ),
    "voice_hey": (
        0x080FB520, (0x0805F9B0,), "voice",
        "97c005d9726399b1771d64ce687ab7506d11d179182dfdd58f90079dc0c6162a",
        "{clear}{wait}{clear}{wait}{clear}{wait}",
    ),
    "child_start": (
        0x080FB534, (0x0805F9C8,), "child",
        "39c67c9b9d8fd34b63327582749e476b778c1a344428a9ba7c4cf88c892950b1",
        "{clear}{wait}",
    ),
    "girl_quiet": (
        0x080FB544, (0x0805F9F8,), "girl",
        "5c26130fba79ee3048171aaaf05a7eee17635a2ea53b1aa36ea36501e631c7eb",
        "{clear}{wait}",
    ),
    "girl_play": (
        0x080FB578, (0x0805FA34,), "girl",
        "27c1acbd9a5b646b09ed72f7fe7b16dbbdcec4e4c68411369fac54712592cda1",
        "{clear}{wait}{wait}",
    ),
    "girl_no_fun": (
        0x080FB5D4, (0x0805FA58,), "girl",
        "d7f543303344202ea68d910ea8a1f617e067629f94c4750f4e45b32acec55d6f",
        "{clear}{wait}{clear}{wait}",
    ),
    "old_man_fun": (
        0x080FB634, (0x0805FA88,), "old_man",
        "8de1f55cc43423733ed1110401c3e1f41ccbade718b7ad32d9125504606ed630",
        "{clear}{wait}{clear}{wait}{clear}{wait}",
    ),
    "old_man_letter": (
        0x080FB6C0, (0x0805FAC4,), "old_man",
        "78286f5dcc071f8005d02243c676f657cd044edf613bb1b27522a18ad2769912",
        "{clear}{wait}",
    ),
    "old_man_address": (
        0x080FB710, (0x0805FAE8,), "old_man",
        "740cecbe6c5438071314a6a9c37f512620f7d97a4350a04aed66c6a3b4c0fdc0",
        "{clear}{wait}",
    ),
    "girl_leaving": (
        0x080FB738, (0x0805FB18,), "girl",
        "93de7cb4232ed2e9a9bdb9704414e64adc7eda9d896fc5e81f5d57fe64c9891a",
        "{clear}{wait}",
    ),
    "girl_come_back": (
        0x080FB754, (0x0805FB54,), "girl",
        "be944a85798cad62545e32fdc7f1a387bc5ca0308255707c816f110866dd873d",
        "{clear}{wait}{clear}{wait}",
    ),
    "old_man_friend": (
        0x080FB7A0, (0x0805FB80,), "old_man",
        "e092bfbe08b3fac36c966d63d06774d671273e7e9f4d4f62ef9896d761c4d839",
        "{clear}{wait}",
    ),
    "old_man_waiting": (
        0x080FB7F0, (0x0805FBB0,), "old_man",
        "1ea4626efca4d10c2960e7c2cd29634135f38b19ee137b732632b42aba46e2dc",
        "{clear}{wait}",
    ),
}

# key: (address, literals, SHA-256 of the original)
_NAME_SOURCES: dict[str, tuple[int, tuple[int, ...], str]] = {
    "mother": (
        0x080FB234, (0x0805F788, 0x0805F800, 0x0805F868, 0x0805F97C),
        "86605cac7f0646867f62ff0f03ca6af9dc3ce860f772a8673cdb6cd34dffc3b1",
    ),
    "father": (
        0x080FB27C, (0x0805F7C4, 0x0805F824, 0x0805F8A4, 0x0805F91C),
        "bcc1fbae6cef9aa27524da4b78a0dc70ba5c9c7a876ba947e463f80ea8f7f7bc",
    ),
    "old_man": (
        0x080FB300,
        (0x0805F83C, 0x0805F8E0, 0x0805F958, 0x0805FA84, 0x0805FAC0, 0x0805FAE4, 0x0805FB7C,
         0x0805FBAC),
        "b064cabb8bd63bba6cb65093729300dfecb5ead546e8d222fcabb57980bba845",
    ),
    "voice": (
        0x080FB51C, (0x0805F9AC,),
        "a03b221c6c6eae7122ca51695d456d5222e524889136394944b2f9763b483615",
    ),
    "girl": (
        0x080FB53C, (0x0805F9F4, 0x0805FA30, 0x0805FA54, 0x0805FB14, 0x0805FB50),
        "1499a166709402ecf2f32ccfabd7d7797a0168a3ee00828aba8ec39f6aa0f14d",
    ),
}
# fmt: on

_ARABIC: dict[str, str] = {
    # Script 867: Thomas and the newcomer.
    "thomas_owner": (
        "مهلا! صاحب هذه المزرعة\nتوفي منذ مدة.{wait}{clear}"
        "لا يمكنك أن تدخل إلى هنا\nهكذا وكأن المكان مكانك!{wait}"
    ),
    "thomas_knew": "ماذا؟ أكنت تعرفه؟{wait}{clear}ولم تكن تعلم\nبأنه قد مات...؟{wait}",
    "thomas_will": (
        "لقد مات منذ...{wait}{clear}"
        "منذ ستة أشهر تقريبا على ما أظن.\nوحين كنت أرتب بيته\nوجدت وصيته.{wait}{clear}"
        "وقد كتب فيها: أترك مزرعتي\nإلى {name}.{wait}{clear}"
        "لذا سأعتني أنا بالمزرعة\nإلى أن يظهر صاحب هذا الاسم.{wait}"
    ),
    "thomas_you": "ماذا؟ هل تقول إنك أنت\n{name}؟{wait}",
    "thomas_tell": "هلا أخبرتني كيف تعرفت\nعلى ذلك الرجل العجوز...؟{wait}",
    "thomas_letters": (
        "إذن كنتما تتراسلان، ها؟{wait}{clear}"
        "ولما توقف عن الرد على رسائلك\nجئت لتطمئن عليه، صحيح؟{wait}"
    ),
    "thomas_yours": "بما أنه أوصى لك بالمزرعة\nفهي لك إن أردتها.{wait}{clear}فما رأيك؟{wait}",
    "thomas_great": "رائع! من اليوم فصاعدا\nهذا المكان ملكك!{wait}",
    "thomas_proud": "لن يكون الأمر سهلا، ولكن\nإن اجتهدت فستنجز عملا\nيجعله فخورا بك.{wait}",
    "next_day": "\nوفي اليوم التالي...{wait}",
    # The flashback.
    "mother_trip": "{clear}ما رأيك يا {name}؟\nألست سعيدا لأنك جئت\nفي هذه الرحلة؟{wait}",
    "father_fishing": (
        "{clear}وأنا أيضا سعيد بهذه العطلة.\nهيا، ما رأيك أن نذهب\nلصيد السمك في النهر؟{wait}"
    ),
    "mother_lost": "{clear}{name}؟{wait}{clear}يا إلهي! لا أجد\n{name}!{wait}",
    "father_what": "{clear}ماذا...؟{wait}",
    "old_man_crying": (
        "{clear}مرحبا يا بني.\nلماذا تبكي؟\nهل أضعت طريقك؟{wait}"
        "\nما هذا؟ هل هذا رقم هاتفكم\nالمكتوب على حقيبتك؟{wait}"
        "\nهيا نتصل بوالديك.{wait}"
    ),
    "mother_thanks": "{clear}شكرا جزيلا لك\nلأنك ساعدتنا في العثور على ابننا!{wait}",
    "father_city": (
        "{clear}نحن نعيش في المدينة، لكننا\nأردنا أن نري ابننا الريف\nفي هذه الرحلة.{wait}"
    ),
    "old_man_farm": (
        "{clear}أهكذا إذن؟{wait}{clear}في هذه الحالة، لم لا تأتون\nلتقضوا بضعة أيام\nفي مزرعتي؟{wait}"
    ),
    "father_mean_it": "{clear}هل تعني ذلك حقا؟{wait}",
    "old_man_alone": ("{clear}بالتأكيد! أنا أعيش وحيدا،\nفلن تزعجوا أحدا.\nوستسعدني صحبتكم.{wait}"),
    "mother_great": (
        "{clear}أليس هذا رائعا يا\n{name}؟{wait}\nستكون لديك مزرعة كاملة\nتلعب فيها!{wait}"
    ),
    "voice_hey": "{clear}يـ...{wait}{clear}يا...{wait}{clear}يا أنت.{wait}",
    "child_start": "{clear}!{wait}",
    "girl_quiet": "{clear}كنت صامتا جدا\nحتى ظننتك ميتا!{wait}",
    "girl_play": "{clear}هذا ممتاز. كنت أبحث\nعن أحد ألعب معه.{wait}\nأظن أنك ستفي بالغرض.{wait}",
    "girl_no_fun": (
        "{clear}ليس من الممتع أن تجلس\nهكذا دون أن تقول شيئا!{wait}{clear}"
        "لم لا تحدثني عن نفسك؟{wait}"
    ),
    "old_man_fun": (
        "{clear}هل استمتعت بوقتك؟{wait}{clear}"
        "أنا استمتعت كثيرا برفقتك.\nفليس لي أحفاد\nكما تعلم...{wait}{clear}"
        "حسنا، عليك أن تذهب الآن.\nوداعا!...{wait}"
    ),
    "old_man_letter": "{clear}هل لك أن تكتب لهذا العجوز\nرسالة من حين لآخر...؟{wait}",
    "old_man_address": "{clear}حقا؟\nإذن هذا عنواني.{wait}",
    "girl_leaving": "{clear}هل سترحل بهذه السرعة؟{wait}",
    "girl_come_back": (
        "{clear}إن رحلت فسأشعر بالملل\nوالوحدة من جديد...{wait}{clear}يجب أن تعود، اتفقنا؟{wait}"
    ),
    "old_man_friend": "{clear}يبدو أنك كسبت صديقة!\nهذا سبب آخر للعودة\nعلى ما أظن.{wait}",
    "old_man_waiting": "{clear}سأنتظر رسالتك...{wait}",
}

_NAMES: dict[str, str] = {
    "mother": "الأم",
    "father": "الأب",
    "old_man": "العجوز",
    "voice": "؟؟؟",
    "girl": "الفتاة",
}


def fomt_arabic_strings() -> tuple[FomtArabicString, ...]:
    """Every translated string: the script's in index order, then the story's."""
    if set(_SCRIPT_SOURCES) | set(_STORY_SOURCES) != set(_ARABIC):
        raise ValueError("every pinned FoMT string needs exactly one translation")
    strings = [
        FomtArabicString(
            key=key,
            style=PlaceholderStyle.SCRIPT,
            index=index,
            address=None,
            literals=(),
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=_skeleton(skeleton),
            notation=_ARABIC[key],
        )
        for key, (index, speaker, digest, skeleton) in _SCRIPT_SOURCES.items()
    ]
    strings += [
        FomtArabicString(
            key=key,
            style=PlaceholderStyle.STORY,
            index=None,
            address=address,
            literals=literals,
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=_skeleton(skeleton),
            notation=_ARABIC[key],
        )
        for key, (address, literals, speaker, digest, skeleton) in _STORY_SOURCES.items()
    ]
    return tuple(strings)


def fomt_arabic_names() -> tuple[FomtArabicName, ...]:
    if set(_NAME_SOURCES) != set(_NAMES):
        raise ValueError("every pinned FoMT speaker name needs exactly one translation")
    return tuple(
        FomtArabicName(key, address, literals, digest, _NAMES[key])
        for key, (address, literals, digest) in _NAME_SOURCES.items()
    )
