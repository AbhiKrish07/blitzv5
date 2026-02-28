"""
B.L.I.T.Z. Proactive Intelligence — Background cron agents that monitor the world.
Injects a morning briefing into every session.
"""
import os, asyncio, json, time
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
USER_CITY       = os.getenv("USER_CITY", "Singapore")

_groq = None
def _get_groq():
    global _groq
    if _groq is None:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq

# ── Shared state ──────────────────────────────────────────────────────────────
_briefing: dict = {
    "generated_at": None,
    "summary": "",
    "weather": "",
    "news": [],
    "day": ""
}
_cron_running = False

# ── Weather fetch ─────────────────────────────────────────────────────────────
async def fetch_weather() -> str:
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
            temp  = round(d["main"]["temp"])
            feels = round(d["main"]["feels_like"])
            desc  = d["weather"][0]["description"].capitalize()
            humid = d["main"]["humidity"]
            return f"{USER_CITY}: {desc}, {temp}°C (feels like {feels}°C), humidity {humid}%"
    except Exception as e:
        return f"Weather unavailable ({e})"


# ── News fetch via Tavily ─────────────────────────────────────────────────────
async def fetch_news(topics: list[str] = None) -> list[str]:
    if not TAVILY_API_KEY:
        return []
    topics = topics or ["AI technology breakthroughs", "JEE preparation tips", "NTU NUS Singapore admissions"]
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        headlines = []
        for topic in topics[:3]:
            results = tavily.search(topic, max_results=2, search_depth="basic")
            for r in results.get("results", [])[:1]:
                headlines.append(f"• [{topic}] {r['title']}")
        return headlines
    except Exception as e:
        print(f"[CRON] News fetch failed: {e}")
        return []


# ── Synthesise briefing ───────────────────────────────────────────────────────
async def generate_morning_briefing():
    """Generate a concise morning briefing. Runs once every few hours."""
    global _briefing
    
    now = datetime.now()
    day_str  = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%H:%M")
    
    weather = await fetch_weather()
    news    = await fetch_news()
    
    news_block = "\n".join(news) if news else "No major updates."
    weather_block = weather or "Weather data unavailable."
    
    prompt = f"""You are B.L.I.T.Z. generating a 3-sentence morning briefing for Abhinav. Today is {day_str}, {time_str}.

Weather: {weather_block}
Recent Headlines:
{news_block}

Write a natural, JARVIS-style briefing that's concise, smart, and personal. Include the date/time, one weather note if relevant, and one key insight from the news. Maximum 3 sentences. No bullet points. Speak directly."""

    try:
        groq = _get_groq()
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.6
        )
        summary = r.choices[0].message.content.strip()
    except Exception as e:
        summary = f"Good {get_time_of_day()}, sir. It's {day_str}. All systems nominal."
    
    _briefing = {
        "generated_at": time.time(),
        "summary": summary,
        "weather": weather,
        "news": news,
        "day": day_str
    }
    print(f"[CRON] Briefing updated: {summary[:60]}...")


def get_time_of_day() -> str:
    h = datetime.now().hour
    if h < 12:
        return "morning"
    elif h < 17:
        return "afternoon"
    else:
        return "evening"


# ── Get current briefing ──────────────────────────────────────────────────────
def get_briefing_context() -> str:
    """Returns briefing to inject into system prompt."""
    if not _briefing.get("summary"):
        now = datetime.now()
        return f"Current time: {now.strftime('%H:%M on %A, %B %d, %Y')}."
    
    age_hours = (time.time() - (_briefing.get("generated_at") or 0)) / 3600
    stale = " (briefing may be slightly outdated)" if age_hours > 4 else ""
    
    return f"""== LIVE CONTEXT{stale} ==
{_briefing['summary']}
Time: {datetime.now().strftime('%H:%M')} | {_briefing.get('day', '')}
{f"Weather: {_briefing['weather']}" if _briefing.get('weather') else ''}""".strip()


# ── Background cron loop ──────────────────────────────────────────────────────
async def cron_loop():
    """Background task: regenerate briefing every 3 hours."""
    global _cron_running
    _cron_running = True
    
    # Initial briefing on startup
    await asyncio.sleep(3)  # Let server start first
    await generate_morning_briefing()
    
    while True:
        await asyncio.sleep(3 * 3600)  # 3 hours
        try:
            await generate_morning_briefing()
        except Exception as e:
            print(f"[CRON ERROR] {e}")


def start_cron(loop=None):
    """Start background cron. Call from FastAPI startup event."""
    asyncio.create_task(cron_loop())
    print("[OK] Proactive cron started")
