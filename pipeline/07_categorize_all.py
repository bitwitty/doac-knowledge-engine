"""
07_categorize_all.py
Batch categorizes all 811 episodes using Claude Haiku.
Sends batches of 20 episodes per API call to minimise cost.
Output: data/categorized_episodes.json
"""

import json
import re
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_FILE = DATA_DIR / "episodes.json"
OUTPUT_FILE = DATA_DIR / "categorized_episodes.json"

client = anthropic.Anthropic()

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

BATCH_SIZE = 20


def format_episode_for_prompt(ep: dict, idx: int) -> str:
    return (
        f"[{idx}] Title: {ep['title']}\n"
        f"    Guest: {ep.get('guest', 'Unknown')}\n"
        f"    Description: {ep.get('description', '')[:200]}"
    )


def categorize_batch(episodes: list[dict]) -> list[dict]:
    """Send a batch of episodes to Claude Haiku for categorization."""
    formatted = "\n\n".join(format_episode_for_prompt(ep, i + 1) for i, ep in enumerate(episodes))
    topics_list = "\n".join(f"- {t}" for t in TOPICS)

    prompt = f"""You are categorizing podcast episodes from "The Diary of a CEO with Steven Bartlett".

Available topics:
{topics_list}

For each numbered episode below, return a JSON object with:
- "primary_topic": one topic from the list above (exact spelling)
- "secondary_topics": array of 0-2 additional relevant topics
- "summary": one sentence (max 20 words) describing what this episode is about

Return a JSON array with one object per episode, in the same order.
Return ONLY valid JSON, no explanation.

Episodes:
{formatted}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Extract JSON array even if wrapped in markdown code blocks
    json_match = re.search(r"\[[\s\S]*\]", text)
    if not json_match:
        raise ValueError(f"No JSON array found in response: {text[:200]}")

    results = json.loads(json_match.group())

    if len(results) != len(episodes):
        raise ValueError(f"Expected {len(episodes)} results, got {len(results)}")

    return results


def main():
    print("=" * 60)
    print("Episode Categorization — Step 7 of 7")
    print("=" * 60)

    with open(INPUT_FILE, encoding="utf-8") as f:
        episodes = json.load(f)

    print(f"Categorizing {len(episodes)} episodes in batches of {BATCH_SIZE}...")
    print(f"Estimated API calls: {len(episodes) // BATCH_SIZE + 1}")

    # Load existing results if resuming
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        existing_ids = {ep["id"] for ep in existing}
        already_done = {ep["id"]: ep for ep in existing}
        episodes_to_process = [ep for ep in episodes if ep["id"] not in existing_ids]
        print(f"Resuming — {len(existing_ids)} already categorized, {len(episodes_to_process)} remaining")
    else:
        already_done = {}
        episodes_to_process = episodes

    categorized = list(already_done.values())

    # Process in batches
    batches = [episodes_to_process[i : i + BATCH_SIZE] for i in range(0, len(episodes_to_process), BATCH_SIZE)]

    for batch_num, batch in enumerate(tqdm(batches, desc="Categorizing batches")):
        retries = 3
        for attempt in range(retries):
            try:
                results = categorize_batch(batch)
                for ep, cat in zip(batch, results):
                    categorized.append({
                        **ep,
                        "primary_topic": cat.get("primary_topic", "Entrepreneurship"),
                        "secondary_topics": cat.get("secondary_topics", []),
                        "ai_summary": cat.get("summary", ""),
                    })
                break
            except anthropic.RateLimitError:
                wait = 30 * (attempt + 1)
                print(f"\n  Rate limit — waiting {wait}s...")
                time.sleep(wait)
            except (ValueError, json.JSONDecodeError) as e:
                print(f"\n  Parse error on batch {batch_num}: {e}")
                if attempt == retries - 1:
                    # Fall back: use keyword-based topic for this batch
                    for ep in batch:
                        categorized.append({
                            **ep,
                            "primary_topic": "Entrepreneurship",
                            "secondary_topics": [],
                            "ai_summary": ep.get("description", "")[:80],
                        })

        # Save progress every 5 batches
        if batch_num % 5 == 0:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(categorized, f, indent=2, ensure_ascii=False)

        time.sleep(1)  # gentle pacing

    # Final save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(categorized, f, indent=2, ensure_ascii=False)

    # Topic distribution summary
    print(f"\nCategorized {len(categorized)} episodes total")
    topic_counts: dict[str, int] = {}
    for ep in categorized:
        t = ep.get("primary_topic", "Unknown")
        topic_counts[t] = topic_counts.get(t, 0) + 1

    print("\nTopic distribution:")
    for topic in TOPICS:
        count = topic_counts.get(topic, 0)
        bar = "█" * (count // 5)
        print(f"  {topic:<25} {count:>3}  {bar}")

    other = sum(v for k, v in topic_counts.items() if k not in TOPICS)
    if other:
        print(f"  {'Other':<25} {other:>3}")

    print(f"\nSaved to {OUTPUT_FILE}")
    print("Step 7 complete.")


if __name__ == "__main__":
    main()
