import os
import ssl
import json as _json
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import certifi

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
            "x-api-key":         os.getenv("ANTHROPIC_API_KEY", "").strip(),
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
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
Synthesize insights from The Diary of a CEO with Steven Bartlett.

Question: "{query}"

Excerpts:

{context}

Rules (follow exactly):
- MAXIMUM 90 words. Aim for 75. Stop writing when you reach 90. This is a hard limit.
- Two short paragraphs. No title line. Do not restate the question.
- Every sentence must name the guest who said it. No sentence without a named guest.
- Only attribute a point to a guest if the excerpt clearly comes from that guest's episode \
and is not the host (Steven Bartlett) speaking. Compilation episodes ("Most Replayed Moment") \
contain several unnamed speakers — skip any point that cannot be attributed to a named guest.
- Never say "multiple guests", "the experts agree", "consensus", or similar unless at least \
two named guests explicitly say the same thing in the excerpts.
- Plain, direct sentences. No markdown. Avoid "resonates", "collective wisdom", "core message", "unified".
- The host often states a claim or statistic and then asks a question about it. Never attribute a claim that leads into a question to the guest.
- Don't add causes or explanations that aren't stated in the excerpt.
- Stop after the last guest's point. Do not add a concluding or summarising sentence of your own."""


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


GUEST_NORMALISE = {
    "Gabor Mate": "Gabor Maté",
}


def _norm_guest(name: str) -> str:
    return GUEST_NORMALISE.get(name, name)


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
            "guest":         _norm_guest(md.get("guest", "")),
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
        synthesis = _call_claude(prompt, max_tokens=250)
    except Exception:
        return jsonify({"error": "Please try again."}), 500

    return jsonify({"synthesis": synthesis})


if __name__ == "__main__":
    print("DOAC Knowledge Engine")
    print("→ Open http://localhost:5000")
    app.run(debug=True, port=5000)
