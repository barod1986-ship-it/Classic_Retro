"""The libretro backend: any libretro core, driven through ctypes.

libretro cores exist for most consoles: mGBA, Snes9x, Genesis Plus GX, Mesen,
Beetle PSX and others. This frontend loads a core's shared library, gives it the
game and drives it frame by frame. Keys are pressed on RetroPad port 1, a touch
is a pointer pressed on the frame (a core with a touch screen reads it, such as
DeSmuME with its pointer set to ``touch``), frames come from the core's software
video output, and savestates use the core's serializer. Memory is read by bus
address through the memory map the core publishes, or as an offset into a
region the core names (``system_ram``, ``save_ram``, ``video_ram``, ``rtc``).
libretro has no debugger; breakpoints and watchpoints need the mgba backend.

A core runs one game at a time, and each core library loads once per process.
The core gets an empty system directory unless one is given (BIOS files go
there), and its options keep their defaults unless ``options`` sets them.
"""

from __future__ import annotations

import ctypes
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.research.emulator import (
    RETROPAD_KEYS,
    Address,
    Emulator,
    Hit,
    RegionAddress,
    Screen,
)

_API_VERSION = 1
_EXPERIMENTAL = 0x10000

# Environment calls the frontend answers (libretro.h).
_GET_CAN_DUPE = 3
_SHUTDOWN = 7
_GET_SYSTEM_DIRECTORY = 9
_SET_PIXEL_FORMAT = 10
_GET_VARIABLE = 15
_GET_VARIABLE_UPDATE = 17
_GET_LOG_INTERFACE = 27
_GET_CONTENT_DIRECTORY = 30
_GET_SAVE_DIRECTORY = 31
_SET_MEMORY_MAPS = 36 | _EXPERIMENTAL
_GET_INPUT_BITMASKS = 51 | _EXPERIMENTAL
# Calls that only tell the frontend something it does not need.
_ACCEPTED = frozenset(
    {
        6,  # SET_MESSAGE
        8,  # SET_PERFORMANCE_LEVEL
        11,  # SET_INPUT_DESCRIPTORS
        16,  # SET_VARIABLES
        18,  # SET_SUPPORT_NO_GAME
        32,  # SET_SYSTEM_AV_INFO
        34,  # SET_SUBSYSTEM_INFO
        35,  # SET_CONTROLLER_INFO
        37,  # SET_GEOMETRY
        42 | _EXPERIMENTAL,  # SET_SUPPORT_ACHIEVEMENTS
        44,  # SET_SERIALIZATION_QUIRKS (before libretro moved it to 87)
        55,  # SET_CORE_OPTIONS_DISPLAY
        60,  # SET_MESSAGE_EXT
        69,  # SET_CORE_OPTIONS_UPDATE_DISPLAY_CALLBACK
        70,  # SET_VARIABLE
        87,  # SET_SERIALIZATION_QUIRKS
    }
)

_PIXEL_0RGB1555 = 0
_PIXEL_XRGB8888 = 1
_PIXEL_RGB565 = 2
# Pillow's raw modes for libretro's pixel formats, and their bytes a pixel.
_RAW_MODES = {
    _PIXEL_0RGB1555: ("BGR;15", 2),
    _PIXEL_XRGB8888: ("BGRX", 4),
    _PIXEL_RGB565: ("BGR;16", 2),
}

_DEVICE_JOYPAD = 1
_DEVICE_POINTER = 6
_DEVICE_MASK = 0xFF
# A pointer's X and Y run from -0x7FFF (left, top) to 0x7FFF across the frame.
_POINTER_X = 0
_POINTER_Y = 1
_POINTER_PRESSED = 2
_POINTER_SPAN = 0x10000
_JOYPAD_MASK = 256
_BUTTONS = {
    "B": 0,
    "Y": 1,
    "SELECT": 2,
    "START": 3,
    "UP": 4,
    "DOWN": 5,
    "LEFT": 6,
    "RIGHT": 7,
    "A": 8,
    "X": 9,
    "L": 10,
    "R": 11,
    "L2": 12,
    "R2": 13,
    "L3": 14,
    "R3": 15,
}
REGIONS = {"save_ram": 0, "rtc": 1, "system_ram": 2, "video_ram": 3}
_MEMDESC_CONST = 1


class _SystemInfo(ctypes.Structure):
    _fields_ = [
        ("library_name", ctypes.c_char_p),
        ("library_version", ctypes.c_char_p),
        ("valid_extensions", ctypes.c_char_p),
        ("need_fullpath", ctypes.c_bool),
        ("block_extract", ctypes.c_bool),
    ]


class _GameGeometry(ctypes.Structure):
    _fields_ = [
        ("base_width", ctypes.c_uint),
        ("base_height", ctypes.c_uint),
        ("max_width", ctypes.c_uint),
        ("max_height", ctypes.c_uint),
        ("aspect_ratio", ctypes.c_float),
    ]


class _SystemTiming(ctypes.Structure):
    _fields_ = [("fps", ctypes.c_double), ("sample_rate", ctypes.c_double)]


class _SystemAvInfo(ctypes.Structure):
    _fields_ = [("geometry", _GameGeometry), ("timing", _SystemTiming)]


class _GameInfo(ctypes.Structure):
    _fields_ = [
        ("path", ctypes.c_char_p),
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("meta", ctypes.c_char_p),
    ]


class _Variable(ctypes.Structure):
    _fields_ = [("key", ctypes.c_char_p), ("value", ctypes.c_void_p)]


class _MemoryDescriptor(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("ptr", ctypes.c_void_p),
        ("offset", ctypes.c_size_t),
        ("start", ctypes.c_size_t),
        ("select", ctypes.c_size_t),
        ("disconnect", ctypes.c_size_t),
        ("len", ctypes.c_size_t),
        ("addrspace", ctypes.c_char_p),
    ]


class _MemoryMap(ctypes.Structure):
    _fields_ = [
        ("descriptors", ctypes.POINTER(_MemoryDescriptor)),
        ("num_descriptors", ctypes.c_uint),
    ]


_ENVIRONMENT = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint, ctypes.c_void_p)
_VIDEO_REFRESH = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_size_t
)
_AUDIO_SAMPLE = ctypes.CFUNCTYPE(None, ctypes.c_int16, ctypes.c_int16)
_AUDIO_SAMPLE_BATCH = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t)
_INPUT_POLL = ctypes.CFUNCTYPE(None)
# retro_log_printf_t takes a format and its arguments; the frontend reads the
# level and the format only, which every C calling convention passes the same
# way to a variadic function, and drops them: some cores (DeSmuME) log without
# checking that the frontend gave them a callback.
_LOG = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p)
_INPUT_STATE = ctypes.CFUNCTYPE(
    ctypes.c_int16, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
)


def _declare(core: ctypes.CDLL) -> None:
    signatures = {
        "retro_api_version": (ctypes.c_uint, []),
        "retro_set_environment": (None, [_ENVIRONMENT]),
        "retro_set_video_refresh": (None, [_VIDEO_REFRESH]),
        "retro_set_audio_sample": (None, [_AUDIO_SAMPLE]),
        "retro_set_audio_sample_batch": (None, [_AUDIO_SAMPLE_BATCH]),
        "retro_set_input_poll": (None, [_INPUT_POLL]),
        "retro_set_input_state": (None, [_INPUT_STATE]),
        "retro_init": (None, []),
        "retro_deinit": (None, []),
        "retro_get_system_info": (None, [ctypes.POINTER(_SystemInfo)]),
        "retro_get_system_av_info": (None, [ctypes.POINTER(_SystemAvInfo)]),
        "retro_set_controller_port_device": (None, [ctypes.c_uint, ctypes.c_uint]),
        "retro_load_game": (ctypes.c_bool, [ctypes.POINTER(_GameInfo)]),
        "retro_unload_game": (None, []),
        "retro_reset": (None, []),
        "retro_run": (None, []),
        "retro_serialize_size": (ctypes.c_size_t, []),
        "retro_serialize": (ctypes.c_bool, [ctypes.c_void_p, ctypes.c_size_t]),
        "retro_unserialize": (ctypes.c_bool, [ctypes.c_void_p, ctypes.c_size_t]),
        "retro_get_memory_data": (ctypes.c_void_p, [ctypes.c_uint]),
        "retro_get_memory_size": (ctypes.c_size_t, [ctypes.c_uint]),
    }
    for name, (result, arguments) in signatures.items():
        try:
            function = getattr(core, name)
        except AttributeError:
            raise ClassicRetroError(
                ErrorCode.EMULATOR_UNAVAILABLE, f"Not a libretro core: it has no {name}"
            ) from None
        function.restype = result
        function.argtypes = arguments


@dataclass(frozen=True, slots=True)
class _Mapping:
    """One memory descriptor of a core's memory map."""

    pointer: int | None
    offset: int
    start: int
    select: int
    disconnect: int
    length: int
    constant: bool

    def locate(self, address: int) -> tuple[int, int] | None:
        """The byte ``address`` maps to, as (offset into ``pointer``, bytes contiguous)."""
        if self.select:
            if (address ^ self.start) & self.select:
                return None
            offset = _drop_bits(address - self.start, self.disconnect)
            while self.length and offset >= self.length:
                offset &= ~(1 << (offset.bit_length() - 1))
            # The mapping runs on until the next select block or the region's end.
            step = self.select & -self.select
            run = step - (address & (step - 1))
            if self.length:
                run = min(run, self.length - offset)
            if self.disconnect:
                run = 1
        else:
            if not self.start <= address < self.start + self.length:
                return None
            offset = address - self.start
            run = self.start + self.length - address
        return self.offset + offset, run


def _drop_bits(value: int, mask: int) -> int:
    """``value`` with the bits set in ``mask`` removed, higher bits moving down."""
    while mask:
        low = mask & -mask
        value = (value & (low - 1)) | ((value >> 1) & ~(low - 1))
        mask = (mask & (mask - 1)) >> 1
    return value


# Core libraries with a game running, by path: a library loads once per process.
_RUNNING: set[str] = set()


class LibretroEmulator(Emulator):
    """A game under a libretro core."""

    backend = "libretro"
    keys = frozenset(RETROPAD_KEYS)
    regions = frozenset(REGIONS)
    pointer = True

    def __init__(
        self,
        core: Path,
        image: Path,
        *,
        options: Mapping[str, str] | None = None,
        system_dir: Path | None = None,
    ) -> None:
        library = str(core.resolve())
        if library in _RUNNING:
            raise ClassicRetroError(
                ErrorCode.EMULATOR_UNAVAILABLE, f"The core {core} already runs a game here"
            )
        try:
            self._core = ctypes.CDLL(library)
        except OSError as exc:
            raise ClassicRetroError(
                ErrorCode.EMULATOR_UNAVAILABLE, f"Could not load the libretro core {core}: {exc}"
            ) from exc
        _declare(self._core)
        if self._core.retro_api_version() != _API_VERSION:
            raise ClassicRetroError(
                ErrorCode.EMULATOR_UNAVAILABLE, f"{core} is not a libretro API 1 core"
            )
        self._library = library
        self._work = tempfile.TemporaryDirectory(prefix="classic-retro-libretro-")
        system = str((system_dir or Path(self._work.name)).resolve()).encode()
        self._directories = {
            _GET_SYSTEM_DIRECTORY: ctypes.create_string_buffer(system),
            _GET_SAVE_DIRECTORY: ctypes.create_string_buffer(self._work.name.encode()),
            _GET_CONTENT_DIRECTORY: ctypes.create_string_buffer(
                str(image.resolve().parent).encode()
            ),
        }
        self._options = {
            key.encode(): ctypes.create_string_buffer(value.encode())
            for key, value in (options or {}).items()
        }
        self._pixel_format = _PIXEL_0RGB1555
        self._frame: tuple[bytes, int, int, int, int] | None = None
        self._pressed = 0
        self._touch: tuple[int, int] | None = None
        self._geometry = (0, 0)
        self._maps: tuple[_Mapping, ...] = ()
        self._callback_error: BaseException | None = None
        self._loaded = False
        self._callbacks = (
            _ENVIRONMENT(self._environment),
            _VIDEO_REFRESH(self._video),
            _AUDIO_SAMPLE(lambda left, right: None),
            _AUDIO_SAMPLE_BATCH(lambda data, frames: frames),
            _INPUT_POLL(lambda: None),
            _INPUT_STATE(self._input),
        )
        self._log = _LOG(lambda level, text: None)
        environment, video, sample, batch, poll, state = self._callbacks
        self._core.retro_set_environment(environment)
        self._core.retro_set_video_refresh(video)
        self._core.retro_set_audio_sample(sample)
        self._core.retro_set_audio_sample_batch(batch)
        self._core.retro_set_input_poll(poll)
        self._core.retro_set_input_state(state)
        self._core.retro_init()
        _RUNNING.add(library)
        try:
            self._load(image)
        except BaseException:
            self.close()
            raise

    def _load(self, image: Path) -> None:
        info = _SystemInfo()
        self._core.retro_get_system_info(ctypes.byref(info))
        name = (info.library_name or b"libretro core").decode("utf-8", "replace")
        version = (info.library_version or b"").decode("utf-8", "replace")
        self.core = f"{name} {version}".strip()
        game = _GameInfo(path=str(image.resolve()).encode())
        if not info.need_fullpath:
            self._game_data = ctypes.create_string_buffer(image.read_bytes(), image.stat().st_size)
            game.data = ctypes.cast(self._game_data, ctypes.c_void_p)
            game.size = len(self._game_data)
        if not self._core.retro_load_game(ctypes.byref(game)):
            raise ClassicRetroError(
                ErrorCode.EMULATOR_FAILED, f"The core {self.core} could not load {image}"
            )
        self._loaded = True
        # Frontends ask for the timing after loading; some cores finish setting up there.
        av_info = _SystemAvInfo()
        self._core.retro_get_system_av_info(ctypes.byref(av_info))
        self._geometry = (av_info.geometry.base_width, av_info.geometry.base_height)
        self._check_callbacks()
        self._core.retro_set_controller_port_device(0, _DEVICE_JOYPAD)

    # Callbacks from the core: they must never raise into C.

    def _environment(self, command: int, data: int | None) -> bool:
        try:
            return self._answer(command, data)
        except Exception as exc:  # a callback must not raise into the core
            self._callback_error = self._callback_error or exc
            return False

    def _answer(self, command: int, data: int | None) -> bool:
        if command in _ACCEPTED or command == _SHUTDOWN:
            return True
        if data is None:
            return command == _GET_INPUT_BITMASKS
        if command == _GET_CAN_DUPE:
            ctypes.c_bool.from_address(data).value = True
            return True
        if command in self._directories:
            ctypes.c_void_p.from_address(data).value = ctypes.addressof(self._directories[command])
            return True
        if command == _SET_PIXEL_FORMAT:
            pixel_format = ctypes.c_int.from_address(data).value
            if pixel_format not in _RAW_MODES:
                return False
            self._pixel_format = pixel_format
            return True
        if command == _GET_VARIABLE:
            variable = _Variable.from_address(data)
            value = self._options.get(variable.key or b"")
            variable.value = None if value is None else ctypes.addressof(value)
            return value is not None
        if command == _GET_VARIABLE_UPDATE:
            ctypes.c_bool.from_address(data).value = False
            return True
        if command == _GET_LOG_INTERFACE:
            ctypes.c_void_p.from_address(data).value = ctypes.cast(self._log, ctypes.c_void_p).value
            return True
        if command == _SET_MEMORY_MAPS:
            memory_map = _MemoryMap.from_address(data)
            self._maps = tuple(
                _Mapping(
                    pointer=item.ptr,
                    offset=item.offset,
                    start=item.start,
                    select=item.select,
                    disconnect=item.disconnect,
                    length=item.len,
                    constant=bool(item.flags & _MEMDESC_CONST),
                )
                for item in memory_map.descriptors[: memory_map.num_descriptors]
            )
            return True
        return command == _GET_INPUT_BITMASKS

    def _video(self, data: int | None, width: int, height: int, pitch: int) -> None:
        # No data repeats the last frame; -1 would be a hardware-rendered one.
        if data is None or data == ctypes.c_void_p(-1).value:
            return
        try:
            pixels = ctypes.string_at(data, pitch * height)
            self._frame = (pixels, width, height, pitch, self._pixel_format)
        except Exception as exc:  # a callback must not raise into the core
            self._callback_error = self._callback_error or exc

    def _input(self, port: int, device: int, index: int, button: int) -> int:
        if port == 0 and device & _DEVICE_MASK == _DEVICE_POINTER and index == 0:
            return self._pointer(button)
        if port != 0 or device & _DEVICE_MASK != _DEVICE_JOYPAD:
            return 0
        if button == _JOYPAD_MASK:
            return self._pressed
        return (self._pressed >> button) & 1 if button < 16 else 0

    def _pointer(self, axis: int) -> int:
        """The pointer as libretro gives it: the touched pixel scaled across the frame."""
        if self._touch is None:
            return 0
        if axis == _POINTER_PRESSED:
            return 1
        if axis not in (_POINTER_X, _POINTER_Y):
            return 0
        size = self._frame[1 + axis] if self._frame is not None else self._geometry[axis]
        if not size:
            return 0
        # The centre of the pixel, so the core's scaling back lands on the pixel itself.
        position = (2 * self._touch[axis] + 1) * _POINTER_SPAN // (2 * size) - _POINTER_SPAN // 2
        return max(-0x7FFF, min(0x7FFF, position))

    def _check_callbacks(self) -> None:
        if self._callback_error is not None:
            error, self._callback_error = self._callback_error, None
            raise ClassicRetroError(
                ErrorCode.EMULATOR_FAILED, f"The frontend failed answering {self.core}: {error}"
            ) from error

    # The Emulator interface.

    def run(self, frames: int, keys: frozenset[str]) -> list[Hit]:
        self._pressed = sum(1 << _BUTTONS[key] for key in keys)
        for _ in range(frames):
            self._core.retro_run()
        self._check_callbacks()
        return []

    def touch(self, point: tuple[int, int] | None) -> None:
        self._touch = point

    def screen(self) -> Screen:
        if self._frame is None:
            raise ClassicRetroError(
                ErrorCode.EMULATOR_FAILED, "No frame yet: run at least one frame before a shot"
            )
        pixels, width, height, pitch, pixel_format = self._frame
        mode, size = _RAW_MODES[pixel_format]
        if pitch < width * size:
            raise ClassicRetroError(ErrorCode.EMULATOR_FAILED, "The core drew a malformed frame")
        image = Image.frombuffer("RGB", (width, height), pixels, "raw", mode, pitch, 1)
        return Screen(width, height, image.tobytes())

    def save_state(self) -> bytes:
        size = self._core.retro_serialize_size()
        buffer = ctypes.create_string_buffer(size)
        if not size or not self._core.retro_serialize(buffer, size):
            raise ClassicRetroError(
                ErrorCode.EMULATOR_FAILED, f"{self.core} could not save a state"
            )
        return buffer.raw

    def load_state(self, state: bytes) -> None:
        buffer = ctypes.create_string_buffer(state, len(state))
        if not self._core.retro_unserialize(buffer, len(state)):
            raise ClassicRetroError(ErrorCode.EMULATOR_FAILED, f"{self.core} rejected the state")

    def _spans(self, address: Address, length: int, writing: bool) -> list[tuple[int, int]]:
        """Host (pointer, length) spans holding ``length`` bytes from ``address``."""
        if isinstance(address, RegionAddress):
            region = REGIONS[address.region]
            pointer = self._core.retro_get_memory_data(region)
            size = self._core.retro_get_memory_size(region)
            if not pointer or address.offset + length > size:
                raise ClassicRetroError(
                    ErrorCode.EMULATOR_FAILED,
                    f"{address} + {length} bytes is outside {address.region} "
                    f"({size} bytes in {self.core})",
                )
            return [(pointer + address.offset, length)]
        if not self._maps:
            raise ClassicRetroError(
                ErrorCode.EMULATOR_FAILED,
                f"{self.core} publishes no memory map: use a region "
                f"({', '.join(REGIONS)}), e.g. system_ram:0x0",
            )
        spans = []
        while length:
            pointer, run, constant = self._locate(address)
            if writing and constant:
                raise ClassicRetroError(ErrorCode.EMULATOR_FAILED, f"0x{address:08X} is read-only")
            take = min(length, run)
            spans.append((pointer, take))
            address += take
            length -= take
        return spans

    def _locate(self, address: int) -> tuple[int, int, bool]:
        """The host pointer of ``address``, the bytes contiguous from it, and read-only-ness."""
        for mapping in self._maps:
            found = mapping.locate(address)
            if found is not None:
                if mapping.pointer is None:
                    break
                offset, run = found
                return mapping.pointer + offset, run, mapping.constant
        raise ClassicRetroError(
            ErrorCode.EMULATOR_FAILED, f"0x{address:08X} is not mapped to memory"
        )

    def read(self, address: Address, length: int) -> bytes:
        return b"".join(
            ctypes.string_at(pointer, size) for pointer, size in self._spans(address, length, False)
        )

    def write(self, address: Address, data: bytes) -> None:
        position = 0
        for pointer, size in self._spans(address, len(data), True):
            ctypes.memmove(pointer, data[position : position + size], size)
            position += size

    def reset(self) -> None:
        self._core.retro_reset()

    def close(self) -> None:
        if self._library not in _RUNNING:
            return
        if self._loaded:
            self._core.retro_unload_game()
            self._loaded = False
        self._core.retro_deinit()
        _RUNNING.discard(self._library)
        self._work.cleanup()
