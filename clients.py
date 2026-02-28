"""
B.L.I.T.Z. Client Memory Namespaces
Each client gets isolated storage: stack, goals, sprints, hours, meetings, notes.
Designed for a technical agency managing multiple clients.
"""
import os, json, time, pathlib, re
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

CLIENTS_DIR = pathlib.Path(os.getenv("CLIENTS_DIR", "clients"))


# ── Helpers ───────────────────────────────────────────────────────────────────
def _client_dir(client_id: str) -> pathlib.Path:
    safe_id = re.sub(r"[^\w\-]", "_", client_id.lower().strip())
    d = CLIENTS_DIR / safe_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _write_json(path: pathlib.Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Client CRUD ───────────────────────────────────────────────────────────────
def create_client(
    client_id: str,
    name: str,
    stack: list[str] = None,
    goals: list[str] = None,
    notes: str = "",
    rate: float = 0.0,
    timezone: str = "UTC"
) -> dict:
    """Create a new client namespace with isolated memory."""
    d = _client_dir(client_id)
    profile = {
        "id": client_id,
        "name": name,
        "created_at": time.time(),
        "stack": stack or [],
        "goals": goals or [],
        "notes": notes,
        "non_negotiables": [],
        "comm_style": "",
        "health": "green",           # green / yellow / red
        "last_contact": time.time(),
        "rate": rate,                # hourly rate USD
        "mrr": 0.0,
        "timezone": timezone,
        "tags": [],
    }
    _write_json(d / "profile.json", profile)
    _write_json(d / "memory.json", {"entries": [], "personality": {}})
    _write_json(d / "sprints.json", {"sprints": []})
    _write_json(d / "meetings.json", {"meetings": []})
    return profile


def list_clients() -> list[dict]:
    """Return all client profiles."""
    if not CLIENTS_DIR.exists():
        return []
    clients = []
    for d in CLIENTS_DIR.iterdir():
        if d.is_dir():
            p = _read_json(d / "profile.json", None)
            if p:
                clients.append(p)
    return sorted(clients, key=lambda c: c.get("name", ""))


def get_client(client_id: str) -> Optional[dict]:
    d = _client_dir(client_id)
    return _read_json(d / "profile.json", None)


def update_client(client_id: str, updates: dict) -> dict:
    profile = get_client(client_id) or {"id": client_id}
    profile.update(updates)
    _write_json(_client_dir(client_id) / "profile.json", profile)
    return profile


# ── Client Memory ─────────────────────────────────────────────────────────────
def add_client_memory(client_id: str, entry: str, tag: str = "note") -> dict:
    """Append an entry to a client's memory log."""
    d = _client_dir(client_id)
    mf = d / "memory.json"
    data = _read_json(mf, {"entries": [], "personality": {}})
    record = {
        "text": entry,
        "tag": tag,            # note / decision / red_flag / feedback / blocker
        "ts": time.strftime("%Y-%m-%d %H:%M"),
        "timestamp": time.time()
    }
    data["entries"].append(record)
    data["entries"] = data["entries"][-300:]  # keep last 300
    _write_json(mf, data)
    return record


def search_client_memory(client_id: str, query: str, top_k: int = 10) -> list[dict]:
    """Keyword-scored search over a client's memory entries."""
    from embeddings import keyword_score
    d = _client_dir(client_id)
    data = _read_json(d / "memory.json", {"entries": []})
    entries = data.get("entries", [])
    if not query.strip():
        return entries[-top_k:]
    scored = [(e, keyword_score(query, e.get("text", ""))) for e in entries]
    scored.sort(key=lambda x: x[1], reverse=True)
    relevant = [e for e, s in scored if s > 0][:top_k]
    return relevant if relevant else entries[-top_k:]


def get_client_context(client_id: str, query: str = "") -> str:
    """
    Build full client context string for injection into system prompt.
    Includes profile, recent memory, and active sprint.
    """
    profile = get_client(client_id)
    if not profile:
        return ""

    d = _client_dir(client_id)

    # Recent memory (relevant or latest)
    relevant_mem = search_client_memory(client_id, query, top_k=10) if query else []
    if not relevant_mem:
        data = _read_json(d / "memory.json", {"entries": []})
        relevant_mem = data.get("entries", [])[-10:]

    # Active sprint
    sprint_ctx = ""
    sprints_data = _read_json(d / "sprints.json", {"sprints": []})
    sprints = sprints_data.get("sprints", [])
    if sprints:
        active = next((s for s in reversed(sprints) if s.get("status") == "active"), None)
        if active:
            done_str = ", ".join(active.get("done", [])[:3]) or "none yet"
            pending_str = ", ".join(active.get("pending", [])[:3]) or "none"
            sprint_ctx = (f"\n[SPRINT: {active.get('name','?')}] "
                          f"Done: {done_str} | Pending: {pending_str} | "
                          f"Blockers: {', '.join(active.get('blockers', [])) or 'none'}")

    # Days since contact
    days_since = int((time.time() - profile.get("last_contact", time.time())) / 86400)

    lines = [
        f"== CLIENT: {profile['name']} ({client_id}) ==",
        f"Stack: {', '.join(profile.get('stack', [])) or 'Not specified'}",
        f"Goals: {', '.join(profile.get('goals', [])) or 'Not specified'}",
        f"Non-negotiables: {', '.join(profile.get('non_negotiables', [])) or 'None on record'}",
        f"Comm style: {profile.get('comm_style') or 'Not yet characterized'}",
        f"Health: {profile.get('health', 'green').upper()} | Last contact: {days_since}d ago",
        f"Rate: ${profile.get('rate', 0)}/hr | MRR: ${profile.get('mrr', 0)}",
        sprint_ctx,
        "\n[RECENT NOTES]",
        *[f"  [{e.get('tag','note')}] {e.get('ts','')} — {e.get('text','')}" for e in relevant_mem[-8:]],
    ]
    return "\n".join(l for l in lines if l)


# ── Sprint Management ─────────────────────────────────────────────────────────
def start_sprint(client_id: str, sprint_name: str, goals: list[str]) -> dict:
    """Start a new sprint. Auto-closes any active sprint."""
    d = _client_dir(client_id)
    sf = d / "sprints.json"
    data = _read_json(sf, {"sprints": []})

    for s in data["sprints"]:
        if s.get("status") == "active":
            s["status"] = "completed"
            s["completed_at"] = time.time()

    sprint = {
        "name": sprint_name,
        "started_at": time.time(),
        "status": "active",
        "goals": goals,
        "done": [],
        "pending": list(goals),
        "blockers": [],
        "notes": ""
    }
    data["sprints"].append(sprint)
    _write_json(sf, data)
    return sprint


def update_sprint(client_id: str, done: list[str] = None, blockers: list[str] = None, notes: str = None) -> dict:
    """Update the active sprint's progress."""
    d = _client_dir(client_id)
    sf = d / "sprints.json"
    data = _read_json(sf, {"sprints": []})
    active = next((s for s in reversed(data["sprints"]) if s.get("status") == "active"), None)
    if not active:
        return {"error": "No active sprint"}
    if done:
        active["done"].extend(done)
        active["pending"] = [p for p in active["pending"] if p not in done]
    if blockers is not None:
        active["blockers"] = blockers
    if notes is not None:
        active["notes"] = notes
    _write_json(sf, data)
    return active


def get_sprint_context(client_id: str) -> str:
    """
    'Start Acme sprint 3' → BLITZ already knows: what's done, pending, blockers.
    Returns full sprint history context string.
    """
    d = _client_dir(client_id)
    sprints_data = _read_json(d / "sprints.json", {"sprints": []})
    sprints = sprints_data.get("sprints", [])
    if not sprints:
        return f"No sprint history for client {client_id}."

    lines = [f"Sprint history for {client_id} ({len(sprints)} sprints total):"]
    for s in sprints[-5:]:  # last 5 sprints
        status = s.get("status", "?")
        lines.append(
            f"\n[{s.get('name', '?')}] Status: {status.upper()}"
            f"\n  Goals: {', '.join(s.get('goals', []))}"
            f"\n  Done: {', '.join(s.get('done', []) or ['nothing logged'])}"
            f"\n  Pending: {', '.join(s.get('pending', []) or ['all done'])}"
            f"\n  Blockers: {', '.join(s.get('blockers', []) or ['none'])}"
        )
    return "\n".join(lines)


# ── At-Risk Detection ─────────────────────────────────────────────────────────
def get_at_risk_clients(days_threshold: int = 7) -> list[dict]:
    """Flag clients by: no contact > N days, health red/yellow, open blockers."""
    clients = list_clients()
    at_risk = []
    now = time.time()
    for c in clients:
        days_since = (now - c.get("last_contact", now)) / 86400
        risks = []
        if days_since >= days_threshold:
            risks.append(f"No contact in {int(days_since)}d")
        if c.get("health") in ("red", "yellow"):
            risks.append(f"Health: {c['health'].upper()}")

        # Check for open blockers in active sprint
        sprints = _read_json(_client_dir(c["id"]) / "sprints.json", {"sprints": []}).get("sprints", [])
        active = next((s for s in reversed(sprints) if s.get("status") == "active"), None)
        if active and active.get("blockers"):
            risks.append(f"Open blockers: {', '.join(active['blockers'][:2])}")

        if risks:
            at_risk.append({**c, "risk_factors": risks, "days_since_contact": int(days_since)})

    return sorted(at_risk, key=lambda x: x.get("days_since_contact", 0), reverse=True)
