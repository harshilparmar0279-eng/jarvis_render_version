"""
ui_lyrics_panel.py — Spotify-Inspired Real-Time Multilingual Synchronized Lyrics Widget.

Features:
- Dark translucent glassmorphism surface with subtle glow and thin gold/cyan borders.
- Smooth automatic vertical scrolling keeping the active lyric comfortably centered.
- Active line highlighted in bright cyan (#00e5ff) / near-white (#ffffff) with luminous glow.
- Faded previous lines and subdued upcoming lines.
- Responsively displays 3–7 lines.
- Header with track info, artist, sync status, and detected language/script badge.
- Interactive display mode toggle: [AUTO], [ORIGINAL], [ROMANIZED].
- Dismiss button that restores previous search content.
"""

from __future__ import annotations

import re
from typing import Optional, List
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QRect
from PyQt6.QtGui import QFont, QColor, QPainter, QLinearGradient, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy
)

from theme import ThemeColors as C
from core.lyrics_engine import LyricsTrack, LyricsLine, apply_language_rules
from memory.config_manager import get_lyrics_mode, save_lyrics_mode, get_roman_gujarati_enabled


class LyricLineWidget(QLabel):
    """Individual line widget with opacity, font, and glow handling."""

    clicked = pyqtSignal(float)  # emitted when user clicks line to jump/seek

    def __init__(self, line: LyricsLine, index: int, parent=None):
        super().__init__(parent)
        self.line = line
        self.index = index
        self._is_active = False
        self._is_past = False
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 11, QFont.Weight.Normal))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.update_style()

    def set_line_state(self, active: bool, past: bool):
        if self._is_active != active or self._is_past != past:
            self._is_active = active
            self._is_past = past
            self.update_style()

    def update_style(self):
        txt = self.line.display_text or self.line.original_text or "♪"
        self.setText(txt)

        if self._is_active:
            self.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            self.setStyleSheet(f"""
                QLabel {{
                    color: #00e5ff;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(0, 229, 255, 0.16),
                        stop:0.6 rgba(0, 229, 255, 0.05),
                        stop:1 transparent);
                    border-left: 3px solid #00e5ff;
                    border-radius: 4px;
                    padding: 6px 12px;
                    margin: 2px 0px;
                }}
            """)
        elif self._is_past:
            self.setFont(QFont("Segoe UI", 10))
            self.setStyleSheet("""
                QLabel {{
                    color: rgba(148, 163, 184, 0.40);
                    background: transparent;
                    border-left: 3px solid transparent;
                    padding: 3px 12px;
                    margin: 1px 0px;
                }}
            """)
        else:
            self.setFont(QFont("Segoe UI", 11))
            self.setStyleSheet("""
                QLabel {{
                    color: rgba(203, 213, 225, 0.70);
                    background: transparent;
                    border-left: 3px solid transparent;
                    padding: 4px 12px;
                    margin: 1px 0px;
                }}
            """)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.line.time_sec)
        super().mousePressEvent(ev)


class LyricsPanelWidget(QWidget):
    """
    Spotify-inspired glassmorphism live synchronized lyrics view.
    Replaces bottom-center search panel when music is playing.
    """

    dismiss_requested = pyqtSignal()
    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LyricsPanelWidget")
        self._track: Optional[LyricsTrack] = None
        self._current_index: int = -1
        self._line_widgets: List[LyricLineWidget] = []
        self._display_mode: str = get_lyrics_mode()
        self._roman_gujarati: bool = get_roman_gujarati_enabled()

        self._build_ui()

    def _build_ui(self):
        # Glassmorphism container
        self.setStyleSheet(f"""
            QWidget#LyricsPanelWidget {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(10, 15, 26, 0.94),
                    stop:1 rgba(4, 7, 14, 0.97));
                border: 1px solid rgba(197, 160, 89, 0.38);
                border-radius: 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # ── Header bar ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        # Pulsing music icon
        self._music_icon = QLabel("♪")
        self._music_icon.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._music_icon.setStyleSheet("color: #00e5ff; background: transparent;")
        hdr.addWidget(self._music_icon)

        # Track title & artist
        self._title_lbl = QLabel("NOW PLAYING — WAITING FOR MUSIC")
        self._title_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.WHITE}; letter-spacing: 1px; background: transparent;")
        hdr.addWidget(self._title_lbl)

        # Status badge (e.g. [SYNCED · HINGLISH])
        self._badge_lbl = QLabel("[SYNCED · AUTO]")
        self._badge_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._badge_lbl.setStyleSheet("""
            QLabel {
                color: #00e5ff;
                background: rgba(0, 229, 255, 0.12);
                border: 1px solid rgba(0, 229, 255, 0.35);
                border-radius: 3px;
                padding: 1px 6px;
            }
        """)
        hdr.addWidget(self._badge_lbl)
        hdr.addStretch()

        # Display mode toggle button: AUTO -> ORIGINAL -> ROMANIZED
        self._mode_btn = QPushButton(f"MODE: {self._display_mode.upper()} ▾")
        self._mode_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._mode_btn.setFixedHeight(20)
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(197, 160, 89, 0.4);
                border-radius: 3px;
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: rgba(0, 229, 255, 0.15);
                border-color: #00e5ff;
                color: #ffffff;
            }}
        """)
        self._mode_btn.clicked.connect(self._cycle_display_mode)
        hdr.addWidget(self._mode_btn)

        # Dismiss / Restore Search button
        self._dismiss_btn = QPushButton("RESTORE SEARCH  ✕")
        self._dismiss_btn.setFont(QFont("Courier New", 7))
        self._dismiss_btn.setFixedHeight(20)
        self._dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 0 7px;
            }}
            QPushButton:hover {{
                color: {C.TEXT}; border-color: {C.BORDER_B}; background: rgba(255,255,255,0.06);
            }}
        """)
        self._dismiss_btn.clicked.connect(self._on_dismiss_clicked)
        hdr.addWidget(self._dismiss_btn)

        layout.addLayout(hdr)

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: rgba(197, 160, 89, 0.25); max-height: 1px;")
        layout.addWidget(sep)

        # ── Scrollable Lyrics Container ───────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: rgba(0, 0, 0, 0.2); width: 5px; border: none; border-radius: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0, 229, 255, 0.35); border-radius: 2px; min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(0, 229, 255, 0.7);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)

        self._lines_container = QWidget()
        self._lines_container.setStyleSheet("background: transparent;")
        self._lines_layout = QVBoxLayout(self._lines_container)
        self._lines_layout.setContentsMargins(0, 10, 0, 10)
        self._lines_layout.setSpacing(4)
        self._lines_layout.addStretch()

        self._scroll.setWidget(self._lines_container)
        layout.addWidget(self._scroll)

        # Placeholder message label (loading / errors / instrumental)
        self._placeholder_lbl = QLabel("READY")
        self._placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._placeholder_lbl.setStyleSheet("color: #00e5ff; padding: 20px; background: transparent;")
        self._placeholder_lbl.hide()
        layout.addWidget(self._placeholder_lbl)

    def _cycle_display_mode(self):
        """Cycles display mode: auto -> original -> romanized."""
        modes = ["auto", "original", "romanized"]
        idx = modes.index(self._display_mode) if self._display_mode in modes else 0
        self._display_mode = modes[(idx + 1) % len(modes)]
        save_lyrics_mode(self._display_mode)
        self._mode_btn.setText(f"MODE: {self._display_mode.upper()} ▾")

        if self._track:
            apply_language_rules(self._track, mode=self._display_mode, roman_gujarati=self._roman_gujarati)
            self._update_all_line_texts()
            self._update_badge()

    def set_loading(self, track_name: str, artist_name: str = ""):
        """Display loading state while lyrics are being fetched."""
        artist_str = f" · {artist_name.upper()}" if artist_name else ""
        self._title_lbl.setText(f"♪ NOW PLAYING — {track_name.upper()}{artist_str}")
        self._badge_lbl.setText("[FETCHING LYRICS...]")
        self._badge_lbl.setStyleSheet("""
            color: #facc15; background: rgba(250, 204, 21, 0.12);
            border: 1px solid rgba(250, 204, 21, 0.35); border-radius: 3px; padding: 1px 6px;
        """)
        self._clear_lines()
        self._placeholder_lbl.setText("FETCHING SYNCHRONIZED LYRICS...")
        self._placeholder_lbl.show()

    def set_state_message(self, message: str, status_badge: str = ""):
        """Set fallback state message (e.g. INSTRUMENTAL, LYRICS NOT AVAILABLE)."""
        self._clear_lines()
        self._placeholder_lbl.setText(message)
        self._placeholder_lbl.show()
        if status_badge:
            self._badge_lbl.setText(f"[{status_badge.upper()}]")

    def load_track(self, track: Optional[LyricsTrack], raw_query: str = ""):
        """Loads and displays a LyricsTrack."""
        self._clear_lines()
        self._track = track
        self._current_index = -1

        if not track:
            self._title_lbl.setText(f"♪ NOW PLAYING — {raw_query.upper() if raw_query else 'MEDIA'}")
            self.set_state_message("LYRICS NOT AVAILABLE", "NOT AVAILABLE")
            return

        artist_part = f" · {track.artist_name.upper()}" if track.artist_name else ""
        self._title_lbl.setText(f"♪ NOW PLAYING — {track.track_name.upper()}{artist_part}")

        if track.is_instrumental:
            self.set_state_message("INSTRUMENTAL TRACK", "INSTRUMENTAL")
            return

        if not track.lines:
            self.set_state_message("LYRICS NOT AVAILABLE", "NO LYRICS")
            return

        self._placeholder_lbl.hide()
        self._update_badge()

        # Build lyric line widgets
        # Add top spacer
        top_spacer = QWidget()
        top_spacer.setFixedHeight(30)
        self._lines_layout.addWidget(top_spacer)

        for i, line in enumerate(track.lines):
            w = LyricLineWidget(line, i, self._lines_container)
            w.clicked.connect(self._on_line_clicked)
            self._line_widgets.append(w)
            self._lines_layout.addWidget(w)

        # Add bottom spacer for comfortable vertical scrolling
        bottom_spacer = QWidget()
        bottom_spacer.setFixedHeight(60)
        self._lines_layout.addWidget(bottom_spacer)

        self._lines_layout.addStretch()

        # Initial position 0.0s
        self.update_position(0.0)

    def _update_badge(self):
        if not self._track:
            return
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
        self._badge_lbl.setStyleSheet("""
            QLabel {
                color: #00e5ff; background: rgba(0, 229, 255, 0.12);
                border: 1px solid rgba(0, 229, 255, 0.35); border-radius: 3px; padding: 1px 6px;
            }
        """)

    def _update_all_line_texts(self):
        for w in self._line_widgets:
            w.update_style()

    def update_position(self, position_sec: float):
        """Update synchronized active lyric line based on playback timestamp."""
        if not self._track or not self._line_widgets:
            return

        idx = self._track.get_active_index(position_sec)
        if idx == self._current_index:
            return

        self._current_index = idx

        for i, w in enumerate(self._line_widgets):
            is_active = (i == idx)
            is_past = (i < idx)
            w.set_line_state(is_active, is_past)

        # Smooth scroll to keep active line centered
        if 0 <= idx < len(self._line_widgets):
            active_widget = self._line_widgets[idx]
            self._scroll_to_widget(active_widget)

    def _scroll_to_widget(self, target_widget: QWidget):
        """Smoothly scrolls the area so target_widget is vertically centered."""
        scroll_bar = self._scroll.verticalScrollBar()
        widget_pos = target_widget.geometry().center().y()
        viewport_height = self._scroll.viewport().height()
        target_val = widget_pos - (viewport_height // 2)

        # Clamp target
        target_val = max(0, min(target_val, scroll_bar.maximum()))

        # Smooth animation
        anim = QPropertyAnimation(scroll_bar, b"value", self)
        anim.setDuration(280)
        anim.setStartValue(scroll_bar.value())
        anim.setEndValue(target_val)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()

    def _on_line_clicked(self, time_sec: float):
        self.seek_requested.emit(time_sec)
        self.update_position(time_sec)

    def _on_dismiss_clicked(self):
        self.dismiss_requested.emit()

    def _clear_lines(self):
        for w in self._line_widgets:
            w.setParent(None)
            w.deleteLater()
        self._line_widgets.clear()

        # Remove spacers
        while self._lines_layout.count():
            item = self._lines_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
