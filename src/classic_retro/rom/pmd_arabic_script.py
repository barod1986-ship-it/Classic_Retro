"""Arabic translation of the *Pokémon Mystery Dungeon: Red Rescue Team* (USA) personality test.

A new game starts with the personality test: six floating messages on a
black screen (from the welcome to the start of the interview), then eight of 55
questions picked at random, each in the dialogue box with its answers in a
menu (one more question follows an answer of the alien invasion), then the
gender question. Every one of those strings is translated here: 158 strings
behind 206 pointers (the yes and no answers are shared by most questions).

For each string the original is pinned by its ROM address, the SHA-256 of its
bytes and its command skeleton (commands in order, line ends excluded), and
every pointer to it (a scan of the image finds no other) is listed, so the
translation can be checked without the ROM and the ROM build can refuse a
different script.

The Arabic lives in ``classic_retro/translations/pmd-red.json``: logical
Unicode Arabic in the engine's notation
(``engines.pmd``): ``{CENTER_ALIGN}``, ``{WAIT_PRESS}`` and ``{EXTRA_MSG}``
keep their original order, and line ends (``\\n``) may move.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.pmd import Piece, notation_skeleton, parse_notation
from classic_retro.engines.pmd_arabic import PmdTextBox
from classic_retro.localization.translations import TranslationSet, builtin_translation_set

FLOATING = PmdTextBox.FLOATING
DIALOGUE = PmdTextBox.DIALOGUE
MENU = PmdTextBox.MENU


@dataclass(frozen=True, slots=True)
class PmdArabicString:
    key: str
    box: PmdTextBox
    source_address: int
    references: tuple[int, ...]
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


# key: (box, original string, pointers to it, SHA-256 of the original, its commands)
# fmt: off
_SOURCES: dict[str, tuple[PmdTextBox, int, tuple[int, ...], str, str]] = {
    "intro.welcome": (FLOATING, 0x0826E1F4, (0x0826E034,), "bf00c829f599eec77d3d162c4a1d9980da39b03037bcc6fe60eeec412f30e424", "{CENTER_ALIGN}"),
    "intro.portal": (FLOATING, 0x0826E1B8, (0x0826E044,), "968a93538552eafe41c8d522ea7eee10ad8cee151cc16cd418b5cf95e4d7c7df", "{CENTER_ALIGN}{CENTER_ALIGN}"),
    "intro.questions": (FLOATING, 0x0826E16C, (0x0826E054,), "faef9ded3ec61abe9ad313d5a9d991ff1aa9b7b51aaabf92e498a2331ca907aa", "{CENTER_ALIGN}{CENTER_ALIGN}"),
    "intro.sincerely": (FLOATING, 0x0826E144, (0x0826E064,), "ffae90e88e53dd1897288a6ffc7cfd9a34c0f7a57762067b3da24318e84b8bb3", "{CENTER_ALIGN}"),
    "intro.ready": (FLOATING, 0x0826E130, (0x0826E074,), "8e6143e5098561cc0876243abf3db1334557792f1cf5ce6ce3c3c089b217cd2e", "{CENTER_ALIGN}"),
    "intro.begin": (FLOATING, 0x0826E108, (0x0826E084,), "45a1d5184a31784f732fc7c40e862b7f24a8c9dafe5aa52426a7726c36c036d6", "{CENTER_ALIGN}{WAIT_PRESS}{CENTER_ALIGN}"),
    "hardy.1": (DIALOGUE, 0x080F00E4, (0x080F00D8,), "86a079576d9f630d08bf5c01f86ba7469f9c04339d03784386f90cba1bd85ac9", ""),
    "hardy.1.0": (MENU, 0x080F00CC, (0x080F0084,), "c1bf85f3d5695baf6fbd3cf9dcc4e50f63db2a235d1f948198ff4e446befdeac", ""),
    "hardy.1.1": (MENU, 0x080F00B8, (0x080F008C,), "2b793ae969f4bd13fe413ea4a5dd4cea91791950782f08a306301d56afe426a1", ""),
    "hardy.1.2": (MENU, 0x080F00A4, (0x080F0094,), "954f597b6bcdb32f1d5910a276ffcce087dd571c84c973e928d3c085c89e9269", ""),
    "hardy.2": (DIALOGUE, 0x080F0168, (0x080F015C,), "74deaeef04efdfdc6acabc5a7a43943fcd68b3fa9350c7b2a706c4bfe988e27c", ""),
    "yes": (MENU, 0x080F0154, (0x080F0134, 0x080F01B0, 0x080F05F8, 0x080F0AA4, 0x080F0B08, 0x080F0D7C, 0x080F0DE4, 0x080F0E3C, 0x080F1030, 0x080F1090, 0x080F10F8, 0x080F1944, 0x080F19B4, 0x080F1A20, 0x080F1A9C, 0x080F1B20, 0x080F1BA4, 0x080F1C00, 0x080F1C58, 0x080F1CC8, 0x080F1E10, 0x080F1E7C, 0x080F1EEC, 0x080F2114), "5f9a2b795615ba6a3d5455fd5624d773fbca5bcd16249c421fd37411dc9837da", ""),
    "no-space": (MENU, 0x080F014C, (0x080F013C,), "2de5cf832dbecaac9cd2d036e5d942bbde70835de9413a8558daae0697910eb3", ""),
    "hardy.3": (DIALOGUE, 0x080F01D8, (0x080F01CC,), "44c7da42c33031b4dd02d603389ce5e50aafaccdde0dcc9df7d755f4f476c3c1", ""),
    "no": (MENU, 0x080F01C8, (0x080F01B8, 0x080F0600, 0x080F0AAC, 0x080F0B10, 0x080F0D84, 0x080F0DEC, 0x080F0E44, 0x080F1038, 0x080F1098, 0x080F1100, 0x080F194C, 0x080F19BC, 0x080F1A28, 0x080F1AA4, 0x080F1B28, 0x080F1BAC, 0x080F1C08, 0x080F1C60, 0x080F1CD0, 0x080F1E18, 0x080F1E84, 0x080F1EF4, 0x080F211C), "38178a20b470cfd18299fb1593dd4ba706f1a83321dac051d01086efd8b7a96f", ""),
    "hardy.4": (DIALOGUE, 0x080F0280, (0x080F0274,), "530c37f5e3a80ca0cbea3ccda503883724b173d3015e9409895479d96a6c7726", ""),
    "hardy.4.0": (MENU, 0x080F026C, (0x080F0238,), "bf4f0df71685b1cac1cedfc05fc000c861ca07099baa1cdc45dbbb20b7bce2fe", ""),
    "hardy.4.1": (MENU, 0x080F0264, (0x080F0240,), "24b29ea88b006ad4c3ab2935201bb9a4a4aff9b84a4faf31cd78a42130388b22", ""),
    "a-little": (MENU, 0x080F0258, (0x080F0248, 0x080F0FB0), "2ba8e9895e7dcf44944b7a4dfb698b51a72b67b47ad5d8671e7031b7df366559", ""),
    "docile.1": (DIALOGUE, 0x080F0324, (0x080F0318,), "301ef57acd73da4376401e0d22e11f18c1bbd2fcbfe044bc248f0d8689724298", ""),
    "docile.1.0": (MENU, 0x080F030C, (0x080F02E8,), "29cb68fe012a6d7c03572e2a92d6e21fa675b93682a31c55debac5347ae6a87c", ""),
    "docile.1.1": (MENU, 0x080F0300, (0x080F02F0,), "38ae0cc06d3327bae0d1d65048da4036593ddba67d2811aed7a9f29e27a3bc42", ""),
    "docile.2": (DIALOGUE, 0x080F03D8, (0x080F03CC,), "5af7e8e2a0a41953583f0ff7026ed2b842f029d8833fd48286986ad2f0f169c4", ""),
    "docile.2.0": (MENU, 0x080F03B0, (0x080F0384,), "582dc35125434800317fb95af999b86cd884204aaddb235b37db75d031ea4d6c", ""),
    "docile.2.1": (MENU, 0x080F039C, (0x080F038C,), "922413b0b137e46ea1c0f176d7d6710dfa7255f6605bf7e48d90c06f2ef8e307", ""),
    "docile.3": (DIALOGUE, 0x080F04BC, (0x080F04B0,), "61677542cb0e2a59cd9f3960c7d93209019b608f53a5b8d80bd49098c2f21139", "{WAIT_PRESS}"),
    "docile.3.0": (MENU, 0x080F0494, (0x080F0440,), "e00e46c1b7f829918da0407d662e965002cda39b3679a9513e9945e223392ab4", ""),
    "docile.3.1": (MENU, 0x080F047C, (0x080F0448,), "e22eb23e6b9c96bdcbd2f90755c6318610f444b656960e39414cea9768db5b8a", ""),
    "docile.3.2": (MENU, 0x080F0460, (0x080F0450,), "8c72789ca22fee5d2dea4d5576e109dabcd3c3b800b904453533eeaf40f6c48d", ""),
    "docile.4": (DIALOGUE, 0x080F05AC, (0x080F05A0,), "4a1b8ae4c79642a83893595c745fd28f4f46ae92a5123c6996074f835db84492", ""),
    "docile.4.0": (MENU, 0x080F0584, (0x080F0540,), "77de793793f74dd99f380957a33682d2bd8260f1c8b08195b424174fe066e2b0", ""),
    "docile.4.1": (MENU, 0x080F0578, (0x080F0548,), "64cc1280e8418c2148b53641c6a1d0e274f8e44d143970afce721d51bde6b49f", ""),
    "docile.4.2": (MENU, 0x080F0560, (0x080F0550,), "192f86c510599ad930d7a8bb7ecead807d94951cacb9c835e061fb5ac2d8963f", ""),
    "brave.1": (DIALOGUE, 0x080F061C, (0x080F0610,), "fd9e1d4fbdc8a5ef080a60fe5286ed514e53d12bc1c4ac7d71a47e11438f7b1c", "{EXTRA_MSG}{WAIT_PRESS}{EXTRA_MSG}"),
    "brave.2a": (DIALOGUE, 0x080F0750, (0x080F0744,), "cbf620a1847470211b2dd2227619d2bd1e1d3b37ee89f132dbae42a428643e35", ""),
    "brave.2a.0": (MENU, 0x080F073C, (0x080F0708,), "8dd1682365c177bc77e5240141a5109e9c4ea47e3d40f55c7ba70c361a462631", ""),
    "brave.2a.1": (MENU, 0x080F0734, (0x080F0710,), "9c06e90c362f7d60e3e00dc88feb420d098caa3992d6e7f0c70ea0aa5c27aef4", ""),
    "brave.2a.2": (MENU, 0x080F0728, (0x080F0718,), "039159bf872250071d66d61a5ad529f5b476914760c943b372ddf063e413bb95", ""),
    "brave.3": (DIALOGUE, 0x080F0928, (0x080F091C,), "4c16051cafb0ac1d0d48f01a65b93c1c415662aa9b09ebf69940798414c1ecde", "{WAIT_PRESS}"),
    "brave.3.0": (MENU, 0x080F0908, (0x080F08DC,), "083f47dc6780282e1d8e72dda94a369444a2cb742f09b0cf4efab0603456a80a", ""),
    "brave.3.1": (MENU, 0x080F08F4, (0x080F08E4,), "39aa0cf43c318e13f2d6b976ffc4aa5730865c6d5579f9023aa778133159fea4", ""),
    "brave.4": (DIALOGUE, 0x080F0A38, (0x080F0A2C,), "9bf0a17d57de2cc9e603d49b2f943da17002b557e120b06789ea78513e470153", "{WAIT_PRESS}"),
    "brave.4.0": (MENU, 0x080F0A10, (0x080F09A4,), "a2f6de2fb30412c3ff6c21c3d5c2e2954f8b1c5bb214617c21399498f4646951", ""),
    "brave.4.1": (MENU, 0x080F09F8, (0x080F09AC,), "e12810de29ce0cb42af920416db7e85e8a9ce2a2ec70ea39c9a2711612952858", ""),
    "brave.4.2": (MENU, 0x080F09E4, (0x080F09B4,), "b5e67ed56d7455f7a065da7fe07a355f6cc57526a627484505aebede40c901f6", ""),
    "brave.4.3": (MENU, 0x080F09CC, (0x080F09BC,), "39940179efba01bde7efe16e9e0ff3157f303f498a3b063500a390cbee268457", ""),
    "jolly.1": (DIALOGUE, 0x080F0AC8, (0x080F0ABC,), "4774cbf0b660af3471b38034d19c17cc484205b3c24bd9029b87fbcd2e63defd", ""),
    "jolly.2": (DIALOGUE, 0x080F0B2C, (0x080F0B20,), "5558f349615ec0db530b052ceb78155d42ca81e092fcaeb3277306e033daf875", ""),
    "jolly.3": (DIALOGUE, 0x080F0BDC, (0x080F0BD0,), "2bbf6e1eb28a442bd7dcf838bb0598e956fb6fd0176176167e06f7f909ee0629", ""),
    "jolly.3.0": (MENU, 0x080F0BC4, (0x080F0B90,), "27ac186dc39982bea2e2a1d93aa90b740beaadd2b7d63482cf8493c21abf985a", ""),
    "jolly.3.1": (MENU, 0x080F0BBC, (0x080F0B98,), "2b9ccdb920114660d4440a44bef4b2f380124aa88904bacc41524973672d9829", ""),
    "jolly.3.2": (MENU, 0x080F0BB0, (0x080F0BA0,), "399cef407f9b2959fdcf14e4e000ba79dddea60fdb80a20d139578e00f501209", ""),
    "jolly.4": (DIALOGUE, 0x080F0CC8, (0x080F0CBC,), "8773a0388786878068d39ae4d3102e869d2c3fe3c93fdbd63f3770b5e024abec", "{EXTRA_MSG}{WAIT_PRESS}"),
    "jolly.4.0": (MENU, 0x080F0CA4, (0x080F0C44,), "5b579c2f4e50e782e670024dcad4798985d55b0e6e51eff395bcaaa14b77e74e", ""),
    "jolly.4.1": (MENU, 0x080F0C84, (0x080F0C4C,), "6c778179eba600e975fe0a147353731e00bda1573721c7aa9adfa911c73f397f", ""),
    "jolly.4.2": (MENU, 0x080F0C64, (0x080F0C54,), "ee860282edddf2e828d606164d6d1fcee60341b38b8b779923f472e9d75131ad", ""),
    "impish.1": (DIALOGUE, 0x080F0DA0, (0x080F0D94,), "0997cdf0c68ce6146d9d50ca8fe50fa94ae3cb6ec43fd04986377bdae27ffd05", ""),
    "impish.2": (DIALOGUE, 0x080F0E08, (0x080F0DFC,), "b4c0b31e0383cc3d2cf15fcf75e83a77913e7f1af61774504a214ea185011112", ""),
    "impish.3": (DIALOGUE, 0x080F0E60, (0x080F0E54,), "ab3b307fb499652afa6ef002ebf4913b597f557a8ab8ffd4aaaf9dbd91c5db5b", ""),
    "impish.4": (DIALOGUE, 0x080F0F48, (0x080F0F3C,), "3214873300b376539d27b4381b3d24f9f3a31966916f10c611255d247f3b9219", ""),
    "impish.4.0": (MENU, 0x080F0F24, (0x080F0EC4,), "c289dbe5941d3fc3c729a74c058aedb4f3438088887b55599b83f451159dc95a", ""),
    "impish.4.1": (MENU, 0x080F0F04, (0x080F0ECC,), "e5220dbaa7d9915eeb1ee1737c5b35811ac0a304fa1b5ddb31c88c900b9c2027", ""),
    "impish.4.2": (MENU, 0x080F0EE4, (0x080F0ED4,), "b1c2cead136eb0736d2ab27015e1f2d5007316db16635d2173a42997600625a4", ""),
    "naive.1": (DIALOGUE, 0x080F0FEC, (0x080F0FE0,), "5c6ba6828ad2b6141c156fe90cf664d38730bc0583a0d493b4461b50a7ad97a2", ""),
    "love-them": (MENU, 0x080F0FD4, (0x080F0FA8, 0x080F251C), "794f95d8a78be80aabbcecebbb4aa533f0dfe5f55e488a073f8d6aed1b9a3bce", ""),
    "naive.1.2": (MENU, 0x080F0FC8, (0x080F0FB8,), "a87f66ca86aa06f3a6bba7b48eb1ca6b19d1036c646c21c6e5c519462c02eb4c", ""),
    "naive.2": (DIALOGUE, 0x080F1054, (0x080F1048,), "b551ef33d0cf426caa5f47f07bee136ed7bf64f504287fa52a5e8a732526467a", ""),
    "naive.3": (DIALOGUE, 0x080F10B4, (0x080F10A8,), "fb0d9664319823bd418d4e44be1c8132260bb912146ebc08f32cd2ab2effd80e", ""),
    "naive.4": (DIALOGUE, 0x080F111C, (0x080F1110,), "8410a3fb0caf3eaa98a3494205e56b1d8157756ae23f929354e65253f4316fa9", ""),
    "timid.1": (DIALOGUE, 0x080F11F4, (0x080F11E8,), "e10ad60232eeb4ae0f5242c24877d78f019586896489eecffed5aaab76d29241", ""),
    "timid.1.0": (MENU, 0x080F11D8, (0x080F1180,), "2983c4e408c5dec091627b6e21ff74c8acd3e21dbcc42415bedb1f65815f5bd8", ""),
    "timid.1.1": (MENU, 0x080F11B8, (0x080F1188,), "a08ce96b7bafca817cf0049e7b412650ee4b77065edc872551f69ec1dd992e8a", ""),
    "timid.1.2": (MENU, 0x080F11A0, (0x080F1190,), "f6357e8b89e1fcbde0e93a40cbb3d4e23a0e181958b5546139b1218088d7a0cc", ""),
    "timid.2": (DIALOGUE, 0x080F1304, (0x080F12F8,), "32b78b0db62196743ced81426ffb357c96a1981fec128f308b62218b505b53aa", "{WAIT_PRESS}"),
    "timid.2.0": (MENU, 0x080F12F0, (0x080F1280,), "08b4793893cafd3135e990bbc288b5f609f7c4a2bd11c2a47eac69c13a00b9f5", ""),
    "timid.2.1": (MENU, 0x080F12E0, (0x080F1288,), "815d72ab7fd23adf2df0fbb134e762d85c684573eebf0d279f428d3970fd49ca", ""),
    "timid.2.2": (MENU, 0x080F12D0, (0x080F1290,), "19df148dec91b5d8492343e9a2e28c7280163ec2bb533a167686b272b7c97eac", ""),
    "timid.2.3": (MENU, 0x080F12C0, (0x080F1298,), "9c77fcba5ebdf7c399dcc720c88b7db159ca2d21e35d076434778a8a56b78243", ""),
    "timid.2.4": (MENU, 0x080F12B0, (0x080F12A0,), "6b0b47e4ab10270a0e0f6de30997ee31543fad0889723bce53a4d91b4fd6a986", ""),
    "timid.3": (DIALOGUE, 0x080F13D8, (0x080F13CC,), "6c9e71c9534cafeb315afa5eda3af11b92771691a2a9d5a371d0d9816bfc4f7c", "{WAIT_PRESS}"),
    "timid.3.0": (MENU, 0x080F13BC, (0x080F1388,), "f8f8ab3ca427161ca15ec78472c2db930373e1746c9a3e2c15e8ee4fce37a23b", ""),
    "timid.3.1": (MENU, 0x080F13B4, (0x080F1390,), "6ec77be0453ef91542c3d4bb33b326e606db2556911561d3aa058e432fc39037", ""),
    "timid.3.2": (MENU, 0x080F13A8, (0x080F1398,), "41e46faad95f851d608a67550b9e8d3d4aa934812e24d058e8d2e68d9bb44562", ""),
    "timid.4": (DIALOGUE, 0x080F14B0, (0x080F14A4,), "8eb316bf9ae65c0ffcdc1b41fb48f9f0900577d249f96f570be78bd9f80fab82", ""),
    "timid.4.0": (MENU, 0x080F1498, (0x080F1450,), "f001e3ed4df7e0ee926c05dc5b99752ded5ffd2127759b85641ddee3dd7d9e26", ""),
    "timid.4.1": (MENU, 0x080F1488, (0x080F1458,), "2ec5916fc5c25d6e4f30019c5c7b1539c2ace57d043079fcb476b0e1a8d11183", ""),
    "timid.4.2": (MENU, 0x080F1470, (0x080F1460,), "c06cf229b063703bbd07d2229b204d0b40b07c373b880638966dd1a10c4e1536", ""),
    "hasty.1": (DIALOGUE, 0x080F1568, (0x080F155C,), "d50c156a6f9c5c889e06a1bc8d01ddde1f49f079a9c81c67b780cd37052ba0c2", "{WAIT_PRESS}{WAIT_PRESS}"),
    "hasty.1.0": (MENU, 0x080F154C, (0x080F1504,), "38dc35adb81ab1d43bab86507364a22fe18609c9cbc157e2f96dadee6d168451", ""),
    "hasty.1.1": (MENU, 0x080F153C, (0x080F150C,), "d34c976acfae4fe486d4f340ae0c69ffc5f42c2539f041f3f469e24136cd198c", ""),
    "hasty.1.2": (MENU, 0x080F1524, (0x080F1514,), "1319e881eb2ff1187ac479b71af0c2b2166f89706748eedbe2f58040159829cc", ""),
    "hasty.2": (DIALOGUE, 0x080F1654, (0x080F1648,), "546d4d3152014dc67f668da3f8b893b4361ed6fa4fec710fbc4a30dd723982c7", "{WAIT_PRESS}"),
    "hasty.2.0": (MENU, 0x080F1638, (0x080F15FC,), "e605328a7d5d6aecfabe376b2d432ccd4ef221348d59b42379b8ced3af9d7cef", ""),
    "hasty.2.1": (MENU, 0x080F162C, (0x080F1604,), "74d5e9b0f3b64943a0f2141d72fad8f74cb4480a54acfda02b709544bb566065", ""),
    "hasty.2.2": (MENU, 0x080F161C, (0x080F160C,), "ba0820884699ecc8d5bd1733e1df40dc265f9063b54d3badf1cb3bd400c57f74", ""),
    "hasty.3": (DIALOGUE, 0x080F1730, (0x080F1724,), "3b3ad4bb8451b4ee4d9362ebbb27c3bb586354aa1967e9ac204b0e4f52a23972", ""),
    "hasty.3.0": (MENU, 0x080F1710, (0x080F16B8,), "11a2d120fc9f43674ec3acd334929481320ed2a89e9234b58f7cc5cce0a0603f", ""),
    "hasty.3.1": (MENU, 0x080F16F4, (0x080F16C0,), "d6d88f4980b325b4673bea98376ce13a77c5e9bd2f98b29bb1e84c25f1401953", ""),
    "hasty.3.2": (MENU, 0x080F16D8, (0x080F16C8,), "c0eea15a7c107bca68d93dd761f730683fc4521252d7ce814421cc8ec46e37c4", ""),
    "hasty.4": (DIALOGUE, 0x080F17F8, (0x080F17EC,), "9c736aac2ae399431c0b1339be3f185f641758aa99f63edc8a0150f012ccf424", ""),
    "hasty.4.0": (MENU, 0x080F17D8, (0x080F1794,), "be50c1e79eed5ec910d79293e3d7ec055152b30658d3b007f3121c2eef182d78", ""),
    "hasty.4.1": (MENU, 0x080F17C8, (0x080F179C,), "4248d35b82f05d179494f6035eed228f266648696d8f35ec2e42bb01cb665243", ""),
    "hasty.4.2": (MENU, 0x080F17B4, (0x080F17A4,), "29c5909298fe3bd2932b9003cdf4325469b77f1b7d549b06b55fd30e822e396e", ""),
    "sassy.1": (DIALOGUE, 0x080F18D8, (0x080F18CC,), "909a857b3ec0ff568358a7757d4524764ac260680aded95c4ef148bcaa449783", ""),
    "sassy.1.0": (MENU, 0x080F18BC, (0x080F187C,), "7c60acceafa32a0e61b42621c25524848c9d0108f71bc66ebe4f64ba71e70e1d", ""),
    "sassy.1.1": (MENU, 0x080F18A8, (0x080F1884,), "38356a2c2f9e067532eecc168aaf6ef967c526f8f42897367a195aa4c93b1661", ""),
    "sassy.1.2": (MENU, 0x080F189C, (0x080F188C,), "8f078ac7d3a57cb746f32b44a4bc9b6f48402c141b15aedea30c7d72a7d35522", ""),
    "sassy.2": (DIALOGUE, 0x080F1968, (0x080F195C,), "df1b8c8251db53aa5bc5be1c498e458f3b123231bd1643b43cf60cd8b915998e", ""),
    "sassy.3": (DIALOGUE, 0x080F19D8, (0x080F19CC,), "9669a5d8ad004ad35297ba9f249ed912248ae38b671c390d351d5ac9737b2056", ""),
    "sassy.4": (DIALOGUE, 0x080F1A44, (0x080F1A38,), "ea48e14c09c73afd30ac8a8ac7d914f85a43bc5c6b305cc6499fb237f963f0e1", ""),
    "calm.1": (DIALOGUE, 0x080F1AC0, (0x080F1AB4,), "0d89f08ece3d6393eb1098d6ccd1c267c8e8ba0ca002c96fe7581c5dbd2d5409", ""),
    "calm.2": (DIALOGUE, 0x080F1B44, (0x080F1B38,), "2c965b7827ace87cf611e6b632effc6d27688fcc6271050be49da80b59f8803c", ""),
    "calm.3": (DIALOGUE, 0x080F1BC8, (0x080F1BBC,), "ed7d012100ec3ec89aaa8a8f24920b9d1a4679a907313883957f75efa54b5319", ""),
    "calm.4": (DIALOGUE, 0x080F1C24, (0x080F1C18,), "62e9a6c7675a443f4ebedb836682880e0e21fb55df5ef693f22dd8bb68165bd2", ""),
    "relaxed.1": (DIALOGUE, 0x080F1C7C, (0x080F1C70,), "70d1316593e88308105a66929050ac812877938440251bb22c67cc1c6a451288", ""),
    "relaxed.2": (DIALOGUE, 0x080F1CEC, (0x080F1CE0,), "48241e33992c6c05d6d566867594cd1395595c759a46c7a5c013c6c090b10a31", ""),
    "relaxed.3": (DIALOGUE, 0x080F1DBC, (0x080F1DB0,), "a8353cfba20ba5431611fdb3daacdcd1ca46455ad54f482059ceb74d13f5bb91", ""),
    "relaxed.3.0": (MENU, 0x080F1D9C, (0x080F1D58,), "a5613c8376a82e1bd8918041103d949fcd7e1ac7caaf5b3089b1c458f1b2d90e", ""),
    "relaxed.3.1": (MENU, 0x080F1D90, (0x080F1D60,), "92bfc142eebd5f1184f364656d452e177cdb00a0c442cb74a7539f2b0a73da17", ""),
    "relaxed.3.2": (MENU, 0x080F1D78, (0x080F1D68,), "0d4ec0a5f18a30dd227b7118322204d7a4da70e6b490f3777d9619c7b6fbc1e4", ""),
    "relaxed.4": (DIALOGUE, 0x080F1E34, (0x080F1E28,), "aac8bdbf980283bf84839a02d156e40dd629d26f96c6dbd9b36447972468b722", ""),
    "lonely.1": (DIALOGUE, 0x080F1EA0, (0x080F1E94,), "d5c8355a755fa708f792ac3ef0c89e90a89972f0a920a53004c74ea357c49509", ""),
    "lonely.2": (DIALOGUE, 0x080F1F10, (0x080F1F04,), "85ac2406743a932a4e2643b26ed86f17c9ced9d9381159b92e41adb52d0ae2ee", ""),
    "lonely.3": (DIALOGUE, 0x080F1FC4, (0x080F1FB8,), "c1f49de6de7e069b6234e0b22d98be54c9cc8d31e57022bc955e8315335fe678", ""),
    "lonely.3.0": (MENU, 0x080F1FA8, (0x080F1F80,), "4a5628c1eedb9cb1047b5375d1eb07512ce64d898c9fa42edf8cd138449e2022", ""),
    "lonely.3.1": (MENU, 0x080F1F98, (0x080F1F88,), "9122d2f528d1757cf7b307cfb9ca804d711f0d45babd87911705cb7581dcfe4c", ""),
    "lonely.4": (DIALOGUE, 0x080F20AC, (0x080F20A0,), "1a46a9186a4dff5f6e22d72b83cfeb1714554bdfa77450b0becf447d62d65a59", ""),
    "lonely.4.0": (MENU, 0x080F2090, (0x080F2044,), "2872db84b92f85a20700af623cab6460be416d1e72c113f21d10189f870cddf8", ""),
    "lonely.4.1": (MENU, 0x080F2078, (0x080F204C,), "49cc40acbf952abcf30a4b0a1d34c35278785c64f49ae7fd98ea83d13fd5c0d0", ""),
    "lonely.4.2": (MENU, 0x080F2064, (0x080F2054,), "162592d828b35fa12488a8201e3ceec2d99501d0e42fb0d5391be981b9960ab5", ""),
    "quirky.1": (DIALOGUE, 0x080F2138, (0x080F212C,), "d8e4c740b1ad1115151ec6c2aefa480d37b6d2ee6b52450a8268546d31d15801", ""),
    "quirky.2": (DIALOGUE, 0x080F2210, (0x080F2204,), "4f020fbc3a5e13fb8260dfbdbbf6877885d1f01dddddd872ce475795a11e5cb4", ""),
    "quirky.2.0": (MENU, 0x080F21F0, (0x080F21A4,), "6a61829276ea1db42bfea137297d15096751d85dabea977af50a958beb8bf2de", ""),
    "quirky.2.1": (MENU, 0x080F21D8, (0x080F21AC,), "af152e113e8c6677ca2698cc9c4859d455531c8e20e108c708548a71cb03f88d", ""),
    "quirky.2.2": (MENU, 0x080F21C4, (0x080F21B4,), "87ea44730920fdc6c291e88313a478a635d971a9da4d8fc4ebc1b05a8f94c1e2", ""),
    "quirky.3": (DIALOGUE, 0x080F2310, (0x080F2304,), "b5ff2852cfae422067f230e66f8d945fefe72a75eef909518629cb9776634236", "{WAIT_PRESS}"),
    "quirky.3.0": (MENU, 0x080F22E8, (0x080F227C,), "b9aa03eaf5f1e4a4bc3a1e8b5a01af619db3378eb86dcd9766d834277cc3ac03", ""),
    "quirky.3.1": (MENU, 0x080F22D4, (0x080F2284,), "f369cf82520353cb2a480871eadb9dd6f6d2867c99803ba9b85f277530a6907c", ""),
    "quirky.3.2": (MENU, 0x080F22B4, (0x080F228C,), "18fd53818d0e6fe66e181e8ed6bbcb1e5a27c6649fa43e6a4d3b8889bc59f3ce", ""),
    "quirky.3.3": (MENU, 0x080F22A4, (0x080F2294,), "8a7b98075a92e7fada94cfa79edad0651a077644c862a9fb3d45da31c0e3556f", ""),
    "quirky.4": (DIALOGUE, 0x080F2408, (0x080F23FC,), "fafdb63704ff801189cacc53eeeca6d0ceebc909b35914ddcb56d9514c3afd95", ""),
    "quirky.4.0": (MENU, 0x080F23E8, (0x080F239C,), "a79af3bb6b57dab91127d5acfc121f90bbacc0d52db5d5ad4479692a817164ee", ""),
    "quirky.4.1": (MENU, 0x080F23D0, (0x080F23A4,), "e583479cf6b6fd3fe7c2a09600babccb9581d781d164cf567753a4ad553fa1d0", ""),
    "quirky.4.2": (MENU, 0x080F23BC, (0x080F23AC,), "90d79758e8998419794b39927fb7e37206562eb4cead29950ad19bd73f1fbaad", ""),
    "misc.1": (DIALOGUE, 0x080F24D4, (0x080F24C8,), "ee7ae39b0ededdf8927a6c6399274c98294ef4cb6a0e19544700842fc4489621", ""),
    "misc.1.0": (MENU, 0x080F24BC, (0x080F2494,), "fb8cccf04b2ef4831c0368715e539db4225a372b1ac312b31e2bf03ae89bfb02", ""),
    "misc.1.1": (MENU, 0x080F24AC, (0x080F249C,), "457ddca0974656cbf45209f44f7c015714185646e9833d38e688c3193fe6fefc", ""),
    "misc.2": (DIALOGUE, 0x080F2550, (0x080F2544,), "700a4c38c53c58fb49120026737e19d6f8951c1cb3c9092c0fba5f596b15e899", ""),
    "misc.2.1": (MENU, 0x080F2534, (0x080F2524,), "e3fbd627a713484d784b0d1b5a7967265e3fcaa2c7767a8f72b581c2345408da", ""),
    "misc.3": (DIALOGUE, 0x080F25DC, (0x080F25D0,), "4a657cd6b91d38a21b0fd7aa5f6310731d0e6fc92ca8b78c0dad4a110cdd143f", ""),
    "misc.3.0": (MENU, 0x080F25C8, (0x080F25A4,), "dd6da7de30ab683ccde7660ecf14e3e762c46c18644180cfcbf45cfa33968742", ""),
    "misc.3.1": (MENU, 0x080F25BC, (0x080F25AC,), "87f28569312c6f7c0d2f72722b6b355adf6aaa1f9eb5ac00480b656109eba77d", ""),
    "brave.2b": (DIALOGUE, 0x080F07E4, (0x080F07D8,), "0e8c014cf48ff663e43c18225ff32c23f9aeda416c3466a2a3090f676b328702", "{WAIT_PRESS}{EXTRA_MSG}{EXTRA_MSG}{EXTRA_MSG}{WAIT_PRESS}"),
    "brave.2b.0": (MENU, 0x080F07C0, (0x080F07A0,), "95c8670ab96ffaacc651fb4a60d12c77e7e4e83395494877ad0446615d919599", ""),
    "brave.2b.1": (MENU, 0x080F07B8, (0x080F07A8,), "f78d9bb769de02f1c309398d6ed3b061d7859760f168244c7a9b9e0d19d82e0b", ""),
    "gender": (DIALOGUE, 0x080F273C, (0x0803C8A8, 0x080F2758), "402a897fdaa788e997b053de1db84c8e2f1e21f1fa5ea041728434153ca03732", ""),
    "gender.boy": (MENU, 0x080F277C, (0x080F275C,), "5f7388e4ada5e32edb321f174ccafbd2e063f6abd3dd41ec5c98b2118be85730", ""),
    "gender.girl": (MENU, 0x080F2774, (0x080F2764,), "4e076745a37cd278549d42b212400b6989618985199f75e78505d33a79c5290f", ""),
}
# fmt: on

TARGET = "pmd-red"


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))


def pmd_arabic_strings(translations: TranslationSet | None = None) -> tuple[PmdArabicString, ...]:
    """The personality test's intro, then every question with its answers, then the gender."""
    texts = _texts(translations)
    return tuple(
        PmdArabicString(
            key=key,
            box=box,
            source_address=source,
            references=references,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (box, source, references, digest, skeleton) in _SOURCES.items()
    )
