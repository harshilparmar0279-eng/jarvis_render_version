"""
core/local_launcher.py — Dynamic Local System File & Application Launcher.

Scans Start Menu, Desktop, Downloads, Documents, and Program installation paths.
Uses fuzzy & alias matching to immediately launch applications or open files using os.startfile / subprocess.
"""
from __future__ import annotations

import difflib
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

_OS = platform.system()

# Common app aliases
APP_ALIASES = {
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "word": "winword",
    "ms word": "winword",
    "excel": "excel",
    "ms excel": "excel",
    "powerpoint": "powerpnt",
    "ms powerpoint": "powerpnt",
    "calculator": "calc",
    "notepad": "notepad",
    "terminal": "wt",
    "cmd": "cmd",
    "command prompt": "cmd",
    "file manager": "explorer",
    "file explorer": "explorer",
    "browser": "chrome",
    "google chrome": "chrome",
    "vlc": "vlc",
    "spotify": "spotify",
    "whatsapp": "whatsapp:",
    "whatsapp desktop": "whatsapp:",
    "wp": "whatsapp:",
    "wapp": "whatsapp:",
}


def get_search_roots() -> list[Path]:
    """Returns local system search directories on Windows."""
    roots = []
    if _OS != "Windows":
        return [Path.home()]

    user_home = Path.home()
    local_app_data = Path(os.environ.get("LOCALAPPDATA", user_home / "AppData" / "Local"))
    app_data = Path(os.environ.get("APPDATA", user_home / "AppData" / "Roaming"))
    program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))

    # 1. Desktop & Quick access
    roots.append(user_home / "Desktop")
    public_desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    if public_desktop.is_dir():
        roots.append(public_desktop)

    # 2. Start Menu Programs
    user_start = app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if user_start.is_dir():
        roots.append(user_start)
    common_start = program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if common_start.is_dir():
        roots.append(common_start)

    # 3. User Documents & Downloads
    roots.append(user_home / "Downloads")
    roots.append(user_home / "Documents")

    # 4. Local App Data Programs
    local_programs = local_app_data / "Programs"
    if local_programs.is_dir():
        roots.append(local_programs)

    return [p for p in roots if p.is_dir()]


def find_local_target(query: str) -> Optional[Path]:
    """
    Search Start Menu, Desktop, and user folders for matching application or file.
    """
    q = query.strip().lower()
    if not q:
        return None

    # Check alias
    canonical = APP_ALIASES.get(q, q)
    if canonical.endswith(":") or "://" in canonical:
        return Path(canonical)

    # 1. First check PATH
    resolved_path = shutil.which(canonical) or shutil.which(q)
    if resolved_path:
        return Path(resolved_path)

    roots = get_search_roots()

    candidates: list[Tuple[int, Path]] = []

    for root in roots:
        try:
            # Walk up to 3 levels deep to stay ultra fast (<50ms)
            for dirpath, dirnames, filenames in os.walk(root):
                depth = len(Path(dirpath).relative_to(root).parts)
                if depth > 3:
                    dirnames.clear()
                    continue

                for fn in filenames:
                    p = Path(dirpath) / fn
                    name_lower = fn.lower()
                    stem_lower = p.stem.lower()
                    ext_lower = p.suffix.lower()

                    # Ignore code scripts and internal app files unless requested with exact extension
                    if ext_lower in (".py", ".pyc", ".pyo", ".pyd", ".git", ".log", ".tmp") and not q.endswith(ext_lower):
                        continue

                    # Ignore image, audio, and video media files when searching for applications
                    MEDIA_EXTENSIONS = (
                        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".tiff",
                        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm",
                        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
                    )
                    if ext_lower in MEDIA_EXTENSIONS and not any(q.endswith(me) for me in MEDIA_EXTENSIONS):
                        continue

                    # Never match WhatsApp image/video/audio downloads when searching for WhatsApp app
                    if "whatsapp" in q and ("whatsappimage" in stem_lower or "whatsapp video" in stem_lower or "whatsapp audio" in stem_lower):
                        continue

                    # Exact matches
                    if stem_lower == q or stem_lower == canonical:
                        return p
                    if name_lower == q:
                        return p

                    # Substring match
                    if q in stem_lower or canonical in stem_lower:
                        score = 80 - len(stem_lower)
                        candidates.append((score, p))
                    elif q in name_lower:
                        score = 70 - len(name_lower)
                        candidates.append((score, p))
        except Exception:
            continue

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # Fuzzy match across filenames
    all_files: list[Path] = []
    for root in roots[:4]:  # Top desktop/start menu roots
        try:
            for p in root.rglob("*"):
                if p.is_file():
                    all_files.append(p)
        except Exception:
            pass

    stems = [p.stem.lower() for p in all_files]
    matches = difflib.get_close_matches(q, stems, n=1, cutoff=0.6)
    if matches:
        idx = stems.index(matches[0])
        return all_files[idx]

    return None


def launch_target(target_path: Path) -> Tuple[bool, str]:
    """Launch file or executable immediately."""
    try:
        p_str = str(target_path)
        if p_str.endswith(":") or "://" in p_str:
            os.startfile(p_str)
            return True, f"Opened application via protocol {p_str}."

        p_resolved = str(target_path.resolve())
        ext = target_path.suffix.lower()

        if ext == ".exe":
            subprocess.Popen([p_resolved], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"Launched executable {target_path.name}."
        else:
            # .lnk shortcuts, folders, documents (.pdf, .txt, etc.)
            os.startfile(p_resolved)
            return True, f"Opened {target_path.name}."
    except Exception as e:
        return False, f"Failed to open {target_path.name}: {e}"


def find_and_launch(query: str) -> Tuple[bool, str]:
    """Finds matching app or file from local system and opens it immediately."""
    from core.command_lock import sync_command_mutex

    with sync_command_mutex(timeout=10.0):
        target = find_local_target(query)
        if not target:
            return False, f"Could not find any application or file matching '{query}' on local system."
        return launch_target(target)
