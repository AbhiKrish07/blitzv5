"""
voice_engine.py — B.L.I.T.Z. Jarvis-grade Voice Engine
Handles: Wake word detection, STT (Whisper/WebSpeech), TTS (edge-tts/pyttsx3), 
         NLP intent routing, voice session management.
"""
import asyncio
import json
import os
import re
import time
import logging
from typing import Optional, AsyncGenerator
from datetime import datetime

logger = logging.getLogger("blitz.voice")

# ─── TTS Engine ───────────────────────────────────────────────────────────────
_tts_engine = None
_tts_mode = "none"

def _init_tts():
    global _tts_engine, _tts_mode
    # Try edge-tts (best quality, sounds like Jarvis)
    try:
        import edge_tts  # noqa
        _tts_mode = "edge"
        logger.info("[Voice] TTS: edge-tts (HD)")
        return
    except ImportError:
        pass
    # Fallback: pyttsx3
    try:
        import pyttsx3
        _tts_engine = pyttsx3.init()
        # Set Jarvis-like voice: deeper, slower
        voices = _tts_engine.getProperty('voices')
        # Prefer male English voice
        for v in voices:
            if 'david' in v.name.lower() or 'james' in v.name.lower() or 'mark' in v.name.lower():
                _tts_engine.setProperty('voice', v.id)
                break
        _tts_engine.setProperty('rate', 165)   # Slightly slower = authoritative
        _tts_engine.setProperty('volume', 0.95)
        _tts_mode = "pyttsx3"
        logger.info("[Voice] TTS: pyttsx3")
    except Exception as e:
        logger.warning(f"[Voice] No TTS available: {e}")
        _tts_mode = "none"

_init_tts()

# ─── Wake Word Config ──────────────────────────────────────────────────────────
WAKE_WORDS = ["hey blitz", "blitz", "jarvis", "hey jarvis", "computer"]
STOP_WORDS = ["stop", "cancel", "never mind", "be quiet", "shut up", "sleep"]

# ─── Intent Routing ───────────────────────────────────────────────────────────
INTENT_MAP = [
    # Navigation
    (r'\b(dashboard|home|digest|overview|main)\b', 'nav:digest'),
    (r'\b(financial|finance|money|revenue|mrr|arr|burn|cash|runway)\b', 'nav:financials'),
    (r'\b(okr|goal|objective|target|key result)\b', 'nav:okrs'),
    (r'\b(promise|commitment|deliver|commitments)\b', 'nav:promises'),
    (r'\b(competitor|competition|competitive)\b', 'nav:competitors'),
    (r'\b(contact|people|stakeholder|person)\b', 'nav:contacts'),
    (r'\b(team|org chart|hiring|headcount|department|recruit)\b', 'nav:org'),
    (r'\b(habit|development|personal|growth|self.improv|tracker)\b', 'nav:habits'),
    (r'\b(workflow|automation|trigger|automat)\b', 'nav:workflows'),
    (r'\b(biometric|health|hrv|sleep|recovery|body|whoop|oura)\b', 'nav:biometrics'),
    (r'\b(market|industry|funding|vc|venture|intel|intelligence)\b', 'nav:market'),
    (r'\b(google|email|calendar|gmail|task)\b', 'nav:google'),

    # Actions
    (r'\b(log|track|record|did|completed?|mark)\b.*\b(habit|workout|exercise|read|meditat|network|gym)\b', 'action:log_habit'),
    (r'\b(board|briefing|board.prep|board.meeting|investor)\b', 'action:board_prep'),
    (r'\b(refresh|reload|update|sync)\b', 'action:refresh'),
    (r'\b(close|exit|hide|go back|back)\b', 'action:close'),
    (r'\b(seed|load sample|dummy data|sample data)\b', 'action:seed'),

    # Queries (MUST be last — catch-all)
    (r'\b(time|clock|date|day|what.?s the time)\b', 'query:time'),
    (r'\b(weather|temperature|forecast)\b', 'query:weather'),
    (r'\b(morning|briefing)\b', 'query:digest'),
    # query:general is the final fallback — matched only if nothing above fits
]

def classify_intent(text: str) -> str:
    """Classify voice command into intent string."""
    t = text.lower().strip()
    # Stop commands override everything
    if any(w in t for w in STOP_WORDS):
        return "action:stop"
    for pattern, intent in INTENT_MAP:
        if re.search(pattern, t):
            return intent
    return "query:general"

def strip_wake_word(text: str) -> str:
    """Remove wake word from start of transcript."""
    t = text.strip()
    for ww in sorted(WAKE_WORDS, key=len, reverse=True):
        if t.lower().startswith(ww):
            return t[len(ww):].strip(' ,').strip()
    return t

def is_stop_command(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in STOP_WORDS)

def contains_wake_word(text: str) -> bool:
    t = text.lower()
    return any(ww in t for ww in WAKE_WORDS)

# ─── TTS Synthesis ────────────────────────────────────────────────────────────
async def synthesize_speech(text: str, voice: str = "en-US-GuyNeural") -> Optional[bytes]:
    """
    Synthesize speech. Returns MP3 bytes or None.
    Uses edge-tts for HD quality (Jarvis-like), falls back to pyttsx3 stream or None.
    """
    # Clean text for TTS — remove markdown
    clean = re.sub(r'\*+', '', text)
    clean = re.sub(r'#+\s*', '', clean)
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
    clean = re.sub(r'`[^`]*`', '', clean)
    clean = clean.strip()
    if not clean:
        return None

    if _tts_mode == "edge":
        try:
            import edge_tts
            tts = edge_tts.Communicate(clean, voice=voice, rate="-5%", pitch="-10Hz")
            audio_chunks = []
            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            return b"".join(audio_chunks) if audio_chunks else None
        except Exception as e:
            logger.error(f"[Voice] edge-tts error: {e}")
            return None

    elif _tts_mode == "pyttsx3":
        try:
            import io, threading
            # pyttsx3 is sync — run in thread
            result = []
            def _speak():
                _tts_engine.save_to_file(clean, '/tmp/blitz_tts.mp3')
                _tts_engine.runAndWait()
                try:
                    with open('/tmp/blitz_tts.mp3', 'rb') as f:
                        result.append(f.read())
                except Exception:
                    pass
            t = threading.Thread(target=_speak, daemon=True)
            t.start()
            t.join(timeout=10)
            return result[0] if result else None
        except Exception as e:
            logger.error(f"[Voice] pyttsx3 error: {e}")
            return None

    return None

async def synthesize_speech_streaming(text: str, voice: str = "en-US-GuyNeural") -> AsyncGenerator[bytes, None]:
    """Stream TTS audio chunks for low-latency playback."""
    clean = re.sub(r'\*+', '', text)
    clean = re.sub(r'#+\s*', '', clean)
    clean = clean.strip()
    if not clean:
        return

    if _tts_mode == "edge":
        try:
            import edge_tts
            tts = edge_tts.Communicate(clean, voice=voice, rate="-5%", pitch="-10Hz")
            async for chunk in tts.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            logger.error(f"[Voice] edge-tts stream error: {e}")

# ─── Jarvis Response Formatter ────────────────────────────────────────────────
JARVIS_PREFIXES = [
    "Understood.",
    "At once.",
    "Right away.",
    "Of course.",
    "Certainly.",
    "Affirmative.",
    "",  # Sometimes no prefix — keeps it natural
    "",
    "",
]

def format_jarvis_response(text: str, add_prefix: bool = True) -> str:
    """Format AI response in Jarvis style for TTS — strip markdown, add prefix."""
    import random
    clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    clean = re.sub(r'\*([^*]+)\*', r'\1', clean)       # italic
    clean = re.sub(r'#+\s*', '', clean)                 # headers
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)  # links
    clean = re.sub(r'`[^`]*`', '', clean)               # code
    clean = re.sub(r'\n{2,}', '. ', clean)
    clean = re.sub(r'\n', ' ', clean).strip()
    # Trim to ~400 chars for voice (don't read entire reports)
    if len(clean) > 450:
        clean = clean[:420].rsplit(' ', 1)[0] + '...'
    if add_prefix:
        prefix = random.choice(JARVIS_PREFIXES)
        if prefix:
            clean = f"{prefix} {clean}"
    return clean

# ─── Voice Session State ──────────────────────────────────────────────────────
class VoiceSession:
    def __init__(self):
        self.active = False
        self.last_activity = time.time()
        self.conversation: list[dict] = []
        self.wake_word_detected = False
        self.speaking = False
        self.listening = False

    def record_interaction(self, user_text: str, blitz_response: str):
        self.conversation.append({
            "ts": datetime.now().isoformat(),
            "user": user_text,
            "blitz": blitz_response,
        })
        self.last_activity = time.time()
        # Keep last 10 turns
        self.conversation = self.conversation[-10:]

    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    def to_dict(self):
        return {
            "active": self.active,
            "listening": self.listening,
            "speaking": self.speaking,
            "wake_word_detected": self.wake_word_detected,
            "last_activity": self.last_activity,
            "session_turns": len(self.conversation),
            "tts_mode": _tts_mode,
            "wake_words": WAKE_WORDS,
        }

# Global session
_voice_session = VoiceSession()

def get_voice_session() -> VoiceSession:
    return _voice_session

# ─── NLP / Command Processing ─────────────────────────────────────────────────
async def process_voice_command(text: str, groq_client=None, system_context: str = "") -> dict:
    """
    Full pipeline: text → intent → AI response → TTS audio bytes.
    Returns: {intent, response, audio_b64, nav_target, action}
    """
    import base64

    if not text or not text.strip():
        return {"error": "empty_text"}

    # Strip wake word if present
    cleaned = strip_wake_word(text)
    if not cleaned:
        return {"ack": True, "response": "Yes, boss. How can I help?"}

    # Classify intent
    intent = classify_intent(cleaned)
    nav_target = None
    action = None
    ai_response = None

    if intent.startswith("nav:"):
        nav_target = intent.split(":", 1)[1]
        nav_labels = {
            "digest": "dashboard", "financials": "financials", "okrs": "OKRs",
            "promises": "commitments", "competitors": "competitive intel",
            "contacts": "contacts", "org": "org chart", "habits": "personal development",
            "workflows": "workflows", "biometrics": "biometrics", "market": "market intel",
            "google": "Google integration",
        }
        label = nav_labels.get(nav_target, nav_target)
        ai_response = f"Opening {label}."

    elif intent.startswith("action:"):
        action = intent.split(":", 1)[1]
        action_responses = {
            "refresh": "Refreshing data now.",
            "close": "Closing the overlay.",
            "board_prep": "Generating your board briefing.",
            "seed": "Loading agency data.",
            "log_habit": "Which habit would you like to log?",
        }
        ai_response = action_responses.get(action, "On it.")

    elif intent == "query:time":
        now = datetime.now()
        ai_response = f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}."

    else:
        # General query — route to Groq AI
        if groq_client:
            try:
                sys_prompt = f"""You are B.L.I.T.Z., an AI chief of staff modeled on Jarvis from Iron Man.
You are speaking to your boss via voice. Keep responses SHORT (2-3 sentences max), confident, and direct.
Do NOT use markdown. Speak naturally as if responding out loud.
{system_context}
Current time: {datetime.now().strftime('%A, %B %d %Y at %I:%M %p')}"""
                resp = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": cleaned}
                    ],
                    max_tokens=150,
                    temperature=0.4,
                )
                ai_response = resp.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"[Voice] Groq error: {e}")
                ai_response = "My apologies, boss. The AI backend is temporarily unavailable."
        else:
            ai_response = f"You said: {cleaned}. AI backend not connected."

    # Format for TTS
    tts_text = format_jarvis_response(ai_response or "Understood.", add_prefix=False)

    # Synthesize
    audio_bytes = await synthesize_speech(tts_text)
    audio_b64 = base64.b64encode(audio_bytes).decode() if audio_bytes else None

    _voice_session.record_interaction(text, ai_response or "")

    return {
        "text": cleaned,
        "intent": intent,
        "response": ai_response or "",
        "tts_text": tts_text,
        "audio_b64": audio_b64,
        "audio_mime": "audio/mpeg" if audio_bytes else None,
        "nav_target": nav_target,
        "action": action,
        "tts_available": _tts_mode != "none",
    }
