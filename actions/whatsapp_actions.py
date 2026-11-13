"""
WhatsApp actions for JARVIS: application opening, contact search, messaging with confirmation, audio calls, and video calls.

Auto-discovered by core/action_loader.py. Uses verified desktop driver from plugins/_whatsapp_core.py.
"""
from __future__ import annotations

import os
import platform
import threading
from typing import Optional

from core import outcome
from plugins import _whatsapp_core as wa

_OS = platform.system()


def _log(player, message: str) -> None:
    if player and hasattr(player, "write_log"):
        try:
            player.write_log(message)
        except Exception:
            pass


def _say(player, instruction: str) -> None:
    if player and hasattr(player, "request_say"):
        try:
            player.request_say(instruction)
        except Exception:
            pass


def whatsapp_actions(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = (params.get("action") or "search").strip().lower()
    contact_name = (params.get("contact_name") or params.get("receiver") or "").strip()
    message_text = (params.get("message") or params.get("message_text") or "").strip()
    confirm_send = bool(params.get("confirm", False) or params.get("confirmed", False))

    driver, why = wa.get()
    if driver is None:
        return outcome.failed("whatsapp_actions", f"WhatsApp automation unavailable: {why}")

    # 0. Open WhatsApp Application
    if action in ("open", "launch", "start", "focus"):
        _log(player, "JARVIS: Opening WhatsApp application…")
        driver.ensure_open()
        return outcome.done("whatsapp_actions", action="open", verified=True, message="Opened WhatsApp application.")

    # 1. Contact Search
    if action == "search":
        if not contact_name:
            return outcome.failed("whatsapp_actions", "No contact name was specified.")
        _log(player, f"JARVIS: Searching for {contact_name} in WhatsApp…")
        ok, detail = driver.search_contact(contact_name)
        if ok:
            _log(player, f"JARVIS: {detail}")
            return outcome.done("whatsapp_actions", action="search", contact=contact_name, verified=True, detail=detail)
        else:
            _log(player, f"JARVIS: {detail}")
            _say(player, f"Tell the user in one short sentence: could not find {contact_name} in WhatsApp.")
            return outcome.failed("whatsapp_actions", detail, action="search", contact=contact_name)

    # 2. Send Message (Paste first -> Ask user if message is okay -> Send after confirmation)
    elif action in ("send_message", "message", "prepare_message", "paste_message"):
        if not contact_name:
            return outcome.failed("whatsapp_actions", "No contact name was specified.")
        if not message_text:
            msg = "Please specify what message you want to send."
            _log(player, f"JARVIS: {msg}")
            _say(player, "What message would you like me to send?")
            return outcome.failed("whatsapp_actions", msg, action="send_message", contact=contact_name, needs_message=True)

        if confirm_send or action == "send_now":
            _log(player, f"JARVIS: Sending confirmed message to {contact_name}…")
            ok, detail = driver.send_message_to(contact_name, message_text)
            if ok:
                _log(player, f"JARVIS: Sent to {contact_name}: {message_text}")
                return outcome.done("whatsapp_actions", action="send_message", contact=contact_name, verified=True, message=message_text)
            else:
                return outcome.failed("whatsapp_actions", detail, action="send_message", contact=contact_name)

        # Prepare message by pasting into the chat composer box without sending
        _log(player, f"JARVIS: Preparing message for {contact_name} in WhatsApp…")
        ok, detail = driver.prepare_message(contact_name, message_text)
        if not ok:
            return outcome.failed("whatsapp_actions", detail, action="send_message", contact=contact_name)

        _log(player, f"JARVIS: Typed message for {contact_name}: {message_text}")

        # Register on-screen confirmation banner with callback
        from core import confirm
        def do_send():
            d_ok, d_msg = driver.send_typed_message()
            _log(player, f"JARVIS: Sent message to {contact_name}: {message_text}")
            return d_msg

        confirm.request(
            f"wa_send_{contact_name}",
            f"Send WhatsApp message to {contact_name}",
            f"Message: '{message_text}'",
            do_send
        )

        return (
            f"[CONFIRMATION_PENDING] The message has been typed in {contact_name}'s chat: '{message_text}'. "
            f"You MUST ask the user in their language addressing them as Sir: "
            f"'Sir, {contact_name} ke liye message type kar diya hai: \'{message_text}\'. Kya yeh theek hai, bhej doon?' "
            f"Do NOT send the message until the user confirms."
        )

    # 3. Confirm Send (user verbally confirmed)
    elif action in ("confirm_send", "send_now", "send"):
        _log(player, "JARVIS: Sending typed WhatsApp message…")
        ok, detail = driver.send_typed_message()
        if ok:
            _log(player, "JARVIS: WhatsApp message sent successfully.")
            return outcome.done("whatsapp_actions", action="confirm_send", verified=True, message="Message sent successfully, Sir.")
        else:
            return outcome.failed("whatsapp_actions", detail, action="confirm_send")

    # 4. Audio / Voice Call (First Priority for Calls)
    elif action in ("audio_call", "call", "voice_call"):
        if not contact_name:
            return outcome.failed("whatsapp_actions", "No contact name was specified.")
        _log(player, f"JARVIS: Initiating audio call to {contact_name}…")
        ok, detail = driver.initiate_call(contact_name, video=False)
        if ok:
            _log(player, f"JARVIS: {detail}")
            return outcome.done("whatsapp_actions", action="audio_call", contact=contact_name, status="ringing", verified=True)
        else:
            _log(player, f"JARVIS: {detail}")
            _say(player, f"Tell the user: audio call to {contact_name} failed - {detail}")
            return outcome.failed("whatsapp_actions", detail, action="audio_call", contact=contact_name)

    # 5. Video Call
    elif action in ("video_call", "video"):
        if not contact_name:
            return outcome.failed("whatsapp_actions", "No contact name was specified.")
        _log(player, f"JARVIS: Initiating video call to {contact_name}…")
        ok, detail = driver.initiate_call(contact_name, video=True)
        if ok:
            _log(player, f"JARVIS: {detail}")
            return outcome.done("whatsapp_actions", action="video_call", contact=contact_name, status="ringing", verified=True)
        else:
            _log(player, f"JARVIS: {detail}")
            _say(player, f"Tell the user: video call to {contact_name} failed - {detail}")
            return outcome.failed("whatsapp_actions", detail, action="video_call", contact=contact_name)

    else:
        return outcome.failed("whatsapp_actions", f"Unknown action: '{action}'. Use open, search, send_message, confirm_send, audio_call, or video_call.")


TOOL = {
    "name": "whatsapp_actions",
    "description": (
        "Controls WhatsApp on this computer: open the WhatsApp application, search for a contact, "
        "type a message with confirmation, send a message, start an audio/voice call (DEFAULT PRIORITY), or start a video call. "
        "Use whenever the user asks to: "
        "1. Open WhatsApp ('open WhatsApp', 'WhatsApp kholo') -> action='open'. NEVER open an image! "
        "2. Call someone on WhatsApp ('call [person]', 'WhatsApp call [person]') -> action='audio_call' (FIRST PRIORITY). "
        "3. Video call someone on WhatsApp ('video call [person]') -> action='video_call'. "
        "4. Send a message ('send [person] message [text]') -> action='send_message'. This pastes the message in chat and asks 'Sir, message is okay?' before sending! "
        "5. User confirms sending ('yes', 'send it', 'theek hai bhej do') -> action='confirm_send'."
    ),
    "tier": "core",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "open | search | send_message | confirm_send | audio_call | video_call"
            },
            "contact_name": {
                "type": "STRING",
                "description": "The person or contact name on WhatsApp"
            },
            "message": {
                "type": "STRING",
                "description": "The exact message content to send"
            },
            "confirm": {
                "type": "BOOLEAN",
                "description": "Set to true when user has explicitly confirmed sending"
            }
        },
        "required": ["action"]
    },
    "handler": whatsapp_actions,
}
