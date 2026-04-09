"""
05_chunk.py
Chunks cleaned transcripts into overlapping windows for embedding.
Each chunk carries full metadata for citation generation.

Strategy:
  - Target ~400 tokens per chunk (≈ 300 words)
  - 50-token overlap between consecutive chunks (≈ 35 words)
  - Preserve start/end timestamps for citation timestamps
  - Never split mid-sentence where possible (sentence-boundary aware)

Output: data/chunks.jsonl
Each line: {"id", "episode_id", "episode_title", "guest", "youtube_url",
            "primary_topic", "text", "start_seconds", "end_seconds",
            "chunk_index", "total_chunks"}
"""

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CLEANED_DIR = DATA_DIR / "cleaned_transcripts"
SELECTED_FILE = DATA_DIR / "selected_episodes.json"
OUTPUT_FILE = DATA_DIR / "chunks.jsonl"

TARGET_WORDS = 300   # ≈ 400 tokens
OVERLAP_WORDS = 35   # ≈ 50 tokens


def split_into_sentences(text: str) -> list[str]:
    """Rough sentence splitter for spoken transcript text."""
    # Split on sentence-ending punctuation followed by space + capital
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sentences if s.strip()]


def chunk_episode(segments: list[dict], episode_meta: dict) -> list[dict]:
    """
    Chunk an episode's cleaned transcript segments into overlapping windows.
    segments: list of {text, start_seconds, end_seconds}
    """
    # Flatten all segments into a word-level list with timestamps
    # Each word carries the segment's start/end time
    words_with_time: list[tuple[str, int, int]] = []
    for seg in segments:
        words = seg["text"].split()
        for word in words:
            words_with_time.append((word, seg["start_seconds"], seg["end_seconds"]))

    if not words_with_time:
        return []

    chunks = []
    start_idx = 0
    total_words = len(words_with_time)

    while start_idx < total_words:
        end_idx = min(start_idx + TARGET_WORDS, total_words)

        # Try to extend to a sentence boundary (look ahead up to 30 words)
        if end_idx < total_words:
            look_ahead = min(end_idx + 30, total_words)
            text_so_far = " ".join(w for w, _, _ in words_with_time[start_idx:end_idx])
            for i in range(end_idx, look_ahead):
                word = words_with_time[i][0]
                if word.endswith(".") or word.endswith("?") or word.endswith("!"):
                    end_idx = i + 1
                    break

        chunk_words = words_with_time[start_idx:end_idx]
        text = " ".join(w for w, _, _ in chunk_words)
        start_seconds = chunk_words[0][1]
        end_seconds = chunk_words[-1][2]

        chunk_id = f"{episode_meta['id']}_chunk_{len(chunks):04d}"

        chunks.append({
            "id": chunk_id,
            "episode_id": episode_meta["id"],
            "episode_title": episode_meta["title"],
            "guest": episode_meta.get("marquee_guest") or episode_meta.get("guest", ""),
            "youtube_url": episode_meta.get("youtube_url", ""),
            "primary_topic": episode_meta.get("primary_topic", ""),
            "text": text,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "chunk_index": len(chunks),
            "total_chunks": -1,  # filled in after
        })

        # Advance with overlap; break if we just processed the final words
        if end_idx >= total_words:
            break
        start_idx = end_idx - OVERLAP_WORDS
        if start_idx <= 0:
            start_idx = end_idx  # safety: never go backwards

    # Fill in total_chunks
    for chunk in chunks:
        chunk["total_chunks"] = len(chunks)

    return chunks


def format_timestamp(seconds: int) -> str:
    """Convert seconds to HH:MM:SS for display."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def main():
    print("=" * 60)
    print("Chunking — Step 5 of 7")
    print("=" * 60)

    with open(SELECTED_FILE, encoding="utf-8") as f:
        episodes = {ep["id"]: ep for ep in json.load(f)}

    cleaned_files = sorted(CLEANED_DIR.glob("*.json"))
    if not cleaned_files:
        print("No cleaned transcripts found. Run 04_clean_transcripts.py first.")
        return

    print(f"Chunking {len(cleaned_files)} cleaned transcripts...")

    all_chunks = []
    for cleaned_file in cleaned_files:
        episode_id = cleaned_file.stem
        if episode_id not in episodes:
            print(f"  Warning: {episode_id} not in selected_episodes.json, skipping")
            continue

        with open(cleaned_file, encoding="utf-8") as f:
            segments = json.load(f)

        episode_meta = episodes[episode_id]
        chunks = chunk_episode(segments, episode_meta)
        all_chunks.extend(chunks)

        duration_min = (segments[-1]["end_seconds"] - segments[0]["start_seconds"]) // 60 if segments else 0
        print(f"  {episode_meta['title'][:55]}")
        print(f"    → {len(chunks)} chunks, {duration_min} min, "
              f"~{len(segments)} segments")

    print(f"\nTotal chunks: {len(all_chunks)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"Saved to {OUTPUT_FILE}")

    # Sanity check: show a sample chunk
    if all_chunks:
        sample = all_chunks[len(all_chunks) // 2]
        print(f"\nSample chunk ({sample['episode_title'][:40]}...):")
        print(f"  Time: {format_timestamp(sample['start_seconds'])} → {format_timestamp(sample['end_seconds'])}")
        print(f"  Text: {sample['text'][:200]}...")

    print("\nStep 5 complete.")


if __name__ == "__main__":
    main()
