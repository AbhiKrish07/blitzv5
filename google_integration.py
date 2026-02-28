"""
B.L.I.T.Z. Google Integration — Calendar, Gmail, Contacts, Tasks
OAuth2 flow + API wrappers for CEO-grade Google connectivity.
"""
import os, json, pathlib, time
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/google/callback")
GOOGLE_SCOPES        = "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/tasks.readonly"

TOKEN_FILE = pathlib.Path(os.getenv("CEO_DATA_DIR", "ceo_data")) / "google_token.json"
TOKEN_FILE.parent.mkdir(exist_ok=True)

_httpx = None
def _get_httpx():
    global _httpx
    if _httpx is None:
        import httpx
        _httpx = httpx
    return _httpx

# ─────────────────────────────────────────────────────────────────────────────
# OAuth2 Flow
# ─────────────────────────────────────────────────────────────────────────────

def get_google_auth_url() -> str:
    """Generate Google OAuth2 consent URL."""
    if not GOOGLE_CLIENT_ID:
        return ""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"

async def exchange_google_code(code: str) -> dict:
    """Exchange authorization code for tokens."""
    httpx = _get_httpx()
    async with httpx.AsyncClient() as client:
        r = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        tokens = r.json()
        if "access_token" in tokens:
            tokens["obtained_at"] = time.time()
            TOKEN_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        return tokens

async def _get_valid_token() -> Optional[str]:
    """Get a valid access token, refreshing if needed."""
    if not TOKEN_FILE.exists():
        return None
    tokens = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    obtained_at = tokens.get("obtained_at", 0)
    expires_in = tokens.get("expires_in", 3600)

    # Check if expired (with 5 min buffer)
    if time.time() - obtained_at > expires_in - 300:
        if refresh_token:
            httpx = _get_httpx()
            async with httpx.AsyncClient() as client:
                r = await client.post("https://oauth2.googleapis.com/token", data={
                    "refresh_token": refresh_token,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                })
                new_tokens = r.json()
                if "access_token" in new_tokens:
                    tokens["access_token"] = new_tokens["access_token"]
                    tokens["obtained_at"] = time.time()
                    tokens["expires_in"] = new_tokens.get("expires_in", 3600)
                    TOKEN_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
                    return new_tokens["access_token"]
        return None
    return access_token

def is_google_connected() -> bool:
    return TOKEN_FILE.exists()

def disconnect_google():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return {"status": "disconnected"}

# ─────────────────────────────────────────────────────────────────────────────
# Google Calendar
# ─────────────────────────────────────────────────────────────────────────────

async def get_calendar_events(days: int = 1, max_results: int = 15) -> list[dict]:
    """Fetch upcoming calendar events."""
    token = await _get_valid_token()
    if not token:
        return []
    
    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(days=days)).isoformat() + "Z"
    
    httpx = _get_httpx()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "maxResults": max_results,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                }
            )
            data = r.json()
            events = []
            for item in data.get("items", []):
                start = item.get("start", {})
                end = item.get("end", {})
                events.append({
                    "id": item.get("id", ""),
                    "title": item.get("summary", "No Title"),
                    "start": start.get("dateTime", start.get("date", "")),
                    "end": end.get("dateTime", end.get("date", "")),
                    "location": item.get("location", ""),
                    "description": (item.get("description") or "")[:200],
                    "attendees": [a.get("email", "") for a in item.get("attendees", [])[:5]],
                    "link": item.get("hangoutLink", item.get("htmlLink", "")),
                    "status": item.get("status", ""),
                })
            return events
    except Exception as e:
        print(f"[Google Calendar] Error: {e}")
        return []

async def get_today_schedule() -> str:
    """Human-readable schedule for today."""
    events = await get_calendar_events(days=1)
    if not events:
        return "No events scheduled today." if is_google_connected() else "Google Calendar not connected."
    
    lines = []
    for ev in events:
        t = ev["start"]
        if "T" in t:
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                t = dt.strftime("%H:%M")
            except:
                pass
        line = f"• {t} — {ev['title']}"
        if ev.get("location"):
            line += f" 📍 {ev['location']}"
        if ev.get("attendees"):
            line += f" ({len(ev['attendees'])} attendees)"
        lines.append(line)
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Gmail
# ─────────────────────────────────────────────────────────────────────────────

async def get_recent_emails(max_results: int = 10, query: str = "is:unread") -> list[dict]:
    """Fetch recent emails from Gmail."""
    token = await _get_valid_token()
    if not token:
        return []
    
    httpx = _get_httpx()
    try:
        async with httpx.AsyncClient() as client:
            # List messages
            r = await client.get(
                "https://www.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"maxResults": max_results, "q": query}
            )
            msg_list = r.json().get("messages", [])
            
            emails = []
            for msg_ref in msg_list[:max_results]:
                rm = await client.get(
                    f"https://www.googleapis.com/gmail/v1/users/me/messages/{msg_ref['id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata", "metadataHeaders": "Subject,From,Date"}
                )
                msg = rm.json()
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                emails.append({
                    "id": msg.get("id", ""),
                    "subject": headers.get("Subject", "No Subject"),
                    "from": headers.get("From", "Unknown"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", "")[:200],
                    "labels": msg.get("labelIds", []),
                    "unread": "UNREAD" in msg.get("labelIds", []),
                })
            return emails
    except Exception as e:
        print(f"[Gmail] Error: {e}")
        return []

async def get_email_summary() -> dict:
    """Get email stats + top unread."""
    emails = await get_recent_emails(max_results=20, query="is:unread")
    return {
        "unread_count": len(emails),
        "top_emails": emails[:5],
        "connected": is_google_connected(),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Google Tasks
# ─────────────────────────────────────────────────────────────────────────────

async def get_google_tasks(max_results: int = 20) -> list[dict]:
    """Fetch tasks from Google Tasks."""
    token = await _get_valid_token()
    if not token:
        return []
    
    httpx = _get_httpx()
    try:
        async with httpx.AsyncClient() as client:
            # Get task lists
            r = await client.get(
                "https://www.googleapis.com/tasks/v1/users/@me/lists",
                headers={"Authorization": f"Bearer {token}"}
            )
            lists = r.json().get("items", [])
            
            all_tasks = []
            for tl in lists[:3]:
                rt = await client.get(
                    f"https://www.googleapis.com/tasks/v1/lists/{tl['id']}/tasks",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"maxResults": max_results, "showCompleted": "false"}
                )
                for task in rt.json().get("items", []):
                    all_tasks.append({
                        "id": task.get("id", ""),
                        "title": task.get("title", ""),
                        "due": task.get("due", ""),
                        "status": task.get("status", "needsAction"),
                        "notes": (task.get("notes") or "")[:150],
                        "list": tl.get("title", ""),
                    })
            return all_tasks
    except Exception as e:
        print(f"[Google Tasks] Error: {e}")
        return []

# ─────────────────────────────────────────────────────────────────────────────
# Combined Status
# ─────────────────────────────────────────────────────────────────────────────

async def get_google_status() -> dict:
    """Full Google connection status with data previews."""
    connected = is_google_connected()
    result = {
        "connected": connected,
        "auth_url": get_google_auth_url() if not connected else "",
    }
    if connected:
        events = await get_calendar_events(days=1)
        emails = await get_email_summary()
        result["calendar"] = {
            "today_count": len(events),
            "events": events[:5],
            "schedule": await get_today_schedule(),
        }
        result["gmail"] = emails
    return result
