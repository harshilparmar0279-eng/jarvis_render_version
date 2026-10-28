"""
render_server.py — Cloud Entrypoint for JARVIS on Render.com
Runs 24/7 headless AI Assistant + Mobile PWA Dashboard for Phone use.
"""

import os
import sys
import json
import time
import base64
import asyncio
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Ensure headless Qt mode if any module touches Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def get_gemini_api_key() -> str:
    """Retrieve Gemini API key from environment variable or local config."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key

    key_file = BASE_DIR / "config" / "api_keys.json"
    if key_file.exists():
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("gemini_api_key", "").strip()
        except Exception:
            pass
    return ""


def load_cloud_prompt() -> str:
    """Load system prompt with Mayra / companion rules."""
    prompt_file = BASE_DIR / "core" / "prompt.txt"
    base_prompt = ""
    if prompt_file.exists():
        try:
            base_prompt = prompt_file.read_text(encoding="utf-8")
        except Exception:
            pass

    cloud_context = (
        "\n\n[CLOUD DEPLOYMENT ENVIRONMENT: RENDER.COM]\n"
        "- You are running as a 24/7 cloud assistant for Harshil.\n"
        "- The user is accessing you from their mobile phone app.\n"
        "- The user's physical laptop is currently offline / closed.\n"
        "- You have full AI conversation, memory, web knowledge, and persona capability.\n"
        "- If the user commands you to open physical laptop desktop apps (like local Notepad, local Calculator, or local WhatsApp Desktop app), "
        "politely inform them in sweet Hinglish that their laptop is offline, but you are always here 24/7 on their phone for conversation, questions, and reminders."
    )
    return base_prompt + cloud_context


async def generate_speech_base64(text: str, voice: str = "hi-IN-SwaraNeural") -> str:
    """Generate audio base64 via edge_tts for phone playback."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        full_audio = b"".join(audio_chunks)
        return base64.b64encode(full_audio).decode("utf-8")
    except Exception as e:
        print(f"[TTS] Warning: Failed to generate audio ({e})")
        return ""


async def process_cloud_commands(srv, api_key: str):
    """Background worker processing commands from the phone dashboard."""
    from google import genai
    from google.genai import types

    sys_prompt = load_cloud_prompt()
    client = genai.Client(api_key=api_key)

    chat = client.aio.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=sys_prompt,
            temperature=0.7,
        ),
    )

    print("[CloudBrain] Gemini Cloud Session initialized and waiting for phone commands...")

    while True:
        try:
            text = await srv._command_queue.get()
            if not text:
                continue

            print(f"[PhoneCommand] User: {text}")
            await srv.broadcast({"type": "transcript", "role": "user", "text": text})

            # Call Gemini
            response = await chat.send_message(text)
            reply = response.text or ""
            print(f"[CloudBrain] JARVIS: {reply}")

            # Generate audio for phone speaker
            audio_b64 = await generate_speech_base64(reply)

            # Broadcast reply and audio to phone
            msg_payload = {
                "type": "transcript",
                "role": "model",
                "text": reply,
            }
            if audio_b64:
                msg_payload["audio"] = audio_b64

            await srv.broadcast(msg_payload)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[CloudBrain] Error: {e}")
            await srv.broadcast({
                "type": "transcript",
                "role": "model",
                "text": f"Error: {e}",
            })


def main():
    port = int(os.environ.get("PORT", 10000))
    api_key = get_gemini_api_key()

    if not api_key:
        print("[Warning] GEMINI_API_KEY is not set! Set GEMINI_API_KEY in Render Environment Variables.")

    print(f"=================================================")
    print(f"   STARTING JARVIS ON RENDER CLOUD (PORT {port})   ")
    print(f"=================================================")

    from dashboard.server import DashboardServer
    import uvicorn
    from fastapi.responses import JSONResponse

    srv = DashboardServer()

    # Add health check route for Render
    @srv.app.get("/health")
    async def health_check():
        return JSONResponse({"status": "healthy", "service": "jarvis-render-cloud", "time": time.time()})

    async def run_server():
        # Start cloud command processor
        asyncio.create_task(process_cloud_commands(srv, api_key))

        cfg = uvicorn.Config(
            srv.app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(cfg)
        await server.serve()

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\n[Server] Shutdown requested.")


if __name__ == "__main__":
    main()
