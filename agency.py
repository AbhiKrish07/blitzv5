"""
B.L.I.T.Z. Agency Ops
Hour logging, invoice generation, utilization tracking, P&L summary.
Voice: "Log 3 hours Acme, backend refactor" → stored and categorized.
"""
import os, json, time, re, pathlib
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

AGENCY_DIR  = pathlib.Path(os.getenv("AGENCY_DIR", "agency"))
HOURS_FILE  = AGENCY_DIR / "hours.json"
RATES_FILE  = AGENCY_DIR / "rates.json"
AGENCY_DIR.mkdir(exist_ok=True)

SERVICE_TYPES = ["development", "strategy", "design", "devops", "consulting",
                 "meeting", "review", "support", "docs", "internal"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _load_hours() -> list:
    try:
        return json.loads(HOURS_FILE.read_text(encoding="utf-8")) if HOURS_FILE.exists() else []
    except Exception:
        return []


def _save_hours(data: list):
    HOURS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_rates() -> dict:
    try:
        return json.loads(RATES_FILE.read_text(encoding="utf-8")) if RATES_FILE.exists() else {}
    except Exception:
        return {}


def set_rate(client_id: str, rate: float):
    """Set hourly rate for a client."""
    rates = _load_rates()
    rates[client_id] = rate
    RATES_FILE.write_text(json.dumps(rates, indent=2), encoding="utf-8")


# ── Hour Logging ──────────────────────────────────────────────────────────────
def log_hours(
    client_id: str,
    hours: float,
    description: str,
    service_type: str = "development",
    date: str = None
) -> dict:
    """
    Log billable hours. Rate looked up from rates.json → agency default → $150/hr.
    Voice: "Log 3 hours Acme, backend refactor" → parse_voice_log() then call this.
    """
    rates = _load_rates()
    rate = rates.get(client_id.lower(), rates.get("default", 150.0))

    if service_type not in SERVICE_TYPES:
        service_type = "development"

    entry = {
        "id": f"{int(time.time())}_{client_id}",
        "client_id": client_id.lower(),
        "hours": round(float(hours), 2),
        "description": description.strip(),
        "service_type": service_type,
        "rate": rate,
        "amount": round(float(hours) * rate, 2),
        "date": date or time.strftime("%Y-%m-%d"),
        "timestamp": time.time(),
        "invoiced": False,
        "invoice_id": None,
    }
    data = _load_hours()
    data.append(entry)
    _save_hours(data)

    # Update client last_contact
    try:
        from clients import update_client
        update_client(client_id, {"last_contact": time.time()})
    except Exception:
        pass

    return entry


def parse_voice_log(text: str) -> Optional[dict]:
    """
    Parse natural language hour log.
    Patterns:
      "Log 3 hours Acme, backend refactor"
      "Log 1.5 hrs Yofi on strategy"
      "Logged 2 hours client-name: description"
    Returns kwargs dict for log_hours() or None if not parseable.
    """
    # "log X hours/hrs CLIENT[,: ] description [on service_type]"
    m = re.search(
        r"(?:log(?:ged?)?)\s+([\d.]+)\s+h(?:ou?r?s?)?\s+([\w\-]+)[\s,:\-]+(.+?)(?:\s+on\s+(\w+))?\.?$",
        text, re.I
    )
    if not m:
        return None
    hours, client, desc, svc = m.group(1), m.group(2), m.group(3), m.group(4)
    return {
        "client_id": client.lower(),
        "hours": float(hours),
        "description": desc.strip(),
        "service_type": (svc or "development").lower()
    }


# ── Utilization & Summary ─────────────────────────────────────────────────────
def get_utilization(days: int = 30, client_id: str = None) -> dict:
    """Utilization breakdown: total hours, revenue, by-client, by-service."""
    cutoff = time.time() - days * 86400
    entries = [e for e in _load_hours() if e["timestamp"] >= cutoff]
    if client_id:
        entries = [e for e in entries if e["client_id"] == client_id.lower()]

    total_hours   = round(sum(e["hours"] for e in entries), 2)
    total_revenue = round(sum(e["amount"] for e in entries), 2)

    by_client: dict = {}
    by_service: dict = {}
    for e in entries:
        cid = e["client_id"]
        svc = e["service_type"]
        if cid not in by_client:
            by_client[cid] = {"hours": 0.0, "revenue": 0.0, "entries": 0}
        by_client[cid]["hours"]   = round(by_client[cid]["hours"] + e["hours"], 2)
        by_client[cid]["revenue"] = round(by_client[cid]["revenue"] + e["amount"], 2)
        by_client[cid]["entries"] += 1

        if svc not in by_service:
            by_service[svc] = {"hours": 0.0}
        by_service[svc]["hours"] = round(by_service[svc]["hours"] + e["hours"], 2)

    avg_rate = round(total_revenue / total_hours, 2) if total_hours else 0.0

    return {
        "period_days": days,
        "total_hours": total_hours,
        "total_revenue": total_revenue,
        "avg_rate": avg_rate,
        "entry_count": len(entries),
        "by_client": dict(sorted(by_client.items(), key=lambda x: x[1]["revenue"], reverse=True)),
        "by_service": dict(sorted(by_service.items(), key=lambda x: x[1]["hours"], reverse=True)),
    }


# ── Invoice Generator ─────────────────────────────────────────────────────────
def generate_invoice(client_id: str) -> dict:
    """
    Generate invoice for all un-invoiced hours for a client.
    Marks entries as invoiced. Returns invoice dict ready to print/send.
    """
    data   = _load_hours()
    cid    = client_id.lower()
    unbilled = [e for e in data if e["client_id"] == cid and not e["invoiced"]]

    if not unbilled:
        return {"error": f"No un-invoiced hours for '{client_id}'"}

    invoice_id = f"INV-{int(time.time())}"
    subtotal   = round(sum(e["amount"] for e in unbilled), 2)

    invoice = {
        "invoice_id": invoice_id,
        "client_id": cid,
        "issued":    time.strftime("%Y-%m-%d"),
        "due":       "",          # caller should add NET30
        "line_items": [
            {
                "date":        e["date"],
                "description": e["description"],
                "service":     e["service_type"],
                "hours":       e["hours"],
                "rate":        e["rate"],
                "amount":      e["amount"],
            }
            for e in sorted(unbilled, key=lambda x: x["date"])
        ],
        "subtotal":  subtotal,
        "tax":       0.0,
        "total":     subtotal,
        "status":    "draft",
    }

    # Mark entries as invoiced
    billed_ids = {e["id"] for e in unbilled}
    for e in data:
        if e["id"] in billed_ids:
            e["invoiced"]   = True
            e["invoice_id"] = invoice_id
    _save_hours(data)

    # Persist invoice to agency dir
    inv_path = AGENCY_DIR / f"{invoice_id}.json"
    inv_path.write_text(json.dumps(invoice, indent=2), encoding="utf-8")

    return invoice


# ── P&L Summary ───────────────────────────────────────────────────────────────
def get_pl_summary(months: int = 1) -> dict:
    """Monthly P&L: revenue per client, most profitable service lines."""
    cutoff  = time.time() - months * 30 * 86400
    entries = [e for e in _load_hours() if e["timestamp"] >= cutoff]

    by_client: dict = {}
    for e in entries:
        cid = e["client_id"]
        if cid not in by_client:
            by_client[cid] = {"revenue": 0.0, "hours": 0.0, "cost_hrs": 0.0}
        by_client[cid]["revenue"] = round(by_client[cid]["revenue"] + e["amount"], 2)
        by_client[cid]["hours"]   = round(by_client[cid]["hours"] + e["hours"], 2)

    sorted_clients = sorted(by_client.items(), key=lambda x: x[1]["revenue"], reverse=True)
    total_rev   = round(sum(e["amount"] for e in entries), 2)
    total_hours = round(sum(e["hours"]  for e in entries), 2)

    return {
        "period_months": months,
        "total_revenue": total_rev,
        "total_hours":   total_hours,
        "avg_rate":      round(total_rev / total_hours, 2) if total_hours else 0,
        "top_client":    sorted_clients[0][0] if sorted_clients else "N/A",
        "by_client":     {k: v for k, v in sorted_clients},
        "month_label":   time.strftime("%B %Y"),
    }
