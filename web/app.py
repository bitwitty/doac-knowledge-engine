import os
import json as _json
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from flask import Flask, render_template, request, jsonify
import voyageai
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__)

_voyage  = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))
_pc      = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
_index   = _pc.Index(os.getenv("PINECONE_INDEX_NAME", "doac-knowledge-engine"))


def _call_claude(prompt: str, max_tokens: int = 500) -> str:
    """Call the Anthropic Messages API directly via urllib (no SDK dependency)."""
    payload = _json.dumps({
        "model":      "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages":   [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         os.getenv("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = _json.loads(resp.read())
    return body["content"][0]["text"].strip()

TOPICS = [
    "Entrepreneurship",
    "Mental Health",
    "Nutrition & Health",
    "Neuroscience",
    "Relationships",
    "AI & Technology",
    "Money & Investing",
    "Creativity & Career",
    "Spirituality & Meaning",
]

SYNTHESIS_PROMPT = """\
You are synthesizing insights from The Diary of a CEO with Steven Bartlett.

The user asked: "{query}"

Here are relevant moments from different episodes:

{context}

Write a direct, 2–3 paragraph synthesis of what these experts collectively say about this question. \
Name specific guests when attributing ideas. Highlight where they agree and where their perspectives differ. \
Write for someone who wants the core wisdom without having to watch the episodes — be specific, not generic."""


def fmt_time(seconds: int) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def make_watch_url(youtube_url: str, seconds: int) -> str:
    if not youtube_url:
        return ""
    try:
        parsed = urlparse(youtube_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        params["t"] = str(int(seconds))
        return urlunparse(parsed._replace(query=urlencode(params)))
    except Exception:
        return youtube_url


def retrieve(query: str, topic: str) -> tuple[list[dict], list]:
    """Embed query and search Pinecone. Returns (formatted_results, raw_chunks_for_synthesis)."""
    emb = _voyage.embed([query], model="voyage-3-large", input_type="query").embeddings[0]
    kwargs = {"vector": emb, "top_k": 8, "include_metadata": True}
    if topic in TOPICS:
        kwargs["filter"] = {"primary_topic": {"$eq": topic}}
    matches = _index.query(**kwargs).matches

    results = []
    for m in matches:
        md = m.metadata
        start = int(md.get("start_seconds", 0))
        results.append({
            "guest":         md.get("guest", ""),
            "episode_title": md.get("episode_title", ""),
            "primary_topic": md.get("primary_topic", ""),
            "text":          md.get("text", ""),
            "timestamp":     fmt_time(start),
            "watch_url":     make_watch_url(md.get("youtube_url", ""), start),
        })
    return results


@app.route("/")
def index():
    return render_template("index.html", topics=TOPICS)


@app.route("/api/search", methods=["POST"])
def search():
    data  = request.get_json() or {}
    query = data.get("query", "").strip()
    topic = data.get("topic", "")

    if not query:
        return jsonify({"error": "Query is required"}), 400
    if len(query) > 500:
        return jsonify({"error": "Query too long"}), 400

    try:
        results = retrieve(query, topic)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"results": results, "query": query})


@app.route("/api/health")
def health():
    """Diagnostic endpoint — checks keys and Anthropic reachability."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    try:
        _call_claude("Say OK", max_tokens=5)
        claude_ok = True
        claude_error = None
    except Exception as e:
        claude_ok = False
        claude_error = f"[{type(e).__name__}] {e}"
    return jsonify({
        "anthropic_key_set":    bool(key),
        "anthropic_key_prefix": key[:12] + "..." if len(key) > 12 else "(empty)",
        "claude_reachable":     claude_ok,
        "claude_error":         claude_error,
    })


@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    """Accept query + pre-fetched results, return a Claude synthesis."""
    data    = request.get_json() or {}
    query   = data.get("query", "").strip()
    results = data.get("results", [])

    if not query:
        return jsonify({"error": "Query is required"}), 400
    if not results:
        return jsonify({"error": "No results provided"}), 400

    context = "\n\n".join(
        f"[{r.get('guest', '')} — {r.get('episode_title', '')}]\n{r.get('text', '')}"
        for r in results[:6]
    )
    prompt = SYNTHESIS_PROMPT.format(query=query, context=context)

    try:
        synthesis = _call_claude(prompt)
    except Exception as e:
        error_type = type(e).__name__
        return jsonify({"error": f"Synthesis failed [{error_type}]: {str(e)}"}), 500

    return jsonify({"synthesis": synthesis})


if __name__ == "__main__":
    print("DOAC Knowledge Engine")
    print("→ Open http://localhost:5000")
    app.run(debug=True, port=5000)
