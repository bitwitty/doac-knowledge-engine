# DOAC Knowledge Engine

A semantic search and synthesis tool built on top of The Diary of a CEO podcast (815+ episodes). Ask a natural-language question, get the most relevant moments across episodes with timestamped YouTube links and an AI-generated synthesis of what the experts collectively say.

Fan-built prototype — not affiliated with the podcast.

## What it does

- **Semantic search** across 2,500+ transcript chunks via Voyage AI embeddings and Pinecone
- **AI synthesis** — Claude generates a summary card attributing ideas to specific guests, highlighting where experts agree or differ
- **Timestamped deep links** — every result links to the exact moment in the YouTube video
- **Topic filtering** across 9 categories (Mental Health, Entrepreneurship, Neuroscience, Relationships, AI & Technology, etc.)
- **Full episode categorization** — all 815 episodes classified by topic with AI-generated summaries

## The pipeline

The data pipeline is a 7-step numbered sequence:

| Step | What it does |
|------|-------------|
| 01 | Fetches all 815 episode metadata from the Acast RSS feed via iTunes API |
| 02 | Selects ~30 demo episodes balancing marquee guests and topical diversity |
| 03 | Matches episodes to YouTube videos by title similarity, downloads auto-captions |
| 04 | Cleans raw VTT transcripts via Claude Haiku (fixes transcription errors, punctuation) |
| 05 | Chunks into ~300-word overlapping windows with sentence-boundary awareness |
| 06 | Embeds with Voyage AI (1024-dim), upserts to Pinecone with full metadata |
| 07 | Categorizes all 815 episodes via Claude Haiku (primary topic, secondary topics, summary) |

Each step is a standalone script that can be run independently or as part of the full pipeline.

## Stack

| Layer | Tech |
|-------|------|
| Pipeline | Python, yt-dlp, feedparser, httpx |
| AI (cleanup) | Claude Haiku |
| Embeddings | Voyage AI voyage-3-large (1024-dim) |
| Vector DB | Pinecone serverless |
| AI (synthesis) | Claude Haiku (real-time at query time) |
| Web app | Flask, vanilla JS |
| Hosting | Railway |

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env
# Add your API keys to .env

# Run the web app
python web/app.py

# Run pipeline steps individually
python pipeline/01_fetch_metadata.py
python pipeline/02_select_episodes.py
# ... etc
```

## Status

30 of 815 episodes indexed (2,501 searchable moments). Infrastructure supports scaling to the full catalogue.
