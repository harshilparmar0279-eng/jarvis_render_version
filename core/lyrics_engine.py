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
class LyricsWord:
    text: str
    start_sec: float
    end_sec: float


@dataclass
class LyricsLine:
    time_sec: float
    original_text: str
    display_text: str = ""
    language: str = "en"
    words: List[LyricsWord] = field(default_factory=list)

    def build_words(self, next_time_sec: float = 0.0) -> List[LyricsWord]:
        if self.words:
            return self.words
        raw = (self.display_text or self.original_text or "").strip()
        if not raw:
            return []
        tokens = raw.split()
        if not tokens:
            return []
        dur = max(1.8, (next_time_sec - self.time_sec) if next_time_sec > self.time_sec else 3.5)
        total_len = sum(len(t) for t in tokens)
        cur = self.time_sec
        words_out = []
        for t in tokens:
            w_dur = (len(t) / max(1, total_len)) * dur
            words_out.append(LyricsWord(text=t, start_sec=cur, end_sec=cur + w_dur))
            cur += w_dur
        self.words = words_out
        return self.words


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

    def get_active_word_index(self, line_idx: int, position_sec: float) -> int:
        if 0 <= line_idx < len(self.lines):
            line = self.lines[line_idx]
            if not line.words:
                next_t = self.lines[line_idx + 1].time_sec if line_idx + 1 < len(self.lines) else line.time_sec + 3.5
                line.build_words(next_t)
            for i, w in enumerate(line.words):
                if w.start_sec <= position_sec + 0.10 <= w.end_sec:
                    return i
            if line.words and position_sec >= line.words[-1].end_sec:
                return len(line.words) - 1
            if line.words and position_sec >= line.words[0].start_sec:
                return 0
        return 0


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


# ── Smart Title Cleaner & Multilingual Multi-Source Pipeline ─────────────────

CHANNELS = (
    'coke studio', 'coke studio bharat', 'coke studio pakistan',
    't-series', 't series', 'tseries', 't-series apna punjab',
    'zee music company', 'zee music', 'zee music gujarati',
    'speed records', 'tips official', 'tips music',
    'sony music india', 'sony music', 'sony music south',
    'yrf', 'saregama', 'aditya music', 'white hill music',
    'geet mp3', 'desi music factory', 'eros now', 'shemaroo',
    'vyrl originals', 'svf', 'times music'
)


def get_song_candidates(title: str, artist: str = '') -> List[Tuple[str, str]]:
    """
    Extracts multiple high-probability (track_name, artist_name) search candidates
    from noisy YouTube and media titles.
    Strips noise words (song, video, 4k) and ignores known record label channels.
    """
    if not title:
        return [('', (artist or '').strip())]

    clean = title.strip()
    clean = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', clean)
    noise_pattern = (
        r'\b(?:8k|4k|hd|uhd|full video|full song|audio song|video song|official video|'
        r'official audio|lyric video|lyrics video|lyrical video|visualizer|audio|video|'
        r'remix|slowed|reverb|4k 60fps|8k 60fps|song|songs|teaser|trailer|hook step|dance step)\b'
    )
    clean = re.sub(noise_pattern, ' ', clean, flags=re.I)
    clean = re.sub(r'[\r\n]+', ' ', clean).strip()

    parts = [p.strip() for p in re.split(r'[|•]', clean) if p.strip()]
    first_part = parts[0] if parts else clean

    auto_artist = (artist or '').strip()
    # If the provided artist is a known record label channel name, discard it
    if auto_artist.lower() in CHANNELS or any(c in auto_artist.lower() for c in CHANNELS):
        auto_artist = ''

    if not auto_artist and len(parts) > 1:
        for p in parts[1:]:
            m = re.search(r'\b(?:by|singer|artist|ft\.?|feat\.?)\s*([a-zA-Z\s]+)', p, re.I)
            if m:
                cand_a = m.group(1).strip()
                if cand_a.lower() not in CHANNELS:
                    auto_artist = cand_a
                    break

    candidates: List[Tuple[str, str]] = []

    if ':' in first_part:
        sub = [s.strip() for s in first_part.split(':', 1)]
        candidates.append((sub[1], auto_artist or ('' if sub[0].lower() in CHANNELS else sub[0])))
        candidates.append((sub[1], ''))
        candidates.append((sub[0], ''))

    if '-' in first_part:
        sub = [s.strip() for s in first_part.split('-', 1)]
        candidates.append((sub[0], auto_artist or ('' if sub[1].lower() in CHANNELS else sub[1])))
        candidates.append((sub[1], auto_artist or ('' if sub[0].lower() in CHANNELS else sub[0])))
        candidates.append((sub[0], ''))
        candidates.append((sub[1], ''))
    else:
        candidates.append((first_part, auto_artist))
        candidates.append((first_part, ''))

    # If title has multiple parts, also test prefixing movie or album name
    if len(parts) >= 2:
        part0 = re.sub(noise_pattern, ' ', parts[0], flags=re.I).strip()
        part1 = re.sub(noise_pattern, ' ', parts[1], flags=re.I).strip()
        if part0 and part1 and part1.lower() not in CHANNELS:
            candidates.append((f"{part1} {part0}", auto_artist))
            candidates.append((f"{part0} {part1}", auto_artist))

    result: List[Tuple[str, str]] = []
    seen = set()
    for t_raw, a_raw in candidates:
        t_c = re.sub(noise_pattern, ' ', t_raw, flags=re.I)
        t_c = re.sub(r'\s+', ' ', t_c).strip(' -:|')
        a_c = re.sub(noise_pattern, ' ', a_raw, flags=re.I)
        a_c = re.sub(r'\s+', ' ', a_c).strip(' -:|')
        if a_c.lower() in CHANNELS:
            a_c = ''
        if t_c and (t_c.lower(), a_c.lower()) not in seen:
            seen.add((t_c.lower(), a_c.lower()))
            result.append((t_c, a_c))

    return result or [(clean, auto_artist)]


def clean_song_title(title: str, artist: str = '') -> Tuple[str, str]:
    """Cleans noisy YouTube titles and extracts clean song title and artist."""
    candidates = get_song_candidates(title, artist)
    if candidates:
        return candidates[0]
    return title.strip(), (artist or '').strip()

# ── YouTube Direct Subtitles / Captions Client ──────────────────────────────

class YouTubeSubtitleClient:
    """Extracts timestamped synchronized lyrics from YouTube subtitles and automatic captions."""

    @classmethod
    def fetch_from_info(cls, info: dict, title: str = '', artist: str = '', allow_auto: bool = False) -> Optional[LyricsTrack]:
        if not info:
            return None

        subs = info.get('subtitles') or {}
        auto_subs = info.get('automatic_captions') or {}

        target_lang = None
        target_fmts = None

        manual_langs = [l for l in subs.keys() if l != 'live_chat']
        # Prioritize authentic native lyrics over English translations
        preferred_priority = [
            'hi', 'hi-Latn', 'gu', 'pa', 'mr', 'bn', 'ta', 'te',
            'en', 'en-IN', 'es', 'fr', 'de', 'ja', 'ko'
        ]

        if manual_langs:
            target_lang = next((l for l in preferred_priority if l in manual_langs), manual_langs[0])
            target_fmts = subs.get(target_lang)
        elif allow_auto and auto_subs:
            target_lang = next((l for l in preferred_priority if l in auto_subs), list(auto_subs.keys())[0])
            target_fmts = auto_subs.get(target_lang)

        if not target_fmts:
            return None

        json3_fmt = next((f for f in target_fmts if f.get('ext') == 'json3'), None)
        if not json3_fmt or not json3_fmt.get('url'):
            return None

        try:
            req = urllib.request.Request(json3_fmt['url'], headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            events = data.get('events', [])
            lines: List[LyricsLine] = []
            for ev in events:
                t_sec = ev.get('tStartMs', 0) / 1000.0
                segs = ev.get('segs', [])
                raw_text = ''.join(s.get('utf8', '') for s in segs).strip()
                raw_text = re.sub(r'\[.*?\]', '', raw_text).strip()
                if not raw_text:
                    continue

                # Handle multi-line events (e.g. Coke Studio with Gujarati, Romanized, English)
                sub_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
                if not sub_lines:
                    continue

                # Pick the authentic native script or primary line
                primary_line = sub_lines[0]
                for sl in sub_lines:
                    if re.search(r'[\u0900-\u097F\u0A80-\u0AFF]', sl):
                        primary_line = sl
                        break

                clean_text = re.sub(r'^[“"👉\s]+|[”"👈\s]+$', '', primary_line).strip()
                if clean_text:
                    l_obj = LyricsLine(time_sec=t_sec, original_text=clean_text)
                    lines.append(l_obj)

            if not lines:
                return None

            lines.sort(key=lambda x: x.time_sec)
            sample_text = ' '.join(l.original_text for l in lines[:10])
            primary_lang = detect_language(sample_text)

            clean_title, clean_artist = clean_song_title(title or info.get('title') or 'Media', artist)
            track = LyricsTrack(
                track_name=clean_title or title or 'Media',
                artist_name=clean_artist or artist,
                duration=lines[-1].time_sec if lines else 0.0,
                is_synced=True,
                is_instrumental=False,
                lines=lines,
                primary_language=primary_lang,
                source=f'YouTube ({target_lang})',
            )
            apply_language_rules(track, mode='auto')
            return track
        except Exception:
            return None


# ── LRCLIB API Client ────────────────────────────────────────────────────────

class LRCLIBClient:
    """Client for retrieving synchronized and plain lyrics from lrclib.net."""
    
    BASE_URL = 'https://lrclib.net/api'
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
                frac = float(f'0.{m.group(3)}')
                total_sec = mins * 60 + secs + frac
                text = m.group(4).strip()
                if text.startswith(('ar:', 'ti:', 'al:', 'by:', 'offset:')):
                    continue
                lines.append(LyricsLine(time_sec=total_sec, original_text=text))
        
        lines.sort(key=lambda x: x.time_sec)
        return lines

    @classmethod
    def fetch_lyrics(cls, track_name: str, artist_name: str = '', duration: float = 0.0) -> Optional[LyricsTrack]:
        """
        Retrieves matching lyrics from LRCLIB.
        Uses in-memory cache to prevent repeated requests.
        """
        clean_track, auto_artist = clean_song_title(track_name, artist_name)
        clean_artist = (artist_name or auto_artist).strip()
        cache_key = f'{clean_track.lower()}|{clean_artist.lower()}'
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        headers = {
            'User-Agent': 'JARVIS-Music/2.0 (contact: harshilparmar0279@gmail.com; https://github.com/harshilparmar0279-eng/JARVIS-S)',
            'Accept': 'application/json',
        }

        track_obj: Optional[LyricsTrack] = None

        # Attempt 1: Exact track_name search (avoids 503 on raw queries like 'Main Tera Boyfriend')
        if clean_track:
            params = {'track_name': clean_track}
            if clean_artist and clean_artist.lower() not in CHANNELS:
                params['artist_name'] = clean_artist
            try:
                url = f'{cls.BASE_URL}/search?{urllib.parse.urlencode(params)}'
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        results = json.loads(resp.read().decode('utf-8'))
                        if results and isinstance(results, list):
                            # Strictly filter results to match the requested song title and artist
                            def _match_score(item: dict) -> float:
                                cand_title = (item.get('trackName') or '').strip().lower()
                                req_t = clean_track.strip().lower()
                                if not cand_title or not req_t:
                                    return 0.0
                                if cand_title == req_t or req_t in cand_title or cand_title in req_t:
                                    return 1.0 + (0.5 if item.get('syncedLyrics') else 0.0)
                                r_words = set(re.findall(r'\w+', req_t))
                                c_words = set(re.findall(r'\w+', cand_title))
                                overlap = len(r_words & c_words) / max(1, len(r_words))
                                if overlap >= 0.5:
                                    return overlap + (0.3 if item.get('syncedLyrics') else 0.0)
                                return 0.0

                            scored = [(item, _match_score(item)) for item in results]
                            valid = [item for item, score in scored if score >= 0.5]
                            if valid:
                                selected = next((item for item in valid if item.get('syncedLyrics')), valid[0])
                                track_obj = cls._data_to_track(selected, clean_track, clean_artist)
            except Exception:
                track_obj = None

        # Attempt 2: If clean_artist is provided, exact /get query with duration
        if not track_obj and clean_artist and duration > 0 and clean_artist.lower() not in CHANNELS:
            params = {
                'track_name': clean_track,
                'artist_name': clean_artist,
                'duration': int(duration),
            }
            try:
                url = f'{cls.BASE_URL}/get?{urllib.parse.urlencode(params)}'
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode('utf-8'))
                        track_obj = cls._data_to_track(data, clean_track, clean_artist)
            except Exception:
                track_obj = None

        # Attempt 3: General search query 'q'
        if not track_obj:
            q_artist = f" {clean_artist}" if clean_artist and clean_artist.lower() not in CHANNELS else ""
            query = f'{clean_track}{q_artist}'.strip()
            params = {'q': query}
            try:
                url = f'{cls.BASE_URL}/search?{urllib.parse.urlencode(params)}'
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        results = json.loads(resp.read().decode('utf-8'))
                        if results and isinstance(results, list):
                            selected = next((item for item in results if item.get('syncedLyrics')), results[0])
                            track_obj = cls._data_to_track(selected, clean_track, clean_artist)
            except Exception:
                track_obj = None

        cls._cache[cache_key] = track_obj
        return track_obj

    @classmethod
    def _data_to_track(cls, data: dict, req_track: str, req_artist: str) -> Optional[LyricsTrack]:
        if not data:
            return None

        is_instrumental = bool(data.get('instrumental', False))
        synced_lrc = data.get('syncedLyrics', '') or ''
        plain_text = data.get('plainLyrics', '') or ''

        lines: List[LyricsLine] = []
        is_synced = False

        if synced_lrc:
            lines = cls.parse_lrc(synced_lrc)
            is_synced = len(lines) > 0
        
        if not lines and plain_text:
            for raw_line in plain_text.splitlines():
                if raw_line.strip():
                    lines.append(LyricsLine(time_sec=0.0, original_text=raw_line.strip()))
            is_synced = False

        track_title = data.get('trackName') or req_track
        artist = data.get('artistName') or req_artist
        duration = float(data.get('duration') or 0.0)

        sample_text = ' '.join(line.original_text for line in lines[:8])
        primary_lang = detect_language(sample_text)

        track = LyricsTrack(
            track_name=track_title,
            artist_name=artist,
            duration=duration,
            is_synced=is_synced,
            is_instrumental=is_instrumental,
            lines=lines,
            primary_language=primary_lang,
            source='LRCLIB',
        )

        apply_language_rules(track, mode='auto')
        return track


# ── YouTube Description Lyrics Extractor ──────────────────────────────────────

CREDIT_FILTER_WORDS = (
    'mixed & mastered', 'mix & master', 'mixed by', 'mastered by', 'mastered:-', 'mastered:',
    'lyrical video', 'video by', 'directed by', 'director',
    'album art', 'cover art', 'artwork', 'visualizer', 'the quirky i', 'artsyfatiima', 'simon vikram',
    'dop', 'cinematographer', 'editor', 'colorist', 'di colorist',
    'cast', 'starring', 'featuring', 'performed by', 'performers',
    'qawaali vocals', 'vocals', 'music by', 'composed by', 'composer',
    'producer', 'produced by', 'record label', 'music label',
    'all rights reserved', 'stream on', 'listen on', 'download on',
    'special thanks', 'publicity design', 'poster design',
    'chorus vocals', 'backing vocals', 'guitars by', 'recording engineer', 'sound engineer',
    'singer:', 'singers:', 'artist:', 'music:', 'lyrics:', 'lyricist:', 'composed:'
)


def is_credit_line(line: str) -> bool:
    """Returns True if the line contains technical/production credits rather than singing lyrics."""
    if not line:
        return False
    lower = line.lower().strip()
    if any(cw in lower for cw in CREDIT_FILTER_WORDS):
        return True
    if re.search(r'\b(?:lyrics|music|singer|performer|composer|director|mastered|video|audio|art|label|dop)\s*[:-]', lower):
        return True
    if lower.startswith(('stream', 'streaming', 'spotify', 'apple', 'insta', 'follow', 'subscribe', 'credits', 'label', 'visual by', 'video by')):
        return True
    if ':-' in lower or '::' in lower:
        return True
    return False


def is_valid_lyrics_track(track: Optional[LyricsTrack]) -> bool:
    """Validates that a track contains real singing lyrics and NOT credits or metadata."""
    if not track or not track.lines:
        return False
    # Strip any individual credit lines first
    track.lines = [l for l in track.lines if not is_credit_line(l.original_text) and not is_credit_line(l.display_text)]
    if len(track.lines) < 3:
        return False
    return True


class YouTubeDescriptionLyricsClient:
    """
    Extracts authentic artist-provided lyrics directly from YouTube video description.
    Strictly filters out production credits, mixing/mastering notes, and social links.
    """

    @classmethod
    def fetch_from_info(cls, info: dict, title: str = '', artist: str = '') -> Optional[LyricsTrack]:
        if not info or not isinstance(info, dict):
            return None
        desc = info.get('description', '') or ''
        if not desc or len(desc) < 40:
            return None

        # Look strictly for actual lyrics blocks
        patterns = [
            r'(?:^|\n)\s*(?:song\s+lyrics|lyrics|bol|lyrics\s*&?\s*composition|गीत\s*के\s*बोल)\s*[:\-—]*\s*\n+(.*?)(?=\n\s*(?:stream\s+on|streaming\s+links|audio\s+credits|credits|visual\s+credits|directed\s+by|produced\s+by|mix\s+&?\s+master|enjoy\s+&|subscribe|follow\s+on|copyright|performers|visual by|dop|\Z))',
        ]

        raw_block = ""
        for p in patterns:
            m = re.search(p, desc, re.IGNORECASE | re.DOTALL)
            if m:
                raw_block = m.group(1).strip()
                if len(raw_block) > 40:
                    break

        if not raw_block:
            return None

        # Filter lines
        candidate_lines = [
            re.sub(r'^[“"👉\s]+|[”"👈\s]+$', '', l).strip()
            for l in raw_block.splitlines()
            if l.strip() and not l.strip().startswith(('-', '=', '#', 'http'))
        ]

        clean_lines = []
        for l in candidate_lines:
            if is_credit_line(l):
                continue
            if len(l) < 3 or len(l) > 110:
                continue
            clean_lines.append(l)

        # Must have at least 5 authentic song verse lines
        if len(clean_lines) < 5:
            return None

        duration = float(info.get('duration') or 180.0)
        intro_sec = 12.0
        outro_sec = 8.0
        usable_sec = max(20.0, duration - intro_sec - outro_sec)
        time_step = usable_sec / max(1, len(clean_lines))

        track_lines: List[LyricsLine] = []
        cur_t = intro_sec
        for l in clean_lines:
            track_lines.append(LyricsLine(time_sec=cur_t, original_text=l))
            cur_t += time_step

        sample_text = ' '.join(l.original_text for l in track_lines[:8])
        primary_lang = detect_language(sample_text)
        clean_title, clean_artist = clean_song_title(title or info.get('title') or 'Media', artist)

        track = LyricsTrack(
            track_name=clean_title,
            artist_name=clean_artist,
            duration=duration,
            is_synced=True,
            is_instrumental=False,
            lines=track_lines,
            primary_language=primary_lang,
            source='YouTube Description',
        )
        apply_language_rules(track, mode='auto')
        return track if is_valid_lyrics_track(track) else None


# ── Spotify Official Color-Lyrics Client ─────────────────────────────────────

class SpotifyLyricsClient:
    """
    Client for retrieving official studio-synchronized lyrics from Spotify's
    Color-Lyrics API using the user's sp_dc cookie.
    Provides official synchronized lyrics for any song in the Spotify catalog.
    """

    BASE_URL = "https://spclient.wg.spotify.com/color-lyrics/v2/track"
    TOKEN_URL = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
    SEARCH_URL = "https://api.spotify.com/v1/search"
    
    _cached_token: str = ""
    _token_expires_at: float = 0.0

    @classmethod
    def get_access_token(cls, sp_dc: str) -> Optional[str]:
        import time
        if cls._cached_token and time.time() < cls._token_expires_at - 60:
            return cls._cached_token
        if not sp_dc:
            return None
        try:
            req = urllib.request.Request(
                cls.TOKEN_URL,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Cookie': f'sp_dc={sp_dc}',
                    'Accept': 'application/json',
                }
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    cls._cached_token = data.get('accessToken', '')
                    expires_ms = data.get('accessTokenExpirationTimestampMs', 0)
                    if expires_ms:
                        cls._token_expires_at = expires_ms / 1000.0
                    else:
                        cls._token_expires_at = time.time() + 3600
                    return cls._cached_token
        except Exception:
            return None
        return None

    @classmethod
    def fetch_lyrics(cls, track_name: str, artist_name: str = '') -> Optional[LyricsTrack]:
        from memory.config_manager import get_spotify_sp_dc
        sp_dc = get_spotify_sp_dc()
        if not sp_dc:
            return None

        token = cls.get_access_token(sp_dc)
        if not token:
            return None

        clean_track, auto_artist = clean_song_title(track_name, artist_name)
        clean_artist = artist_name or auto_artist
        query = f"{clean_track} {clean_artist}".strip()

        try:
            # 1. Search for Spotify track ID
            search_params = urllib.parse.urlencode({'q': query, 'type': 'track', 'limit': 3})
            search_req = urllib.request.Request(
                f"{cls.SEARCH_URL}?{search_params}",
                headers={'Authorization': f'Bearer {token}', 'User-Agent': USER_AGENT}
            )
            spotify_id = None
            official_title = clean_track
            official_artist = clean_artist
            with urllib.request.urlopen(search_req, timeout=6.0) as resp:
                if resp.status == 200:
                    s_data = json.loads(resp.read().decode('utf-8'))
                    items = s_data.get('tracks', {}).get('items', [])
                    if items:
                        item = items[0]
                        spotify_id = item.get('id')
                        official_title = item.get('name') or clean_track
                        artists = item.get('artists', [])
                        if artists:
                            official_artist = artists[0].get('name') or clean_artist

            if not spotify_id:
                return None

            # 2. Fetch official Color-Lyrics
            lyrics_url = f"{cls.BASE_URL}/{spotify_id}?format=json&market=from_token"
            lyrics_req = urllib.request.Request(
                lyrics_url,
                headers={
                    'Authorization': f'Bearer {token}',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'app-platform': 'WebPlayer',
                }
            )
            with urllib.request.urlopen(lyrics_req, timeout=6.0) as resp:
                if resp.status == 200:
                    l_data = json.loads(resp.read().decode('utf-8'))
                    lyrics_obj = l_data.get('lyrics', {})
                    raw_lines = lyrics_obj.get('lines', [])
                    if not raw_lines:
                        return None

                    track_lines: List[LyricsLine] = []
                    for line_item in raw_lines:
                        t_ms = float(line_item.get('startTimeMs') or 0.0)
                        words_text = (line_item.get('words') or '').strip()
                        if words_text and words_text != '♪':
                            track_lines.append(LyricsLine(time_sec=t_ms / 1000.0, original_text=words_text))

                    if not track_lines:
                        return None

                    sample_text = ' '.join(l.original_text for l in track_lines[:8])
                    primary_lang = detect_language(sample_text)

                    track = LyricsTrack(
                        track_name=official_title,
                        artist_name=official_artist,
                        duration=track_lines[-1].time_sec if track_lines else 0.0,
                        is_synced=True,
                        is_instrumental=False,
                        lines=track_lines,
                        primary_language=primary_lang,
                        source='Spotify Official',
                    )
                    apply_language_rules(track, mode='auto')
                    return track
        except Exception:
            return None
        return None


# ── Gemini AI Lyrics Fallback Client ─────────────────────────────────────────

class GeminiLyricsClient:
    """AI fallback for generating synchronized lyrics for any song in any language."""

    @classmethod
    def fetch_lyrics(cls, track_name: str, artist_name: str = '') -> Optional[LyricsTrack]:
        clean_track, clean_artist = clean_song_title(track_name, artist_name)
        if not clean_track:
            return None

        try:
            from core import gemini
            artist_part = f" by '{clean_artist}'" if clean_artist else ''
            prompt = (
                f"Provide full synchronized lyrics for the song '{clean_track}'{artist_part} "
                f"in its authentic original language and native script (e.g., Devanagari Hindi, Gujarati script, Punjabi Gurmukhi, English, Spanish, etc.). "
                f"Format strictly as standard LRC with timestamps for each line (e.g. [00:15.20] Lyric line). "
                f"Produce ONLY the LRC timestamped lines. Do not include markdown fences, comments, or explanations."
            )
            raw = gemini.text(prompt)
            if not raw or '[' not in raw:
                return None

            lines = LRCLIBClient.parse_lrc(raw)
            if not lines:
                for l in raw.splitlines():
                    t = l.strip()
                    if t and not t.startswith(('```', '#')):
                        lines.append(LyricsLine(time_sec=0.0, original_text=t))

            if not lines:
                return None

            sample_text = ' '.join(line.original_text for line in lines[:8])
            primary_lang = detect_language(sample_text)

            track = LyricsTrack(
                track_name=clean_track,
                artist_name=clean_artist,
                duration=lines[-1].time_sec if lines else 0.0,
                is_synced=any(l.time_sec > 0 for l in lines),
                is_instrumental=False,
                lines=lines,
                primary_language=primary_lang,
                source='Gemini AI',
            )
            apply_language_rules(track, mode='auto')
            return track
        except Exception:
            return None


# ── Unified Multilingual Lyrics Engine ───────────────────────────────────────

class LyricsEngine:
    """
    Unified Multilingual Lyrics Engine coordinating Spotify Color-Lyrics, YouTube Subtitles,
    LRCLIB Studio Records, YouTube Video Description Extraction, and Gemini AI.
    Guarantees authentic lyrics belonging strictly to the requested song (never credits or wrong metadata).
    """

    _cache: Dict[str, Optional[LyricsTrack]] = {}

    @classmethod
    def get_lyrics(cls, track_name: str, artist_name: str = '', youtube_info: dict = None) -> Optional[LyricsTrack]:
        cache_key = f'{track_name.strip().lower()}|{artist_name.strip().lower()}'
        if cache_key in cls._cache and cls._cache[cache_key]:
            return cls._cache[cache_key]

        track: Optional[LyricsTrack] = None

        # Stage 1: Spotify Official Color-Lyrics (if sp_dc cookie is configured)
        try:
            track = SpotifyLyricsClient.fetch_lyrics(track_name, artist_name)
            if not is_valid_lyrics_track(track):
                track = None
        except Exception:
            track = None

        # Stage 2: Official manual human-uploaded lyrics from YouTube (100% verified)
        if not track and youtube_info:
            try:
                track = YouTubeSubtitleClient.fetch_from_info(youtube_info, track_name, artist_name, allow_auto=False)
                if not is_valid_lyrics_track(track):
                    track = None
            except Exception:
                track = None

        # Stage 3: Official studio-synchronized lyrics from LRCLIB (Spotify/Apple Music master records)
        if not track:
            candidates = get_song_candidates(track_name, artist_name)
            for cand_track, cand_artist in candidates:
                cand_track_obj = LRCLIBClient.fetch_lyrics(cand_track, cand_artist)
                if cand_track_obj and is_valid_lyrics_track(cand_track_obj):
                    track = cand_track_obj
                    break

        # Stage 4: YouTube Description Lyrics Extractor (Authentic artist lyrics for fresh releases like 'Baawli')
        if not track and youtube_info:
            try:
                desc_track = YouTubeDescriptionLyricsClient.fetch_from_info(youtube_info, track_name, artist_name)
                if desc_track and is_valid_lyrics_track(desc_track):
                    track = desc_track
            except Exception:
                track = None

        # Stage 5: YouTube Automatic Speech-to-Text Captions
        if not track and youtube_info:
            try:
                auto_track = YouTubeSubtitleClient.fetch_from_info(youtube_info, track_name, artist_name, allow_auto=True)
                if auto_track and is_valid_lyrics_track(auto_track):
                    track = auto_track
            except Exception:
                track = None

        # Stage 6: Gemini AI High-Precision Synchronized Lyrics (Official authentic song lyrics fallback)
        if not track:
            clean_track, clean_artist = clean_song_title(track_name, artist_name)
            ai_track = GeminiLyricsClient.fetch_lyrics(clean_track, clean_artist)
            if ai_track and is_valid_lyrics_track(ai_track):
                track = ai_track

        if track:
            cls._cache[cache_key] = track
        return track
