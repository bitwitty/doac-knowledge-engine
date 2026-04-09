"""
04_clean_transcripts.py
Parses raw WebVTT files and runs a Claude Haiku cleanup pass.

VTT → list of timed segments → Claude cleanup → cleaned JSON
Output: data/cleaned_transcripts/{episode_id}.json
Each file: list of {"text": str, "start_seconds": int, "end_seconds": int}
"""

import json
import re
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
CLEANED_DIR = DATA_DIR / "cleaned_transcripts"
CLEANED_DIR.mkdir(exist_ok=True)
SELECTED_FILE = DATA_DIR / "selected_episodes.json"

client = anthropic.Anthropic()

WINDOW_SECONDS = 30  # Group VTT cues into ~30-second windows


def parse_vtt_timestamp(ts: str) -> int:
    """Convert VTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to integer seconds."""
    ts = ts.strip().split(".")[0]  # drop milliseconds
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0
    except ValueError:
        return 0


def parse_vtt(vtt_path: Path) -> list[dict]:
    """Parse a WebVTT file into a list of {text, start, end} cues."""
    content = vtt_path.read_text(encoding="utf-8", errors="replace")
    cues = []
    # Match VTT cue blocks: timestamp line + text
    pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})"
        r"\s*-->\s*"
        r"(\d{2}:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})"
        r"[^\n]*\n([\s\S]*?)(?=\n\n|\Z)",
        re.MULTILINE,
    )
    for match in pattern.finditer(content):
        start = parse_vtt_timestamp(match.group(1))
        end = parse_vtt_timestamp(match.group(2))
        text = match.group(3).strip()
        # Strip VTT tags like <c>, <00:00:01.000>
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cues.append({"text": text, "start": start, "end": end})

    # Deduplicate consecutive identical cues (auto-subs repeat frequently)
    deduped = []
    for cue in cues:
        if not deduped or cue["text"] != deduped[-1]["text"]:
            deduped.append(cue)

    return deduped


def group_into_windows(cues: list[dict], window_secs: int = WINDOW_SECONDS) -> list[dict]:
    """Group cues into fixed-size time windows for cleaner cleaning chunks."""
    if not cues:
        return []

    windows = []
    current_texts = []
    current_start = cues[0]["start"]
    current_end = cues[0]["end"]
    window_end = current_start + window_secs

    for cue in cues:
        if cue["start"] > window_end:
            if current_texts:
                windows.append({
                    "text": " ".join(current_texts),
                    "start_seconds": current_start,
                    "end_seconds": current_end,
                })
            current_texts = [cue["text"]]
            current_start = cue["start"]
            current_end = cue["end"]
            window_end = current_start + window_secs
        else:
            current_texts.append(cue["text"])
            current_end = cue["end"]

    if current_texts:
        windows.append({
            "text": " ".join(current_texts),
            "start_seconds": current_start,
            "end_seconds": current_end,
        })

    return windows


def clean_segment_batch(segments: list[dict], episode_title: str, guest_name: str) -> list[dict]:
    """
    Send a batch of transcript segments to Claude Haiku for cleanup.
    Returns cleaned segments preserving timestamps.
    """
    # Build a numbered batch for the model to clean
    batch_text = "\n\n".join(
        f"[{i+1}] {seg['text']}" for i, seg in enumerate(segments)
    )

    prompt = f"""You are cleaning auto-generated transcript segments from the podcast "The Diary of a CEO with Steven Bartlett".

Episode: {episode_title}
Guest: {guest_name or "Unknown"}

TASK: Clean each numbered transcript segment. Fix:
- Obvious transcription errors (wrong words, mangled names)
- Missing punctuation (add commas, full stops where natural)
- Speaker names likely garbled (Steven Bartlett, {guest_name or "the guest"})
- Technical terms specific to this episode's topic

RULES:
- Do NOT paraphrase or change the meaning
- Do NOT add content that wasn't there
- Keep each segment roughly the same length
- Return EXACTLY the same number of segments, each starting with [N]
- Preserve contractions and spoken language style

Segments to clean:
{batch_text}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    cleaned_text = response.content[0].text

    # Parse the numbered responses back
    cleaned_segments = []
    for i, seg in enumerate(segments):
        pattern = rf"\[{i+1}\]\s*([\s\S]*?)(?=\[{i+2}\]|\Z)"
        match = re.search(pattern, cleaned_text)
        if match:
            cleaned_content = match.group(1).strip()
        else:
            cleaned_content = seg["text"]  # fallback to original

        cleaned_segments.append({
            "text": cleaned_content,
            "start_seconds": seg["start_seconds"],
            "end_seconds": seg["end_seconds"],
        })

    return cleaned_segments


def clean_transcript(episode: dict, vtt_path: Path) -> list[dict] | None:
    """Full pipeline for one episode's VTT file."""
    print(f"\n  Parsing VTT: {vtt_path.name}")
    cues = parse_vtt(vtt_path)
    if not cues:
        print(f"  WARNING: No cues parsed from {vtt_path}")
        return None

    windows = group_into_windows(cues)
    print(f"  {len(cues)} cues → {len(windows)} windows")

    # Clean in batches of 10 windows
    batch_size = 10
    all_cleaned = []
    guest = episode.get("marquee_guest") or episode.get("guest") or ""

    for i in range(0, len(windows), batch_size):
        batch = windows[i : i + batch_size]
        try:
            cleaned = clean_segment_batch(batch, episode["title"], guest)
            all_cleaned.extend(cleaned)
        except anthropic.RateLimitError:
            print("  Rate limit hit — waiting 30s...")
            time.sleep(30)
            cleaned = clean_segment_batch(batch, episode["title"], guest)
            all_cleaned.extend(cleaned)
        except Exception as e:
            print(f"  Haiku cleanup failed for batch {i//batch_size}: {e}")
            # Fall back to uncleaned windows
            all_cleaned.extend(batch)

        time.sleep(0.5)  # gentle pacing

    return all_cleaned


def main():
    print("=" * 60)
    print("Transcript Cleanup — Step 4 of 7")
    print("=" * 60)

    with open(SELECTED_FILE, encoding="utf-8") as f:
        episodes = json.load(f)

    # Filter to episodes that have VTT files
    to_clean = []
    for ep in episodes:
        ep_dir = TRANSCRIPTS_DIR / ep["id"]
        if ep_dir.exists():
            vtt_files = list(ep_dir.glob("*.vtt"))
            if vtt_files:
                # Skip if already cleaned
                output_path = CLEANED_DIR / f"{ep['id']}.json"
                if output_path.exists():
                    print(f"  [Skip - already cleaned] {ep['title'][:50]}")
                    continue
                to_clean.append((ep, vtt_files[0]))

    if not to_clean:
        print("Nothing to clean. Run 03_fetch_transcripts.py first.")
        sys.exit(0)

    print(f"Episodes to clean: {len(to_clean)}")

    success = 0
    for ep, vtt_path in to_clean:
        print(f"\nCleaning: {ep['title'][:60]}")
        cleaned = clean_transcript(ep, vtt_path)
        if cleaned:
            output_path = CLEANED_DIR / f"{ep['id']}.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2, ensure_ascii=False)
            total_words = sum(len(seg["text"].split()) for seg in cleaned)
            duration_min = (cleaned[-1]["end_seconds"] - cleaned[0]["start_seconds"]) // 60
            print(f"  Saved: {len(cleaned)} segments, ~{total_words} words, {duration_min} min")
            success += 1

    print(f"\n{success}/{len(to_clean)} episodes cleaned.")
    print("Step 4 complete.")


if __name__ == "__main__":
    main()
