"""
test_resource_guardian_and_palette.py — Verification suite for:
1. Smart Resource Guardian (telemetry, bounded history, leak diagnostics, profiles)
2. Smart Command Palette (discovery, fuzzy/substring search, MRU, safe dispatch)
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.resource_guardian import (
    ResourceGuardian,
    ResourceSnapshot,
    PROFILE_LOW_RAM,
    PROFILE_BALANCED,
    PROFILE_FULL_EXPERIENCE,
    SUSTAINED_GROWTH_MIN_MB,
)
from core.command_palette import CommandPaletteRegistry, CommandItem
from memory.config_manager import get_resource_profile, save_resource_profile


class TestResourceGuardianMetrics(unittest.TestCase):
    def setUp(self):
        self.guardian = ResourceGuardian()

    def test_snapshot_capture(self):
        snap = self.guardian.capture_snapshot(state="IDLE")
        self.assertIsInstance(snap, ResourceSnapshot)
        self.assertGreater(snap.process_rss_mb, 0.0, "Process RSS must be > 0 MB")
        self.assertGreaterEqual(snap.system_ram_percent, 0.0)
        self.assertLessEqual(snap.system_ram_percent, 100.0)
        self.assertGreater(snap.system_ram_total_gb, 0.0)
        self.assertEqual(snap.state, "IDLE")

    def test_separation_of_process_and_system_ram(self):
        snap = self.guardian.capture_snapshot()
        # Process RSS is in MB (typically 50-600MB)
        # System total RAM is in GB (typically 4-128GB)
        self.assertNotEqual(snap.process_rss_mb, snap.system_ram_percent)
        self.assertGreater(snap.system_ram_total_gb, 1.0)

    def test_bounded_history_length(self):
        # Insert 80 snapshots
        for i in range(80):
            self.guardian.capture_snapshot()
        hist = self.guardian.get_history()
        self.assertEqual(len(hist), 60, "History must be strictly bounded to 60 samples")

    def test_state_transitions(self):
        self.guardian.set_state("VOICE_ACTIVE")
        snap = self.guardian.capture_snapshot()
        self.assertEqual(snap.state, "VOICE_ACTIVE")

        self.guardian.set_optional_feature_active("camera", True)
        self.guardian.set_state("IDLE")  # If optional feature is active, sets to OPTIONAL_FEATURES
        self.guardian.set_optional_feature_active("camera", True)
        self.assertEqual(self.guardian._state, "OPTIONAL_FEATURES")

        self.guardian.set_optional_feature_active("camera", False)
        self.assertEqual(self.guardian._state, "IDLE")


class TestResourceGuardianDiagnostics(unittest.TestCase):
    def setUp(self):
        self.guardian = ResourceGuardian()

    def test_stable_memory_analysis(self):
        # Fill history with constant memory
        for _ in range(25):
            self.guardian._history.append(ResourceSnapshot(
                timestamp=100.0,
                process_rss_mb=120.0,
                process_cpu_percent=1.0,
                system_cpu_percent=10.0,
                system_ram_percent=45.0,
                system_ram_available_gb=8.0,
                system_ram_total_gb=16.0,
                state="IDLE"
            ))
        diag = self.guardian.analyze_memory()
        self.assertEqual(diag["growth_status"], "STABLE")
        self.assertIn("normal", diag["recommendation"].lower())

    def test_sustained_growth_detection(self):
        # Simulate monotonic rise exceeding SUSTAINED_GROWTH_MIN_MB (e.g. 100MB to 150MB)
        base_t = 1000.0
        for i in range(30):
            self.guardian._history.append(ResourceSnapshot(
                timestamp=base_t + i * 2.0,
                process_rss_mb=100.0 + i * 1.5,  # increases by 45MB monotonically
                process_cpu_percent=2.0,
                system_cpu_percent=15.0,
                system_ram_percent=50.0,
                system_ram_available_gb=8.0,
                system_ram_total_gb=16.0,
                state="IDLE"
            ))
        diag = self.guardian.analyze_memory()
        self.assertEqual(diag["growth_status"], "SUSTAINED_GROWTH")
        self.assertGreater(diag["growth_rate_mb_min"], 0.0)
        self.assertIn("Process RAM has increased", diag["recommendation"])

    def test_startup_tracking(self):
        tracker = self.guardian.startup_tracker
        tracker.mark_start()
        tracker.record_stage("TestStage1", 0.045, "Loaded 12 tools")
        tracker.record_stage("TestStage2", 0.015, "Ready")
        summary = tracker.get_summary()
        self.assertEqual(len(summary["stages"]), 2)
        self.assertEqual(summary["stages"][0]["name"], "TestStage1")
        self.assertGreater(summary["total_tracked_duration_s"], 0.05)
        self.assertIn("openwakeword", summary["optional_modules"])

    def test_worker_registration(self):
        self.guardian.register_worker("test_worker", "Background poller", is_alive_fn=lambda: True)
        workers = self.guardian.get_workers_status()
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["name"], "test_worker")
        self.assertTrue(workers[0]["is_alive"])


class TestResourceProfiles(unittest.TestCase):
    def setUp(self):
        self.guardian = ResourceGuardian()

    def test_profile_persistence(self):
        initial = get_resource_profile()
        try:
            save_resource_profile(PROFILE_LOW_RAM)
            self.assertEqual(get_resource_profile(), PROFILE_LOW_RAM)

            save_resource_profile(PROFILE_FULL_EXPERIENCE)
            self.assertEqual(get_resource_profile(), PROFILE_FULL_EXPERIENCE)

            save_resource_profile(PROFILE_BALANCED)
            self.assertEqual(get_resource_profile(), PROFILE_BALANCED)
        finally:
            save_resource_profile(initial)

    def test_profile_tuning_parameters(self):
        self.guardian.set_profile(PROFILE_LOW_RAM)
        self.assertEqual(self.guardian.get_telemetry_interval_sec(), 20.0)
        self.assertEqual(self.guardian.get_dust_particles_count(), 0)
        self.assertEqual(self.guardian.get_wave_steps(), 36)
        self.assertEqual(self.guardian.get_hud_timer_ms(), 33)
        self.assertFalse(self.guardian.is_3d_avatar_enabled())
        self.assertEqual(self.guardian.get_anim_duration_ms(), 70)
        self.assertFalse(self.guardian.is_sparkline_live_enabled())
        self.assertFalse(self.guardian.is_sensor_tracking_enabled())

        self.guardian.set_profile(PROFILE_BALANCED)
        self.assertEqual(self.guardian.get_telemetry_interval_sec(), 3.0)
        self.assertEqual(self.guardian.get_dust_particles_count(), 14)
        self.assertEqual(self.guardian.get_wave_steps(), 48)
        self.assertEqual(self.guardian.get_hud_timer_ms(), 33)
        self.assertTrue(self.guardian.is_3d_avatar_enabled())
        self.assertEqual(self.guardian.get_anim_duration_ms(), 90)
        self.assertTrue(self.guardian.is_sparkline_live_enabled())
        self.assertTrue(self.guardian.is_sensor_tracking_enabled())

        self.guardian.set_profile(PROFILE_FULL_EXPERIENCE)
        self.assertEqual(self.guardian.get_telemetry_interval_sec(), 1.5)
        self.assertEqual(self.guardian.get_dust_particles_count(), 35)
        self.assertEqual(self.guardian.get_wave_steps(), 72)
        self.assertEqual(self.guardian.get_hud_timer_ms(), 16)
        self.assertTrue(self.guardian.is_3d_avatar_enabled())
        self.assertEqual(self.guardian.get_anim_duration_ms(), 130)
        self.assertTrue(self.guardian.is_sparkline_live_enabled())

    def test_invalid_profile_fallback(self):
        res = self.guardian.set_profile("nonexistent_profile")
        self.assertEqual(res, PROFILE_BALANCED)

    def test_profile_listeners(self):
        calls = []
        listener = lambda p: calls.append(p)
        self.guardian.add_profile_listener(listener)
        self.guardian.set_profile(PROFILE_LOW_RAM)
        self.guardian.set_profile(PROFILE_BALANCED)
        self.assertEqual(calls, [PROFILE_LOW_RAM, PROFILE_BALANCED])
        self.guardian.remove_profile_listener(listener)


class TestCommandPaletteRegistry(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.reg = CommandPaletteRegistry(notify_log=lambda m: self.logs.append(m))
        self.cmd_executed = False

        def handler():
            self.cmd_executed = True
            return "Command OK"

        self.reg.register(CommandItem(
            id="panel.memory",
            title="Open Memory Bank",
            description="Inspect saved memories",
            category="SYSTEM",
            shortcut="Ctrl+M",
            handler=handler
        ))
        self.reg.register(CommandItem(
            id="view.fullscreen",
            title="Toggle Fullscreen",
            description="Toggle full screen HUD",
            category="VIEW",
            shortcut="F11",
            handler=lambda: "Fullscreen toggled"
        ))
        self.reg.register(CommandItem(
            id="action.open_app",
            title="Action: open_app",
            description="Launch desktop application",
            category="ACTION",
            requires_params=True,
            param_names=["app_name"]
        ))
        self.reg.register(CommandItem(
            id="plugin.disabled_plugin",
            title="Plugin: disabled_plugin",
            description="A disabled plugin",
            category="PLUGIN",
            is_available=False,
            unavailable_reason="Plugin is disabled in Plugin Manager."
        ))

    def test_filtering_case_insensitive_and_partial(self):
        # Substring / partial matches
        res_mem = self.reg.filter_commands("mem")
        self.assertEqual(len(res_mem), 1)
        self.assertEqual(res_mem[0].id, "panel.memory")

        res_full = self.reg.filter_commands("FULL")
        self.assertEqual(len(res_full), 1)
        self.assertEqual(res_full[0].id, "view.fullscreen")

        res_action = self.reg.filter_commands("open_app")
        self.assertEqual(len(res_action), 1)
        self.assertEqual(res_action[0].id, "action.open_app")

        # Non-matching query
        res_none = self.reg.filter_commands("xyz123_not_found")
        self.assertEqual(len(res_none), 0)

    def test_empty_query_returns_all_with_mru(self):
        all_cmds = self.reg.filter_commands("")
        self.assertEqual(len(all_cmds), 4)

        # Execute one command to place it in MRU
        self.reg.execute("panel.memory")
        mru_cmds = self.reg.filter_commands("")
        # The first item should be the recently used one
        self.assertEqual(mru_cmds[0].id, "panel.memory")
        self.assertEqual(mru_cmds[0].category, "RECENT")

    def test_successful_dispatch(self):
        ok, msg = self.reg.execute("panel.memory")
        self.assertTrue(ok)
        self.assertTrue(self.cmd_executed)
        self.assertEqual(msg, "Command OK")

    def test_unavailable_command_dispatch(self):
        ok, msg = self.reg.execute("plugin.disabled_plugin")
        self.assertFalse(ok)
        self.assertIn("disabled", msg)

    def test_command_requiring_parameters(self):
        ok, msg = self.reg.execute("action.open_app")
        self.assertFalse(ok)
        self.assertIn("requires parameters", msg)

    def test_invalid_command_dispatch(self):
        ok, msg = self.reg.execute("nonexistent_id")
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_handler_exception_safety(self):
        def crashing_handler():
            raise RuntimeError("Simulated crash")

        self.reg.register(CommandItem("crash_cmd", "Crasher", handler=crashing_handler))
        ok, msg = self.reg.execute("crash_cmd")
        self.assertFalse(ok)
        self.assertIn("failed", msg)


class TestUIOverlayIntegration(unittest.TestCase):
    def test_resource_widgets_initialization(self):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        from ui_resource_guardian import ResourceSparkline, ResourceDiagnosticsOverlay
        from ui_command_palette import CommandPaletteOverlay

        sparkline = ResourceSparkline()
        self.assertEqual(sparkline.height(), 46)

        diag_ov = ResourceDiagnosticsOverlay()
        self.assertEqual(diag_ov.width(), ResourceDiagnosticsOverlay._OW)
        self.assertEqual(diag_ov.height(), ResourceDiagnosticsOverlay._OH)

        reg = CommandPaletteRegistry()
        reg.register(CommandItem("test", "Test Item"))
        cmd_ov = CommandPaletteOverlay(reg)
        self.assertEqual(cmd_ov.width(), CommandPaletteOverlay._OW)
        self.assertEqual(cmd_ov.height(), CommandPaletteOverlay._OH)

        # Trigger search and refresh
        cmd_ov._refresh_list("Test")
        self.assertEqual(cmd_ov._list.count(), 1)


if __name__ == "__main__":
    unittest.main()
