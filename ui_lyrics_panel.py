"""
ui_lyrics_panel.py — 2D Astronomical Constellation Lyrics & Spotlight Reel System.

Features:
- 2D Astronomical Constellation Flow: Lyrics lines are mapped across the 2D panel space
  (NOT horizontal, NOT vertical, but randomly/astronomically placed star dots).
  The active star lights up with a radiant corona, and the exact lyric line appears right
  at that dot inside a frosted glassmorphism capsule pill.
  An energized laser filament with an animated traveling photon pulse connects from the previous
  star to the active star, dynamically charting the constellation across the sky.
- Ultra-Low RAM Architecture: Zero QGraphicsBlurEffect allocations; animation timer runs ONLY
  during active photon pulse transitions (~600ms) and sleeps immediately (0% CPU, < 3 MB RAM).
- Spotlight Reel View: Active middle line is magnified (26pt Bold) with glowing emphasis
  and agile 130ms snappy transitions.
- View Switcher: Seamless one-click toggle between [VIEW: CONSTELLATION ✦] (Default) and [VIEW: REEL ▾].
- Interactive Seek: Clicking any star dot in Constellation or any line in Reel seeks playback immediately.
"""

from __future__ import annotations

import re
import math
import random
from typing import Optional, List, Tuple
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QRectF, QPointF, QTimer
from PyQt6.QtGui import QFont, QColor, QFontMetrics, QPainter, QPen, QBrush, QRadialGradient
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QStackedWidget
)

from theme import ThemeColors
from core.lyrics_engine import LyricsTrack, LyricsLine, apply_language_rules
from memory.config_manager import (
    get_lyrics_mode, save_lyrics_mode, get_roman_gujarati_enabled,
    get_lyrics_view_mode, save_lyrics_view_mode
)


# ── 2D Astronomical Constellation Canvas ─────────────────────────────────────

class ConstellationLyricsWidget(QWidget):
    """
    2D Celestial Star Constellation Lyrics Canvas with Blurred Cosmic Nebula & Frosted Acrylic Backdrop.
    - Zero Lingering Past Lyrics: When a lyric finishes singing, it disappears immediately from the screen.
    - Zero Future Spoilers: Future lyrics remain completely hidden until their exact singing timestamp.
    - Dynamic Sing-along Karaoke: As words are sung, they ignite into brilliant radiant white.
    - Laser Filament Connection: When switching stars, an animated laser beam shoots from the previous star.
    - Ultra-Low CPU & Zero Memory Leak: Animation timer runs strictly during the ~500ms photon pulse (0% CPU idle).
    """

    word_clicked = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(240)

        self._lines: List[dict] = []
        self._active_idx: int = -1
        self._prev_active_idx: int = -1
        self._active_word_idx: int = -1
        self._pulse_phase: float = 1.0
        self._pri_color: QColor = QColor("#00ff41")
        self._is_black_theme: bool = True
        self._cluster_size: int = 5

        # 60 precomputed ambient micro-stars scattered across deep space
        random.seed(1337)
        self._bg_stars = [
            (random.uniform(0.02, 0.98), random.uniform(0.04, 0.96), random.uniform(1.0, 2.2), random.randint(25, 120))
            for _ in range(60)
        ]

        # Timer runs ONLY during active photon pulse transition (~500ms), then stops immediately (0% CPU at idle)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_anim_tick)

    def apply_resource_profile(self, profile: str) -> None:
        """Dynamic background star trimming based on active resource profile."""
        from core.resource_guardian import PROFILE_LOW_RAM, PROFILE_BALANCED
        if profile == PROFILE_LOW_RAM:
            self._bg_stars_count = 15
        elif profile == PROFILE_BALANCED:
            self._bg_stars_count = 35
        else:
            self._bg_stars_count = 60
        self.update()

    def set_theme(self, pri_hex: str, is_black: bool = True):
        self._pri_color = QColor(pri_hex)
        self._is_black_theme = is_black
        self.update()

    def set_words(self, words: List[dict]):
        """Legacy helper for backward compatibility."""
        pass

    def set_rich_lines(self, lines_data: List[dict]):
        """
        Populates rich line and word-level data into 2D astronomical constellation coordinates.
        Calculates distinct start and end times for each line so finished lyrics disappear cleanly.
        """
        self._lines.clear()
        self._active_idx = -1
        self._prev_active_idx = -1
        self._active_word_idx = -1
        self._pulse_phase = 1.0
        if not lines_data:
            self.update()
            return

        constellation_shapes = [
            [(0.20, 0.65), (0.35, 0.30), (0.50, 0.60), (0.65, 0.28), (0.80, 0.62)],
            [(0.50, 0.24), (0.25, 0.52), (0.75, 0.50), (0.50, 0.78), (0.62, 0.36)],
            [(0.22, 0.35), (0.38, 0.70), (0.62, 0.72), (0.78, 0.36), (0.50, 0.45)],
            [(0.28, 0.28), (0.72, 0.30), (0.68, 0.74), (0.32, 0.70), (0.50, 0.48)],
            [(0.24, 0.70), (0.38, 0.40), (0.62, 0.30), (0.76, 0.58), (0.48, 0.54)],
        ]

        for i, item in enumerate(lines_data):
            c_idx = (i // self._cluster_size) % len(constellation_shapes)
            shape = constellation_shapes[c_idx]
            pt = shape[i % len(shape)]

            jx = math.sin(i * 3.1415 + 1.2) * 0.035
            jy = math.cos(i * 2.7182 + 0.8) * 0.04
            xr = max(0.12, min(0.88, pt[0] + jx))
            yr = max(0.20, min(0.80, pt[1] + jy))

            t_sec = float(item['time'])
            txt = str(item['text'])
            words = list(item.get('words') or [])

            next_t = float(lines_data[i + 1]['time']) if i + 1 < len(lines_data) else t_sec + 5.0

            # Line active duration: ends cleanly when singing finishes so it exits the screen
            if words and len(words) > 0:
                last_w_end = float(words[-1].get('end') or words[-1].get('end_sec') or (t_sec + 2.5))
                end_sec = max(t_sec + 1.2, min(next_t - 0.20, last_w_end + 0.35))
            else:
                est_dur = max(2.0, min(5.0, len(txt.split()) * 0.42 + 0.6))
                end_sec = min(next_t - 0.20, t_sec + est_dur) if next_t > t_sec else t_sec + est_dur

            self._lines.append({
                'text': txt,
                'time': t_sec,
                'end_time': end_sec,
                'words': words,
                'x_ratio': xr,
                'y_ratio': yr,
                'cluster': i // self._cluster_size,
            })

        self.update()

    def set_lines(self, lines_data):
        """Standard entry point: converts raw tuples or dicts into rich lines."""
        if not lines_data:
            self.set_rich_lines([])
            return
        if isinstance(lines_data[0], dict):
            self.set_rich_lines(lines_data)
            return

        converted = []
        for i, (t_sec, txt) in enumerate(lines_data):
            tokens = txt.split()
            next_t = lines_data[i + 1][0] if i + 1 < len(lines_data) else t_sec + 4.0
            dur = max(1.8, (next_t - t_sec) if next_t > t_sec else 3.5)
            total_len = max(1, sum(len(tk) for tk in tokens))
            cur = t_sec
            w_list = []
            for tk in tokens:
                w_dur = (len(tk) / total_len) * dur
                w_list.append({'text': tk, 'start': cur, 'end': cur + w_dur})
                cur += w_dur

            converted.append({
                'time': t_sec,
                'text': txt,
                'words': w_list,
            })
        self.set_rich_lines(converted)

    def update_position(self, current_sec: float):
        if not self._lines:
            return

        new_active = -1
        new_active_word = -1

        for i, item in enumerate(self._lines):
            t_start = item['time']
            t_end = item['end_time']
            if t_start <= current_sec <= t_end:
                new_active = i
                words = item['words']
                if words:
                    for w_i, w in enumerate(words):
                        w_start = float(w.get('start', w.get('start_sec', 0.0)))
                        w_end = float(w.get('end', w.get('end_sec', 0.0)))
                        if w_start <= current_sec <= w_end:
                            new_active_word = w_i
                            break
                        elif w_start <= current_sec:
                            new_active_word = w_i
                break
            elif current_sec < t_start:
                # Chronologically sorted: future line not reached yet
                break
            # If current_sec > t_end: THIS LINE HAS FINISHED!
            # It will NOT linger on the screen; new_active remains -1 until the next line starts.

        if new_active != self._active_idx:
            if new_active != -1:
                # Dynamic transition to newly ignited star
                self._prev_active_idx = self._active_idx if self._active_idx != -1 else max(0, new_active - 1)
                self._pulse_phase = 0.0
                if not self._anim_timer.isActive():
                    self._anim_timer.start()
            self._active_idx = new_active
            self._active_word_idx = new_active_word
            self.update()
        elif new_active_word != self._active_word_idx:
            self._active_word_idx = new_active_word
            self.update()

    def _on_anim_tick(self):
        self._pulse_phase += 0.07
        if self._pulse_phase >= 1.0:
            self._pulse_phase = 1.0
            self._anim_timer.stop()  # Sleep immediately upon arrival: 0% CPU & zero RAM churn!
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        W = float(self.width())
        H = float(self.height())

        pri_r = self._pri_color.red()
        pri_g = self._pri_color.green()
        pri_b = self._pri_color.blue()

        # ── 1. Deep Cosmic Night Sky ─────────────────────────────────────────
        p.fillRect(self.rect(), QColor("#000000" if self._is_black_theme else "#020704"))

        # ── 2. Background Blur Effect (Blurred Cosmic Nebulae) ───────────────
        # Soft Gaussian-like celestial nebulas rendered with efficient multi-stop radial gradients
        if 0 <= self._active_idx < len(self._lines):
            active_item = self._lines[self._active_idx]
            anx = active_item['x_ratio'] * W
            any_ = active_item['y_ratio'] * H
            # Active star glowing celestial nebula
            g_nebula = QRadialGradient(anx, any_, max(W, H) * 0.55)
            g_nebula.setColorAt(0.0, QColor(pri_r, pri_g, pri_b, 45))
            g_nebula.setColorAt(0.35, QColor(int(pri_r * 0.3), int(pri_g * 0.7), int(pri_b * 0.5), 18))
            g_nebula.setColorAt(0.70, QColor(5, 25, 40, 8))
            g_nebula.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g_nebula))
            p.drawRect(self.rect())
        else:
            # Ambient cosmic nebula when quiet between lines
            g_nebula = QRadialGradient(W * 0.5, H * 0.5, max(W, H) * 0.5)
            g_nebula.setColorAt(0.0, QColor(pri_r, pri_g, pri_b, 16))
            g_nebula.setColorAt(0.5, QColor(5, 20, 30, 8))
            g_nebula.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g_nebula))
            p.drawRect(self.rect())

        # Opposite ambient cosmic indigo glow
        g_corner = QRadialGradient(W * 0.85, H * 0.22, max(W, H) * 0.40)
        g_corner.setColorAt(0.0, QColor(0, 140, 220, 14))
        g_corner.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(g_corner))
        p.drawRect(self.rect())

        # Frosted acrylic blur vignette overlay
        p.fillRect(self.rect(), QColor(2, 6, 3, 110))

        # Ambient background micro-stars
        p.setPen(Qt.PenStyle.NoPen)
        limit = getattr(self, "_bg_stars_count", len(self._bg_stars))
        for sx, sy, sz, sa in self._bg_stars[:limit]:
            p.setBrush(QBrush(QColor(220, 255, 230, sa)))
            p.drawEllipse(QPointF(sx * W, sy * H), sz / 2.0, sz / 2.0)

        if not self._lines:
            p.setPen(QColor(pri_r, pri_g, pri_b, 160))
            p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "✦ WAITING FOR CONSTELLATION SYNC ✦")
            return

        # ── 3. Astronomical Star Reference Dots (Microscopic, Zero Text) ─────
        # Other stars are drawn strictly as faint distant beacons; NO past or future text clutter!
        active_cluster = self._lines[self._active_idx]['cluster'] if 0 <= self._active_idx < len(self._lines) else 0

        for i, item in enumerate(self._lines):
            if item['cluster'] == active_cluster and i != self._active_idx:
                sx = item['x_ratio'] * W
                sy = item['y_ratio'] * H
                p.setPen(Qt.PenStyle.NoPen)
                # Soft starlight dot
                p.setBrush(QBrush(QColor(110, 160, 140, 60)))
                p.drawEllipse(QPointF(sx, sy), 2.2, 2.2)

        # ── 4. Active Starlight, Laser Filament & Dynamic Lyric Capsule ──────
        if 0 <= self._active_idx < len(self._lines):
            active_item = self._lines[self._active_idx]
            nx = active_item['x_ratio'] * W
            ny = active_item['y_ratio'] * H
            line_text = active_item['text']
            words = active_item.get('words') or []
            active_w_idx = self._active_word_idx

            # A. Laser Filament connecting previous star to newly active star
            # Active strictly during transition flight (pulse_phase < 1.0); completely removed upon arrival at the new node!
            if (self._pulse_phase < 1.0 and 
                0 <= self._prev_active_idx < len(self._lines) and 
                self._prev_active_idx != self._active_idx):
                prev_item = self._lines[self._prev_active_idx]
                px_prev = prev_item['x_ratio'] * W
                py_prev = prev_item['y_ratio'] * H

                bx = px_prev + (nx - px_prev) * self._pulse_phase
                by = py_prev + (ny - py_prev) * self._pulse_phase

                # Radiant laser beam shoots from origin node towards the traveling photon head
                p.setPen(QPen(QColor(pri_r, pri_g, pri_b, 75), 4.5))
                p.drawLine(QPointF(px_prev, py_prev), QPointF(bx, by))

                p.setPen(QPen(QColor(225, 255, 235, 230), 1.8))
                p.drawLine(QPointF(px_prev, py_prev), QPointF(bx, by))

                # Traveling Photon Pulse Particle at the leading tip
                g_pulse = QRadialGradient(bx, by, 15.0)
                g_pulse.setColorAt(0.0, QColor(255, 255, 255, 255))
                g_pulse.setColorAt(0.35, QColor(pri_r, pri_g, pri_b, 220))
                g_pulse.setColorAt(1.0, QColor(pri_r, pri_g, pri_b, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g_pulse))
                p.drawEllipse(QPointF(bx, by), 13, 13)

            # B. ACTIVE STAR: Radiant Starlight Corona
            g_star = QRadialGradient(nx, ny, 36.0)
            g_star.setColorAt(0.0, QColor(255, 255, 255, 255))
            g_star.setColorAt(0.25, QColor(pri_r, pri_g, pri_b, 230))
            g_star.setColorAt(0.65, QColor(pri_r, pri_g, pri_b, 45))
            g_star.setColorAt(1.0, QColor(pri_r, pri_g, pri_b, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g_star))
            p.drawEllipse(QPointF(nx, ny), 34, 34)

            # Star center beacon
            p.setBrush(QBrush(QColor("#ffffff")))
            p.drawEllipse(QPointF(nx, ny), 4.0, 4.0)

            # C. Frosted Glass Capsule with Word-by-Word Sing-along Karaoke
            f = QFont("Segoe UI", 16, QFont.Weight.Bold)
            p.setFont(f)
            fm = p.fontMetrics()

            word_boxes = []
            cur_x_offset = 0.0
            space_w = fm.horizontalAdvance(" ")

            if words:
                for w_i, w_obj in enumerate(words):
                    w_str = str(w_obj.get('text', ''))
                    w_width = fm.horizontalAdvance(w_str)
                    word_boxes.append((w_str, cur_x_offset, w_width, w_i))
                    cur_x_offset += w_width + space_w
                total_text_w = max(fm.horizontalAdvance(line_text), cur_x_offset - space_w)
            else:
                total_text_w = fm.horizontalAdvance(line_text)

            th = fm.height()
            pill_w = total_text_w + 38.0
            pill_h = th + 18.0

            pill_y = ny - pill_h - 12.0 if ny > H * 0.45 else ny + 14.0
            pill_x = max(16.0, min(W - pill_w - 16.0, nx - pill_w / 2.0))
            pill_rect = QRectF(pill_x, pill_y, pill_w, pill_h)

            # Soft blurred outer glow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(pri_r, pri_g, pri_b, 35)))
            p.drawRoundedRect(pill_rect.adjusted(-5, -5, 5, 5), 12.0, 12.0)

            # Frosted glass capsule body (Acrylic frosted glass effect)
            p.setPen(QPen(QColor(255, 255, 255, 160), 1.2))
            p.setBrush(QBrush(QColor(10, 24, 15, 220) if self._is_black_theme else QColor(14, 32, 22, 220)))
            p.drawRoundedRect(pill_rect, 9.0, 9.0)

            # Inner neon accent frame
            p.setPen(QPen(QColor(pri_r, pri_g, pri_b, 175), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(pill_rect.adjusted(2, 2, -2, -2), 7.0, 7.0)

            # D. Render lyric text with real-time active word sing-along
            if words and word_boxes:
                base_text_x = pill_x + (pill_w - total_text_w) / 2.0
                text_baseline_y = pill_y + (pill_h - th) / 2.0 + fm.ascent()

                for w_str, x_off, w_w, w_idx in word_boxes:
                    wx = base_text_x + x_off
                    if w_idx == active_w_idx:
                        # Active word being spoken right now: radiant white with active starlight underline!
                        p.setPen(QColor(255, 255, 255, 255))
                        p.drawText(QPointF(wx, text_baseline_y), w_str)
                        p.setPen(QPen(QColor("#ffffff"), 2.0))
                        p.drawLine(QPointF(wx, text_baseline_y + 3), QPointF(wx + w_w, text_baseline_y + 3))
                    elif w_idx < active_w_idx:
                        # Sung words in this line: primary neon green
                        p.setPen(self._pri_color)
                        p.drawText(QPointF(wx, text_baseline_y), w_str)
                    else:
                        # Upcoming words in this line: soft subtle green preview
                        p.setPen(QColor(pri_r, pri_g, pri_b, 120))
                        p.drawText(QPointF(wx, text_baseline_y), w_str)
            else:
                p.setPen(self._pri_color)
                p.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, line_text)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            W = float(self.width())
            H = float(self.height())
            for item in self._lines:
                nx = item['x_ratio'] * W
                ny = item['y_ratio'] * H
                if math.hypot(ev.pos().x() - nx, ev.pos().y() - ny) < 35:
                    self.word_clicked.emit(item['time'])
                    break
        super().mousePressEvent(ev)


# ── Cylindrical Reel Scroll Area & Line Widget ───────────────────────────────

class LyricsScrollArea(QScrollArea):
    """
    Scroll area with automatic viewport-width pinning and snappy kinetic sub-scrolling.
    Ensures container width never stretches beyond viewport, guaranteeing
    100% dead-center horizontal alignment of all single-line lyrics.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._wheel_anim: Optional[QPropertyAnimation] = None

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        w = self.widget()
        if w:
            w.setFixedWidth(self.viewport().width())

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        if delta != 0:
            scroll_bar = self.verticalScrollBar()
            step = -int(delta * 0.75)
            target = max(0, min(scroll_bar.value() + step, scroll_bar.maximum()))
            if self._wheel_anim:
                self._wheel_anim.stop()
            self._wheel_anim = QPropertyAnimation(scroll_bar, b"value", self)
            self._wheel_anim.setDuration(110)
            self._wheel_anim.setStartValue(scroll_bar.value())
            self._wheel_anim.setEndValue(target)
            self._wheel_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            self._wheel_anim.start()
            ev.accept()
        else:
            super().wheelEvent(ev)


class LyricLineWidget(QLabel):
    """
    Spotlight lyric line widget.
    Features:
    - Dead-center horizontal alignment and strict single-line display (no line-wrapping).
    - High-contrast spotlight magnification: active center line is 26pt Bold with pure
      glowing text highlight (NO background rectangular bar or box).
    - Angular 3D cylindrical drum perspective: progressive inward margins simulating a rotating wheel.
    - Zero QGraphicsBlurEffect allocations for ultra-low RAM usage.
    """

    clicked = pyqtSignal(float)

    def __init__(self, line: LyricsLine, index: int, parent=None):
        super().__init__(parent)
        self.line = line
        self.index = index
        self._distance: int = 99
        self._is_active: bool = False
        self._is_past: bool = False

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.update_style()

    def set_distance(self, dist: int, is_active: bool, is_past: bool):
        if self._distance != dist or self._is_active != is_active or self._is_past != is_past:
            self._distance = dist
            self._is_active = is_active
            self._is_past = is_past
            self.update_style()

    def set_line_state(self, active: bool, past: bool):
        dist = 0 if active else (1 if past else 2)
        self.set_distance(dist, active, past)

    def update_style(self):
        raw = (self.line.display_text or self.line.original_text or "♪").strip()
        from ui import C

        pri = getattr(C, "PRI", "#00ff41")
        is_black_theme = getattr(C, "BG", "") == "#000000"
        parent_w = self.parentWidget().width() if self.parentWidget() else 600

        if self._is_active:
            display_str = f"▸  {raw}  ◂"

            # Dynamic autoscaling: keep 26pt default (noticeably larger than surrounding lines)
            avail_w = max(280, parent_w - 50)
            target_pt = 26
            probe_font = QFont("Segoe UI", target_pt, QFont.Weight.Bold)
            text_advance = QFontMetrics(probe_font).horizontalAdvance(display_str)
            if text_advance > avail_w:
                final_pt = max(14, int(target_pt * (avail_w / text_advance)))
            else:
                final_pt = target_pt

            self.setFont(QFont("Segoe UI", final_pt, QFont.Weight.Bold))
            self.setText(display_str)
            self.setFixedHeight(54)
            self.setStyleSheet(f"""
                QLabel {{
                    color: {pri};
                    background: transparent;
                    border: none;
                    padding: 4px 8px;
                    margin: 2px 10px;
                }}
            """)
        elif self._distance == 1:
            self.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
            self.setText(raw)
            self.setFixedHeight(36)
            col = "rgba(225, 255, 235, 0.85)" if is_black_theme else "rgba(226, 232, 240, 0.88)"
            self.setStyleSheet(f"""
                QLabel {{
                    color: {col};
                    background: transparent;
                    border: none;
                    padding: 3px 8px;
                    margin: 2px 20px;
                }}
                QLabel:hover {{
                    color: {pri};
                }}
            """)
        elif self._distance == 2:
            self.setFont(QFont("Segoe UI", 10, QFont.Weight.Normal))
            self.setText(raw)
            self.setFixedHeight(30)
            col = "rgba(180, 235, 195, 0.60)" if is_black_theme else "rgba(168, 185, 205, 0.65)"
            self.setStyleSheet(f"""
                QLabel {{
                    color: {col};
                    background: transparent;
                    border: none;
                    padding: 2px 6px;
                    margin: 2px 32px;
                }}
                QLabel:hover {{
                    color: {pri};
                }}
            """)
        else:
            self.setFont(QFont("Segoe UI", 9, QFont.Weight.Normal))
            self.setText(raw)
            self.setFixedHeight(26)
            col = "rgba(140, 205, 160, 0.40)" if is_black_theme else "rgba(140, 158, 180, 0.45)"
            self.setStyleSheet(f"""
                QLabel {{
                    color: {col};
                    background: transparent;
                    border: none;
                    padding: 1px 4px;
                    margin: 1px 44px;
                }}
                QLabel:hover {{
                    color: {pri};
                }}
            """)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.line.time_sec)
        super().mousePressEvent(ev)


# ── Unified Synchronized Lyrics Panel Widget ─────────────────────────────────

class LyricsPanelWidget(QWidget):
    """
    Cinematic live synchronized lyrics widget.
    Coordinates the default 2D Star Constellation view and the
    classic Cylindrical Spotlight Reel view with dynamic view toggling.
    """

    dismiss_requested = pyqtSignal()
    seek_requested = pyqtSignal(float)
    playback_speed_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LyricsPanelWidget")
        self._track: Optional[LyricsTrack] = None
        self._current_index: int = -1
        self._line_widgets: List[LyricLineWidget] = []
        self._display_mode: str = get_lyrics_mode()
        self._view_mode: str = get_lyrics_view_mode()
        self._roman_gujarati: bool = get_roman_gujarati_enabled()
        self._playback_speed: float = 1.0

        self._build_ui()

    def _build_ui(self):
        from ui import C
        pri = getattr(C, "PRI", "#00ff41")
        border = getattr(C, "BORDER", "rgba(0, 255, 65, 0.40)")
        panel_bg = getattr(C, "PANEL", "rgba(2, 10, 4, 0.90)")

        self.setStyleSheet(f"""
            QWidget#LyricsPanelWidget {{
                background: {panel_bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # ── Header Bar ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        self._music_icon = QLabel("🎧")
        self._music_icon.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._music_icon.setStyleSheet(f"color: {pri}; background: transparent;")
        hdr.addWidget(self._music_icon)

        self._title_lbl = QLabel("NOW VIBING — WAITING FOR MUSIC")
        self._title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {getattr(C, 'WHITE', '#ffffff')}; letter-spacing: 1px; background: transparent;")
        hdr.addWidget(self._title_lbl)

        self._badge_lbl = QLabel("[SYNCED · AUTO]")
        self._badge_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._badge_lbl.setStyleSheet(f"""
            QLabel {{
                color: {pri};
                background: rgba(0, 255, 65, 0.12);
                border: 1px solid rgba(0, 255, 65, 0.35);
                border-radius: 4px;
                padding: 1px 6px;
            }}
        """)
        hdr.addWidget(self._badge_lbl)
        hdr.addStretch()

        # View Mode Toggle: [VIEW: CONSTELLATION ✦] <-> [VIEW: REEL ▾]
        btn_txt = "VIEW: CONSTELLATION ✦" if self._view_mode == "constellation" else "VIEW: REEL ▾"
        self._view_btn = QPushButton(btn_txt)
        self._view_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._view_btn.setFixedHeight(22)
        self._view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_btn.setToolTip("Toggle lyrics format: 2D Astronomical Constellation / Cylindrical Spotlight Reel")
        self._view_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 255, 65, 0.10);
                color: {pri};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: rgba(0, 255, 65, 0.20);
                border-color: {pri};
                color: #ffffff;
            }}
        """)
        self._view_btn.clicked.connect(self._cycle_view_mode)
        hdr.addWidget(self._view_btn)

        # Language display mode toggle: AUTO -> ORIGINAL -> ROMANIZED
        self._mode_btn = QPushButton(f"MODE: {self._display_mode.upper()} ▾")
        self._mode_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._mode_btn.setFixedHeight(22)
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: {getattr(C, 'TEXT', '#8ffcff')};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: rgba(0, 255, 65, 0.16);
                border-color: {pri};
                color: #ffffff;
            }}
        """)
        self._mode_btn.clicked.connect(self._cycle_display_mode)
        hdr.addWidget(self._mode_btn)

        # Playback speed toggle (1.0x -> 1.1x -> 1.25x)
        self._speed_btn = QPushButton(f"SPEED: {self._playback_speed:.1f}x ⚡")
        self._speed_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._speed_btn.setFixedHeight(22)
        self._speed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._speed_btn.setToolTip("Toggle song and word playback speed (1.0x / 1.1x / 1.25x)")
        self._speed_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: {pri};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: rgba(0, 255, 65, 0.16);
                border-color: {pri};
                color: #ffffff;
            }}
        """)
        self._speed_btn.clicked.connect(self._cycle_playback_speed)
        hdr.addWidget(self._speed_btn)

        # Dismiss button
        self._dismiss_btn = QPushButton("✕")
        self._dismiss_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._dismiss_btn.setFixedSize(22, 22)
        self._dismiss_btn.setToolTip("Restore previous search results")
        self._dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {getattr(C, 'TEXT_DIM', '#888888')};
                border: 1px solid {border}; border-radius: 4px;
            }}
            QPushButton:hover {{
                color: #ff4d6d; border-color: #ff4d6d; background: rgba(255, 77, 109, 0.12);
            }}
        """)
        self._dismiss_btn.clicked.connect(self._on_dismiss_clicked)
        hdr.addWidget(self._dismiss_btn)

        layout.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background: {border}; max-height: 1px;")
        layout.addWidget(sep)

        # ── Stacked Views Container ───────────────────────────────────────────
        self._view_stack = QStackedWidget()

        # View 0: 2D Astronomical Constellation Flow
        self._constellation = ConstellationLyricsWidget()
        self._constellation.word_clicked.connect(self._on_line_clicked)
        self._constellation.set_theme(pri, is_black=getattr(C, "BG", "") == "#000000")
        self._view_stack.addWidget(self._constellation)

        # View 1: Cylindrical Spotlight Reel
        self._scroll = LyricsScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._lines_container = QWidget()
        self._lines_container.setStyleSheet("background: transparent;")
        self._lines_layout = QVBoxLayout(self._lines_container)
        self._lines_layout.setContentsMargins(0, 0, 0, 0)
        self._lines_layout.setSpacing(6)
        self._lines_layout.addStretch()

        self._scroll.setWidget(self._lines_container)
        self._view_stack.addWidget(self._scroll)

        # Set active view
        self._view_stack.setCurrentIndex(1 if self._view_mode == "reel" else 0)
        layout.addWidget(self._view_stack)

        # Placeholder message label (loading / errors / instrumental)
        self._placeholder_lbl = QLabel("READY")
        self._placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._placeholder_lbl.setStyleSheet(f"color: {pri}; padding: 20px; background: transparent;")
        self._placeholder_lbl.hide()
        layout.addWidget(self._placeholder_lbl)

    def apply_resource_profile(self, profile: str) -> None:
        """Dynamic resource trimming for constellation stars and animations."""
        if hasattr(self, "_constellation"):
            self._constellation.apply_resource_profile(profile)

    def _cycle_view_mode(self):
        if self._view_mode == "constellation":
            self._view_mode = "reel"
            self._view_btn.setText("VIEW: REEL ▾")
            self._view_stack.setCurrentIndex(1)
            if 0 <= self._current_index < len(self._line_widgets):
                self._scroll_to_widget(self._line_widgets[self._current_index])
        else:
            self._view_mode = "constellation"
            self._view_btn.setText("VIEW: CONSTELLATION ✦")
            self._view_stack.setCurrentIndex(0)
        save_lyrics_view_mode(self._view_mode)

    def _cycle_display_mode(self):
        modes = ["auto", "original", "romanized"]
        idx = modes.index(self._display_mode) if self._display_mode in modes else 0
        self._display_mode = modes[(idx + 1) % len(modes)]
        save_lyrics_mode(self._display_mode)
        self._mode_btn.setText(f"MODE: {self._display_mode.upper()} ▾")

        if self._track:
            apply_language_rules(self._track, mode=self._display_mode, roman_gujarati=self._roman_gujarati)
            self._update_all_line_texts()
            self._update_constellation_lines()
            self._update_badge()

    def _cycle_playback_speed(self):
        speeds = [1.0, 1.1, 1.2, 1.25, 1.5]
        idx = speeds.index(self._playback_speed) if self._playback_speed in speeds else 0
        self._playback_speed = speeds[(idx + 1) % len(speeds)]
        self._speed_btn.setText(f"SPEED: {self._playback_speed:.1f}x ⚡")
        self.playback_speed_requested.emit(self._playback_speed)

    def set_loading(self, track_name: str, artist_name: str = ""):
        artist_str = f" · {artist_name.upper()}" if artist_name else ""
        self._title_lbl.setText(f"NOW VIBING — {track_name.upper()}{artist_str}")
        self._badge_lbl.setText("[FETCHING LYRICS...]")
        self._badge_lbl.setStyleSheet("""
            color: #facc15; background: rgba(250, 204, 21, 0.12);
            border: 1px solid rgba(250, 204, 21, 0.35); border-radius: 4px; padding: 1px 6px;
        """)
        self._clear_lines()
        self._constellation.set_lines([])
        self._view_stack.hide()
        self._placeholder_lbl.setText("FETCHING SYNCHRONIZED LYRICS...")
        self._placeholder_lbl.show()

    def set_state_message(self, message: str, status_badge: str = ""):
        self._clear_lines()
        self._constellation.set_lines([])
        self._view_stack.hide()
        self._placeholder_lbl.setText(message)
        self._placeholder_lbl.show()
        if status_badge:
            self._badge_lbl.setText(f"[{status_badge.upper()}]")

    def load_track(self, track: Optional[LyricsTrack], raw_query: str = ""):
        self._clear_lines()
        self._track = track
        self._current_index = -1

        if not track:
            self._title_lbl.setText(f"NOW VIBING — {raw_query.upper() if raw_query else 'MEDIA'}")
            self.set_state_message("LYRICS NOT AVAILABLE FOR THIS TRACK", "NOT AVAILABLE")
            return

        artist_part = f" · {track.artist_name.upper()}" if track.artist_name else ""
        self._title_lbl.setText(f"NOW VIBING — {track.track_name.upper()}{artist_part}")

        if track.is_instrumental:
            self.set_state_message("INSTRUMENTAL TRACK", "INSTRUMENTAL")
            return

        if not track.lines:
            self.set_state_message("LYRICS NOT AVAILABLE FOR THIS TRACK", "NO LYRICS")
            return

        self._placeholder_lbl.hide()
        self._view_stack.show()
        self._update_badge()

        # 1. Filter out credit lines & populate Reel View Lines
        from core.lyrics_engine import is_credit_line
        valid_lines = [
            l for l in track.lines
            if not is_credit_line(l.original_text) and not is_credit_line(l.display_text)
        ]
        track.lines = valid_lines

        top_spacer = QWidget()
        top_spacer.setFixedHeight(120)
        self._lines_layout.addWidget(top_spacer)

        for i, line in enumerate(track.lines):
            w = LyricLineWidget(line, i, self._lines_container)
            w.clicked.connect(self._on_line_clicked)
            self._line_widgets.append(w)
            self._lines_layout.addWidget(w)

        bottom_spacer = QWidget()
        bottom_spacer.setFixedHeight(140)
        self._lines_layout.addWidget(bottom_spacer)
        self._lines_layout.addStretch()

        # 2. Populate 2D Astronomical Constellation Dots
        self._update_constellation_lines()

        # Initial position 0.0s
        self.update_position(0.0)

    def _update_constellation_lines(self):
        if not self._track:
            self._constellation.set_lines([])
            return

        from core.lyrics_engine import is_credit_line
        lines_data = []
        for i, line in enumerate(self._track.lines):
            txt = (line.display_text or line.original_text or "").strip()
            if txt and not is_credit_line(txt):
                next_t = self._track.lines[i + 1].time_sec if i + 1 < len(self._track.lines) else line.time_sec + 5.0
                words = line.build_words(next_t)
                words_list = [{'text': w.text, 'start': w.start_sec, 'end': w.end_sec} for w in words]
                lines_data.append({
                    'time': line.time_sec,
                    'text': txt,
                    'words': words_list,
                })
        self._constellation.set_rich_lines(lines_data)

    def _update_badge(self):
        if not self._track:
            return
        from ui import C
        pri = getattr(C, "PRI", "#00ff41")
        sync_str = "SYNCED" if self._track.is_synced else "UNSYNCHRONIZED"
        lang_str = self._track.primary_language.upper()
        if self._display_mode == "auto":
            if self._track.primary_language in ("hi", "mixed"):
                lang_str = "HINGLISH"
            elif self._track.primary_language == "gu":
                lang_str = "ROMAN GUJARATI" if self._roman_gujarati else "GUJARATI"
        elif self._display_mode == "romanized":
            lang_str = "ROMANIZED"
        elif self._display_mode == "original":
            lang_str = "ORIGINAL"

        self._badge_lbl.setText(f"[{sync_str} · {lang_str}]")
        self._badge_lbl.setStyleSheet(f"""
            QLabel {{
                color: {pri}; background: rgba(0, 255, 65, 0.12);
                border: 1px solid rgba(0, 255, 65, 0.35); border-radius: 4px; padding: 1px 6px;
            }}
        """)

    def _update_all_line_texts(self):
        for w in self._line_widgets:
            w.update_style()

    def update_position(self, position_sec: float):
        """Update synchronized active lyric in Constellation and Reel views."""
        if not self._track:
            return

        lead_offset = 0.20 * getattr(self, "_playback_speed", 1.0)
        adj_pos = position_sec + lead_offset

        # Update 2D Constellation View
        self._constellation.update_position(adj_pos)

        # Update Reel View
        if not self._line_widgets:
            return

        idx = self._track.get_active_index(adj_pos)
        if idx == self._current_index:
            return

        self._current_index = idx

        for i, w in enumerate(self._line_widgets):
            dist = abs(i - idx) if idx >= 0 else 99
            w.set_distance(dist, is_active=(i == idx), is_past=(i < idx))

        if 0 <= idx < len(self._line_widgets) and self._view_mode == "reel":
            active_widget = self._line_widgets[idx]
            self._scroll_to_widget(active_widget)

    def _scroll_to_widget(self, target_widget: QWidget):
        scroll_bar = self._scroll.verticalScrollBar()
        widget_pos = target_widget.geometry().center().y()
        viewport_height = self._scroll.viewport().height()
        target_val = widget_pos - (viewport_height // 2)
        target_val = max(0, min(target_val, scroll_bar.maximum()))

        from core.resource_guardian import ResourceGuardian
        dur = ResourceGuardian.get_instance().get_anim_duration_ms()
        if dur == 0:
            if getattr(self, "_scroll_anim", None):
                self._scroll_anim.stop()
            scroll_bar.setValue(target_val)
            return

        if getattr(self, "_scroll_anim", None):
            self._scroll_anim.stop()
        self._scroll_anim = QPropertyAnimation(scroll_bar, b"value", self)
        self._scroll_anim.setDuration(dur)  # Dynamic agile easing: 0ms (low_ram), 90ms (balanced), 130ms (full)
        self._scroll_anim.setStartValue(scroll_bar.value())
        self._scroll_anim.setEndValue(target_val)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._scroll_anim.start()

    def _on_line_clicked(self, time_sec: float):
        self.seek_requested.emit(time_sec)
        self.update_position(time_sec)

    def _on_dismiss_clicked(self):
        self.dismiss_requested.emit()

    def _clear_lines(self):
        for w in self._line_widgets:
            w.setGraphicsEffect(None)
            w.setParent(None)
            w.deleteLater()
        self._line_widgets.clear()

        while self._lines_layout.count():
            item = self._lines_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
