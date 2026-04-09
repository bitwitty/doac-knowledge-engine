"""
02_select_episodes.py
Selects ~30 demo episodes from the full metadata.
Strategy:
  - Guaranteed slots: 6 marquee guests
  - Fill remaining ~24 slots from topical diversity across 9 categories
  - Uses keyword matching on titles + descriptions to categorise
Output: data/selected_episodes.json
"""

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_FILE = DATA_DIR / "episodes.json"
OUTPUT_FILE = DATA_DIR / "selected_episodes.json"

# Marquee guests — these get guaranteed slots regardless of topic balance
MARQUEE_GUESTS = [
    "Andrew Huberman",
    "Alex Hormozi",
    "Mo Gawdat",
    "Esther Perel",
    "Gabor Maté",
    "Gabor Mate",       # variant spelling
    "Simon Sinek",
]

# Topic taxonomy with keyword signals for matching
TOPIC_KEYWORDS = {
    "Entrepreneurship": [
        "startup", "founder", "business", "entrepreneur", "venture", "company",
        "building", "scale", "product", "CEO", "leadership", "investor",
        "hormozi", "hustle", "agency",
    ],
    "Mental Health": [
        "mental health", "anxiety", "depression", "trauma", "therapy",
        "suicide", "loneliness", "mindset", "burnout", "stress", "emotional",
        "gabor", "self-worth", "wellbeing",
    ],
    "Nutrition & Health": [
        "nutrition", "diet", "food", "gut", "weight", "metabolic", "sleep",
        "exercise", "longevity", "health", "fasting", "protein", "cancer",
        "doctor", "medical",
    ],
    "Neuroscience": [
        "brain", "neuroscience", "dopamine", "habits", "addiction", "focus",
        "cognitive", "memory", "huberman", "neuroplasticity", "nervous system",
        "psychology", "behaviour", "attention",
    ],
    "Relationships": [
        "relationship", "love", "marriage", "dating", "sex", "intimacy",
        "attachment", "partner", "family", "perel", "divorce", "communication",
        "connection",
    ],
    "AI & Technology": [
        "AI", "artificial intelligence", "technology", "robot", "machine learning",
        "gawdat", "future", "tech", "automation", "GPT", "data", "digital",
    ],
    "Money & Investing": [
        "money", "wealth", "invest", "finance", "bitcoin", "crypto", "property",
        "rich", "savings", "debt", "financial", "stocks", "retire",
    ],
    "Creativity & Career": [
        "creative", "career", "art", "music", "film", "comedy", "write",
        "design", "brand", "content", "media", "storytelling", "book",
    ],
    "Spirituality & Meaning": [
        "meaning", "purpose", "spirituality", "mindfulness", "meditation",
        "death", "grief", "philosophy", "happiness", "joy", "ikigai",
        "consciousness", "soul",
    ],
}

# Minimum episodes per topic (for topical diversity)
TARGET_PER_TOPIC = 2
TOTAL_TARGET = 30


def score_episode(episode: dict) -> dict[str, float]:
    """Return topic scores for an episode based on title + description keywords."""
    text = (episode["title"] + " " + episode["description"]).lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        scores[topic] = score
    return scores


def is_marquee_guest(episode: dict) -> str | None:
    """Return the matched marquee guest name if episode features a marquee guest."""
    title_lower = episode["title"].lower()
    desc_lower = episode["description"].lower()
    combined = title_lower + " " + desc_lower
    for guest in MARQUEE_GUESTS:
        if guest.lower() in combined:
            return guest
    return None


def assign_primary_topic(scores: dict[str, float]) -> str:
    if not scores or max(scores.values()) == 0:
        return "Entrepreneurship"  # default
    return max(scores, key=scores.get)


def main():
    print("=" * 60)
    print("Episode Selection — Step 2 of 7")
    print("=" * 60)

    with open(INPUT_FILE, encoding="utf-8") as f:
        episodes = json.load(f)

    print(f"Loaded {len(episodes)} episodes")

    # Filter out episodes shorter than 20 mins (likely trailers/bonus clips)
    episodes = [ep for ep in episodes if ep["duration_seconds"] > 20 * 60]
    print(f"After filtering short episodes: {len(episodes)}")

    # Score all episodes
    for ep in episodes:
        ep["_scores"] = score_episode(ep)
        ep["_primary_topic"] = assign_primary_topic(ep["_scores"])
        ep["_marquee_guest"] = is_marquee_guest(ep)

    selected = []
    selected_ids = set()

    # Phase 1: Guarantee marquee guest episodes
    marquee_found = {}
    for ep in episodes:
        if ep["_marquee_guest"] and ep["_marquee_guest"] not in marquee_found:
            selected.append(ep)
            selected_ids.add(ep["id"])
            marquee_found[ep["_marquee_guest"]] = ep["title"]
            print(f"  [Marquee] {ep['_marquee_guest']}: {ep['title'][:60]}")

    print(f"\nMarquee episodes selected: {len(selected)}")

    # Phase 2: Fill topically — try to get TARGET_PER_TOPIC per category
    topic_counts = {topic: 0 for topic in TOPIC_KEYWORDS}
    for ep in selected:
        topic_counts[ep["_primary_topic"]] = topic_counts.get(ep["_primary_topic"], 0) + 1

    # Iterate episodes most-recent-first (they're already sorted by recency from RSS)
    for ep in episodes:
        if len(selected) >= TOTAL_TARGET:
            break
        if ep["id"] in selected_ids:
            continue
        topic = ep["_primary_topic"]
        if topic_counts.get(topic, 0) < TARGET_PER_TOPIC:
            selected.append(ep)
            selected_ids.add(ep["id"])
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    # Phase 3: If still under target, fill without topic constraint
    for ep in episodes:
        if len(selected) >= TOTAL_TARGET:
            break
        if ep["id"] in selected_ids:
            continue
        selected.append(ep)
        selected_ids.add(ep["id"])

    print(f"\nFinal selection: {len(selected)} episodes")

    # Clean up internal scoring fields before saving
    output = []
    for ep in selected:
        clean = {k: v for k, v in ep.items() if not k.startswith("_")}
        clean["primary_topic"] = ep["_primary_topic"]
        clean["is_marquee"] = ep["_marquee_guest"] is not None
        clean["marquee_guest"] = ep["_marquee_guest"] or ""
        output.append(clean)

    # Print summary by topic
    print("\nTopic breakdown:")
    topic_summary: dict[str, list[str]] = {}
    for ep in output:
        t = ep["primary_topic"]
        topic_summary.setdefault(t, []).append(ep["title"][:50])
    for topic, titles in sorted(topic_summary.items()):
        print(f"  {topic} ({len(titles)})")
        for t in titles:
            print(f"    - {t}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {OUTPUT_FILE}")
    print("Step 2 complete. Review the selection above — edit selected_episodes.json if needed.")


if __name__ == "__main__":
    main()
