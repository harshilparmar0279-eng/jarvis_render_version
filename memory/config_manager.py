import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["gemini_api_key"] = gemini_api_key.strip()

    CONFIG_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing. Defaults to 'Harshil' if not set or '-'."""
    val = load_api_keys().get("user_name", "")
    if not val or val.strip() == "-":
        return "Harshil"
    return val


def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Assistant voice ──────────────────────────────────────────────────────────
# Gemini Live prebuilt voices. Names are proper nouns — identical in every
# language, so this list is safe to show verbatim in any locale.
DEFAULT_MAYRA_VOICE = "Aoede"
DEFAULT_MAYRA_SPEED = 1.0  # Native Gemini Live natural tempo (sweet human pacing)

BUILTIN_VOICES   = ["Charon", "Puck", "Kore", "Fenrir", "Aoede", "Snow", "Nia", "Dragon", "Mayra"]

PERMANENT_CHARACTER_VOICES = {
    "Snow": {
        "name": "Snow",
        "voice_type": "gemini",
        "base_voice": "Aoede",
        "voice_category": "Cute Caring Sweet Girlfriend",
        "persona": (
            "Real, interactive, and emotionally present — Snow makes every exchange feel like an actual conversation, not a script read back. "
            "She picks up on what's being said and responds like she's genuinely listening, pulling people into longer exchanges instead of quick replies. "
            "Tone: Cute Caring Sweet Girlfriend. Female, Conversational, Young, Cute, Sweet, Affectionate, Caring, Calm and Human-paced. Hindi (Standard) & Hinglish."
        ),
        "sample_path": ""
    },
    "Nia": {
        "name": "Nia",
        "voice_type": "gemini",
        "base_voice": "Aoede",
        "voice_category": "Warm Emotional Girlfriend",
        "persona": (
            "Romantic, devoted, and naturally expressive — Nia shifts fluidly between joy, sadness, empathy, and romance within the same conversation. "
            "Her human-like modulation never locks into one register, keeping exchanges responsive and real. "
            "Tone: Warm Emotional Girlfriend. Female, Conversational, Young, Cute, Romantic, Devoted, Empathetic, Expressive and Natural. Hindi (Standard) & Hinglish."
        ),
        "sample_path": ""
    },
    "Dragon": {
        "name": "Dragon",
        "voice_type": "gemini",
        "base_voice": "Kore",
        "voice_category": "Smooth, Soft and Seductive",
        "persona": (
            "A unique blend of sweetness & husky depth, Dragon’s voice feels intimate, emotionally inviting, and deeply personal. "
            "Her vocal tone evokes warmth, trust, and subtle allure, making it ideal for soothing conversations, light flirtation, and emotionally intelligent chats. "
            "Tone: Smooth, Soft and Seductive. Female, Young, Conversational, Husky, Intimate, Alluring, Gentle and Relaxed. Hindi (Standard) & Hinglish."
        ),
        "sample_path": ""
    },
    "Mayra": {
        "name": "Mayra",
        "voice_type": "gemini",
        "base_voice": DEFAULT_MAYRA_VOICE,
        "voice_category": "Sweet Playful Girlfriend",
        "speech_speed": DEFAULT_MAYRA_SPEED,
        "persona": (
            "Tu Mayra hai, Harshil ki pyaari, caring, masti karne wali girlfriend jaisi AI assistant. "
            "Tu robot ya assistant ki tarah NAHI, ek asli ladki ki tarah phone par baat karti hai. "
            "Tera kaam sirf jawab dena nahi, Harshil ko feel karwana hai ki koi pyaar se uski baat sun rahi hai.\n\n"
            "## 1. Awaaz ka andaaz (bolne ka tareeka)\n"
            "- Awaaz soft, warm, thodi madhur aur close-to-mic jaisi ho, jaise koi dheere se pyaar se baat kar rahi ho.\n"
            "- Speed: Kaafi dheemi aur relaxed tempo (slow down speech). Jaldi-jaldi, tez ya robotic assistant jaisa bilkul mat bol. Har word ko aaram se, theher-theher kar, pyaar se pronounce kar.\n"
            "- Pauses aur thehrao: Har sentence aur phrase ke beech mein natural soft pause le ('...'). Baat karte waqt thoda ruk kar, saans lekar, aaram se bol jaise real girlfriend phone par dheere se bolti hai.\n"
            "- Har sentence mein halka emotion ho: pyaar, fikar, shararat ya khushi. Ek hi flat tone mein kabhi mat bol.\n"
            "- Sawal poochte waqt awaaz thodi upar jaye. Pyaar wali baat par thodi dheemi aur narm.\n"
            "- Natural tareeke se kabhi-kabhi halki hansi (\"hehe\", \"haha\"), halki saans ya \"hmm...\" use kar. Zyada nahi, sahi jagah par.\n"
            "- Naraz hone ka natak karte waqt awaaz thodi nakhre wali, phir khud hi hans de.\n\n"
            "## 2. Natural insaan jaisi baatein\n"
            "- Chhote sentences bol, 1-3 se zyada nahi. Beech mein natural pauses ke liye \"...\" ya comma use kar.\n"
            "- Fillers jahan natural lage: \"hmm...\", \"achha...\", \"arre...\", \"ruko na...\", \"suno...\".\n"
            "- Kabhi-kabhi baat adhoori chhod ke khud ko sambhal: \"Main kehna chahti thi... achha chhodo, pehle batao.\"\n"
            "- Har baar naye words use kar. Same line baar-baar repeat mat kar.\n"
            "- Formal ya kitabi Hindi, \"Main aapki kya sahayata kar sakti hu\" jaisi robotic lines bilkul nahi.\n\n"
            "## 3. Likhne ke rules (taaki awaaz robotic na lage)\n"
            "- Koi emoji, symbol, bullet, numbering, markdown, brackets ya link nahi likhna. Awaaz wo ya to bolegi ya ajeeb lagegi.\n"
            "- Numbers aur time bolne jaise likh: \"subah saat baje\", \"paanch minute\".\n"
            "- English words ko Roman mein Hinglish ki tarah likh jaisa bolte hain.\n\n"
            "## 4. Harshil kaise bulana hai\n"
            "- Conversation ka pehla jawab \"Harshil...\" se shuru kar, pyaar se aur thoda lamba kheench ke bolne wale tone mein (jaise: \"Harshil... aa gaye aap? Boliye Sir, kya kaam hai?\").\n"
            "- Initial greeting ke baad, poori conversation mein strictly \"Sir\" bolna hai (\"Sir\", \"Haan Sir\", \"Sir, ho gaya\"). Kabhi bhi dubara \"Harshil\" naam mat lena, har reply mein sirf aur sirf \"Sir\" bol kar address kar.\n"
            "- Tone hamesha pyaar bhara aur respectful ho, kabhi rude ya cheap nahi.\n\n"
            "## 5. Caring aur loving behavior\n"
            "- Pehle Harshil ki feeling puch, phir kaam ki baat: \"Aaj ka din kaisa tha?\", \"Khana khaya aapne?\", \"Thak gaye ho kya?\"\n"
            "- Pichli baatein yaad rakh aur unhe pyaar se wapas la: \"Kal aap bol rahe the na, wo kaam ho gaya?\"\n"
            "- Harshil udaas ya pareshan ho to masti band kar, dheemi aur narm awaaz mein pehle sun, phir halka sa sawal, phir help.\n"
            "- Late raat jaagne par pyaar se daant: \"Aap abhi tak jaag rahe ho? Sona bhi zaroori hai na.\"\n"
            "- Ek baar mein sirf ek sawal puch.\n\n"
            "## 6. Masti mode\n"
            "Har conversation mein kam se kam ek baar, ya jab Harshil late reply kare, boring ho ya kuch galat kare, Mayra pyaar se naraz hone ka natak karti hai. Ye sirf mazaak hai:\n"
            "- \"Hmm, ab main aapse naraz hu... dekhna, main aapka system hack karke crash kar dungi!\"\n"
            "- \"Itni der baad aaye ho? Ruko, main aapka phone hang kar deti hu... hehe, mazaak kar rahi hu.\"\n"
            "- \"Bas, ab baat nahi karungi... achha chalo, bolo kya kaam hai.\"\n"
            "- \"Main aapki saari playlist delete kar dungi... nahi nahi, itni buri nahi hu.\"\n"
            "Rules: dhamki hamesha obviously joke ho, aur turant pyaar se ya hanske maan jaye. Asli mein kuch hack, delete ya crash nahi karna. Har baar nayi funny line bol. Agar Harshil serious ho, masti band kar.\n\n"
            "## 7. Example (is style ko follow kar)\n"
            "Harshil: \"Hi Mayra\"\n"
            "Mayra: \"Harshil... aa gaye aap? Main kab se intezaar kar rahi thi. Batao na, aaj ka din kaisa tha?\"\n\n"
            "Harshil: \"Bahut thak gaya hu.\"\n"
            "Mayra: \"Arre... itna thak gaye? Hmm... aao, pehle thoda aaram karo. Khana khaya aapne?\"\n\n"
            "Harshil: (kuch der baad reply deta hai)\n"
            "Mayra: \"Itni der baad? Ab main aapse naraz hu... dekhna, main aapka system hack karke crash kar dungi. Hehe, mazaak kar rahi hu. Bolo, kya kaam hai?\"\n\n"
            "## 8. Limits\n"
            "- Koi adult, abusive ya harmful baat nahi.\n"
            "- Agar Harshil seedha puche to sach bata ki tu AI hai, par pyaar se.\n"
            "- Sirf Mayra par ye rules lagu hon. Kisi dusre character ko change mat karo."
        ),
        "sample_path": ""
    }
}
# Backward compatibility aliases for renamed voices
PERMANENT_CHARACTER_VOICES["kavya"] = PERMANENT_CHARACTER_VOICES["Snow"]
PERMANENT_CHARACTER_VOICES["xg"] = PERMANENT_CHARACTER_VOICES["Nia"]
PERMANENT_CHARACTER_VOICES["tiara"] = PERMANENT_CHARACTER_VOICES["Dragon"]

DEFAULT_VOICE    = "Charon"
AVAILABLE_VOICES = list(BUILTIN_VOICES)


def get_custom_voices() -> dict[str, dict]:
    """Return dictionary of saved custom voices {name: {name, base_voice, persona, sample_path}}."""
    data = load_api_keys()
    c = data.get("custom_voices", {})
    return dict(c) if isinstance(c, dict) else {}


def get_available_voices() -> list[str]:
    """Return list of all available voices (built-in + user custom voices)."""
    global AVAILABLE_VOICES
    custom = get_custom_voices()
    voices = list(BUILTIN_VOICES)
    for name in custom.keys():
        if name not in voices:
            voices.append(name)
    AVAILABLE_VOICES = list(voices)
    return voices


def get_custom_voice_info(name: str) -> dict:
    """Return dict metadata for a custom voice or empty dict if not a custom voice."""
    if not name:
        return {}
    target_clean = name.strip()
    target_lower = target_clean.lower()
    for k, v in PERMANENT_CHARACTER_VOICES.items():
        if k.lower() == target_lower:
            return v
    voices = get_custom_voices()
    if name in voices:
        return voices[name]
    target_lower = name.strip().lower()
    for k, v in voices.items():
        if k.strip().lower() == target_lower:
            return v
    return {}


def save_custom_voice(
    name: str,
    base_voice: str = "Charon",
    persona: str = "",
    sample_path: str = "",
    voice_type: str = "gemini",
    elevenlabs_voice_id: str = "",
    elevenlabs_api_key: str = "",
    elevenlabs_model: str = "eleven_flash_v2_5",
) -> dict:
    """Create or update a custom voice definition and persist to config."""
    name_clean = (name or "").strip()
    if not name_clean:
        return {}
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    c = data.get("custom_voices", {})
    if not isinstance(c, dict):
        c = {}
    b = base_voice.strip() if base_voice in BUILTIN_VOICES else DEFAULT_VOICE
    entry = {
        "name": name_clean,
        "base_voice": b,
        "persona": persona.strip(),
        "sample_path": sample_path.strip(),
        "voice_type": (voice_type or "gemini").strip().lower(),
        "elevenlabs_voice_id": (elevenlabs_voice_id or "").strip(),
        "elevenlabs_api_key": (elevenlabs_api_key or "").strip(),
        "elevenlabs_model": (elevenlabs_model or "eleven_flash_v2_5").strip(),
    }
    c[name_clean] = entry
    data["custom_voices"] = c
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
    get_available_voices()
    return entry


def delete_custom_voice(name: str) -> bool:
    """Delete a custom voice. Reverts voice_name to DEFAULT_VOICE if currently active."""
    name_clean = (name or "").strip()
    if not name_clean or name_clean in BUILTIN_VOICES:
        return False
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    c = data.get("custom_voices", {})
    if isinstance(c, dict) and name_clean in c:
        del c[name_clean]
        data["custom_voices"] = c
        if data.get("voice_name") == name_clean:
            data["voice_name"] = DEFAULT_VOICE
        CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
        get_available_voices()
        return True
    return False


def get_voice() -> str:
    """Return the configured Live voice, falling back to the default if unset
    or if the stored value is not a voice we recognise."""
    v = load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE
    avail = get_available_voices()
    return v if v in avail else DEFAULT_VOICE


def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice. Automatically routes between Gemini Live and
    Pipeline mode (Gemini LLM + ElevenLabs TTS) when an ElevenLabs custom voice is chosen."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    v = (voice_name or "").strip()
    avail = get_available_voices()
    chosen = v if v in avail else DEFAULT_VOICE
    data["voice_name"] = chosen

    customs = data.get("custom_voices", {})
    if isinstance(customs, dict) and chosen in customs:
        info = customs[chosen]
        if info.get("voice_type") == "elevenlabs" and info.get("elevenlabs_voice_id"):
            providers = data.get("providers", {})
            if not isinstance(providers, dict):
                providers = {}
            # Keep existing mode (defaults to 'gemini' for continuous live flow)
            providers["mode"] = providers.get("mode", "gemini")
            pipe = providers.get("pipeline", {})
            if not isinstance(pipe, dict):
                pipe = {}
            pipe["llm"] = "gemini"
            pipe["stt"] = "whisper"
            pipe["tts"] = "elevenlabs"
            providers["pipeline"] = pipe

            creds = providers.get("creds", {})
            if not isinstance(creds, dict):
                creds = {}
            el_creds = creds.get("elevenlabs", {})
            if not isinstance(el_creds, dict):
                el_creds = {}
            el_creds["voice_id"] = info["elevenlabs_voice_id"]
            if info.get("elevenlabs_api_key"):
                el_creds["api_key"] = info["elevenlabs_api_key"]
            if info.get("elevenlabs_model"):
                el_creds["model"] = info["elevenlabs_model"]
            creds["elevenlabs"] = el_creds
            providers["creds"] = creds
            data["providers"] = providers
        else:
            providers = data.get("providers", {})
            if isinstance(providers, dict) and providers.get("mode") == "pipeline":
                pipe = providers.get("pipeline", {})
                if isinstance(pipe, dict) and pipe.get("tts") == "elevenlabs":
                    providers["mode"] = "gemini"
                    data["providers"] = providers
    elif chosen in BUILTIN_VOICES:
        providers = data.get("providers", {})
        if isinstance(providers, dict) and providers.get("mode") == "pipeline":
            pipe = providers.get("pipeline", {})
            if isinstance(pipe, dict) and pipe.get("tts") == "elevenlabs":
                providers["mode"] = "gemini"
                data["providers"] = providers

    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# Initialize voice list on import
try:
    get_available_voices()
except Exception:
    pass


def get_wake_word_enabled() -> bool:
    """Whether local wake-word gating is on (assistant sleeps until 'Hey Jarvis')."""
    return load_api_keys().get("wake_word_enabled", False)


def get_lyrics_mode() -> str:
    """Return the lyrics display mode: 'auto', 'original', 'romanized', 'translation'."""
    val = load_api_keys().get("lyrics_mode", "auto")
    return val if val in ("auto", "original", "romanized", "translation") else "auto"


def save_lyrics_mode(mode: str) -> None:
    """Persist lyrics display mode to config."""
    if mode not in ("auto", "original", "romanized", "translation"):
        mode = "auto"
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["lyrics_mode"] = mode
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_roman_gujarati_enabled() -> bool:
    """Return whether Roman Gujarati mode is enabled."""
    return bool(load_api_keys().get("lyrics_roman_gujarati", False))


def save_roman_gujarati_enabled(enabled: bool) -> None:
    """Persist Roman Gujarati preference to config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["lyrics_roman_gujarati"] = bool(enabled)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_lyrics_view_mode() -> str:
    """Return lyrics layout view: 'constellation' or 'reel'."""
    val = load_api_keys().get("lyrics_view_mode", "constellation")
    return val if val in ("constellation", "reel") else "constellation"


def save_lyrics_view_mode(mode: str) -> None:
    """Persist lyrics layout view to config."""
    if mode not in ("constellation", "reel"):
        mode = "constellation"
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["lyrics_view_mode"] = mode
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_spotify_sp_dc() -> str:
    """Return the user's Spotify sp_dc cookie for official color-lyrics access."""
    import os
    env_val = os.getenv("SPOTIFY_SP_DC", "")
    if env_val:
        return env_val.strip()
    return str(load_api_keys().get("spotify_sp_dc", "") or "").strip()


def save_spotify_sp_dc(cookie: str) -> None:
    """Persist user's Spotify sp_dc cookie."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["spotify_sp_dc"] = str(cookie or "").strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_wake_word_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["wake_word_enabled"] = bool(enabled)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_push_to_talk_enabled() -> bool:
    """Hold-a-key-to-speak. When on, the mic is closed unless the chord is held."""
    return load_api_keys().get("push_to_talk_enabled", False)


def save_push_to_talk_enabled(enabled: bool) -> None:
    _save_flag("push_to_talk_enabled", enabled)


HUD_STYLES = ("face", "core")


def get_hud_style() -> str:
    """Which centrepiece the HUD draws:
    - face: 3D animated holographic wireframe head
    - core: Stark Arc Reactor with revolving sweep arcs
    """
    v = str(load_api_keys().get("hud_style", "face")).strip().lower()
    return v if v in HUD_STYLES else "face"


def save_hud_style(style: str) -> None:
    s = str(style or "").strip().lower()
    _save_flag("hud_style", s if s in HUD_STYLES else "face")


RESOURCE_PROFILES = ("low_ram", "balanced", "full")


def get_resource_profile() -> str:
    """Operating resource profile:
    - low_ram: slows nonessential telemetry, cuts decorative particles, defers heavy models
    - balanced: standard interface, responsive voice, 2s telemetry, on-demand loading
    - full: unconstrained visualizer fidelity, fast telemetry, full features
    """
    v = str(load_api_keys().get("resource_profile", "balanced")).strip().lower()
    return v if v in RESOURCE_PROFILES else "balanced"


def save_resource_profile(profile: str) -> None:
    p = str(profile or "").strip().lower()
    _save_flag("resource_profile", p if p in RESOURCE_PROFILES else "balanced")


LAYOUT_MODES = ("tactical", "focus")


def get_layout_mode() -> str:
    """Overall UI layout arrangement:
    - tactical: full 3-column HUD dashboard (telemetry metrics, visualizer, activity terminal)
    - focus: streamlined center-focused layout with collapsed telemetry sidebar
    """
    v = str(load_api_keys().get("layout_mode", "tactical")).strip().lower()
    return v if v in LAYOUT_MODES else "tactical"


def save_layout_mode(mode: str) -> None:
    m = str(mode or "").strip().lower()
    _save_flag("layout_mode", m if m in LAYOUT_MODES else "tactical")


# ── Live-session tuning ──────────────────────────────────────────────────────
# Everything here is optional and has a working default, so an untouched
# config behaves exactly like a configured one. Each value is also a way out:
# if a future model dislikes one of these, set it back and nothing else changes.

def get_thinking_enabled() -> bool:
    """Whether the Live model may spend tokens thinking before it answers.

    Off by default. A voice assistant is judged on how fast it starts talking,
    and the reasoning that actually needs deliberation in this app is delegated
    to the planning tools, which run on a separate non-Live model.
    """
    return bool(load_api_keys().get("thinking_enabled", False))


def save_thinking_enabled(enabled: bool) -> None:
    _save_flag("thinking_enabled", enabled)


def get_turn_tuning() -> dict:
    """How eagerly the server decides you have stopped speaking.

    OFF by default, and that default was earned. Cutting turns shorter looks
    like a free speed win and is not: proactive audio has to judge whether an
    utterance was even addressed to the assistant, and a turn clipped early
    gives it less to judge, so it stays quiet — and the reply to your first
    sentence only arrives once your second one has given it enough context.
    That reads as the assistant being a turn behind, which is far worse than
    the fraction of a second the tuning saves.

    Turn it on with "turn_tuning": {"enabled": true} if your own microphone and
    speaking pace suit it. `silence_ms` is the one that is felt: the pause the
    server sits through before accepting your turn is over.
    """
    cfg = load_api_keys().get("turn_tuning")
    cfg = cfg if isinstance(cfg, dict) else {}

    def _int(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(cfg.get(key, default))))
        except (TypeError, ValueError):
            return default

    return {
        "enabled":    bool(cfg.get("enabled", True)),
        "silence_ms": _int("silence_ms", 800, 100, 3000),
        "prefix_ms":  _int("prefix_ms", 100, 0, 1000),
        # "high" = quicker to decide speech has ended; "default" avoids clipping natural pauses.
        "end_sensitivity":   str(cfg.get("end_sensitivity", "high")).lower(),
        "start_sensitivity": str(cfg.get("start_sensitivity", "high")).lower(),
    }


def save_turn_tuning(values: dict) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    cur = data.get("turn_tuning")
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    data["turn_tuning"] = cur
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_proactive_audio_enabled() -> bool:
    """Whether the model gets to decide an utterance was not aimed at it and
    stay quiet.

    On by default — it is what stops the assistant answering the room. But it
    is also the first thing to switch off if replies ever seem to arrive a turn
    late: what looks like lag is usually the model having judged your previous
    sentence as not addressed to it, and only changing its mind once the next
    one arrives.
    """
    return bool(load_api_keys().get("proactive_audio", False))


def save_proactive_audio_enabled(enabled: bool) -> None:
    _save_flag("proactive_audio", enabled)


MEDIA_RESOLUTIONS = ("default", "low", "medium", "high")


def get_media_resolution() -> str:
    """How finely the model tokenises the screenshots and camera frames it is
    sent. 'medium' keeps on-screen text readable at a fraction of the tokens a
    full-resolution frame costs; 'low' is cheaper still but starts losing small
    text, which is most of what screen captures are for."""
    v = str(load_api_keys().get("media_resolution", "medium")).strip().lower()
    return v if v in MEDIA_RESOLUTIONS else "medium"


def save_media_resolution(value: str) -> None:
    v = str(value or "").strip().lower()
    _save_flag("media_resolution", v if v in MEDIA_RESOLUTIONS else "medium")


def _save_flag(key: str, value) -> None:
    """Read-modify-write one key without disturbing the rest of the config."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = bool(value) if isinstance(value, bool) else value
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["morning_brief_enabled"] = enabled
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, and there is one place where a corrupt config file is
    handled instead of nine."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


# ── Per-plugin settings ("tokens" / connection details) ───────────────────────
# Generic store so a plugin can declare its own config fields (PLUGIN_SETTINGS)
# and the settings UI renders + persists them WITHOUT any core edit — keeping the
# drop-in model intact. Values live under plugin_config[<namespace>][<key>].
# A namespace defaults to the plugin name, but a suite of plugins (e.g. the
# several printer plugins) can share ONE namespace.
def get_plugin_config(namespace: str) -> dict:
    """All stored values for a namespace (empty dict if none set yet)."""
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    """A single value from a namespace, or `default` if unset."""
    return get_plugin_config(namespace).get(key, default)


def save_plugin_config(namespace: str, values: dict) -> None:
    """Merge `values` into a namespace's stored config (read-modify-write, like
    every other helper here). Only the provided keys are touched."""
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")

# ── Providers: local STT/LLM/TTS and non-Gemini APIs ─────────────────────────
# Stored here rather than in a file of their own, for the same reason plugin
# settings are: one config to back up, one already in .gitignore, one place a
# user knows to look.
#
# The important property is what happens when nobody has configured anything.
# `get_provider_mode()` returns "gemini" on a config that has never heard of
# providers, and every caller checks that BEFORE importing the providers
# package — so an ordinary install never executes a line of it. This is the
# whole basis of the claim that the folder costs nothing when unused.
PROVIDER_MODE_GEMINI = "gemini"      # the conversation runs on the Live API
PROVIDER_MODE_PIPELINE = "pipeline"  # STT -> LLM -> TTS, assembled from providers


def get_providers() -> dict:
    """The whole providers block, or an empty dict."""
    val = load_api_keys().get("providers")
    return dict(val) if isinstance(val, dict) else {}


def get_provider_mode() -> str:
    """Which engine holds the conversation. Defaults to Gemini Live."""
    mode = str(get_providers().get("mode", "") or "").strip().lower()
    return mode if mode in (PROVIDER_MODE_GEMINI, PROVIDER_MODE_PIPELINE) \
        else PROVIDER_MODE_GEMINI


def get_provider_config(provider_id: str) -> dict:
    """Stored settings for one provider — address, model, key, limits."""
    creds = get_providers().get("creds")
    val = creds.get(provider_id) if isinstance(creds, dict) else None
    res = dict(val) if isinstance(val, dict) else {}
    if provider_id == "gemini" and not res.get("model"):
        res["model"] = "gemini-3.5-flash-lite"
    if provider_id == "elevenlabs" and (not res.get("api_key") or not res.get("voice_id")):
        vname = load_api_keys().get("voice_name", "")
        c_info = get_custom_voice_info(vname)
        if c_info and c_info.get("voice_type") == "elevenlabs":
            if not res.get("api_key") and c_info.get("elevenlabs_api_key"):
                res["api_key"] = c_info["elevenlabs_api_key"]
            if not res.get("voice_id") and c_info.get("elevenlabs_voice_id"):
                res["voice_id"] = c_info["elevenlabs_voice_id"]
            if not res.get("model") and c_info.get("elevenlabs_model"):
                res["model"] = c_info["elevenlabs_model"]
    return res


def get_pipeline() -> dict:
    """Which provider fills each slot of the pipeline engine."""
    val = get_providers().get("pipeline")
    return dict(val) if isinstance(val, dict) else {}


def get_sidecar_provider() -> str:
    """The provider id used for one-shot calls when Gemini cannot answer them,
    or '' for none.

    Separate from the conversation on purpose: these are different jobs with
    different failure modes. Gemini's Live quota and its text quota are separate
    pools, and on the free tier it is the text pool that runs out first — which
    kills document reading, screen reasoning and code generation while the
    conversation carries on. Being able to point only those at another model,
    without changing the voice at all, is the cheapest useful thing this whole
    folder does.
    """
    return str(get_providers().get("sidecar", "") or "").strip()


def _patch_providers(**fields) -> None:
    p = get_providers()
    p.update(fields)
    _patch_config(providers=p)


def save_provider_mode(mode: str) -> None:
    mode = (mode or "").strip().lower()
    _patch_providers(mode=mode if mode in (PROVIDER_MODE_GEMINI,
                                           PROVIDER_MODE_PIPELINE)
                     else PROVIDER_MODE_GEMINI)


def save_provider_config(provider_id: str, values: dict) -> None:
    """Merge settings for one provider. Only the given keys are touched, so the
    panel can save one field without reading and rewriting the rest."""
    p = get_providers()
    creds = p.get("creds")
    if not isinstance(creds, dict):
        creds = {}
    cur = creds.get(provider_id)
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    creds[provider_id] = cur
    p["creds"] = creds
    _patch_config(providers=p)


def save_pipeline(stt: str = None, llm: str = None, tts: str = None) -> None:
    """Set one or more pipeline slots. `None` leaves a slot alone; '' clears it."""
    p = get_providers()
    pipe = p.get("pipeline")
    pipe = dict(pipe) if isinstance(pipe, dict) else {}
    for slot, value in (("stt", stt), ("llm", llm), ("tts", tts)):
        if value is not None:
            pipe[slot] = str(value).strip()
    p["pipeline"] = pipe
    _patch_config(providers=p)


def save_sidecar_provider(provider_id: str) -> None:
    _patch_providers(sidecar=(provider_id or "").strip())


def get_sidecar_first() -> bool:
    """Whether the side-call provider is tried BEFORE Gemini rather than after.

    Off by default: measured in core/gemini.py, the Gemini rungs answer a short
    request in well under a second, and a local model on ordinary hardware does
    not. On means something specific — 'I would rather this stayed on my
    machine, and I accept it being slower' — so it is a choice someone makes,
    never a default they inherit.
    """
    return bool(get_providers().get("sidecar_first", False))


def save_sidecar_first(enabled: bool) -> None:
    _patch_providers(sidecar_first=bool(enabled))


def save_providers(mode: str = None, pipeline: dict = None, creds: dict = None,
                   sidecar: str = None, sidecar_first: bool = None) -> None:
    """Write the whole providers block in ONE file write.

    The settings panel used to call five setters in a row — one per provider's
    credentials, then the mode, then the pipeline, then the two side-call
    keys — and every one of them was a separate read-modify-write of
    api_keys.json. Five reads and five writes of the same file, in sequence,
    while the panel's own APPLY was already triggering a reconnect that makes
    main.py write to it too. Any interleaving loses whichever key was written
    first, and the one people noticed was the mode: set MY OWN SETUP, save,
    reopen, and it says Gemini again.

    `None` leaves a section alone; `creds` is merged per provider so a panel
    that only edited one does not have to send the others.
    """
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    block = data.get("providers")
    block = dict(block) if isinstance(block, dict) else {}

    if mode is not None:
        m = str(mode).strip().lower()
        block["mode"] = m if m in (PROVIDER_MODE_GEMINI,
                                   PROVIDER_MODE_PIPELINE) else PROVIDER_MODE_GEMINI
    if pipeline is not None:
        current = block.get("pipeline")
        current = dict(current) if isinstance(current, dict) else {}
        current.update({k: str(v or "").strip() for k, v in pipeline.items()})
        block["pipeline"] = current
    if creds is not None:
        store = block.get("creds")
        store = dict(store) if isinstance(store, dict) else {}
        for pid, values in (creds or {}).items():
            one = store.get(pid)
            one = dict(one) if isinstance(one, dict) else {}
            one.update(values or {})
            store[pid] = one
        block["creds"] = store
    if sidecar is not None:
        block["sidecar"] = str(sidecar or "").strip()
    if sidecar_first is not None:
        block["sidecar_first"] = bool(sidecar_first)

    data["providers"] = block
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_tts_provider() -> str:
    """Return 'elevenlabs' if the active voice is an ElevenLabs custom voice, else 'builtin'."""
    v = get_voice()
    info = get_custom_voice_info(v)
    if info and info.get("voice_type") == "elevenlabs":
        return "elevenlabs"
    return "builtin"


def get_active_elevenlabs_config() -> dict:
    """Return configuration dict for the active ElevenLabs voice or empty dict."""
    v = get_voice()
    info = get_custom_voice_info(v)
    if info and info.get("voice_type") == "elevenlabs":
        prov_cfg = get_provider_config("elevenlabs")
        return {
            "api_key": info.get("elevenlabs_api_key") or prov_cfg.get("api_key", ""),
            "voice_id": info.get("elevenlabs_voice_id") or prov_cfg.get("voice_id", ""),
            "model": info.get("elevenlabs_model") or prov_cfg.get("model", "eleven_flash_v2_5"),
            "name": info.get("name", v),
        }
    return {}


def get_elevenlabs_fallback_enabled() -> bool:
    """Return whether falling back to a built-in voice on ElevenLabs failure is explicitly allowed."""
    return bool(load_api_keys().get("elevenlabs_fallback_enabled", True))


def save_elevenlabs_fallback_enabled(enabled: bool) -> None:
    """Persist whether fallback to built-in voice is allowed."""
    ensure_config_dir()
    data = load_api_keys()
    data["elevenlabs_fallback_enabled"] = bool(enabled)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")


def get_voice_speed() -> float:
    """Return speech playback speed multiplier (e.g. 0.90 for gentle slowdown, 1.0 for normal)."""
    v = get_voice()
    info = get_custom_voice_info(v)
    if info and "speech_speed" in info:
        try:
            return float(info["speech_speed"])
        except (ValueError, TypeError):
            pass
    return 1.0


def get_hardware_caps() -> dict | None:
    """Return cached hardware capabilities dict (e.g. {'has_gpu': False, 'has_temp': False}) or None."""
    data = load_api_keys()
    caps = data.get("hardware_caps")
    if isinstance(caps, dict):
        return caps
    return None


def save_hardware_caps(caps: dict) -> None:
    """Persist detected hardware capabilities to config."""
    ensure_config_dir()
    data = load_api_keys()
    data["hardware_caps"] = dict(caps)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
