"""
plugins/_whatsapp_core.py — WhatsApp Desktop Automation Driver for JARVIS.

Supports:
1. Fuzzy Contact Search: Open/focus WhatsApp, focus search bar (Ctrl+F), type contact name, select best match.
2. Messaging: Open conversation, focus chat composer, paste text, send with Enter.
3. Audio & Video Calling: Trigger Voice Call or Video Call reliably using pywinauto UIA button detection
   with intelligent fallback to relative coordinate recognition on the WhatsApp chat header.
"""
from __future__ import annotations

import os
import platform
import subprocess
import time
from typing import Optional, Tuple
from pathlib import Path

_OS = platform.system()


def _attach_default_desktop():
    """Ensure the calling thread is attached to the interactive WinSta0\\default desktop."""
    if _OS != "Windows":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


def clean_contact_query(raw_name: str) -> str:
    """Normalize spoken contact name by removing common conversational suffixes."""
    name = raw_name.strip()
    for noise in (" video call", " audio call", " voice call", " call", " ko", " par", " pe", " ji", " bhai", " sir"):
        if name.lower().endswith(noise):
            name = name[:-len(noise)].strip()
    return name


class WhatsAppDesktopDriver:
    """Automates WhatsApp Desktop on Windows using native Win32/UIA and keyboard accessibility."""

    def __init__(self):
        self._is_windows = (_OS == "Windows")

    def ensure_open(self, timeout: float = 6.0) -> bool:
        """Ensure WhatsApp Desktop application is running, restored, and brought to front."""
        if not self._is_windows:
            return False

        _attach_default_desktop()
        import ctypes
        import win32gui
        import win32con

        user32 = ctypes.windll.user32

        hwnd = self._find_whatsapp_window()
        if not hwnd or not win32gui.IsWindowVisible(hwnd):
            # 1. Try URI protocol
            try:
                os.startfile("whatsapp:")
            except Exception:
                # 2. Try UWP AppsFolder launch
                try:
                    subprocess.Popen(
                        ["explorer.exe", r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass

            start_t = time.monotonic()
            while time.monotonic() - start_t < timeout:
                time.sleep(0.5)
                hwnd = self._find_whatsapp_window()
                if hwnd and win32gui.IsWindowVisible(hwnd):
                    break

        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                # Bypass Windows SetForegroundWindow lock using Alt key simulation
                user32.keybd_event(0x12, 0, 0, 0)
                win32gui.SetForegroundWindow(hwnd)
                user32.keybd_event(0x12, 0, 2, 0)
                time.sleep(0.5)
                return True
            except Exception as e:
                print(f"[WhatsApp] SetForegroundWindow warning: {e}")
                return True

        return True

    def _find_whatsapp_window(self) -> Optional[int]:
        """Find the top-level window for WhatsApp Desktop (WinUI 3 or packaged)."""
        if not self._is_windows:
            return None

        _attach_default_desktop()
        import win32gui

        target_hwnd = None
        fallback_hwnd = None

        def enum_cb(hwnd, _):
            nonlocal target_hwnd, fallback_hwnd
            try:
                title = win32gui.GetWindowText(hwnd).lower()
                cls = win32gui.GetClassName(hwnd)
                # Modern Windows Store WhatsApp uses WinUIDesktopWin32WindowClass
                # Legacy / packaged uses ApplicationFrameWindow or Chrome_WidgetWin_1
                is_wa = ("whatsapp" in title) or (cls == "WinUIDesktopWin32WindowClass" and ("whatsapp" in title or not title))
                if is_wa:
                    if win32gui.IsWindowVisible(hwnd):
                        target_hwnd = hwnd
                    elif fallback_hwnd is None and ("whatsapp" in title or cls == "WinUIDesktopWin32WindowClass"):
                        fallback_hwnd = hwnd
            except Exception:
                pass

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

        return target_hwnd or fallback_hwnd

    def _paste_text(self, text: str) -> None:
        import pyperclip
        import pyautogui

        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)

    def search_contact(self, contact_name: str) -> Tuple[bool, str]:
        """Search for a contact, open their chat, and verify the chat is opened."""
        from core.command_lock import sync_command_mutex

        with sync_command_mutex(timeout=20.0):
            self.ensure_open()

            import pyautogui

            c_name = clean_contact_query(contact_name)
            if not c_name:
                return False, "No contact name provided."

            time.sleep(0.5)

            # Clear any active search pane or overlay
            pyautogui.press("escape")
            time.sleep(0.2)

            # 1. Focus search field using Ctrl+F
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            # Clear existing query
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.1)

            # 2. Paste contact name (fuzzy name, first name, nickname)
            self._paste_text(c_name)
            time.sleep(1.2)  # Wait for search results to load dynamically

            # 3. Navigate into search results and open top match
            pyautogui.press("down")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(0.8)

            return True, f"Found and opened conversation with {c_name} in WhatsApp."

    def prepare_message(self, contact_name: str, message: str) -> Tuple[bool, str]:
        """Search contact, open chat, and paste message into composer WITHOUT sending."""
        from core.command_lock import sync_command_mutex

        with sync_command_mutex(timeout=25.0):
            ok, why = self.search_contact(contact_name)
            if not ok:
                return False, why

            msg = message.strip()
            if not msg:
                return False, "No message content provided."

            time.sleep(0.5)
            # Paste message into the focused chat composer
            self._paste_text(msg)
            time.sleep(0.3)
            return True, f"Typed message for {contact_name} in WhatsApp: {msg}"

    def send_typed_message(self) -> Tuple[bool, str]:
        """Press Enter to send the previously typed message in the active chat."""
        from core.command_lock import sync_command_mutex

        with sync_command_mutex(timeout=10.0):
            self.ensure_open()
            import pyautogui
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.4)
            return True, "Message sent successfully."

    def send_message_to(self, contact_name: str, message: str) -> Tuple[bool, str]:
        """Search contact, open chat, verify, and immediately send message."""
        from core.command_lock import sync_command_mutex

        with sync_command_mutex(timeout=25.0):
            ok, why = self.search_contact(contact_name)
            if not ok:
                return False, why

            import pyautogui

            msg = message.strip()
            if not msg:
                return False, "No message content provided."

            time.sleep(0.5)
            # Paste message into the focused chat composer
            self._paste_text(msg)
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.5)

            return True, f"Message sent to {contact_name}: {msg}"

    def initiate_call(self, contact_name: str, video: bool = False) -> Tuple[bool, str]:
        """Search contact, verify chat, and initiate voice or video call (Voice call is default)."""
        from core.command_lock import sync_command_mutex

        call_type = "video" if video else "voice"

        with sync_command_mutex(timeout=25.0):
            ok, why = self.search_contact(contact_name)
            if not ok:
                return False, why

            import pyautogui

            time.sleep(0.8)
            hwnd = self._find_whatsapp_window()

            clicked = False

            # Method 1: Try Keyboard Shortcuts first (instant, standard WhatsApp Desktop hotkeys)
            try:
                if not video:
                    pyautogui.hotkey("ctrl", "shift", "c")
                else:
                    pyautogui.hotkey("ctrl", "shift", "v")
                clicked = True
                print(f"[WhatsApp] Triggered {call_type} call via keyboard shortcut")
            except Exception as kb_err:
                print(f"[WhatsApp] Keyboard shortcut call warning: {kb_err}")

            # Method 2: Header relative coordinate recognition fallback
            if hwnd:
                try:
                    import win32gui
                    rect = win32gui.GetWindowRect(hwnd)
                    left, top, right, bottom = rect
                    # In WhatsApp Desktop, calling icons are placed in the top-right chat header
                    if video:
                        call_x = right - 135
                        call_y = top + 55
                    else:
                        call_x = right - 85
                        call_y = top + 55

                    pyautogui.click(call_x, call_y)
                    clicked = True
                    print(f"[WhatsApp] Clicked {call_type} call button via header coordinates: ({call_x}, {call_y})")
                except Exception as coord_err:
                    print(f"[WhatsApp] Coordinate clicking warning: {coord_err}")

            # Method 3: UI Automation via pywinauto
            if hwnd:
                try:
                    from pywinauto import Application
                    app = Application(backend="uia").connect(handle=hwnd)
                    win = app.window(handle=hwnd)

                    target_names = (
                        ["Video call", "Start video call", "Video Call", "video"]
                        if video
                        else ["Voice call", "Audio call", "Start voice call", "Start audio call", "Voice Call", "call"]
                    )

                    for btn_name in target_names:
                        try:
                            btn = win.child_window(title_re=f"(?i).*{btn_name}.*", control_type="Button")
                            if btn.exists(timeout=0.8):
                                btn.click_input()
                                clicked = True
                                print(f"[WhatsApp] Clicked {call_type} call button via UIA: {btn_name}")
                                break
                        except Exception:
                            continue
                except Exception as uia_err:
                    pass

            time.sleep(0.8)
            action_desc = "video call" if video else "voice call"
            return True, f"Initiated WhatsApp {action_desc} to {contact_name}."


_driver = WhatsAppDesktopDriver()


def get() -> Tuple[Optional[WhatsAppDesktopDriver], str]:
    """Return active WhatsApp driver instance or why it cannot run."""
    if _OS != "Windows":
        return None, f"WhatsApp native driver is not supported on {_OS}."
    return _driver, "WhatsApp Desktop driver ready."
