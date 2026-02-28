"""
B.L.I.T.Z. Backend v5.0 — Jarvis-Level Autonomous AI Assistant
FastAPI + WebSocket Streaming + Per-Session History + Auth + Vector Memory
+ Cron Agents + Tool-Using Swarm + Voice Pipeline + PC Bridge
"""
import os, time, json, asyncio, re, pathlib, hashlib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()

from config import config

# ── Groq ──────────────────────────────────────────────────────────────────────
from groq import AsyncGroq
groq_client = AsyncGroq(api_key=config.GROQ_API_KEY)

# ── Tavily ────────────────────────────────────────────────────────────────────
try:
    from tavily import TavilyClient
    tavily = TavilyClient(api_key=config.TAVILY_API_KEY) if config.TAVILY_API_KEY else None
except ImportError:
    tavily = None

# ── Auth ──────────────────────────────────────────────────────────────────────
from auth import create_token, verify_token, require_auth, require_auth_ws, PASSPHRASE

# ── Memory Engine ─────────────────────────────────────────────────────────────
from memory_engine import (
    load_memory, save_memory, save_memory_entry,
    search_memory, auto_extract_memory, get_rich_memory_context,
    get_personality_context
)

# ── Proactive Cron ────────────────────────────────────────────────────────────
from proactive import (
    get_briefing_context, start_cron, get_full_briefing,
    add_task, complete_task, get_pending_tasks, get_tasks_summary
)

# ── ElevenLabs TTS (optional) ─────────────────────────────────────────────────
ELEVEN_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel default
_eleven_available = bool(ELEVEN_API_KEY)

async def elevenlabs_tts(text: str) -> bytes | None:
    """Generate audio with ElevenLabs. Returns mp3 bytes or None."""
    if not _eleven_available:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream",
                headers={"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.35}
                }
            )
            if r.status_code == 200:
                return r.content
    except Exception as e:
        print(f"[TTS] ElevenLabs error: {e}")
    return None

# ── Metrics ───────────────────────────────────────────────────────────────────
_metrics = {"requests": 0, "tokens": 0, "avg_latency_ms": 0, "errors": 0}
_latencies: list[int] = []
MAX_HISTORY = 20

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="B.L.I.T.Z. API", version="5.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

try:
    from system_control import router as sys_router
    app.include_router(sys_router)
    print("[OK] system_control router loaded")
except Exception as _e:
    print(f"[WARN] system_control not loaded: {_e}")

# ── PC Bridge WebSocket connections ───────────────────────────────────────────
_bridge_connections: dict[str, WebSocket] = {}   # bridge_id → ws
_bridge_pending: dict[str, asyncio.Future] = {}  # request_id → future

# ── Startup / Shutdown ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    start_cron()
    print("[OK] B.L.I.T.Z. v5 started")

# ── Models ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    passphrase: str

class CommandRequest(BaseModel):
    text: str
    active_modules: list[str] = []
    system_override: str = ""
    use_history: bool = True

class MemoryRequest(BaseModel):
    entry: str
    key: str = ""

class VisionRequest(BaseModel):
    image_b64: str
    question: str = "Describe this image in detail. Identify text, UI elements, errors, or actionable items."

class ForgeRequest(BaseModel):
    code: str
    language: str = "python"
    instruction: str = ""

class IntentRequest(BaseModel):
    text: str

class ScrapeRequest(BaseModel):
    url: str

class AutoRequest(BaseModel):
    text: str
    context: str = ""

class TTSRequest(BaseModel):
    text: str

class STTRequest(BaseModel):
    audio_b64: str  # base64 audio
    language: str = "en"

# ── Auth Endpoints ────────────────────────────────────────────────────────────
@app.post("/api/login")
async def login(req: LoginRequest):
    if req.passphrase != PASSPHRASE:
        raise HTTPException(status_code=401, detail="Wrong passphrase.")
    token = create_token()
    resp = JSONResponse({"status": "ok", "token": token})
    resp.set_cookie("blitz_token", token, httponly=True, max_age=72*3600, samesite="lax")
    return resp

@app.get("/api/me")
async def me(request: Request, _=Depends(require_auth)):
    return {"status": "authenticated"}

# ── Status & Briefing Endpoints ───────────────────────────────────────────────
@app.get("/api/status")
async def api_status():
    """Health check + feature availability. Used by frontend on load."""
    return {
        "status":        "online",
        "version":       "5.0.0",
        "tts_available": _eleven_available,
        "memory":        "pinecone" if os.getenv("PINECONE_API_KEY") else "json",
        "embeddings":    "jina" if os.getenv("JINA_API_KEY") else "keyword",
        "weather":       bool(os.getenv("OPENWEATHER_API_KEY")),
        "calendar":      bool(os.getenv("GOOGLE_CREDENTIALS_JSON")),
    }

@app.get("/api/briefing")
async def api_briefing(_=Depends(require_auth)):
    """
    Full morning briefing: weather + news + tasks + calendar.
    Called by frontend on load to populate the briefing panel.
    """
    return get_full_briefing()

@app.post("/api/briefing/refresh")
async def api_briefing_refresh(_=Depends(require_auth)):
    """Force-regenerate the briefing (e.g. when user manually refreshes)."""
    from proactive import generate_morning_briefing
    asyncio.create_task(generate_morning_briefing())
    return {"status": "refreshing", "message": "Briefing will update in ~5 seconds"}

# ── Task Endpoints ────────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    due: str = ""          # YYYY-MM-DD or 'today' / 'tomorrow'
    priority: str = "medium"  # low / medium / high / urgent
    client_id: str = ""

class TaskComplete(BaseModel):
    task_id: str   # id or partial title

@app.get("/api/tasks")
async def api_get_tasks(_=Depends(require_auth)):
    """Return all pending tasks sorted by priority."""
    return {"tasks": get_pending_tasks(20), "summary": get_tasks_summary()}

@app.post("/api/tasks")
async def api_add_task(req: TaskCreate, _=Depends(require_auth)):
    """Add a task. Voice: tell BLITZ 'add task X due tomorrow' and it calls this."""
    task = add_task(req.title, req.due, req.priority, req.client_id)
    return {"status": "created", "task": task}

@app.post("/api/tasks/complete")
async def api_complete_task(req: TaskComplete, _=Depends(require_auth)):
    """Mark a task as done by id or partial title match."""
    ok = complete_task(req.task_id)
    return {"status": "done" if ok else "not_found", "task_id": req.task_id}

# ── Intent Detection ──────────────────────────────────────────────────────────
INTENT_PATTERNS = {
    "open_app":        re.compile(r"\b(open|launch|start|run)\b.*(app|chrome|firefox|notepad|vscode|spotify|discord|slack|terminal|explorer|calculator|paint|word|excel)\b", re.I),
    "web_search":      re.compile(r"\b(search|google|look up|what is|who is|when did|how to|latest|news|weather)\b", re.I),
    "set_volume":      re.compile(r"\b(volume|sound|mute|unmute|louder|quieter|audio)\b", re.I),
    "set_brightness":  re.compile(r"\b(brightness|dim|brighter|screen light)\b", re.I),
    "play_music":      re.compile(r"\b(play music|pause music|skip|next track|previous track|stop music)\b", re.I),
    "system_info":     re.compile(r"\b(cpu|ram|memory usage|battery|processes|system info)\b", re.I),
    "take_screenshot": re.compile(r"\b(screenshot|screen capture|what.*screen)\b", re.I),
    "remember":        re.compile(r"\b(remember|note that|save this|store|don.t forget)\b", re.I),
    "recall":          re.compile(r"\b(recall|what did i say|do you remember|what.*stored|my.*note)\b", re.I),
}

def detect_intent(text: str) -> str:
    for intent, pattern in INTENT_PATTERNS.items():
        if pattern.search(text):
            return intent
    return "chat"

# ── System Prompt Builder ─────────────────────────────────────────────────────
async def build_system_prompt(
    active_modules: list[str],
    web_ctx: str = "",
    intent: str = "",
    query: str = "",
    mood: str = "normal",
    client_id: str = ""
) -> str:
    # Rich memory context (semantic if Pinecone + Jina configured)
    ctx = await get_rich_memory_context(query)
    personality = get_personality_context()
    briefing    = get_briefing_context()
    
    mode = "none"
    for m in ["coding", "studying", "create", "research", "memory", "vision", "voice"]:
        if m in active_modules:
            mode = m
            break
    if active_modules and mode == "none":
        mode = "general"
    mode_instr = config.MODE_PROMPTS.get(mode, config.MODE_PROMPTS["general"])
    if web_ctx:
        mode_instr += f"\n\nLIVE WEB RESULTS (cite naturally):\n{web_ctx}"
    
    base = config.BASE_PROMPT.format(
        context=ctx,
        active_modules=", ".join(active_modules) if active_modules else "none",
        mode=mode.upper(),
        mode_instructions=mode_instr
    )
    
    extras = []
    if briefing:
        extras.append(briefing)
    if personality:
        extras.append(personality)

    # Mood-adaptive response style
    mood_instr = MOOD_INSTRUCTIONS.get(mood, "") if "MOOD_INSTRUCTIONS" in dir() else ""
    if mood_instr:
        extras.append(f"[TONE INSTRUCTION]: {mood_instr}")

    # Client context injection (if client_id provided)
    if client_id and _agency_ok:
        try:
            client_ctx = get_client_context(client_id, query)
            if client_ctx:
                extras.append(client_ctx)
        except Exception:
            pass
    
    if extras:
        base += "\n\n" + "\n".join(extras)
    
    return base

# ── Autonomous Action Handler ─────────────────────────────────────────────────
async def handle_autonomous_action(intent: str, text: str) -> dict | None:
    """Try PC bridge first, fall back to local server."""
    import httpx
    base = "http://localhost:8000"
    
    # Try PC bridge first if connected
    if _bridge_connections:
        result = await relay_to_bridge(intent, text)
        if result:
            return result
    
    # Local fallback
    try:
        if intent == "take_screenshot":
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{base}/api/sys/screenshot")
                if r.status_code == 200:
                    return {"type": "screenshot", "data": r.json()}

        elif intent == "system_info":
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{base}/api/sys/info")
                if r.status_code == 200:
                    return {"type": "system_info", "data": r.json()}

        elif intent == "open_app":
            match = re.search(r"\b(open|launch|start)\b\s+(.+?)(?:\s+(?:for|please|now))?.?$", text, re.I)
            if match:
                app_name = match.group(2).strip()
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.post(f"{base}/api/sys/open-app", json={"name": app_name})
                    if r.status_code == 200:
                        return {"type": "app_launched", "data": r.json()}

        elif intent == "set_volume":
            vol_match = re.search(r"\b(\d+)\s*%?\b", text)
            if vol_match:
                level = min(100, max(0, int(vol_match.group(1))))
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.post(f"{base}/api/sys/volume", json={"level": level})
                    if r.status_code == 200:
                        return {"type": "volume_set", "data": r.json()}
            elif re.search(r"\bmute\b", text, re.I):
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.post(f"{base}/api/sys/volume", json={"mute": True})
                    if r.status_code == 200:
                        return {"type": "muted", "data": r.json()}

        elif intent == "set_brightness":
            bright_match = re.search(r"\b(\d+)\s*%?\b", text)
            if bright_match:
                level = min(100, max(1, int(bright_match.group(1))))
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.post(f"{base}/api/sys/brightness", json={"level": level})
                    if r.status_code == 200:
                        return {"type": "brightness_set", "data": r.json()}

        elif intent == "play_music":
            action_map = {"pause": "pause", "stop": "pause", "next": "next", "previous": "previous", "play": "play", "skip": "next"}
            for word, action in action_map.items():
                if re.search(rf"\b{word}\b", text, re.I):
                    async with httpx.AsyncClient(timeout=5) as c:
                        r = await c.post(f"{base}/api/sys/spotify/control", json={"action": action})
                        if r.status_code == 200:
                            return {"type": "music_control", "data": r.json()}
                    break

    except Exception as e:
        print(f"[AUTO ACTION ERROR] {intent}: {e}")
    return None

# ── PC Bridge relay ───────────────────────────────────────────────────────────
async def relay_to_bridge(intent: str, text: str) -> dict | None:
    """Send command to connected PC bridge and await result."""
    if not _bridge_connections:
        return None
    
    bridge_ws = next(iter(_bridge_connections.values()))
    request_id = hashlib.sha256(f"{intent}{time.time()}".encode()).hexdigest()[:12]
    
    # Map intent to bridge command
    cmd_map = {
        "open_app":        "open_app",
        "set_volume":      "set_volume",
        "set_brightness":  "set_brightness",
        "system_info":     "system_info",
        "take_screenshot": "screenshot",
        "play_music":      "spotify"
    }
    cmd_type = cmd_map.get(intent)
    if not cmd_type:
        return None
    
    payload = {}
    if intent == "open_app":
        m = re.search(r"\b(open|launch|start)\b\s+(.+)", text, re.I)
        payload = {"name": m.group(2).strip() if m else text}
    elif intent == "set_volume":
        m = re.search(r"\b(\d+)\b", text)
        payload = {"level": int(m.group(1)) if m else 50, "mute": bool(re.search(r"\bmute\b", text, re.I))}
    elif intent == "set_brightness":
        m = re.search(r"\b(\d+)\b", text)
        payload = {"level": int(m.group(1)) if m else 50}
    elif intent == "play_music":
        for word in ["pause", "stop", "next", "previous", "play", "skip"]:
            if re.search(rf"\b{word}\b", text, re.I):
                payload = {"action": "next" if word == "skip" else word}
                break
    
    future = asyncio.get_event_loop().create_future()
    _bridge_pending[request_id] = future
    
    try:
        await bridge_ws.send_text(json.dumps({
            "type": "command",
            "cmd_type": cmd_type,
            "payload": payload,
            "request_id": request_id
        }))
        result = await asyncio.wait_for(future, timeout=8.0)
        return {"type": cmd_type, "data": result, "source": "pc_bridge"}
    except asyncio.TimeoutError:
        _bridge_pending.pop(request_id, None)
        return None
    except Exception as e:
        _bridge_pending.pop(request_id, None)
        return None

# ── Tool-Using Agent Swarm ────────────────────────────────────────────────────
async def tool_browse_url(url: str) -> str:
    """Tool: fetch and extract text from a URL."""
    try:
        import httpx, re as _re
        async with httpx.AsyncClient(timeout=12, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BLITZ/5.0)"}) as c:
            r = await c.get(url)
            html = r.text
        html = _re.sub(r"<(script|style|nav|footer)[^>]*>[\s\S]*?</\1>", "", html, flags=_re.I)
        text = _re.sub(r"<[^>]+>", " ", html)
        text = _re.sub(r"\s{3,}", "\n", text).strip()
        return text[:3000]
    except Exception as e:
        return f"Error fetching {url}: {e}"

async def tool_search(query: str) -> str:
    """Tool: Tavily web search."""
    if not tavily:
        return "Search unavailable."
    try:
        results = tavily.search(query, max_results=3, search_depth="advanced")
        return "\n\n".join(
            f"[{r['title']}]({r['url']})\n{r.get('content', '')[:400]}"
            for r in results.get("results", [])
        )
    except Exception as e:
        return f"Search error: {e}"

async def tool_remember(fact: str) -> str:
    """Tool: Save a fact to memory."""
    await save_memory_entry(fact, meta={"type": "agent_saved"})
    return f"Remembered: {fact}"

async def tool_recall(query: str) -> str:
    """Tool: Search memory."""
    results = await search_memory(query, top_k=5)
    if results:
        return "From memory:\n" + "\n".join(f"• {r}" for r in results)
    return "Nothing relevant found in memory."

AVAILABLE_TOOLS = {
    "search": tool_search,
    "browse": tool_browse_url,
    "remember": tool_remember,
    "recall": tool_recall,
}

TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "search", "description": "Search the web for any topic", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "browse", "description": "Fetch and read a specific URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "remember", "description": "Save an important fact to long-term memory", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "recall", "description": "Search past memory for relevant information", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

async def run_tool_agent(question: str, ws: WebSocket = None) -> tuple[str, list[str]]:
    """Run a tool-using agent loop: think → use tool → feed result → continue."""
    logs = []
    messages = [
        {"role": "system", "content": "You are B.L.I.T.Z. — an autonomous AI agent. Use your tools to answer the user's question thoroughly. Think step by step. Use tools when you need current information or to save facts."},
        {"role": "user", "content": question}
    ]
    
    max_iterations = 5
    for i in range(max_iterations):
        try:
            r = await groq_client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                max_tokens=1500,
                temperature=0.5
            )
            
            choice = r.choices[0]
            msg = choice.message
            
            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]})
                
                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except Exception:
                        fn_args = {}
                    
                    log = f"🔧 [TOOL:{fn_name.upper()}] {list(fn_args.values())[0] if fn_args else ''}"
                    logs.append(log)
                    if ws:
                        await ws.send_text(json.dumps({"type": "swarm_log", "text": log}))
                    
                    tool_fn = AVAILABLE_TOOLS.get(fn_name)
                    if tool_fn:
                        result = await tool_fn(**fn_args)
                    else:
                        result = "Tool not found."
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result
                    })
            
            elif choice.finish_reason == "stop":
                final = msg.content or ""
                logs.append(f"✅ [AGENT] Done after {i+1} iteration(s)")
                return final, logs
            
            else:
                break
                
        except Exception as e:
            logs.append(f"❌ [AGENT ERROR] {e}")
            break
    
    # Fallback
    return question, logs

# ── Legacy swarm (for non-tool mode) ─────────────────────────────────────────
async def agent_planner(question: str) -> list[str]:
    r = await groq_client.chat.completions.create(
        model=config.SWARM_MODEL,
        messages=[
            {"role": "system", "content": "Output a JSON array of 2-3 specific research sub-tasks for the question. JSON array only, no markdown."},
            {"role": "user", "content": question}
        ],
        max_tokens=300, temperature=0.3
    )
    try:
        tasks = json.loads(r.choices[0].message.content.strip())
        return tasks if isinstance(tasks, list) else [question]
    except Exception:
        return [question]

async def agent_researcher(subtask: str, web_ctx: str) -> str:
    r = await groq_client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": f"Research Specialist. Answer concisely.\nWeb context:\n{web_ctx[:1500]}"},
            {"role": "user", "content": subtask}
        ],
        max_tokens=500, temperature=0.5
    )
    return r.choices[0].message.content.strip()

async def agent_critic(draft: str) -> str:
    r = await groq_client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[
            {"role": "system", "content": "Critic. In 2-3 bullets, identify factual gaps or errors. Be precise."},
            {"role": "user", "content": draft}
        ],
        max_tokens=200, temperature=0.4
    )
    return r.choices[0].message.content.strip()

async def run_agent_swarm(question: str, web_ctx: str = "", ws: WebSocket = None) -> tuple[str, list[str]]:
    logs = []
    try:
        logs.append("🟡 [PLANNER] Decomposing query...")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))
        subtasks = await agent_planner(question)
        logs.append(f"✅ [PLANNER] {len(subtasks)} sub-tasks")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))

        logs.append(f"🔵 [RESEARCHERS] {len(subtasks)} parallel agents...")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))
        results = await asyncio.gather(*[agent_researcher(t, web_ctx) for t in subtasks[:3]])
        combined = "\n\n".join(f"**{subtasks[i]}**\n{r}" for i, r in enumerate(results))
        logs.append("✅ [RESEARCHERS] All returned.")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))

        logs.append("🔴 [CRITIC] Reviewing...")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))
        critique = await agent_critic(combined)
        logs.append("✅ [CRITIC] Done")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))

        logs.append("🟣 [WRITER] Synthesizing...")
        if ws: await ws.send_text(json.dumps({"type": "swarm_log", "text": logs[-1]}))
        synthesis = (
            f"Research findings:\n{combined}\n\nCritic notes:\n{critique}\n\n"
            f"Question: {question}\n\nWrite a comprehensive markdown answer addressing all findings."
        )
        return synthesis, logs
    except Exception as e:
        logs.append(f"❌ [SWARM ERROR] {e}")
        return question, logs

# ── Groq Whisper STT ──────────────────────────────────────────────────────────
async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Transcribe audio using Groq Whisper (fastest STT on planet)."""
    try:
        transcription = await groq_client.audio.transcriptions.create(
            file=(filename, audio_bytes, "audio/webm"),
            model="whisper-large-v3-turbo",
            language="en",
            response_format="text"
        )
        return transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
    except Exception as e:
        print(f"[STT] Whisper error: {e}")
        return ""

# ── PC Bridge WebSocket ───────────────────────────────────────────────────────
@app.websocket("/ws/bridge")
async def ws_bridge(ws: WebSocket):
    """PC Bridge connection — the bridge script connects here."""
    bridge_id = f"bridge_{int(time.time())}"
    await ws.accept()
    
    try:
        # Very simple auth for bridge
        hello = json.loads(await ws.receive_text())
        if hello.get("type") != "bridge_hello":
            await ws.close(code=4001)
            return
        
        _bridge_connections[bridge_id] = ws
        print(f"[BRIDGE] PC Bridge connected: {bridge_id}")
        
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)
            
            if data.get("type") == "pong":
                continue
            
            if data.get("type") == "command_result":
                request_id = data.get("data", {}).get("request_id") or data.get("request_id")
                future = _bridge_pending.pop(request_id, None)
                if future and not future.done():
                    future.set_result(data.get("data", {}))
    
    except WebSocketDisconnect:
        print(f"[BRIDGE] Disconnected: {bridge_id}")
    except Exception as e:
        print(f"[BRIDGE] Error: {e}")
    finally:
        _bridge_connections.pop(bridge_id, None)

# ── Main Chat WebSocket (per-session history) ─────────────────────────────────
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    
    # Per-session conversation history
    session_history: list[dict] = []
    
    # Auth — first message should include token
    try:
        first_raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        first_data = json.loads(first_raw)
        token = first_data.get("token", "")
        ip = ws.client.host if ws.client else "ws"
        
        if not await require_auth_ws(token, ip):
            await ws.send_text(json.dumps({"type": "error", "text": "Unauthorized"}))
            await ws.close(code=4001)
            return
        
        # If auth message also has text, process it too
        initial_text = first_data.get("text", "").strip()
        
    except asyncio.TimeoutError:
        await ws.close(code=4008)
        return
    
    await ws.send_text(json.dumps({"type": "auth_ok"}))
    
    async def process_message(data: dict):
        nonlocal session_history
        text = data.get("text", "").strip()
        active_modules = data.get("active_modules", [])
        use_swarm  = data.get("use_swarm", False)
        use_tools  = data.get("use_tools", True)
        voice_mode = data.get("voice_mode", False)
        client_id  = data.get("client_id", "")   # optional: load client context

        if not text:
            return

        # Mood detection — drives tone adaptation
        mood = detect_message_mood(text) if "detect_message_mood" in dir() else "normal"

        t0 = time.time()
        _metrics["requests"] += 1
        web_ctx = ""

        intent = detect_intent(text)
        await ws.send_text(json.dumps({"type": "intent", "intent": intent}))

        # Autonomous actions
        if intent not in ("chat", "web_search", "remember", "recall"):
            action_result = await handle_autonomous_action(intent, text)
            if action_result:
                await ws.send_text(json.dumps({"type": "action_result", "data": action_result}))

        # Web search
        if ("research" in active_modules or use_swarm or intent == "web_search") and tavily:
            try:
                await ws.send_text(json.dumps({"type": "status", "text": "🔍 Searching the web..."}))
                results = tavily.search(text, max_results=5, search_depth="advanced")
                web_ctx = "\n\n".join(
                    f"[{r['title']}]({r['url']})\n{r.get('content', '')[:400]}"
                    for r in results.get("results", [])
                )
            except Exception as e:
                web_ctx = f"(Web search error: {e})"

        actual_prompt = text
        swarm_logs = []
        
        if use_swarm and use_tools:
            # Tool-using agent swarm
            await ws.send_text(json.dumps({"type": "status", "text": "🤖 Agent swarm activated..."}))
            final_answer, swarm_logs = await run_tool_agent(text, ws)
            # Agent gives direct answer — use it directly
            full_response = final_answer
            
            lat = int((time.time() - t0) * 1000)
            _latencies.append(lat)
            if len(_latencies) > 100: _latencies.pop(0)
            _metrics["avg_latency_ms"] = int(sum(_latencies) / len(_latencies))
            
            session_history.append({"role": "user", "content": text})
            session_history.append({"role": "assistant", "content": full_response})
            if len(session_history) > MAX_HISTORY * 2:
                session_history = session_history[-MAX_HISTORY * 2:]
            
            asyncio.create_task(auto_extract_memory(text, full_response))
            
            await ws.send_text(json.dumps({"type": "token", "text": full_response}))
            await ws.send_text(json.dumps({"type": "done", "latency_ms": lat, "route": "tool_agent", "intent": intent}))
            return
        
        elif use_swarm:
            actual_prompt, swarm_logs = await run_agent_swarm(text, web_ctx, ws)

        system = await build_system_prompt(active_modules, web_ctx, intent, text, mood=mood, client_id=client_id)
        
        # Build messages with session history (the key fix!)
        messages = [{"role": "system", "content": system}]
        if session_history:
            messages.extend(session_history[-MAX_HISTORY:])  # sliding window
        messages.append({"role": "user", "content": actual_prompt})

        full_response = ""
        try:
            stream = await groq_client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=messages,
                max_tokens=2048, temperature=0.7, stream=True
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_response += delta
                    await ws.send_text(json.dumps({"type": "token", "text": delta}))
        except Exception as e:
            err = f"**Error:** {e}"
            await ws.send_text(json.dumps({"type": "token", "text": err}))
            full_response = err
            _metrics["errors"] += 1

        # Update session history (per-session, not global)
        session_history.append({"role": "user", "content": text})
        session_history.append({"role": "assistant", "content": full_response})
        if len(session_history) > MAX_HISTORY * 2:
            session_history = session_history[-MAX_HISTORY * 2:]

        # Auto-save memories and personality in background
        if intent == "remember":
            asyncio.create_task(save_memory_entry(text, meta={"type": "manual"}))
        asyncio.create_task(auto_extract_memory(text, full_response))

        # Voice: generate TTS if voice mode
        if voice_mode and _eleven_available:
            # Clean response for TTS (remove markdown)
            tts_text = re.sub(r"[*#`\[\]]+", "", full_response)
            tts_text = re.sub(r"\n{2,}", ". ", tts_text).strip()[:500]
            audio = await elevenlabs_tts(tts_text)
            if audio:
                import base64
                await ws.send_text(json.dumps({
                    "type": "audio",
                    "audio_b64": base64.b64encode(audio).decode(),
                    "format": "mp3"
                }))

        lat = int((time.time() - t0) * 1000)
        _latencies.append(lat)
        if len(_latencies) > 100: _latencies.pop(0)
        _metrics["avg_latency_ms"] = int(sum(_latencies) / len(_latencies))

        hud_data = None
        match = re.search(r"```(\w*)\n([\s\S]+?)```", full_response)
        if match:
            hud_data = {"title": match.group(1) or "Output", "content": match.group(2).strip(), "type": "CODE"}

        route = "swarm" if use_swarm else (intent if intent != "chat" else "llm")
        await ws.send_text(json.dumps({
            "type": "done",
            "latency_ms": lat,
            "route": route,
            "intent": intent,
            "hud": hud_data
        }))
    
    try:
        # Process initial message if it had text
        if initial_text:
            first_data["text"] = initial_text
            await process_message(first_data)
        
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            await process_message(data)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "text": str(e)}))
        except Exception:
            pass

# ── STT Endpoint (Groq Whisper) ───────────────────────────────────────────────
@app.post("/api/stt")
async def stt(req: STTRequest, _=Depends(require_auth)):
    import base64
    try:
        audio_bytes = base64.b64decode(req.audio_b64)
        text = await transcribe_audio(audio_bytes)
        return {"text": text, "language": req.language}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# ── TTS Endpoint (ElevenLabs) ─────────────────────────────────────────────────
@app.post("/api/tts")
async def tts(req: TTSRequest, _=Depends(require_auth)):
    import base64
    audio = await elevenlabs_tts(req.text[:500])
    if audio:
        return {"audio_b64": base64.b64encode(audio).decode(), "format": "mp3"}
    return JSONResponse(status_code=503, content={"error": "TTS unavailable"})

# ── REST Endpoints ─────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    return {
        "status": "ok",
        "version": "5.0.0",
        "name": "B.L.I.T.Z. API",
        "model": config.MODEL_NAME,
        "tts_available": _eleven_available,
        "bridge_connected": bool(_bridge_connections),
        "bridge_count": len(_bridge_connections)
    }

@app.get("/api/metrics")
async def metrics(_=Depends(require_auth)):
    try:
        import psutil
        _metrics["cpu_percent"] = psutil.cpu_percent()
        _metrics["memory_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    except Exception:
        pass
    return _metrics

@app.get("/api/briefing")
async def get_briefing(_=Depends(require_auth)):
    from proactive import _briefing
    return _briefing

@app.post("/api/connect/{module_id}")
async def connect_module(module_id: str, _=Depends(require_auth)):
    t0 = time.time()
    await asyncio.sleep(0.05)
    return {"status": "connected", "module": module_id, "latency_ms": int((time.time()-t0)*1000)}

@app.post("/api/disconnect/{module_id}")
async def disconnect_module(module_id: str, _=Depends(require_auth)):
    return {"status": "disconnected", "module": module_id}

@app.post("/api/intent")
async def detect_intent_api(req: IntentRequest):
    return {"intent": detect_intent(req.text), "text": req.text}

@app.post("/api/command")
async def command(req: CommandRequest, _=Depends(require_auth)):
    t0 = time.time()
    _metrics["requests"] += 1
    web_ctx = ""
    intent = detect_intent(req.text)

    if "research" in req.active_modules and tavily:
        try:
            results = tavily.search(req.text, max_results=4)
            web_ctx = "\n\n".join(f"[{r['title']}]\n{r.get('content', '')[:350]}" for r in results.get("results", []))
        except Exception:
            pass

    system = req.system_override if req.system_override else await build_system_prompt(req.active_modules, web_ctx, intent, req.text)
    messages = [{"role": "system", "content": system}]
    messages.append({"role": "user", "content": req.text})

    try:
        r = await groq_client.chat.completions.create(
            model=config.MODEL_NAME, messages=messages, max_tokens=1500, temperature=0.7
        )
        response = r.choices[0].message.content
    except Exception as e:
        response = f"**Error:** {e}"
        _metrics["errors"] += 1

    asyncio.create_task(auto_extract_memory(req.text, response))

    lat = int((time.time() - t0) * 1000)
    _latencies.append(lat)
    if len(_latencies) > 100: _latencies.pop(0)

    hud_data = None
    match = re.search(r"```(\w*)\n([\s\S]+?)```", response)
    if match:
        hud_data = {"title": match.group(1) or "Output", "content": match.group(2).strip(), "type": "CODE"}

    mode = next((m for m in ["coding", "studying", "create", "research", "memory", "vision", "voice"] if m in req.active_modules), "general")
    return {
        "response": response, "latency_ms": lat, "route": mode, "intent": intent,
        "spawn_hud": bool(hud_data),
        "hud_title": hud_data["title"] if hud_data else None,
        "hud_content": hud_data["content"] if hud_data else None,
        "hud_type": hud_data["type"] if hud_data else None,
    }

@app.post("/api/vision")
async def vision(req: VisionRequest, _=Depends(require_auth)):
    try:
        r = await groq_client.chat.completions.create(
            model=config.VISION_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{req.image_b64}"}},
                {"type": "text", "text": req.question}
            ]}],
            max_tokens=1000
        )
        return {"response": r.choices[0].message.content}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/forge")
async def forge(req: ForgeRequest, _=Depends(require_auth)):
    system = """You are B.L.I.T.Z. FORGE mode — senior autonomous coding agent.
Fix/improve the code. Respond with: 1-2 sentence explanation + complete corrected code block.
Be precise. No verbose commentary."""
    user_msg = f"Language: {req.language}\nInstruction: {req.instruction}\n\nCode:\n```{req.language}\n{req.code}\n```"
    try:
        r = await groq_client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            max_tokens=2000, temperature=0.25
        )
        return {"response": r.choices[0].message.content}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/memory")
async def save_mem(req: MemoryRequest, _=Depends(require_auth)):
    await save_memory_entry(req.entry, meta={"key": req.key} if req.key else {})
    data = load_memory()
    if req.key:
        data.setdefault("structured", {})[req.key] = req.entry
        save_memory(data)
    return {"status": "saved", "total_entries": len(data.get("entries", []))}

@app.get("/api/memory-view")
async def view_mem(_=Depends(require_auth)):
    data = load_memory()
    return {"content": "\n".join(data.get("entries", [])), "structured": data.get("structured", {}), "personality": data.get("personality", {})}

@app.post("/api/memory-clear")
async def clear_mem(_=Depends(require_auth)):
    save_memory({"entries": [], "context": "", "preferences": {}, "personality": {}})
    return {"status": "cleared"}

@app.get("/api/memory-search")
async def memory_search(q: str, _=Depends(require_auth)):
    results = await search_memory(q, top_k=10)
    return {"results": results, "query": q}

@app.get("/api/search")
async def web_search(q: str, _=Depends(require_auth)):
    if not tavily:
        return {"error": "Tavily not configured"}
    try:
        results = tavily.search(q, max_results=5, search_depth="advanced")
        return {"results": results.get("results", [])}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/scrape")
async def scrape(req: ScrapeRequest, _=Depends(require_auth)):
    import httpx, re as _re
    if not req.url.startswith("http"):
        return JSONResponse(status_code=400, content={"error": "Invalid URL"})
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; BLITZ/5.0)"}) as client:
            r = await client.get(req.url)
            html = r.text
        html = _re.sub(r"<(script|style|nav|footer|header)[^>]*>[\s\S]*?</\1>", "", html, flags=_re.I)
        title_m = _re.search(r"<title[^>]*>(.*?)</title>", html, _re.I | _re.S)
        title = title_m.group(1).strip() if title_m else req.url
        text = _re.sub(r"<[^>]+>", " ", html)
        text = _re.sub(r"\s{3,}", "\n\n", text).strip()
        return {"title": title, "content": text[:6000], "url": req.url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/auto")
async def autonomous_execute(req: AutoRequest, _=Depends(require_auth)):
    intent = detect_intent(req.text)
    action_result = await handle_autonomous_action(intent, req.text)
    system = await build_system_prompt([], "", intent, req.text)
    action_ctx = f"\n\n[SYSTEM ACTION EXECUTED]: {json.dumps(action_result)}" if action_result else ""
    try:
        r = await groq_client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": req.text + action_ctx}],
            max_tokens=500, temperature=0.6
        )
        response = r.choices[0].message.content
    except Exception:
        response = f"Action executed: {action_result}"
    return {"response": response, "intent": intent, "action": action_result}

# ── Login Page ────────────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>B.L.I.T.Z. — Access</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#04050a;font-family:'Syne',sans-serif;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;overflow:hidden}
body::after{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.015) 2px,rgba(0,0,0,.015) 4px);pointer-events:none;z-index:999}
.bg{position:fixed;inset:0;background:radial-gradient(ellipse 60% 50% at 50% 50%,rgba(88,28,220,.18),transparent 70%)}
.card{position:relative;z-index:1;width:360px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:44px 36px;backdrop-filter:blur(32px);text-align:center}
.orb{width:64px;height:64px;border-radius:50%;background:radial-gradient(circle at 33% 28%,#fff 0%,rgba(215,225,255,.76) 26%,rgba(165,185,240,.5) 58%,transparent 100%);border:1px solid rgba(255,255,255,.4);box-shadow:0 0 60px rgba(110,140,255,.3);margin:0 auto 20px;animation:breathe 4s ease-in-out infinite}
@keyframes breathe{0%,100%{box-shadow:0 0 40px rgba(110,140,255,.2)}50%{box-shadow:0 0 80px rgba(110,140,255,.5)}}
h1{font-size:26px;font-weight:800;letter-spacing:-.02em;margin-bottom:4px}
.sub{font-family:'Space Mono',monospace;font-size:11px;color:rgba(255,255,255,.4);margin-bottom:32px;letter-spacing:.06em}
input{width:100%;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:13px 16px;color:#fff;font-family:'Space Mono',monospace;font-size:14px;outline:none;transition:.2s;margin-bottom:16px;text-align:center;letter-spacing:.1em}
input:focus{border-color:rgba(167,139,250,.5);background:rgba(255,255,255,.08)}
input::placeholder{color:rgba(255,255,255,.25);letter-spacing:.04em}
button{width:100%;padding:13px;background:linear-gradient(135deg,rgba(167,139,250,.2),rgba(96,165,250,.15));border:1px solid rgba(167,139,250,.35);border-radius:10px;color:#fff;font-family:'Syne',sans-serif;font-size:14px;font-weight:700;letter-spacing:.06em;cursor:pointer;transition:.2s}
button:hover{background:linear-gradient(135deg,rgba(167,139,250,.32),rgba(96,165,250,.25));border-color:rgba(167,139,250,.6);transform:translateY(-1px)}
.err{color:#fb7185;font-family:'Space Mono',monospace;font-size:11px;margin-top:12px;display:none}
.err.show{display:block}
</style>
</head>
<body>
<div class="bg"></div>
<div class="card">
  <div class="orb"></div>
  <h1>B.L.I.T.Z.</h1>
  <p class="sub">BIOMETRIC LOCK — ENTER PASSPHRASE</p>
  <input type="password" id="pass" placeholder="••••••••••••" autocomplete="off" autofocus>
  <button onclick="login()">AUTHENTICATE</button>
  <p class="err" id="err">⚠ Invalid passphrase. Access denied.</p>
</div>
<script>
document.getElementById('pass').addEventListener('keydown', e => { if(e.key==='Enter') login(); });
async function login() {
  const pass = document.getElementById('pass').value;
  const err = document.getElementById('err');
  err.classList.remove('show');
  const r = await fetch('/api/login', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({passphrase: pass}), credentials: 'include'
  });
  if(r.ok) {
    const d = await r.json();
    localStorage.setItem('blitz_token', d.token);
    window.location.href = '/';
  } else {
    err.classList.add('show');
    document.getElementById('pass').value = '';
    document.getElementById('pass').focus();
  }
}
</script>
</body>
</html>"""

@app.get("/login")
async def login_page():
    return HTMLResponse(LOGIN_HTML)

# ── Agency OS — Lazy Module Imports ──────────────────────────────────────────
_agency_ok = False
try:
    from clients  import (create_client, list_clients, get_client, update_client,
                          add_client_memory, search_client_memory, get_client_context,
                          start_sprint, update_sprint, get_sprint_context, get_at_risk_clients)
    from agency   import (log_hours, parse_voice_log, get_utilization,
                          generate_invoice, get_pl_summary, set_rate)
    from intelligence import (analyze_meeting, generate_prd, detect_scope_creep,
                               tech_to_business, generate_proposal, analyze_prospect,
                               commits_to_update)
    from indexer  import (index_directory, search_codebase, get_index_summary,
                          summarize_architecture, analyze_dependency_impact)
    _agency_ok = True
    print("[OK] Agency OS modules loaded")
except Exception as _ae:
    print(f"[WARN] Agency modules not loaded: {_ae}")

# ── Agency Pydantic Models ────────────────────────────────────────────────────
class ClientCreate(BaseModel):
    id: str
    name: str
    stack: list[str] = []
    goals: list[str] = []
    notes: str = ""
    rate: float = 0.0
    timezone: str = "UTC"

class ClientUpdate(BaseModel):
    name: str = ""
    stack: list[str] = []
    goals: list[str] = []
    notes: str = ""
    non_negotiables: list[str] = []
    comm_style: str = ""
    health: str = ""
    rate: float = 0.0
    mrr: float = 0.0

class ClientMemoryEntry(BaseModel):
    entry: str
    tag: str = "note"  # note / decision / red_flag / feedback / blocker

class SprintCreate(BaseModel):
    name: str
    goals: list[str]

class SprintUpdate(BaseModel):
    done: list[str] = []
    blockers: list[str] = []
    notes: str = ""

class HourLogRequest(BaseModel):
    client_id: str
    hours: float
    description: str
    service_type: str = "development"
    date: str = ""

class VoiceLogRequest(BaseModel):
    text: str   # "Log 3 hours Acme, backend refactor"

class RateSetRequest(BaseModel):
    client_id: str
    rate: float

class MeetingRequest(BaseModel):
    transcript: str
    client_id: str = ""
    client_name: str = "Client"

class PRDRequest(BaseModel):
    description: str
    stack: str = ""
    client_id: str = ""

class ScopeCreepRequest(BaseModel):
    new_request: str
    original_scope: str = ""
    client_id: str = ""

class TechTranslateRequest(BaseModel):
    text: str
    audience: str = "non-technical client"

class ProposalRequest(BaseModel):
    scope: str
    prospect_analysis: str = ""
    past_context: str = ""

class ProspectRequest(BaseModel):
    content: str   # website text, LinkedIn, job posting, etc.

class IndexRequest(BaseModel):
    path: str
    extensions: list[str] = []
    force: bool = False

class CodebaseSearchRequest(BaseModel):
    query: str
    top_k: int = 8
    file_filter: str = ""

class DependencyRequest(BaseModel):
    target: str   # file or function name

def _agency_required():
    if not _agency_ok:
        raise HTTPException(503, "Agency modules failed to load. Check server logs.")

# ──────────────────────────────────────────────────────────────────────────────
# CLIENT NAMESPACE ENDPOINTS
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/clients")
async def api_create_client(req: ClientCreate, _=Depends(require_auth)):
    _agency_required()
    return create_client(req.id, req.name, req.stack, req.goals, req.notes, req.rate, req.timezone)

@app.get("/api/clients")
async def api_list_clients(_=Depends(require_auth)):
    _agency_required()
    return {"clients": list_clients(), "at_risk": get_at_risk_clients()}

@app.get("/api/clients/at-risk")
async def api_at_risk(_=Depends(require_auth)):
    _agency_required()
    return {"at_risk": get_at_risk_clients()}

@app.get("/api/clients/{client_id}")
async def api_get_client(client_id: str, _=Depends(require_auth)):
    _agency_required()
    c = get_client(client_id)
    if not c:
        raise HTTPException(404, f"Client '{client_id}' not found")
    return c

@app.patch("/api/clients/{client_id}")
async def api_update_client(client_id: str, req: ClientUpdate, _=Depends(require_auth)):
    _agency_required()
    updates = {k: v for k, v in req.dict().items() if v or v == 0.0}
    return update_client(client_id, updates)

@app.get("/api/clients/{client_id}/context")
async def api_client_context(client_id: str, q: str = "", _=Depends(require_auth)):
    """Get full client context (for injecting into a Groq call)."""
    _agency_required()
    return {"context": get_client_context(client_id, q)}

@app.post("/api/clients/{client_id}/memory")
async def api_add_client_memory(client_id: str, req: ClientMemoryEntry, _=Depends(require_auth)):
    _agency_required()
    return add_client_memory(client_id, req.entry, req.tag)

@app.get("/api/clients/{client_id}/memory")
async def api_search_client_memory(client_id: str, q: str = "", _=Depends(require_auth)):
    _agency_required()
    return {"results": search_client_memory(client_id, q)}

@app.post("/api/clients/{client_id}/sprint")
async def api_start_sprint(client_id: str, req: SprintCreate, _=Depends(require_auth)):
    _agency_required()
    return start_sprint(client_id, req.name, req.goals)

@app.patch("/api/clients/{client_id}/sprint")
async def api_update_sprint(client_id: str, req: SprintUpdate, _=Depends(require_auth)):
    _agency_required()
    return update_sprint(client_id, req.done or None, req.blockers or None, req.notes or None)

@app.get("/api/clients/{client_id}/sprint")
async def api_get_sprint(client_id: str, _=Depends(require_auth)):
    _agency_required()
    return {"context": get_sprint_context(client_id)}

# ──────────────────────────────────────────────────────────────────────────────
# HOUR LOGGING / INVOICING / P&L
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/hours/log")
async def api_log_hours(req: HourLogRequest, _=Depends(require_auth)):
    _agency_required()
    return log_hours(req.client_id, req.hours, req.description, req.service_type, req.date)

@app.post("/api/hours/voice")
async def api_voice_log(req: VoiceLogRequest, _=Depends(require_auth)):
    """Parse 'Log 3 hours Acme, backend refactor' and auto-log."""
    _agency_required()
    parsed = parse_voice_log(req.text)
    if not parsed:
        return JSONResponse(400, content={"error": "Could not parse hour log. Use: 'Log X hours CLIENT, description'"})
    return log_hours(**parsed)

@app.post("/api/hours/rate")
async def api_set_rate(req: RateSetRequest, _=Depends(require_auth)):
    _agency_required()
    set_rate(req.client_id, req.rate)
    return {"status": "ok", "client_id": req.client_id, "rate": req.rate}

@app.get("/api/hours/summary")
async def api_utilization(days: int = 30, client_id: str = "", _=Depends(require_auth)):
    _agency_required()
    return get_utilization(days, client_id or None)

@app.post("/api/hours/invoice/{client_id}")
async def api_invoice(client_id: str, _=Depends(require_auth)):
    _agency_required()
    result = generate_invoice(client_id)
    if "error" in result:
        return JSONResponse(404, content=result)
    return result

@app.get("/api/hours/pl")
async def api_pl(months: int = 1, _=Depends(require_auth)):
    _agency_required()
    return get_pl_summary(months)

# ──────────────────────────────────────────────────────────────────────────────
# INTELLIGENCE: MEETINGS, PRD, SCOPE CREEP, PROPOSALS
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/meetings/analyze")
async def api_analyze_meeting(req: MeetingRequest, _=Depends(require_auth)):
    """
    Paste any meeting transcript → action items, decisions, red flags,
    scope creep signals, follow-up email. Auto-saved to client namespace.
    """
    _agency_required()
    return await analyze_meeting(req.transcript, req.client_id, req.client_name)

@app.post("/api/prd/generate")
async def api_generate_prd(req: PRDRequest, _=Depends(require_auth)):
    """Describe a feature → full PRD with API design, DB schema, edge cases."""
    _agency_required()
    content = await generate_prd(req.description, req.stack, req.client_id)
    return {"prd": content, "chars": len(content)}

@app.post("/api/scope-creep")
async def api_scope_creep(req: ScopeCreepRequest, _=Depends(require_auth)):
    """
    'Client just asked for X' → is this scope creep? Impact? Pushback language?
    """
    _agency_required()
    return await detect_scope_creep(req.new_request, req.original_scope, req.client_id)

@app.post("/api/translate/tech-to-business")
async def api_tech_translate(req: TechTranslateRequest, _=Depends(require_auth)):
    """Convert technical work description to client-facing plain English."""
    _agency_required()
    return {"translation": await tech_to_business(req.text, req.audience)}

@app.post("/api/proposals/generate")
async def api_generate_proposal(req: ProposalRequest, _=Depends(require_auth)):
    """Generate a hyper-specific proposal from prospect analysis."""
    _agency_required()
    content = await generate_proposal(req.scope, req.prospect_analysis, req.past_context)
    return {"proposal": content}

@app.post("/api/prospects/analyze")
async def api_analyze_prospect(req: ProspectRequest, _=Depends(require_auth)):
    """
    Paste website/LinkedIn/job posting → inferred stack, pain points, pitch strategy.
    """
    _agency_required()
    return await analyze_prospect(req.content)

# ──────────────────────────────────────────────────────────────────────────────
# CODEBASE INTELLIGENCE
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/codebase/index")
async def api_index_codebase(req: IndexRequest, _=Depends(require_auth)):
    """
    Index a code repository. Run once, then search/analyze forever.
    POST {"path": "/path/to/repo", "force": false}
    """
    _agency_required()
    if not pathlib.Path(req.path).exists():
        raise HTTPException(400, f"Path not found: {req.path}")
    exts = set(f".{e.lstrip('.')}" for e in req.extensions) if req.extensions else None
    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, index_directory, req.path, exts, None)
    return summary

@app.get("/api/codebase/status")
async def api_codebase_status(_=Depends(require_auth)):
    _agency_required()
    return get_index_summary()

@app.post("/api/codebase/search")
async def api_codebase_search(req: CodebaseSearchRequest, _=Depends(require_auth)):
    """Keyword search over indexed codebase chunks."""
    _agency_required()
    results = search_codebase(req.query, req.top_k, req.file_filter)
    return {"results": results, "count": len(results), "query": req.query}

@app.post("/api/codebase/architecture")
async def api_architecture(req: IndexRequest, _=Depends(require_auth)):
    """Generate/update ARCHITECTURE.md from the codebase index."""
    _agency_required()
    doc = await summarize_architecture(req.path or None, req.force)
    return {"architecture": doc, "chars": len(doc)}

@app.post("/api/codebase/impact")
async def api_impact(req: DependencyRequest, _=Depends(require_auth)):
    """'What breaks if I change X?' — traces impact across codebase."""
    _agency_required()
    return await analyze_dependency_impact(req.target)

# ──────────────────────────────────────────────────────────────────────────────
# GITHUB WEBHOOK
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/github/webhook")
async def github_webhook(request: Request):
    """
    GitHub webhook: reads push events → generates technical changelog + client update.
    Configure in GitHub repo Settings → Webhooks → Payload URL: /api/github/webhook
    No signature verification yet — add GITHUB_WEBHOOK_SECRET for production.
    """
    try:
        payload   = await request.json()
        ref       = payload.get("ref", "")
        repo_name = payload.get("repository", {}).get("name", "unknown")
        commits   = payload.get("commits", [])

        if not commits:
            return {"status": "no commits"}

        # Try to match repo to a client
        client_id = repo_name.lower()

        result = await commits_to_update(commits, client_id)
        result["repo"]    = repo_name
        result["ref"]     = ref
        result["commits"] = len(commits)

        # Save to client memory if client exists
        if _agency_ok:
            try:
                if get_client(client_id):
                    add_client_memory(
                        client_id,
                        f"DEPLOY [{ref}]: {result.get('emoji_summary','')} — {len(commits)} commits",
                        tag="deploy"
                    )
            except Exception:
                pass

        return result

    except Exception as e:
        return JSONResponse(500, content={"error": str(e)})

# ──────────────────────────────────────────────────────────────────────────────
# MOOD & CONTEXT DETECTION (injects into system prompt)
# ──────────────────────────────────────────────────────────────────────────────

def detect_message_mood(text: str) -> str:
    """
    Short terse messages → BLITZ gets direct.
    Long exploratory → BLITZ goes deep.
    All caps → match high energy.
    """
    word_count = len(text.split())
    is_all_caps = text.isupper() and len(text) > 5
    has_question = "?" in text
    ends_with_dot = text.strip().endswith(".")

    if word_count <= 4:
        return "terse"     # "do it" / "what is X" / "why"
    elif word_count >= 50:
        return "exploratory"  # detailed context dump → go deep
    elif is_all_caps:
        return "urgent"
    elif has_question and word_count < 15:
        return "direct"
    else:
        return "normal"

MOOD_INSTRUCTIONS = {
    "terse":       "User is being terse. Match their energy: be brief, direct, no fluff. Answer in ≤3 sentences unless they need more.",
    "exploratory": "User is thinking through something complex. Go deep. Explore options, tradeoffs, edge cases. Long response is appropriate.",
    "urgent":      "User seems urgent or frustrated. Acknowledge first, then solve fast. No preamble.",
    "direct":      "User wants a direct answer. Lead with the answer, then support it.",
    "normal":      "",
}

# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE INTEGRATION — OAuth2, Calendar, Gmail, Tasks
# ══════════════════════════════════════════════════════════════════════════════

_google_ok = False
try:
    from google_integration import (
        get_google_auth_url, exchange_google_code, is_google_connected,
        disconnect_google, get_calendar_events, get_today_schedule,
        get_recent_emails, get_email_summary, get_google_tasks, get_google_status,
    )
    _google_ok = True
    print("[OK] Google integration module loaded")
except Exception as _ge:
    print(f"[WARN] Google integration not loaded: {_ge}")

@app.get("/api/google/status")
async def api_google_status(_=Depends(require_auth)):
    if not _google_ok:
        return {"connected": False, "error": "Google module not loaded"}
    return await get_google_status()

@app.get("/api/google/connect")
async def api_google_connect(_=Depends(require_auth)):
    if not _google_ok:
        raise HTTPException(503, "Google module not loaded")
    url = get_google_auth_url()
    if not url:
        return {"error": "GOOGLE_CLIENT_ID not configured in .env"}
    return {"auth_url": url}

@app.get("/api/google/callback")
async def api_google_callback(code: str = ""):
    """OAuth2 callback — Google redirects here after user consent."""
    if not _google_ok or not code:
        return HTMLResponse("<script>window.close()</script>")
    tokens = await exchange_google_code(code)
    if "access_token" in tokens:
        return HTMLResponse("<html><body style='background:#06070d;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh'><div style='text-align:center'><h2>✅ Google Connected!</h2><p>You can close this window.</p><script>setTimeout(()=>window.close(),2000)</script></div></body></html>")
    return HTMLResponse(f"<html><body style='background:#06070d;color:#f87171;font-family:sans-serif;padding:40px'><h2>❌ Connection Failed</h2><pre>{tokens}</pre></body></html>")

@app.post("/api/google/disconnect")
async def api_google_disconnect(_=Depends(require_auth)):
    if not _google_ok:
        return {"status": "not loaded"}
    return disconnect_google()

@app.get("/api/google/calendar")
async def api_google_calendar(days: int = 1, _=Depends(require_auth)):
    if not _google_ok:
        return {"events": [], "connected": False}
    events = await get_calendar_events(days)
    return {"events": events, "connected": is_google_connected(), "schedule": await get_today_schedule()}

@app.get("/api/google/gmail")
async def api_google_gmail(_=Depends(require_auth)):
    if not _google_ok:
        return {"emails": [], "connected": False}
    return await get_email_summary()

@app.get("/api/google/tasks")
async def api_google_tasks(_=Depends(require_auth)):
    if not _google_ok:
        return {"tasks": [], "connected": False}
    tasks = await get_google_tasks()
    return {"tasks": tasks, "connected": is_google_connected()}

# ══════════════════════════════════════════════════════════════════════════════
# CEO JARVIS MODULE — Contacts, OKRs, Competitors, Board Prep, P&L, Biometrics
# ══════════════════════════════════════════════════════════════════════════════

_ceo_ok = False
try:
    from jarvis_ceo import (
        # Contacts
        upsert_contact, get_contact, list_contacts, get_contact_briefing,
        # Competitive Intel
        add_competitor, list_competitors, scan_competitor, get_competitive_digest,
        # OKRs
        create_objective, update_key_result, get_okr_summary,
        # Board
        generate_board_briefing,
        # People & Org
        upsert_team_member, get_org_chart, add_open_role, get_hiring_pipeline,
        # Promises
        log_promise, fulfill_promise, get_open_promises, extract_promises_from_meeting,
        # Workflows / Triggers
        create_workflow, list_workflows, create_trigger, list_triggers, execute_workflow_chain,
        # Biometrics
        ingest_biometric_data, get_biometric_summary, get_performance_insight,
        # Financials
        update_financial_kpis, get_financial_dashboard, generate_financial_narrative,
        # Market
        log_market_data, get_latest_market_data, get_market_intelligence,
        # Digest
        generate_ceo_digest,
        # Habits
        upsert_habit, log_habit, get_habit_stats,
        # Seed
        seed_agency_data,
    )
    _ceo_ok = True
    print("[OK] CEO Jarvis modules loaded")
except Exception as _ce:
    print(f"[WARN] CEO modules not loaded: {_ce}")

# ── CEO Pydantic Models ───────────────────────────────────────────────────────
class ContactUpsert(BaseModel):
    contact_id: str
    name: str
    role: str = ""
    company: str = ""
    notes: str = ""
    relationship: str = ""
    last_touchpoint: str = ""

class ContactBriefingRequest(BaseModel):
    contact_id: str
    meeting_topic: str = ""

class CompetitorAdd(BaseModel):
    name: str
    domain: str = ""
    industry: str = ""

class CompetitorScan(BaseModel):
    name: str
    domain: str = ""

class ObjectiveCreate(BaseModel):
    title: str
    quarter: str = ""
    key_results: list[dict] = []

class KRUpdate(BaseModel):
    obj_id: str
    kr_id: str
    current_value: float
    notes: str = ""

class TeamMemberUpsert(BaseModel):
    employee_id: str
    name: str
    role: str
    department: str
    manager_id: str = ""
    level: str = ""
    location: str = ""

class OpenRoleRequest(BaseModel):
    title: str
    department: str
    priority: str = "normal"
    description: str = ""
    target_date: str = ""

class PromiseCreate(BaseModel):
    promised_by: str
    promised_to: str
    what: str
    due_date: str = ""
    context: str = ""

class PromiseFulfill(BaseModel):
    promise_id: str

class PromiseExtract(BaseModel):
    transcript: str

class WorkflowCreate(BaseModel):
    name: str
    trigger: str
    steps: list[str]
    enabled: bool = True

class TriggerCreate(BaseModel):
    name: str
    condition: str
    action: str
    threshold: float = 0
    enabled: bool = True

class WorkflowExecute(BaseModel):
    trigger: str
    context: str = ""

class BiometricIngest(BaseModel):
    source: str   # whoop / oura / apple_watch / manual
    data: dict    # hrv, recovery, sleep_score, strain, steps, etc.
    date: str = ""

class FinancialKPIs(BaseModel):
    mrr: float = 0
    arr: float = 0
    burn_rate: float = 0
    runway_months: float = 0
    cash: float = 0
    headcount: int = 0
    headcount_cost: float = 0
    gross_margin: float = 0
    period: str = ""

class MarketDataLog(BaseModel):
    tickers: dict = {}
    funding_rounds: list[dict] = []
    notes: str = ""

class MarketIntelRequest(BaseModel):
    topic: str = "AI startup market"

def _ceo_required():
    if not _ceo_ok:
        raise HTTPException(503, "CEO modules failed to load. Check server logs.")

# ─── CONTACTS ─────────────────────────────────────────────────────────────────
@app.post("/api/ceo/contacts")
async def api_upsert_contact(req: ContactUpsert, _=Depends(require_auth)):
    _ceo_required()
    return upsert_contact(req.contact_id, req.name, req.role, req.company,
                          req.notes, req.relationship, req.last_touchpoint)

@app.get("/api/ceo/contacts")
async def api_list_contacts(q: str = "", _=Depends(require_auth)):
    _ceo_required()
    return {"contacts": list_contacts(q)}

@app.get("/api/ceo/contacts/{contact_id}")
async def api_get_contact(contact_id: str, _=Depends(require_auth)):
    _ceo_required()
    c = get_contact(contact_id)
    if not c: raise HTTPException(404, "Contact not found")
    return c

@app.post("/api/ceo/contacts/briefing")
async def api_contact_briefing(req: ContactBriefingRequest, _=Depends(require_auth)):
    _ceo_required()
    return {"briefing": await get_contact_briefing(req.contact_id, req.meeting_topic)}

# ─── COMPETITIVE INTEL ────────────────────────────────────────────────────────
@app.post("/api/ceo/competitors")
async def api_add_competitor(req: CompetitorAdd, _=Depends(require_auth)):
    _ceo_required()
    return add_competitor(req.name, req.domain, req.industry)

@app.get("/api/ceo/competitors")
async def api_list_competitors(_=Depends(require_auth)):
    _ceo_required()
    return {"competitors": list_competitors()}

@app.post("/api/ceo/competitors/scan")
async def api_scan_competitor(req: CompetitorScan, _=Depends(require_auth)):
    _ceo_required()
    return await scan_competitor(req.name, req.domain)

@app.get("/api/ceo/competitors/digest")
async def api_competitive_digest(_=Depends(require_auth)):
    _ceo_required()
    return await get_competitive_digest()

# ─── OKRs ─────────────────────────────────────────────────────────────────────
@app.post("/api/ceo/okrs")
async def api_create_objective(req: ObjectiveCreate, _=Depends(require_auth)):
    _ceo_required()
    return create_objective(req.title, req.quarter, req.key_results)

@app.get("/api/ceo/okrs")
async def api_get_okrs(_=Depends(require_auth)):
    _ceo_required()
    return get_okr_summary()

@app.patch("/api/ceo/okrs/kr")
async def api_update_kr(req: KRUpdate, _=Depends(require_auth)):
    _ceo_required()
    return update_key_result(req.obj_id, req.kr_id, req.current_value, req.notes)

@app.get("/api/ceo/board-briefing")
async def api_board_briefing(_=Depends(require_auth)):
    _ceo_required()
    return {"briefing": await generate_board_briefing()}

# ─── ORG CHART ────────────────────────────────────────────────────────────────
@app.post("/api/ceo/org")
async def api_upsert_member(req: TeamMemberUpsert, _=Depends(require_auth)):
    _ceo_required()
    return upsert_team_member(req.employee_id, req.name, req.role, req.department,
                              req.manager_id, req.level, req.location)

@app.get("/api/ceo/org")
async def api_org_chart(_=Depends(require_auth)):
    _ceo_required()
    return get_org_chart()

# ─── HIRING ───────────────────────────────────────────────────────────────────
@app.post("/api/ceo/hiring")
async def api_add_role(req: OpenRoleRequest, _=Depends(require_auth)):
    _ceo_required()
    return add_open_role(req.title, req.department, req.priority, req.description, req.target_date)

@app.get("/api/ceo/hiring")
async def api_hiring_pipeline(_=Depends(require_auth)):
    _ceo_required()
    return get_hiring_pipeline()

# ─── PROMISES / COMMITMENTS ───────────────────────────────────────────────────
@app.post("/api/ceo/promises")
async def api_log_promise(req: PromiseCreate, _=Depends(require_auth)):
    _ceo_required()
    return log_promise(req.promised_by, req.promised_to, req.what, req.due_date, req.context)

@app.get("/api/ceo/promises")
async def api_get_promises(_=Depends(require_auth)):
    _ceo_required()
    return {"promises": get_open_promises()}

@app.post("/api/ceo/promises/fulfill")
async def api_fulfill_promise(req: PromiseFulfill, _=Depends(require_auth)):
    _ceo_required()
    ok = fulfill_promise(req.promise_id)
    return {"status": "fulfilled" if ok else "not_found"}

@app.post("/api/ceo/promises/extract")
async def api_extract_promises(req: PromiseExtract, _=Depends(require_auth)):
    """Auto-extract commitments from a meeting transcript."""
    _ceo_required()
    saved = await extract_promises_from_meeting(req.transcript)
    return {"extracted": len(saved), "promises": saved}

# ─── WORKFLOWS ────────────────────────────────────────────────────────────────
@app.post("/api/ceo/workflows")
async def api_create_workflow(req: WorkflowCreate, _=Depends(require_auth)):
    _ceo_required()
    return create_workflow(req.name, req.trigger, req.steps, req.enabled)

@app.get("/api/ceo/workflows")
async def api_list_workflows(_=Depends(require_auth)):
    _ceo_required()
    return {"workflows": list_workflows()}

@app.post("/api/ceo/workflows/execute")
async def api_execute_workflow(req: WorkflowExecute, _=Depends(require_auth)):
    _ceo_required()
    return await execute_workflow_chain(req.trigger, req.context)

@app.post("/api/ceo/triggers")
async def api_create_trigger(req: TriggerCreate, _=Depends(require_auth)):
    _ceo_required()
    return create_trigger(req.name, req.condition, req.action, req.threshold, req.enabled)

@app.get("/api/ceo/triggers")
async def api_list_triggers(_=Depends(require_auth)):
    _ceo_required()
    return {"triggers": list_triggers()}

# ─── BIOMETRICS ───────────────────────────────────────────────────────────────
@app.post("/api/ceo/biometrics")
async def api_ingest_biometrics(req: BiometricIngest, _=Depends(require_auth)):
    _ceo_required()
    return ingest_biometric_data(req.source, req.data, req.date)

@app.get("/api/ceo/biometrics")
async def api_biometric_summary(days: int = 7, _=Depends(require_auth)):
    _ceo_required()
    return get_biometric_summary(days)

@app.get("/api/ceo/biometrics/insight")
async def api_biometric_insight(days: int = 7, _=Depends(require_auth)):
    _ceo_required()
    return {"insight": await get_performance_insight(days)}

# ─── FINANCIALS ───────────────────────────────────────────────────────────────
@app.post("/api/ceo/financials")
async def api_update_financials(req: FinancialKPIs, _=Depends(require_auth)):
    _ceo_required()
    kpis = {k: v for k, v in req.dict().items() if k != "period" and v}
    return update_financial_kpis(kpis, req.period)

@app.get("/api/ceo/financials")
async def api_financial_dashboard(_=Depends(require_auth)):
    _ceo_required()
    return get_financial_dashboard()

@app.get("/api/ceo/financials/narrative")
async def api_financial_narrative(_=Depends(require_auth)):
    _ceo_required()
    return {"narrative": await generate_financial_narrative()}

# ─── MARKET INTELLIGENCE ──────────────────────────────────────────────────────
@app.post("/api/ceo/market")
async def api_log_market(req: MarketDataLog, _=Depends(require_auth)):
    _ceo_required()
    return log_market_data(req.tickers, req.funding_rounds, req.notes)

@app.get("/api/ceo/market")
async def api_latest_market(_=Depends(require_auth)):
    _ceo_required()
    return get_latest_market_data()

@app.post("/api/ceo/market/intel")
async def api_market_intel(req: MarketIntelRequest, _=Depends(require_auth)):
    _ceo_required()
    return await get_market_intelligence(req.topic)

# ─── CEO DIGEST (master endpoint) ─────────────────────────────────────────────
@app.get("/api/ceo/digest")
async def api_ceo_digest(_=Depends(require_auth)):
    """Full CEO morning digest — all data sources in one call."""
    if not _ceo_ok:
        return {"error": "CEO modules not loaded"}
    return await generate_ceo_digest()

# ── Serve HTML ────────────────────────────────────────────────────────────────

import pathlib as _pl
_HTML_DIR = _pl.Path(__file__).parent
_HTML_FILES = ["blitz_hub.html", "forge.html", "canvas.html", "nexus.html", "studio.html", "index.html", "jarvis_hud.html"]

for _fname in _HTML_FILES:
    _path = _HTML_DIR / _fname
    if _path.exists():
        @app.get(f"/{_fname}", include_in_schema=False)
        async def _serve(f=_path):
            return FileResponse(f, media_type="text/html")

# ── Habits Tracker ────────────────────────────────────────────────────────────
class HabitUpsert(BaseModel):
    habit_id: str
    name: str
    icon: str = "🎯"
    target_per_month: int = 25

class HabitLog(BaseModel):
    habit_id: str
    done: bool = True
    date: str = ""
    notes: str = ""

@app.post("/api/ceo/habits")
async def api_upsert_habit(body: HabitUpsert, _=Depends(require_auth)):
    if not _ceo_ok: raise HTTPException(503)
    return upsert_habit(body.habit_id, body.name, body.icon, body.target_per_month)

@app.post("/api/ceo/habits/log")
async def api_log_habit(body: HabitLog, _=Depends(require_auth)):
    if not _ceo_ok: raise HTTPException(503)
    return log_habit(body.habit_id, body.done, body.date, body.notes)

@app.get("/api/ceo/habits")
async def api_get_habits(months: int = 6, _=Depends(require_auth)):
    if not _ceo_ok: raise HTTPException(503)
    return get_habit_stats(months)

# ── Seed Data ─────────────────────────────────────────────────────────────────
@app.post("/api/ceo/seed")
async def api_seed_data(_=Depends(require_auth)):
    if not _ceo_ok: raise HTTPException(503)
    return seed_agency_data()

_CLEAN_ROUTES = {"hub": "blitz_hub.html", "forge": "forge.html", "canvas": "canvas.html", "nexus": "nexus.html", "studio": "studio.html", "jarvis": "jarvis_hud.html"}
for _route, _file in _CLEAN_ROUTES.items():
    _fpath = _HTML_DIR / _file
    if _fpath.exists():
        @app.get(f"/{_route}", include_in_schema=False)
        async def _serve_clean(f=_fpath):
            return FileResponse(f, media_type="text/html")

@app.get("/")
async def root(request: Request):
    # Check auth via cookie
    token = request.cookies.get("blitz_token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token or not verify_token(token):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/login")
    return FileResponse(_pl.Path(__file__).parent / "index.html", media_type="text/html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
