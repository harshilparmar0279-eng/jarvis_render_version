"""
core/lyrics_engine.py — High-Performance Multilingual Lyrics Engine for JARVIS.

Features:
- LRCLIB API client with caching, timestamp parsing, and fallback matching.
- Automatic script and language detection (Hindi, English, Gujarati, Mixed).
- Native Hindi-to-Hinglish phonological transliteration (Bollywood style with schwa deletion).
- Gujarati transliteration support.
- Preservation of English lyrics and English tokens in mixed lines.
- Configurable display modes: Auto, Original Script, Romanized, Translation.
"""

from __future__ import annotations

import re
import time
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

USER_AGENT = "JARVIS-Lyrics/1.0 (https://github.com/harshilparmar0279-eng/JARVIS-S)"

# ── High-frequency Hindi & Bollywood word dictionary ─────────────────────────
# Maps common words to their most familiar, natural Hinglish spellings.
HINDI_DICT: Dict[str, str] = {
    'मेरे': 'Mere', 'दिल': 'dil', 'में': 'mein', 'आज': 'aaj', 'क्या': 'kya', 'है': 'hai',
    'हैं': 'hain', 'तुम': 'Tum', 'ही': 'hi', 'हो': 'ho', 'तू': 'tu', 'तेरा': 'tera',
    'तेरी': 'teri', 'तेरे': 'tere', 'मेरा': 'mera', 'मेरी': 'meri', 'हम': 'hum',
    'हमारा': 'hamaara', 'इश्क़': 'ishq', 'प्यार': 'pyaar', 'मोहब्बत': 'mohabbat',
    'केसरिया': 'Kesariya', 'हुस्न': 'husn', 'रब्बा': 'Rabba', 'ने': 'ne', 'तुझको': 'tujhko',
    'बनाने': 'banane', 'की': 'ki', 'ख़ाली': 'khaali', 'काजल': 'kaajal', 'सियाही': 'siyaahi',
    'से': 'se', 'लिखी': 'likhi', 'तूने': 'toone', 'जाने': 'jaane', 'कितनों': 'kitnon',
    'पिया': 'piya', 'रंग': 'rang', 'जाऊँ': 'jaaoon', 'जो': 'jo', 'मैं': 'main',
    'हाथ': 'haath', 'लगाऊँ': 'lagaaoon', 'लव': 'love', 'स्टोरियाँ': 'storiyan',
    'ज़िंदगी': 'zindagi', 'आँखों': 'aankhon', 'बातें': 'baatein', 'दिन': 'din',
    'रात': 'raat', 'याद': 'yaad', 'साथ': 'saath', 'कोई': 'koi', 'मुझको': 'mujhko',
    'इतना': 'itna', 'बताए': 'bataye', 'कैसे': 'kaise', 'तुझसे': 'tujhse', 'ना': 'na',
    'लगाए': 'lagaye', 'तिजोरियाँ': 'tijoriyan', 'दुनिया': 'duniya', 'खुदा': 'khuda',
    'जान': 'jaan', 'आशिक़': 'aashiq', 'सपना': 'sapna', 'दीवाना': 'deewana',
    'सनम': 'sanam', 'हवा': 'hawa', 'मौसम': 'mausam', 'ख्वाब': 'khwaab',
}

DEVA_VOWELS = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'ऋ': 'ri',
}

DEVA_MATRAS = {
    'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ृ': 'ri',
}

DEVA_CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v',
    'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
    'क़': 'q', 'ख़': 'kh', 'ग़': 'gh', 'ज़': 'z', 'फ़': 'f', 'ड़': 'r', 'ढ़': 'rh',
}

# Gujarati Mappings
GUJ_VOWELS = {
    'અ': 'a', 'આ': 'aa', 'ઇ': 'i', 'ઈ': 'ee', 'ઉ': 'u', 'ઊ': 'oo',
    'એ': 'e', 'ઐ': 'ai', 'ઓ': 'o', 'ઔ': 'au', 'ઋ': 'ri',
}

GUJ_MATRAS = {
    'ા': 'a', 'િ': 'i', 'ી': 'ee', 'ુ': 'u', 'ૂ': 'oo',
    'ે': 'e', 'ૈ': 'ai', 'ો': 'o', 'ૌ': 'au', 'ૃ': 'ri',
}

GUJ_CONSONANTS = {
    'ક': 'k', 'ખ': 'kh', 'ગ': 'g', 'ઘ': 'gh', 'ઙ': 'ng',
    'ચ': 'ch', 'છ': 'chh', 'જ': 'j', 'ઝ': 'jh', 'ઞ': 'ny',
    'ટ': 't', 'ઠ': 'th', 'ડ': 'd', 'ઢ': 'dh', 'ણ': 'n',
    'ત': 't', 'થ': 'th', 'દ': 'd', 'ધ': 'dh', 'ન': 'n',
    'પ': 'p', 'ફ': 'ph', 'બ': 'b', 'ભ': 'bh', 'મ': 'm',
    'ય': 'y', 'ર': 'r', 'લ': 'l', 'વ': 'v', 'ળ': 'l',
    'શ': 'sh', 'ષ': 'sh', 'સ': 's', 'હ': 'h',
}


def detect_language(text: str) -> str:
    """
    Detects language/script of lyrics:
    - 'hi': Hindi / Devanagari script
    - 'gu': Gujarati script
    - 'en': English / Latin script
    - 'mixed': Mixed Hindi & English
    """
    if not text:
        return "en"
    deva_count = len(re.findall(r'[\u0900-\u097F]', text))
    guj_count = len(re.findall(r'[\u0A80-\u0AFF]', text))
    latin_count = len(re.findall(r'[a-zA-Z]', text))

    total = deva_count + guj_count + latin_count
    if total == 0:
        return "en"

    if deva_count > 0 and latin_count > 0 and (deva_count / total > 0.2) and (latin_count / total > 0.2):
        return "mixed"
    if deva_count > 0 and deva_count >= guj_count and deva_count >= latin_count:
        return "hi"
    if guj_count > 0 and guj_count >= deva_count and guj_count >= latin_count:
        return "gu"
    return "en"


def _transliterate_word_deva(word: str) -> str:
    clean = re.sub(r'[^\w\u0900-\u097F]', '', word)
    if clean in HINDI_DICT:
        return HINDI_DICT[clean]

    out = []
    i = 0
    chars = list(word)
    n = len(chars)

    while i < n:
        c = chars[i]
        # Check nukta combination (e.g. क़, ख़, ग़, ज़, फ़)
        if i + 1 < n and chars[i+1] == '़':
            c_combined = c + '़'
            if c_combined in DEVA_CONSONANTS:
                cons = DEVA_CONSONANTS[c_combined]
                i += 2
                if i < n and chars[i] == '्':
                    out.append(cons)
                    i += 1
                elif i < n and chars[i] in DEVA_MATRAS:
                    out.append(cons + DEVA_MATRAS[chars[i]])
                    i += 1
                else:
                    out.append(cons + ('' if i == n else 'a'))
                continue

        if c in DEVA_VOWELS:
            out.append(DEVA_VOWELS[c])
            i += 1
        elif c in DEVA_CONSONANTS:
            cons = DEVA_CONSONANTS[c]
            i += 1
            if i < n and chars[i] == '्':
                out.append(cons)
                i += 1
            elif i < n and chars[i] in DEVA_MATRAS:
                mat = DEVA_MATRAS[chars[i]]
                i += 1
                if i < n and chars[i] in ('ं', 'ँ'):
                    mat = mat + 'n'
                    i += 1
                out.append(cons + mat)
            elif i < n and chars[i] in ('ं', 'ँ'):
                out.append(cons + 'an')
                i += 1
            else:
                # Schwa deletion at end of word or before non-Devanagari
                if i == n or not re.match(r'[\u0900-\u097F]', chars[i]):
                    out.append(cons)
                else:
                    out.append(cons + 'a')
        elif c in ('ं', 'ँ'):
            out.append('n')
            i += 1
        elif c in DEVA_MATRAS:
            out.append(DEVA_MATRAS[c])
            i += 1
        else:
            out.append(c)
            i += 1

    return "".join(out)


def transliterate_to_hinglish(text: str) -> str:
    """Converts Devanagari Hindi text to readable Hinglish while preserving English tokens."""
    if not text:
        return ""
    # Split preserving punctuation, whitespace, and English tokens
    tokens = re.split(r'(\s+|[^\w\u0900-\u097F]+)', text)
    result = []
    for tok in tokens:
        if not tok:
            continue
        if re.search(r'[\u0900-\u097F]', tok):
            result.append(_transliterate_word_deva(tok))
        else:
            result.append(tok)

    line = "".join(result)
    line = re.sub(r'(\w)yaa\b', r'\1ya', line)
    # Capitalize first letter of sentence naturally
    if line and line[0].islower():
        line = line[0].upper() + line[1:]
    return line


def transliterate_gujarati(text: str) -> str:
    """Converts Gujarati script text to readable Roman Gujarati while preserving English tokens."""
    if not text:
        return ""
    tokens = re.split(r'(\s+|[^\w\u0A80-\u0AFF]+)', text)
    result = []
    for tok in tokens:
        if not tok:
            continue
        if re.search(r'[\u0A80-\u0AFF]', tok):
            out = []
            chars = list(tok)
            n = len(chars)
            i = 0
            while i < n:
                c = chars[i]
                if c in GUJ_VOWELS:
                    out.append(GUJ_VOWELS[c])
                    i += 1
                elif c in GUJ_CONSONANTS:
                    cons = GUJ_CONSONANTS[c]
                    i += 1
                    if i < n and chars[i] == '્':  # virama
                        out.append(cons)
                        i += 1
                    elif i < n and chars[i] in GUJ_MATRAS:
                        mat = GUJ_MATRAS[chars[i]]
                        i += 1
                        if i < n and chars[i] in ('ં', 'ઁ'):
                            mat = mat + 'n'
                            i += 1
                        out.append(cons + mat)
                    elif i < n and chars[i] in ('ં', 'ઁ'):
                        out.append(cons + 'an')
                        i += 1
                    else:
                        if i == n:
                            out.append(cons)
                        else:
                            out.append(cons + 'a')
                elif c in ('ં', 'ઁ'):
                    out.append('n')
                    i += 1
                elif c in GUJ_MATRAS:
                    out.append(GUJ_MATRAS[c])
                    i += 1
                else:
                    out.append(c)
                    i += 1
            res = "".join(out)
            result.append(res)
        else:
            result.append(tok)
    return "".join(result)


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class LyricsLine:
    time_sec: float
    original_text: str
    display_text: str = ""
    language: str = "en"


@dataclass
class LyricsTrack:
    track_name: str
    artist_name: str = ""
    duration: float = 0.0
    is_synced: bool = False
    is_instrumental: bool = False
    lines: List[LyricsLine] = field(default_factory=list)
    primary_language: str = "en"
    display_mode: str = "auto"
    source: str = "LRCLIB"

    def get_active_index(self, position_sec: float) -> int:
        """Return the index of the currently active lyric line for a playback timestamp."""
        if not self.lines:
            return -1
        # Find the last line whose time_sec <= position_sec
        active_idx = -1
        for idx, line in enumerate(self.lines):
            if line.time_sec <= position_sec + 0.15:  # small 150ms anticipation tolerance
                active_idx = idx
            else:
                break
        return active_idx


def apply_language_rules(track: LyricsTrack, mode: str = "auto", roman_gujarati: bool = False) -> None:
    """
    Applies the core user language rules to each lyric line:
    - In Auto mode:
      - Hindi -> Hinglish
      - English -> English (no transliteration or translation)
      - Gujarati -> Gujarati script (or Roman Gujarati if enabled)
      - Mixed -> Line-level transliteration
    - In Original mode:
      - All lines display original script.
    - In Romanized mode:
      - Translates Devanagari & Gujarati to Latin script.
    """
    track.display_mode = mode
    for line in track.lines:
        line_lang = detect_language(line.original_text)
        line.language = line_lang

        if mode == "original":
            line.display_text = line.original_text
        elif mode == "romanized":
            if line_lang in ("hi", "mixed"):
                line.display_text = transliterate_to_hinglish(line.original_text)
            elif line_lang == "gu":
                line.display_text = transliterate_gujarati(line.original_text)
            else:
                line.display_text = line.original_text
        else:
            # Auto mode (default)
            if line_lang in ("hi", "mixed"):
                line.display_text = transliterate_to_hinglish(line.original_text)
            elif line_lang == "gu":
                if roman_gujarati:
                    line.display_text = transliterate_gujarati(line.original_text)
                else:
                    line.display_text = line.original_text
            else:
                # English or other: preserve original words intact!
                line.display_text = line.original_text


# ── LRCLIB API Client ────────────────────────────────────────────────────────

class LRCLIBClient:
    """Client for retrieving synchronized and plain lyrics from lrclib.net."""
    
    BASE_URL = "https://lrclib.net/api"
    _cache: Dict[str, Optional[LyricsTrack]] = {}

    @classmethod
    def parse_lrc(cls, lrc_text: str) -> List[LyricsLine]:
        """Parses standard LRC lyrics into timestamped LyricsLine objects."""
        lines: List[LyricsLine] = []
        lrc_pattern = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)')
        
        for raw in lrc_text.splitlines():
            m = lrc_pattern.match(raw.strip())
            if m:
                mins = int(m.group(1))
                secs = int(m.group(2))
                frac = float(f"0.{m.group(3)}")
                total_sec = mins * 60 + secs + frac
                text = m.group(4).strip()
                # Exclude purely metadata tags
                if text.startswith(("ar:", "ti:", "al:", "by:", "offset:")):
                    continue
                lines.append(LyricsLine(time_sec=total_sec, original_text=text))
        
        lines.sort(key=lambda x: x.time_sec)
        return lines

    @classmethod
    def fetch_lyrics(cls, track_name: str, artist_name: str = "", duration: float = 0.0) -> Optional[LyricsTrack]:
        """
        Retrieves matching lyrics from LRCLIB.
        Uses in-memory cache to prevent repeated requests.
        """
        clean_track = track_name.strip()
        clean_artist = artist_name.strip()
        cache_key = f"{clean_track.lower()}|{clean_artist.lower()}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        track_obj: Optional[LyricsTrack] = None

        # 1. Try exact get endpoint if artist and duration are known
        if clean_artist and duration > 0:
            params = {
                "track_name": clean_track,
                "artist_name": clean_artist,
                "duration": int(duration),
            }
            try:
                url = f"{cls.BASE_URL}/get?{urllib.parse.urlencode(params)}"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        track_obj = cls._data_to_track(data, clean_track, clean_artist)
            except Exception:
                track_obj = None

        # 2. Try search endpoint
        if not track_obj:
            query = f"{clean_track} {clean_artist}".strip()
            params = {"q": query}
            try:
                url = f"{cls.BASE_URL}/search?{urllib.parse.urlencode(params)}"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    if resp.status == 200:
                        results = json.loads(resp.read().decode("utf-8"))
                        if results and isinstance(results, list):
                            # Prefer synchronized result
                            selected = next((item for item in results if item.get("syncedLyrics")), results[0])
                            track_obj = cls._data_to_track(selected, clean_track, clean_artist)
            except Exception:
                track_obj = None

        cls._cache[cache_key] = track_obj
        return track_obj

    @classmethod
    def _data_to_track(cls, data: dict, req_track: str, req_artist: str) -> Optional[LyricsTrack]:
        if not data:
            return None

        is_instrumental = bool(data.get("instrumental", False))
        synced_lrc = data.get("syncedLyrics", "") or ""
        plain_text = data.get("plainLyrics", "") or ""

        lines: List[LyricsLine] = []
        is_synced = False

        if synced_lrc:
            lines = cls.parse_lrc(synced_lrc)
            is_synced = len(lines) > 0
        
        if not lines and plain_text:
            # Fallback plain lyrics (unsynchronized)
            for raw_line in plain_text.splitlines():
                if raw_line.strip():
                    lines.append(LyricsLine(time_sec=0.0, original_text=raw_line.strip()))
            is_synced = False

        track_title = data.get("trackName") or req_track
        artist = data.get("artistName") or req_artist
        duration = float(data.get("duration") or 0.0)

        # Detect primary language of full track
        sample_text = " ".join(line.original_text for line in lines[:8])
        primary_lang = detect_language(sample_text)

        track = LyricsTrack(
            track_name=track_title,
            artist_name=artist,
            duration=duration,
            is_synced=is_synced,
            is_instrumental=is_instrumental,
            lines=lines,
            primary_language=primary_lang,
            source="LRCLIB",
        )

        apply_language_rules(track, mode="auto")
        return track
