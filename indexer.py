"""
B.L.I.T.Z. Codebase Indexer
Reads and chunks your entire repo into a searchable index.
BLITZ knows your architecture, design patterns, and file structure.

Commands:
  index_directory("/path/to/repo")       → chunks all code into JSON index
  search_codebase("how auth works")      → finds relevant files and chunks
  summarize_architecture("/path/to/repo") → generates/updates ARCHITECTURE.md

Storage: codebase_index.json (local, no cloud required)
Optional Pinecone: set PINECONE_API_KEY + JINA_API_KEY for semantic search
"""
import os, json, time, re, pathlib, asyncio
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
INDEX_FILE   = pathlib.Path(os.getenv("CODEBASE_INDEX_PATH", "codebase_index.json"))

# File extensions to index
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs",
    ".go", ".java", ".cpp", ".c", ".h", ".cs",
    ".rb", ".php", ".swift", ".kt", ".rs",
    ".sql", ".graphql", ".yaml", ".yml", ".toml",
    ".md", ".txt", ".env.example",
}

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", "vendor", "target", ".cargo",
    "coverage", ".nyc_output", "eggs", ".eggs", "*.egg-info",
}

CHUNK_SIZE    = 1200   # chars per chunk
CHUNK_OVERLAP = 150    # overlap to preserve context across boundaries

_groq = None
def _get_groq():
    global _groq
    if _groq is None:
        from groq import AsyncGroq
        _groq = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq


# ── Smart Code Chunker ────────────────────────────────────────────────────────
def chunk_code(content: str, filepath: str = "") -> list[str]:
    """
    Split code on function/class boundaries first, then fixed size.
    Preserves semantic units — a chunk always starts at a meaningful boundary.
    """
    # Try to split on logical boundaries (works for Python, JS, Go, etc.)
    boundary_pattern = re.compile(
        r"^(?:def |async def |class |function |const |let |var |export (?:default )?(?:function|class|const)|"
        r"func |pub fn |fn |static |public |private |protected |@app\.|@router\.|module\.exports)",
        re.MULTILINE
    )
    positions = [m.start() for m in boundary_pattern.finditer(content)]

    chunks = []
    if len(positions) > 1:
        for i, pos in enumerate(positions):
            end   = positions[i + 1] if i + 1 < len(positions) else len(content)
            chunk = content[pos:end].strip()
            if not chunk:
                continue
            # Sub-split if chunk is too large
            while len(chunk) > CHUNK_SIZE:
                chunks.append(chunk[:CHUNK_SIZE])
                chunk = chunk[CHUNK_SIZE - CHUNK_OVERLAP:]
            if chunk:
                chunks.append(chunk)
    else:
        # Fallback: fixed-size with overlap
        for i in range(0, len(content), CHUNK_SIZE - CHUNK_OVERLAP):
            chunk = content[i:i + CHUNK_SIZE].strip()
            if chunk:
                chunks.append(chunk)

    return chunks


# ── Directory Indexer ─────────────────────────────────────────────────────────
def index_directory(
    root_path: str,
    extensions: set = None,
    exclude_dirs: set = None,
    max_file_kb: int = 512,
) -> dict:
    """
    Walk a directory, chunk all code files, write index to codebase_index.json.
    Returns summary dict.
    """
    root      = pathlib.Path(root_path).resolve()
    exts      = extensions or CODE_EXTENSIONS
    skip      = exclude_dirs or SKIP_DIRS
    all_chunks = []
    file_count = 0
    skipped    = 0

    for fpath in root.rglob("*"):
        # Skip excluded dirs
        if any(part in skip for part in fpath.parts):
            continue
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() not in exts:
            continue
        if fpath.stat().st_size > max_file_kb * 1024:
            skipped += 1
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            if len(content.strip()) < 30:
                continue

            rel_path = str(fpath.relative_to(root))
            chunks   = chunk_code(content, str(fpath))

            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    "id":          f"{rel_path}::{i}",
                    "file":        rel_path,
                    "chunk_index": i,
                    "content":     chunk,
                    "language":    fpath.suffix.lstrip("."),
                    "size_chars":  len(chunk),
                })
            file_count += 1

        except Exception as e:
            print(f"[INDEXER] Skipping {fpath}: {e}")

    index = {
        "root":        str(root),
        "indexed_at":  time.time(),
        "indexed_date": time.strftime("%Y-%m-%d %H:%M"),
        "file_count":  file_count,
        "chunk_count": len(all_chunks),
        "skipped":     skipped,
        "chunks":      all_chunks,
    }
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[INDEXER] ✓ {file_count} files → {len(all_chunks)} chunks → {INDEX_FILE}")
    return {k: v for k, v in index.items() if k != "chunks"}  # don't return all chunks in summary


# ── Codebase Search ───────────────────────────────────────────────────────────
def search_codebase(query: str, top_k: int = 8, file_filter: str = "") -> list[dict]:
    """
    Keyword-scored search over indexed codebase.
    Set file_filter to narrow to a file path substring (e.g. "auth", ".py").
    """
    if not INDEX_FILE.exists():
        return []

    from embeddings import keyword_score
    try:
        data   = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    chunks = data.get("chunks", [])

    if file_filter:
        chunks = [c for c in chunks if file_filter.lower() in c["file"].lower()]

    scored = [
        (c, keyword_score(query, c["content"]) * 0.7 + keyword_score(query, c["file"]) * 0.3)
        for c in chunks
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    results = [c for c, s in scored if s > 0][:top_k]

    # Add relevance score
    for i, (c, s) in enumerate(scored[:top_k]):
        if s > 0:
            c["relevance"] = round(s, 3)

    return results


def get_index_summary() -> dict:
    """Return metadata about the current index without the full chunk data."""
    if not INDEX_FILE.exists():
        return {"indexed": False}
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        files = list(set(c["file"] for c in data.get("chunks", [])))
        return {
            "indexed":      True,
            "root":         data.get("root"),
            "indexed_date": data.get("indexed_date"),
            "file_count":   data.get("file_count"),
            "chunk_count":  data.get("chunk_count"),
            "file_types":   list(set(f.rsplit(".", 1)[-1] for f in files if "." in f)),
            "sample_files": sorted(files)[:20],
        }
    except Exception as e:
        return {"indexed": False, "error": str(e)}


# ── Architecture Doc Generator ────────────────────────────────────────────────
async def summarize_architecture(root_path: str = None, force_reindex: bool = False) -> str:
    """
    Generate/update ARCHITECTURE.md from the codebase index.
    Reads key files to understand structure, then asks Groq to document it.
    """
    if force_reindex and root_path:
        index_directory(root_path)
    elif not INDEX_FILE.exists() and root_path:
        index_directory(root_path)
    elif not INDEX_FILE.exists():
        return "No codebase indexed. Run `POST /api/codebase/index` first."

    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to read index: {e}"

    chunks = data.get("chunks", [])

    # Build a compact overview: first chunk of each file + all filenames
    all_files   = sorted(set(c["file"] for c in chunks))
    first_chunks = {}
    for c in chunks:
        if c["file"] not in first_chunks:
            first_chunks[c["file"]] = c["content"][:600]

    # Pick most interesting files: entry points, routers, models, configs
    priority_keywords = ["main", "app", "router", "model", "schema", "config", "index", "server"]
    priority_files = [f for f in all_files if any(k in f.lower() for k in priority_keywords)]
    sample_files   = priority_files[:15] + [f for f in all_files if f not in priority_files][:10]

    context = "FILES:\n" + "\n".join(all_files[:80])
    context += "\n\nKEY FILE PREVIEWS:\n"
    for f in sample_files:
        if f in first_chunks:
            context += f"\n### {f}\n```\n{first_chunks[f]}\n```\n"

    groq = _get_groq()
    try:
        r = await groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are B.L.I.T.Z. generating a living ARCHITECTURE.md. "
                        "Be precise about data flow, design decisions, and patterns. "
                        "A senior engineer should read this and immediately understand the system."
                    )
                },
                {
                    "role": "user",
                    "content": f"""Generate a comprehensive ARCHITECTURE.md for this codebase.

{context}

Include these sections:
## Overview
## Directory Structure (tree format)
## Core Components (what each file/module does)
## Data Flow (how a request moves through the system)
## Key Design Decisions (with rationale)
## API Endpoints (if applicable)
## Environment Variables (required vs optional)
## Known Limitations / TODOs"""
                }
            ],
            max_tokens=4000,
            temperature=0.2
        )
        arch_doc = r.choices[0].message.content

        # Write to repo root
        arch_path = (pathlib.Path(data.get("root", ".")) / "ARCHITECTURE.md")
        arch_path.write_text(arch_doc, encoding="utf-8")
        print(f"[INDEXER] ARCHITECTURE.md written to {arch_path}")
        return arch_doc

    except Exception as e:
        return f"Architecture generation failed: {e}"


# ── Dependency Analyzer ───────────────────────────────────────────────────────
async def analyze_dependency_impact(file_or_function: str) -> dict:
    """
    'What breaks if I change X?' — traces impact across the codebase.
    Returns files that import/reference the target.
    """
    if not INDEX_FILE.exists():
        return {"error": "No codebase indexed"}

    try:
        data   = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
    except Exception as e:
        return {"error": str(e)}

    target  = file_or_function.lower()
    matches = []
    for c in chunks:
        if target in c["content"].lower() or target in c["file"].lower():
            matches.append({
                "file":    c["file"],
                "snippet": c["content"][:200].strip(),
            })

    # Deduplicate by file
    seen  = set()
    dedup = []
    for m in matches:
        if m["file"] not in seen:
            seen.add(m["file"])
            dedup.append(m)

    if not dedup:
        return {"target": target, "impacted_files": [], "risk": "none", "summary": "No references found."}

    # Ask Groq to assess risk
    groq = _get_groq()
    impact_ctx = "\n".join(f"- {m['file']}: {m['snippet'][:80]}" for m in dedup[:10])
    try:
        r = await groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Dependency impact analyzer. Return only valid JSON."},
                {"role": "user", "content": f"""Target: {file_or_function}
Impacted files ({len(dedup)} total):
{impact_ctx}

Return JSON: {{"risk": "low|medium|high|critical", "summary": "string", "key_concerns": ["string"]}}"""}
            ],
            max_tokens=300,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        assessment = json.loads(r.choices[0].message.content)
    except Exception:
        assessment = {"risk": "unknown", "summary": f"{len(dedup)} files reference this"}

    return {
        "target":         file_or_function,
        "impacted_files": dedup[:20],
        "total_refs":     len(dedup),
        **assessment
    }
