"""
01_fetch_metadata.py
Fetches all DOAC episode metadata from the podcast RSS feed.
Uses iTunes Lookup API to get the authoritative RSS feed URL, then parses it with feedparser.
Output: data/episodes.json
"""

import json
import re
import sys
import time
from pathlib import Path

import feedparser
import httpx
from tqdm import tqdm

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = DATA_DIR / "episodes.json"

APPLE_PODCASTS_ID = "1291423644"  # The Diary of a CEO with Steven Bartlett


def get_rss_feed_url() -> str:
    """Resolve the authoritative RSS URL via iTunes Lookup API."""
    url = f"https://itunes.apple.com/lookup?id={APPLE_PODCASTS_ID}&entity=podcast"
    print(f"Resolving RSS feed URL via iTunes Lookup API...")
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise RuntimeError("No results from iTunes Lookup API")
    feed_url = results[0].get("feedUrl")
    if not feed_url:
        raise RuntimeError("No feedUrl in iTunes Lookup response")
    print(f"RSS feed URL: {feed_url}")
    return feed_url


def extract_guest_from_title(title: str) -> str:
    """
    Best-effort guest extraction from DOAC episode titles.
    DOAC uses consistent patterns like:
      "Guest Name: Topic Headline"
      "Steven Bartlett: ..."  <- Steven-only episode
    Returns empty string if uncertain.
    """
    # Many DOAC titles follow "Name: Topic" or "E{n}: Guest Name: Topic"
    # Strip episode number prefix if present
    clean = re.sub(r"^E\d+[\s\|:]+", "", title, flags=re.IGNORECASE).strip()
    # Try "Name: Topic" pattern
    if ":" in clean:
        candidate = clean.split(":")[0].strip()
        # Sanity check: guest names are 2-4 words, not too long
        words = candidate.split()
        if 1 < len(words) <= 4 and len(candidate) < 50:
            return candidate
    return ""


def parse_duration(duration_str: str) -> int:
    """Convert duration string (HH:MM:SS or MM:SS or seconds) to seconds."""
    if not duration_str:
        return 0
    parts = str(duration_str).strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(parts[0])
    except ValueError:
        return 0


def fetch_episodes(feed_url: str) -> list[dict]:
    print(f"Parsing RSS feed (this may take a moment for 800+ episodes)...")
    # Use httpx to fetch feed content (avoids macOS Python SSL cert issues)
    # feedparser.parse() accepts raw content string as well as URLs
    print(f"Downloading feed content...")
    resp = httpx.get(feed_url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    if feed.bozo:
        print(f"Warning: Feed parser encountered an issue: {feed.bozo_exception}")

    entries = feed.entries
    print(f"Found {len(entries)} episodes in feed")

    episodes = []
    for i, entry in enumerate(tqdm(entries, desc="Parsing episodes")):
        episode_id = entry.get("id", "") or entry.get("guid", "") or str(i)
        # Sanitize to a safe filename-compatible ID
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", episode_id)[-64:]

        title = entry.get("title", "").strip()
        description = entry.get("summary", "") or entry.get("description", "")
        # Strip HTML tags from description
        description_clean = re.sub(r"<[^>]+>", "", description).strip()
        # Trim to first 500 chars for metadata (full text not needed here)
        description_clean = description_clean[:500]

        # Published date
        published = entry.get("published", "") or entry.get("updated", "")

        # Duration (itunes namespace)
        duration_str = entry.get("itunes_duration", "") or entry.get("duration", "")
        duration_secs = parse_duration(str(duration_str))

        # Audio URL (first enclosure)
        audio_url = ""
        if entry.get("enclosures"):
            audio_url = entry["enclosures"][0].get("href", "")

        # Episode number (itunes namespace)
        ep_number = entry.get("itunes_episode", "") or ""

        # Guest (best-effort from title)
        guest = extract_guest_from_title(title)

        episodes.append({
            "id": safe_id,
            "episode_number": str(ep_number),
            "title": title,
            "guest": guest,
            "published": published,
            "duration_seconds": duration_secs,
            "description": description_clean,
            "audio_url": audio_url,
            "youtube_url": "",  # populated later via yt-dlp channel scrape
        })

        # Be kind to the parser on huge feeds
        if i % 100 == 0 and i > 0:
            time.sleep(0.1)

    # Most recent first
    return episodes


def main():
    print("=" * 60)
    print("DOAC Metadata Fetch — Step 1 of 7")
    print("=" * 60)

    try:
        feed_url = get_rss_feed_url()
    except Exception as e:
        print(f"iTunes lookup failed: {e}")
        print("Trying known fallback feed URLs...")
        # Known Acast feed URL for DOAC
        feed_url = "https://feeds.acast.com/public/shows/the-diary-of-a-ceo-with-steven-bartlett"

    episodes = fetch_episodes(feed_url)

    if not episodes:
        print("ERROR: No episodes found. Check the feed URL.")
        sys.exit(1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(episodes, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(episodes)} episodes to {OUTPUT_FILE}")

    # Summary
    guests_found = sum(1 for ep in episodes if ep["guest"])
    avg_duration = sum(ep["duration_seconds"] for ep in episodes) / len(episodes) / 60
    print(f"Guest names extracted: {guests_found}/{len(episodes)}")
    print(f"Average episode duration: {avg_duration:.0f} minutes")
    print(f"\nSample episodes:")
    for ep in episodes[:5]:
        print(f"  [{ep['episode_number']}] {ep['title'][:70]}")

    print("\nStep 1 complete.")


if __name__ == "__main__":
    main()
