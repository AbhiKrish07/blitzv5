"""
B.L.I.T.Z. Vector Memory — Pinecone-backed semantic memory with auto-extraction.
Falls back to JSON flat storage + Jina-powered keyword search (no API key needed for fallback).

Embedding engine: Jina AI (free, 1M tokens/month, https://jina.ai)
Pinecone dimension: 768 (jina-embeddings-v2-base-en)
"""
import os, json, time, hashlib, pathlib, asyncio, re
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX   = os.getenv("PINECONE_INDEX", "blitz-memory")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")

# Import embedding engine (Jina AI — free, no OpenAI)
from embeddings import embed_text, rank_by_relevance

MEMORY_FILE = pathlib.Path("memory.json")
_groq = None  # lazy init

def _get_groq():
    global _groq
    if _groq is None:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq


# ── Pinecone init (optional) ──────────────────────────────────────────────────
_pc_index = None
_use_pinecone = False

if PINECONE_API_KEY:
    try:
        from pinecone import Pinecone, ServerlessSpec
        _pc = Pinecone(api_key=PINECONE_API_KEY)
        if PINECONE_INDEX not in [i.name for i in _pc.list_indexes()]:
            _pc.create_index(
                name=PINECONE_INDEX,
                dimension=768,   # jina-embeddings-v2-base-en (v3=1024 — update EMBEDDING_DIM too)
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
        _pc_index = _pc.Index(PINECONE_INDEX)
        _use_pinecone = True
        print("[OK] Pinecone memory connected (768-dim, Jina AI)")
    except Exception as e:
        print(f"[WARN] Pinecone not available: {e}. Using flat JSON.")

# ── Flat JSON fallback ────────────────────────────────────────────────────────
def load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text())
        except Exception:
            pass
    return {"entries": [], "context": "", "preferences": {}, "personality": {}}


def save_memory(data: dict):
    MEMORY_FILE.write_text(json.dumps(data, indent=2))


# embed_text and rank_by_relevance imported from embeddings.py above
# _keyword_score kept as local alias for internal use
def _keyword_score(query: str, entry: str) -> float:
    from embeddings import keyword_score
    return keyword_score(query, entry)


# ── Save memory entry ─────────────────────────────────────────────────────────
async def save_memory_entry(text: str, meta: dict = None):
    """Save a memory entry to JSON + optionally Pinecone."""
    entry_id = hashlib.sha256(f"{text}{time.time()}".encode()).hexdigest()[:16]
    
    # Flat JSON always
    data = load_memory()
    entry = f"[{time.strftime('%Y-%m-%d %H:%M')}] {text}"
    data["entries"].append(entry)
    data["context"] = "\n".join(data["entries"][-50:])  # last 50 entries
    save_memory(data)
    
    # Pinecone
    if _use_pinecone and _pc_index:
        vector = await embed_text(text)
        if vector:
            _pc_index.upsert(vectors=[{
                "id": entry_id,
                "values": vector,
                "metadata": {"text": text, "timestamp": time.time(), **(meta or {})}
            }])


# ── Semantic search ───────────────────────────────────────────────────────────
async def search_memory(query: str, top_k: int = 5) -> list[str]:
    """Semantic search via Jina AI + Pinecone. Falls back to ranked keyword search."""
    if _use_pinecone and _pc_index:
        vector = await embed_text(query)  # uses Jina AI
        if vector:
            try:
                results = _pc_index.query(vector=vector, top_k=top_k, include_metadata=True)
                matches = [m["metadata"]["text"] for m in results.get("matches", []) if m["score"] > 0.65]
                if matches:
                    return matches
            except Exception as e:
                print(f"[WARN] Pinecone query failed: {e}")

    # Fallback: keyword-ranked search (much smarter than last-N)
    data    = load_memory()
    entries = data.get("entries", [])
    if not entries:
        return []
    return rank_by_relevance(query, entries, top_k=top_k)


# ── Auto-extract memory from conversation ─────────────────────────────────────
async def auto_extract_memory(user_msg: str, assistant_msg: str):
    """Use LLM to extract memorable facts from a conversation turn."""
    extraction_prompt = f"""Analyze this conversation exchange and extract any memorable facts, preferences, or important information about the user that should be remembered long-term.

User said: {user_msg[:500]}
Assistant replied: {assistant_msg[:300]}

RULES:
- Only extract genuinely important, long-lasting information (name, goals, preferences, facts about their life, ongoing projects)
- If nothing memorable, respond with exactly: NOTHING
- If something memorable, respond with 1-2 bullet points max, starting with: MEMORY:
  • [fact to remember]
- Also note any personality/communication preferences as: PERSONALITY: [preference]"""

    try:
        groq = _get_groq()
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": extraction_prompt}],
            max_tokens=150, temperature=0.2
        )
        result = r.choices[0].message.content.strip()
        
        if result.startswith("NOTHING"):
            return
        
        data = load_memory()
        
        if "MEMORY:" in result:
            mem_lines = [l.strip() for l in result.split("\n") if l.strip().startswith("•")]
            for line in mem_lines:
                fact = line.lstrip("• ").strip()
                if fact:
                    await save_memory_entry(fact, meta={"type": "auto_extracted"})
        
        if "PERSONALITY:" in result:
            pref_line = result.split("PERSONALITY:")[-1].strip().split("\n")[0]
            if pref_line:
                prefs = data.get("personality", {})
                prefs[f"pref_{int(time.time())}"] = pref_line
                # Keep only last 20 prefs
                if len(prefs) > 20:
                    oldest = sorted(prefs.keys())[0]
                    del prefs[oldest]
                data["personality"] = prefs
                save_memory(data)
    except Exception as e:
        print(f"[WARN] Memory extraction failed: {e}")


# ── Get personality context ───────────────────────────────────────────────────
def get_personality_context() -> str:
    """Get personality/communication preferences to inject into system prompt."""
    data = load_memory()
    prefs = data.get("personality", {})
    if not prefs:
        return ""
    return "Communication style notes: " + " | ".join(list(prefs.values())[-10:])


# ── Build rich memory context ─────────────────────────────────────────────────
async def get_rich_memory_context(query: str = "") -> str:
    """Get both flat context and semantic search results."""
    data = load_memory()
    flat_ctx = data.get("context", "") or "\n".join(data.get("entries", [])[-20:])
    
    semantic_ctx = ""
    if query and _use_pinecone:
        results = await search_memory(query, top_k=5)
        if results:
            semantic_ctx = "\n\nSemantically relevant memories:\n" + "\n".join(f"• {r}" for r in results)
    
    personality = get_personality_context()
    
    parts = []
    if flat_ctx:
        parts.append(flat_ctx)
    if semantic_ctx:
        parts.append(semantic_ctx)
    if personality:
        parts.append(f"\n{personality}")
    
    return "\n".join(parts) if parts else "No personal context saved yet."
