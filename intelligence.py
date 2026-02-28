"""
B.L.I.T.Z. Intelligence Layer
Meeting Intelligence, PRD Generator, Prompt Engineering Lab, Scope Creep Detector,
Technical → Business Translator, Proposal Generator, Case Study Generator.
All powered by Groq (llama-3.3-70b-versatile for quality, llama-3.1-8b-instant for speed).
"""
import os, json, time, re, pathlib
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_groq = None


def _get_groq():
    global _groq
    if _groq is None:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq


# ── Meeting Intelligence ───────────────────────────────────────────────────────
MEETING_PROMPT = """You are B.L.I.T.Z., a senior technical agency AI. Analyze this meeting transcript precisely.

CLIENT: {client_name}
DATE: {date}

TRANSCRIPT:
{transcript}

Extract and return ONLY valid JSON matching this schema exactly:
{{
  "action_items": [{{"owner": "string", "task": "string", "deadline": "string or null"}}],
  "client_asks": [{{"request": "string", "in_scope": true/false, "impact": "string"}}],
  "decisions": ["string"],
  "red_flags": [{{"flag": "string", "severity": "low|medium|high", "context": "string"}}],
  "blockers": ["string"],
  "sentiment": "positive|neutral|cautious|negative",
  "key_quotes": ["string"],
  "follow_up_email": "full email text as a single string with \\n for newlines",
  "summary": "2-3 sentence executive summary"
}}

Be precise. Flag scope creep in client_asks.in_scope. Capture verbatim client quotes in key_quotes."""


async def analyze_meeting(
    transcript: str,
    client_id: str = "",
    client_name: str = "Client"
) -> dict:
    """
    Paste any meeting transcript → extracts action items, decisions, red flags,
    scope creep signals, and generates follow-up email.
    Auto-saves to client namespace if client_id provided.
    """
    groq = _get_groq()
    prompt = MEETING_PROMPT.format(
        client_name=client_name,
        date=time.strftime("%Y-%m-%d"),
        transcript=transcript[:10000]
    )

    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are B.L.I.T.Z. meeting intelligence. Return only valid JSON, no markdown."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(r.choices[0].message.content)
    except json.JSONDecodeError as e:
        # Re-attempt without json_object mode
        try:
            raw = r.choices[0].message.content
            match = re.search(r"\{[\s\S]+\}", raw)
            result = json.loads(match.group()) if match else {"error": "JSON parse failed", "raw": raw[:500]}
        except Exception:
            result = {"error": str(e)}
    except Exception as e:
        result = {"error": str(e)}

    result["analyzed_at"] = time.strftime("%Y-%m-%d %H:%M")
    result["client_id"]   = client_id

    # Store in client namespace
    if client_id:
        try:
            from clients import _client_dir, add_client_memory, _read_json, _write_json
            d = _client_dir(client_id)
            mf = d / "meetings.json"
            data = _read_json(mf, {"meetings": []})
            data["meetings"].append({
                "timestamp": time.time(),
                "date": time.strftime("%Y-%m-%d"),
                "analysis": result,
                "transcript_chars": len(transcript)
            })
            _write_json(mf, data)

            # Auto-store high-severity red flags in client memory
            for flag in result.get("red_flags", []):
                if flag.get("severity") in ("medium", "high"):
                    add_client_memory(
                        client_id,
                        f"RED FLAG ({flag['severity']}): {flag.get('flag','')} — {flag.get('context','')}",
                        tag="red_flag"
                    )

            # Auto-store decisions
            for decision in result.get("decisions", []):
                add_client_memory(client_id, f"DECISION: {decision}", tag="decision")
        except Exception as ex:
            print(f"[MEETINGS] Failed to save to client namespace: {ex}")

    return result


# ── PRD Generator ─────────────────────────────────────────────────────────────
PRD_PROMPT = """You are B.L.I.T.Z., acting as a senior technical product manager and solutions architect.
Generate a complete, production-grade PRD for the feature described below.

CLIENT CONTEXT: {client_context}
TECH STACK: {stack}
FEATURE REQUEST: {description}

Write a comprehensive PRD with these sections:

## 1. Problem Statement & Success Criteria
## 2. User Stories (3-5, with acceptance criteria)
## 3. Functional Requirements (numbered, precise)
## 4. Non-Functional Requirements (latency, uptime, security)
## 5. API Design
   - Endpoints with method, path, request body, response schema
   - Include actual field names and types
## 6. Database Schema
   - Table names, column names, data types, indexes, foreign keys
## 7. Implementation Plan
   - Phase breakdown with effort estimates (S/M/L)
   - Key technical decisions with rationale
## 8. Edge Cases & Error Handling
## 9. Testing Strategy
## 10. Explicitly Out of Scope

Use code blocks for schemas. Be specific — a developer should be able to start building from this doc alone."""


async def generate_prd(
    description: str,
    stack: str = "",
    client_id: str = ""
) -> str:
    """Generate a complete PRD from a voice or text description."""
    groq = _get_groq()

    client_context = ""
    if client_id:
        try:
            from clients import get_client_context
            client_context = get_client_context(client_id, description)
        except Exception:
            pass

    if not stack and client_id:
        try:
            from clients import get_client
            profile = get_client(client_id)
            if profile:
                stack = ", ".join(profile.get("stack", []))
        except Exception:
            pass

    prompt = PRD_PROMPT.format(
        client_context=client_context or "Not specified",
        stack=stack or "Not specified",
        description=description
    )

    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are writing a PRD a senior engineer will use to build a production feature. Be specific. Include real field names, types, and API paths."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            temperature=0.25
        )
        return r.choices[0].message.content
    except Exception as e:
        return f"**PRD generation failed:** {e}"


# ── Scope Creep Detector ───────────────────────────────────────────────────────
SCOPE_PROMPT = """You are B.L.I.T.Z., a technical project manager protecting the agency from scope creep.

ORIGINAL SCOPE (from project notes/PRD):
{original_scope}

NEW CLIENT REQUEST:
{new_request}

Analyze this. Return JSON:
{{
  "is_scope_creep": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "one sentence",
  "impact_estimate": "S|M|L|XL",
  "suggested_response": "exact language to use with client to push back or accept",
  "change_order_needed": true/false
}}"""


async def detect_scope_creep(new_request: str, original_scope: str, client_id: str = "") -> dict:
    """
    Real-time scope creep detection. Flags when a request falls outside original spec.
    Returns impact estimate and exact pushback language.
    """
    groq = _get_groq()

    # Pull client notes as additional scope context
    if client_id and not original_scope:
        try:
            from clients import get_client_context
            original_scope = get_client_context(client_id)
        except Exception:
            pass

    try:
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Scope creep detector for a technical agency. Return only valid JSON."},
                {"role": "user", "content": SCOPE_PROMPT.format(
                    original_scope=original_scope[:3000] or "Not provided",
                    new_request=new_request
                )}
            ],
            max_tokens=600,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(r.choices[0].message.content)
    except Exception as e:
        result = {"error": str(e), "is_scope_creep": None}

    # Log if scope creep detected
    if client_id and result.get("is_scope_creep"):
        try:
            from clients import add_client_memory
            add_client_memory(
                client_id,
                f"SCOPE CREEP [{result.get('impact_estimate','?')}]: {new_request[:100]}",
                tag="scope_creep"
            )
        except Exception:
            pass

    return result


# ── Technical → Business Translator ───────────────────────────────────────────
async def tech_to_business(technical_description: str, audience: str = "non-technical client") -> str:
    """
    Convert what you built into language a non-technical client understands.
    'We refactored the auth module to use JWT with refresh tokens' →
    'We improved your app's login security so users stay logged in longer without compromising safety'
    """
    groq = _get_groq()
    try:
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"Translate technical work into clear, value-focused language for a {audience}. Focus on business impact, not implementation details. 2-3 sentences max."},
                {"role": "user", "content": f"Translate this:\n{technical_description}"}
            ],
            max_tokens=200,
            temperature=0.4
        )
        return r.choices[0].message.content
    except Exception as e:
        return f"Translation failed: {e}"


# ── Proposal Generator ────────────────────────────────────────────────────────
PROPOSAL_PROMPT = """You are B.L.I.T.Z., writing a hyper-specific technical proposal for a prospect.

PROSPECT ANALYSIS:
{prospect_analysis}

PAST PROJECT CONTEXT (from memory):
{past_context}

REQUESTED SCOPE:
{scope}

Generate a professional, winning proposal with:
1. Executive Summary (what you'll build and why it matters to THEM specifically)
2. Technical Approach (show depth of understanding)
3. Deliverables (specific, measurable)
4. Timeline (realistic phases)
5. Investment (placeholder — $X,XXX-X,XXX range based on scope)
6. Why [Agency Name] (specific to their tech stack and pain points)
7. Next Steps

Tone: confident, specific, peer-to-peer (not salesy). Reference their specific tech stack."""


async def generate_proposal(scope: str, prospect_analysis: str = "", past_context: str = "") -> str:
    """Generate a tailored proposal from prospect analysis + your past project memory."""
    groq = _get_groq()
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are writing a winning technical proposal. Be specific, confident, and reference their exact situation."},
                {"role": "user", "content": PROPOSAL_PROMPT.format(
                    prospect_analysis=prospect_analysis or "Not provided",
                    past_context=past_context or "No similar past projects on file",
                    scope=scope
                )}
            ],
            max_tokens=3000,
            temperature=0.3
        )
        return r.choices[0].message.content
    except Exception as e:
        return f"Proposal generation failed: {e}"


# ── Prospect Analyzer ─────────────────────────────────────────────────────────
async def analyze_prospect(website_or_text: str) -> dict:
    """
    Paste a website, LinkedIn, or job posting text.
    BLITZ infers tech stack, pain points, and maps to your services.
    """
    groq = _get_groq()
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are B.L.I.T.Z. analyzing a prospect for a technical agency. Return only valid JSON."},
                {"role": "user", "content": f"""Analyze this prospect and return JSON:
{{
  "company_type": "string",
  "inferred_stack": ["string"],
  "pain_points": ["string"],
  "growth_signals": ["string"],
  "budget_signal": "startup|smb|enterprise|unknown",
  "best_services_to_pitch": ["string"],
  "conversation_opener": "exact first message to send them",
  "red_flags": ["string"]
}}

Content to analyze:
{website_or_text[:5000]}"""}
            ],
            max_tokens=1000,
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}


# ── GitHub → Client Update ────────────────────────────────────────────────────
async def commits_to_update(commits: list[dict], client_name: str = "Client") -> dict:
    """
    GitHub webhook payload commits → technical changelog + client-facing plain-English update.
    """
    groq = _get_groq()
    commit_msgs = "\n".join(f"- {c.get('message', '')[:120]}" for c in commits[:15])

    try:
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a technical writer converting git commits to client updates. Return valid JSON only."},
                {"role": "user", "content": f"""Convert these commits for {client_name} to a status update. Return JSON:
{{
  "technical_changelog": "markdown formatted, for dev team",
  "client_update": "plain English, 2-3 sentences, focus on value delivered not implementation",
  "emoji_summary": "one emoji + 5 words capturing the sprint"
}}

Commits:
{commit_msgs}"""}
            ],
            max_tokens=600,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        return json.loads(r.choices[0].message.content)
    except Exception as e:
        return {"error": str(e)}
