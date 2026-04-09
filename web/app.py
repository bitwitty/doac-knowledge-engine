import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import anthropic
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import voyageai
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__)

_voyage  = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))
_pc      = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
_index   = _pc.Index(os.getenv("PINECONE_INDEX_NAME", "doac-knowledge-engine"))
_claude  = anthropic.Anthropic()

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


@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    """Stream a Claude synthesis over SSE given a query + topic."""
    data  = request.get_json() or {}
    query = data.get("query", "").strip()
    topic = data.get("topic", "")

    if not query:
        return jsonify({"error": "Query is required"}), 400

    try:
        results = retrieve(query, topic)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not results:
        return jsonify({"error": "No results to synthesize"}), 404

    # Build context block from top 6 results
    context = "\n\n".join(
        f"[{r['guest']} — {r['episode_title']}]\n{r['text']}"
        for r in results[:6]
    )
    prompt = SYNTHESIS_PROMPT.format(query=query, context=context)

    def generate():
        with _claude.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                # Server-Sent Events format
                yield f"data: {text.replace(chr(10), '<br>')}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print("DOAC Knowledge Engine")
    print("→ Open http://localhost:5000")
    app.run(debug=True, port=5000)
