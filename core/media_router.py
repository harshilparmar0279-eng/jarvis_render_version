"""
core/media_router.py — Centralized Media Command Routing and Browser Selection.

Implements strict rules for YouTube and YouTube Music playback & browsing:
- Default Browser: Chrome
- Default URLs:
    YOUTUBE_URL = "https://www.youtube.com/?authuser=0"
    YOUTUBE_MUSIC_URL = "https://music.youtube.com/"
    DEFAULT_BROWSER = "chrome"
- "YouTube kholo" / "Open YouTube" -> YOUTUBE_URL in Chrome (never Brave default)
- "YouTube Music kholo" -> YOUTUBE_MUSIC_URL in Chrome
- "Play [song]" / "[song] music play karo" -> YouTube Music in Chrome with auto-playback
- "Chrome mein [song] play karo" -> Regular YouTube in Chrome (not redirected to Music)
- Explicit browser overrides: "Brave mein YouTube kholo" -> Brave; "Chrome mein..." -> Chrome
- Without specified browser: always use Chrome; never silently fall back to Brave
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Optional, Tuple
from urllib.parse import quote_plus

from actions.chrome_launcher import find_chrome_executable, launch_chrome
from actions.brave_launcher import find_brave_executable, open_in_brave
from core import appidentity, outcome

YOUTUBE_URL: str = "https://www.youtube.com/?authuser=0"
YOUTUBE_MUSIC_URL: str = "https://music.youtube.com/"
DEFAULT_BROWSER: str = "chrome"

# Regex patterns for browser detection
_RE_BRAVE = re.compile(r"\b(brave\s+me(?:in)?|in\s+brave|brave\s+pe|use\s+brave)\b", re.IGNORECASE)
_RE_CHROME = re.compile(r"\b(chrome\s+me(?:in)?|in\s+chrome|chrome\s+pe|use\s+chrome)\b", re.IGNORECASE)

# Words indicating YouTube Music
_RE_YT_MUSIC = re.compile(r"\byoutube\s+music\b", re.IGNORECASE)
_RE_YT = re.compile(r"\byoutube\b", re.IGNORECASE)

# Open verbs (Hindi / English)
_RE_OPEN_VERBS = re.compile(
    r"\b(open|kholo|launch|start|chalao|dikhao|open\s+karo|chalu\s+karo)\b",
    re.IGNORECASE
)

# Play verbs (Hindi / English)
_RE_PLAY_VERBS = re.compile(
    r"\b(play|chalao|bajao|lagao|sunao|listen\s+to|stream)\b",
    re.IGNORECASE
)


def is_media_target(text: str) -> bool:
    """Return True if text or spoken command targets YouTube, YouTube Music, or music playback."""
    if not text:
        return False
    t = str(text).strip().lower()
    if any(k in t for k in ("youtube.com", "youtu.be", "music.youtube.com")):
        return True
    if _RE_YT.search(t) or _RE_YT_MUSIC.search(t):
        return True
    if any(w in t for w in ("play ", "play karo", "gana chalao", "song play", "music play", "bajao", "sunao")):
        return True
    return False


def extract_browser_preference(command: str) -> Tuple[str, bool]:
    """
    Extracts browser from command.
    Returns: (browser_name: 'chrome' | 'brave', is_explicit: bool)
    Rule: Never silently fall back to Brave. Defaults to Chrome.
    """
    cmd = command.lower()
    if _RE_BRAVE.search(cmd):
        return "brave", True
    if _RE_CHROME.search(cmd):
        return "chrome", True
    return DEFAULT_BROWSER, False


def clean_song_query(raw_query: str) -> str:
    """
    Strips noise words while preserving full song title and artist names (e.g. 'by Arijit Singh').
    """
    q = raw_query.strip()
    # Remove browser instructions
    q = _RE_BRAVE.sub("", q)
    q = _RE_CHROME.sub("", q)
    # Remove service names
    q = _RE_YT_MUSIC.sub("", q)
    q = _RE_YT.sub("", q)

    # Remove generic filler prefixes and suffixes
    patterns_to_remove = [
        r"^(please\s+)?(play\s+me|play|stream|listen\s+to)\s+",
        r"^(mujhe\s+)?(ek\s+)?(gana|song|music|video)\s+",
        r"\s+(music\s+)?(play\s+karo|chalao|bajao|lagao|sunao|chalu\s+karo|play\s+kardo)$",
        r"\s+(gana|song|music)$",
        r"\s+(kholo|open\s+karo|open|launch)$",
        r"^(jarvis|snow|nia|dragon|mayra|kavya|xg|tiara|alexa|siri|computer)[,\s]+",
    ]
    for pat in patterns_to_remove:
        q = re.sub(pat, "", q, flags=re.IGNORECASE).strip()

    # If stripped empty, return original stripped
    return q.strip() if q.strip() else raw_query.strip()


def parse_media_intent(command: str) -> dict:
    """
    Parses a natural language voice or text command into structured media execution details.
    
    Rules handled:
    A. 'YouTube kholo' -> Open YOUTUBE_URL in Chrome (or explicit browser)
    B. 'YouTube Music kholo' -> Open YOUTUBE_MUSIC_URL in Chrome (or explicit browser)
    C. 'Play [song]' / '[song] music play karo' -> YouTube Music in Chrome with auto-playback
    D. 'Chrome mein [song] play karo' -> Regular YouTube in Chrome (NOT redirected to Music)
    E. Explicit browser requests override defaults. Without a specified browser, use Chrome.
    """
    raw = command.strip()
    cmd_lower = raw.lower()

    browser, is_explicit_browser = extract_browser_preference(cmd_lower)

    # Check for Rule D: Explicit "Chrome mein [song] play karo"
    # User specifically asked for Chrome playback of a song -> Regular YouTube
    is_chrome_explicit_play = (
        bool(_RE_CHROME.search(cmd_lower)) and
        bool(_RE_PLAY_VERBS.search(cmd_lower)) and
        not bool(_RE_YT_MUSIC.search(cmd_lower))
    )

    # Check if this is an explicit YouTube open (no song query)
    is_yt_music_kw = bool(_RE_YT_MUSIC.search(cmd_lower))
    is_yt_kw = bool(_RE_YT.search(cmd_lower))
    has_open_verb = bool(_RE_OPEN_VERBS.search(cmd_lower))
    has_play_verb = bool(_RE_PLAY_VERBS.search(cmd_lower))

    # Clean the query to see if a specific song/title was mentioned
    song_candidate = clean_song_query(raw)

    # Rule B: Open YouTube Music home
    if is_yt_music_kw and (has_open_verb or not song_candidate or song_candidate.lower() in ("music", "youtube music")):
        return {
            "intent": "OPEN_YOUTUBE_MUSIC",
            "service": "youtube_music",
            "browser": browser,
            "explicit_browser": is_explicit_browser,
            "url": YOUTUBE_MUSIC_URL,
            "query": "",
            "verified_playback": False,
        }

    # Rule A: Open regular YouTube home
    if is_yt_kw and not is_yt_music_kw and not has_play_verb and (has_open_verb or not song_candidate or song_candidate.lower() in ("youtube", "open youtube", "youtube kholo")):
        return {
            "intent": "OPEN_YOUTUBE",
            "service": "youtube",
            "browser": browser,
            "explicit_browser": is_explicit_browser,
            "url": YOUTUBE_URL,
            "query": "",
            "verified_playback": False,
        }

    # Rule D: 'Chrome mein [song name] play karo' -> Regular YouTube in Chrome
    if is_chrome_explicit_play:
        return {
            "intent": "PLAY_YOUTUBE",
            "service": "youtube",
            "browser": "chrome",
            "explicit_browser": True,
            "url": "",
            "query": song_candidate,
            "verified_playback": True,
        }

    # Rule C: 'Play [song name]' / '[song name] music play karo' -> YouTube Music default!
    if has_play_verb or is_yt_music_kw or "music" in cmd_lower or "gana" in cmd_lower or "song" in cmd_lower:
        return {
            "intent": "PLAY_MUSIC",
            "service": "youtube_music",
            "browser": browser,
            "explicit_browser": is_explicit_browser,
            "url": "",
            "query": song_candidate,
            "verified_playback": True,
        }

    # Fallback: if YouTube was explicitly mentioned with a query
    if is_yt_kw:
        return {
            "intent": "PLAY_YOUTUBE",
            "service": "youtube",
            "browser": browser,
            "explicit_browser": is_explicit_browser,
            "url": "",
            "query": song_candidate,
            "verified_playback": True,
        }

    # Generic Play command
    return {
        "intent": "PLAY_MUSIC",
        "service": "youtube_music",
        "browser": browser,
        "explicit_browser": is_explicit_browser,
        "url": "",
        "query": song_candidate,
        "verified_playback": True,
    }


def _resolve_video_id(query: str) -> Optional[str]:
    """Helper to scrape the first non-shorts video ID using fast scraping."""
    from actions.youtube_video import _scrape_first_video_url, _extract_video_id
    try:
        url = _scrape_first_video_url(query)
        if url:
            return _extract_video_id(url)
    except Exception as e:
        print(f"[MediaRouter] Video resolution warning: {e}")
    return None


def execute_media_command(intent_data: dict, player=None) -> Tuple[bool, str, dict]:

    from core.command_lock import sync_command_mutex
    from core.command_lock import sync_command_mutex
    """
    Executes the parsed media command with the selected browser and truthful reporting.
    
    Returns: (success: bool, user_message: str, result_metadata: dict)
    """
    intent = intent_data.get("intent", "OPEN_YOUTUBE")
    service = intent_data.get("service", "youtube")
    browser = intent_data.get("browser", DEFAULT_BROWSER).lower()
    query = intent_data.get("query", "").strip()
    target_url = intent_data.get("url", "")
    verified_playback = False

    # 1. Browser resolution & validation
    # Rule E: "Never silently fall back to Brave if Chrome is unavailable."
    if browser == "chrome":
        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            err_msg = "Google Chrome is not installed or executable could not be found on this system."
            if player:
                player.write_log(f"ERR: {err_msg}")
            return False, err_msg, {"error": "chrome_not_installed", "browser": "chrome"}
    elif browser == "brave":
        brave_exe = find_brave_executable()
        if not brave_exe:
            err_msg = "Brave browser is not installed or executable could not be found on this system."
            if player:
                player.write_log(f"ERR: {err_msg}")
            return False, err_msg, {"error": "brave_not_installed", "browser": "brave"}
    else:
        # Unknown browser, enforce Chrome
        browser = "chrome"
        chrome_exe = find_chrome_executable()
        if not chrome_exe:
            return False, "Google Chrome is not installed on this system.", {"error": "chrome_not_installed"}

    # 2. URL resolution based on intent
    if intent == "OPEN_YOUTUBE":
        target_url = YOUTUBE_URL
        verified_playback = False

    elif intent == "OPEN_YOUTUBE_MUSIC":
        target_url = YOUTUBE_MUSIC_URL
        verified_playback = False

    elif intent == "PLAY_MUSIC":
        # Rule C: Open YouTube Music, search for song, select relevant playable result and start playback
        if query:
            vid = _resolve_video_id(f"{query} song") or _resolve_video_id(query)
            if vid:
                target_url = f"https://music.youtube.com/watch?v={vid}"
                verified_playback = True
            else:
                # Scrape failed: open search page truthfully
                target_url = f"https://music.youtube.com/search?q={quote_plus(query)}"
                verified_playback = False
        else:
            target_url = YOUTUBE_MUSIC_URL
            verified_playback = False

    elif intent == "PLAY_YOUTUBE":
        # Rule D: Open regular YouTube, search for song, select relevant result and play it
        if query:
            vid = _resolve_video_id(query)
            if vid:
                target_url = f"https://www.youtube.com/watch?v={vid}"
                verified_playback = True
            else:
                # Scrape failed: open filtered results page truthfully
                target_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgIQAQ%3D%3D"
                verified_playback = False
        else:
            target_url = YOUTUBE_URL
            verified_playback = False

    # 3. Launch the browser
    launch_ok = False
    launch_msg = ""

    if browser == "brave":
        launch_ok, launch_msg = open_in_brave(target_url)
    else:
        # Launch Chrome with default user profile (empty profile_dir uses default/active session)
        launch_ok, launch_msg = launch_chrome(profile_dir="", url=target_url)

    if not launch_ok:
        if player:
            player.write_log(f"ERR: Failed to launch {browser}: {launch_msg}")
        return False, f"Failed to open {target_url} in {browser.title()}: {launch_msg}", {
            "browser": browser, "url": target_url, "verified": False
        }

    # 4. Bring browser window to the foreground
    time.sleep(0.4)
    try:
        cand = appidentity.find_running(browser)
        if cand:
            appidentity.focus(cand)
    except Exception:
        pass

    # 5. Build truthful reporting message
    svc_name = "YouTube Music" if service == "youtube_music" else "YouTube"
    if verified_playback:
        resp_text = f"Playing '{query}' on {svc_name} in {browser.title()}."
    elif query:
        resp_text = f"Opened {svc_name} search for '{query}' in {browser.title()} (manual selection required)."
    else:
        resp_text = f"Opened {svc_name} in {browser.title()}."

    if player:
        player.write_log(f"[Media] ✅ {resp_text}")
        if query and hasattr(player, "show_lyrics_track"):
            m = re.search(r"\b(?:by|singer)\s+([a-zA-Z\s]+)", query, re.I)
            artist = m.group(1).strip() if m else ""
            track = re.sub(r"\b(?:by|singer)\s+([a-zA-Z\s]+)", "", query, flags=re.I).strip()
            player.show_lyrics_track(track or query, artist)

    result_data = {
        "status": "playing" if verified_playback else "opened",
        "service": svc_name,
        "browser": browser,
        "url": target_url,
        "query": query,
        "verified": verified_playback,
    }
    return True, resp_text, result_data


def route_media_command(command: str, player=None) -> Tuple[bool, str, dict]:
    """Central entry point: parses media command and executes it immediately."""
    intent = parse_media_intent(command)
    return execute_media_command(intent, player=player)
