from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

# Qt's video backend prints the ffmpeg stream banner — codec, bitrate, the
# whole signed googlevideo URL — to the console for every stream it opens. That
# is two screenfuls per video, it looks like an error to anyone reading the log,
# and it puts a URL carrying the viewer's IP address into a terminal people
# paste into bug reports. Silenced here, before Qt initialises its logging.
# An explicit setting from the user is left alone.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PyQt6.QtCore import (
    QEasingCurve, QLineF, QMimeData, QObject, QParallelAnimationGroup, QPointF,
    QPoint, QPropertyAnimation, QRect, QRectF, QSize, QSizeF, Qt, QTimer,
    QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QKeySequence, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient, QShortcut,
)
# Video playback for the HUD. Part of PyQt6, so it costs no new dependency —
# but the multimedia plugins are a separate piece of the Qt install and can be
# absent on a stripped-down system, so a failure here disables one feature
# rather than stopping JARVIS from starting.
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
    HAVE_VIDEO = True
except Exception as _e:            # noqa: BLE001 - reported, never fatal
    QAudioOutput = QMediaPlayer = QGraphicsVideoItem = None
    HAVE_VIDEO = False
    print(f"[Video] playback unavailable ({_e}) — the HUD will not show video.")

from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QGraphicsScene, QGraphicsView,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QProgressBar, QSlider,
)

try:
    from core.avatar import HoloAvatar
except Exception:      # pragma: no cover — HUD must never die over cosmetics
    HoloAvatar = None

from core.resource_guardian import (
    ResourceGuardian,
    PROFILE_LOW_RAM,
    PROFILE_BALANCED,
    PROFILE_FULL_EXPERIENCE,
    PROFILE_DISPLAY_NAMES,
)
from core.command_palette import CommandPaletteRegistry, CommandItem
from ui_resource_guardian import ResourceSparkline, ResourceDiagnosticsOverlay
from ui_command_palette import CommandPaletteOverlay


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"


def _read_full_config() -> dict:
    """Read api_keys.json config dict. Returns {} on any error."""
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Single source of truth for the release name — the window title, the header
# badge and the readme must never disagree again.
APP_VERSION  = ""
APP_PROTOCOL = "SECURE"

_DEFAULT_W, _DEFAULT_H = 980, 700
_MIN_W,     _MIN_H     = 820, 580
_LEFT_W  = 148
_RIGHT_W = 340

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


from theme import ThemeColors, THEME_PRESETS as _THEME_PRESETS, HUD_PRESETS as _HUD_PRESETS, LAYOUT_PRESETS as _LAYOUT_PRESETS, CSS_VARIABLES

class C:
    # Deep ocean dark navy background
    BG        = ThemeColors.BG
    PANEL     = ThemeColors.PANEL
    PANEL2    = ThemeColors.PANEL2
    # Thin warm brass & gold borders
    BORDER    = ThemeColors.BORDER
    BORDER_B  = ThemeColors.BORDER_B
    BORDER_A  = ThemeColors.BORDER_A
    # Holographic cyan/teal glow
    PRI       = ThemeColors.PRI
    PRI_DIM   = ThemeColors.PRI_DIM
    PRI_GHO   = ThemeColors.PRI_GHO
    # Warm brass & gold
    BRASS     = ThemeColors.BRASS
    BRASS_BRIGHT = ThemeColors.BRASS_BRIGHT
    BRASS_GHO = ThemeColors.BRASS_GHO
    # Warm amber
    ACC       = ThemeColors.ACC
    ACC2      = ThemeColors.ACC2
    ACC_GHO   = ThemeColors.ACC_GHO
    # System status (no purple anywhere)
    GREEN     = ThemeColors.GREEN
    GREEN_D   = ThemeColors.GREEN_D
    RED       = ThemeColors.RED
    MUTED_C   = ThemeColors.MUTED_C
    # Monospace typography
    TEXT      = ThemeColors.TEXT
    TEXT_DIM  = ThemeColors.TEXT_DIM
    TEXT_MED  = ThemeColors.TEXT_MED
    WHITE     = ThemeColors.WHITE
    DARK      = ThemeColors.DARK
    BAR_BG    = ThemeColors.BAR_BG


# Keys tied to the accent colour — status colours (ACC, GREEN, RED…) stay fixed
_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG", "BRASS", "BRASS_BRIGHT", "BRASS_GHO", "ACC",
)
_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}

DEFAULT_UI_COLOR = "#00e5ff" 


def apply_ui_accent(accent_hex: str) -> bool:
    """
    Re-derives the whole teal-family palette from the chosen accent colour
    (hue shift — brightness/saturation ratios are preserved, design stays intact).
    Painted elements (HUD, waveform, metrics) pick up the new colour on the next
    frame; stylesheet-based panels pick it up when they are rebuilt.
    """
    import colorsys

    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _parse_color(c: str) -> tuple[float, float, float, float | None]:
        c = (c or "").strip().lower()
        if c.startswith("#"):
            if len(c) == 7:
                return int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0, int(c[5:7], 16) / 255.0, None
            elif len(c) == 9:
                return int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0, int(c[5:7], 16) / 255.0, int(c[7:9], 16) / 255.0
        elif c.startswith("rgba"):
            parts = c[c.find("(") + 1 : c.rfind(")")].split(",")
            return float(parts[0].strip()) / 255.0, float(parts[1].strip()) / 255.0, float(parts[2].strip()) / 255.0, float(parts[3].strip())
        elif c.startswith("rgb"):
            parts = c[c.find("(") + 1 : c.rfind(")")].split(",")
            return float(parts[0].strip()) / 255.0, float(parts[1].strip()) / 255.0, float(parts[2].strip()) / 255.0, None
        return 0.0, 0.0, 0.0, None

    def _color_to_hsv(c: str) -> tuple[float, float, float, float | None]:
        r, g, b, a = _parse_color(c)
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        return h, s, v, a

    acc_h, acc_s, _av, _ = _color_to_hsv(accent_hex)
    is_matrix_green = accent_hex in ("#00ff41", "#00ff66", "#00e676", "#10b981", "#00ff00") or (0.25 <= acc_h <= 0.44 and acc_s > 0.35)

    if is_matrix_green:
        green_palette = {
            "BG": "#000000",
            "DARK": "#000000",
            "BAR_BG": "#020703",
            "PANEL": "rgba(2, 10, 4, 0.90)",
            "PANEL2": "rgba(3, 14, 6, 0.94)",
            "BORDER": "rgba(0, 255, 65, 0.42)",
            "BORDER_B": "rgba(0, 255, 65, 0.75)",
            "BORDER_A": "rgba(0, 255, 65, 0.50)",
            "PRI": accent_hex,
            "PRI_DIM": "#008f24",
            "PRI_GHO": "rgba(0, 255, 65, 0.15)",
            "TEXT": "#00ff41",
            "TEXT_DIM": "#1b7a32",
            "TEXT_MED": "#33cc55",
            "WHITE": "#d4ffe0",
            "BRASS": "#00ff41",
            "BRASS_BRIGHT": "#33ff66",
            "BRASS_GHO": "rgba(0, 255, 65, 0.18)",
            "ACC": "#00ff41",
        }
        for key, val in green_palette.items():
            setattr(C, key, val)
        return True

    C.BRASS = ThemeColors.BRASS
    C.BRASS_BRIGHT = ThemeColors.BRASS_BRIGHT
    C.BRASS_GHO = ThemeColors.BRASS_GHO
    C.ACC = ThemeColors.ACC

    base_h = _color_to_hsv(_PALETTE_DEFAULTS["PRI"])[0]
    dh   = acc_h - base_h
    grey = acc_s < 0.08   # near-grey accent → the whole theme is desaturated

    for key, hex0 in _PALETTE_DEFAULTS.items():
        try:
            h, s, v, a = _color_to_hsv(hex0)
            if grey:
                s *= 0.15
            r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
            if a is not None:
                alpha_str = f"{a:.2f}".rstrip("0").rstrip(".") if a != int(a) else str(int(a))
                val = f"rgba({int(r * 255 + 0.5)}, {int(g * 255 + 0.5)}, {int(b * 255 + 0.5)}, {alpha_str})"
            else:
                val = "#{:02x}{:02x}{:02x}".format(
                    int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))
            setattr(C, key, val)
        except Exception:
            pass
    return True


def current_palette() -> dict[str, str]:
    """A snapshot of the accent-linked colours currently on class C."""
    return {k: getattr(C, k) for k in _HUE_LINKED}


def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    """
    LIVE full theme change. Replaces the old palette colours with the new ones
    in EVERY widget's stylesheet across the app and repaints them. This way the
    colour change applies INSTANTLY across the whole interface — panels, buttons,
    borders included — not just the painted elements. No restart needed.
    """
    mapping = {old[k].lower(): new[k].lower()
               for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                s2 = ss
                for o, n in mapping.items():
                    if o in s2:
                        s2 = s2.replace(o, n)
                if s2 != ss:
                    w.setStyleSheet(s2)
            w.update()
        except Exception:
            pass


def qcol(h: str, a: int = 255) -> QColor:
    if not h:
        return QColor(0, 0, 0, a)
    h_str = str(h).strip()
    if h_str.startswith("rgba"):
        try:
            parts = h_str[h_str.find("(") + 1 : h_str.rfind(")")].split(",")
            r = int(float(parts[0].strip()))
            g = int(float(parts[1].strip()))
            b = int(float(parts[2].strip()))
            alpha_val = float(parts[3].strip())
            alpha_int = int(alpha_val * 255 + 0.5) if (alpha_val <= 1.0 and "." in parts[3]) else int(alpha_val)
            if a != 255:
                alpha_int = int(alpha_int * (a / 255.0))
            return QColor(r, g, b, alpha_int)
        except Exception:
            pass
    elif h_str.startswith("rgb"):
        try:
            parts = h_str[h_str.find("(") + 1 : h_str.rfind(")")].split(",")
            r = int(float(parts[0].strip()))
            g = int(float(parts[1].strip()))
            b = int(float(parts[2].strip()))
            return QColor(r, g, b, a)
        except Exception:
            pass
    c = QColor(h_str)
    c.setAlpha(a)
    return c


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self.proc_ram = 0.0
        self.proc_cpu = 0.0
        self.sys_ram_avail = 0.0
        self.sys_ram_total = 0.0
        self.state = "IDLE"
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        # Probe caches — GPU (NVML) and temperature (WMI) are the expensive
        # queries; initialise their handles once and reuse them instead of
        # rebuilding a connection on every poll.
        self._slow_tick = 0            # gpu/temp refreshed every 3rd cycle
        self._pynvml    = None         # cached pynvml module + device handle
        self._pynvml_h  = None
        self._pynvml_ok = None         # None=untested, False=unavailable here
        self._nv_unix   = None         # cached (lib, dev) for Linux/macOS NVML
        self._wmi_conn  = None         # cached WMI connection (creating one is slow)
        self._wmi_ok    = None         # None=untested, False=unavailable here

        # Detect or load cached hardware capabilities (GPU & ACPI Temperature)
        from memory.config_manager import get_hardware_caps, save_hardware_caps
        caps = get_hardware_caps()
        if caps is None:
            # First launch probe: detect whether GPU and Temperature sensors physically exist
            gpu_initial = self._probe_gpu()
            temp_initial = self._probe_temp()
            self._has_gpu = bool(gpu_initial >= 0.0)
            self._has_temp = bool(temp_initial >= 0.0)
            try:
                save_hardware_caps({"has_gpu": self._has_gpu, "has_temp": self._has_temp})
            except Exception:
                pass
        else:
            self._has_gpu = bool(caps.get("has_gpu", False))
            self._has_temp = bool(caps.get("has_temp", False))

        if not self._has_gpu:
            self._pynvml_ok = False
            global _nvml_ok
            _nvml_ok = False
            self.gpu = -1.0

        if not self._has_temp:
            self._wmi_ok = False
            self.tmp = -1.0

        t = threading.Thread(target=self._loop, daemon=True, name="sys-metrics-poller")
        t.start()
        ResourceGuardian.get_instance().register_worker("sys_metrics", "System & Process telemetry poller", thread_ref=t, is_essential=True)

    def _loop(self):
        last_trim = time.time()
        while self._running:
            try:
                self._update()
                now = time.time()
                if now - last_trim >= 35.0:
                    last_trim = now
                    prof = ResourceGuardian.get_instance().get_profile()
                    if prof in ("balanced", "low_ram"):
                        try:
                            from core.ram_cleaner import release_unused_ram
                            release_unused_ram()
                        except Exception:
                            pass
            except Exception:
                pass
            interval = ResourceGuardian.get_instance().get_telemetry_interval_sec()
            time.sleep(interval)

    def _update(self):
        prof = ResourceGuardian.get_instance().get_profile()
        if prof == "low_ram":
            # In Low RAM mode: bypass expensive WMI, NVML, network counter deltas, and process sweeps!
            snap = ResourceGuardian.get_instance().capture_snapshot()
            with self._lock:
                self.cpu = snap.system_cpu_percent
                self.mem = snap.system_ram_percent
                self.net = 0.0
                self.gpu = -1.0
                self.tmp = -1.0
                self.proc_ram = snap.process_rss_mb
                self.proc_cpu = snap.process_cpu_percent
                self.sys_ram_avail = snap.system_ram_available_gb
                self.sys_ram_total = snap.system_ram_total_gb
                self.state = snap.state
            return

        snap = ResourceGuardian.get_instance().capture_snapshot()
        cpu = snap.system_cpu_percent
        mem = snap.system_ram_percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        # GPU and temperature change slowly and are the most expensive probes
        # (NVML / WMI) — refresh them every 3rd cycle (~6 s) instead of every
        # cycle, reusing the previous reading in between.
        self._slow_tick = (self._slow_tick + 1) % 3
        if self._slow_tick == 1:
            gpu = self._get_gpu()
            tmp = self._get_temp()
        else:
            gpu = self.gpu
            tmp = self.tmp

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp
            self.proc_ram = snap.process_rss_mb
            self.proc_cpu = snap.process_cpu_percent
            self.sys_ram_avail = snap.system_ram_available_gb
            self.sys_ram_total = snap.system_ram_total_gb
            self.state = snap.state
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _probe_gpu(self) -> float:
        return self._probe_gpu_internal()

    def _probe_temp(self) -> float:
        return self._probe_temp_internal()

    def _get_gpu(self) -> float:
        if not getattr(self, "_has_gpu", True):
            return -1.0
        return self._probe_gpu_internal()

    def _probe_gpu_internal(self) -> float:
        # pynvml — subprocess-free; initialise once and reuse the handle.
        # Re-initialising NVML on every poll is slow, so cache it and stop
        # retrying pynvml entirely once it proves unavailable here.
        if self._pynvml_ok is not False:
            try:
                if self._pynvml_h is None:
                    import pynvml  # type: ignore
                    pynvml.nvmlInit()
                    self._pynvml    = pynvml
                    self._pynvml_h  = pynvml.nvmlDeviceGetHandleByIndex(0)
                    self._pynvml_ok = True
                return float(self._pynvml.nvmlDeviceGetUtilizationRates(self._pynvml_h).gpu)
            except Exception:
                self._pynvml_ok = False

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes — init once, reuse
        try:
            import ctypes

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            if self._nv_unix is None:
                _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"
                nv = ctypes.CDLL(_lib)
                nv.nvmlInit_v2()
                dev = ctypes.c_void_p()
                nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
                self._nv_unix = (nv, dev)

            nv, dev = self._nv_unix
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        if not getattr(self, "_has_temp", True):
            return -1.0
        return self._probe_temp_internal()

    def _probe_temp_internal(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess). Reuse a single
        # connection — building a fresh wmi.WMI() on every poll spins up a COM
        # connection each time and is very slow. Give up after one failure.
        if _OS == "Windows" and self._wmi_ok is not False:
            try:
                if self._wmi_conn is None:
                    import wmi  # type: ignore
                    self._wmi_conn = wmi.WMI(namespace="root/wmi")
                tz = self._wmi_conn.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                self._wmi_ok   = False
                self._wmi_conn = None

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
                "proc_ram": self.proc_ram,
                "proc_cpu": self.proc_cpu,
                "sys_ram_avail": self.sys_ram_avail,
                "sys_ram_total": self.sys_ram_total,
                "state": self.state,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, assistant_name: str = "J.A.R.V.I.S", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name

        # The holographic head that fills the HUD. If it could not be imported
        # we fall back to the old glowing core so the panel is never empty.
        self._avatar = None
        if HoloAvatar is not None:
            try:
                self._avatar = HoloAvatar()
            except Exception:
                self._avatar = None

        # Which centrepiece to draw. Read once here and changed live by the
        # settings toggle; the avatar object is kept either way so switching
        # back is instant and costs no reload.
        try:
            from memory.config_manager import get_hud_style
            self.hud_style = get_hud_style()
        except Exception:
            self.hud_style = "face"
        self._core_phase = 0.0

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._step_t     = time.time()
        self._blink      = True
        self._blink_tick = 0

        # Rescaled-face cache: the smooth rescale is expensive, so we keep the
        # last result and only rebuild it when the (quantised) size changes.

        # Static grid-dot layer, pre-rendered once per size/theme into a pixmap
        # so paintEvent blits it in one call instead of thousands of drawPoint()s.
        self._grid_cache: QPixmap | None = None
        self._grid_key = None
        # Repaint throttle counter (idle frames drop to ~20 Hz — see _step()).
        self._paint_tick = 0

        # Live audio reactivity: _live_amp is written from the audio threads
        # (0.0–1.0), _amp_disp is the smoothed value the paint code reads.
        self._live_amp  = 0.0
        self._amp_disp  = 0.0
        # (frames, start_time, hop) posted by the playback thread — see
        # push_visemes(). None means "no schedule; use the plain level".
        self._visemes = None
        self._vis_i = None        # first schedule frame not yet handed to the mouth
        self._base_scale = 1.0    # slow "breathing" target; amp is added per-frame
        self._base_halo  = 55.0

        # Floating dust particles for Holographic Brass & Deep Ocean ambiance
        self._particles = [
            [random.uniform(0, 1400), random.uniform(0, 1000),
             random.uniform(-0.16, 0.16), random.uniform(-0.30, -0.05),
             random.uniform(1.2, 2.6), random.uniform(0.18, 0.45)]
            for _ in range(35)
        ]

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        # 33ms (~30 FPS) provides fluid visual fidelity while keeping CPU usage strictly under 15%
        self._tmr.start(33)

    def apply_resource_profile(self, profile: str) -> None:
        """Dynamic UI and timer trimming based on the active resource profile."""
        self._profile = profile
        rg = ResourceGuardian.get_instance()

        # Particles count trimming
        num_pt = rg.get_dust_particles_count()
        if num_pt == 0:
            self._particles = []
        else:
            self._particles = [
                [random.uniform(0, 1400), random.uniform(0, 1000),
                 random.uniform(-0.16, 0.16), random.uniform(-0.30, -0.05),
                 random.uniform(1.2, 2.6), random.uniform(0.18, 0.45)]
                for _ in range(num_pt)
            ]

        # Timer rate trimming
        tmr_ms = rg.get_hud_timer_ms()
        self._tmr.setInterval(tmr_ms)
        self.update()

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Ask the avatar to look somewhere for a moment (see HoloAvatar.glance)."""
        try:
            if self._avatar is not None:
                self._avatar.glance(dx, dy, hold)
        except Exception:
            pass

    def push_visemes(self, frames, hop: float, at: float) -> None:
        """Thread-safe: hand over a schedule of (level, openness, width) frames.

        The playback thread writes up to 200 ms of audio in one go, so a single
        averaged level would only move the mouth five times a second — enough to
        flap, nowhere near enough to articulate. It instead posts the whole
        slice's worth of 20 ms frames here and `_step()` plays them out against
        the wall clock, in step with the audio going to the speakers.

        `at` is the wall-clock time this batch will *begin to sound*, which the
        caller tracks as a playback cursor. It is not the time of the call, and
        the difference is the whole point: `stream.write` returns once the buffer
        accepts the samples, so consecutive batches are handed over far faster
        than they play. Anchoring each one to "now" made every batch start while
        its predecessor was still sounding, so each schedule replaced the last
        after a couple of frames and the mouth only ever played the opening
        instant of every 200 ms — the reason it did not match the words.

        Successive batches are therefore *appended* into one continuous
        timeline, not swapped in. A paragraph is one schedule; the mouth stops
        falling into a gap at every chunk boundary and having to climb back out.
        """
        try:
            if not frames:
                return
            hop = max(1e-3, float(hop))
            at = float(at)
            new = list(frames)
            cur = self._visemes
            if cur is not None:
                old, t0, ohop = cur
                if abs(ohop - hop) < 1e-6:
                    # Where in the existing timeline does this batch land?
                    i = int(round((at - t0) / hop))
                    if 0 <= i <= len(old) + 1:
                        # Continues (or slightly overlaps) what is already
                        # queued: extend rather than restart. Drop whatever has
                        # already been played so the list cannot grow without
                        # bound over a long reply.
                        merged = old[:i] + new
                        played = int((time.time() - t0) / hop) - 2
                        if played > 60:
                            merged = merged[played:]
                            t0 += played * hop
                            if self._vis_i is not None:
                                self._vis_i = max(0, self._vis_i - played)
                        self._visemes = (merged, t0, hop)
                        return
            self._visemes = (new, at, hop)
            self._vis_i = None
        except Exception:
            pass

    def set_audio_level(self, level: float) -> None:
        """Thread-safe entry point for the audio threads. Stores the louder of
        the incoming level and the current value so brief gaps between chunks
        don't make the waveform stutter; _step() decays it back down."""
        try:
            lv = float(level)
        except (TypeError, ValueError):
            return
        if lv < 0.0:
            lv = 0.0
        elif lv > 1.0:
            lv = 1.0
        if lv > self._live_amp:
            self._live_amp = lv

    def _make_grid(self, W: int, H: int) -> QPixmap:
        """Pre-render the static grid-dot background into a transparent pixmap so
        paintEvent can blit it once per frame instead of running a nested
        drawPoint() loop across the whole widget every 16 ms."""
        pm = QPixmap(max(1, W), max(1, H))
        pm.fill(Qt.GlobalColor.transparent)
        gp = QPainter(pm)
        gp.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                gp.drawPoint(x, y)
        gp.end()
        return pm

    def _step(self):
        if not self._on_screen():
            if self._tmr.interval() < 350:
                self._tmr.setInterval(350)  # Low-frequency idle sleep: drops background CPU to near 0%
            return

        prof = getattr(self, "_profile", "") or ResourceGuardian.get_instance().get_profile()
        if prof == "low_ram":
            # In Low RAM mode: trim continuous 3D math and sleep timer when quiet
            if not self.speaking and self._live_amp < 0.02 and self.state in ("IDLE", "LISTENING", "SLEEPING"):
                if self._tmr.interval() < 600:
                    self._tmr.setInterval(600)  # 1.5 wakeups/sec when idle: true 0% CPU!
                return
            elif self._tmr.interval() != 33:
                self._tmr.setInterval(33)       # 30 FPS fluid rendering during speech/active interaction (zero lag!)
        elif self._tmr.interval() > 50:
            rate = 33 if prof == "balanced" else 16
            self._tmr.setInterval(rate)

        self._tick += 1
        now = time.time()

        # ── Live audio reactivity ────────────────────────────────────────────
        # A viseme schedule, if one is playing, gives both the level and the
        # mouth shape for this exact instant; otherwise fall back to the peak
        # level the audio threads pushed in.
        v_open = v_wide = v_level = None
        v_seq = None
        sched = self._visemes
        if sched is not None:
            frames, t0, hop = sched
            i = int((now - t0) / hop)
            if 0 <= i < len(frames):
                # Hand over *every* frame since the last tick, not just the one
                # under the cursor. This timer runs at 60 Hz but the paint is
                # throttled and the machine may be busy, so a tick can span two
                # or three 20 ms frames — and a consonant closure is only two
                # frames long. Sampling one and discarding the rest is how the
                # closures between words went missing.
                j = self._vis_i if self._vis_i is not None else i
                v_seq = frames[max(0, j):i + 1]
                self._vis_i = max(j, i + 1)
                v_level, v_open, v_wide = frames[i]
                if v_seq:
                    peak = max(f[0] for f in v_seq)
                    if peak > self._live_amp:
                        self._live_amp = peak
            elif i >= len(frames):
                self._visemes = None        # schedule spent
                self._vis_i = None

        # Audio threads push peaks into _live_amp; decay it toward silence so
        # gaps between chunks fade out instead of freezing, then smooth it.
        self._live_amp *= 0.86
        self._amp_disp += (self._live_amp - self._amp_disp) * 0.45
        amp = self._amp_disp

        # The avatar animates off the very same smoothed level the waveform
        # uses — one audio source, so the mouth can never drift out of sync.
        dt = now - self._step_t
        self._step_t = now

        # Update floating dust particles
        _w_c, _h_c = max(1, self.width()), max(1, self.height())
        for _pt in self._particles:
            _pt[0] = (_pt[0] + _pt[2]) % _w_c
            _pt[1] = (_pt[1] + _pt[3]) % _h_c
        # Integrated, not derived from absolute time: multiplying wall-clock by
        # a rate that changes with state jumps the rings the instant JARVIS
        # starts talking. Same lesson the head's sway taught.
        self._core_phase += min(0.10, max(0.0, dt))

        if self._avatar is not None and self.hud_style == "face" and ResourceGuardian.get_instance().is_3d_avatar_enabled():
            self._avatar.step(dt, amp, speaking=self.speaking,
                              muted=self.muted, state=self.state,
                              v_open=v_open, v_wide=v_wide or 0.0,
                              v_level=v_level, v_seq=v_seq,
                              v_hop=(sched[2] if sched is not None else 0.02))
        else:
            # Fallback core: slow "breathing" base target, lifted by the level.
            if now - self._last_t > (0.12 if self.speaking else 0.5):
                if self.speaking:
                    self._base_scale = 1.03
                    self._base_halo  = 122.0
                elif self.muted:
                    self._base_scale = random.uniform(0.998, 1.002)
                    self._base_halo  = random.uniform(15, 28)
                else:
                    self._base_scale = random.uniform(1.001, 1.008)
                    self._base_halo  = random.uniform(48, 68)
                self._last_t = now

            if self.muted:
                self._tgt_scale, self._tgt_halo = self._base_scale, self._base_halo
            elif self.speaking:
                self._tgt_scale = self._base_scale + amp * 0.13
                self._tgt_halo  = self._base_halo  + amp * 95.0
            else:
                self._tgt_scale = self._base_scale + amp * 0.06
                self._tgt_halo  = self._base_halo  + amp * 75.0

            sp = 0.38 if self.speaking else (0.30 if amp > 0.02 else 0.15)
            self._scale += (self._tgt_scale - self._scale) * sp
            self._halo  += (self._tgt_halo  - self._halo)  * sp

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
            _blinked = True
        else:
            _blinked = False

        # Repaint throttling — advancing the animation state above is cheap at
        # 60 Hz, but the paint is heavy. Active (speaking, audio, thinking) runs
        # at ~30 Hz, which is the frame rate animation has used for talking
        # characters forever and is indistinguishable here; idle drops to ~20 Hz
        # so a sleeping HUD stops pinning a CPU core. The visuals stay smooth
        # either way because the animation state keeps stepping at 60 Hz.
        self._paint_tick = (self._paint_tick + 1) % 6
        active = (self.speaking or amp > 0.02
                  or self.state in ("THINKING", "PROCESSING"))
        if _blinked or (self._paint_tick % 2 == 0 if active
                        else self._paint_tick % 3 == 0):
            # Nothing is on screen when the window is hidden or minimised, so
            # rendering the avatar into it is pure waste — and this app is meant
            # to sit running all day. The animation state above keeps stepping,
            # so it picks up mid-motion instead of snapping when you come back.
            if self._on_screen():
                self.update()

    def _on_screen(self) -> bool:
        """True only when this canvas can actually be seen by the user."""
        try:
            p = self.parent()
            if isinstance(p, QStackedWidget) and p.currentWidget() is not self:
                return False
            if not self.isVisible():
                return False
            win = self.window()
            return not (win.isMinimized() or win.isHidden())
        except Exception:
            return True      # never let a visibility check stop the HUD drawing

    # ── reactor core ─────────────────────────────────────────────────────────
    # The centrepiece for anyone who did not want a face looking back at them.
    # Built from the same budget as the head — software QPainter, no GPU — and
    # from the same principle: everything on it means something. The rings turn
    # at a rate the state sets, the spectrum ring is the real audio level, and
    # the core brightens with the voice. Nothing here is decoration that moves
    # for its own sake, which is what made the old glowing orb feel dead.

    def _core_colours(self):
        if self.muted:
            return qcol(C.MUTED_C), qcol(C.MUTED_C)
        if self.speaking:
            return qcol(getattr(C, "BRASS", "#d4af37")), qcol(C.ACC)
        if self.state in ("THINKING", "PROCESSING"):
            return qcol(getattr(C, "BRASS", "#d4af37")), qcol(C.ACC2)
        if self.state == "LISTENING":
            return qcol(C.PRI), qcol(getattr(C, "BRASS", "#d4af37"))
        return qcol(C.PRI), qcol(C.PRI_DIM)

    def _paint_core(self, p: QPainter, cx: float, cy: float, r: float,
                    W: float = 0.0, H: float = 0.0):
        """Draw the reactor at (cx, cy) with outer radius r, using the whole
        canvas (W x H) for the marks that frame it."""
        main, acc = self._core_colours()
        bg = qcol(C.BG)
        amp = self._amp_disp
        t = self._core_phase
        live = (self.speaking or amp > 0.04) and not self.muted

        def blend(col: QColor, a: float) -> QColor:
            """Pre-mix onto the background instead of asking Qt to composite.
            The raster engine's opaque path is several times faster than its
            translucent one, and everything here is a line or an arc."""
            k = max(0.0, min(1.0, a))
            return QColor(int(bg.red()   + (col.red()   - bg.red())   * k),
                          int(bg.green() + (col.green() - bg.green()) * k),
                          int(bg.blue()  + (col.blue()  - bg.blue())  * k))

        p.setBrush(Qt.BrushStyle.NoBrush)

        # 1. The atmosphere. One radial gradient doing what a stack of discs did
        #    badly: a wide, soft body of light that gives the thing presence
        #    before any detail is read. This single element decides whether the
        #    HUD looks vast or looks small, so it is drawn first and drawn big.
        # Concentrated rather than spread: a gradient reaching the outer rim
        # washes the whole disc a flat dim blue and reads as fog. Ending it at
        # two thirds leaves it a body of light with somewhere to fall off to,
        # which is what makes it look lit rather than tinted.
        lift = 1.0 + 0.55 * amp + (0.18 if self.speaking else 0.0)
        p.setPen(Qt.PenStyle.NoPen)
        for gr, a0, a1 in ((r * 0.70, 0.30, 0.0), (r * 0.34, 0.34, 0.0)):
            g = QRadialGradient(cx, cy, gr)
            g.setColorAt(0.00, blend(main, min(0.95, a0 * lift)))
            g.setColorAt(0.45, blend(main, min(0.95, a0 * lift * 0.52)))
            g.setColorAt(0.78, blend(main, min(0.95, a0 * lift * 0.18)))
            g.setColorAt(1.00, blend(main, a1))
            p.setBrush(QBrush(g))
            p.drawEllipse(QRectF(cx - gr, cy - gr, gr * 2, gr * 2))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 2. Frame marks at the corners of the whole canvas, not of the circle.
        #    They are what set the scale: the eye reads the reactor as filling
        #    the room rather than sitting in the middle of it.
        if W > 40 and H > 40:
            m, arm = min(W, H) * 0.035, min(W, H) * 0.055
            p.setPen(QPen(blend(main, 0.45), 1.4))
            for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                x = cx + sx * (W / 2 - m)
                y = cy + sy * (H / 2 - m)
                p.drawLine(QLineF(x, y, x - sx * arm, y))
                p.drawLine(QLineF(x, y, x, y - sy * arm))

        # 3. Crosshair across the full canvas, broken around the core so it
        #    frames the reactor rather than crossing it.
        p.setPen(QPen(blend(main, 0.16), 1))
        gap = r * 0.62
        if W > 40:
            p.drawLine(QLineF(cx - W / 2, cy, cx - gap, cy))
            p.drawLine(QLineF(cx + gap, cy, cx + W / 2, cy))
        if H > 40:
            p.drawLine(QLineF(cx, cy - H / 2, cx, cy - gap))
            p.drawLine(QLineF(cx, cy + gap, cx, cy + H / 2))

        # 4. Two thin outer circles. Sparse on purpose — a dense ring reads as a
        #    grey band at this size, and restraint is what made the original
        #    look expensive.
        for rr, a in ((1.00, 0.34), (0.93, 0.16)):
            rad = r * rr
            p.setPen(QPen(blend(main, a), 1))
            p.drawEllipse(QRectF(cx - rad, cy - rad, rad * 2, rad * 2))

        # 5. Long, sparse graduations: 24 majors reaching well in from the rim,
        #    with shorter minors between them.
        major, minor = [], []
        for i in range(72):
            a = math.radians(i * 5.0)
            ca, sa = math.cos(a), math.sin(a)
            if i % 3 == 0:
                major.append(QLineF(cx + ca * r * 0.885, cy + sa * r * 0.885,
                                    cx + ca * r * 0.985, cy + sa * r * 0.985))
            else:
                minor.append(QLineF(cx + ca * r * 0.945, cy + sa * r * 0.945,
                                    cx + ca * r * 0.985, cy + sa * r * 0.985))
        p.setPen(QPen(blend(main, 0.42), 1.3))
        p.drawLines(major)
        p.setPen(QPen(blend(main, 0.18), 1))
        p.drawLines(minor)

        # 6. Sweeping arcs. Long spans, not dashes — the original's grandeur
        #    came from a few big strokes. Speed is the state: idle drifts,
        #    thinking hurries, speaking runs.
        rate = 1.0 + (1.9 if self.state in ("THINKING", "PROCESSING") else 0.0) \
                   + (1.2 if self.speaking else 0.0)
        for k, (rr, span, count, dirn, col, a, wid) in enumerate((
                (0.955, 118, 2, +1, acc,  0.75, 2.0),
                (0.845, 82,  3, -1, main, 0.38, 1.3),
                (0.760, 150, 1, +1, acc,  0.45, 1.6),
                (0.660, 64,  4, -1, main, 0.26, 1.1),
                (0.545, 128, 2, +1, main, 0.30, 1.2))):
            rad = r * rr
            p.setPen(QPen(blend(col, a), wid))
            box = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
            base = (t * rate * (9 + k * 6) * dirn) % 360.0
            for sgm in range(count):
                p.drawArc(box, int((base + sgm * (360.0 / count)) * 16),
                          int(span * 16))

        # 7. The voice, as a ring of graduations that grow with it. Kept out at
        #    a wide radius so it never crowds the middle.
        n = 60
        ring = r * 0.415
        spikes = []
        for i in range(n):
            a = math.radians(i * (360.0 / n))
            ca, sa = math.cos(a), math.sin(a)
            wob = 0.5 + 0.5 * math.sin(t * 2.3 + i * 0.42)
            idle = 0.018 + 0.012 * math.sin(t * 1.2 + i * 0.7)
            h = r * (idle + (amp * 0.20 * wob if live else 0.0))
            spikes.append(QLineF(cx + ca * ring, cy + sa * ring,
                                 cx + ca * (ring + h), cy + sa * (ring + h)))
        p.setPen(QPen(blend(acc if live else main, 0.25 + 0.5 * amp), 1.6))
        p.drawLines(spikes)

        # 8. The inner ring the name sits in.
        inner = r * 0.355
        p.setPen(QPen(blend(acc, 0.30 + 0.45 * amp), 1.5))
        p.drawEllipse(QRectF(cx - inner, cy - inner, inner * 2, inner * 2))

        # 9. The name, sized from the string rather than from the radius alone:
        #    "J.A.R.V.I.S" and a name someone renamed to "MAX" are very
        #    different widths, and a fixed fraction of r spills one of them past
        #    the ring it is supposed to sit inside.
        name = self._assistant_name or ""
        if name:
            space = max(1.0, r * 0.018)
            fsz = max(8, int(min(r * 0.105,
                                 (inner * 1.75) / max(1, len(name)) * 1.6 - space)))
            f = QFont("Courier New", fsz, QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, space)
            p.setFont(f)
            p.drawText(QRectF(cx - r, cy - fsz, r * 2, fsz * 2),
                       Qt.AlignmentFlag.AlignCenter, name)

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():      # device not ready (e.g. 0-size during layout) — skip cleanly
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # Draw subtle glowing floating dust particles (Holographic Brass / Ocean specks)
        if ResourceGuardian.get_instance().get_dust_particles_count() > 0:
            p.setPen(Qt.PenStyle.NoPen)
            for _pt in self._particles:
                _alpha = int(_pt[5] * 255 * (0.8 + 0.2 * math.sin(self._tick * 0.05 + _pt[0])))
                p.setBrush(QBrush(QColor(212, 175, 55, max(15, min(220, _alpha)))))
                p.drawEllipse(QPointF(_pt[0], _pt[1]), _pt[4] * 0.5, _pt[4] * 0.5)

        # grid dots — blitted from a cached layer; rebuilt only when the size
        # or the theme's ghost colour changes (so live re-theming still works).
        _gkey = (W, H, C.PRI_GHO)
        if self._grid_cache is None or self._grid_key != _gkey:
            self._grid_cache = self._make_grid(W, H)
            self._grid_key   = _gkey
        p.drawPixmap(0, 0, self._grid_cache)

        _sy_status = cy + fw * 0.40
        _band_t = 12.0
        _band_h = max(60.0, _sy_status - 12.0 - _band_t)
        _r = min(W * 0.46, _band_h / 2.0)

        # ── Visualizer Centrepiece Mode ──────────────────────────────────────
        use_3d = (self._avatar is not None and self.hud_style == "face"
                  and ResourceGuardian.get_instance().is_3d_avatar_enabled())
        if use_3d:
            _r_head = min(fw * 0.355, _band_h / (self._avatar.SPAN + 0.08))
            _head_cy = _band_t + (_band_h - self._avatar.SPAN * _r_head) / 2.0 + _r_head

            if self.muted:
                _main = _acc = qcol(C.MUTED_C)
            else:
                # Recolor 3D low-poly face to warm brass surface facets + holographic teal wireframe
                _main = qcol(getattr(C, "BRASS", "#d4af37"))
                if self.speaking:
                    _acc = qcol(C.ACC)
                elif self.state in ("THINKING", "PROCESSING"):
                    _acc = qcol(C.ACC2)
                elif self.state == "LISTENING":
                    _acc = qcol(C.PRI)
                else:
                    _acc = qcol(C.PRI)
            self._avatar.paint(p, cx, _head_cy, _r_head, _main, _acc, qcol(C.BG))
        else:
            self._paint_core(p, cx, _band_t + _band_h / 2.0, _r, W, _band_h)

        # status text
        sy = _sy_status
        if self.muted:
            txt, col = "⊘  MUTED",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING",  qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform — reacts to the real audio level (mic while listening,
        # JARVIS's own voice while speaking). Falls back to a gentle idle
        # ripple when there's no sound. _amp_disp is the smoothed 0–1 level.
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        amp = self._amp_disp
        mid = (N - 1) / 2.0
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            else:
                env     = (1.0 - abs(i - mid) / mid) ** 0.7      # center-weighted hump
                shimmer = 0.55 + 0.45 * math.sin(self._tick * 0.18 + i * 0.7)
                idle    = 3.0 + 2.0 * math.sin(self._tick * 0.09 + i * 0.6)
                hgt     = int(max(2, min(24, idle + amp * 22.0 * env * shimmer)))
                if amp > 0.05:
                    cl = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
                else:
                    cl = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)

        p.end()   # end deterministically so the backing store never flushes an active painter

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self._hovered = False
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def enterEvent(self, _):
        self._hovered = True
        self.update()

    def leaveEvent(self, _):
        self._hovered = False
        self.update()

    def set_value(self, pct: float, text: str):
        v = max(0.0, min(100.0, pct))
        if v == self._value and text == self._text:
            return          # unchanged — skip the repaint
        self._value = v
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Frosted glass panel with warm amber/gold border on hover/active
        p.setBrush(QBrush(qcol(C.PANEL2)))
        if getattr(self, '_hovered', False) or self._value > 75:
            p.setPen(QPen(qcol(getattr(C, 'ACC', '#ffaa22')), 1.5))
        else:
            p.setPen(QPen(qcol(getattr(C, 'BORDER', '#3a321a')), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 5, 5)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

        p.end()

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        # Cap scrollback so an hours-long session can't grow the document
        # without bound — keeps memory flat and every insert cheap. Oldest
        # lines drop off the top automatically.
        self.document().setMaximumBlockCount(600)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._ai_name_lc = "jarvis"   # updated when assistant name changes
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        _ai_pfx = f"{self._ai_name_lc}:"
        if   tl.startswith("you:"):                              self._tag = "you"
        elif tl.startswith(_ai_pfx) or tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):                             self._tag = "file"
        elif "err" in tl or "fail" in tl:                        self._tag = "err"
        elif "warn" in tl or "alert" in tl:                      self._tag = "warn"
        else:                                                    self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "warn": qcol(getattr(C, "ACC", "#ffaa22")),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.TEXT),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        # Do not start timer when idle to prevent continuous background CPU wakeups
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        # The marching-ants dashed border is only meaningful while the user is
        # hovering or dragging a file over the zone. When idle, skip the repaint
        # entirely instead of redrawing the whole zone 25×/s forever — that idle
        # repaint held the GIL and stole time from the audio/response threads.
        if not (self._hovering or self._drag_over):
            return
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            if not self._anim_tmr.isActive():
                self._anim_tmr.start(40)
            self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False
        if not self._hovering and self._anim_tmr.isActive():
            self._anim_tmr.stop()
        self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

        p.end()

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class HueWheel(QWidget):
    """
    Circular colour picker. The user drags the handle (small white circle)
    around the wheel to choose from ALL hues. The filled circle in the centre
    is a live preview of the selected colour.
    """

    hue_picked    = pyqtSignal(str)   # while dragging (live)
    hue_committed = pyqtSignal(str)   # when the handle is released

    _RING = 16   # ring thickness (px)

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.53
        self._drag = False
        self.set_color(initial_hex)

    # ── API ──────────────────────────────────────────────────────────────────
    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    # ── geometry helpers ─────────────────────────────────────────────────────
    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()          # screen y goes down — flip to math axis
        ang = math.atan2(dy, dx)      # [-π, π], counter-clockwise
        return (ang / (2 * math.pi)) % 1.0

    # ── drawing ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # centre preview circle
        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        # draggable handle
        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#00060a"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)
        p.end()

    # ── fare ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())



# Re-export presets from theme.py (Strictly NO purple anywhere)
from theme import THEME_PRESETS as _THEME_PRESETS, HUD_PRESETS as _HUD_PRESETS, LAYOUT_PRESETS as _LAYOUT_PRESETS


class CustomizeOverlay(QWidget):
    """Floating overlay — Holographic Brass & Deep Ocean UI makeover:
    All settings arranged in ONE unified view with ZERO scrollbars/sliders."""

    saved = pyqtSignal(str, str, str, str, str, str)   # assistant_name, user_name, ui_color, voice, hud_style, layout_mode
    _OW, _OH = 860, 520

    def __init__(self, assistant_name="JARVIS", user_name="",
                 ui_color=DEFAULT_UI_COLOR, voice="",
                 hud_style="face", layout_mode="tactical", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self._initial_hud_style = hud_style or "face"
        self._sel_hud_style     = self._initial_hud_style
        self._initial_layout_mode = layout_mode or "tactical"
        self._sel_layout_mode     = self._initial_layout_mode

        self.on_preview        = None   # callable(hex) — live preview
        self.on_preview_hud    = None   # callable(hud_style)
        self.on_preview_layout = None   # callable(layout_mode)

        # Frosted glassmorphism modal with glowing brass/gold border
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(3, 14, 26, 0.97);
                border: 1.5px solid rgba(212, 175, 55, 0.65);
                border-radius: 10px;
            }}
        """)

        # Main Layout — fits completely in ONE screen with ZERO scrollbars
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(14, 12, 14, 12)
        main_lay.setSpacing(8)

        # ── Header ──────────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        title_lbl = QLabel("⚙  CUSTOMISE ASSISTANT & UI MAKEOVER")
        title_lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #f0c544; background: transparent;")
        hdr_row.addWidget(title_lbl)

        badge_lbl = QLabel("[ HOLOGRAPHIC BRASS & DEEP OCEAN ]")
        badge_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        badge_lbl.setStyleSheet("color: #00e5ff; background: transparent;")
        hdr_row.addWidget(badge_lbl)
        hdr_row.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #6ab8cc; border: 1px solid rgba(212, 175, 55, 0.3); border-radius: 3px; }
            QPushButton:hover { background: rgba(255, 77, 109, 0.2); color: #ff4d6d; border-color: #ff4d6d; }
        """)
        close_btn.clicked.connect(self._cancel)
        hdr_row.addWidget(close_btn)
        main_lay.addLayout(hdr_row)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("color: rgba(212, 175, 55, 0.35); margin: 0;")
        main_lay.addWidget(sep0)

        # ── Columns Container (Left: Visuals & Identity, Right: Voice & Persona) ──
        cols_lay = QHBoxLayout()
        cols_lay.setSpacing(12)

        _fs = ("QLineEdit { background: rgba(2, 11, 20, 0.90); color: #8ffcff; "
               "border: 1px solid rgba(212, 175, 55, 0.35); border-radius: 4px; padding: 2px 6px; } "
               "QLineEdit:focus { border: 1px solid #00e5ff; background: rgba(2, 14, 26, 0.98); }")

        def _card_panel():
            f = QFrame()
            f.setStyleSheet("""
                QFrame {
                    background: rgba(4, 18, 30, 0.78);
                    border: 1px solid rgba(212, 175, 55, 0.28);
                    border-radius: 8px;
                }
            """)
            return f

        def _sub_lbl(txt, color="#d4af37"):
            w = QLabel(txt)
            w.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            w.setStyleSheet(f"color: {color}; background: transparent; letter-spacing: 1px;")
            return w

        # ======================================================================
        # LEFT CARD: Identity, Visualizer Animation, Layout, Themes
        # ======================================================================
        left_card = _card_panel()
        left_lay = QVBoxLayout(left_card)
        left_lay.setContentsMargins(10, 8, 10, 8)
        left_lay.setSpacing(6)

        left_lay.addWidget(_sub_lbl("◈  IDENTITY & CALLSIGN"))

        names_row = QHBoxLayout(); names_row.setSpacing(6)
        n1_col = QVBoxLayout(); n1_col.setSpacing(2)
        n1_col.addWidget(QLabel("ASSISTANT NAME", font=QFont("Courier New", 6), styleSheet="color: #4a7d90;"))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(QFont("Courier New", 8))
        self._name_input.setFixedHeight(24)
        self._name_input.setStyleSheet(_fs)
        n1_col.addWidget(self._name_input)
        names_row.addLayout(n1_col, stretch=1)

        n2_col = QVBoxLayout(); n2_col.setSpacing(2)
        n2_col.addWidget(QLabel("YOUR CALLSIGN (SIR / NAME)", font=QFont("Courier New", 6), styleSheet="color: #4a7d90;"))
        _u_val = (user_name or "").strip()
        if not _u_val or _u_val == "-":
            _u_val = "Harshil"
        self._user_input = QLineEdit(_u_val)
        self._user_input.setPlaceholderText("sir")
        self._user_input.setFont(QFont("Courier New", 8))
        self._user_input.setFixedHeight(24)
        self._user_input.setStyleSheet(_fs)
        n2_col.addWidget(self._user_input)
        names_row.addLayout(n2_col, stretch=1)
        left_lay.addLayout(names_row)

        # AI Visualizer
        left_lay.addWidget(_sub_lbl("◈  AI VISUALIZER ANIMATION"))
        self._hud_btns: dict[str, QPushButton] = {}
        hud_row1 = QHBoxLayout(); hud_row1.setSpacing(4)
        hud_row2 = QHBoxLayout(); hud_row2.setSpacing(4)
        for idx, (htitle, hmode) in enumerate(_HUD_PRESETS):
            b = QPushButton(htitle)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=hmode: self._on_hud_pick(m))
            self._hud_btns[hmode] = b
            if idx < 2:
                hud_row1.addWidget(b)
            else:
                hud_row2.addWidget(b)
        left_lay.addLayout(hud_row1)
        left_lay.addLayout(hud_row2)
        self._refresh_hud_btns()

        # UI Layout Mode
        left_lay.addWidget(_sub_lbl("◈  UI LAYOUT MODE"))
        self._layout_btns: dict[str, QPushButton] = {}
        layout_row = QHBoxLayout(); layout_row.setSpacing(4)
        for ltitle, lmode in _LAYOUT_PRESETS:
            b = QPushButton(ltitle)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=lmode: self._on_layout_pick(m))
            self._layout_btns[lmode] = b
            layout_row.addWidget(b)
        left_lay.addLayout(layout_row)
        self._refresh_layout_btns()

        # Theme Presets (Strictly NO Purple)
        left_lay.addWidget(_sub_lbl("◈  THEME PRESETS (HOLOGRAPHIC PALETTES)"))
        self._theme_btns: dict[str, QPushButton] = {}
        t_row1 = QHBoxLayout(); t_row1.setSpacing(4)
        t_row2 = QHBoxLayout(); t_row2.setSpacing(4)
        split_idx = (len(_THEME_PRESETS) + 1) // 2
        for idx, (tname, thex) in enumerate(_THEME_PRESETS):
            b = QPushButton(tname)
            b.setCheckable(True)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, h=thex: self._on_theme_pick(h))
            self._theme_btns[thex] = b
            if idx < split_idx:
                t_row1.addWidget(b)
            else:
                t_row2.addWidget(b)
        left_lay.addLayout(t_row1)
        left_lay.addLayout(t_row2)
        self._refresh_theme_btns()

        # Custom Accent Color
        left_lay.addWidget(_sub_lbl("◈  CUSTOM ACCENT COLOR"))
        accent_row = QHBoxLayout(); accent_row.setSpacing(4)

        swatches = [
            ("#d4af37", "Gold"),
            ("#00e5ff", "Teal"),
            ("#ffaa22", "Amber"),
            ("#f0c544", "Brass"),
            ("#8899aa", "Silver"),
            ("#00b4d8", "Marine"),
            ("#00ff41", "Matrix Green"),
        ]
        for sw_hex, sw_tip in swatches:
            sb = QPushButton()
            sb.setFixedSize(18, 18)
            sb.setToolTip(sw_tip)
            sb.setCursor(Qt.CursorShape.PointingHandCursor)
            sb.setStyleSheet(f"background: {sw_hex}; border: 1px solid rgba(255,255,255,0.4); border-radius: 9px;")
            sb.clicked.connect(lambda _=False, h=sw_hex: self._set_color(h))
            accent_row.addWidget(sb)

        accent_row.addSpacing(6)
        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#00e5ff")
        self._hex_input.setFont(QFont("Courier New", 8))
        self._hex_input.setFixedHeight(24)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        accent_row.addWidget(self._hex_input, stretch=1)

        df_btn = QPushButton("DEFAULT")
        df_btn.setFixedSize(58, 24)
        df_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #6ab8cc; border: 1px solid rgba(212,175,55,0.3); border-radius: 3px; }
            QPushButton:hover { color: #f0c544; border-color: #f0c544; }
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        accent_row.addWidget(df_btn)
        left_lay.addLayout(accent_row)

        cols_lay.addWidget(left_card, stretch=1)

        # ======================================================================
        # RIGHT CARD: Assistant Voice & Persona
        # ======================================================================
        right_card = _card_panel()
        right_lay = QVBoxLayout(right_card)
        right_lay.setContentsMargins(10, 8, 10, 8)
        right_lay.setSpacing(6)

        v_hdr = QHBoxLayout()
        v_hdr.addWidget(_sub_lbl("✦  ASSISTANT VOICE & PERSONA"))
        v_hdr.addStretch()

        self._add_voice_btn = QPushButton("+ CUSTOM")
        self._add_voice_btn.setFixedSize(65, 20)
        self._add_voice_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._add_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_voice_btn.setStyleSheet("""
            QPushButton { background: rgba(0, 229, 255, 0.12); color: #00e5ff; border: 1px solid rgba(0, 229, 255, 0.4); border-radius: 3px; }
            QPushButton:hover { background: #00e5ff; color: #000; }
        """)
        self._add_voice_btn.clicked.connect(self._toggle_custom_voice_box)
        v_hdr.addWidget(self._add_voice_btn)
        right_lay.addLayout(v_hdr)

        from memory.config_manager import DEFAULT_VOICE, get_available_voices
        self._sel_voice = (voice or DEFAULT_VOICE)
        if self._sel_voice not in get_available_voices():
            self._sel_voice = DEFAULT_VOICE

        self._voice_btns: dict[str, QPushButton] = {}
        self._voice_container_lay = QVBoxLayout()
        self._voice_container_lay.setSpacing(4)
        right_lay.addLayout(self._voice_container_lay)

        # Voice Tone Presets Chips
        right_lay.addWidget(_sub_lbl("◈  VOICE TONE / PERSONA PRESET CHIPS", "#00e5ff"))
        tone_chips_row = QHBoxLayout(); tone_chips_row.setSpacing(4)
        tone_presets = [
            ("Cute & Caring", "Snow"),
            ("Romantic Warm", "Nia"),
            ("Intimate Seductive", "Dragon"),
            ("Mayra Masti", "Mayra"),
            ("Formal Butler", "Charon"),
            ("Crisp Balanced", "Kore"),
        ]
        for t_label, v_assoc in tone_presets:
            tb = QPushButton(f"[{t_label}]")
            tb.setFixedHeight(22)
            tb.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
            tb.setCursor(Qt.CursorShape.PointingHandCursor)
            tb.setStyleSheet("""
                QPushButton { background: rgba(212, 175, 55, 0.08); color: #8ffcff; border: 1px solid rgba(212, 175, 55, 0.25); border-radius: 4px; padding: 0 4px; }
                QPushButton:hover { background: rgba(212, 175, 55, 0.25); color: #f0c544; border-color: #f0c544; }
            """)
            tb.clicked.connect(lambda _=False, v=v_assoc: self._on_voice_pick(v))
            tone_chips_row.addWidget(tb)
        right_lay.addLayout(tone_chips_row)

        # Active Voice Information Mini-Card
        self._cv_info_box = QFrame()
        self._cv_info_box.setStyleSheet("""
            QFrame {
                background: rgba(2, 12, 22, 0.85);
                border: 1px dashed rgba(212, 175, 55, 0.45);
                border-radius: 6px;
                padding: 4px;
            }
        """)
        cv_info_lay = QVBoxLayout(self._cv_info_box)
        cv_info_lay.setContentsMargins(6, 4, 6, 4)
        cv_info_lay.setSpacing(2)
        self._cv_info_lbl = QLabel()
        self._cv_info_lbl.setFont(QFont("Courier New", 7))
        self._cv_info_lbl.setWordWrap(True)
        self._cv_info_lbl.setStyleSheet("color: #8ffcff; background: transparent;")
        cv_info_lay.addWidget(self._cv_info_lbl)

        # Test Voice / Remove Row
        cv_tools_row = QHBoxLayout()
        cv_tools_row.setSpacing(6)
        self._cv_test_active_btn = QPushButton("▶ TEST")
        self._cv_test_active_btn.setFixedHeight(20)
        self._cv_test_active_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._cv_test_active_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cv_test_active_btn.setStyleSheet("""
            QPushButton { background: rgba(0, 229, 255, 0.12); color: #00e5ff; border: 1px solid #00e5ff; border-radius: 3px; padding: 0 6px; }
            QPushButton:hover { background: #00e5ff; color: #000; }
        """)
        self._cv_test_active_btn.clicked.connect(self._test_active_custom_voice)
        cv_tools_row.addWidget(self._cv_test_active_btn)

        self._cv_del_btn = QPushButton("🗑 REMOVE")
        self._cv_del_btn.setFixedHeight(20)
        self._cv_del_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._cv_del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cv_del_btn.setStyleSheet("""
            QPushButton { background: rgba(255, 77, 109, 0.15); color: #ff6688; border: 1px solid #ff4d6d; border-radius: 3px; padding: 0 6px; }
            QPushButton:hover { background: #ff4d6d; color: #fff; }
        """)
        self._cv_del_btn.clicked.connect(self._on_delete_custom_voice)
        cv_tools_row.addWidget(self._cv_del_btn)
        cv_tools_row.addStretch()

        self._cv_active_test_status_lbl = QLabel()
        self._cv_active_test_status_lbl.setFont(QFont("Courier New", 6))
        self._cv_active_test_status_lbl.setStyleSheet("color: #4a7d90; background: transparent;")
        cv_tools_row.addWidget(self._cv_active_test_status_lbl)

        cv_info_lay.addLayout(cv_tools_row)
        right_lay.addWidget(self._cv_info_box)

        # Expandable Custom Voice Creator Box
        self._custom_voice_box = QFrame()
        self._custom_voice_box.setStyleSheet("""
            QFrame { background: rgba(2, 14, 26, 0.95); border: 1px solid #00e5ff; border-radius: 6px; }
        """)
        self._custom_voice_box.setVisible(False)
        cv_form_lay = QVBoxLayout(self._custom_voice_box)
        cv_form_lay.setContentsMargins(6, 6, 6, 6)
        cv_form_lay.setSpacing(4)

        cv_form_lay.addWidget(_sub_lbl("✦ CREATE CUSTOM ASSISTANT VOICE"))
        self._cv_name_input = QLineEdit()
        self._cv_name_input.setPlaceholderText("Voice Name (e.g. Jarvis Mk2, Friday)")
        self._cv_name_input.setFixedHeight(22)
        self._cv_name_input.setFont(QFont("Courier New", 7))
        self._cv_name_input.setStyleSheet(_fs)
        cv_form_lay.addWidget(self._cv_name_input)

        cv_act_row = QHBoxLayout()
        save_cv_btn = QPushButton("✓ SAVE VOICE")
        save_cv_btn.setFixedHeight(22)
        save_cv_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        save_cv_btn.setStyleSheet("""
            QPushButton { background: rgba(0, 229, 255, 0.2); color: #00e5ff; border: 1px solid #00e5ff; border-radius: 3px; }
            QPushButton:hover { background: #00e5ff; color: #000; }
        """)
        save_cv_btn.clicked.connect(self._on_save_custom_voice)
        cv_act_row.addWidget(save_cv_btn)

        cancel_cv_btn = QPushButton("CANCEL")
        cancel_cv_btn.setFixedHeight(22)
        cancel_cv_btn.setFont(QFont("Courier New", 7))
        cancel_cv_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #6ab8cc; border: 1px solid rgba(212,175,55,0.3); border-radius: 3px; }
            QPushButton:hover { color: #fff; }
        """)
        cancel_cv_btn.clicked.connect(self._toggle_custom_voice_box)
        cv_act_row.addWidget(cancel_cv_btn)
        cv_form_lay.addLayout(cv_act_row)
        right_lay.addWidget(self._custom_voice_box)

        cols_lay.addWidget(right_card, stretch=1)
        main_lay.addLayout(cols_lay, stretch=1)

        # ── Bottom Action Buttons ─────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(10)
        btn_row.addStretch()

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedSize(110, 32)
        cancel_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(4, 18, 30, 0.70);
                color: #6ab8cc;
                border: 1px solid rgba(212, 175, 55, 0.35);
                border-radius: 5px;
            }
            QPushButton:hover {
                background: rgba(212, 175, 55, 0.15);
                color: #ffffff;
                border-color: rgba(212, 175, 55, 0.65);
            }
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)

        shortcut_btn = QPushButton("◈  DESKTOP SHORTCUT")
        shortcut_btn.setFixedHeight(32)
        shortcut_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shortcut_btn.setStyleSheet("""
            QPushButton {
                background: rgba(4, 18, 30, 0.75);
                color: #8ffcff;
                border: 1px solid rgba(0, 229, 255, 0.4);
                border-radius: 4px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background: rgba(0, 229, 255, 0.15);
                color: #ffffff;
                border-color: #00e5ff;
            }
        """)
        def _on_create_shortcut():
            from core.desktop_shortcut import create_desktop_shortcut
            ok, msg = create_desktop_shortcut(force=True)
            if ok:
                shortcut_btn.setText("✓ SHORTCUT ADDED")
                shortcut_btn.setStyleSheet("QPushButton { background: #002b1a; color: #00ffaa; border: 1px solid #00ffaa; border-radius: 4px; padding: 0 10px; }")
            else:
                shortcut_btn.setText("⚠️ FAILED")
        shortcut_btn.clicked.connect(_on_create_shortcut)
        btn_row.addWidget(shortcut_btn)

        save_btn = QPushButton("▸  APPLY CHANGES")
        save_btn.setFixedSize(170, 32)
        save_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(212, 175, 55, 0.30), stop:1 rgba(0, 229, 255, 0.25));
                color: #f0c544;
                border: 1.5px solid #d4af37;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(212, 175, 55, 0.55), stop:1 rgba(0, 229, 255, 0.45));
                border-color: #f0c544;
                color: #ffffff;
            }
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        main_lay.addLayout(btn_row)

        self._rebuild_voice_pills()

    # ── hud visualizer selection ──────────────────────────────────────────────
    def _on_hud_pick(self, mode: str):
        self._sel_hud_style = mode
        self._refresh_hud_btns()
        if self.on_preview_hud:
            self.on_preview_hud(mode)

    def _refresh_hud_btns(self):
        for mode, b in self._hud_btns.items():
            on = (mode == self._sel_hud_style)
            b.setChecked(on)
            if on:
                b.setStyleSheet("""
                    QPushButton { background: rgba(0, 229, 255, 0.20); color: #00e5ff;
                        border: 1px solid #00e5ff; border-radius: 4px; }
                """)
            else:
                b.setStyleSheet("""
                    QPushButton { background: rgba(4, 18, 30, 0.60); color: #6ab8cc;
                        border: 1px solid rgba(212, 175, 55, 0.25); border-radius: 4px; }
                    QPushButton:hover { color: #f0c544; border-color: rgba(212, 175, 55, 0.55); }
                """)

    # ── layout selection ──────────────────────────────────────────────────────
    def _on_layout_pick(self, mode: str):
        self._sel_layout_mode = mode
        self._refresh_layout_btns()
        if self.on_preview_layout:
            self.on_preview_layout(mode)

    def _refresh_layout_btns(self):
        for mode, b in self._layout_btns.items():
            on = (mode == self._sel_layout_mode)
            b.setChecked(on)
            if on:
                b.setStyleSheet("""
                    QPushButton { background: rgba(212, 175, 55, 0.22); color: #f0c544;
                        border: 1px solid #d4af37; border-radius: 4px; }
                """)
            else:
                b.setStyleSheet("""
                    QPushButton { background: rgba(4, 18, 30, 0.60); color: #6ab8cc;
                        border: 1px solid rgba(212, 175, 55, 0.25); border-radius: 4px; }
                    QPushButton:hover { color: #f0c544; border-color: rgba(212, 175, 55, 0.55); }
                """)

    # ── voice selection ───────────────────────────────────────────────────────
    def _toggle_custom_voice_box(self):
        vis = not self._custom_voice_box.isVisible()
        self._custom_voice_box.setVisible(vis)
        self._add_voice_btn.setText("▲ CLOSE" if vis else "+ CUSTOM")

    def _on_save_custom_voice(self):
        name = self._cv_name_input.text().strip()
        if not name:
            self._cv_name_input.setFocus()
            return
        from memory.config_manager import save_custom_voice
        save_custom_voice(name, voice_type="gemini", base_voice="Aoede", persona="")
        self._sel_voice = name
        self._custom_voice_box.setVisible(False)
        self._add_voice_btn.setText("+ CUSTOM")
        self._cv_name_input.clear()
        self._rebuild_voice_pills()

    def _on_delete_custom_voice(self):
        from memory.config_manager import delete_custom_voice, DEFAULT_VOICE
        if delete_custom_voice(self._sel_voice):
            self._sel_voice = DEFAULT_VOICE
            self._rebuild_voice_pills()

    def _on_voice_pick(self, name: str):
        self._sel_voice = name
        self._refresh_voice_btns()

    def _rebuild_voice_pills(self):
        """Re-render voice buttons in clean rows: Permanent character voices on top, core timbres below."""
        from memory.config_manager import get_available_voices
        while self._voice_container_lay.count():
            item = self._voice_container_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

        self._voice_btns.clear()

        # Row 1: Permanent Character Voices (Featured First Class)
        lbl_p = QLabel("PERMANENT GIRLFRIEND & COMPANION VOICES (NATIVE GEMINI)")
        lbl_p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        lbl_p.setStyleSheet("color: #d4af37; background: transparent;")
        self._voice_container_lay.addWidget(lbl_p)

        row_char = QHBoxLayout(); row_char.setSpacing(4)
        for _v, _badge in [("Snow", "🌸 Snow"), ("Nia", "💖 Nia"), ("Dragon", "✨ Dragon"), ("Mayra", "🌙 Mayra")]:
            b = QPushButton(_badge)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
            self._voice_btns[_v] = b
            row_char.addWidget(b)
        self._voice_container_lay.addLayout(row_char)

        # Row 2: Standard Core Built-in Voices
        lbl_c = QLabel("STANDARD CORE TIMBRES")
        lbl_c.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        lbl_c.setStyleSheet("color: #4a7d90; background: transparent; margin-top: 2px;")
        self._voice_container_lay.addWidget(lbl_c)

        row_builtin = QHBoxLayout(); row_builtin.setSpacing(4)
        for _v in ("Charon", "Puck", "Kore", "Fenrir", "Aoede"):
            b = QPushButton(_v)
            b.setCheckable(True)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
            self._voice_btns[_v] = b
            row_builtin.addWidget(b)
        self._voice_container_lay.addLayout(row_builtin)

        # Extra customs (if any)
        avail = get_available_voices()
        extra_customs = [v for v in avail if v not in ("Charon", "Puck", "Kore", "Fenrir", "Aoede", "Snow", "Nia", "Dragon", "Mayra", "kavya", "XG", "Tiara")]
        if extra_customs:
            row_custom = QHBoxLayout(); row_custom.setSpacing(4)
            for _v in extra_customs:
                b = QPushButton(_v)
                b.setCheckable(True)
                b.setFixedHeight(22)
                b.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
                self._voice_btns[_v] = b
                row_custom.addWidget(b)
            self._voice_container_lay.addLayout(row_custom)

        self._refresh_voice_btns()

    def _refresh_voice_btns(self):
        """Highlight active voice button and update info card."""
        from memory.config_manager import get_custom_voice_info
        v_canonical = {"kavya": "Snow", "xg": "Nia", "tiara": "Dragon"}.get((self._sel_voice or "").lower(), self._sel_voice)
        for name, b in self._voice_btns.items():
            on = (name == self._sel_voice or name.lower() == (v_canonical or "").lower())
            b.setChecked(on)
            if on:
                b.setStyleSheet("""
                    QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(212, 175, 55, 0.35), stop:1 rgba(0, 229, 255, 0.30));
                        color: #ffffff; border: 1.5px solid #00e5ff; border-radius: 4px; font-weight: bold; }
                """)
            else:
                b.setStyleSheet("""
                    QPushButton { background: rgba(4, 18, 30, 0.60); color: #8ffcff;
                        border: 1px solid rgba(212, 175, 55, 0.25); border-radius: 4px; }
                    QPushButton:hover { color: #f0c544; border-color: rgba(212, 175, 55, 0.6); }
                """)

        info = get_custom_voice_info(self._sel_voice)
        v_lower = (self._sel_voice or "").lower()
        if v_lower in ("snow", "kavya"):
            txt = ("🌸 Snow (Cute Caring Sweet Girlfriend)\n"
                   "Real, interactive, and emotionally present — Snow persona.\n"
                   "Permanent Native Gemini Acoustic (Aoede) • 0 ElevenLabs Connection.")
        elif v_lower in ("nia", "xg"):
            txt = ("💖 Nia (Warm Emotional Girlfriend)\n"
                   "Romantic, devoted, naturally expressive — Nia persona.\n"
                   "Permanent Native Gemini Acoustic (Aoede) • 0 ElevenLabs Connection.")
        elif v_lower in ("dragon", "tiara"):
            txt = ("✨ Dragon (Smooth, Soft and Seductive)\n"
                   "Sweetness & husky depth, intimate and personal warmth.\n"
                   "Permanent Native Gemini Acoustic (Kore) • 0 ElevenLabs Connection.")
        elif v_lower == "mayra":
            txt = ("🌙 Mayra (Sweet Playful Girlfriend)\n"
                   "Real, interactive, aur emotionally present. Thodi nakhre wali, masti karne wali, caring persona.\n"
                   "Permanent Native Gemini Acoustic (Aoede) • 0 ElevenLabs Connection.")
        elif info:
            cat = info.get("voice_category", "Custom Voice")
            base = info.get("base_voice", "Aoede")
            txt = (f"🎙 ACTIVE: {self._sel_voice} ({cat}) | TIMBRE: {base}\n"
                   "Native Gemini Engine • Permanent Storage.")
        else:
            txt = (f"🎙 ACTIVE: {self._sel_voice} (Built-in Gemini Acoustic Core)\n"
                   "Direct low-latency speech synthesis.")

        self._cv_info_lbl.setText(txt)
        is_perm = v_lower in ("charon", "puck", "kore", "fenrir", "aoede", "snow", "nia", "dragon", "mayra", "kavya", "xg", "tiara")
        self._cv_del_btn.setVisible(not is_perm)
        self._cv_test_active_btn.setVisible(not is_perm)

    def _test_active_custom_voice(self):
        self._cv_active_test_status_lbl.setText("Native Gemini voices stream live during conversations.")

    # ── theme preset selection ────────────────────────────────────────────────
    def _on_theme_pick(self, hex_color: str):
        self._set_color(hex_color)
        self._refresh_theme_btns()

    def _refresh_theme_btns(self):
        if not hasattr(self, '_theme_btns'):
            return
        sel = (getattr(self, '_sel_color', "") or "").strip().lower()
        for thex, b in self._theme_btns.items():
            on = (thex.lower() == sel)
            b.setChecked(on)
            if on:
                b.setStyleSheet("""
                    QPushButton { background: rgba(0, 229, 255, 0.22); color: #00e5ff;
                        border: 1.5px solid #00e5ff; border-radius: 4px; }
                """)
            else:
                b.setStyleSheet("""
                    QPushButton { background: rgba(4, 18, 30, 0.60); color: #6ab8cc;
                        border: 1px solid rgba(212, 175, 55, 0.25); border-radius: 4px; }
                    QPushButton:hover { color: #f0c544; border-color: rgba(212, 175, 55, 0.55); }
                """)

    def _set_color(self, hx: str, preview: bool = True):
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)
        if hasattr(self, '_theme_btns'):
            self._refresh_theme_btns()

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
                self._set_color(t, preview=True)
            except ValueError:
                pass

    def _cancel(self):
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        if self.on_preview_hud and self._sel_hud_style != self._initial_hud_style:
            self.on_preview_hud(self._initial_hud_style)
        if self.on_preview_layout and self._sel_layout_mode != self._initial_layout_mode:
            self.on_preview_layout(self._initial_layout_mode)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "JARVIS"
        user = self._user_input.text().strip()
        self.saved.emit(name, user, self._sel_color or DEFAULT_UI_COLOR,
                        self._sel_voice, self._sel_hud_style, self._sel_layout_mode)
        self.hide()

class PluginManagerOverlay(QWidget):
    """Floating overlay — lists discovered plugins with per-plugin ON/OFF toggles."""

    _OW = 420

    def __init__(self, plugins: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginManagerOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🧩  PLUGIN MANAGER")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        if not plugins:
            empty = QLabel("No plugins found in /plugins.")
            empty.setFont(QFont("Courier New", 8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(empty)

        for p in plugins:
            lay.addLayout(self._build_row(p))

        lay.addSpacing(4)
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(30)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        self.adjustSize()

    def _build_row(self, p: dict) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(6)

        label_text = p["name"] if p["valid"] else f"{p['name']}  (⚠ {p['file']})"
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT if p['valid'] else C.TEXT_DIM}; background: transparent;")
        lbl.setToolTip(p["description"] if p["valid"] else p["error"])
        lbl.setWordWrap(False)
        row.addWidget(lbl, stretch=1)

        btn = QPushButton()
        btn.setFixedSize(72, 24)
        btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        if not p["valid"]:
            btn.setText("BROKEN")
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
        else:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_toggle(btn, p["enabled"])
            btn.clicked.connect(lambda _, name=p["name"], b=btn: self._toggle(name, b))
        row.addWidget(btn)
        return row

    def _style_toggle(self, btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle(self, name: str, btn: QPushButton):
        from memory.config_manager import get_plugin_enabled, save_plugin_enabled
        new_val = not get_plugin_enabled(name)
        save_plugin_enabled(name, new_val)
        self._style_toggle(btn, new_val)


class _HudOverlay(QWidget):
    """Base for the floating panels placed by hand over the HUD.

    They are children of the central widget but sit in no layout, so Qt never
    invalidates the region they occupy when they hide or shrink: the HUD keeps
    painting around them and their last frame stays on screen as a ghost. Any
    overlay positioned with _centre_overlay needs this."""

    def hideEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            # Repaint exactly what we were covering, before we stop covering it.
            p.update(self.geometry())
        super().hideEvent(e)

    def closeEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            p.update(self.geometry())
        super().closeEvent(e)


class ConfirmBanner(_HudOverlay):
    """The gate in front of an action that cannot be taken back.

    The old confirmation was a tool parameter the model filled in itself, which
    means it confirmed its own shutdown requests. This is the interface asking,
    and the answer travels from a human finger to core/confirm.py without the
    model in the loop. Nothing blocks while it is up: the assistant keeps
    talking, so this costs no latency — unlike the old gate, which spent two
    tool round trips on every power command."""

    answered = pyqtSignal(bool)
    _OW = 430

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ConfirmBanner {{
                background: rgba(14, 3, 0, 250);
                border: 1px solid {C.ACC};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        hdr = QLabel("⚠  CONFIRM")
        hdr.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.ACC}; background: transparent;")
        lay.addWidget(hdr)

        ttl = QLabel(title)
        ttl.setWordWrap(True)
        ttl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        ttl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(ttl)

        if detail:
            dtl = QLabel(detail)
            dtl.setWordWrap(True)
            dtl.setFont(QFont("Courier New", 8))
            dtl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            lay.addWidget(dtl)

        row = QHBoxLayout(); row.setSpacing(8)

        yes = QPushButton("▸  CONFIRM")
        yes.setFixedHeight(32)
        yes.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        yes.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.ACC};
                border: 1px solid {C.ACC}; border-radius: 3px; }}
            QPushButton:hover {{ background: rgba(255,107,0,40); }}
        """)
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(yes)

        no = QPushButton("CANCEL")
        no.setFixedHeight(32)
        no.setFont(QFont("Courier New", 9))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        no.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(no)
        lay.addLayout(row)

        # Default focus on CANCEL: if someone hits Enter without reading, the
        # safe answer wins.
        no.setDefault(True)
        no.setFocus()


class AudioDeviceOverlay(_HudOverlay):
    """Choose which microphone JARVIS listens to and which speakers it uses.

    Both audio streams used to open with no `device=` at all, so they always
    took the OS default — which on Windows moves by itself the moment a headset
    is plugged in. 'JARVIS can't hear me' is usually 'JARVIS is listening to the
    webcam'."""

    picked = pyqtSignal()      # emitted after Apply, when something changed

    # THESE EXIST BECAUSE QTimer.singleShot FROM A WORKER THREAD NEVER FIRES.
    #
    # The first version posted results back with `QTimer.singleShot(0, fn)` from
    # inside the audio thread. A QTimer belongs to the thread that creates it,
    # and that thread has no event loop — so the timer was created, never ran,
    # and the panel sat on "Speak now…" for ever while the recording finished
    # silently behind it. Reported as "I saw no sign of anything at all", which
    # is precisely what it looked like.
    #
    # A signal is the thread-safe way across: Qt queues it onto the receiving
    # object's thread, which for a widget is the GUI thread. Both carry only
    # plain values — never a widget — because the widgets belong to the GUI
    # thread and the worker must not touch them even to pass them along.
    _level_seen = pyqtSignal(int)          # 0-100, while recording
    _test_result = pyqtSignal(str, bool)   # sentence, was it good

    _OW = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.audio_devices import list_devices, DEFAULT_LABEL
        from memory.config_manager import get_input_device, get_output_device

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AudioDeviceOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🎧  AUDIO DEVICES")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        _combo_css = (
            f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )

        _test_css = (
            f"QPushButton {{ background: transparent; color: {C.TEXT_DIM}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; }}"
            f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}"
            f"QPushButton:disabled {{ color: {C.BORDER}; }}"
        )

        def _row(label: str, kind: str, current: str) -> QComboBox:
            cap = QLabel(label)
            cap.setFont(QFont("Courier New", 8))
            cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(cap)

            box = QComboBox()
            box.setFont(QFont("Courier New", 9))
            box.setFixedHeight(30)
            box.setStyleSheet(_combo_css)
            # The list is served from a cache warmed on a background thread at
            # startup, so opening this panel never blocks the Qt thread on the
            # host audio API.
            box.addItem(DEFAULT_LABEL, "")
            for name in list_devices(kind):
                box.addItem(name, name)
            idx = box.findData(current) if current else 0
            box.setCurrentIndex(idx if idx >= 0 else 0)
            if current and idx < 0:
                # Saved device is not plugged in right now. Show it rather than
                # silently resetting the user's choice to default.
                box.addItem(f"{current}  (not connected)", current)
                box.setCurrentIndex(box.count() - 1)

            # THE ONE CHECK THE STARTUP PROBE CANNOT MAKE.
            #
            # core/audio_devices decides at launch whether a device opens and
            # whether it moves audio, and it does that with silence. A muted
            # microphone, a level slider at zero and a privacy shutter all pass
            # every one of those tests and still deliver a flat line — the only
            # thing that separates them from a working microphone is a person
            # speaking into it.
            #
            # So the button is here, beside the dropdown, in the panel somebody
            # opens when JARVIS cannot hear them. It replaces a loose
            # `ses_testi.py` in the project root that nobody would ever find.
            btn_row = QHBoxLayout(); btn_row.setSpacing(6)
            btn_row.addWidget(box, 1)
            test = QPushButton("TEST")
            test.setFixedSize(64, 30)
            test.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            test.setCursor(Qt.CursorShape.PointingHandCursor)
            test.setStyleSheet(_test_css)
            btn_row.addWidget(test)
            lay.addLayout(btn_row)

            # A meter, because a static label is indistinguishable from a hang.
            # Three seconds of "Speak now" with nothing moving was reported as
            # "I saw no sign of anything" — correctly, since nothing on screen
            # responded to the user's voice.
            meter = QProgressBar()
            meter.setRange(0, 100)
            meter.setValue(0)
            meter.setTextVisible(False)
            meter.setFixedHeight(6)
            meter.setStyleSheet(
                f"QProgressBar {{ background: #000d12; border: 1px solid {C.BORDER}; "
                f"border-radius: 3px; }}"
                f"QProgressBar::chunk {{ background: {C.PRI}; border-radius: 2px; }}")
            meter.hide()
            lay.addWidget(meter)

            result = QLabel("")
            result.setWordWrap(True)
            result.setFont(QFont("Courier New", 7))
            result.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(result)

            test.clicked.connect(
                lambda _=False, k=kind, b=box, t=test, r=result, m=meter:
                    self._run_test(k, b, t, r, m))
            return box

        # Which row is being tested right now. One at a time — the button is
        # disabled for the duration — so a single slot is enough, and it keeps
        # widgets off the signal payload.
        self._active = None                # (button, label, meter)
        self._level_seen.connect(self._on_level)
        self._test_result.connect(self._on_result)

        self._in_box  = _row("MICROPHONE — what JARVIS hears you with",
                             "input", get_input_device())
        lay.addSpacing(4)
        self._out_box = _row("SPEAKERS — what JARVIS talks through",
                             "output", get_output_device())

        # ── Output volume, beside the output device ──────────────────────────
        #
        # Choosing "Realtek(R) Audio" here and finding it far too quiet used to
        # mean leaving this panel, opening the system sound settings, finding
        # the same endpoint again and moving a slider there. The volume belongs
        # next to the device it applies to.
        _vol_now = None
        try:
            from core.audio_devices import get_output_volume
            # The SELECTED output, not the system default. Somebody puts the
            # assistant on their speakers and keeps everything else in their
            # headphones; a slider labelled with one device that moves the
            # other is worse than no slider at all.
            _vol_now = get_output_volume(self._out_box.currentData() or "")
        except Exception:
            pass

        if _vol_now is not None:
            vcap = QLabel("OUTPUT VOLUME")
            vcap.setFont(QFont("Courier New", 8))
            vcap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addSpacing(4)
            lay.addWidget(vcap)

            vrow = QHBoxLayout(); vrow.setSpacing(8)
            self._vol = QSlider(Qt.Orientation.Horizontal)
            self._vol.setRange(0, 100)
            self._vol.setValue(int(_vol_now))
            self._vol.setFixedHeight(22)
            self._vol.setStyleSheet(
                f"QSlider::groove:horizontal {{ background: #000d12; height: 4px; "
                f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
                f"QSlider::sub-page:horizontal {{ background: {C.PRI_DIM}; "
                f"border-radius: 2px; }}"
                f"QSlider::handle:horizontal {{ background: {C.PRI}; width: 10px; "
                f"margin: -5px 0; border-radius: 5px; }}")
            self._vol_lbl = QLabel(f"{int(_vol_now)}%")
            self._vol_lbl.setFont(QFont("Courier New", 8))
            self._vol_lbl.setFixedWidth(40)
            self._vol_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            vrow.addWidget(self._vol, 1)
            vrow.addWidget(self._vol_lbl)
            lay.addLayout(vrow)

            # valueChanged fires for every pixel of a drag, and each one is a
            # COM call into the audio endpoint. sliderReleased fires once, when
            # the user has decided — the label still follows the handle so the
            # number moves while they drag.
            self._vol.valueChanged.connect(
                lambda v: self._vol_lbl.setText(f"{v}%"))
            self._vol.sliderReleased.connect(self._apply_volume)
            self._out_box.currentIndexChanged.connect(
                lambda _i: self._volume_follows_device())

        note = QLabel("Applying reconnects the session. Your conversation is kept.")
        note.setWordWrap(True)
        note.setFont(QFont("Courier New", 7))
        note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(6)
        lay.addWidget(note)

        row = QHBoxLayout(); row.setSpacing(8)
        ok = QPushButton("▸  APPLY")
        ok.setFixedHeight(32)
        ok.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        ok.clicked.connect(self._apply)
        row.addWidget(ok)

        cancel = QPushButton("CLOSE")
        cancel.setFixedHeight(32)
        cancel.setFont(QFont("Courier New", 9))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel.clicked.connect(self.hide)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _apply_volume(self):
        """Set the system output volume from the slider, off the Qt thread.

        The Windows path goes through COM, which can block for tens of
        milliseconds; that is not long enough to see but is long enough to
        stutter a drag, and there is no reason to make the interface wait for
        it.
        """
        import threading
        value = self._vol.value()
        device = self._out_box.currentData() or ""

        def _work():
            from core import audio_devices
            if not audio_devices.set_output_volume(value, device):
                print(f"[Audio] the volume of '{device}' could not be set "
                      f"to {value}%")

        threading.Thread(target=_work, daemon=True, name="audio-volume").start()

    def _volume_follows_device(self):
        """Re-read the slider when the chosen output changes.

        Each device keeps its own level, so leaving the handle where it was
        would show the previous device's volume against the new device's name —
        and the next drag would then jump it there.
        """
        if not hasattr(self, "_vol"):
            return
        try:
            from core.audio_devices import get_output_volume
            now = get_output_volume(self._out_box.currentData() or "")
        except Exception:
            now = None
        if now is None:
            return
        self._vol.blockSignals(True)
        self._vol.setValue(int(now))
        self._vol.blockSignals(False)
        self._vol_lbl.setText(f"{int(now)}%")

    def _run_test(self, kind, box, button, label, meter=None):
        """Record or play for real, off the Qt thread.

        Both calls block for seconds — recording waits for the user to speak,
        the tone waits for itself — and doing that on the Qt thread freezes the
        HUD, which is the mistake Mark LV already paid for once with a 2.1
        second wake-word import in the settings drawer.

        Results come back by signal, not by timer. See the note on
        `_level_seen` above for why that distinction is the whole feature.
        """
        import threading

        name = box.currentData() or ""
        self._active = (button, label, meter)
        button.setEnabled(False)
        label.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        label.setText("Speak now…" if kind == "input" else "Playing a tone…")
        if meter is not None and kind == "input":
            meter.setValue(0)
            meter.show()

        def _work():
            from core import audio_devices
            try:
                if kind == "input":
                    res = audio_devices.measure_input(
                        name,
                        on_level=lambda f: self._level_seen.emit(int(f * 100)))
                    text = f"peak {res['peak']}  —  {res['verdict']}"
                else:
                    res = audio_devices.play_tone(name)
                    text = res["verdict"]
                good = bool(res.get("ok", False))
            except Exception as e:
                text, good = f"The test itself failed: {e}", False
            self._test_result.emit(text, good)

        threading.Thread(target=_work, daemon=True, name=f"audio-test-{kind}").start()

    def _on_level(self, value: int):
        """A live level, already on the GUI thread thanks to the signal."""
        if self._active and self._active[2] is not None:
            self._active[2].setValue(max(0, min(100, value)))

    def _on_result(self, text: str, good: bool):
        if not self._active:
            return
        button, label, meter = self._active
        self._active = None
        button.setEnabled(True)
        if meter is not None:
            meter.setValue(0)
            meter.hide()
        label.setStyleSheet(
            f"color: {C.PRI if good else C.TEXT_DIM}; background: transparent;")
        label.setText(text)

    def _apply(self):
        from memory.config_manager import (
            get_input_device, get_output_device,
            save_input_device, save_output_device,
        )
        new_in  = self._in_box.currentData()  or ""
        new_out = self._out_box.currentData() or ""
        changed = (new_in != get_input_device()) or (new_out != get_output_device())
        save_input_device(new_in)
        save_output_device(new_out)
        self.hide()
        # Only rebuild the session if something actually moved — a no-op Apply
        # should not cost a reconnect.
        if changed:
            self.picked.emit()


class MemoryOverlay(_HudOverlay):
    """Everything JARVIS has stored about you, and when it learned it.

    Memory used to be a 2200-character store that deleted its oldest entries
    when full and mentioned it only on stdout. The cap is gone; this panel is
    the other half of that change — a memory you cannot inspect is a memory you
    cannot trust, and 'delete' has to be something the person can do."""

    _OW = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MemoryOverlay {{
                background: rgba(0, 6, 10, 246);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(5)
        self._rebuild()

    def _clear_layout(self):
        """Take every item out of the layout and detach it from the widget tree
        in this call.

        deleteLater() on its own is not enough: it queues destruction for the
        next event-loop pass, and until then the old rows are still children of
        this widget and still paint — which is what drew half of the previous
        panel over the new one. setParent(None) removes them from the tree now;
        deleteLater() then frees them safely."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() stops it painting in this frame; deleteLater() frees it
                # safely afterwards. setParent(None) would also stop the paint,
                # but it turns the widget into a top-level window for the moment
                # between the two calls, which is not something to leave lying
                # around inside a click handler.
                w.hide()
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw is not None:
                        sw.hide()
                        sw.deleteLater()
                sub.deleteLater()

    def _settle(self, before):
        """Size the panel to its content, re-centre it, and repaint what the old
        size covered.

        The re-size has to happen here rather than at the end of _rebuild
        because Qt has not polished the freshly-created children at that point,
        so the size hint it would read is the empty-layout one. Measured: a
        first adjustSize() returned 32 px for a panel whose content needed 155,
        and a second call — after the same widgets had been through the event
        loop — returned 155. So this runs twice: once now, once on the next
        turn, from _rebuild.

        The re-centre and the repaint are needed because the overlay is placed
        by hand and is in no layout: shrinking it leaves it off-centre and
        leaves its former pixels on screen, since nothing tells the parent that
        region changed. The repaint has to cover the union of the old and new
        rectangles."""
        self._lay.invalidate()
        self._lay.activate()
        self.updateGeometry()
        self.adjustSize()

        p = self.parentWidget()
        if p is None:
            self.update()
            return
        self.move(max(0, (p.width()  - self.width())  // 2),
                  max(0, (p.height() - self.height()) // 2))
        p.update(before.united(self.geometry()))
        self.update()

    def _rebuild(self):
        before = self.geometry()
        self._clear_layout()

        from memory.memory_manager import all_entries_for_ui

        hdr = QLabel("🧠  WHAT JARVIS REMEMBERS")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        self._lay.addWidget(sep)

        rows = all_entries_for_ui()

        cap = QLabel(f"{len(rows)} stored facts — newest first. "
                     f"Nothing here is sent anywhere; it lives in "
                     f"memory/long_term.json on this machine.")
        cap.setWordWrap(True)
        cap.setFont(QFont("Courier New", 7))
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(cap)

        if not rows:
            empty = QLabel("Nothing stored yet.")
            empty.setFont(QFont("Courier New", 9))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            self._lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(min(420, 34 * len(rows) + 10))
            scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {C.BORDER}; border-radius: 3px; "
                f"background: transparent; }}"
            )
            inner = QWidget()
            ilay  = QVBoxLayout(inner)
            ilay.setContentsMargins(6, 6, 6, 6)
            ilay.setSpacing(3)

            for r in rows:
                line = QHBoxLayout(); line.setSpacing(6)
                txt = QLabel(f"<b>{r['key'].replace('_', ' ')}</b> "
                             f"<span style='color:{C.TEXT_MED}'>— {r['value']}</span>")
                txt.setWordWrap(True)
                txt.setFont(QFont("Courier New", 8))
                txt.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
                line.addWidget(txt, 1)

                meta = QLabel(f"{r['category'][:4]} · {r['updated'] or '—'}")
                meta.setFont(QFont("Courier New", 7))
                meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                line.addWidget(meta)

                rm = QPushButton("✕")
                rm.setFixedSize(20, 20)
                rm.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip("Forget this")
                rm.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
                """)
                rm.clicked.connect(
                    lambda _=False, c=r["category"], k=r["key"]: self._forget(c, k))
                line.addWidget(rm)

                holder = QWidget()
                holder.setLayout(line)
                ilay.addWidget(holder)

            ilay.addStretch()
            scroll.setWidget(inner)
            self._lay.addWidget(scroll)

        close = QPushButton("CLOSE")
        close.setFixedHeight(30)
        close.setFont(QFont("Courier New", 9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        self._lay.addWidget(close)

        self._settle(before)
        # …and again once Qt has polished the new children, because the size
        # hint is not final until then. Harmless when the first pass already
        # got it right: _settle is idempotent.
        QTimer.singleShot(0, lambda g=before: self._settle(g))

    def _forget(self, category: str, key: str):
        from memory.memory_manager import forget
        forget(key, category)
        # Rebuild on the NEXT event-loop turn, not inside this click handler.
        # The rebuild destroys the very ✕ button that emitted this signal, and
        # Qt is entitled to touch the sender after a slot returns; tearing it
        # down mid-emission is how a widget ends up half-alive on screen.
        QTimer.singleShot(0, self._rebuild)


class _ScrollSafeCombo(QComboBox):
    """A dropdown that does not change when you scroll past it.

    Qt's default is that a combo box under the pointer swallows the wheel and
    steps its own value with it. Inside a scrolling panel that is not a
    convenience, it is a trap: scrolling down the list of settings silently
    changes whichever ones the pointer crossed on the way, and nothing on screen
    says so. It was reported as "selections move around when I scroll", and it
    is the same bug every Qt settings panel has until somebody fixes it.

    The wheel is only accepted when the box has been clicked into. Otherwise the
    event is passed up, which is what makes the panel scroll instead.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # StrongFocus so it can still be tabbed to and used from the keyboard;
        # the wheel is gated on having focus, not on being focusable.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class ProvidersOverlay(_HudOverlay):
    """Choose what runs the assistant: Gemini Live, or your own stack.

    WHAT THE FIRST VERSION GOT WRONG, AND WHY IT IS WORTH WRITING DOWN
        It listed the PROVIDERS, and a provider here covers thirteen services at
        once because they all speak the same protocol. That is the right shape
        for the code — it is why `llm_openai.py` is one file instead of thirteen
        — and it is the wrong shape for a person.

        Watched in use: somebody who wanted to run a model on their own machine
        opened the dropdown, saw a single entry reading "OpenAI-compatible", and
        concluded the feature was not there. They were right to. Nobody looking
        for Ollama searches for the name of a protocol, and "OpenAI" is the last
        word you expect to find under "run it locally".

        So the panel now lists what people are actually looking for — Ollama, LM
        Studio, Groq, DeepSeek — from each provider's own `catalog`. One file
        behind the scenes, thirteen recognisable names in front of them.

    THE OTHER TWO CHANGES
        It was 560 pixels of stacked dropdowns with no grouping, which reads as
        a form to be endured rather than three decisions to be made. It is 760
        wide now, and the three parts of a conversation are three numbered boxes
        that say what they do in plain words.

        And every field a provider declares was shown at once — download folders,
        stability weights, thread counts. A setting almost nobody changes costs
        more in the confusion it adds to the five that matter than it saves for
        the one person who wants it, so `advanced` fields sit behind MORE.

    WHAT IT COSTS WHEN NOBODY OPENS IT
        Nothing. The button is built with the rest of the SETUP drawer, but the
        `providers` package is imported inside `__init__` of THIS class — on the
        click. Same lesson as the wake-word check that spent a measured 2.104
        seconds importing `openwakeword` on the Qt thread and made the drawer
        look broken.
    """

    changed = pyqtSignal()          # emitted on APPLY when the engine moved
    # Emitted from a worker thread when something the machine had to be asked
    # for — the installed voices — has arrived. A signal rather than a direct
    # call because the worker must not touch a widget.
    _live_ready = pyqtSignal()
    # (provider id, [(value, label), ...]) from a worker that went and asked an
    # endpoint what it offers.
    _models_ready = pyqtSignal(str, list)
    _OW = 760                       # the window's own minimum is 820

    # Which provider fills each slot, and what the slot is FOR — in the words
    # somebody configuring it would use, not the words the code uses.
    _SLOTS = (
        ("stt", "①", "HEARING",  "turns what you say into words"),
        ("llm", "②", "THINKING", "understands, decides, uses your tools"),
        ("tts", "③", "SPEAKING", "reads the answer out loud"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        # Imported HERE, on the click — never at startup. See the class docstring.
        from memory.config_manager import (get_pipeline, get_provider_config,
                                           get_provider_mode, get_sidecar_first,
                                           get_sidecar_provider)
        from providers import registry

        self._registry = registry
        self._get_cfg = get_provider_config
        # Warm anything a provider can only learn by asking the machine, off
        # this thread. The installed voice list costs a PowerShell subprocess —
        # measured at 1.70 seconds — and the form asks for it on every rebuild,
        # so without this the panel freezes for most of two seconds every time
        # a dropdown is touched. Started here rather than at startup, because
        # nothing in this folder may run before somebody opens it.
        self._live_ready.connect(self._on_live_ready)
        self._models_ready.connect(self._on_models_ready)
        self._model_cache: dict[str, list] = {}
        self._fetching: set = set()
        for _kind in ("tts", "stt", "llm"):
            for _decl in registry.discover(_kind):
                try:
                    _mod = __import__(f"providers.{_decl['_module']}",
                                      fromlist=["prefetch"])
                    _pf = getattr(_mod, "prefetch", None)
                    if _pf:
                        _pf(self._live_ready.emit)
                except Exception:
                    pass
        self._edits: dict[str, dict] = {}       # provider id -> {key: (widget, Field)}
        self._status: dict[str, QLabel] = {}    # provider id -> status line
        self._more: dict[str, bool] = {}        # provider id -> advanced shown
        # Fields deliberately not drawn — the catalog already answered them, or
        # they are behind MORE. Tracked rather than asked of Qt: see _fields_into.
        self._hidden: dict[str, set] = {}
        self._picked: dict[str, str] = {}       # slot -> catalog entry id

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ProvidersOverlay {{
                background: rgba(0, 6, 10, 249);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        self.setFixedWidth(self._OW)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(10)

        title = QLabel("🔌  ENGINE  &  PROVIDERS")
        title.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        outer.addWidget(title)

        sub = QLabel("Choose what powers the conversation. "
                     "Gemini is the default and needs nothing set up here.")
        sub.setWordWrap(True)
        sub.setFont(QFont("Courier New", 8))
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        outer.addWidget(sub)

        # ── Mode: two cards, not a dropdown ─────────────────────────────────
        # A dropdown hides the option you did not choose. This is the one
        # decision on the panel that changes everything below it, and both
        # answers deserve to be readable at the same time.
        self._mode = get_provider_mode()
        cards = QHBoxLayout(); cards.setSpacing(10)
        self._card_gemini = self._mode_card(
            "☁  GEMINI LIVE",
            "One connection carries your voice, its voice, the transcript and "
            "the tools together. The fastest option — about half a second to "
            "the first word.",
            "gemini")
        self._card_local = self._mode_card(
            "🖥  MY OWN SETUP",
            "Your choice of hearing, thinking and speaking. Can run entirely on "
            "this computer, with nothing leaving it. Slower: 1.5 to 4 seconds.",
            "pipeline")
        cards.addWidget(self._card_gemini)
        cards.addWidget(self._card_local)
        outer.addLayout(cards)

        # ── Body ────────────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            f"QScrollBar:vertical {{ background: {C.DARK}; width: 9px; "
            f"margin: 0; border-radius: 4px; }}"
            f"QScrollBar::handle:vertical {{ background: {C.BORDER_B}; "
            f"border-radius: 4px; min-height: 30px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: none; }")
        self._scroll.setMinimumHeight(230)
        self._scroll.setMaximumHeight(360)
        outer.addWidget(self._scroll, 1)

        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 2, 8, 2)
        self._body_lay.setSpacing(10)
        self._scroll.setWidget(self._body)

        # Built BEFORE the body, because `_rebuild_body` writes into it — and
        # added to the layout after, so it still sits under the scroll area.
        self._footer = QLabel("")
        self._footer.setWordWrap(True)
        self._footer.setFont(QFont("Courier New", 7))
        self._footer.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")

        self._pipe = dict(get_pipeline())
        self._sidecar = get_sidecar_provider()
        self._sidecar_first = get_sidecar_first()
        self._rebuild_body()

        outer.addWidget(self._footer)

        row = QHBoxLayout(); row.setSpacing(8)
        apply_btn = QPushButton("▸  SAVE  &  APPLY")
        apply_btn.setFixedHeight(34)
        apply_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 4px; }}
            QPushButton:hover {{ background: {C.BORDER}; border-color: {C.PRI}; }}
        """)
        apply_btn.clicked.connect(self._apply)
        row.addWidget(apply_btn, 2)

        close = QPushButton("CLOSE")
        close.setFixedHeight(34)
        close.setFont(QFont("Courier New", 9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 4px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        row.addWidget(close, 1)
        outer.addLayout(row)
        self._refresh_cards()

    # ── pieces ───────────────────────────────────────────────────────────────
    def _mode_card(self, title: str, body: str, value: str) -> QPushButton:
        b = QPushButton()
        b.setCheckable(True)
        b.setMinimumHeight(84)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setText(f"{title}\n\n{body}")
        b.setFont(QFont("Courier New", 7))
        b.clicked.connect(lambda _=0, v=value: self._set_mode(v))
        b.setProperty("modeValue", value)
        return b

    def _refresh_cards(self) -> None:
        for card in (self._card_gemini, self._card_local):
            on = card.property("modeValue") == self._mode
            card.setChecked(on)
            card.setStyleSheet(f"""
                QPushButton {{
                    text-align: left; padding: 10px 12px;
                    background: {C.PRI_GHO if on else 'transparent'};
                    color: {C.TEXT if on else C.TEXT_DIM};
                    border: 1px solid {C.PRI_DIM if on else C.BORDER};
                    border-radius: 5px;
                }}
                QPushButton:hover {{ border-color: {C.BORDER_B}; }}
            """)

    def _on_live_ready(self) -> None:
        """A machine-supplied list has arrived — redraw once so it appears."""
        if not self.isHidden():
            self._rebuild_body()

    # ── Asking an endpoint what it has, without being asked to ──────────────
    def _fetch_models(self, pid: str) -> None:
        """Go and get the model list in the background.

        Pressing LIST worked, and making somebody press it was still wrong: at
        the moment a local server is chosen, the one thing they need is the list
        of models on it, and the app can simply go and read it. A button whose
        only job is "now do the obvious next thing" is a button that should not
        exist.

        Off the interface thread, because it is a network call — a local server
        answers in milliseconds and a cloud one does not, and a panel that
        freezes while it finds out is worse than one that fills in a second
        later. Failure is silent: not reaching the endpoint yet is the normal
        state while somebody is still typing an address, and TEST is where a
        real answer about reachability belongs."""
        import threading

        if not pid or pid in self._fetching:
            return
        try:
            values = self._values(pid) or dict(self._get_cfg(pid))
        except Exception:
            values = dict(self._get_cfg(pid))
        if not values.get("base_url") and not values.get("api_key"):
            return
        self._fetching.add(pid)

        def work():
            items = []
            try:
                inst = self._registry.build(pid, values)
                if hasattr(inst, "models"):
                    items = [(m, m) for m in inst.models(timeout=6.0)]
                elif hasattr(inst, "voices"):
                    items = list(inst.voices())
            except Exception:
                items = []
            finally:
                self._fetching.discard(pid)
            if items:
                self._models_ready.emit(pid, items)

        threading.Thread(target=work, daemon=True).start()

    def _prepare(self, pid: str) -> None:
        """Let a provider get itself ready as soon as it is configured.

        Piper uses it to download the chosen voice. Generic on purpose: the
        panel asks whether the module has a `prepare`, and providers that do not
        need one are simply skipped — nothing here knows what a voice is."""
        import threading

        try:
            decl = self._registry.get_declaration(pid)
            mod = __import__(f"providers.{decl['_module']}", fromlist=["prepare"])
            fn = getattr(mod, "prepare", None)
        except Exception:
            fn = None
        if fn is None:
            return
        values = self._values(pid) or dict(self._get_cfg(pid))

        def report(ok, msg):
            colour = C.TEXT_DIM if ok is None else (C.GREEN if ok else C.RED)
            mark = "" if ok is None else ("✓  " if ok else "✕  ")
            QTimer.singleShot(0, lambda: self._say(pid, mark + msg, colour))

        threading.Thread(target=lambda: fn(values, report), daemon=True).start()

    def _on_models_ready(self, pid: str, items: list) -> None:
        self._model_cache[pid] = list(items)
        if self.isHidden():
            return
        key = "voice_id" if any(v != l for v, l in items) else "model"
        entry = self._edits.get(pid, {}).get(key)
        if entry is None:
            entry = self._edits.get(pid, {}).get("model")
        if entry is None or not isinstance(entry[0], QComboBox):
            return
        box = entry[0]
        keep = box.currentText()
        box.clear()
        for value, label in items:
            box.addItem(str(label), str(value))
        j = box.findData(keep)
        if j >= 0:
            box.setCurrentIndex(j)
        elif keep:
            box.setCurrentText(keep)
        self._say(pid, f"{len(items)} model{'s' if len(items) != 1 else ''} "
                       f"found on this server — pick one above.", C.TEXT_DIM)

    def _set_mode(self, value: str) -> None:
        if value == self._mode:
            self._refresh_cards()
            return
        self._mode = value
        self._remember_edits()
        self._refresh_cards()
        QTimer.singleShot(0, self._rebuild_body)

    def _box(self, title_widgets: list) -> tuple[QWidget, QVBoxLayout]:
        """A bordered section. Grouping is the difference between three
        decisions and eleven controls."""
        w = QWidget()
        w.setStyleSheet(f"background: {C.PANEL}; border: 1px solid {C.BORDER}; "
                        f"border-radius: 5px;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 11)
        lay.setSpacing(5)
        for tw in title_widgets:
            lay.addWidget(tw)
        return w, lay

    def _label(self, text: str, size: int = 8, colour: str = None,
               bold: bool = False) -> QLabel:
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setFont(QFont("Courier New", size,
                         QFont.Weight.Bold if bold else QFont.Weight.Normal))
        lb.setStyleSheet(f"color: {colour or C.TEXT_MED}; background: transparent; "
                         f"border: none;")
        return lb

    def _combo(self) -> QComboBox:
        box = _ScrollSafeCombo()
        box.setFont(QFont("Courier New", 8))
        box.setFixedHeight(29)
        box.setStyleSheet(
            f"QComboBox {{ background: {C.DARK}; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 9px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: {C.DARK}; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; "
            f"border: 1px solid {C.BORDER_B}; padding: 2px; }}")
        return box

    def _line(self, text: str = "") -> QLineEdit:
        w = QLineEdit(text)
        w.setFont(QFont("Courier New", 8))
        w.setFixedHeight(27)
        w.setStyleSheet(
            f"QLineEdit {{ background: {C.DARK}; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 9px; }}"
            f"QLineEdit:focus {{ border-color: {C.PRI_DIM}; }}")
        return w

    def _btn(self, text: str, slot, colour: str = None) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(25)
        b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        col = colour or C.TEXT_MED
        b.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {col};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 0 12px; }}
            QPushButton:hover {{ border-color: {C.BORDER_B}; color: {C.TEXT}; }}
        """)
        b.clicked.connect(slot)
        return b

    # ── catalog ──────────────────────────────────────────────────────────────
    def _catalog(self, kind: str) -> list[tuple[str, str, dict, dict]]:
        """(provider id, entry id, entry, declaration) for one slot.

        A provider with no catalog contributes itself as a single entry, so
        nothing has to declare one to appear."""
        out = []
        for decl in self._registry.discover(kind):
            entries = decl.get("catalog") or (
                {"id": decl["id"], "label": decl["label"],
                 "note": decl.get("hint", ""), "local": None, "values": {}},)
            for e in entries:
                out.append((decl["id"], e["id"], e, decl))
        return out

    def _current_entry(self, kind: str, pid: str) -> str:
        """Which catalog entry is selected.

        STORED, not derived. The first version worked it out by comparing the
        saved address against each entry's — which is elegant and wrong, and it
        showed up immediately: pick "Whisper on this computer", reopen the
        panel, and the box reads "— not set —" while the form beneath it is
        fully drawn. That entry's address is the empty string, so any config
        whose address had ever been touched matched nothing and fell through to
        no selection at all.

        The entry is a CHOICE somebody made, not a fact about the settings.
        Choices get stored. The derivation is kept only as a fallback for a
        config written before this key existed."""
        if not pid:
            return ""
        cfg = self._get_cfg(pid)
        saved = str(cfg.get("catalog") or "").strip()
        entries = [(eid, entry) for _p, eid, entry, _d in self._catalog(kind)
                   if _p == pid]
        if saved and any(eid == saved for eid, _e in entries):
            return saved

        # Written before the key existed: work it out once, from the address.
        best = ""
        for eid, entry in entries:
            vals = entry.get("values") or {}
            if not vals:
                best = best or eid            # a catch-all like "Something else"
                continue
            if all(str(cfg.get(k, "")).rstrip("/") == str(v).rstrip("/")
                   for k, v in vals.items() if k in ("base_url", "backend")):
                return eid
        return best or (entries[0][0] if len(entries) == 1 else "")

    # ── body ─────────────────────────────────────────────────────────────────
    def _clear(self, lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                self._clear(item.layout())

    def _rebuild_body(self) -> None:
        # Keep whatever is in the boxes before they are destroyed.
        #
        # A redraw can be triggered by things the person did not do: a model
        # list arriving from a background fetch, a slot changing, the panel
        # settling after a click. Every one of those replaces the widgets, and
        # anything typed but not yet saved went with them — most visibly a model
        # name entered by hand, which came back empty on SAVE with no
        # indication that it had been dropped.
        self._remember_edits()
        self._clear(self._body_lay)
        self._edits.clear()
        self._status.clear()

        if self._mode == "pipeline":
            for slot, num, name, what in self._SLOTS:
                self._body_lay.addWidget(self._slot_box(slot, num, name, what))
        else:
            w, lay = self._box([])
            lay.addWidget(self._label(
                "Nothing to set up. Your voice goes to Gemini and comes back as "
                "speech over one connection, with the transcript and every tool "
                "call on the same wire.", 8, C.TEXT_DIM))
            lay.addWidget(self._label(
                "Pick MY OWN SETUP above to run it on your own machine, or "
                "through another company's model.", 7, C.TEXT_DIM))
            self._body_lay.addWidget(w)

        self._body_lay.addWidget(self._sidecar_box_widget())
        self._body_lay.addStretch(1)
        self._update_footer()

    def _slot_box(self, slot: str, num: str, name: str, what: str) -> QWidget:
        head = self._label(f"{num}  {name}", 9, C.PRI, bold=True)
        w, lay = self._box([head, self._label(what, 7, C.TEXT_DIM)])

        entries = self._catalog(slot)
        box = self._combo()
        box.addItem("— not set —", ("", ""))
        for pid, eid, entry, decl in entries:
            label = entry["label"]
            if entry.get("local") is True:
                label = f"🖥  {label}"
            elif entry.get("local") is False:
                label = f"☁  {label}"
            else:
                label = f"    {label}"
            note = entry.get("note") or ""
            if not decl.get("_available", True):
                note = (note + " · needs install").strip(" ·")
            box.addItem(f"{label}{'   —  ' + note if note else ''}", (pid, eid))

        pid_now = self._pipe.get(slot, "")
        eid_now = self._picked.get(slot) or self._current_entry(slot, pid_now)
        idx = box.findData((pid_now, eid_now)) if pid_now else 0
        if pid_now and idx < 0:
            # A provider IS chosen — the form for it is drawn right below — so
            # the box must never read "not set". It did, and it was the first
            # thing anybody noticed: an entry whose settings no longer match
            # any catalog row (upgraded from an older layout, or edited by
            # hand) resolved to nothing at all, and the panel contradicted
            # itself on screen. Falling back to that provider's first row is
            # always closer to the truth than claiming nothing is selected.
            for i in range(box.count()):
                data = box.itemData(i)
                if data and data[0] == pid_now:
                    idx = i
                    self._picked[slot] = data[1]
                    break
        box.setCurrentIndex(idx if idx >= 0 else 0)
        box.currentIndexChanged.connect(
            lambda _i, s=slot, b=box: self._slot_changed(s, b))
        if pid_now:
            QTimer.singleShot(0, lambda p=pid_now: self._prepare(p))
        lay.addWidget(box)

        if pid_now:
            self._fields_into(lay, slot, pid_now, eid_now)
            # If a list was already fetched, use it; if not, go and get one.
            if self._model_cache.get(pid_now):
                QTimer.singleShot(0, lambda p=pid_now: self._on_models_ready(
                    p, self._model_cache[p]))
            else:
                QTimer.singleShot(0, lambda p=pid_now: self._fetch_models(p))
        return w

    def _slot_changed(self, slot: str, box: QComboBox) -> None:
        pid, eid = box.currentData() or ("", "")
        self._remember_edits()
        self._pipe[slot] = pid
        self._picked[slot] = eid
        if pid and eid:
            # Applying the shortcut is the entire point of the catalog: pick
            # Ollama and the address is already right. The choice itself is
            # saved alongside it — see _current_entry for why.
            from memory.config_manager import save_provider_config
            for _p, _e, entry, _d in self._catalog(slot):
                if _p == pid and _e == eid:
                    values = dict(entry.get("values") or {})
                    values["catalog"] = eid
                    save_provider_config(pid, values)
                    break
            self._fetch_models(pid)
        QTimer.singleShot(0, self._rebuild_body)

    def _fields_into(self, lay, slot: str, pid: str, eid: str) -> None:
        from providers.base import Field

        decl = self._registry.get_declaration(pid)
        if decl is None:
            return
        stored = dict(self._get_cfg(pid))
        entry = next((e for p, i, e, _ in self._catalog(slot)
                      if p == pid and i == eid), {})
        is_local = entry.get("local") is True
        entry_values = entry.get("values") or {}
        # An entry that MENTIONS the address has answered it — including
        # answering it with "", which is what the local speech recogniser does
        # because it does not use one at all. Testing the value rather than the
        # presence of the key is what put an empty "API address" box under
        # "Whisper on this computer", inviting somebody to fill in a field that
        # backend never reads.
        custom = "base_url" not in entry_values

        # Three buckets, tracked explicitly.
        #
        # `isHidden()` is NOT a usable test for "I hid this on purpose": a widget
        # that has not been added to a layout yet is already hidden, so asking it
        # returned True for every field and the form came up completely empty.
        # Which of these a field lands in is a decision made here, so it is kept
        # here rather than inferred from Qt afterwards.
        shown: dict = {}        # drawn now
        carried: dict = {}      # kept for saving, never drawn — answered by the catalog
        advanced: list = []     # drawn only behind MORE

        for f in decl.get("needs", ()):
            if not isinstance(f, Field):
                continue
            # Do not show what the catalog entry already answered. The address
            # somebody did not have to type is one more thing to read and one
            # more thing to break; a key a local server never asks for is a box
            # that makes people think they need an account.
            if f.key == "base_url" and not custom:
                carried[f.key] = (self._line(
                    str(stored.get(f.key, f.default) or "")), f)
                continue
            if f.key == "api_key" and is_local:
                carried[f.key] = (self._line(str(stored.get(f.key, "") or "")), f)
                continue
            if f.key == "backend":
                carried[f.key] = (self._line(
                    str(entry.get("values", {}).get("backend")
                        or stored.get(f.key, f.default) or "")), f)
                continue
            w = self._make_widget(pid, f, stored.get(f.key, f.default))
            if f.advanced:
                advanced.append((f, w))
            else:
                shown[f.key] = (w, f)

        for _key, (w, f) in shown.items():
            lay.addWidget(self._label(
                f.label + ("" if f.required else "   (optional)"), 7, C.TEXT_DIM))
            lay.addWidget(w)
            # A text box already shows its hint as placeholder text. Adding the
            # label as well printed every hint twice, which is how the panel
            # came to look careless.
            if f.hint and not isinstance(w, QLineEdit):
                lay.addWidget(self._label(f.hint, 7, C.TEXT_DIM))

        fields = dict(shown)
        fields.update(carried)
        self._hidden[pid] = set(carried) | {f.key for f, _w in advanced}

        # Buttons and status.
        status = self._label("", 7, C.TEXT_DIM)
        self._status[pid] = status

        brow = QHBoxLayout(); brow.setSpacing(6)
        brow.addWidget(self._btn("TEST", lambda _=0, p=pid: self._test(p), C.PRI))
        # Not "LIST" any more: the list arrives on its own when a service is
        # chosen. This is the button for when it did not — the server was
        # starting up, or a model has just been pulled.
        if any(k in shown for k in ("model", "voice_id", "voice")):
            brow.addWidget(self._btn("↻ REFRESH", lambda _=0, p=pid: self._list(p)))
        if advanced:
            brow.addWidget(self._btn(
                ("⌃ LESS" if self._more.get(pid) else "⌄ MORE"),
                lambda _=0, p=pid: self._toggle_more(p)))
        if not decl.get("_available", True) and decl.get("install"):
            brow.addWidget(self._btn(f"INSTALL {decl['install']}",
                                     lambda _=0, p=pid: self._install(p), C.ACC2))
        brow.addStretch(1)
        holder = QWidget()
        holder.setStyleSheet("background: transparent; border: none;")
        holder.setLayout(brow)
        lay.addWidget(holder)
        lay.addWidget(status)

        if self._more.get(pid):
            lay.addWidget(self._label("─" * 46, 7, C.BORDER))
            for f, w in advanced:
                lay.addWidget(self._label(f"{f.label}   (optional)", 7, C.TEXT_DIM))
                lay.addWidget(w)
                if f.hint and not isinstance(w, QLineEdit):
                    lay.addWidget(self._label(f.hint, 7, C.TEXT_DIM))
                fields[f.key] = (w, f)
                self._hidden[pid].discard(f.key)
        else:
            for f, w in advanced:
                fields[f.key] = (w, f)

        self._edits[pid] = fields

    def _make_widget(self, pid: str, f, value):
        if f.kind == "choice":
            w = self._combo()
            choices = list(self._live_choices(pid, f.key) or f.choices)
            if not f.required:
                w.addItem("— default —", "")
            for c in choices:
                w.addItem(str(c), str(c))
            w.setEditable(f.key in ("base_url", "model", "voice_id"))
            if w.isEditable():
                w.lineEdit().setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            if value:
                j = w.findData(str(value))
                if j < 0:
                    w.addItem(str(value), str(value))
                    j = w.count() - 1
                w.setCurrentIndex(j)
                if w.isEditable():
                    w.setCurrentText(str(value))
            return w
        if f.kind == "bool":
            w = self._combo()
            w.addItem("no", "")
            w.addItem("yes", "1")
            w.setCurrentIndex(1 if str(value) in ("1", "True", "true") else 0)
            return w
        w = self._line(str(value if value is not None else ""))
        if f.kind == "secret":
            w.setEchoMode(QLineEdit.EchoMode.Password)
        if f.hint:
            w.setPlaceholderText(f.hint[:64])
        return w

    def _toggle_more(self, pid: str) -> None:
        self._more[pid] = not self._more.get(pid)
        self._remember_edits()
        QTimer.singleShot(0, self._rebuild_body)

    def _sidecar_box_widget(self) -> QWidget:
        head = self._label("⚡  BACKGROUND REQUESTS", 9, C.PRI, bold=True)
        w, lay = self._box([head])
        lay.addWidget(self._label(
            "Reading a document, looking at your screen, writing code — the "
            "assistant's own requests, not the conversation. These use Gemini's "
            "text quota, which runs out before the voice does. Sending them "
            "somewhere else keeps them working, and changes nothing you hear.",
            7, C.TEXT_DIM))

        # Read the stored choice BEFORE the box exists. The first version asked
        # `_sidecar_choice()`, which reads the combo — and at this point that is
        # the empty box being built, so the answer was always "nothing chosen"
        # and the form under it never appeared.
        cur_pid = self._sidecar
        cur_eid = self._current_entry("llm", cur_pid) if cur_pid else ""

        self._sidecar_combo = self._combo()
        self._sidecar_combo.addItem("Gemini only  —  the way it has always been",
                                    ("", ""))
        for pid, eid, entry, decl in self._catalog("llm"):
            mark = "🖥" if entry.get("local") else ("☁" if entry.get("local")
                                                   is False else "  ")
            self._sidecar_combo.addItem(
                f"{mark}  Fall back to {entry['label']}", (pid, eid))
        i = self._sidecar_combo.findData((cur_pid, cur_eid)) if cur_pid else 0
        if cur_pid and i < 0:
            for j in range(1, self._sidecar_combo.count()):
                if (self._sidecar_combo.itemData(j) or ("", ""))[0] == cur_pid:
                    i = j
                    break
        self._sidecar_combo.setCurrentIndex(max(0, i))
        self._sidecar_combo.currentIndexChanged.connect(self._sidecar_changed)
        lay.addWidget(self._sidecar_combo)

        self._first_combo = self._combo()
        self._first_combo.addItem("Try Gemini first  —  faster", "after")
        self._first_combo.addItem(
            "Try the other one first  —  keeps more on your machine", "before")
        self._first_combo.setCurrentIndex(1 if self._sidecar_first else 0)
        lay.addWidget(self._first_combo)

        # In pipeline mode the model chosen for ② THINKING answers these too, so
        # there is nothing more to fill in. In Gemini mode there IS no ② section
        # — and the first version still said "it uses whatever you set up under
        # ② THINKING", which named a box that was not on the screen. So a
        # service picked here gets its own form, right here.
        if cur_pid:
            if self._mode == "pipeline" and cur_pid == self._pipe.get("llm"):
                lay.addWidget(self._label(
                    "Uses the model you chose for ② THINKING.", 7, C.TEXT_DIM))
            else:
                self._fields_into(lay, "llm", cur_pid, cur_eid)
        else:
            lay.addWidget(self._label(
                "Left as it is, these keep using Gemini and stop working when "
                "its text quota runs out.", 7, C.TEXT_DIM))
        return w

    def _sidecar_choice(self) -> tuple:
        """(provider id, catalog entry id) for the background-request model."""
        box = getattr(self, "_sidecar_combo", None)
        if box is not None:
            data = box.currentData()
            if isinstance(data, tuple):
                return data
        pid = self._sidecar
        return (pid, self._current_entry("llm", pid) if pid else "")

    def _sidecar_changed(self, _ix) -> None:
        pid, eid = self._sidecar_choice()
        self._remember_edits()
        self._sidecar = pid
        if pid and eid:
            from memory.config_manager import save_provider_config
            for _p, _e, entry, _d in self._catalog("llm"):
                if _p == pid and _e == eid:
                    values = dict(entry.get("values") or {})
                    values["catalog"] = eid
                    save_provider_config(pid, values)
                    break
        QTimer.singleShot(0, self._rebuild_body)

    def _update_footer(self) -> None:
        if self._mode != "pipeline":
            self._footer.setText(
                "Gemini Live. Nothing on this panel changes the conversation.")
            return
        missing = [name for slot, _n, name, _w in self._SLOTS
                   if not self._pipe.get(slot)]
        if "THINKING" in missing:
            self._footer.setText(
                "⚠  ② THINKING is not set — without it the assistant falls back "
                "to Gemini Live and says so in the log.")
        elif missing:
            words = " and ".join(f"{m.lower()}" for m in missing)
            self._footer.setText(
                f"Only {words} is missing — it will run, but you will type "
                f"instead of speak, or read instead of listen.")
        else:
            self._footer.setText(
                "All three set. SAVE & APPLY reconnects; the conversation is kept.")

    # ── actions ──────────────────────────────────────────────────────────────
    def _live_choices(self, pid: str, key: str) -> tuple:
        try:
            decl = self._registry.get_declaration(pid)
            mod = __import__(f"providers.{decl['_module']}", fromlist=["choices_for"])
            fn = getattr(mod, "choices_for", None)
            return tuple(fn(key)) if fn else ()
        except Exception:
            return ()

    def _values(self, pid: str) -> dict:
        out = {}
        hidden = self._hidden.get(pid, set())
        stored = self._get_cfg(pid)
        for key, (w, _f) in self._edits.get(pid, {}).items():
            if isinstance(w, QComboBox):
                value = (w.currentText().strip() if w.isEditable()
                         else (w.currentData() or ""))
            else:
                value = w.text().strip()
            # A field nobody can see must never blank out a setting that has
            # one. These widgets are rebuilt on every redraw, and a redraw that
            # raced a background fetch could recreate a hidden address as empty
            # and then save that over a working one — leaving a pipeline that
            # had been configured correctly pointing at nothing, with no visible
            # cause. Clearing a value is still possible; it just has to be done
            # in a box that is on screen.
            if not value and key in hidden and stored.get(key):
                continue
            out[key] = value
        return out

    def _remember_edits(self) -> None:
        """Keep what has been typed when the form is rebuilt.

        Without it, changing the speech engine wiped an API key somebody had
        just entered into the box above."""
        from memory.config_manager import save_provider_config
        for pid in list(self._edits):
            try:
                save_provider_config(pid, self._values(pid))
            except Exception:
                pass

    def _say(self, pid: str, text: str, colour: str) -> None:
        lb = self._status.get(pid)
        if lb is not None:
            lb.setText(text)
            lb.setStyleSheet(f"color: {colour}; background: transparent; border: none;")

    def _test(self, pid: str) -> None:
        # Read the boxes BEFORE letting Qt run. `processEvents` will happily
        # deliver a queued rebuild, which deletes the very widgets this is
        # about to read — and a deleted QWidget raises rather than returning
        # something wrong, so it takes the click down with it.
        values = self._values(pid)
        self._say(pid, "checking…", C.TEXT_DIM)
        QApplication.processEvents()
        try:
            inst = self._registry.build(pid, values)
            probe = getattr(inst, "probe", None)
            if probe is None:
                self._say(pid, "Nothing to check for this one.", C.TEXT_DIM)
                return
            ok, msg = probe()
        except Exception as e:
            self._say(pid, f"✕  {type(e).__name__}: {str(e)[:150]}", C.RED)
            return
        self._say(pid, ("✓  " if ok else "✕  ") + msg, C.GREEN if ok else C.ACC)
        # TEST is also where "can this model see?" gets answered — by asking the
        # endpoint, not the user. Write the answer back into the stored settings
        # so the assistant is told the truth about its own eyes.
        seen = (getattr(inst, "caps", {}) or {}).get("vision")
        if ok and seen is not None:
            from memory.config_manager import save_provider_config
            save_provider_config(pid, {"vision": "1" if seen else ""})
            entry = self._edits.get(pid, {}).get("vision")
            if entry is not None and isinstance(entry[0], QComboBox):
                entry[0].setCurrentIndex(1 if seen else 0)

    def _list(self, pid: str) -> None:
        values = self._values(pid)          # before processEvents — see _test
        self._say(pid, "reading…", C.TEXT_DIM)
        QApplication.processEvents()
        try:
            inst = self._registry.build(pid, values)
            if hasattr(inst, "models"):
                items, key = [(m, m) for m in inst.models()], "model"
            elif hasattr(inst, "voices"):
                items, key = list(inst.voices()), "voice_id"
            else:
                self._say(pid, "Nothing to list for this one.", C.TEXT_DIM)
                return
        except Exception as e:
            self._say(pid, f"✕  {type(e).__name__}: {str(e)[:150]}", C.RED)
            return

        entry = self._edits.get(pid, {}).get(key)
        if entry is None or not items:
            self._say(pid, f"✓  {len(items)} found." if items else "None found.",
                      C.GREEN if items else C.TEXT_DIM)
            return
        box = entry[0]
        if isinstance(box, QComboBox):
            keep = box.currentText()
            box.clear()
            for value, label in items:
                box.addItem(str(label), str(value))
            j = box.findData(keep)
            box.setCurrentIndex(j if j >= 0 else 0)
        else:
            self._say(pid, f"✓  {len(items)} available: "
                           f"{', '.join(str(v) for v, _ in items[:8])}", C.GREEN)
            return
        self._say(pid, f"✓  {len(items)} available — pick one above.", C.GREEN)

    def _install(self, pid: str) -> None:
        """Fetch a provider's optional dependency, off the Qt thread — pip takes
        tens of seconds and a frozen window looks like a crashed one."""
        import subprocess
        import sys as _sys
        import threading

        decl = self._registry.get_declaration(pid) or {}
        pkg = decl.get("install")
        if not pkg:
            return
        self._say(pid, f"installing {pkg} — this can take a minute…", C.ACC2)

        def work():
            try:
                r = subprocess.run(
                    [_sys.executable, "-m", "pip", "install", pkg],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
                good = r.returncode == 0
                tail = r.stdout.decode("utf-8", "replace").strip().splitlines()
                msg = ("✓  installed — close and reopen this panel"
                       if good else (tail[-1][:150] if tail else "pip failed"))
            except Exception as e:
                good, msg = False, f"{type(e).__name__}: {str(e)[:120]}"
            QTimer.singleShot(0, lambda: self._say(pid, msg,
                                                   C.GREEN if good else C.RED))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self) -> None:
        from memory.config_manager import (get_pipeline, get_provider_mode,
                                           save_providers)

        before = (get_provider_mode(), dict(get_pipeline()))

        # ONE write, not five. See save_providers for what the five cost.
        creds = {pid: self._values(pid) for pid in list(self._edits)}
        for slot, eid in self._picked.items():
            pid = self._pipe.get(slot, "")
            if pid and eid:
                creds.setdefault(pid, {})["catalog"] = eid
        sidecar_pid, sidecar_eid = self._sidecar_choice()
        if sidecar_pid and sidecar_eid:
            creds.setdefault(sidecar_pid, {}).setdefault("catalog", sidecar_eid)

        save_providers(
            mode=self._mode,
            pipeline={"stt": self._pipe.get("stt", ""),
                      "llm": self._pipe.get("llm", ""),
                      "tts": self._pipe.get("tts", "")},
            creds=creds,
            sidecar=sidecar_pid,
            sidecar_first=self._first_combo.currentData() == "before",
        )

        # Providers are cached by configuration; a changed setting must not go
        # on being served by an object built from the old one.
        try:
            self._registry.reset()
        except Exception:
            pass

        after = (get_provider_mode(), dict(get_pipeline()))
        self.hide()
        # Background-request settings take effect on the next call with no
        # reconnect. Only the conversation engine needs the session rebuilt.
        if before != after:
            self.changed.emit()


class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — offers quick Jarvis actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(0, 8, 14, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setFont(QFont("Courier New", 8))
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(QFont("Courier New", 8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class PluginSettingsOverlay(QWidget):
    """Floating overlay — renders per-plugin settings forms.

    Fully generic: it iterates the settings schemas a plugin declared via its
    PLUGIN_SETTINGS constant (delivered by PluginRegistry.settings_schemas) and
    builds a form for each. It knows NOTHING about any specific plugin, so the
    core stays clean and plugins remain pure drop-in — install a plugin that
    declares fields (e.g. the 3D-printer suite) and its section appears here;
    install none and this panel simply says there's nothing to configure.
    """

    _test_done = pyqtSignal(str, bool, str)   # namespace, ok, message
    _OW = 460

    def __init__(self, sections: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginSettingsOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self._sections = sections or []
        self._widgets: dict[tuple, object] = {}    # (namespace, key) -> input widget
        self._types:   dict[tuple, str]    = {}     # (namespace, key) -> field type
        self._status_labels: dict[str, QLabel] = {} # namespace -> status QLabel
        self._test_done.connect(self._on_test_done)

        self._fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
                    f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
                    f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(8)

        root.addWidget(self._lbl("⚙  PLUGIN SETTINGS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        root.addWidget(sep)

        if not self._sections:
            root.addWidget(self._lbl(
                "No configurable plugins are installed.\nDrop a plugin that needs "
                "settings (like the 3D-printer suite) into the plugins folder and "
                "it will show up here.", 9, color=C.TEXT_DIM))
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; }")
            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            form = QVBoxLayout(inner)
            form.setContentsMargins(0, 0, 6, 0)
            form.setSpacing(6)
            for sec in self._sections:
                self._build_section(form, sec)
            form.addStretch(1)
            scroll.setWidget(inner)
            root.addWidget(scroll, 1)

        # ── bottom buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        if self._sections:
            save_btn = QPushButton("▸  SAVE")
            save_btn.setFixedHeight(34)
            save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.PRI};
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
            """)
            save_btn.clicked.connect(self._save_all)
            btn_row.addWidget(save_btn)

        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(34)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _lbl(self, txt, fs=9, bold=False, color=C.PRI,
             align=Qt.AlignmentFlag.AlignLeft):
        w = QLabel(txt); w.setAlignment(align); w.setWordWrap(True)
        w.setFont(QFont("Courier New", fs,
                        QFont.Weight.Bold if bold else QFont.Weight.Normal))
        w.setStyleSheet(f"color: {color}; background: transparent;")
        return w

    def _build_section(self, form: QVBoxLayout, sec: dict):
        ns     = sec.get("namespace") or sec.get("plugin") or "plugin"
        title  = sec.get("title") or ns
        fields = sec.get("fields") or []
        values = sec.get("values") or {}

        form.addSpacing(4)
        form.addWidget(self._lbl(title, 10, True, C.PRI))

        for field in fields:
            if not isinstance(field, dict) or not field.get("key"):
                continue
            key   = field["key"]
            ftype = (field.get("type") or "text").lower()
            label = field.get("label") or key
            default = field.get("default")
            stored  = values.get(key, default)

            form.addWidget(self._lbl(label.upper(), 8, color=C.TEXT_DIM))

            if ftype == "choice":
                w = QComboBox()
                w.addItems([str(o) for o in field.get("options", [])])
                w.setFont(QFont("Courier New", 9))
                w.setFixedHeight(30)
                w.setStyleSheet(
                    f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
                    f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 8px; }}"
                    f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
                    f"selection-background-color: {C.PRI_GHO}; }}")
                if stored is not None:
                    w.setCurrentText(str(stored))
            elif ftype == "toggle":
                w = QPushButton()
                w.setCheckable(True)
                w.setChecked(bool(stored))
                w.setFixedHeight(28)
                w.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                w.setCursor(Qt.CursorShape.PointingHandCursor)
                self._style_toggle(w)
                w.toggled.connect(lambda _=False, b=w: self._style_toggle(b))
            else:  # text / password
                w = QLineEdit("" if stored is None else str(stored))
                w.setFont(QFont("Courier New", 10))
                w.setFixedHeight(30)
                w.setStyleSheet(self._fs)
                if field.get("placeholder"):
                    w.setPlaceholderText(str(field["placeholder"]))
                if ftype == "password":
                    w.setEchoMode(QLineEdit.EchoMode.Password)

            self._widgets[(ns, key)] = w
            self._types[(ns, key)]   = ftype
            form.addWidget(w)

        # optional test/connect action button + status line
        action = sec.get("action")
        if isinstance(action, dict) and callable(action.get("run")):
            form.addSpacing(2)
            ab = QPushButton(str(action.get("label") or "TEST"))
            ab.setFixedHeight(30)
            ab.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            ab.setCursor(Qt.CursorShape.PointingHandCursor)
            ab.setStyleSheet(f"""
                QPushButton {{ background: #00091a; color: {C.PRI};
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
            """)
            ab.clicked.connect(lambda _=False, n=ns: self._run_action(n))
            form.addWidget(ab)

        status = self._lbl("", 8, color=C.TEXT_DIM)
        self._status_labels[ns] = status
        form.addWidget(status)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER}; margin: 4px 0;")
        form.addWidget(line)

    def _style_toggle(self, btn: QPushButton):
        on = btn.isChecked()
        btn.setText("ON" if on else "OFF")
        if on:
            btn.setStyleSheet(f"QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI}; "
                              f"border: 1px solid {C.PRI}; border-radius: 3px; }}")
        else:
            btn.setStyleSheet(f"QPushButton {{ background: transparent; color: {C.TEXT_MED}; "
                              f"border: 1px solid {C.BORDER}; border-radius: 3px; }}")

    # ── data ──────────────────────────────────────────────────────────────────
    def _gather(self, ns: str) -> dict:
        out = {}
        for (n, key), w in self._widgets.items():
            if n != ns:
                continue
            t = self._types.get((n, key), "text")
            if t == "choice":
                out[key] = w.currentText()
            elif t == "toggle":
                out[key] = w.isChecked()
            else:
                out[key] = w.text().strip()
        return out

    def _save_ns(self, ns: str):
        from memory.config_manager import save_plugin_config
        save_plugin_config(ns, self._gather(ns))

    def _save_all(self):
        for sec in self._sections:
            ns = sec.get("namespace") or sec.get("plugin")
            if ns:
                self._save_ns(ns)
                lbl = self._status_labels.get(ns)
                if lbl:
                    lbl.setText("Saved ✓")
                    lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")

    def _run_action(self, ns: str):
        sec = next((s for s in self._sections
                    if (s.get("namespace") or s.get("plugin")) == ns), None)
        if not sec:
            return
        run_fn = (sec.get("action") or {}).get("run")
        if not callable(run_fn):
            return
        self._save_ns(ns)                 # persist what the user typed before testing
        values = self._gather(ns)
        lbl = self._status_labels.get(ns)
        if lbl:
            lbl.setText("Testing…")
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")

        def worker():
            try:
                res = run_fn(values)
                if isinstance(res, tuple) and len(res) == 2:
                    ok, msg = bool(res[0]), str(res[1])
                else:
                    ok, msg = bool(res), str(res)
            except Exception as e:
                ok, msg = False, str(e)
            self._test_done.emit(ns, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ns: str, ok: bool, msg: str):
        lbl = self._status_labels.get(ns)
        if not lbl:
            return
        lbl.setText(msg)
        color = C.PRI if ok else "#ff6b6b"
        lbl.setStyleSheet(f"color: {color}; background: transparent;")


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None,
                 bind_error: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        # THE ONE FAILURE THAT LOOKS LIKE THE SERVER BEING OFF.
        #
        # Windows writes a BLOCK rule for an executable when its "Allow access?"
        # prompt is dismissed, and a block overrides every allow rule there is —
        # including the port rule this app carefully creates. The phone then
        # reports "refused to connect" while the server is running perfectly.
        #
        # It is invisible from the HUD, which is where the person scanning the
        # QR code is looking, and it is per-EXECUTABLE: the shortcut runs
        # pythonw.exe while an editor runs python.exe, so it can block one launch
        # method and not the other on the same machine. That difference is
        # unguessable without being told, so it is said here.
        # Whatever is stopping this from working, say it HERE — beside the QR
        # code, where the person about to scan it is looking. A dashboard that
        # cannot be reached and does not explain why is the single most
        # frustrating failure this app has.
        if bind_error:
            lay.addWidget(_lbl("⚠  " + bind_error, 8, color="#f4b942"))

        try:
            from dashboard.server import blocking_firewall_rules
            _blocked = blocking_firewall_rules()
        except Exception:
            _blocked = []
        if _blocked:
            warn = _lbl(
                "⚠  Windows is blocking incoming connections to this copy of "
                "Python, so your phone cannot reach this page. Restart JARVIS "
                "and accept the Windows prompt, or remove the rules named "
                + ", ".join(sorted({n for n, _ in _blocked}))
                + " under Windows Defender Firewall → Inbound Rules.",
                8, color="#f4b942")
            lay.addWidget(warn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Courier New", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class MainWindow(QMainWindow):
    _log_sig        = pyqtSignal(str)
    _state_sig      = pyqtSignal(str)
    _content_sig    = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _reconfig_sig   = pyqtSignal()           # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)      # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)       # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)      # live camera frame → HUD area
    _video_open_sig  = pyqtSignal(str, str, bool, str)  # video, title, muted, audio
    _wake_btns_sig   = pyqtSignal()          # wake state resolved off-thread
    _video_close_sig = pyqtSignal()
    _video_mute_sig  = pyqtSignal(bool)
    _clipboard_sig  = pyqtSignal(str)        # clipboard text changed (thread-safe)
    _confirm_sig    = pyqtSignal(str, str)   # (title, detail) — irreversible-action gate
    _confirm_hide_sig = pyqtSignal()
    _wake_dl_sig    = pyqtSignal(bool, str)  # wake-word install finished (ok, message)
    _quiz_sig       = pyqtSignal(str, object, object)  # (topic, questions, grader)
    _quiz_hide_sig  = pyqtSignal()
    _review_sig     = pyqtSignal(str, str, object, object)  # document review payload
    _lyrics_open_sig   = pyqtSignal(str, str, object)  # (track_name, artist_name, youtube_info)
    _lyrics_loaded_sig = pyqtSignal(object, str)       # (LyricsTrack, raw_query)
    _lyrics_pos_sig    = pyqtSignal(float)             # position_sec
    _lyrics_close_sig  = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path

        # Load customization from config
        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "JARVIS").strip()
        _display = self._assistant_name.upper()

        # Apply the saved UI colour BEFORE panels/stylesheets are built
        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        title = f"{_display} — {APP_VERSION}" if APP_VERSION else _display
        self.setWindowTitle(title)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_voice_change   = None   # callable: () -> None — rebuild session with new voice
        self.on_audio_device_change = None  # callable: () -> None — reopen audio streams
        self._confirm_overlay  = None   # live ConfirmBanner, if one is on screen
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self.get_plugin_settings = None # callable: () -> list[dict] settings schemas, set by JarvisLive
        self.on_wake_toggle    = None   # callable: (enable: bool) -> str, set by JarvisLive
        self.on_wake_manual    = None   # callable: () -> None — manual sleep/wake
        self.on_push_to_talk   = None   # callable: (enable: bool) -> str scope
        self.ptt_hold          = None   # callable: (held: bool) -> None — windowed chord
        self.wake_get_state    = None   # callable: () -> dict {enabled, awake, ready}
        self.get_action_registry = None # callable: () -> ActionRegistry
        self.get_plugin_registry = None # callable: () -> PluginRegistry
        self.dispatch_action   = None   # callable: (name: str, params: dict) -> str
        self.dispatch_plugin   = None   # callable: (name: str, params: dict) -> str
        self._res_diag_overlay = None   # ResourceDiagnosticsOverlay
        self._command_registry = None   # CommandPaletteRegistry
        self._command_palette  = None   # CommandPaletteOverlay
        self._muted            = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        # Center column: HUD + resizable content panel via QSplitter
        self.hud = HudCanvas(face_path, _display)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_panel = self._build_content_panel()
        self._quiz_panel = self._build_quiz_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #000308;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # ── Video surface ────────────────────────────────────────────────
        # Built exactly like the camera page above and stacked beside it,
        # because it is the same idea: something takes the centre of the HUD
        # for a while and then gives it back. Sharing the stack rather than
        # inventing a second mechanism means the avatar, the camera and a video
        # can never be on screen at once.
        self._video_split = False        # is the sound a separate stream?
        self._video_auto_muted = False   # did JARVIS close the mic, or the user?
        # A plain flag rather than reading the widget. video_is_playing() is
        # called from plugin threads, and reading a widget's state from one is
        # not something to rely on; an attribute is.
        self._video_on = False
        self._video_cont = QWidget()
        self._video_cont.setStyleSheet(f"background: {C.BG};")
        _vid_v = QVBoxLayout(self._video_cont)
        _vid_v.setContentsMargins(8, 6, 8, 8)
        _vid_v.setSpacing(4)

        _vid_hdr = QHBoxLayout()
        self._video_title = QLabel("▶  VIDEO")
        self._video_title.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._video_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _vid_hdr.addWidget(self._video_title)
        _vid_hdr.addStretch()

        def _vid_btn(text: str) -> QPushButton:
            b = QPushButton(text)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    color: {C.TEXT_DIM}; background: transparent;
                    border: none; padding: 2px 6px;
                }}
                QPushButton:hover {{ color: {C.PRI}; }}
            """)
            return b

        # Muted is the default and the button says so, because a soundtrack
        # talking over JARVIS is the one way this feature could make the
        # assistant worse rather than better.
        self._video_mute_btn = _vid_btn("🔊  SOUND ON")
        self._video_mute_btn.clicked.connect(self._toggle_video_mute)
        _vid_hdr.addWidget(self._video_mute_btn)

        _vid_x = _vid_btn("✕  CLOSE")
        _vid_x.clicked.connect(self.stop_video)
        _vid_hdr.addWidget(_vid_x)
        _vid_v.addLayout(_vid_hdr)

        if HAVE_VIDEO:
            # A GRAPHICS ITEM, NOT A QVideoWidget.
            #
            # QVideoWidget gets a native window of its own, and a native window
            # is painted by the compositor above every ordinary widget that
            # shares the screen with it — so the settings drawer opened
            # *underneath* the video and raise_() could not help, because the
            # two are not in the same painting order at all. A video item drawn
            # into a QGraphicsView goes through Qt's own painter like any other
            # widget, and anything laid over it stays over it.
            self._video_scene = QGraphicsScene(self)
            self._video_item = QGraphicsVideoItem()
            self._video_scene.addItem(self._video_item)
            self._video_widget = QGraphicsView(self._video_scene)
            self._video_widget.setStyleSheet("background: #000; border: none;")
            self._video_widget.setFrameShape(QGraphicsView.Shape.NoFrame)
            self._video_widget.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._video_widget.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._video_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            _vid_v.addWidget(self._video_widget, stretch=1)

            self._video_audio = QAudioOutput()
            self._video_audio.setMuted(False)
            self._video_player = QMediaPlayer()
            self._video_player.setVideoOutput(self._video_item)
            # Keep the picture filling the view as the window is resized.
            self._video_item.nativeSizeChanged.connect(self._fit_video)
            self._video_player.setAudioOutput(self._video_audio)
            self._video_player.errorOccurred.connect(self._on_video_error)
            self._video_player.mediaStatusChanged.connect(self._on_video_media_status_changed)
            self._video_player.positionChanged.connect(self._on_video_position_changed)

            # A SECOND player, for sound that arrives separately.
            #
            # YouTube no longer serves a single stream carrying both picture and
            # sound — not for new uploads and not for old ones; checked against
            # three videos including the oldest on the site, and every one of
            # them offered zero combined formats. Picture and sound are two
            # URLs, so they are two players, started together and nudged back
            # into line by the timer below.
            #
            # A local file or a direct video URL still uses the first player
            # alone: one stream, one player, nothing to synchronise.
            self._video_sound = QMediaPlayer()
            self._video_sound_out = QAudioOutput()
            self._video_sound_out.setMuted(False)
            self._video_sound.setAudioOutput(self._video_sound_out)
            self._video_sound.mediaStatusChanged.connect(self._on_video_media_status_changed)

            self._video_sync = QTimer(self)
            self._video_sync.setInterval(1000)
            self._video_sync.timeout.connect(self._sync_video_sound)
        else:
            self._video_scene = None
            self._video_item = None
            self._video_widget = None
            self._video_player = None
            self._video_audio = None
            self._video_sound = None
            self._video_sound_out = None
            self._video_sync = None
            _miss = QLabel("Video playback is not available in this Qt install.")
            _miss.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _miss.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            _vid_v.addWidget(_miss, stretch=1)

        # Stack: 0 = animated HUD, 1 = live camera, 2 = video
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.addWidget(_cam_cont)
        self._hud_cam_stack.addWidget(self._video_cont)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER};
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._hud_cam_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.addWidget(self._quiz_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        # Quick-access drawer (floating overlay, built after central widget layout is done)
        self._quick_drawer = self._build_quick_drawer()
        self._ctrl_drawer = self._build_controls_drawer()
        self._warm_wake_state()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())
        from memory.config_manager import get_layout_mode as _glm
        self._layout_mode = _glm()
        self.set_layout_mode(self._layout_mode, persist=False)
        from memory.config_manager import get_resource_profile as _grp
        self._resource_profile = _grp()
        self.set_resource_profile(self._resource_profile, persist=False)

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metric update timer
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._confirm_sig.connect(self._show_confirm_banner)
        self._confirm_hide_sig.connect(self._hide_confirm_banner)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._wake_btns_sig.connect(self._refresh_wake_btns)
        self._video_open_sig.connect(self._on_video_open)
        self._video_close_sig.connect(self._on_video_close)
        self._video_mute_sig.connect(self._on_video_mute)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._wake_dl_sig.connect(self._on_wake_install_done)
        self._quiz_sig.connect(self._show_quiz)
        self._quiz_hide_sig.connect(self._hide_quiz)
        self._review_sig.connect(self._show_review)
        self._saved_search_title = ""
        self._saved_search_text = ""
        self._saved_search_visible = False
        self._lyrics_open_sig.connect(self._on_lyrics_open)
        self._lyrics_loaded_sig.connect(self._on_lyrics_loaded)
        self._lyrics_pos_sig.connect(self._on_lyrics_pos)
        self._lyrics_close_sig.connect(self.restore_search_content)
        self._cam_stop = threading.Event()

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # Clipboard panel (child of central widget, bottom-center)
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)
        sc_palette = QShortcut(QKeySequence("Ctrl+K"), self)
        sc_palette.activated.connect(self._toggle_command_palette)
        sc_diag = QShortcut(QKeySequence("Ctrl+D"), self)
        sc_diag.activated.connect(self._open_resource_diagnostics)

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        if start:
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._hud_cam_stack.setCurrentIndex(0)
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # --- Video in the HUD area ---------------------------------------------
    #
    # Everything below runs on the Qt thread. Plugins and the assistant reach it
    # through the signals above, the same way every other panel is driven, so a
    # background thread never touches a widget.
    def _on_video_open(self, source: str, title: str, muted: bool,
                       audio_source: str = "") -> None:
        if not HAVE_VIDEO or not self._video_player:
            self.write_log("SYS: Video playback is not available in this Qt "
                           "install.")
            return
        # A video and the live camera cannot share the centre of the HUD.
        self._cam_stop.set()

        self._video_title.setText(f"▶  {(title or 'VIDEO')[:44].upper()}")
        self._video_split = bool(audio_source)
        self._set_video_muted(bool(muted))

        url = (QUrl.fromLocalFile(source) if Path(source).exists()
               else QUrl(source))
        self._video_player.setSource(url)
        if self._video_split:
            self._video_sound.setSource(QUrl(audio_source))
        self._hud_cam_stack.setCurrentIndex(2)
        self._video_on = True
        # Re-run now that the video counts as playing: _set_video_muted ran
        # before this line and saw no video, so its mic check was a no-op.
        self._sync_mic_for_video()
        current_rate = getattr(getattr(self, "_lyrics_panel", None), "_playback_speed", 1.0)
        if current_rate != 1.0:
            for p in (self._video_player, self._video_sound):
                if p:
                    try:
                        p.setPlaybackRate(float(current_rate))
                    except Exception:
                        pass
        self._video_player.play()
        if self._video_split:
            self._video_sound.play()
            self._video_sync.start()

    def _fit_video(self, *_a) -> None:
        """Size the picture to the panel, keeping its shape."""
        if not (self._video_item and self._video_widget):
            return
        try:
            native = self._video_item.nativeSize()
            if native.isEmpty():
                return
            view = self._video_widget.viewport().size()
            scale = min(view.width() / native.width(),
                        view.height() / native.height())
            w, h = native.width() * scale, native.height() * scale
            self._video_item.setSize(QSizeF(w, h))
            self._video_scene.setSceneRect(0, 0, w, h)
            self._video_widget.centerOn(self._video_item)
        except Exception:
            pass

    def _on_video_close(self) -> None:
        if self._video_sync:
            self._video_sync.stop()
        for p in (self._video_player, self._video_sound):
            if p:
                p.stop()
                p.setSource(QUrl())
        self._video_split = False
        self._video_on = False
        self._hud_cam_stack.setCurrentIndex(0)
        if self._video_auto_muted:
            self._video_auto_muted = False
            self._set_muted(False, "Media finished — microphone restored.")
        else:
            self._sync_mic_for_video()      # gives the microphone back
        self.restore_search_content()
        self.set_state("LISTENING")

    def _set_video_muted(self, muted: bool) -> None:
        """Silence whichever output is carrying the sound for this video."""
        muted = bool(muted)
        if self._video_audio:
            # When the sound is a separate stream this player has none, but
            # muting it too costs nothing and keeps the two paths identical.
            self._video_audio.setMuted(muted)
        if self._video_sound_out:
            self._video_sound_out.setMuted(muted)
        self._sync_video_mute_btn()
        self._sync_mic_for_video()

    def _on_video_mute(self, muted: bool) -> None:
        self._set_video_muted(muted)

    def _sync_mic_for_video(self) -> None:
        """Close the microphone while the video is making sound.

        JARVIS subtracts its OWN output from the microphone — that is what
        core/echo.py does — but a video plays through a different output
        entirely, so the guard has never heard of it and the assistant answers
        the film. There is no arrangement in which an open microphone and a
        loudspeaker in the same room do not do that.

        So the microphone closes for exactly as long as the sound is on, and
        opens again by itself the moment it goes off or the video is closed.
        Only if JARVIS closed it: a microphone the user muted themselves stays
        muted, and pressing the mute key during a video hands the decision back
        to them for good.
        """
        aud = self._video_sound_out if self._video_split else self._video_audio
        sound_on = bool(self._video_on and aud and not aud.isMuted())
        if sound_on and not self._muted:
            self._video_auto_muted = True
            self._set_muted(True, "The video's sound is on — silence it, close "
                                  "it, or press F4 to talk. Typing still works.")
        elif not sound_on and self._video_auto_muted:
            self._video_auto_muted = False
            self._set_muted(False, "The video is quiet again.")

    def _sync_video_sound(self) -> None:
        """Keep the separate soundtrack in step with the picture.

        Two players started at the same moment do not stay together: they buffer
        independently, and measured on a real stream they were about half a
        second apart after nine seconds. So the sound is nudged back to the
        picture whenever it drifts far enough to hear — and only then, because
        correcting a smaller gap is itself audible.
        """
        if not (self._video_split and self._video_sound and self._video_player):
            return
        try:
            if self._video_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                return
            if self._video_sound.mediaStatus() in (
                QMediaPlayer.MediaStatus.BufferingMedia,
                QMediaPlayer.MediaStatus.LoadingMedia,
            ):
                return
            drift = self._video_sound.position() - self._video_player.position()
            if abs(drift) > 1500:
                self._video_sound.setPosition(self._video_player.position())
        except Exception:
            pass

    def _sync_video_mute_btn(self) -> None:
        out = self._video_sound_out if self._video_split else self._video_audio
        muted = bool(out and out.isMuted())
        self._video_mute_btn.setText("🔇  SOUND OFF" if muted else "🔊  SOUND ON")

    def _toggle_video_mute(self) -> None:
        out = self._video_sound_out if self._video_split else self._video_audio
        if out:
            self._set_video_muted(not out.isMuted())

    def _on_video_media_status_changed(self, status) -> None:
        try:
            if HAVE_VIDEO and QMediaPlayer is not None and status == QMediaPlayer.MediaStatus.EndOfMedia:
                self.write_log("SYS: Media playback ended. Restoring JARVIS HUD interface...")
                self._on_video_close()
                self.set_state("LISTENING")
                if callable(getattr(self, "on_media_finished", None)):
                    self.on_media_finished()
        except Exception:
            pass

    def _on_video_error(self, *_a) -> None:
        err = ""
        try:
            err = self._video_player.errorString()
        except Exception:
            pass
        self.write_log(f"SYS: The video could not be played{(' — ' + err) if err else ''}.")
        self._on_video_close()

    def stop_video(self) -> None:
        self._video_close_sig.emit()

    def video_is_playing(self) -> bool:
        return bool(self._video_on)

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    @staticmethod
    def _get_desktop_dir() -> Path:
        """
        Resolve the user's REAL desktop directory instead of assuming
        ~/Desktop, which breaks when:
          • OneDrive "Known Folder Move" relocates the desktop
            (C:/Users/x/OneDrive/Desktop) — very common on Win 10/11;
          • the XDG desktop is localized on Linux (~/Masaüstü,
            ~/Schreibtisch, ~/Bureau, …).
        Falls back to ~/Desktop only as a last resort.
        """
        home = Path.home()
        _os = platform.system()

        if _os == "Windows":
            # ── 1) SHGetKnownFolderPath(FOLDERID_Desktop) — the canonical
            #       answer; follows OneDrive redirection. No dependencies. ──
            try:
                import ctypes
                from ctypes import wintypes

                class _GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD),
                                ("Data2", wintypes.WORD),
                                ("Data3", wintypes.WORD),
                                ("Data4", ctypes.c_ubyte * 8)]

                # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
                fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                                 0x9A, 0x87, 0xC6, 0x41))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(
                        ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    if p.is_dir():
                        return p
            except Exception:
                pass

            # ── 2) Registry: User Shell Folders (may contain %VARS%) ──────
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders") as key:
                    val, _t = winreg.QueryValueEx(key, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
            except Exception:
                pass

        elif _os == "Linux":
            # ── xdg-user-dir honours localized names (~/Masaüstü, …) ──────
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
                p = Path(out.stdout.strip())
                if out.stdout.strip() and p != home and p.is_dir():
                    return p
            except Exception:
                pass
            try:
                cfg = home / ".config" / "user-dirs.dirs"
                for line in cfg.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR"):
                        val = line.split("=", 1)[1].strip().strip('"')
                        p = Path(val.replace("$HOME", str(home)))
                        if p != home and p.is_dir():
                            return p
            except Exception:
                pass

        # macOS: ~/Desktop is always the real path (localization is
        # display-only). Everything else lands here as a last resort.
        return home / "Desktop"

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = self._get_desktop_dir()

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "J.A.R.V.I.S.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "J.A.R.V.I.S.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            oh = min(oh, cw.height() - 16)
            ow = min(ow, cw.width() - 20)
            self._customize_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )
        # Clipboard panel — bottom-center
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        # Quick drawer — reposition if open
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()
        if hasattr(self, '_ctrl_drawer') and self._ctrl_drawer.isVisible():
            self._position_ctrl_drawer()
        self._fit_video()

    def _update_metrics(self):
        prof = getattr(self, "_resource_profile", "balanced")
        snap = _metrics.snapshot()

        if prof == "low_ram":
            # In Low RAM mode: update minimal eco capsule and skip heavy process table sweeps
            proc_ram = snap.get("proc_ram", 0.0)
            cpu = snap.get("cpu", 0.0)
            st = snap.get("state", "IDLE")
            if hasattr(self, "_eco_status_lbl"):
                self._eco_status_lbl.setText(f"APP: {proc_ram:.0f} MB")
            if hasattr(self, "_eco_sub_lbl"):
                self._eco_sub_lbl.setText(f"CPU: {cpu:.0f}% • {st}")
            if hasattr(self, "_prof_btn"):
                self._prof_btn.setText(PROFILE_DISPLAY_NAMES.get(prof, "LOW RAM"))
            return

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # System MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # Process RAM (RSS)
        proc_ram = snap.get("proc_ram", 0.0)
        pct_ram = min(100.0, (proc_ram / 1024.0) * 100.0)
        if hasattr(self, "_bar_proc_ram"):
            self._bar_proc_ram.set_value(pct_ram, f"{proc_ram:.0f}M")

        # Sparkline
        if hasattr(self, "_sparkline"):
            self._sparkline.update()

        # Profile button
        if hasattr(self, "_prof_btn"):
            cur_p = ResourceGuardian.get_instance().get_profile()
            self._prof_btn.setText(PROFILE_DISPLAY_NAMES.get(cur_p, cur_p.upper()))

        # Status badge
        if hasattr(self, "_status_badge"):
            st = snap.get("state", "IDLE")
            self._status_badge.setText(f"STATUS: {st}")
            st_col = C.GREEN if st == "IDLE" else (C.ACC if "VOICE" in st else C.PRI)
            self._status_badge.setStyleSheet(f"color: {st_col}; background: transparent; border: none;")

        # Diagnostics overlay live refresh if open
        if hasattr(self, "_res_diag_overlay") and self._res_diag_overlay and self._res_diag_overlay.isVisible():
            self._res_diag_overlay.refresh()

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU (only updated if physically available on this system)
        if hasattr(self, "_bar_gpu") and getattr(_metrics, "_has_gpu", True):
            gpu = snap["gpu"]
            if gpu >= 0:
                self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
            else:
                self._bar_gpu.set_value(0, "N/A")

        # TMP (only updated if physically available on this system)
        if hasattr(self, "_bar_tmp") and getattr(_metrics, "_has_temp", True):
            tmp = snap["tmp"]
            if tmp >= 0:
                tmp_pct = min(100, (tmp / 100) * 100)
                self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
            else:
                self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        if APP_VERSION:
            lay.addWidget(_badge(APP_VERSION, C.PRI_DIM))
            lay.addSpacing(8)
        self._drawer_btn = QPushButton("⚙")
        self._drawer_btn.setFixedSize(26, 26)
        self._drawer_btn.setFont(QFont("Courier New", 11))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setToolTip("Settings & Controls")
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
            QPushButton:checked {{ color: {C.PRI}; border-color: {C.PRI}; background: {C.PRI_GHO}; }}
        """)
        self._drawer_btn.setCheckable(True)
        self._drawer_btn.setToolTip("Setup — things you set once")
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)

        # A SECOND drawer, and the split is by how often a thing is touched.
        #
        # One panel held twelve buttons: the ones you press once when you set
        # the assistant up sitting next to the ones you flick on and off every
        # day. Separating them by that — setup behind ⚙, everyday behind 🎛 —
        # is what makes each list short enough to read at a glance.
        self._ctrl_btn = QPushButton("🎛")
        self._ctrl_btn.setFixedSize(26, 26)
        self._ctrl_btn.setFont(QFont("Courier New", 11))
        self._ctrl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ctrl_btn.setToolTip("Controls — the everyday switches")
        self._ctrl_btn.setStyleSheet(self._drawer_btn.styleSheet())
        self._ctrl_btn.setCheckable(True)
        self._ctrl_btn.clicked.connect(self._toggle_controls)
        lay.addSpacing(4)
        lay.addWidget(self._ctrl_btn)
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(_disp)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(QFont("Courier New", 17, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        mid.addWidget(self._title_lbl)
        from memory.config_manager import get_voice
        _v_name = (get_voice() or "Mayra").strip().title()
        if _disp in ("JARVIS", "J.A.R.V.I.S"):
            _sub_text = f"A Friendly Assistant • Voice: {_v_name}" if _v_name else "A Friendly Assistant"
        else:
            _sub_text = f"Personal AI Assistant • Voice: {_v_name}" if _v_name else "Personal AI Assistant"
        self._sub_lbl = QLabel(_sub_text)
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setFont(QFont("Courier New", 7))
        self._sub_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(self._sub_lbl)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(5)

        hdr = QLabel("◈ RESOURCE GUARDIAN")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        self._prof_btn = QPushButton("BALANCED")
        self._prof_btn.setFixedHeight(20)
        self._prof_btn.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        self._prof_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prof_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.BRASS_BRIGHT};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                padding: 0 4px;
            }}
            QPushButton:hover {{
                border-color: {C.BRASS_BRIGHT}; color: #ffffff;
            }}
        """)
        self._prof_btn.clicked.connect(self._open_resource_diagnostics)
        lay.addWidget(self._prof_btn)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("SYS RAM", C.ACC2)
        self._bar_mem.setToolTip("Total Windows Physical RAM used across the entire PC (all apps + OS)")
        self._bar_proc_ram = MetricBar("APP RAM", C.PRI)
        self._bar_proc_ram.setToolTip("JARVIS Process Working Set RAM (memory actually consumed by this assistant)")
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", "#ff6688")

        # Minimal Eco Status Panel (used in Low RAM mode)
        self._eco_panel = QWidget()
        self._eco_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 6px;"
        )
        eco_lay = QVBoxLayout(self._eco_panel)
        eco_lay.setContentsMargins(8, 10, 8, 10)
        eco_lay.setSpacing(6)

        self._eco_badge = QLabel("⚡ ECO ACTIVE")
        self._eco_badge.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._eco_badge.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        eco_lay.addWidget(self._eco_badge)

        self._eco_status_lbl = QLabel("APP: -- MB")
        self._eco_status_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._eco_status_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent; border: none;")
        eco_lay.addWidget(self._eco_status_lbl)

        self._eco_sub_lbl = QLabel("CPU: --% • IDLE")
        self._eco_sub_lbl.setFont(QFont("Courier New", 7))
        self._eco_sub_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        eco_lay.addWidget(self._eco_sub_lbl)

        self._eco_panel.hide()
        lay.addWidget(self._eco_panel)

        for bar in [self._bar_cpu, self._bar_mem, self._bar_proc_ram, self._bar_net,
                    self._bar_gpu, self._bar_tmp]:
            lay.addWidget(bar)

        # Permanently hide unavailable hardware bars (persists across all modes and future runs)
        if not getattr(_metrics, "_has_gpu", True):
            self._bar_gpu.hide()
        if not getattr(_metrics, "_has_temp", True):
            self._bar_tmp.hide()

        self._sparkline = ResourceSparkline(on_click=self._open_resource_diagnostics)
        lay.addWidget(self._sparkline)
        lay.addSpacing(2)

        self._info_panel = QWidget()
        self._info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;"
        )
        ip_lay = QVBoxLayout(self._info_panel)
        ip_lay.setContentsMargins(6, 4, 6, 4)
        ip_lay.setSpacing(2)

        self._status_badge = QLabel("STATUS: IDLE")
        self._status_badge.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._status_badge.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._status_badge)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(self._info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        self._protocol_panel = QWidget()
        self._protocol_panel.setStyleSheet("background: transparent;")
        pp_lay = QVBoxLayout(self._protocol_panel)
        pp_lay.setContentsMargins(0, 0, 0, 0)
        pp_lay.setSpacing(4)

        for txt, col in [
            ("AI CORE\nACTIVE",  C.GREEN),
            ("SEC\nCLEARED",     C.PRI),
            ("PROTOCOL\n" + APP_PROTOCOL,   C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 3px; padding: 4px;"
            )
            pp_lay.addWidget(lbl)

        lay.addWidget(self._protocol_panel)
        return w
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"▸ {txt}")
            l.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            return l

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._interrupt_btn = QPushButton("✋  INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(34)
        self._interrupt_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(36, 12, 18, 0.85), stop:1 rgba(20, 6, 10, 0.95));
                color: #ff6688;
                border: 1px solid rgba(255, 77, 109, 0.55);
                border-radius: 6px;
                padding: 4px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(50, 16, 26, 0.95), stop:1 rgba(30, 10, 16, 0.95));
                border: 1px solid #ff4d6d;
                color: #ff99aa;
            }}
            QPushButton:pressed {{
                background: rgba(15, 4, 8, 0.95);
                border: 1px solid #ff3355;
                padding-top: 6px; padding-left: 5px;
            }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        lay.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        return w

    def _build_quick_drawer(self) -> QWidget:
        """Floating overlay panel shown when the ⚙ header button is toggled."""
        _BTN_STYLE_PRI = f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(212, 175, 55, 0.18), stop:1 rgba(0, 229, 255, 0.14));
                color: #f0c544;
                border: 1px solid rgba(212, 175, 55, 0.45);
                border-radius: 5px;
                text-align: left; padding: 0 10px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(212, 175, 55, 0.32), stop:1 rgba(0, 229, 255, 0.25));
                border-color: #f0c544; color: #ffffff;
            }}
        """
        _BTN_STYLE_DIM = f"""
            QPushButton {{
                background: rgba(4, 18, 30, 0.70);
                color: #6ab8cc;
                border: 1px solid rgba(212, 175, 55, 0.22);
                border-radius: 5px;
                text-align: left; padding: 0 10px;
            }}
            QPushButton:hover {{
                background: rgba(212, 175, 55, 0.15);
                color: #f0c544;
                border-color: rgba(212, 175, 55, 0.50);
            }}
        """

        self._BTN_PRI, self._BTN_DIM = _BTN_STYLE_PRI, _BTN_STYLE_DIM
        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(f"""
            QWidget#QuickDrawer {{
                background: rgba(3, 14, 26, 0.95);
                border: 1.5px solid rgba(212, 175, 55, 0.45);
                border-top: none;
                border-radius: 0 0 10px 10px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("◈ SETUP")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        cp_btn = QPushButton("⌘  COMMAND PALETTE  [Ctrl+K]")
        cp_btn.setFixedHeight(28)
        cp_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        cp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cp_btn.setStyleSheet(_BTN_STYLE_PRI)
        cp_btn.clicked.connect(self._toggle_command_palette)
        lay.addWidget(cp_btn)

        res_btn = QPushButton("◈  RESOURCE GUARDIAN  [Ctrl+D]")
        res_btn.setFixedHeight(26)
        res_btn.setFont(QFont("Courier New", 7))
        res_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        res_btn.setStyleSheet(_BTN_STYLE_DIM)
        res_btn.clicked.connect(self._open_resource_diagnostics)
        lay.addWidget(res_btn)

        remote_btn = QPushButton("◉  REMOTE CONTROL")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(_BTN_STYLE_PRI)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Courier New", 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(_BTN_STYLE_DIM)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        self._autostart_btn = QPushButton("◉  AUTO-START: OFF")
        self._autostart_btn.setFixedHeight(26)
        self._autostart_btn.setFont(QFont("Courier New", 7))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        cust_btn = QPushButton("⚙  CUSTOMISE ASSISTANT")
        cust_btn.setFixedHeight(26)
        cust_btn.setFont(QFont("Courier New", 7))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(_BTN_STYLE_DIM)
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        audio_btn = QPushButton("🎧  AUDIO DEVICES")
        audio_btn.setFixedHeight(26)
        audio_btn.setFont(QFont("Courier New", 7))
        audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        audio_btn.setStyleSheet(_BTN_STYLE_DIM)
        audio_btn.clicked.connect(self._open_audio_devices)
        lay.addWidget(audio_btn)

        mem_btn = QPushButton("🧠  MEMORY")
        mem_btn.setFixedHeight(26)
        mem_btn.setFont(QFont("Courier New", 7))
        mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mem_btn.setStyleSheet(_BTN_STYLE_DIM)
        mem_btn.clicked.connect(self._open_memory_panel)
        lay.addWidget(mem_btn)

        plugin_btn = QPushButton("🧩  PLUGINS")
        plugin_btn.setFixedHeight(26)
        plugin_btn.setFont(QFont("Courier New", 7))
        plugin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plugin_btn.setStyleSheet(_BTN_STYLE_DIM)
        plugin_btn.clicked.connect(self._open_plugin_manager)
        lay.addWidget(plugin_btn)

        settings_btn = QPushButton("⚙  PLUGIN SETTINGS")
        settings_btn.setFixedHeight(26)
        settings_btn.setFont(QFont("Courier New", 7))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setStyleSheet(_BTN_STYLE_DIM)
        settings_btn.clicked.connect(self._open_plugin_settings)
        lay.addWidget(settings_btn)

        # The button is built here with the rest of the drawer; the panel behind
        # it — and the whole providers package — is imported on the click. The
        # drawer used to stutter for a measured 2.104 seconds because a state
        # check imported openwakeword while it was being built, and adding a
        # second thing that does that would undo the fix rather than repeat it.
        prov_btn = QPushButton("🔌  ENGINE & PROVIDERS")
        prov_btn.setFixedHeight(26)
        prov_btn.setFont(QFont("Courier New", 7))
        prov_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        prov_btn.setStyleSheet(_BTN_STYLE_DIM)
        prov_btn.clicked.connect(self._open_providers)
        lay.addWidget(prov_btn)

        w.adjustSize()
        return w

    def _build_controls_drawer(self) -> QWidget:
        """The switches that get flicked every day, in their own panel."""
        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(self._quick_drawer.styleSheet())
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("◈ CONTROLS")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        def _row(button, style=None, height=26):
            button.setFixedHeight(height)
            button.setFont(QFont("Courier New", 7))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if style:
                button.setStyleSheet(style)
            lay.addWidget(button)
            return button

        fs_btn = _row(QPushButton("⛶  FULLSCREEN  [F11]"), self._BTN_DIM)
        fs_btn.clicked.connect(self._toggle_fullscreen)

        self._brief_btn = _row(QPushButton())
        self._brief_btn.clicked.connect(self._toggle_brief)

        self._wake_btn = _row(QPushButton())
        self._wake_btn.clicked.connect(self._toggle_wake_word)
        self._wake_sleep_btn = _row(QPushButton())
        self._wake_sleep_btn.clicked.connect(self._tap_wake_manual)
        # Neutral until the real state lands from the background warm-up.
        self._wake_btn.setText("🎙  WAKE WORD")
        self._wake_btn.setStyleSheet(self._BTN_DIM)
        self._wake_sleep_btn.hide()

        self._ptt_btn = _row(QPushButton())
        self._ptt_btn.clicked.connect(self._toggle_ptt)
        self._refresh_talk_btns()

        self._hud_btn = _row(QPushButton())
        self._hud_btn.clicked.connect(self._toggle_hud_style)
        self._refresh_hud_btn()

        self._layout_btn = _row(QPushButton())
        self._layout_btn.clicked.connect(self._toggle_layout_mode)
        self._refresh_layout_btn()

        w.adjustSize()
        return w

    def _warm_wake_state(self) -> None:
        """Work out the wake-word state off the UI thread, once.

        It used to be resolved when the drawer opened, and that made opening the
        drawer take two seconds the first time — measured at 2.10s, all of it
        `import openwakeword` dragging in onnxruntime behind it. The button
        count had nothing to do with it; the Qt thread was simply waiting on an
        import. Afterwards the same check costs about a millisecond, so it only
        ever needed to happen somewhere other than in front of the user.
        """
        from memory.config_manager import get_wake_word_enabled
        if ResourceGuardian.get_instance().get_profile() == PROFILE_LOW_RAM and not get_wake_word_enabled():
            self._wake_btns_sig.emit()
            return

        def work():
            try:
                self._wake_state()
            except Exception:
                pass
            self._wake_btns_sig.emit()
        threading.Thread(target=work, daemon=True, name="wake-state-warm").start()

    def _toggle_drawer(self, checked: bool):
        if checked:
            self._close_controls()
            self._position_quick_drawer()
            self._quick_drawer.show()
            self._quick_drawer.raise_()
            self._animate_drawer_slide(self._quick_drawer)
        else:
            self._quick_drawer.hide()

    def _toggle_controls(self, checked: bool):
        if checked:
            self._close_setup()
            self._refresh_wake_btns()   # cheap now: the state was warmed at boot
            self._position_ctrl_drawer()
            self._ctrl_drawer.show()
            self._ctrl_drawer.raise_()
            self._animate_drawer_slide(self._ctrl_drawer)
        else:
            self._ctrl_drawer.hide()

    def _animate_drawer_slide(self, drawer):
        try:
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QRect
            anim = QPropertyAnimation(drawer, b"geometry", self)
            anim.setDuration(160)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            final_geom = drawer.geometry()
            start_geom = QRect(final_geom.x(), final_geom.y(), final_geom.width(), 0)
            anim.setStartValue(start_geom)
            anim.setEndValue(final_geom)
            anim.start()
            self._drawer_anim = anim
        except Exception:
            pass

    def _close_setup(self):
        if hasattr(self, "_quick_drawer"):
            self._quick_drawer.hide()
        if hasattr(self, "_drawer_btn"):
            self._drawer_btn.setChecked(False)

    def _close_controls(self):
        if hasattr(self, "_ctrl_drawer"):
            self._ctrl_drawer.hide()
        if hasattr(self, "_ctrl_btn"):
            self._ctrl_btn.setChecked(False)

    def _place_drawer(self, drawer, left: int):
        _W = 220
        drawer.setFixedWidth(_W)
        drawer.adjustSize()
        drawer.setGeometry(left, 54, _W, drawer.sizeHint().height())

    def _position_quick_drawer(self):
        if hasattr(self, "_quick_drawer"):
            self._place_drawer(self._quick_drawer, 12)

    def _position_ctrl_drawer(self):
        # Under its own header button rather than under the other one's.
        if hasattr(self, "_ctrl_drawer"):
            left = 12
            try:
                left = max(12, self._ctrl_btn.mapTo(self.centralWidget(),
                                                    QPoint(0, 0)).x() - 8)
            except Exception:
                pass
            self._place_drawer(self._ctrl_drawer, left)

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d14; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Collapsible panel below the HUD — shows search results, news, briefings.
        Hidden by default; appears when show_content() is called.
        """
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(5)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)

        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Courier New", 7))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 3px;
                padding: 6px 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)

        # ── Stacked container: Search View (Page 0) & Spotify Lyrics (Page 1) ──
        from PyQt6.QtWidgets import QStackedWidget
        self._content_stack = QStackedWidget(w)

        # Page 0: Search Results / Briefings View
        search_widget = QWidget()
        s_lay = QVBoxLayout(search_widget)
        s_lay.setContentsMargins(0, 0, 0, 0)
        s_lay.setSpacing(5)
        s_lay.addLayout(hdr)
        s_lay.addWidget(sep)
        s_lay.addWidget(self._content_display)
        self._content_stack.addWidget(search_widget)

        # Page 1: Spotify-inspired glassmorphism live lyrics view
        from ui_lyrics_panel import LyricsPanelWidget
        self._lyrics_panel = LyricsPanelWidget()
        self._lyrics_panel.dismiss_requested.connect(self.restore_search_content)
        self._lyrics_panel.seek_requested.connect(self._on_lyrics_seek)
        self._lyrics_panel.playback_speed_requested.connect(self._on_lyrics_playback_speed)
        self._content_stack.addWidget(self._lyrics_panel)

        lay.addWidget(self._content_stack)
        return w

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        import time as _time
        # The panel opens below the head, so the head looks down at it. It is a
        # tiny thing that answers "did that land?" before you read a word.
        self.hud.glance(0.0, -0.85, hold=1.3)
        self._saved_search_title = title
        self._saved_search_text = text
        self._saved_search_visible = True
        if hasattr(self, "_content_stack"):
            self._content_stack.setCurrentIndex(0)
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

    # ── document review ──────────────────────────────────────────────────────
    # Rendered as rich text into the content panel that already exists, rather
    # than into a panel of its own. A review is read, not clicked, so QTextEdit
    # gives scrolling, selection and copy for nothing, and the HUD gains no
    # widget it has to lay out. Severity decides colour and order here because
    # that is presentation; the plugin supplies no styling and knows no palette,
    # which is also what lets a re-theme repaint a review correctly.

    # Severity is marked by a symbol and a colour, not by a word. The findings
    # themselves are in the user's language, and "[SERIOUS]" sitting inside a
    # Turkish sentence is the kind of seam this project tries not to have —
    # while translating the tag would mean a table per language, which is worse.
    # A shape carries it in every language, and shape plus colour still reads
    # for someone who cannot separate red from amber. What the marks mean
    # arrives the way everything else does: JARVIS says it out loud.
    _REVIEW_MARKS = {"serious": ("RED", "▲"), "caution": ("ACC2", "●"), "note": ("PRI_DIM", "·")}

    @staticmethod
    def _esc(s) -> str:
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>"))

    def _on_lyrics_open(self, track_name: str, artist_name: str, youtube_info: object = None):
        if not hasattr(self, "_content_stack") or not hasattr(self, "_lyrics_panel"):
            return
        self._content_stack.setCurrentIndex(1)
        self._lyrics_panel.set_loading(track_name, artist_name)
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 240, 120), 240])
        self.hud.glance(0.0, -0.85, hold=1.3)

        import threading
        def _fetch():
            from core.lyrics_engine import LyricsEngine
            y_info = youtube_info if isinstance(youtube_info, dict) else None
            track = LyricsEngine.get_lyrics(track_name, artist_name, youtube_info=y_info)
            self._lyrics_loaded_sig.emit(track, track_name)

        threading.Thread(target=_fetch, daemon=True, name="lyrics-fetch").start()

    def _on_lyrics_loaded(self, track, raw_query: str):
        if hasattr(self, "_lyrics_panel"):
            self._lyrics_panel.load_track(track, raw_query)

    def _on_lyrics_pos(self, pos_sec: float):
        if hasattr(self, "_lyrics_panel") and self._content_stack.currentIndex() == 1:
            self._lyrics_panel.update_position(pos_sec)

    def _on_video_position_changed(self, pos_ms: int):
        pos_sec = pos_ms / 1000.0
        last = getattr(self, "_last_lyrics_pos_emitted", -1.0)
        if abs(pos_sec - last) >= 0.08:
            self._last_lyrics_pos_emitted = pos_sec
            self._lyrics_pos_sig.emit(pos_sec)

    def _on_lyrics_seek(self, time_sec: float):
        if hasattr(self, "_video_player") and self._video_player:
            self._video_player.setPosition(int(time_sec * 1000))

    def _on_lyrics_playback_speed(self, speed: float):
        rate = float(speed)
        for p in (getattr(self, "_video_player", None), getattr(self, "_video_sound", None)):
            if p:
                try:
                    p.setPlaybackRate(rate)
                except Exception:
                    pass

    def restore_search_content(self):
        """Restore previous search results when music finishes or lyrics are dismissed."""
        if getattr(self, "_saved_search_text", "") and getattr(self, "_saved_search_visible", False):
            if hasattr(self, "_content_stack"):
                self._content_stack.setCurrentIndex(0)
            self._show_content(self._saved_search_title, self._saved_search_text)
        else:
            if hasattr(self, "_content_panel"):
                self._content_panel.hide()

    def _show_review(self, title: str, summary: str, findings, unclear):
        """Slot — Qt main thread. Lays a document review into the content panel."""
        e = self._esc
        parts = [f'<div style="color:{C.TEXT}; font-family:Courier New;">']

        if summary:
            parts.append(
                f'<div style="color:{C.WHITE}; border-left:2px solid {C.PRI};'
                f' padding-left:8px; margin-bottom:10px;">{e(summary)}</div>')

        for f in (findings or []):
            key, mark = self._REVIEW_MARKS.get(f.get("severity"), ("PRI_DIM", "·"))
            colour = getattr(C, key)
            parts.append(f'<div style="margin-bottom:11px;">')
            parts.append(
                f'<span style="color:{colour}; font-weight:bold;">{mark}</span> '
                f'<span style="color:{C.WHITE}; font-weight:bold;">'
                f'{e(f.get("heading"))}</span>')
            if f.get("detail"):
                parts.append(f'<div style="margin-left:12px;">{e(f["detail"])}</div>')
            if f.get("quote"):
                # The document's own wording, visually separated from the
                # explanation so the two are never mistaken for each other.
                parts.append(
                    f'<div style="margin-left:12px; color:{C.TEXT_DIM};'
                    f' border-left:1px solid {C.BORDER}; padding-left:7px;">'
                    f'&ldquo;{e(f["quote"])}&rdquo;</div>')
            if f.get("suggestion"):
                parts.append(
                    f'<div style="margin-left:12px; color:{C.PRI};">'
                    f'&rarr; {e(f["suggestion"])}</div>')
            parts.append('</div>')

        if unclear:
            parts.append(
                f'<div style="margin-top:6px; border-top:1px solid {C.BORDER};'
                f' padding-top:7px; color:{C.TEXT_MED};">'
                'The document does not settle:</div>')
            for u in unclear:
                parts.append(
                    f'<div style="margin-left:12px; color:{C.TEXT_MED};">'
                    f'&middot; {e(u)}</div>')
        parts.append('</div>')

        import time as _time
        self.hud.glance(0.0, -0.85, hold=1.3)
        # Left as written, not upper-cased. The other content-panel titles are
        # the app's own English labels, but this one is the document's name in
        # the user's language, and str.upper() applies English casing rules to
        # it: Turkish "Sözleşmesi" comes back "SÖZLEŞMESI", having lost the
        # dotted capital İ. Python has no locale-aware upper to reach for, and
        # imposing one language's rules on all of them is the bug, not the fix.
        self._content_title_lbl.setText((title or "Document")[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setHtml("".join(parts))
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start)
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 260, 120), 260, 0])

    # ── quiz panel ───────────────────────────────────────────────────────────
    # An interactive twin of the content panel. The plugin only ever hands over
    # questions; everything about asking, marking and reporting happens here,
    # and the finished result is pushed back into the conversation the same way
    # a dropped file is — as a message JARVIS reads and responds to. That keeps
    # the tool call short (it returns the moment the board is up) and leaves the
    # talking to the assistant, in the user's own language.

    def _quiz_btn(self, text: str, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setFont(QFont("Courier New", 8))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumHeight(24)
        edge = C.BORDER_B if primary else C.BORDER
        col = C.PRI if primary else C.TEXT_MED
        b.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {col};
                border: 1px solid {edge}; border-radius: 2px;
                padding: 3px 9px; text-align: left;
            }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.PRI_DIM}; }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; border-color: {C.BORDER}; }}
        """)
        return b

    def _build_quiz_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("QuizPanel")
        w.setStyleSheet(f"""
            QWidget#QuizPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(6)

        hdr = QHBoxLayout(); hdr.setSpacing(6)
        dot = QLabel("◈")
        dot.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._quiz_title_lbl = QLabel("QUIZ")
        self._quiz_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._quiz_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;")
        hdr.addWidget(self._quiz_title_lbl)
        hdr.addStretch()

        self._quiz_count_lbl = QLabel("")
        self._quiz_count_lbl.setFont(QFont("Courier New", 7))
        self._quiz_count_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._quiz_count_lbl)

        quit_btn = QPushButton("DISMISS  ✕")
        quit_btn.setFont(QFont("Courier New", 7))
        quit_btn.setFixedHeight(18)
        quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        quit_btn.clicked.connect(self._hide_quiz)
        hdr.addWidget(quit_btn)
        lay.addLayout(hdr)

        rule = QFrame(); rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {C.BORDER};")
        lay.addWidget(rule)

        self._quiz_q_lbl = QLabel("")
        self._quiz_q_lbl.setWordWrap(True)
        self._quiz_q_lbl.setFont(QFont("Courier New", 9))
        self._quiz_q_lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent;")
        lay.addWidget(self._quiz_q_lbl)

        self._quiz_answers = QWidget()
        self._quiz_answers.setStyleSheet("background: transparent;")
        self._quiz_answers_lay = QVBoxLayout(self._quiz_answers)
        self._quiz_answers_lay.setContentsMargins(0, 2, 0, 0)
        self._quiz_answers_lay.setSpacing(4)
        lay.addWidget(self._quiz_answers)

        self._quiz_note_lbl = QLabel("")
        self._quiz_note_lbl.setWordWrap(True)
        self._quiz_note_lbl.setFont(QFont("Courier New", 8))
        self._quiz_note_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._quiz_note_lbl.hide()
        lay.addWidget(self._quiz_note_lbl)

        foot = QHBoxLayout()
        foot.addStretch()
        self._quiz_next_btn = self._quiz_btn("NEXT  →", primary=True)
        self._quiz_next_btn.setFixedWidth(110)
        self._quiz_next_btn.clicked.connect(self._quiz_next)
        self._quiz_next_btn.hide()
        foot.addWidget(self._quiz_next_btn)
        lay.addLayout(foot)

        self._quiz = None
        return w

    def _show_quiz(self, topic: str, questions, grader=None):
        """Slot — Qt main thread. Puts a fresh quiz on the board."""
        if not questions:
            return
        self._quiz = {
            "topic": topic or "",
            "questions": list(questions),
            "grader": grader,
            "i": 0,
            "results": [],
            "answered": False,
        }
        self._quiz_title_lbl.setText((topic or "quiz").upper()[:48])
        self.hud.glance(0.0, -0.85, hold=1.3)
        first_show = not self._quiz_panel.isVisible()
        self._quiz_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 250, 120), 0, 250])
        self._quiz_render()

    def _hide_quiz(self):
        self._quiz = None
        self._quiz_panel.hide()

    def _quiz_clear_answers(self):
        while self._quiz_answers_lay.count():
            item = self._quiz_answers_lay.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
                child.deleteLater()

    def _quiz_render(self):
        q = self._quiz["questions"][self._quiz["i"]]
        n, total = self._quiz["i"] + 1, len(self._quiz["questions"])
        self._quiz_count_lbl.setText(f"{n} / {total}")
        self._quiz_q_lbl.setText(q.get("question", ""))
        self._quiz_note_lbl.hide()
        self._quiz_next_btn.hide()
        self._quiz["answered"] = False
        self._quiz_clear_answers()

        opts = q.get("options") or []
        if opts:
            for text in opts:
                b = self._quiz_btn("   " + text)
                b.clicked.connect(lambda _=False, t=text: self._quiz_submit(t))
                self._quiz_answers_lay.addWidget(b)
        else:
            row = QWidget(); row.setStyleSheet("background: transparent;")
            h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(6)
            field = QLineEdit()
            field.setFont(QFont("Courier New", 9))
            field.setPlaceholderText("your answer")
            field.setStyleSheet(f"""
                QLineEdit {{
                    background: {C.PANEL2}; color: {C.WHITE};
                    border: 1px solid {C.BORDER}; border-radius: 2px; padding: 4px 7px;
                }}
                QLineEdit:focus {{ border-color: {C.PRI_DIM}; }}
            """)
            send = self._quiz_btn("ANSWER", primary=True)
            send.setFixedWidth(90)
            field.returnPressed.connect(lambda: self._quiz_submit(field.text()))
            send.clicked.connect(lambda: self._quiz_submit(field.text()))
            h.addWidget(field, stretch=1)
            h.addWidget(send)
            self._quiz_answers_lay.addWidget(row)
            field.setFocus()

    def _quiz_submit(self, given: str):
        if self._quiz is None or self._quiz["answered"]:
            return
        self._quiz["answered"] = True
        q = self._quiz["questions"][self._quiz["i"]]
        grader = self._quiz.get("grader")
        verdict = None
        if callable(grader):
            try:
                verdict = grader(q, given)
            except Exception:
                verdict = None
        self._quiz["results"].append({
            "question": q.get("question", ""),
            "type": q.get("type", ""),
            "given": str(given or "").strip(),
            "answer": q.get("answer", ""),
            "correct": verdict,
        })

        for i in range(self._quiz_answers_lay.count()):
            wdg = self._quiz_answers_lay.itemAt(i).widget()
            if wdg is not None:
                wdg.setEnabled(False)

        if verdict is True:
            mark, colour = "✓  correct", C.GREEN
        elif verdict is False:
            mark, colour = "✕  " + str(q.get("answer", "")), C.RED
        else:
            # Open answers and near-miss gap-fills are JARVIS's to judge. Saying
            # so is honest; marking it wrong here would be a guess.
            mark, colour = "…  noted — I'll go over this one with you", C.ACC2
        note = q.get("note") or ""
        self._quiz_note_lbl.setText(mark + (("\n" + note) if note else ""))
        self._quiz_note_lbl.setStyleSheet(f"color: {colour}; background: transparent;")
        self._quiz_note_lbl.show()

        last = self._quiz["i"] >= len(self._quiz["questions"]) - 1
        self._quiz_next_btn.setText("FINISH  →" if last else "NEXT  →")
        self._quiz_next_btn.show()
        self._quiz_next_btn.setFocus()

    def _quiz_next(self):
        if self._quiz is None:
            return
        if self._quiz["i"] >= len(self._quiz["questions"]) - 1:
            self._quiz_finish()
        else:
            self._quiz["i"] += 1
            self._quiz_render()

    def _quiz_finish(self):
        if self._quiz is None:
            return
        topic = self._quiz["topic"]
        results = self._quiz["results"]
        right = sum(1 for r in results if r["correct"] is True)
        unsure = sum(1 for r in results if r["correct"] is None)
        total = len(results)
        self._quiz_panel.hide()
        self._quiz = None

        self._log.append_log(f"QUIZ: {topic or 'quiz'} — {right}/{total} correct")

        # Hand it back to JARVIS as a message, not as a tool return: the tool
        # call ended minutes ago. This is the same channel a dropped file uses.
        lines = [f"[QUIZ_DONE] topic={topic or 'general'} | "
                 f"auto-marked {right}/{total} correct"
                 + (f", {unsure} still need your marking" if unsure else "")]
        for i, r in enumerate(results, 1):
            state = ("correct" if r["correct"] is True
                     else "wrong" if r["correct"] is False else "NEEDS MARKING")
            lines.append(
                f"{i}. [{r['type']}] {r['question']} | they answered: "
                f"{r['given'] or '(blank)'} | expected: {r['answer']} | {state}")
        lines.append(
            "Mark every question flagged NEEDS MARKING yourself — accept an answer "
            "that means the same thing. Then tell them how they did in their own "
            "language: the score, what they got wrong and why, in a couple of "
            "sentences. Offer another round only if it fits. "
            "Remember something only if it would still matter next week — that they "
            "are working through a subject, or keep missing the same thing. A score "
            "from one session is not worth a memory, and a memory per quiz would "
            "bury the things that are.")
        msg = "\n".join(lines)
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("By HarshilParmar", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell {self._assistant_name} what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        berr   = result[4] if len(result) >= 5 else ""
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw,
                               bind_error=berr)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    # ── Auto-start ──────────────────────────────────────────────────────────────

    def _check_autostart(self) -> bool:
        """Returns True if auto-start is currently registered on this OS."""
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "JARVIS_AI")
                    return True
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
            elif _OS == "Darwin":
                return (Path.home() / "Library" / "LaunchAgents"
                        / "com.jarvis.assistant.plist").exists()
            else:
                return (Path.home() / ".config" / "autostart" / "jarvis.desktop").exists()
        except Exception:
            return False

    def _toggle_autostart(self):
        currently_on = self._check_autostart()
        try:
            script = str(Path(__file__).resolve().parent / "main.py")
            if _OS == "Windows":
                import winreg
                reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                if currently_on:
                    winreg.DeleteValue(reg, "JARVIS_AI")
                else:
                    pythonw = Path(sys.executable).parent / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else sys.executable)
                    winreg.SetValueEx(reg, "JARVIS_AI", 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
                winreg.CloseKey(reg)
            elif _OS == "Darwin":
                plist_dir = Path.home() / "Library" / "LaunchAgents"
                plist_dir.mkdir(parents=True, exist_ok=True)
                plist = plist_dir / "com.jarvis.assistant.plist"
                if currently_on:
                    plist.unlink(missing_ok=True)
                else:
                    plist.write_text(
                        '<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                        '<plist version="1.0"><dict>\n'
                        '  <key>Label</key><string>com.jarvis.assistant</string>\n'
                        '  <key>ProgramArguments</key><array>\n'
                        f'    <string>{sys.executable}</string>\n'
                        f'    <string>{script}</string>\n'
                        '  </array>\n'
                        '  <key>RunAtLoad</key><true/>\n'
                        '</dict></plist>\n'
                    )
            else:
                desk_dir = Path.home() / ".config" / "autostart"
                desk_dir.mkdir(parents=True, exist_ok=True)
                desk = desk_dir / "jarvis.desktop"
                if currently_on:
                    desk.unlink(missing_ok=True)
                else:
                    desk.write_text(
                        "[Desktop Entry]\n"
                        f"Name={self._assistant_name}\n"
                        f"Exec={sys.executable} {script}\n"
                        "Type=Application\nTerminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n"
                    )
            enabled = not currently_on
            self._update_autostart_btn(enabled)
            self._log.append_log(
                f"SYS: Auto-start {'enabled' if enabled else 'disabled'}.")
        except Exception as e:
            self._log.append_log(f"ERR: Auto-start failed — {e}")

    def _update_autostart_btn(self, enabled: bool):
        if not hasattr(self, '_autostart_btn'):
            return
        if enabled:
            self._autostart_btn.setText("◉  AUTO-START: ON")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._autostart_btn.setText("◉  AUTO-START: OFF")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        new_val = not get_brief_enabled()
        save_brief_enabled(new_val)
        self._update_brief_btn(new_val)

    # ── Wake word settings ───────────────────────────────────────────────────

    def _wake_state(self) -> dict:
        """Combined state for the two wake-word buttons. Readiness is a cheap,
        deterministic on-disk check now (see core.wake_word.is_ready), so there
        is nothing to cache — the button never flickers to a stale value."""
        if self.wake_get_state:
            try:
                s = self.wake_get_state()
                return {"ready": bool(s.get("ready")),
                        "enabled": bool(s.get("enabled")),
                        "awake": bool(s.get("awake"))}
            except Exception:
                pass
        # Before JarvisLive has wired its callback (drawer built at startup).
        ready, enabled = False, False
        try:
            from core.wake_word import is_ready
            from memory.config_manager import get_wake_word_enabled
            ready, enabled = is_ready(), get_wake_word_enabled()
        except Exception:
            pass
        return {"ready": ready, "enabled": enabled, "awake": True}

    def _refresh_wake_btns(self):
        if not hasattr(self, '_wake_btn'):
            return
        st = self._wake_state()
        _on = f"""
            QPushButton {{ background: #001a08; color: {C.GREEN};
                border: 1px solid {C.GREEN_D}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ background: #002010; }}"""
        _off = f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}"""
        self._wake_btn.setEnabled(True)
        if not st["ready"]:
            self._wake_btn.setText("⬇  WAKE WORD: DOWNLOAD")
            self._wake_btn.setStyleSheet(_off)
            self._wake_sleep_btn.hide()
        elif st["enabled"]:
            self._wake_btn.setText("🎙  WAKE WORD: ON")
            self._wake_btn.setStyleSheet(_on)
            self._wake_sleep_btn.show()
            self._wake_sleep_btn.setText("😴  SLEEP NOW" if st["awake"] else "👂  WAKE NOW")
            self._wake_sleep_btn.setStyleSheet(_off)
        else:
            self._wake_btn.setText("🎙  WAKE WORD: OFF")
            self._wake_btn.setStyleSheet(_off)
            self._wake_sleep_btn.hide()

    def _refresh_talk_btns(self):
        """Repaint the push-to-talk row from the saved setting."""
        if not hasattr(self, "_ptt_btn"):
            return
        from core.hotkey import chord_label
        from memory.config_manager import get_push_to_talk_enabled
        _on = f"""
            QPushButton {{ background: #001a08; color: {C.GREEN};
                border: 1px solid {C.GREEN_D}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ background: #002010; }}"""
        _off = f"""
            QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}"""

        ptt = get_push_to_talk_enabled()
        self._ptt_btn.setText(f"🎚  PUSH-TO-TALK: {chord_label()}" if ptt
                              else "🎚  PUSH-TO-TALK: OFF")
        self._ptt_btn.setStyleSheet(_on if ptt else _off)
        self._ptt_btn.setToolTip(
            "Microphone stays closed until you hold the key — nothing is sent "
            "while you are not holding it." if ptt
            else "Hold a key to talk instead of streaming the mic continuously.")


    def _refresh_hud_btn(self):
        if not hasattr(self, '_hud_btn'):
            return
        from memory.config_manager import get_hud_style
        st = get_hud_style()
        labels = {
            "face": ("🧑  HUD: 3D AVATAR", "Holographic 3D wireframe head"),
            "core": ("◉  HUD: ARC REACTOR", "Rotational Stark Arc Reactor"),
        }
        text, tip = labels.get(st, ("🧑  HUD: 3D AVATAR", "AI Visualizer mode"))
        style = f"""
            QPushButton {{ background: {C.PANEL2}; color: {C.PRI};
                border: 1px solid {C.BORDER_A}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.WHITE}; border: 1px solid {C.BORDER_B}; }}"""
        self._hud_btn.setText(text)
        self._hud_btn.setStyleSheet(style)
        self._hud_btn.setToolTip(f"{tip}. Tap to cycle visualizer mode.")

    def _toggle_hud_style(self):
        from memory.config_manager import get_hud_style, save_hud_style, HUD_STYLES
        cur = get_hud_style()
        idx = HUD_STYLES.index(cur) if cur in HUD_STYLES else 0
        want = HUD_STYLES[(idx + 1) % len(HUD_STYLES)]
        save_hud_style(want)
        try:
            self.hud.hud_style = want
            self.hud.update()
        except Exception:
            pass
        self._refresh_hud_btn()
        self._log.append_log(f"SYS: AI HUD visualizer set to {want.upper()}.")

    def set_layout_mode(self, mode: str, persist: bool = True):
        from memory.config_manager import save_layout_mode, LAYOUT_MODES
        m = (mode or "tactical").strip().lower()
        if m not in LAYOUT_MODES:
            m = "tactical"
        self._layout_mode = m
        if persist:
            save_layout_mode(m)
        if hasattr(self, '_left_panel') and self._left_panel is not None:
            self._left_panel.setVisible(m == "tactical")
        self._refresh_layout_btn()

    def _refresh_layout_btn(self):
        if not hasattr(self, '_layout_btn'):
            return
        is_tact = getattr(self, '_layout_mode', 'tactical') == 'tactical'
        self._layout_btn.setText("⊞  LAYOUT: TACTICAL" if is_tact
                                 else "⊟  LAYOUT: FOCUS MODE")
        self._layout_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PANEL2}; color: {C.PRI};
                border: 1px solid {C.BORDER_A}; border-radius: 3px;
                text-align: left; padding: 0 8px; }}
            QPushButton:hover {{ color: {C.WHITE}; border: 1px solid {C.BORDER_B}; }}""")
        self._layout_btn.setToolTip("Toggle between full 3-column tactical dashboard and focused centered view.")

    def _toggle_layout_mode(self):
        want = "focus" if getattr(self, '_layout_mode', 'tactical') == "tactical" else "tactical"
        self.set_layout_mode(want, persist=True)
        self._log.append_log(f"SYS: Layout switched to {want.upper()} mode.")

    def _toggle_ptt(self):
        from memory.config_manager import (get_push_to_talk_enabled,
                                           save_push_to_talk_enabled)
        want = not get_push_to_talk_enabled()
        save_push_to_talk_enabled(want)
        scope = None
        if self.on_push_to_talk:
            try:
                scope = self.on_push_to_talk(want)
            except Exception as e:
                self._log.append_log(f"ERR: Push-to-talk failed — {e}")
                save_push_to_talk_enabled(False)
                want = False
        self._apply_ptt_shortcut(want and scope != "global")
        self._refresh_talk_btns()

    def _apply_ptt_shortcut(self, needed: bool):
        """Bind the chord inside the window when no global hook is available.

        On macOS and Linux there is no dependency-free way to read global key
        state, so the chord is at least live whenever this window has focus.
        Qt gives no key-release for a QShortcut, so a press latches the mic open
        and a short timer closes it; held down, auto-repeat keeps pushing that
        timer out, which behaves like holding a key.
        """
        from PyQt6.QtGui import QKeySequence, QShortcut
        from core.hotkey import qt_sequence

        if not needed:
            sc = getattr(self, "_ptt_sc", None)
            if sc is not None:
                sc.setEnabled(False)
                self._ptt_sc = None
            self._ptt_hold(False)
            return
        if getattr(self, "_ptt_sc", None) is not None:
            return

        self._ptt_release = QTimer(self)
        self._ptt_release.setSingleShot(True)
        self._ptt_release.setInterval(420)
        self._ptt_release.timeout.connect(lambda: self._ptt_hold(False))

        def _press():
            self._ptt_hold(True)
            self._ptt_release.start()

        self._ptt_sc = QShortcut(QKeySequence(qt_sequence()), self)
        self._ptt_sc.setAutoRepeat(True)
        self._ptt_sc.activated.connect(_press)

    def _ptt_hold(self, held: bool):
        """Report a windowed press/release to whoever owns the microphone."""
        cb = getattr(self, "ptt_hold", None)
        if cb:
            try:
                cb(bool(held))
            except Exception:
                pass

    def _toggle_wake_word(self):
        st = self._wake_state()
        if not st["ready"]:
            # First time: download openwakeword + model in a worker thread.
            self._wake_btn.setText("⬇  DOWNLOADING… (one-time)")
            self._wake_btn.setEnabled(False)
            def _work():
                try:
                    from core.wake_word import install_and_download
                    ok, msg = install_and_download(
                        logger=lambda m: self._log_sig.emit(f"SYS: {m}"))
                except Exception as e:
                    ok, msg = False, str(e)
                if ok and self.on_wake_toggle:
                    try:
                        self.on_wake_toggle(True)   # auto-enable after a successful download
                    except Exception:
                        pass
                self._wake_dl_sig.emit(ok, msg)
            threading.Thread(target=_work, daemon=True).start()
            return
        # Already downloaded → just flip enabled/disabled through JarvisLive.
        if self.on_wake_toggle:
            try:
                self.on_wake_toggle(not st["enabled"])
            except Exception:
                pass
        self._refresh_wake_btns()

    def _on_wake_install_done(self, ok: bool, msg: str):
        self._log_sig.emit(f"SYS: {'Wake word ready.' if ok else 'Wake word setup failed: ' + msg}")
        self._refresh_wake_btns()

    def _tap_wake_manual(self):
        if self.on_wake_manual:
            try:
                self.on_wake_manual()
            except Exception:
                pass
        self._refresh_wake_btns()

    def _update_brief_btn(self, enabled: bool):
        if not hasattr(self, '_brief_btn'):
            return
        if enabled:
            self._brief_btn.setText("☀  MORNING BRIEF: ON")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._brief_btn.setText("☀  MORNING BRIEF: OFF")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    # ── Customization ────────────────────────────────────────────────────────────

    def _open_customize(self):
        cfg = _read_full_config()
        if self._customize_overlay:
            self._customize_overlay.hide()
        cw = self.centralWidget()
        from memory.config_manager import get_hud_style, get_layout_mode
        ov = CustomizeOverlay(
            cfg.get("assistant_name", "JARVIS") or "JARVIS",
            cfg.get("user_name", ""),
            cfg.get("ui_color", "") or DEFAULT_UI_COLOR,
            cfg.get("voice_name", ""),
            hud_style=get_hud_style(),
            layout_mode=get_layout_mode(),
            parent=cw,
        )
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        oh = min(oh, cw.height() - 16)
        ow = min(ow, cw.width() - 20)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.on_preview = self._preview_ui_color
        ov.on_preview_hud = self._preview_hud_style
        ov.on_preview_layout = self._preview_layout_mode
        ov.saved.connect(self._apply_name_update)
        ov.show()
        self._customize_overlay = ov

    def _preview_ui_color(self, hex_color: str):
        """Live preview — paints the whole interface the new colour (does NOT write to config)."""
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())

    def _preview_hud_style(self, style: str):
        try:
            self.hud.hud_style = style
            self.hud.update()
        except Exception:
            pass

    def _preview_layout_mode(self, mode: str):
        self.set_layout_mode(mode, persist=False)

    def _apply_name_update(self, name: str, user_name: str, ui_color: str = "",
                           voice: str = "", hud_style: str = "face", layout_mode: str = "tactical"):
        """Update all name/theme/visualizer/layout elements and persist to config."""
        self._assistant_name = name.strip() or "JARVIS"
        display = self._assistant_name.upper()
        title = f"{display} — {APP_VERSION}" if APP_VERSION else display
        self.setWindowTitle(title)
        self._title_lbl.setText(display)
        from memory.config_manager import get_voice
        v_disp = (voice or get_voice() or "Mayra").strip().title()
        if display in ("JARVIS", "J.A.R.V.I.S"):
            if v_disp:
                self._sub_lbl.setText(f"Just A Rather Very Intelligent System • Voice: {v_disp}")
            else:
                self._sub_lbl.setText("Just A Rather Very Intelligent System")
        else:
            if v_disp:
                self._sub_lbl.setText(f"Personal AI Assistant • Voice: {v_disp}")
            else:
                self._sub_lbl.setText("Personal AI Assistant")
        self._log._ai_name_lc = self._assistant_name.lower()
        self.hud._assistant_name = display

        color_changed = False
        if ui_color:
            old = current_palette()
            if apply_ui_accent(ui_color):
                retheme_all_widgets(old, current_palette())
                color_changed = old["PRI"] != C.PRI

        # Voice change → persist and rebuild Live session if changed
        voice_changed = False
        if voice:
            from memory.config_manager import get_voice, save_voice
            if voice != get_voice():
                save_voice(voice)
                voice_changed = True

        # HUD visualizer makeover
        if hud_style:
            from memory.config_manager import save_hud_style
            save_hud_style(hud_style)
            try:
                self.hud.hud_style = hud_style
                self.hud.update()
            except Exception:
                pass
            self._refresh_hud_btn()

        # Layout makeover
        if layout_mode:
            self.set_layout_mode(layout_mode, persist=True)

        try:
            data = _read_full_config()
            data["assistant_name"] = self._assistant_name
            data["user_name"] = user_name.strip()
            if ui_color:
                data["ui_color"] = ui_color.strip().lower()
            if hud_style:
                data["hud_style"] = hud_style
            if layout_mode:
                data["layout_mode"] = layout_mode
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            self._log.append_log(f"SYS: Identity updated — {display}")
            if color_changed:
                self._log.append_log(f"SYS: UI colour applied — {ui_color}")
            if voice_changed:
                self._log.append_log(f"SYS: Voice set — {voice}")
            self._log.append_log(f"SYS: Visualizer — {hud_style.upper()} | Layout: {layout_mode.upper()}")
        except Exception as e:
            self._log.append_log(f"ERR: Config save failed — {e}")

        if voice_changed and self.on_voice_change:
            self.on_voice_change()

    def _centre_overlay(self, ov) -> None:
        """Place a floating overlay in the middle of the HUD and show it."""
        cw = self.centralWidget()
        ov.adjustSize()
        ov.setGeometry(
            max(0, (cw.width()  - ov.width())  // 2),
            max(0, (cw.height() - ov.height()) // 2),
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()

    # ── Audio devices ────────────────────────────────────────────────────────

    def _open_audio_devices(self):
        ov = AudioDeviceOverlay(parent=self.centralWidget())
        ov.picked.connect(self._on_audio_devices_applied)
        self._centre_overlay(ov)
        self._audio_overlay = ov            # keep a reference so it isn't GC'd

    def _on_audio_devices_applied(self):
        self._log.append_log("SYS: Audio devices updated.")
        if self.on_audio_device_change:
            self.on_audio_device_change()

    # ── Engine & providers ───────────────────────────────────────────────────

    def _open_providers(self):
        """Open the engine panel. Everything it needs is imported on this call.

        A failure here must not take the drawer with it — the folder can be
        deleted, which is the point of it being a folder, and the honest answer
        to that is a line in the log rather than a traceback.
        """
        try:
            ov = ProvidersOverlay(parent=self.centralWidget())
        except ImportError:
            self._log.append_log(
                "SYS: The providers folder is not installed — "
                "the assistant runs on Gemini Live.")
            return
        except Exception as e:
            self._log.append_log(f"SYS: Provider settings unavailable: {e}")
            return
        ov.changed.connect(self._on_providers_applied)
        self._centre_overlay(ov)
        self._providers_overlay = ov        # keep a reference so it isn't GC'd

    def _on_providers_applied(self):
        """Rebuild the session so the new engine takes over.

        Reuses the audio-device callback rather than adding a second one: both
        mean 'the conversation has to be rebuilt', main.py already keeps the
        transcript across such a rebuild through session resumption, and one
        path that is known to work is better than two that look alike."""
        self._log.append_log("SYS: Engine settings saved — reconnecting.")
        if self.on_audio_device_change:
            self.on_audio_device_change()

    # ── Memory panel ─────────────────────────────────────────────────────────

    def _open_memory_panel(self):
        ov = MemoryOverlay(parent=self.centralWidget())
        self._centre_overlay(ov)
        self._memory_overlay = ov

    # ── Irreversible-action confirmation ─────────────────────────────────────

    def _show_confirm_banner(self, title: str, detail: str):
        self._hide_confirm_banner()
        ov = ConfirmBanner(title, detail, parent=self.centralWidget())
        ov.answered.connect(self._on_confirm_answered)
        self._centre_overlay(ov)
        self._confirm_overlay = ov

    def _hide_confirm_banner(self):
        ov = getattr(self, "_confirm_overlay", None)
        if ov is not None:
            ov.hide()
            ov.deleteLater()
            self._confirm_overlay = None

    def _on_confirm_answered(self, accepted: bool):
        # Tear the banner down first: core.confirm.resolve() may be about to
        # shut the machine down, and a live widget mid-callback is not where you
        # want to be when that happens.
        self._hide_confirm_banner()
        try:
            from core.confirm import resolve
            resolve(bool(accepted))
        except Exception as e:
            self._log.append_log(f"ERR: Confirmation failed — {e}")

    def _open_plugin_manager(self):
        plugins = self.get_plugins() if self.get_plugins else []
        cw = self.centralWidget()
        ov = PluginManagerOverlay(plugins, parent=cw)
        ov.adjustSize()
        ov.setGeometry(
            (cw.width()  - ov.width())  // 2,
            (cw.height() - ov.height()) // 2,
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()
        self._plugin_manager_overlay = ov   # keep a reference so it isn't GC'd

    def _open_plugin_settings(self):
        sections = self.get_plugin_settings() if self.get_plugin_settings else []
        cw = self.centralWidget()
        ov = PluginSettingsOverlay(sections, parent=cw)
        ow = PluginSettingsOverlay._OW
        oh = min(560, cw.height() - 16)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.show()
        ov.raise_()
        self._plugin_settings_overlay = ov   # keep a reference so it isn't GC'd

    # ── Resource Guardian & Diagnostics ──────────────────────────────────────

    def _open_resource_diagnostics(self):
        if not hasattr(self, "_res_diag_overlay") or self._res_diag_overlay is None:
            self._res_diag_overlay = ResourceDiagnosticsOverlay(
                parent=self.centralWidget(),
                on_profile_changed=self.set_resource_profile,
            )
        self._res_diag_overlay.refresh()
        self._centre_overlay(self._res_diag_overlay)

    def set_resource_profile(self, profile: str, persist: bool = True):
        clean = ResourceGuardian.get_instance().set_profile(profile)
        if persist:
            from memory.config_manager import save_resource_profile
            save_resource_profile(clean)
        self._resource_profile = clean
        disp = PROFILE_DISPLAY_NAMES.get(clean, clean.upper())
        if hasattr(self, "_prof_btn"):
            self._prof_btn.setText(disp)

        # 1. Dynamically rewire HudCanvas rendering and timer loop
        if hasattr(self, "hud") and self.hud:
            self.hud.apply_resource_profile(clean)

        # 2. Dynamically rewire Lyrics Panel animations & star density
        if hasattr(self, "_lyrics_panel") and self._lyrics_panel:
            self._lyrics_panel.apply_resource_profile(clean)

        # 3. Dynamic Left Rail Minimal Restructuring & Telemetry Gating
        is_eco = (clean == "low_ram")
        if hasattr(self, "_eco_panel") and self._eco_panel:
            self._eco_panel.setVisible(is_eco)
        has_gpu = getattr(_metrics, "_has_gpu", True)
        has_temp = getattr(_metrics, "_has_temp", True)
        for b, avail in [
            (getattr(self, "_bar_cpu", None), True),
            (getattr(self, "_bar_mem", None), True),
            (getattr(self, "_bar_proc_ram", None), True),
            (getattr(self, "_bar_net", None), True),
            (getattr(self, "_bar_gpu", None), has_gpu),
            (getattr(self, "_bar_tmp", None), has_temp),
        ]:
            if b:
                b.setVisible((not is_eco) and avail)
        if hasattr(self, "_sparkline") and self._sparkline:
            self._sparkline.setVisible(not is_eco)
            self._sparkline.setEnabled(not is_eco)
        if hasattr(self, "_info_panel") and self._info_panel:
            self._info_panel.setVisible(not is_eco)
        if hasattr(self, "_protocol_panel") and self._protocol_panel:
            self._protocol_panel.setVisible(not is_eco)

        # Dynamic metric timer rate: 20s in low_ram, 3s in balanced, 1.5s in full
        if hasattr(self, "_metric_tmr") and self._metric_tmr:
            tmr_rate = 20000 if is_eco else (3000 if clean == "balanced" else 1500)
            self._metric_tmr.setInterval(tmr_rate)

        # 4. Immediate memory release for Low RAM and Balanced modes
        if clean in ("low_ram", "balanced"):
            try:
                from core.ram_cleaner import release_unused_ram
                release_unused_ram()
            except Exception:
                pass

        if clean == "low_ram":
            self._log.append_log("SYS: ECO / LOW RAM profile activated — 3D mesh math & animation loops trimmed (CPU <2%).")
        elif clean == "balanced":
            self._log.append_log("SYS: BALANCED profile activated — 30 FPS dynamic optimization with smart sleep.")
        else:
            self._log.append_log("SYS: FULL EXPERIENCE profile activated — 60 FPS Stark holographic showcase.")

    # ── Smart Command Palette (Ctrl+K) ───────────────────────────────────────

    def _toggle_command_palette(self):
        if hasattr(self, "_command_palette") and self._command_palette and self._command_palette.isVisible():
            self._command_palette.hide()
            return
        self._populate_command_palette()
        cw = self.centralWidget()
        ow = CommandPaletteOverlay._OW
        oh = CommandPaletteOverlay._OH
        ox = max(0, (cw.width() - ow) // 2)
        oy = max(24, (cw.height() - oh) // 4)
        self._command_palette.setGeometry(ox, oy, ow, oh)
        self._command_palette.show_palette()

    def _populate_command_palette(self):
        if not hasattr(self, "_command_registry") or self._command_registry is None:
            self._command_registry = CommandPaletteRegistry(notify_log=self._log.append_log)
            self._command_palette = CommandPaletteOverlay(self._command_registry, parent=self.centralWidget())

        reg = self._command_registry

        # Navigation & Views
        reg.register(CommandItem("view.fullscreen", "Toggle Fullscreen", "Toggle full screen HUD mode", "VIEW", "F11", self._toggle_fullscreen))
        reg.register(CommandItem("view.mute", "Toggle Microphone Mute", "Mute or unmute the input microphone", "VIEW", "F4", self._toggle_mute))
        reg.register(CommandItem("view.interrupt", "Interrupt Speech", "Cut in and stop speech mid-turn", "VIEW", "Escape", self._do_interrupt))
        reg.register(CommandItem("view.tactical", "Switch Layout: Tactical Mode", "3-column HUD with telemetry, visualizer, and log", "VIEW", "", lambda: self.set_layout_mode("tactical")))
        reg.register(CommandItem("view.focus", "Switch Layout: Focus Mode", "Center-focused streamlined layout", "VIEW", "", lambda: self.set_layout_mode("focus")))
        reg.register(CommandItem("view.style_face", "Visualizer: 3D Holographic Head", "Stark avatar 3D low-poly face", "VIEW", "", lambda: self.set_hud_style("face")))
        reg.register(CommandItem("view.style_core", "Visualizer: Stark Arc Reactor", "Revolving sweep arc core", "VIEW", "", lambda: self.set_hud_style("core")))

        # Panels & Controls
        reg.register(CommandItem("panel.diagnostics", "Resource Guardian & Diagnostics", "Live RSS, memory leak diagnostics, and profiles", "SYSTEM", "Ctrl+D", self._open_resource_diagnostics))
        reg.register(CommandItem("panel.memory", "Open Memory Bank", "Inspect and search long-term memories", "SYSTEM", "", self._open_memory_panel))
        reg.register(CommandItem("panel.audio_devices", "Audio Device Settings", "Configure microphone and speaker devices", "SYSTEM", "", self._open_audio_devices))
        reg.register(CommandItem("panel.providers", "Engine & Provider Settings", "Select LLM, STT, TTS and sidecar providers", "SYSTEM", "", self._open_providers))
        reg.register(CommandItem("panel.plugins", "Plugin Manager", "Browse and toggle community plugins", "SYSTEM", "", self._open_plugin_manager))
        reg.register(CommandItem("panel.plugin_settings", "Plugin Configuration", "Configure parameters for enabled plugins", "SYSTEM", "", self._open_plugin_settings))
        reg.register(CommandItem("panel.customize", "Customise Assistant", "Character voices, visualizer modes, and theme colors", "SYSTEM", "", self._open_customize))
        reg.register(CommandItem("panel.remote", "Remote Control Phone Link", "Pair mobile browser dashboard via QR code", "SYSTEM", "", self._open_remote))
        reg.register(CommandItem("panel.setup_drawer", "Toggle Setup Drawer", "Open or close the setup drawer", "SYSTEM", "", lambda: self._toggle_drawer(not self._quick_drawer.isVisible())))
        reg.register(CommandItem("panel.ctrl_drawer", "Toggle Controls Drawer", "Open or close everyday switches drawer", "SYSTEM", "", lambda: self._toggle_controls(not self._ctrl_drawer.isVisible())))
        reg.register(CommandItem("panel.desktop_shortcut", "Create Desktop Shortcut", "Create launch shortcut on desktop", "SYSTEM", "", self._create_desktop_shortcut))

        # Profiles
        reg.register(CommandItem("profile.low_ram", "Resource Profile: LOW RAM", "Saves memory: drops dust particles, slows telemetry, defers models", "PROFILE", "", lambda: self.set_resource_profile("low_ram")))
        reg.register(CommandItem("profile.balanced", "Resource Profile: BALANCED", "Standard responsive voice assistant with 2s telemetry", "PROFILE", "", lambda: self.set_resource_profile("balanced")))
        reg.register(CommandItem("profile.full", "Resource Profile: FULL EXPERIENCE", "Highest visualizer fidelity and rapid telemetry updates", "PROFILE", "", lambda: self.set_resource_profile("full")))

        # System Tools
        reg.register(CommandItem("core.system_status", "System Status Snapshot", "Read real-time CPU, RAM, GPU, and system uptime", "SYSTEM", "", lambda: self._dispatch_palette_action("system_status", {})))
        reg.register(CommandItem("core.undo", "Undo Last Action", "Undo the most recent computer control action", "SYSTEM", "", lambda: self._dispatch_palette_action("undo", {})))

        # Voice & Gating
        reg.register(CommandItem("ctrl.wake_word", "Toggle Wake Word", "Enable or disable 'Hey Jarvis' keyword detection", "SYSTEM", "", self._toggle_wake_word))
        reg.register(CommandItem("ctrl.wake_manual", "Wake / Sleep Toggle", "Manually wake assistant or put to sleep", "SYSTEM", "", self._tap_wake_manual))
        reg.register(CommandItem("ctrl.push_to_talk", "Toggle Push-to-Talk", "Switch between open mic and push-to-talk hotkey", "SYSTEM", "", self._toggle_ptt))
        reg.register(CommandItem("ctrl.morning_brief", "Toggle Morning Briefing", "Daily briefing on first launch of the morning", "SYSTEM", "", self._toggle_brief))

        # Discovered Actions
        if hasattr(self, "get_action_registry") and callable(self.get_action_registry):
            act_reg = self.get_action_registry()
            if act_reg and hasattr(act_reg, "_actions"):
                for name, rec in act_reg._actions.items():
                    cmd_id = f"action.{name}"
                    props = rec.parameters.get("properties", {})
                    req = bool(props)
                    if not req or name in ("system_status", "undo"):
                        h = lambda n=name: self._dispatch_palette_action(n, {})
                        req_params = False
                    else:
                        h = None
                        req_params = True
                    reg.register(CommandItem(
                        id=cmd_id,
                        title=f"Action: {name}",
                        description=rec.description or f"Registered tool action {name}",
                        category="ACTION",
                        handler=h,
                        action_name=name,
                        requires_params=req_params,
                        param_names=list(props.keys()),
                    ))

        # Discovered Plugins
        if hasattr(self, "get_plugins") and callable(self.get_plugins):
            try:
                plugins = self.get_plugins() or []
                for p in plugins:
                    pname = p.get("name")
                    if not pname:
                        continue
                    cmd_id = f"plugin.{pname}"
                    en = p.get("enabled", False)
                    desc = p.get("description", "")
                    reg.register(CommandItem(
                        id=cmd_id,
                        title=f"Plugin: {pname}",
                        description=desc or f"Community plugin {pname}",
                        category="PLUGIN",
                        is_available=en,
                        unavailable_reason=f"Plugin '{pname}' is disabled in Plugin Manager." if not en else "",
                        plugin_name=pname,
                        handler=(lambda n=pname: self._dispatch_palette_plugin(n, {})) if en else None,
                    ))
            except Exception:
                pass

    def _dispatch_palette_action(self, name: str, params: dict):
        if hasattr(self, "dispatch_action") and callable(self.dispatch_action):
            res = self.dispatch_action(name, params)
            self._log.append_log(f"ACT [{name}]: {res}")
            return res
        elif hasattr(self, "on_text_command") and callable(self.on_text_command):
            self.on_text_command(f"Execute {name}")
            return f"Action {name} dispatched."
        return f"Action {name} cannot be dispatched right now."

    def _dispatch_palette_plugin(self, name: str, params: dict):
        if hasattr(self, "dispatch_plugin") and callable(self.dispatch_plugin):
            res = self.dispatch_plugin(name, params)
            self._log.append_log(f"PLUG [{name}]: {res}")
            return res
        return f"Plugin {name} cannot be dispatched right now."

    # ── Clipboard intelligence ───────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text().strip()
            if len(text) >= 10:
                self._clipboard_sig.emit(text)
        except Exception:
            pass

    def _show_clipboard_panel(self, text: str):
        self._clipboard_panel.show_clipboard(text)
        self._position_clipboard_panel()

    def _position_clipboard_panel(self):
        cw = self.centralWidget()
        pw = ClipboardPanel._W
        ph = self._clipboard_panel.sizeHint().height() or ClipboardPanel._H
        x = (cw.width() - pw) // 2
        y = cw.height() - ph - 6
        self._clipboard_panel.setGeometry(x, y, pw, ph)
        self._clipboard_panel.raise_()

    def _on_clipboard_action(self, cmd: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,), daemon=True).start()

    # ────────────────────────────────────────────────────────────────────────────

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mute(self):
        # A deliberate press settles the question: whatever the video did, or is
        # about to do, the user has now said what they want.
        self._video_auto_muted = False
        self._set_muted(not self._muted)

    def _set_muted(self, muted: bool, note: str = ""):
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.hud.muted = muted
        self._style_mute_btn()
        if muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted." + (f" {note}" if note else ""))
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active." + (f" {note}" if note else ""))

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")

    def set_state(self, state: str) -> None:
        self._apply_state(state)

    @property
    def state(self) -> str:
        return self.hud.state

    def write_log(self, msg: str) -> None:
        if self._log:
            self._log.append_log(msg)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "JARVIS") or "JARVIS"
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. {self._assistant_name} online.")


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self.root = _RootShim(self._app)
        self._win.show()

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_voice_change(self):
        return self._win.on_voice_change

    @on_voice_change.setter
    def on_voice_change(self, cb):
        self._win.on_voice_change = cb

    @property
    def on_audio_device_change(self):
        return self._win.on_audio_device_change

    @on_audio_device_change.setter
    def on_audio_device_change(self, cb):
        self._win.on_audio_device_change = cb

    def show_confirm(self, title: str, detail: str) -> None:
        """Thread-safe: raise the irreversible-action gate. Called from action
        handlers running in executor threads, so it goes through a signal."""
        self._win._confirm_sig.emit(str(title)[:120], str(detail)[:300])

    def hide_confirm(self) -> None:
        """Thread-safe: take the gate down."""
        self._win._confirm_hide_sig.emit()

    @property
    def get_plugins(self):
        return self._win.get_plugins

    @get_plugins.setter
    def get_plugins(self, cb):
        self._win.get_plugins = cb

    @property
    def get_plugin_settings(self):
        return self._win.get_plugin_settings

    @get_plugin_settings.setter
    def get_plugin_settings(self, cb):
        self._win.get_plugin_settings = cb

    @property
    def on_wake_toggle(self):
        return self._win.on_wake_toggle

    @on_wake_toggle.setter
    def on_wake_toggle(self, cb):
        self._win.on_wake_toggle = cb

    @property
    def on_wake_manual(self):
        return self._win.on_wake_manual

    @on_wake_manual.setter
    def on_wake_manual(self, cb):
        self._win.on_wake_manual = cb

    @property
    def wake_get_state(self):
        return self._win.wake_get_state

    @wake_get_state.setter
    def wake_get_state(self, cb):
        self._win.wake_get_state = cb

    def set_audio_level(self, level: float) -> None:
        """Thread-safe: feed a 0.0–1.0 live audio level to the HUD waveform.
        Called from the audio threads; a plain float store is atomic under the
        GIL, so no signal/lock is needed for this cosmetic value."""
        try:
            self._win.hud.set_audio_level(level)
        except Exception:
            pass

    def glance(self, dx: float, dy: float, hold: float = 1.1) -> None:
        """Ask the avatar to look somewhere for a moment (see HoloAvatar.glance)."""
        try:
            if self._avatar is not None:
                self._avatar.glance(dx, dy, hold)
        except Exception:
            pass

    @property
    def ptt_hold(self):
        return self._win.ptt_hold

    @ptt_hold.setter
    def ptt_hold(self, cb):
        self._win.ptt_hold = cb

    @property
    def on_push_to_talk(self):
        return self._win.on_push_to_talk

    @on_push_to_talk.setter
    def on_push_to_talk(self, cb):
        self._win.on_push_to_talk = cb

    @property
    def get_action_registry(self):
        return self._win.get_action_registry

    @get_action_registry.setter
    def get_action_registry(self, cb):
        self._win.get_action_registry = cb

    @property
    def get_plugin_registry(self):
        return self._win.get_plugin_registry

    @get_plugin_registry.setter
    def get_plugin_registry(self, cb):
        self._win.get_plugin_registry = cb

    @property
    def dispatch_action(self):
        return self._win.dispatch_action

    @dispatch_action.setter
    def dispatch_action(self, cb):
        self._win.dispatch_action = cb

    @property
    def dispatch_plugin(self):
        return self._win.dispatch_plugin

    @dispatch_plugin.setter
    def dispatch_plugin(self, cb):
        self._win.dispatch_plugin = cb

    def set_resource_profile(self, profile: str):
        self._win.set_resource_profile(profile)

    def open_command_palette(self):
        self._win._toggle_command_palette()

    def open_resource_diagnostics(self):
        self._win._open_resource_diagnostics()

    def push_visemes(self, frames, hop: float, at: float) -> None:
        """Thread-safe: post a schedule of (level, openness, width) mouth frames
        for JARVIS's own speech. `at` is the wall-clock time the batch begins to
        sound, not the time of the call. See HudCanvas.push_visemes()."""
        try:
            self._win.hud.push_visemes(frames, hop, at)
        except Exception:
            pass

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def show_quiz(self, topic: str, questions, grade=None) -> None:
        """Thread-safe: put an interactive quiz on the board.

        `grade(question, given)` decides each answer — the plugin supplies it so
        the marking rules live with the questions rather than being duplicated
        here. Returning None from it means "JARVIS should judge this one", which
        is how open answers and near-miss gap-fills are handled.

        Returns immediately: the user answers at their own pace and the finished
        result is delivered back through on_text_command.
        """
        self._win._quiz_sig.emit(str(topic or ""), list(questions or []), grade)

    def hide_quiz(self) -> None:
        """Thread-safe: clear any quiz currently on the board."""
        self._win._quiz_hide_sig.emit()

    def show_review(self, title: str, summary: str, findings, unclear=None) -> None:
        """Thread-safe: lay a document review into the panel below the HUD.

        `findings` is a list of {heading, detail, severity, quote, suggestion};
        severity is one of 'serious' / 'caution' / 'note' and decides colour and
        order here, so the caller supplies no styling of its own.
        """
        self._win._review_sig.emit(str(title or ""), str(summary or ""),
                                   list(findings or []), list(unclear or []))

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def show_video(self, source: str, title: str = "", muted: bool = False,
                   audio_source: str = "") -> None:
        """Thread-safe: play a video where the avatar normally is.

        `source` is a local path or a direct media URL. `audio_source` is for
        the case where the sound arrives as its own stream — YouTube serves no
        combined format any more — and when it is given the two are played
        together and kept in step.

        Muted by default, and that is a decision rather than a default: a
        soundtrack talking over JARVIS is the one way this could make the
        assistant worse. The user turns sound on from the header button or by
        asking, and closes it the same two ways.
        """
        self._win._video_open_sig.emit(str(source or ""), str(title or ""),
                                       bool(muted), str(audio_source or ""))

    def stop_video(self) -> None:
        """Thread-safe: close the video and give the HUD back to the avatar."""
        self._win._video_close_sig.emit()

    def set_video_muted(self, muted: bool) -> None:
        """Thread-safe: silence or unsilence whatever is playing."""
        self._win._video_mute_sig.emit(bool(muted))

    def video_is_playing(self) -> bool:
        return bool(self._win.video_is_playing())

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def show_lyrics_track(self, track_name: str, artist_name: str = "", youtube_info: dict = None) -> None:
        """Thread-safe: display live synchronized lyrics in bottom-center panel."""
        self._win._lyrics_open_sig.emit(str(track_name or ""), str(artist_name or ""), youtube_info or {})

    def update_lyrics_position(self, pos_sec: float) -> None:
        """Thread-safe: update lyrics playback position."""
        self._win._lyrics_pos_sig.emit(float(pos_sec))

    def restore_search_content(self) -> None:
        """Thread-safe: restore previous search results when music finishes."""
        self._win._lyrics_close_sig.emit()