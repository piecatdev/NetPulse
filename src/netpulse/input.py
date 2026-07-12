from __future__ import annotations

import asyncio
import platform
import queue
import sys
import threading
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class KeyAction:
    name: str


class KeyboardInput:
    """Non-blocking keyboard reader for interactive terminal controls."""

    async def read_action(self) -> KeyAction:
        while True:
            key = self._poll_key()
            if key:
                return KeyAction(self._map_key(key))
            await asyncio.sleep(0.05)

    def _poll_key(self) -> str:
        if platform.system().lower() == "windows":
            return self._poll_windows_key()
        return self._poll_posix_key()

    @staticmethod
    def _poll_windows_key() -> str:
        event_key = _poll_windows_console_event()
        if event_key:
            return event_key

        # Fallback for older console hosts where ReadConsoleInputW is not
        # available through the current stdin handle.
        import msvcrt

        if not msvcrt.kbhit():
            return ""
        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            code = _wait_windows_char(msvcrt)
            if not code:
                return ""
            return {
                "H": "up",
                "P": "down",
                "K": "left",
                "M": "right",
            }.get(code, "")
        if key == "\x1b":
            sequence = _read_windows_escape_sequence(msvcrt)
            return {
                "[A": "up",
                "[B": "down",
                "[D": "left",
                "[C": "right",
            }.get(sequence, "")
        return key.lower()

    @staticmethod
    def _poll_posix_key() -> str:
        try:
            if not sys.stdin.isatty():
                return ""
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            return ""
        import select
        import termios
        import tty

        try:
            old_settings = termios.tcgetattr(fd)
        except termios.error:
            return ""
        try:
            tty.setcbreak(fd)
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                return ""
            key = sys.stdin.read(1)
            if key == "\x1b":
                ready, _, _ = select.select([sys.stdin], [], [], 0)
                if not ready:
                    return ""
                sequence = sys.stdin.read(2)
                return {
                    "[A": "up",
                    "[B": "down",
                    "[D": "left",
                    "[C": "right",
                }.get(sequence, "")
            return key.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    @staticmethod
    def _map_key(key: str) -> str:
        return {
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "k": "up",
            "j": "down",
            "h": "left",
            "l": "right",
            "r": "refresh",
            "v": "view",
            "q": "quit",
        }.get(key, "noop")


class LineKeyboardInput:
    """Fallback input reader: type a command and press Enter."""

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._read_lines, daemon=True)
        self._thread.start()

    async def read_action(self) -> KeyAction:
        while True:
            try:
                key = self._queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            return KeyAction(KeyboardInput._map_key(key))

    def _read_lines(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except OSError:
                return
            if not line:
                return
            text = line.strip().lower()
            if text:
                self._queue.put(text[0])


def _wait_windows_char(msvcrt_module, timeout: float = 0.08) -> str:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if msvcrt_module.kbhit():
            return msvcrt_module.getwch()
    return ""


def _read_windows_escape_sequence(msvcrt_module) -> str:
    chars: list[str] = []
    deadline = monotonic() + 0.08
    while monotonic() < deadline and len(chars) < 2:
        if msvcrt_module.kbhit():
            chars.append(msvcrt_module.getwch())
    return "".join(chars)


def _poll_windows_console_event() -> str:
    from ctypes import Structure, Union, byref, c_ushort, c_wchar, windll
    from ctypes.wintypes import BOOL, DWORD, HANDLE, WORD

    std_input_handle = -10
    key_event = 0x0001
    vk_left = 0x25
    vk_up = 0x26
    vk_right = 0x27
    vk_down = 0x28

    class _KEY_EVENT_RECORD(Structure):
        _fields_ = [
            ("bKeyDown", BOOL),
            ("wRepeatCount", WORD),
            ("wVirtualKeyCode", WORD),
            ("wVirtualScanCode", WORD),
            ("UnicodeChar", c_wchar),
            ("dwControlKeyState", DWORD),
        ]

    class _INPUT_RECORD_EVENT(Union):
        _fields_ = [
            ("KeyEvent", _KEY_EVENT_RECORD),
            ("padding", c_ushort * 16),
        ]

    class _INPUT_RECORD(Structure):
        _fields_ = [
            ("EventType", WORD),
            ("Event", _INPUT_RECORD_EVENT),
        ]

    try:
        kernel32 = windll.kernel32
    except (AttributeError, OSError):
        return ""

    handle = kernel32.GetStdHandle(std_input_handle)
    if not handle or handle == HANDLE(-1).value:
        return ""

    count = DWORD()
    if not kernel32.GetNumberOfConsoleInputEvents(handle, byref(count)):
        return ""
    if count.value == 0:
        return ""

    record = _INPUT_RECORD()
    read = DWORD()
    if not kernel32.ReadConsoleInputW(handle, byref(record), 1, byref(read)):
        return ""
    if read.value == 0 or record.EventType != key_event:
        return ""

    event = record.Event.KeyEvent
    if not event.bKeyDown:
        return ""

    virtual_key = int(event.wVirtualKeyCode)
    if virtual_key == vk_up:
        return "up"
    if virtual_key == vk_down:
        return "down"
    if virtual_key == vk_left:
        return "left"
    if virtual_key == vk_right:
        return "right"

    char = event.UnicodeChar
    return char.lower() if char else ""
