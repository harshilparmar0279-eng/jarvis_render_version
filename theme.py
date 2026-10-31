"""theme.py - Holographic Brass and Deep Ocean Theme for JARVIS Desktop Assistant.

All color tokens, CSS variables, and glassmorphism styling presets are defined here
as the single source of truth for the entire application.
Strictly NO purple used anywhere.
"""

from __future__ import annotations

# ==============================================================================
# CSS VARIABLES BLOCK (Web / Qt StyleSheet Variable Standard)
# ==============================================================================
CSS_VARIABLES = """
:root {
    /* Deep Ocean Backgrounds */
    --bg-ocean-deep:        #020b14;
    --bg-ocean-panel:       rgba(4, 18, 30, 0.82);
    --bg-ocean-panel2:      rgba(6, 24, 40, 0.85);
    --bg-ocean-glass:       rgba(3, 14, 24, 0.88);
    --bg-ocean-card:        rgba(5, 20, 34, 0.75);

    /* Holographic Brass & Gold Accents */
    --brass-gold:           #d4af37;
    --brass-bright:         #f0c544;
    --brass-light:          #fae07a;
    --brass-dim:            #8c7324;
    --brass-glow:           rgba(212, 175, 55, 0.35);
    --brass-ghost:          rgba(212, 175, 55, 0.12);

    /* Warm Amber Highlights */
    --amber-warm:           #ffaa22;
    --amber-glow:           rgba(255, 170, 34, 0.35);
    --amber-ghost:          rgba(255, 170, 34, 0.12);

    /* Holographic Cyan & Teal Glows */
    --teal-cyan:            #00e5ff;
    --teal-bright:          #68f4ff;
    --teal-dim:             #0088aa;
    --teal-glow:            rgba(0, 229, 255, 0.35);
    --teal-ghost:           rgba(0, 229, 255, 0.12);

    /* Frosted Glass Borders */
    --glass-border:         rgba(212, 175, 55, 0.38);
    --glass-border-bright:  rgba(240, 197, 68, 0.65);
    --glass-border-teal:    rgba(0, 229, 255, 0.35);

    /* Monospace Typography & Logs */
    --text-cyan:            #8ffcff;
    --text-med:             #6ab8cc;
    --text-dim:             #4a7d90;
    --text-white:           #e8faff;
    --text-amber:           #ffaa22;
    --text-red:             #ff4d6d;

    /* Status Indicators */
    --status-listening:     #00ffaa;
    --status-speaking:      #ffaa22;
    --status-thinking:      #f0c544;
    --status-muted:         #ff4d6d;
}
"""


# ==============================================================================
# PYTHON THEME CONSTANTS (Directly consumed by QPainter & Qt Widgets)
# ==============================================================================
class ThemeColors:
    # Deep Ocean Bases
    BG            = "#020b14"           # Dark navy-blue background
    BG_DEEP       = "#01070e"
    PANEL         = "rgba(4, 18, 30, 0.82)"   # Frosted glass panel
    PANEL_SOLID   = "#04121e"
    PANEL2        = "rgba(6, 24, 40, 0.85)"   # Slightly elevated panel
    PANEL2_SOLID  = "#061828"
    DARK          = "#020912"
    BAR_BG        = "#031626"

    # Thin Brass & Gold Borders
    BORDER        = "rgba(212, 175, 55, 0.38)"  # Standard brass border
    BORDER_SOLID  = "#3a321a"
    BORDER_B      = "rgba(240, 197, 68, 0.65)"  # Bright brass border
    BORDER_A      = "rgba(0, 229, 255, 0.38)"   # Teal glow border

    # Primary Holographic Cyan / Teal
    PRI           = "#00e5ff"           # Holographic cyan/teal glow
    PRI_DIM       = "#0088aa"
    PRI_GHO       = "rgba(0, 229, 255, 0.12)"

    # Warm Brass & Gold
    BRASS         = "#d4af37"           # Warm brass / classic gold
    BRASS_BRIGHT  = "#f0c544"           # Brilliant brass
    BRASS_GHO     = "rgba(212, 175, 55, 0.15)"

    # Warm Amber
    ACC           = "#ffaa22"           # Warm amber highlight
    ACC2          = "#f0c544"           # Gold accent
    ACC_GHO       = "rgba(255, 170, 34, 0.15)"

    # System Status Colors
    GREEN         = "#00ffaa"           # Glowing teal-green (Listening)
    GREEN_D       = "#00aa77"
    RED           = "#ff4d6d"           # Soft error red (no purple!)
    MUTED_C       = "#ff4d6d"

    # Typography Colors
    TEXT          = "#8ffcff"           # Crisp cyan monospace
    TEXT_DIM      = "#4a7d90"           # Dim oceanic label
    TEXT_MED      = "#6ab8cc"           # Medium text
    WHITE         = "#e8faff"           # Highlighted white-cyan


# ==============================================================================
# THEME PRESETS (Strictly NO purple anywhere)
# ==============================================================================
THEME_PRESETS = [
    ("✦ BRASS GOLD",   "#d4af37"),   # Classic warm brass
    ("◈ OCEAN TEAL",   "#00e5ff"),   # Deep ocean cyan/teal glow
    ("★ WARM AMBER",   "#ffaa22"),   # Warm amber radiance
    ("⚡ CYBER BRASS",  "#f0c544"),   # High-voltage bright gold
    ("🛡 STEALTH",      "#8899aa"),   # Oceanic silver/grey
    ("🌊 DEEP BLUE",    "#00b4d8"),   # Radiant deep marine
    ("🟢 MATRIX GREEN", "#00ff41"),   # Hacker/terminal cyber green on pure black
]

HUD_PRESETS = [
    ("🧑 3D AVATAR",     "face"),
    ("◉ ARC REACTOR",   "core"),
]

LAYOUT_PRESETS = [
    ("⊞ TACTICAL (3-COL)", "tactical"),
    ("⊟ FOCUS (CENTERED)", "focus"),
]


# ==============================================================================
# REUSABLE FROSTED GLASS & TACTILE QSS STYLES
# ==============================================================================
GLASS_PANEL_STYLE = f"""
    background: {ThemeColors.PANEL};
    border: 1px solid {ThemeColors.BORDER};
    border-radius: 8px;
"""

TACTILE_BUTTON_STYLE = f"""
    QPushButton {{
        background: rgba(4, 18, 30, 0.85);
        color: {ThemeColors.TEXT};
        border: 1px solid {ThemeColors.BORDER};
        border-radius: 5px;
        padding: 4px 10px;
    }}
    QPushButton:hover {{
        background: {ThemeColors.BRASS_GHO};
        color: {ThemeColors.BRASS_BRIGHT};
        border: 1px solid {ThemeColors.BORDER_B};
    }}
    QPushButton:pressed {{
        background: rgba(212, 175, 55, 0.25);
        border: 1px solid {ThemeColors.BRASS_BRIGHT};
    }}
    QPushButton:checked {{
        background: {ThemeColors.BRASS_GHO};
        color: {ThemeColors.BRASS_BRIGHT};
        border: 1px solid {ThemeColors.BORDER_B};
    }}
"""

GLASS_INPUT_STYLE = f"""
    QLineEdit {{
        background: rgba(2, 11, 20, 0.85);
        color: {ThemeColors.TEXT};
        border: 1px solid {ThemeColors.BORDER};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QLineEdit:focus {{
        border: 1px solid {ThemeColors.PRI};
        background: rgba(2, 14, 26, 0.95);
    }}
"""
