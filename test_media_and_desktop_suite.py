"""
test_media_and_desktop_suite.py — Unit & Integration tests for:
1. Media Command Routing (Rules A, B, C, D, E)
2. Song Intent Detection & Query Extraction
3. Playback Verification & Truthful Reporting
4. Idempotent Desktop Shortcut Creation
5. Resource Guardian & Diagnostics Opaque UI Styling
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.media_router import (
    parse_media_intent,
    clean_song_query,
    execute_media_command,
    YOUTUBE_URL,
    YOUTUBE_MUSIC_URL,
    DEFAULT_BROWSER,
)
from core.desktop_shortcut import (
    get_desktop_dir,
    find_target_executable,
    create_desktop_shortcut,
)


class TestMediaCommandRouting(unittest.TestCase):
    """Test Rules A, B, C, D, E for YouTube and YouTube Music integration."""

    def test_rule_a_open_youtube_defaults_to_chrome(self):
        # "YouTube kholo" / "Open YouTube" -> YOUTUBE_URL in Chrome by default
        for phrase in ("YouTube kholo", "Open YouTube", "youtube open karo", "launch youtube"):
            res = parse_media_intent(phrase)
            self.assertEqual(res["intent"], "OPEN_YOUTUBE", f"Failed intent for: {phrase}")
            self.assertEqual(res["browser"], "chrome", f"Failed browser for: {phrase}")
            self.assertEqual(res["url"], YOUTUBE_URL, f"Failed URL for: {phrase}")

    def test_rule_b_open_youtube_music_defaults_to_chrome(self):
        # "YouTube Music kholo" -> YOUTUBE_MUSIC_URL in Chrome by default
        for phrase in ("YouTube Music kholo", "Open YouTube Music", "youtube music open karo"):
            res = parse_media_intent(phrase)
            self.assertEqual(res["intent"], "OPEN_YOUTUBE_MUSIC", f"Failed intent for: {phrase}")
            self.assertEqual(res["browser"], "chrome", f"Failed browser for: {phrase}")
            self.assertEqual(res["url"], YOUTUBE_MUSIC_URL, f"Failed URL for: {phrase}")

    def test_rule_c_play_song_routes_to_youtube_music(self):
        # "Play [song name]" / "[song name] music play karo" -> YouTube Music auto-playback in Chrome
        test_cases = [
            ("Play Kesariya", "Kesariya"),
            ("Kesariya music play karo", "Kesariya"),
            ("Believer song play karo", "Believer"),
            ("Play Kesariya by Arijit Singh", "Kesariya by Arijit Singh"),
            ("listen to Despacito", "Despacito"),
            ("Channa Mereya gana sunao", "Channa Mereya"),
        ]
        for phrase, expected_song in test_cases:
            res = parse_media_intent(phrase)
            self.assertEqual(res["intent"], "PLAY_MUSIC", f"Failed intent for: {phrase}")
            self.assertEqual(res["service"], "youtube_music", f"Failed service for: {phrase}")
            self.assertEqual(res["browser"], "chrome", f"Failed browser for: {phrase}")
            self.assertEqual(res["query"].lower(), expected_song.lower(), f"Failed song extraction for: {phrase}")

    def test_rule_d_chrome_explicit_play_routes_to_regular_youtube(self):
        # "Chrome mein [song name] play karo" -> Regular YouTube in Chrome (NOT redirected to Music)
        test_cases = [
            ("Chrome mein Kesariya play karo", "Kesariya"),
            ("play Believer in Chrome", "Believer"),
            ("Chrome me shape of you play karo", "shape of you"),
        ]
        for phrase, expected_song in test_cases:
            res = parse_media_intent(phrase)
            self.assertEqual(res["intent"], "PLAY_YOUTUBE", f"Rule D intent failed for: {phrase}")
            self.assertEqual(res["service"], "youtube", f"Rule D service failed for: {phrase}")
            self.assertEqual(res["browser"], "chrome", f"Rule D browser failed for: {phrase}")
            self.assertEqual(res["query"].lower(), expected_song.lower(), f"Rule D query failed for: {phrase}")

    def test_rule_e_explicit_browser_requests(self):
        # "Brave mein YouTube kholo" -> Brave with YOUTUBE_URL
        res_brave_yt = parse_media_intent("Brave mein YouTube kholo")
        self.assertEqual(res_brave_yt["intent"], "OPEN_YOUTUBE")
        self.assertEqual(res_brave_yt["browser"], "brave")
        self.assertEqual(res_brave_yt["url"], YOUTUBE_URL)

        # "Chrome mein YouTube kholo" -> Chrome with YOUTUBE_URL
        res_chrome_yt = parse_media_intent("Chrome mein YouTube kholo")
        self.assertEqual(res_chrome_yt["intent"], "OPEN_YOUTUBE")
        self.assertEqual(res_chrome_yt["browser"], "chrome")
        self.assertEqual(res_chrome_yt["url"], YOUTUBE_URL)

        # "Brave mein Kesariya play karo" -> Brave with YouTube Music
        res_brave_music = parse_media_intent("Brave mein Kesariya play karo")
        self.assertEqual(res_brave_music["intent"], "PLAY_MUSIC")
        self.assertEqual(res_brave_music["browser"], "brave")
        self.assertEqual(res_brave_music["query"].lower(), "kesariya")

    def test_rule_f_specific_playback_conditions(self):
        """Test specific playback target conditions: YouTube Music, YouTube, and Brave YouTube."""
        # 1. 'play in youtube music' -> YouTube Music
        res_ytm = parse_media_intent("play Kesariya in youtube music")
        self.assertEqual(res_ytm["intent"], "PLAY_MUSIC")
        self.assertEqual(res_ytm["service"], "youtube_music")
        self.assertEqual(res_ytm["browser"], "chrome")
        self.assertEqual(res_ytm["query"].lower(), "kesariya")

        # 2. 'play in youtube' -> Regular YouTube
        res_yt = parse_media_intent("play Believer in youtube")
        self.assertEqual(res_yt["intent"], "PLAY_YOUTUBE")
        self.assertEqual(res_yt["service"], "youtube")
        self.assertEqual(res_yt["browser"], "chrome")
        self.assertEqual(res_yt["query"].lower(), "believer")

        # 3. 'play in brave youtube' -> Brave browser YouTube
        res_brave_yt = parse_media_intent("play Despacito in brave youtube")
        self.assertEqual(res_brave_yt["intent"], "PLAY_YOUTUBE")
        self.assertEqual(res_brave_yt["service"], "youtube")
        self.assertEqual(res_brave_yt["browser"], "brave")
        self.assertEqual(res_brave_yt["query"].lower(), "despacito")

        res_brave_yt2 = parse_media_intent("play in brave youtube Believer")
        self.assertEqual(res_brave_yt2["intent"], "PLAY_YOUTUBE")
        self.assertEqual(res_brave_yt2["service"], "youtube")
        self.assertEqual(res_brave_yt2["browser"], "brave")
        self.assertEqual(res_brave_yt2["query"].lower(), "believer")

    @patch("core.media_router.find_chrome_executable", return_value=None)
    def test_never_silently_fall_back_to_brave_when_chrome_missing(self, mock_find_chrome):
        # If Chrome is unavailable, return error rather than opening Brave
        intent = {
            "intent": "OPEN_YOUTUBE",
            "service": "youtube",
            "browser": "chrome",
            "query": "",
            "url": YOUTUBE_URL
        }
        ok, msg, data = execute_media_command(intent)
        self.assertFalse(ok)
        self.assertIn("not installed", msg.lower())
        self.assertEqual(data.get("browser"), "chrome")


class TestMediaPlaybackVerification(unittest.TestCase):
    """Test truthfulness in reporting playback status."""

    @patch("core.media_router._resolve_video_id", return_value="BddP6PYo2gs")
    @patch("core.media_router.launch_chrome", return_value=(True, "Opened Chrome"))
    @patch("core.media_router.find_chrome_executable", return_value=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    def test_playback_verified_when_video_id_resolved(self, mock_exe, mock_launch, mock_resolve):
        intent = {
            "intent": "PLAY_MUSIC",
            "service": "youtube_music",
            "browser": "chrome",
            "query": "Kesariya",
        }
        ok, msg, data = execute_media_command(intent)
        self.assertTrue(ok)
        self.assertTrue(data["verified"])
        self.assertEqual(data["status"], "playing")
        self.assertIn("https://music.youtube.com/watch?v=BddP6PYo2gs", data["url"])
        self.assertIn("Playing 'Kesariya'", msg)

    @patch("core.media_router._resolve_video_id", return_value=None)
    @patch("core.media_router.launch_chrome", return_value=(True, "Opened Chrome"))
    @patch("core.media_router.find_chrome_executable", return_value=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    def test_search_fallback_reports_truthfully_manual_selection_required(self, mock_exe, mock_launch, mock_resolve):
        intent = {
            "intent": "PLAY_MUSIC",
            "service": "youtube_music",
            "browser": "chrome",
            "query": "RareUnknownTrack",
        }
        ok, msg, data = execute_media_command(intent)
        self.assertTrue(ok)
        self.assertFalse(data["verified"])
        self.assertEqual(data["status"], "opened")
        self.assertIn("manual selection required", msg.lower())
        self.assertIn("https://music.youtube.com/search?q=RareUnknownTrack", data["url"])


class TestDesktopShortcutCreation(unittest.TestCase):
    """Test dynamic path resolution and idempotency of Desktop shortcut creation."""

    def test_get_desktop_dir(self):
        d = get_desktop_dir()
        self.assertIsNotNone(d)
        self.assertTrue(d.is_dir(), f"Desktop directory must exist: {d}")

    def test_find_target_executable(self):
        exe = find_target_executable(BASE_DIR)
        self.assertTrue(exe.is_file(), f"Target executable must exist: {exe}")
        self.assertTrue(str(exe).lower().endswith("pythonw.exe") or str(exe).lower().endswith("python.exe"))

    def test_idempotent_shortcut_creation(self):
        # First creation
        ok1, msg1 = create_desktop_shortcut(force=False)
        self.assertTrue(ok1, f"Shortcut creation failed: {msg1}")

        desktop = get_desktop_dir()
        shortcut_path = desktop / "Jarvis.lnk"
        self.assertTrue(shortcut_path.is_file(), f"Shortcut file must exist on desktop: {shortcut_path}")

        # Second creation without force — must return True and detect existing shortcut
        ok2, msg2 = create_desktop_shortcut(force=False)
        self.assertTrue(ok2)
        self.assertIn("already exists", msg2.lower())


class TestResourceGuardianOpaqueUI(unittest.TestCase):
    """Test that Resource Diagnostics Overlay has 100% opaque styling with NO glassmorphism."""

    def test_overlay_opaque_attributes(self):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        app = QApplication.instance() or QApplication(sys.argv)

        from ui_resource_guardian import ResourceDiagnosticsOverlay
        ov = ResourceDiagnosticsOverlay()

        # Check Opaque Paint Event & WA_StyledBackground
        self.assertTrue(ov.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent),
                        "WA_OpaquePaintEvent must be True to prevent underlying UI bleeding through")
        self.assertTrue(ov.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
                        "WA_StyledBackground must be True for clean solid CSS rendering")
        self.assertTrue(ov.autoFillBackground())

        # Inspect stylesheet for solid background color
        sheet = ov.styleSheet()
        self.assertIn("background-color: #020b14", sheet, "Must have solid dark background #020b14")
        self.assertNotIn("rgba(", sheet, "ResourceDiagnosticsOverlay root stylesheet must NOT have translucent rgba")


if __name__ == "__main__":
    unittest.main()
