"""Windows system-wide shortcuts used by the reader."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication


HOTKEY_ID = 0x4E52
TOP_HOTKEY_ID = 0x4E53
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000


def windows_hotkey(sequence: str) -> tuple[int, int]:
    """Convert one Qt key sequence to RegisterHotKey modifiers and VK code."""
    shortcut = QKeySequence(sequence)
    if shortcut.count() != 1:
        raise ValueError("全局快捷键只能包含一组按键。")
    combination = shortcut[0]
    key = int(combination.key())
    modifiers = combination.keyboardModifiers()
    if not modifiers & (Qt.ControlModifier | Qt.AltModifier):
        raise ValueError("全局快捷键需要包含 Ctrl 或 Alt。")
    if modifiers & Qt.MetaModifier:
        raise ValueError("全局快捷键不支持 Windows 键。")
    flags = MOD_NOREPEAT
    if modifiers & Qt.AltModifier:
        flags |= MOD_ALT
    if modifiers & Qt.ControlModifier:
        flags |= MOD_CONTROL
    if modifiers & Qt.ShiftModifier:
        flags |= MOD_SHIFT

    if int(Qt.Key_A) <= key <= int(Qt.Key_Z) or int(Qt.Key_0) <= key <= int(Qt.Key_9):
        virtual_key = key
    elif int(Qt.Key_F1) <= key <= int(Qt.Key_F12):
        virtual_key = 0x70 + key - int(Qt.Key_F1)
    else:
        virtual_key = {
            int(Qt.Key_Space): 0x20,
            int(Qt.Key_Escape): 0x1B,
            int(Qt.Key_Delete): 0x2E,
            int(Qt.Key_Insert): 0x2D,
            int(Qt.Key_Home): 0x24,
            int(Qt.Key_End): 0x23,
            int(Qt.Key_PageUp): 0x21,
            int(Qt.Key_PageDown): 0x22,
            int(Qt.Key_Left): 0x25,
            int(Qt.Key_Up): 0x26,
            int(Qt.Key_Right): 0x27,
            int(Qt.Key_Down): 0x28,
        }.get(key)
    if virtual_key is None:
        raise ValueError("这个按键不支持作为全局快捷键；请使用字母、数字、F1–F12 或方向键。")
    return flags, virtual_key


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None], hotkey_id: int):
        super().__init__()
        self.callback = callback
        self.hotkey_id = hotkey_id

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in {b"windows_dispatcher_MSG", b"windows_generic_MSG"}:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0


class GlobalHotkey:
    def __init__(self, callback: Callable[[], None], hotkey_id: int):
        self.app = QApplication.instance()
        self.hotkey_id = hotkey_id
        self.filter = _HotkeyFilter(callback, hotkey_id)
        self.active = False
        self.sequence = ""

    def register(self, sequence: str) -> tuple[bool, str]:
        self.unregister()
        if not sequence:
            return True, ""
        if sys.platform != "win32":
            return False, "全局快捷键只支持 Windows。"
        try:
            flags, virtual_key = windows_hotkey(sequence)
        except ValueError as exc:
            return False, str(exc)
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        user32.RegisterHotKey.restype = wintypes.BOOL
        self.app.installNativeEventFilter(self.filter)
        if not user32.RegisterHotKey(None, self.hotkey_id, flags, virtual_key):
            self.app.removeNativeEventFilter(self.filter)
            return False, f"无法注册 {sequence}；该组合键可能已被其他程序占用。"
        self.active = True
        self.sequence = sequence
        return True, ""

    def unregister(self) -> None:
        if self.active:
            user32 = ctypes.windll.user32
            user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.UnregisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey(None, self.hotkey_id)
            self.app.removeNativeEventFilter(self.filter)
            self.active = False
            self.sequence = ""


class GlobalCloseHotkey(GlobalHotkey):
    def __init__(self, callback: Callable[[], None]):
        super().__init__(callback, HOTKEY_ID)
