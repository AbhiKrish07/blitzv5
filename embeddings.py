"""
B.L.I.T.Z. Embedding Engine
Uses Jina AI (free, 1M tokens/month, no credit card — https://jina.ai)
Zero dependency on OpenAI. Falls back to keyword scoring without a key.

Models:
  jina-embeddings-v2-base-en  → 768 dims  (English, fast, free)
  jina-embeddings-v3          → 1024 dims (multilingual, better, free)
"""
import os, re, asyncio
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

JINA_API_KEY  = os.getenv("JINA_API_KEY", "")
JINA_MODEL    = os.getenv("JINA_MODEL", "jina-embeddings-v2-base-en")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))  # 768 for v2, 1024 for v3

_jina_warned = False


async def embed_text(text: str) -> Optional[list[float]]:
    """
    Get a text embedding via Jina AI (free tier: 1M tokens/month).
    Returns None if JINA_API_KEY is not set — caller falls back to keyword search.
    Sign up: https://jina.ai → copy API key from dashboard (it starts with 'jina_')
    """
    global _jina_warned
    if not JINA_API_KEY:
        if not _jina_warned:
            print("[EMBED] JINA_API_KEY not set — using keyword search fallback. "
                  "Get a free key at https://jina.ai (1M tokens/month, no card)")
            _jina_warned = True
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.post(
                "https://api.jina.ai/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {JINA_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={"input": [text[:8000]], "model": JINA_MODEL}
            )
            if r.status_code == 200:
                return r.json()["data"][0]["embedding"]
            else:
                print(f"[EMBED] Jina error {r.status_code}: {r.text[:200]}")
                return None
    except Exception as e:
        print(f"[EMBED] Jina embedding failed: {e}")
        return None


# ── Keyword scoring fallback (used everywhere when no embedding key) ───────────
def keyword_score(query: str, text: str) -> float:
    """
    TF-IDF-style keyword overlap score. Higher = more relevant.
    Used as semantic search fallback when Jina API key not set.
    """
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "i", "my", "me",
        "to", "of", "and", "in", "it", "this", "that", "for", "on",
        "with", "be", "at", "by", "from", "as", "or", "but", "not"
    }
    q_words = set(re.sub(r"[^\w\s]", "", query.lower()).split()) - stopwords
    t_words = set(re.sub(r"[^\w\s]", "", text.lower()).split()) - stopwords
    if not q_words:
        return 0.0
    overlap = len(q_words & t_words)
    # Boost: check for phrase-level matches
    phrase_boost = 1.5 if query.lower() in text.lower() else 1.0
    return (overlap / len(q_words)) * phrase_boost


def rank_by_relevance(query: str, items: list[str], top_k: int = 5) -> list[str]:
    """Sort a list of text strings by relevance to a query using keyword scoring."""
    if not query.strip():
        return items[-top_k:]
    scored = [(s, keyword_score(query, s)) for s in items]
    scored.sort(key=lambda x: x[1], reverse=True)
    relevant = [s for s, score in scored if score > 0][:top_k]
    return relevant if relevant else items[-top_k:]
