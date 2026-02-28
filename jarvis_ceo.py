"""
B.L.I.T.Z. CEO Intelligence Layer — Jarvis for the C-Suite
Covers: Communication Hub, Competitive Intelligence, Stakeholder Briefings,
OKR/Goal Tracking, Board Prep, People/Org, Memory Layer (long-term promises),
Automation Workflows, Wearable Data Ingestion, Contact Intelligence.
"""
import os, json, time, re, pathlib, asyncio
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY", "")
CEO_DATA_DIR    = pathlib.Path(os.getenv("CEO_DATA_DIR", "ceo_data"))
CEO_DATA_DIR.mkdir(exist_ok=True)

_groq = None
def _get_groq():
    global _groq
    if _groq is None:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq

def _rj(path: pathlib.Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}

def _wj(path: pathlib.Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# ██  CONTACT INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────
CONTACTS_FILE = CEO_DATA_DIR / "contacts.json"

def upsert_contact(contact_id: str, name: str, role: str = "", company: str = "",
                   notes: str = "", relationship: str = "", last_touchpoint: str = "") -> dict:
    """Add or update a contact. Tracks relationship history."""
    contacts = _rj(CONTACTS_FILE, {"contacts": {}})
    existing = contacts["contacts"].get(contact_id, {})
    now = datetime.now().strftime("%Y-%m-%d")
    contacts["contacts"][contact_id] = {
        **existing,
        "id": contact_id,
        "name": name,
        "role": role or existing.get("role", ""),
        "company": company or existing.get("company", ""),
        "notes": notes or existing.get("notes", ""),
        "relationship": relationship or existing.get("relationship", ""),
        "last_touchpoint": last_touchpoint or now,
        "updated_at": now,
        "created_at": existing.get("created_at", now),
        "history": existing.get("history", []),
    }
    if last_touchpoint:
        contacts["contacts"][contact_id]["history"].append(
            {"date": now, "note": last_touchpoint}
        )
    _wj(CONTACTS_FILE, contacts)
    return contacts["contacts"][contact_id]

def get_contact(contact_id: str) -> Optional[dict]:
    contacts = _rj(CONTACTS_FILE, {"contacts": {}})
    return contacts["contacts"].get(contact_id)

def list_contacts(query: str = "") -> list[dict]:
    contacts = _rj(CONTACTS_FILE, {"contacts": {}})
    all_c = list(contacts["contacts"].values())
    if query:
        q = query.lower()
        all_c = [c for c in all_c if q in c.get("name","").lower()
                 or q in c.get("company","").lower() or q in c.get("role","").lower()]
    return sorted(all_c, key=lambda x: x.get("last_touchpoint", ""), reverse=True)

async def get_contact_briefing(contact_id: str, meeting_topic: str = "") -> str:
    """Generate a pre-meeting briefing card for a contact."""
    contact = get_contact(contact_id)
    if not contact:
        return f"No contact found for '{contact_id}'."
    
    history_str = "\n".join(f"• {h['date']}: {h['note']}" for h in contact.get("history", [])[-10:])
    prompt = f"""You are B.L.I.T.Z., a CEO's chief of staff AI. Generate a compact pre-meeting briefing card.

CONTACT: {contact.get('name')} — {contact.get('role')} @ {contact.get('company')}
RELATIONSHIP: {contact.get('relationship', 'not specified')}
NOTES: {contact.get('notes', 'none')}
INTERACTION HISTORY:
{history_str or 'No previous interactions logged.'}
MEETING TOPIC: {meeting_topic or 'General'}

Write a 4-bullet briefing (what matters, last conversation thread, potential asks, talking points).
Be sharp and actionable — like a chief of staff whispering in your ear."""
    
    groq = _get_groq()
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.3
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Pre-meeting briefing for {contact.get('name','contact')}: {contact.get('role','')} at {contact.get('company','')}. Relationship: {contact.get('relationship','N/A')}. Last interaction: {contact.get('last_touchpoint','unknown')}."

# ─────────────────────────────────────────────────────────────────────────────
# ██  COMPETITIVE INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────
COMPS_FILE = CEO_DATA_DIR / "competitors.json"

def add_competitor(name: str, domain: str = "", industry: str = "") -> dict:
    data = _rj(COMPS_FILE, {"competitors": {}})
    cid = re.sub(r"[^a-z0-9]", "_", name.lower())
    data["competitors"][cid] = {
        "id": cid, "name": name, "domain": domain,
        "industry": industry, "added": datetime.now().strftime("%Y-%m-%d"),
        "intel": []
    }
    _wj(COMPS_FILE, data)
    return data["competitors"][cid]

def list_competitors() -> list[dict]:
    data = _rj(COMPS_FILE, {"competitors": {}})
    return list(data["competitors"].values())

async def scan_competitor(name: str, domain: str = "") -> dict:
    """Scan competitor news, job postings, product launches via Tavily."""
    if not TAVILY_API_KEY:
        return {"error": "Tavily not configured", "competitor": name}
    
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        
        queries = [
            f"{name} news product launch announcement",
            f"{name} hiring job posting funding",
        ]
        if domain:
            queries.append(f"site:{domain} OR \"{name}\" press release")
        
        all_results = []
        for q in queries[:2]:
            res = tavily.search(q, max_results=3, search_depth="advanced",
                                include_domains=([domain] if domain else None))
            for r in res.get("results", []):
                all_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:300],
                    "date": r.get("published_date", ""),
                })
        
        # LLM synthesis
        groq = _get_groq()
        raw = "\n\n".join(f"• {r['title']}\n  {r['snippet']}" for r in all_results[:6])
        synthesis_prompt = f"""You are a competitive intelligence analyst. Synthesize these signals about {name}:

{raw}

In 3 bullets, extract:
1. KEY MOVE: What are they doing that matters?
2. THREAT LEVEL: How does this affect us? (Low/Medium/High + reason)
3. OPPORTUNITY: What should we do in response?

Be direct and executive-grade."""
        
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=300, temperature=0.2
        )
        synthesis = r.choices[0].message.content.strip()
        
        # Save to competitor record
        data = _rj(COMPS_FILE, {"competitors": {}})
        cid = re.sub(r"[^a-z0-9]", "_", name.lower())
        if cid in data["competitors"]:
            data["competitors"][cid]["intel"].append({
                "scanned_at": datetime.now().isoformat(),
                "synthesis": synthesis,
                "results": all_results[:6]
            })
            # Keep last 20 scans
            data["competitors"][cid]["intel"] = data["competitors"][cid]["intel"][-20:]
            _wj(COMPS_FILE, data)
        
        return {
            "competitor": name,
            "synthesis": synthesis,
            "raw_results": all_results[:6],
            "scanned_at": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "competitor": name}

async def get_competitive_digest() -> dict:
    """Weekly digest of all tracked competitors."""
    competitors = list_competitors()
    if not competitors:
        return {"message": "No competitors tracked. Add some via /api/ceo/competitors."}
    
    results = await asyncio.gather(*[
        scan_competitor(c["name"], c.get("domain", ""))
        for c in competitors[:5]  # limit to 5 to avoid rate limits
    ])
    return {"digest": results, "generated_at": datetime.now().isoformat()}

# ─────────────────────────────────────────────────────────────────────────────
# ██  OKR / GOAL TRACKING
# ─────────────────────────────────────────────────────────────────────────────
OKRS_FILE = CEO_DATA_DIR / "okrs.json"

def create_objective(title: str, quarter: str = "", key_results: list[dict] = None) -> dict:
    """Create an OKR objective with key results."""
    data = _rj(OKRS_FILE, {"objectives": []})
    now = datetime.now()
    obj_id = f"obj_{int(time.time())}"
    obj = {
        "id": obj_id,
        "title": title,
        "quarter": quarter or f"Q{(now.month-1)//3+1} {now.year}",
        "owner": "CEO",
        "progress": 0,
        "status": "on_track",  # on_track / at_risk / behind / done
        "key_results": [
            {
                "id": f"kr_{i}_{int(time.time())}",
                "description": kr.get("description", ""),
                "target": kr.get("target", 100),
                "current": kr.get("current", 0),
                "unit": kr.get("unit", "%"),
                "owner": kr.get("owner", ""),
            }
            for i, kr in enumerate(key_results or [])
        ],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    data["objectives"].append(obj)
    _wj(OKRS_FILE, data)
    return obj

def update_key_result(obj_id: str, kr_id: str, current_value: float, notes: str = "") -> dict:
    data = _rj(OKRS_FILE, {"objectives": []})
    for obj in data["objectives"]:
        if obj["id"] == obj_id:
            for kr in obj["key_results"]:
                if kr["id"] == kr_id:
                    kr["current"] = current_value
                    if notes:
                        kr.setdefault("updates", []).append(
                            {"date": datetime.now().strftime("%Y-%m-%d"), "value": current_value, "notes": notes}
                        )
                    # Recalculate objective progress
                    if obj["key_results"]:
                        total_pct = sum(
                            min(100, (k["current"] / k["target"] * 100)) if k.get("target") else 0
                            for k in obj["key_results"]
                        )
                        obj["progress"] = round(total_pct / len(obj["key_results"]))
                    obj["updated_at"] = datetime.now().isoformat()
                    # Auto-status
                    if obj["progress"] >= 100:
                        obj["status"] = "done"
                    elif obj["progress"] >= 70:
                        obj["status"] = "on_track"
                    elif obj["progress"] >= 40:
                        obj["status"] = "at_risk"
                    else:
                        obj["status"] = "behind"
                    _wj(OKRS_FILE, data)
                    return obj
    return {"error": "OKR or KR not found"}

def get_okr_summary() -> dict:
    data = _rj(OKRS_FILE, {"objectives": []})
    objs = data.get("objectives", [])
    summary = {
        "total": len(objs),
        "on_track": sum(1 for o in objs if o.get("status") == "on_track"),
        "at_risk": sum(1 for o in objs if o.get("status") == "at_risk"),
        "behind": sum(1 for o in objs if o.get("status") == "behind"),
        "done": sum(1 for o in objs if o.get("status") == "done"),
        "avg_progress": round(sum(o.get("progress", 0) for o in objs) / len(objs)) if objs else 0,
        "objectives": objs
    }
    return summary

async def generate_board_briefing() -> str:
    """Auto-generate a board meeting briefing doc from all data sources."""
    from proactive import get_tasks_summary, get_pending_tasks
    
    okrs = get_okr_summary()
    tasks = get_tasks_summary()
    competitors = list_competitors()
    
    # Pull recent competitive intel
    comp_notes = ""
    for c in competitors[:3]:
        intel = c.get("intel", [])
        if intel:
            latest = intel[-1]
            comp_notes += f"\n**{c['name']}**: {latest.get('synthesis', 'No recent intel.')[:200]}\n"
    
    okr_text = "\n".join(
        f"• [{o.get('status','?').upper()}] {o['title']} — {o.get('progress',0)}% complete"
        for o in okrs.get("objectives", [])[:8]
    ) or "No OKRs tracked."
    
    prompt = f"""You are B.L.I.T.Z., generating a board meeting briefing document for the CEO.

## Current Data

### OKRs ({okrs['on_track']} on track, {okrs['at_risk']} at risk, {okrs['behind']} behind)
{okr_text}

### Key Tasks
{tasks[:500]}

### Competitive Landscape
{comp_notes or 'No competitive intel on file.'}

Generate a professional board briefing with:
1. **Executive Summary** (2 sentences — what's the headline?)
2. **Wins & Progress** (what's going well)
3. **Risks & Blockers** (what needs board attention)
4. **Competitive Moves** (what the market is doing)
5. **Asks & Decisions Needed** (what do you need from the board?)
6. **Next 30 Days** (focus areas)

Keep it tight, board-grade, and CEO-authored in tone."""
    
    groq = _get_groq()
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": "You write board-level executive documents. Be precise, data-driven, and brief."},
                      {"role": "user", "content": prompt}],
            max_tokens=1200, temperature=0.2
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"## Board Briefing — {datetime.now().strftime('%B %d, %Y')}\n\n**OKRs:** {okr_text}\n\n**Tasks:**\n{tasks[:300]}\n\n**Competitive:** {comp_notes or 'No data.'}\n\n_Note: AI narrative unavailable — showing raw data._"

# ─────────────────────────────────────────────────────────────────────────────
# ██  PEOPLE & ORG INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────
ORG_FILE  = CEO_DATA_DIR / "org_chart.json"
HIRE_FILE = CEO_DATA_DIR / "hiring.json"

def upsert_team_member(employee_id: str, name: str, role: str, department: str,
                       manager_id: str = "", level: str = "", location: str = "") -> dict:
    data = _rj(ORG_FILE, {"members": {}})
    existing = data["members"].get(employee_id, {})
    data["members"][employee_id] = {
        **existing,
        "id": employee_id, "name": name, "role": role,
        "department": department,
        "manager_id": manager_id or existing.get("manager_id", ""),
        "level": level or existing.get("level", "IC"),
        "location": location or existing.get("location", ""),
        "added": existing.get("added", datetime.now().strftime("%Y-%m-%d")),
        "direct_reports": existing.get("direct_reports", []),
    }
    # Link to manager's direct reports
    if manager_id and manager_id in data["members"]:
        reports = data["members"][manager_id].get("direct_reports", [])
        if employee_id not in reports:
            reports.append(employee_id)
        data["members"][manager_id]["direct_reports"] = reports
    _wj(ORG_FILE, data)
    return data["members"][employee_id]

def get_org_chart() -> dict:
    data = _rj(ORG_FILE, {"members": {}})
    members = list(data["members"].values())
    by_dept = {}
    for m in members:
        d = m.get("department", "Unassigned")
        by_dept.setdefault(d, []).append(m)
    return {"total_headcount": len(members), "departments": by_dept, "members": members}

def add_open_role(title: str, department: str, priority: str = "normal",
                  description: str = "", target_date: str = "") -> dict:
    data = _rj(HIRE_FILE, {"open_roles": []})
    role = {
        "id": f"req_{int(time.time())}",
        "title": title, "department": department,
        "priority": priority,  # urgent / high / normal
        "description": description,
        "target_date": target_date,
        "status": "open",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "candidates": []
    }
    data["open_roles"].append(role)
    _wj(HIRE_FILE, data)
    return role

def get_hiring_pipeline() -> dict:
    data = _rj(HIRE_FILE, {"open_roles": []})
    roles = data.get("open_roles", [])
    return {
        "open": len([r for r in roles if r.get("status") == "open"]),
        "in_progress": len([r for r in roles if r.get("status") == "in_progress"]),
        "total_reqs": len(roles),
        "urgent": [r for r in roles if r.get("priority") == "urgent"],
        "roles": roles
    }

# ─────────────────────────────────────────────────────────────────────────────
# ██  PROMISES & DECISIONS MEMORY LAYER
# ─────────────────────────────────────────────────────────────────────────────
PROMISES_FILE = CEO_DATA_DIR / "promises.json"

def log_promise(promised_by: str, promised_to: str, what: str,
                due_date: str = "", context: str = "") -> dict:
    """Track commitments made to or by the CEO."""
    data = _rj(PROMISES_FILE, {"promises": []})
    promise = {
        "id": f"p_{int(time.time())}",
        "promised_by": promised_by,
        "promised_to": promised_to,
        "what": what,
        "due_date": due_date,
        "context": context,
        "status": "open",  # open / fulfilled / overdue
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # Auto-detect overdue
    if due_date:
        try:
            due = datetime.strptime(due_date, "%Y-%m-%d")
            if due < datetime.now():
                promise["status"] = "overdue"
        except Exception:
            pass
    data["promises"].append(promise)
    _wj(PROMISES_FILE, data)
    return promise

def fulfill_promise(promise_id: str) -> bool:
    data = _rj(PROMISES_FILE, {"promises": []})
    for p in data["promises"]:
        if p["id"] == promise_id or promise_id.lower() in p["what"].lower():
            p["status"] = "fulfilled"
            p["fulfilled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            _wj(PROMISES_FILE, data)
            return True
    return False

def get_open_promises(show_overdue: bool = True) -> list[dict]:
    data = _rj(PROMISES_FILE, {"promises": []})
    promises = data.get("promises", [])
    # Update overdue status
    today = datetime.now()
    for p in promises:
        if p.get("status") == "open" and p.get("due_date"):
            try:
                due = datetime.strptime(p["due_date"], "%Y-%m-%d")
                if due < today:
                    p["status"] = "overdue"
            except Exception:
                pass
    
    result = [p for p in promises if p.get("status") in ("open", "overdue")]
    if not show_overdue:
        result = [p for p in result if p.get("status") == "open"]
    return sorted(result, key=lambda x: x.get("due_date", "9999"), reverse=False)

async def extract_promises_from_meeting(transcript: str) -> list[dict]:
    """Use LLM to auto-extract promises/commitments from a meeting transcript."""
    groq = _get_groq()
    prompt = f"""Extract all commitments and promises from this meeting transcript.
Return ONLY valid JSON array:
[{{"promised_by": "name or role", "promised_to": "name or role", "what": "exact commitment", "due_date": "YYYY-MM-DD or null"}}]

Transcript:
{transcript[:6000]}

Return ONLY the JSON array, no markdown."""
    try:
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw = r.choices[0].message.content.strip()
        # Handle both array and object wrapper
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else parsed.get("promises", parsed.get("commitments", []))
        saved = []
        for item in items:
            if isinstance(item, dict) and item.get("what"):
                saved.append(log_promise(
                    promised_by=item.get("promised_by", "Unknown"),
                    promised_to=item.get("promised_to", "Unknown"),
                    what=item.get("what", ""),
                    due_date=item.get("due_date") or "",
                    context="Auto-extracted from meeting"
                ))
        return saved
    except Exception as e:
        return []

# ─────────────────────────────────────────────────────────────────────────────
# ██  AUTOMATION WORKFLOWS / TRIGGERS
# ─────────────────────────────────────────────────────────────────────────────
WORKFLOWS_FILE = CEO_DATA_DIR / "workflows.json"
TRIGGERS_FILE  = CEO_DATA_DIR / "triggers.json"

def create_workflow(name: str, trigger: str, steps: list[str], enabled: bool = True) -> dict:
    """Define a multi-step automation workflow."""
    data = _rj(WORKFLOWS_FILE, {"workflows": []})
    wf = {
        "id": f"wf_{int(time.time())}",
        "name": name,
        "trigger": trigger,  # e.g. "after_board_meeting", "daily_9am", "revenue_drop"
        "steps": steps,
        "enabled": enabled,
        "run_count": 0,
        "last_run": None,
        "created": datetime.now().isoformat(),
    }
    data["workflows"].append(wf)
    _wj(WORKFLOWS_FILE, data)
    return wf

def list_workflows() -> list[dict]:
    data = _rj(WORKFLOWS_FILE, {"workflows": []})
    return data.get("workflows", [])

def create_trigger(name: str, condition: str, action: str,
                   threshold: float = 0, enabled: bool = True) -> dict:
    """Conditional trigger: if metric crosses threshold → action."""
    data = _rj(TRIGGERS_FILE, {"triggers": []})
    trigger = {
        "id": f"trig_{int(time.time())}",
        "name": name,
        "condition": condition,  # e.g. "revenue_drops", "burn_rate_increases"
        "action": action,
        "threshold": threshold,
        "enabled": enabled,
        "fired_count": 0,
        "last_fired": None,
        "created": datetime.now().isoformat(),
    }
    data["triggers"].append(trigger)
    _wj(TRIGGERS_FILE, data)
    return trigger

def list_triggers() -> list[dict]:
    data = _rj(TRIGGERS_FILE, {"triggers": []})
    return data.get("triggers", [])

async def execute_workflow_chain(trigger_name: str, context: str = "") -> dict:
    """Execute a named workflow with LLM-generated step content."""
    workflows = list_workflows()
    matching = [w for w in workflows if w.get("trigger") == trigger_name and w.get("enabled")]
    if not matching:
        return {"message": f"No enabled workflow for trigger: {trigger_name}", "executed": 0}
    
    groq = _get_groq()
    results = []
    for wf in matching[:3]:
        steps_str = "\n".join(f"{i+1}. {s}" for i, s in enumerate(wf.get("steps", [])))
        prompt = f"""You are B.L.I.T.Z. executing workflow: "{wf['name']}"
Context: {context or 'No specific context provided.'}

Steps to execute:
{steps_str}

Generate the output/content for each step as if you just executed them.
Format: numbered list matching the steps."""
        try:
            r = await groq.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600, temperature=0.3
            )
            wf["run_count"] = wf.get("run_count", 0) + 1
            wf["last_run"] = datetime.now().isoformat()
            results.append({"workflow": wf["name"], "output": r.choices[0].message.content.strip()})
        except Exception as e:
            results.append({"workflow": wf["name"], "error": str(e)})
    
    # Save updated run counts
    data = _rj(WORKFLOWS_FILE, {"workflows": []})
    wf_map = {w["id"]: w for w in matching}
    for w in data["workflows"]:
        if w["id"] in wf_map:
            w.update(wf_map[w["id"]])
    _wj(WORKFLOWS_FILE, data)
    
    return {"executed": len(results), "results": results, "trigger": trigger_name}

# ─────────────────────────────────────────────────────────────────────────────
# ██  WEARABLE / BIOMETRIC DATA INGESTION
# ─────────────────────────────────────────────────────────────────────────────
BIOMETRICS_FILE = CEO_DATA_DIR / "biometrics.json"

def ingest_biometric_data(source: str, data_points: dict, date: str = "") -> dict:
    """Ingest data from Whoop, Oura, Apple Watch, etc."""
    existing = _rj(BIOMETRICS_FILE, {"entries": []})
    entry = {
        "source": source,  # whoop / oura / apple_watch / manual
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "ingested_at": datetime.now().isoformat(),
        "data": data_points  # HRV, recovery, sleep, steps, strain, etc.
    }
    existing["entries"].append(entry)
    # Keep last 90 days
    existing["entries"] = existing["entries"][-90:]
    _wj(BIOMETRICS_FILE, existing)
    return entry

def get_biometric_summary(days: int = 7) -> dict:
    existing = _rj(BIOMETRICS_FILE, {"entries": []})
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [e for e in existing["entries"] if e.get("date", "") >= cutoff]
    
    if not recent:
        return {"message": "No biometric data in range", "days": days}
    
    # Aggregate
    summary = {"days": days, "entries": len(recent), "sources": list(set(e["source"] for e in recent))}
    
    # Average numeric fields across all entries
    all_data = {}
    for e in recent:
        for k, v in e.get("data", {}).items():
            if isinstance(v, (int, float)):
                all_data.setdefault(k, []).append(v)
    
    summary["averages"] = {k: round(sum(vs)/len(vs), 1) for k, vs in all_data.items()}
    summary["latest"] = recent[-1] if recent else {}
    return summary

async def get_performance_insight(days: int = 7) -> str:
    """LLM insight on biometric trends for CEO performance optimization."""
    summary = get_biometric_summary(days)
    if "message" in summary:
        return "No biometric data available to analyze."
    
    groq = _get_groq()
    prompt = f"""You are B.L.I.T.Z., analyzing {days}-day biometric trends for a CEO.

Data averages: {json.dumps(summary.get('averages', {}), indent=2)}
Latest reading: {json.dumps(summary.get('latest', {}).get('data', {}), indent=2)}

Provide:
1. **Performance State**: Are they operating at peak or degraded capacity?
2. **Key Signal**: One metric that stands out (positive or concerning)
3. **Recommendation**: One concrete action they should take today (sleep, nutrition, exercise, recovery)
4. **Schedule Suggestion**: Should they protect focus time, defer heavy meetings, etc.?

Be direct and personal, like a biometrics-aware chief of staff."""
    try:
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.4
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        avgs = summary.get('averages', {})
        return f"7-day averages: {', '.join(f'{k}: {v}' for k,v in avgs.items())}. AI analysis unavailable — review metrics manually."

# ─────────────────────────────────────────────────────────────────────────────
# ██  FINANCIAL KPI INGESTION (manual / CSV-style)
# ─────────────────────────────────────────────────────────────────────────────
FINANCIALS_FILE = CEO_DATA_DIR / "financials.json"

def update_financial_kpis(kpis: dict, period: str = "") -> dict:
    """Log financial KPIs: MRR, ARR, burn_rate, runway, cash, headcount_cost."""
    data = _rj(FINANCIALS_FILE, {"snapshots": []})
    snapshot = {
        "period": period or datetime.now().strftime("%Y-%m"),
        "recorded_at": datetime.now().isoformat(),
        **kpis
    }
    # Upsert by period
    periods = [s.get("period") for s in data["snapshots"]]
    if snapshot["period"] in periods:
        idx = periods.index(snapshot["period"])
        data["snapshots"][idx] = snapshot
    else:
        data["snapshots"].append(snapshot)
    data["snapshots"] = data["snapshots"][-36:]  # 3 years
    _wj(FINANCIALS_FILE, data)
    return snapshot

def get_financial_dashboard() -> dict:
    data = _rj(FINANCIALS_FILE, {"snapshots": []})
    snapshots = sorted(data.get("snapshots", []), key=lambda x: x.get("period", ""))
    if not snapshots:
        return {"message": "No financial data. POST to /api/ceo/financials to update KPIs."}
    
    latest = snapshots[-1]
    prev = snapshots[-2] if len(snapshots) >= 2 else {}
    
    dashboard = {"current": latest, "period": latest.get("period"), "snapshots": len(snapshots)}
    
    # Calculate MoM changes
    if prev:
        changes = {}
        for k in ["mrr", "arr", "burn_rate", "runway_months", "cash", "headcount"]:
            curr_v = latest.get(k)
            prev_v = prev.get(k)
            if curr_v is not None and prev_v and prev_v != 0:
                changes[k] = round((curr_v - prev_v) / abs(prev_v) * 100, 1)
        dashboard["mom_changes"] = changes
    
    # Alert on runway
    runway = latest.get("runway_months", 999)
    if runway < 6:
        dashboard["alert"] = f"⚠️ CRITICAL: Only {runway} months of runway remaining!"
    elif runway < 12:
        dashboard["warning"] = f"⚠️ {runway} months runway — fundraising window approaching."
    
    return dashboard

async def generate_financial_narrative(period: str = "") -> str:
    """LLM narrative on financial health for board/investors."""
    dashboard = get_financial_dashboard()
    if "message" in dashboard:
        return dashboard["message"]
    
    groq = _get_groq()
    prompt = f"""You are B.L.I.T.Z., writing a financial narrative for the CEO to share with their board.

Current KPIs: {json.dumps(dashboard.get('current', {}), indent=2)}
MoM Changes: {json.dumps(dashboard.get('mom_changes', {}), indent=2)}
Alert: {dashboard.get('alert', '') or dashboard.get('warning', '')}

Write a 3-paragraph investor-grade narrative:
1. Business health overview (lead with MRR growth or concern)
2. Burn & runway status (are we capital efficient?)
3. Forward outlook and key metrics to watch

Professional, honest, board-grade tone."""
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.2
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        cur = dashboard.get('current', {})
        return f"**Financial Snapshot ({cur.get('period','N/A')}):** MRR ${cur.get('mrr','N/A')} | ARR ${cur.get('arr','N/A')} | Burn ${cur.get('burn_rate','N/A')} | Runway {cur.get('runway_months','N/A')}mo. AI narrative unavailable."

# ─────────────────────────────────────────────────────────────────────────────
# ██  CEO DAILY DIGEST (combines all sources)
# ─────────────────────────────────────────────────────────────────────────────
async def generate_ceo_digest() -> dict:
    """Full CEO morning digest: combines biometrics, OKRs, promises, financials, competitive."""
    from proactive import get_tasks_summary, get_full_briefing
    
    briefing = get_full_briefing()
    okrs = get_okr_summary()
    promises = get_open_promises()
    pipeline = get_hiring_pipeline()
    financials = get_financial_dashboard()
    biometrics = get_biometric_summary(7)
    overdue = [p for p in promises if p.get("status") == "overdue"]
    
    okr_str = f"{okrs['on_track']} on track · {okrs['at_risk']} at risk · {okrs['behind']} behind · avg {okrs['avg_progress']}%"
    promise_str = f"{len(promises)} open commitments ({len(overdue)} overdue)"
    hire_str = f"{pipeline['open']} open reqs ({pipeline['urgent'].__len__()} urgent)" if pipeline.get("open") else "No open roles"
    
    mrr = financials.get("current", {}).get("mrr", "N/A")
    runway = financials.get("current", {}).get("runway_months", "N/A")
    fin_alert = financials.get("alert") or financials.get("warning") or ""
    
    groq = _get_groq()
    prompt = f"""You are B.L.I.T.Z., generating the CEO's morning command-center digest.

TODAY: {datetime.now().strftime('%A, %B %d, %Y at %H:%M')}

BRIEFING SUMMARY: {briefing.get('summary', '')}
WEATHER: {briefing.get('weather', '')}
CALENDAR TODAY: {briefing.get('calendar', '')}

OKRs: {okr_str}
COMMITMENTS: {promise_str}
HIRING: {hire_str}
FINANCIALS: MRR ${mrr} | Runway {runway} months {fin_alert}

Generate a 5-bullet executive digest:
• 🎯 TOP PRIORITY (most critical thing for today)
• ⚡ CRITICAL ALERT (any fire / risk / overdue item)
• 📊 METRICS PULSE (one key number that matters)
• 🧩 FOCUS BLOCK (what to protect time for)
• ✅ QUICK WINS (2-3 things to clear fast)

Jarvis-grade: direct, personal, no fluff."""
    
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.3
        )
        digest_text = r.choices[0].message.content.strip()
    except Exception as e:
        # Build a useful digest from local data even without LLM
        lines = []
        if overdue:
            lines.append(f"• ⚡ CRITICAL: {len(overdue)} overdue commitment(s) need attention")
        if financials.get("alert"):
            lines.append(f"• 🔴 FINANCE: {financials['alert']}")
        if pipeline.get("urgent"):
            lines.append(f"• 🏢 HIRING: {len(pipeline['urgent'])} urgent role(s) open")
        lines.append(f"• 📊 OKRs: {okr_str}")
        lines.append(f"• 🤝 {promise_str}")
        if not lines:
            lines.append(f"• 🎯 {datetime.now().strftime('%A, %B %d')} — All systems nominal. No critical items.")
        digest_text = "\n".join(lines)
    
    return {
        "digest": digest_text,
        "generated_at": datetime.now().isoformat(),
        "components": {
            "briefing":   briefing,
            "okrs":       okrs,
            "promises":   {"open": len(promises), "overdue": len(overdue), "items": promises[:5]},
            "hiring":     pipeline,
            "financials": get_financial_dashboard(),
            "biometrics": biometrics,
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# ██  MARKET DATA INGESTION (manual snapshot)
# ─────────────────────────────────────────────────────────────────────────────
MARKET_FILE = CEO_DATA_DIR / "market_data.json"

def log_market_data(tickers: dict, funding_rounds: list[dict] = None,
                    notes: str = "") -> dict:
    """Log stock prices, funding rounds, market notes."""
    data = _rj(MARKET_FILE, {"snapshots": []})
    snapshot = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "recorded_at": datetime.now().isoformat(),
        "tickers": tickers,           # e.g. {"AAPL": 185.2, "MSFT": 412.3}
        "funding_rounds": funding_rounds or [],
        "notes": notes,
    }
    data["snapshots"].append(snapshot)
    data["snapshots"] = data["snapshots"][-90:]
    _wj(MARKET_FILE, data)
    return snapshot

def get_latest_market_data() -> dict:
    data = _rj(MARKET_FILE, {"snapshots": []})
    snapshots = data.get("snapshots", [])
    return snapshots[-1] if snapshots else {"message": "No market data logged yet."}

async def get_market_intelligence(topic: str = "AI startup market") -> dict:
    """Fetch live market intelligence via Tavily."""
    if not TAVILY_API_KEY:
        return {"error": "Tavily not configured"}
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        results = tavily.search(topic, max_results=5, search_depth="advanced")
        snippets = "\n\n".join(
            f"**{r['title']}** ({r.get('published_date','')[:10]})\n{r.get('content','')[:300]}"
            for r in results.get("results", [])[:4]
        )
        
        groq = _get_groq()
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": f"Synthesize these market signals about '{topic}' in 3 CEO-level bullets:\n\n{snippets}"}],
            max_tokens=250, temperature=0.2
        )
        return {
            "topic": topic,
            "synthesis": r.choices[0].message.content.strip(),
            "sources": [{"title": r["title"], "url": r["url"]} for r in results.get("results", [])[:4]],
            "fetched_at": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# ██  PERSONAL DEVELOPMENT / HABITS TRACKER
# ─────────────────────────────────────────────────────────────────────────────
HABITS_FILE = CEO_DATA_DIR / "habits.json"

def get_habits() -> dict:
    return _rj(HABITS_FILE, {"habits": {}, "logs": []})

def upsert_habit(habit_id: str, name: str, icon: str = "🎯", target_per_month: int = 25) -> dict:
    data = get_habits()
    data["habits"][habit_id] = {
        "id": habit_id, "name": name, "icon": icon,
        "target_per_month": target_per_month,
        "created": datetime.now().strftime("%Y-%m-%d")
    }
    _wj(HABITS_FILE, data)
    return data["habits"][habit_id]

def log_habit(habit_id: str, done: bool = True, date: str = "", notes: str = "") -> dict:
    data = get_habits()
    entry = {
        "habit_id": habit_id, "done": done,
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "notes": notes
    }
    data["logs"].append(entry)
    data["logs"] = data["logs"][-3000:]  # keep ~3mo of daily data
    _wj(HABITS_FILE, data)
    return entry

def get_habit_stats(months: int = 6) -> dict:
    data = get_habits()
    habits = data.get("habits", {})
    logs = data.get("logs", [])
    cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m")
    
    # Group logs by month & habit
    monthly = {}
    for log in logs:
        d = log.get("date", "")
        if not d: continue
        month_key = d[:7]
        if month_key < cutoff: continue
        hid = log.get("habit_id", "")
        if not hid: continue
        monthly.setdefault(month_key, {}).setdefault(hid, {"done": 0, "total": 0})
        monthly[month_key][hid]["total"] += 1
        if log.get("done"):
            monthly[month_key][hid]["done"] += 1
    
    # Build chart data
    sorted_months = sorted(monthly.keys())
    chart = {"months": sorted_months, "habits": {}}
    for hid, habit in habits.items():
        target = habit.get("target_per_month", 25)
        chart["habits"][hid] = {
            "name": habit.get("name", hid),
            "icon": habit.get("icon", "🎯"),
            "target": target,
            "data": [],
        }
        for m in sorted_months:
            mdata = monthly.get(m, {}).get(hid, {"done": 0, "total": 0})
            accuracy = round(mdata["done"] / target * 100) if target else 0
            chart["habits"][hid]["data"].append({
                "month": m, "done": mdata["done"],
                "target": target, "accuracy": min(100, accuracy)
            })
    
    return chart

# ─────────────────────────────────────────────────────────────────────────────
# ██  SEED AGENCY DATA — Pre-load realistic data for a tech AI agency
# ─────────────────────────────────────────────────────────────────────────────

def seed_agency_data() -> dict:
    """Load comprehensive dummy data for a tech/AI agency. Safe to call multiple times."""
    seeded = []
    
    # --- Financial History (6 months) ---
    fin_data = _rj(FINANCIALS_FILE, {"snapshots": []})
    if len(fin_data.get("snapshots", [])) < 3:
        months = [
            {"period":"2025-09","mrr":42000,"arr":504000,"burn_rate":95000,"runway_months":18,"cash":1710000,"headcount":12,"headcount_cost":78000,"gross_margin":68},
            {"period":"2025-10","mrr":51000,"arr":612000,"burn_rate":100000,"runway_months":17,"cash":1610000,"headcount":14,"headcount_cost":82000,"gross_margin":69},
            {"period":"2025-11","mrr":62000,"arr":744000,"burn_rate":108000,"runway_months":16,"cash":1502000,"headcount":15,"headcount_cost":85000,"gross_margin":70},
            {"period":"2025-12","mrr":71000,"arr":852000,"burn_rate":115000,"runway_months":15,"cash":1387000,"headcount":16,"headcount_cost":89000,"gross_margin":71},
            {"period":"2026-01","mrr":79000,"arr":948000,"burn_rate":118000,"runway_months":14.5,"cash":1269000,"headcount":17,"headcount_cost":92000,"gross_margin":72},
            {"period":"2026-02","mrr":88000,"arr":1056000,"burn_rate":122000,"runway_months":14,"cash":1147000,"headcount":18,"headcount_cost":96000,"gross_margin":73},
        ]
        for m in months:
            update_financial_kpis(m, m["period"])
        seeded.append("financials_6mo")
    
    # --- Team Members ---
    org_data = _rj(ORG_FILE, {"members": {}})
    if len(org_data.get("members", {})) < 3:
        team = [
            ("ceo","Abhi K.","CEO & Founder","Executive",""),
            ("cto","Raj P.","CTO","Engineering","ceo"),
            ("coo","Maya S.","COO","Operations","ceo"),
            ("lead_eng","Jordan L.","Lead Engineer","Engineering","cto"),
            ("ml_eng","Priya M.","ML Engineer","Engineering","cto"),
            ("fullstack1","Alex T.","Full-Stack Dev","Engineering","lead_eng"),
            ("fullstack2","Sam W.","Full-Stack Dev","Engineering","lead_eng"),
            ("designer","Nikki R.","UI/UX Designer","Design","coo"),
            ("pm","Chris D.","Product Manager","Product","coo"),
            ("mktg","Taylor B.","Growth Lead","Marketing","coo"),
            ("sales1","Devon K.","Account Executive","Sales","coo"),
            ("sales2","Riley F.","SDR","Sales","coo"),
        ]
        for eid, name, role, dept, mgr in team:
            upsert_team_member(eid, name, role, dept, mgr)
        seeded.append("team_12")
    
    # --- Contacts ---
    ctc_data = _rj(CONTACTS_FILE, {"contacts": {}})
    if len(ctc_data.get("contacts", {})) < 3:
        contacts = [
            ("vc_mark","Mark Yuen","Partner","Embark Ventures","Lead investor, Series A","investor"),
            ("client_sarah","Sarah Lin","VP Engineering","NexGen Health","Enterprise client, $8k/mo retainer","client"),
            ("client_james","James Park","CEO","Motiv AI","AI consulting deal, $15k project","client"),
            ("advisor_lisa","Lisa Ng","Founder","Suki AI","Advisor, weekly 1:1","advisor"),
            ("partner_raj","Raj Mehta","CTO","DataFlow Inc","Integration partner","partner"),
        ]
        for cid, name, role, company, notes, rel in contacts:
            upsert_contact(cid, name, role, company, notes, rel)
        seeded.append("contacts_5")
    
    # --- OKRs ---
    okr_data = _rj(OKRS_FILE, {"objectives": []})
    if len(okr_data.get("objectives", [])) < 2:
        create_objective("Hit $120K MRR by Q1 end", "Q1 2026", [
            {"description": "Close 3 enterprise deals >$5k/mo", "target": 3, "current": 1, "unit": "deals"},
            {"description": "Reduce churn below 3%", "target": 3, "current": 4.1, "unit": "%"},
            {"description": "Launch AI Agent marketplace", "target": 100, "current": 72, "unit": "%"},
        ])
        create_objective("Scale team to 22 people", "Q1 2026", [
            {"description": "Hire 2 senior engineers", "target": 2, "current": 0, "unit": "hires"},
            {"description": "Hire Head of Customer Success", "target": 1, "current": 0, "unit": "hire"},
            {"description": "Complete new employee onboarding v2", "target": 100, "current": 40, "unit": "%"},
        ])
        create_objective("Build Brand & Thought Leadership", "Q1 2026", [
            {"description": "Publish 8 blog posts / case studies", "target": 8, "current": 3, "unit": "posts"},
            {"description": "Speak at 2 conferences", "target": 2, "current": 1, "unit": "talks"},
            {"description": "Grow LinkedIn to 5K", "target": 5000, "current": 3200, "unit": "followers"},
        ])
        seeded.append("okrs_3")
    
    # --- Promises ---
    prom_data = _rj(PROMISES_FILE, {"promises": []})
    if len(prom_data.get("promises", [])) < 2:
        log_promise("CEO", "Board", "Present Q1 growth plan with updated projections", "2026-03-10", "Board meeting")
        log_promise("CEO", "Sarah Lin (NexGen)", "Deliver custom AI dashboard by March 15", "2026-03-15", "Client call")
        log_promise("CTO", "CEO", "Complete SOC2 prep checklist", "2026-03-01", "Team standup")
        log_promise("CEO", "Lisa Ng", "Intro to 2 potential enterprise clients", "2026-03-07", "Advisory call")
        log_promise("PM", "CEO", "Ship agent marketplace beta", "2026-02-28", "Sprint planning")
        seeded.append("promises_5")
    
    # --- Hiring ---
    hire_data = _rj(HIRE_FILE, {"open_roles": []})
    if len(hire_data.get("open_roles", [])) < 2:
        add_open_role("Senior Backend Engineer", "Engineering", "urgent", "Python/FastAPI, 5+ yrs")
        add_open_role("Head of Customer Success", "Customer Success", "high", "B2B SaaS experience")
        add_open_role("ML/AI Engineer", "Engineering", "urgent", "LLM fine-tuning, RAG pipelines")
        add_open_role("Content Marketing Manager", "Marketing", "normal", "Tech/AI content")
        seeded.append("hiring_4")
    
    # --- Competitors ---
    comp_data = _rj(COMPS_FILE, {"competitors": {}})
    if len(comp_data.get("competitors", {})) < 2:
        add_competitor("Cursor AI", "cursor.sh", "AI Development Tools")
        add_competitor("Jasper AI", "jasper.ai", "AI Content & Marketing")
        add_competitor("Copy.ai", "copy.ai", "AI Business Automation")
        seeded.append("competitors_3")
    
    # --- Habits ---
    habits_data = get_habits()
    if len(habits_data.get("habits", {})) < 3:
        habits = [
            ("deep_work", "Deep Work (2+ hrs)", "🧠", 22),
            ("exercise", "Exercise / Movement", "🏋️", 20),
            ("reading", "Read 30 min", "📚", 25),
            ("meditation", "Meditation", "🧘", 22),
            ("networking", "1 Connection / Outreach", "🤝", 18),
        ]
        for hid, name, icon, target in habits:
            upsert_habit(hid, name, icon, target)
        
        # Generate 6 months of habit logs with realistic variance
        import random
        random.seed(42)
        base_date = datetime(2025, 9, 1)
        rates = {"deep_work": 0.72, "exercise": 0.65, "reading": 0.58, "meditation": 0.48, "networking": 0.52}
        growth = {"deep_work": 0.04, "exercise": 0.05, "reading": 0.06, "meditation": 0.07, "networking": 0.04}
        
        for month_offset in range(6):
            month_start = datetime(2025, 9 + month_offset, 1) if 9 + month_offset <= 12 else datetime(2026, (9 + month_offset) - 12, 1)
            days_in_month = 28 if month_start.month == 2 else 30
            for day in range(1, days_in_month + 1):
                d = month_start.replace(day=min(day, days_in_month))
                date_str = d.strftime("%Y-%m-%d")
                for hid in rates:
                    rate = min(0.95, rates[hid] + growth[hid] * month_offset)
                    done = random.random() < rate
                    log_habit(hid, done, date_str)
        seeded.append("habits_6mo")
    
    # --- Biometrics (30 days) ---
    bio_data = _rj(BIOMETRICS_FILE, {"entries": []})
    if len(bio_data.get("entries", [])) < 10:
        import random
        random.seed(99)
        for i in range(30):
            d = (datetime.now() - timedelta(days=29 - i)).strftime("%Y-%m-%d")
            ingest_biometric_data("whoop", {
                "hrv": round(40 + random.gauss(10, 5), 1),
                "recovery": round(max(30, min(99, 65 + random.gauss(10, 8)))),
                "sleep_score": round(max(50, min(98, 75 + random.gauss(5, 6)))),
                "strain": round(max(2, min(20, 11 + random.gauss(2, 2))), 1),
                "resting_hr": round(max(48, min(68, 56 + random.gauss(0, 3)))),
            }, d)
        seeded.append("biometrics_30d")
    
    # --- Workflows ---
    wf_data = _rj(WORKFLOWS_FILE, {"workflows": []})
    if not wf_data.get("workflows"):
        create_workflow("Post-Board Meeting", "after_board_meeting", [
            "Send meeting summary to all board members",
            "Update investor relations doc",
            "Create action items from decisions",
            "Schedule follow-up meetings"
        ])
        create_workflow("New Client Onboarding", "client_signed", [
            "Create project channel in Slack",
            "Set up shared drive folder",
            "Schedule kickoff call",
            "Assign PM and tech lead",
            "Send welcome packet"
        ])
        seeded.append("workflows_2")
    
    return {"seeded": seeded, "message": f"Loaded {len(seeded)} data categories"}
