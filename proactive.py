"""
B.L.I.T.Z. Proactive Intelligence — Background cron agents.
Generates a morning briefing: weather + news + tasks + calendar events.
Injects live context into every session's system prompt.
"""
import os, asyncio, json, time, pathlib
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY", "")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
USER_CITY       = os.getenv("USER_CITY", "Singapore")
TASKS_FILE      = pathlib.Path(os.getenv("TASKS_FILE", "tasks.json"))

_groq = None
def _get_groq():
    global _groq
    if _groq is None:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq

# ── Shared state ───────────────────────────────────────────────────────────────
_briefing: dict = {
    "generated_at": None,
    "summary": "",
    "weather": "",
    "news": [],
    "tasks": [],
    "calendar": [],
    "day": ""
}
_cron_running = False


# ── Weather ────────────────────────────────────────────────────────────────────
async def fetch_weather() -> str:
    """Fetch current weather. Returns empty string if key not set."""
    if not WEATHER_API_KEY:
        return ""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": USER_CITY, "appid": WEATHER_API_KEY, "units": "metric"}
            )
            d = r.json()

            # Check for API error before accessing keys
            if d.get("cod") != 200 and d.get("cod") != "200":
                code = d.get("cod", "?")
                msg  = d.get("message", "unknown error")
                print(f"[WEATHER] API error {code}: {msg}")
                # Try to give a helpful hint
                if "city not found" in str(msg).lower():
                    print(f"[WEATHER] City '{USER_CITY}' not found. Check USER_CITY in .env")
                return ""

            # Safe key access
            main   = d.get("main", {})
            temp   = round(main.get("temp", 0))
            feels  = round(main.get("feels_like", temp))
            humid  = main.get("humidity", 0)
            weather_list = d.get("weather", [{}])
            desc   = weather_list[0].get("description", "clear").capitalize() if weather_list else "Clear"
            icon   = _weather_emoji(weather_list[0].get("main", "") if weather_list else "")

            return f"{icon} {USER_CITY}: {desc}, {temp}°C (feels {feels}°C), humidity {humid}%"

    except Exception as e:
        print(f"[WEATHER] Fetch failed: {e}")
        return ""


def _weather_emoji(condition: str) -> str:
    """Map OpenWeatherMap condition string to an emoji."""
    mapping = {
        "Thunderstorm": "⛈️",
        "Drizzle": "🌦️",
        "Rain": "🌧️",
        "Snow": "❄️",
        "Mist": "🌫️",
        "Fog": "🌫️",
        "Haze": "🌫️",
        "Clear": "☀️",
        "Clouds": "☁️",
        "Smoke": "💨",
        "Dust": "💨",
        "Sand": "💨",
        "Ash": "🌋",
        "Squall": "🌬️",
        "Tornado": "🌪️",
    }
    return mapping.get(condition, "🌡️")


# ── News ───────────────────────────────────────────────────────────────────────
async def fetch_news(topics: list[str] = None) -> list[str]:
    if not TAVILY_API_KEY:
        return []
    topics = topics or ["AI technology", "tech startup news", "software engineering"]
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        headlines = []
        for topic in topics[:2]:
            results = tavily.search(topic, max_results=2, search_depth="basic")
            for r in results.get("results", [])[:1]:
                headlines.append(f"• {r['title']}")
        return headlines
    except Exception as e:
        print(f"[CRON] News fetch failed: {e}")
        return []


# ── Tasks ──────────────────────────────────────────────────────────────────────
def load_tasks() -> list[dict]:
    """Load tasks from tasks.json. Returns list of task dicts."""
    if not TASKS_FILE.exists():
        return []
    try:
        data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("tasks", [])
    except Exception:
        return []


def save_tasks(tasks: list[dict]):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")


def add_task(title: str, due: str = "", priority: str = "medium", client_id: str = "") -> dict:
    """Add a task. due format: 'YYYY-MM-DD' or natural like 'tomorrow'."""
    tasks = load_tasks()

    # Resolve natural language dates
    if due.lower() == "today":
        due = datetime.now().strftime("%Y-%m-%d")
    elif due.lower() == "tomorrow":
        due = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    task = {
        "id": f"task_{int(time.time())}",
        "title": title,
        "due": due,
        "priority": priority,        # low / medium / high / urgent
        "client_id": client_id,
        "done": False,
        "created": datetime.now().strftime("%Y-%m-%d"),
    }
    tasks.append(task)
    save_tasks(tasks)
    return task


def complete_task(task_id: str) -> bool:
    tasks = load_tasks()
    for t in tasks:
        if t.get("id") == task_id or task_id.lower() in t.get("title", "").lower():
            t["done"] = True
            t["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            save_tasks(tasks)
            return True
    return False


def get_pending_tasks(limit: int = 10) -> list[dict]:
    """Return pending tasks sorted by priority then due date."""
    tasks = load_tasks()
    pending = [t for t in tasks if not t.get("done")]
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    pending.sort(key=lambda t: (
        priority_order.get(t.get("priority", "medium"), 2),
        t.get("due", "9999-99-99")
    ))
    return pending[:limit]


def get_tasks_summary() -> str:
    """Format task list for display in briefing."""
    pending = get_pending_tasks(8)
    if not pending:
        return "No pending tasks. ✅"
    lines = []
    for t in pending:
        pri = {"urgent": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(t.get("priority", "medium"), "⚪")
        due = f" — due {t['due']}" if t.get("due") else ""
        client = f" [{t['client_id']}]" if t.get("client_id") else ""
        lines.append(f"{pri} {t['title']}{client}{due}")
    return "\n".join(lines)


# ── Google Calendar (optional) ─────────────────────────────────────────────────
GCAL_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
GCAL_TOKEN       = pathlib.Path("gcal_token.json")


async def fetch_calendar_events(days_ahead: int = 1) -> list[str]:
    """
    Fetch upcoming Google Calendar events.
    Requires GOOGLE_CREDENTIALS_JSON env var (service account JSON or OAuth2 token).
    Gracefully returns [] if not configured.
    """
    if not GCAL_CREDENTIALS and not GCAL_TOKEN.exists():
        return []
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        import json as _json

        creds = None
        if GCAL_TOKEN.exists():
            creds = Credentials.from_authorized_user_info(
                _json.loads(GCAL_TOKEN.read_text()), scopes=["https://www.googleapis.com/auth/calendar.readonly"]
            )
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GCAL_TOKEN.write_text(creds.to_json())

        service = build("calendar", "v3", credentials=creds)
        now     = datetime.utcnow().isoformat() + "Z"
        end     = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + "Z"

        result  = service.events().list(
            calendarId="primary",
            timeMin=now, timeMax=end,
            maxResults=10, singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = result.get("items", [])
        formatted = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date", ""))
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M")
            except Exception:
                time_str = start
            formatted.append(f"📅 {time_str} — {e.get('summary', 'Untitled event')}")
        return formatted

    except ImportError:
        # google-api-python-client not installed — silent skip
        return []
    except Exception as e:
        print(f"[GCAL] Error: {e}")
        return []


# ── Morning Briefing ───────────────────────────────────────────────────────────
async def generate_morning_briefing():
    """Generate the full morning briefing: weather + news + tasks + calendar."""
    global _briefing

    now      = datetime.now()
    day_str  = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%H:%M")

    # Fetch all sources in parallel
    weather_task  = asyncio.create_task(fetch_weather())
    news_task     = asyncio.create_task(fetch_news())
    calendar_task = asyncio.create_task(fetch_calendar_events(1))

    weather  = await weather_task
    news     = await news_task
    calendar = await calendar_task
    tasks    = get_pending_tasks(5)

    # Build briefing text
    tasks_summary    = get_tasks_summary()
    news_block       = "\n".join(news) if news else "No major updates."
    calendar_block   = "\n".join(calendar) if calendar else "No events today."
    weather_block    = weather or "Weather data not configured (set OPENWEATHER_API_KEY)."

    prompt = f"""You are B.L.I.T.Z., a JARVIS-style AI assistant. Generate a sharp, 3-sentence morning briefing for your user.

Today: {day_str}, {time_str}
Weather: {weather_block}
Today's calendar: {calendar_block}
Pending tasks ({len(tasks)} total): {tasks_summary[:300]}
Top news: {news_block}

Rules:
- Be direct and personal, like JARVIS talking to Tony Stark
- Lead with the most important thing (urgent task, key meeting, or weather if severe)
- Maximum 3 sentences. No bullet points in the summary itself.
- Speak directly — no 'Good morning sir' cliché"""

    try:
        groq = _get_groq()
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.6
        )
        summary = r.choices[0].message.content.strip()
    except Exception as e:
        greeting = get_time_of_day()
        summary = f"Good {greeting}. It's {day_str}. You have {len(tasks)} pending tasks."

    _briefing = {
        "generated_at": time.time(),
        "summary":      summary,
        "weather":      weather,
        "news":         news,
        "tasks":        tasks,
        "calendar":     calendar,
        "day":          day_str,
        "time":         time_str,
    }
    print(f"[CRON] Briefing updated — {summary[:70]}...")


# ── Public Getters ─────────────────────────────────────────────────────────────
def get_briefing_context() -> str:
    """Inject into system prompt every session."""
    if not _briefing.get("summary"):
        now = datetime.now()
        return f"Current time: {now.strftime('%H:%M on %A, %B %d, %Y')}."

    age_hours = (time.time() - (_briefing.get("generated_at") or 0)) / 3600
    stale     = " (may be slightly outdated)" if age_hours > 4 else ""
    weather   = f"\nWeather: {_briefing['weather']}" if _briefing.get("weather") else ""
    tasks_str = get_tasks_summary()

    return f"""== LIVE CONTEXT{stale} ==
{_briefing['summary']}
Time: {datetime.now().strftime('%H:%M')} | {_briefing.get('day', '')}
{weather}
Tasks: {tasks_str[:200]}""".strip()


def get_full_briefing() -> dict:
    """Return the full briefing dict for the /api/briefing endpoint."""
    tasks_str = get_tasks_summary()
    cal_str   = "\n".join(_briefing.get("calendar", [])) or "No events today."
    return {
        "summary":  _briefing.get("summary", ""),
        "weather":  _briefing.get("weather", ""),
        "news":     _briefing.get("news", []),
        "tasks":    tasks_str,
        "calendar": cal_str,
        "day":      _briefing.get("day", ""),
        "time":     _briefing.get("time", ""),
        "fresh":    (time.time() - (_briefing.get("generated_at") or 0)) < 4 * 3600,
    }


def get_time_of_day() -> str:
    h = datetime.now().hour
    return "morning" if h < 12 else "afternoon" if h < 17 else "evening"


# ── Background Cron ────────────────────────────────────────────────────────────
async def cron_loop():
    global _cron_running
    _cron_running = True

    await asyncio.sleep(2)   # let server fully start first
    await generate_morning_briefing()

    while True:
        await asyncio.sleep(3 * 3600)   # refresh every 3 hours
        try:
            await generate_morning_briefing()
        except Exception as e:
            print(f"[CRON ERROR] {e}")


def start_cron(loop=None):
    asyncio.create_task(cron_loop())
    print("[OK] Proactive cron started — weather + tasks + calendar")
