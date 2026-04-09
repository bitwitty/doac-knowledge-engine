"""
03_fetch_transcripts.py
Fetches YouTube auto-captions for selected episodes via yt-dlp.

Strategy:
  1. Scrape the DOAC YouTube channel for all video metadata (title + URL)
  2. Match each selected episode to a YouTube video by title similarity
  3. Download auto-generated English captions (WebVTT format) for matched videos
  4. Save raw VTT files to data/transcripts/{episode_id}/

Run with --test to process only 3 episodes first.
Output: data/transcripts/{episode_id}/captions.vtt
        data/selected_episodes.json (updated with youtube_url)
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from tqdm import tqdm

DATA_DIR = Path(__file__).parent.parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
TRANSCRIPTS_DIR.mkdir(exist_ok=True)

SELECTED_FILE = DATA_DIR / "selected_episodes.json"
CHANNEL_CACHE = DATA_DIR / "_youtube_channel_cache.json"

# DOAC YouTube channel
DOAC_YOUTUBE_CHANNEL = "https://www.youtube.com/@TheDiaryOfACEO/videos"


def similarity(a: str, b: str) -> float:
    """String similarity ratio between 0-1."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def normalize_title(title: str) -> str:
    """Strip episode numbers and common prefixes for better title matching."""
    # Remove "E123 " or "E123: " or "#123 " prefixes
    title = re.sub(r"^E\d+[\s:|]+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^#\d+[\s:|]+", "", title)
    # Remove trailing " | The Diary Of A CEO" and similar
    title = re.sub(r"\s*\|.*$", "", title)
    title = re.sub(r"\s*-\s*(The Diary Of A CEO|DOAC|Steven Bartlett).*$", "", title, flags=re.IGNORECASE)
    return title.strip()


def fetch_channel_videos() -> list[dict]:
    """Use yt-dlp to fetch all video metadata from the DOAC channel (no download)."""
    if CHANNEL_CACHE.exists():
        print(f"Loading cached channel data from {CHANNEL_CACHE}")
        with open(CHANNEL_CACHE) as f:
            return json.load(f)

    print(f"Scraping DOAC YouTube channel metadata (this takes ~2-3 minutes)...")
    print(f"Channel: {DOAC_YOUTUBE_CHANNEL}")

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--no-warnings",
        "--print", "%(id)s\t%(title)s\t%(upload_date)s\t%(duration)s",
        "--playlist-end", "1000",  # cap at 1000 to be safe
        DOAC_YOUTUBE_CHANNEL,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print("ERROR: yt-dlp timed out scraping the channel")
        sys.exit(1)
    except FileNotFoundError:
        print("ERROR: yt-dlp not found. Install with: pip install yt-dlp")
        sys.exit(1)

    if result.returncode != 0 and not result.stdout:
        print(f"yt-dlp error:\n{result.stderr}")
        sys.exit(1)

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        video_id = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        upload_date = parts[2].strip() if len(parts) > 2 else ""
        duration = parts[3].strip() if len(parts) > 3 else ""
        videos.append({
            "video_id": video_id,
            "title": title,
            "upload_date": upload_date,
            "duration": duration,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
        })

    print(f"Found {len(videos)} videos on channel")

    # Cache for future runs
    with open(CHANNEL_CACHE, "w") as f:
        json.dump(videos, f, indent=2)

    return videos


def match_episode_to_video(episode: dict, videos: list[dict]) -> dict | None:
    """Find best YouTube video match for a podcast episode."""
    ep_title = normalize_title(episode["title"])

    best_match = None
    best_score = 0.0

    for video in videos:
        yt_title = normalize_title(video["title"])
        score = similarity(ep_title, yt_title)
        if score > best_score:
            best_score = score
            best_match = video

    # Guest name check as a tiebreaker signal
    if best_score < 0.5 and episode.get("marquee_guest"):
        guest = episode["marquee_guest"].lower()
        for video in videos:
            if guest in video["title"].lower():
                score = similarity(ep_title, normalize_title(video["title"]))
                if score > best_score:
                    best_score = score
                    best_match = video

    # Require at least 40% similarity to accept a match
    if best_score < 0.40:
        return None

    return {**best_match, "match_score": round(best_score, 3)}


def download_captions(video_url: str, episode_id: str) -> Path | None:
    """Download auto-generated English captions as WebVTT. Returns path to VTT file."""
    ep_dir = TRANSCRIPTS_DIR / episode_id
    ep_dir.mkdir(exist_ok=True)
    output_path = ep_dir / "captions"  # yt-dlp adds extension

    # Check if already downloaded
    existing = list(ep_dir.glob("*.vtt"))
    if existing:
        return existing[0]

    cmd = [
        "yt-dlp",
        "--write-auto-subs",
        "--sub-lang", "en",
        "--sub-format", "vtt",
        "--skip-download",              # captions only, no video/audio
        "--no-warnings",
        "--output", str(output_path),
        video_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print(f"    Timeout downloading captions for {episode_id}")
        return None

    # Find the downloaded VTT file
    vtt_files = list(ep_dir.glob("*.vtt"))
    if vtt_files:
        return vtt_files[0]

    # Some videos only have manual subs — try without "auto"
    cmd_manual = [
        "yt-dlp",
        "--write-subs",
        "--sub-lang", "en",
        "--sub-format", "vtt",
        "--skip-download",
        "--no-warnings",
        "--output", str(output_path),
        video_url,
    ]
    result2 = subprocess.run(cmd_manual, capture_output=True, text=True, timeout=120)
    vtt_files = list(ep_dir.glob("*.vtt"))
    return vtt_files[0] if vtt_files else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Process only 3 episodes for testing")
    parser.add_argument("--skip-channel-scrape", action="store_true", help="Use cached channel data only")
    args = parser.parse_args()

    print("=" * 60)
    print("Transcript Fetch — Step 3 of 7")
    if args.test:
        print("[TEST MODE — 3 episodes only]")
    print("=" * 60)

    with open(SELECTED_FILE, encoding="utf-8") as f:
        episodes = json.load(f)

    if args.test:
        # Pick 3 topically varied episodes for the test run
        test_episodes = []
        seen_topics = set()
        for ep in episodes:
            if ep.get("primary_topic") not in seen_topics:
                test_episodes.append(ep)
                seen_topics.add(ep.get("primary_topic"))
            if len(test_episodes) == 3:
                break
        episodes_to_process = test_episodes
    else:
        episodes_to_process = episodes

    # Fetch YouTube channel video list
    videos = fetch_channel_videos()

    # Match episodes to YouTube videos
    print(f"\nMatching {len(episodes_to_process)} episodes to YouTube videos...")
    matched = []
    unmatched = []

    for ep in episodes_to_process:
        match = match_episode_to_video(ep, videos)
        if match:
            matched.append((ep, match))
            print(f"  ✓ [{match['match_score']:.0%}] {ep['title'][:55]}")
        else:
            unmatched.append(ep)
            print(f"  ✗ NO MATCH: {ep['title'][:55]}")

    print(f"\nMatched: {len(matched)}, Unmatched: {len(unmatched)}")

    if unmatched:
        print("\nUnmatched episodes (will need manual YouTube URLs):")
        for ep in unmatched:
            print(f"  - {ep['title']}")

    # Download captions
    print(f"\nDownloading captions for {len(matched)} episodes...")
    success = []
    failed = []

    for ep, match in tqdm(matched, desc="Downloading captions"):
        vtt_path = download_captions(match["youtube_url"], ep["id"])
        if vtt_path:
            ep["youtube_url"] = match["youtube_url"]
            ep["youtube_match_score"] = match["match_score"]
            ep["vtt_path"] = str(vtt_path)
            success.append(ep)
        else:
            failed.append(ep)
            print(f"\n  Failed to get captions: {ep['title'][:55]}")

    print(f"\nCaptions downloaded: {len(success)}, Failed: {len(failed)}")

    # Update selected_episodes.json with youtube_urls for matched episodes
    # (Only update if doing full run, not test)
    if not args.test:
        ep_by_id = {ep["id"]: ep for ep in success}
        for ep in episodes:
            if ep["id"] in ep_by_id:
                ep["youtube_url"] = ep_by_id[ep["id"]]["youtube_url"]
                ep["youtube_match_score"] = ep_by_id[ep["id"]]["youtube_match_score"]

        with open(SELECTED_FILE, "w", encoding="utf-8") as f:
            json.dump(episodes, f, indent=2, ensure_ascii=False)
        print(f"Updated {SELECTED_FILE} with YouTube URLs")

    if args.test:
        print("\n[TEST COMPLETE] Check data/transcripts/ for VTT files.")
        print("Spot-check quality before running without --test flag.")

    print("\nStep 3 complete.")


if __name__ == "__main__":
    main()
