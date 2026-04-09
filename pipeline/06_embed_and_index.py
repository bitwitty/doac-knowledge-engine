"""
06_embed_and_index.py
Embeds all chunks with Voyage AI voyage-3-large and upserts to Pinecone.

Steps:
  1. Load chunks from data/chunks.jsonl
  2. Batch embed via Voyage API (batch size 128)
  3. Upsert to Pinecone serverless index with full metadata
  4. Verify index stats

Pinecone index config:
  - Name: doac-knowledge-engine (set in .env)
  - Dimension: 1024 (voyage-3-large output dim)
  - Metric: cosine
  - Cloud: AWS us-east-1 (free serverless tier)
"""

import json
import os
import time
from pathlib import Path

import voyageai
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from tqdm import tqdm

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
CHUNKS_FILE = DATA_DIR / "chunks.jsonl"

VOYAGE_MODEL = "voyage-3-large"
EMBED_BATCH_SIZE = 64   # Voyage recommends ≤128; 64 is safe with long texts
PINECONE_BATCH_SIZE = 100
VECTOR_DIMENSION = 1024  # voyage-3-large output dimension


def load_chunks() -> list[dict]:
    chunks = []
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def embed_chunks(chunks: list[dict], voyage_client: voyageai.Client) -> list[list[float]]:
    """Embed all chunks using Voyage AI in batches."""
    texts = [chunk["text"] for chunk in chunks]
    all_embeddings = []

    batches = [texts[i : i + EMBED_BATCH_SIZE] for i in range(0, len(texts), EMBED_BATCH_SIZE)]
    print(f"Embedding {len(texts)} chunks in {len(batches)} batches...")

    for i, batch in enumerate(tqdm(batches, desc="Embedding")):
        retries = 3
        for attempt in range(retries):
            try:
                result = voyage_client.embed(
                    batch,
                    model=VOYAGE_MODEL,
                    input_type="document",
                )
                all_embeddings.extend(result.embeddings)
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise
                wait = 10 * (attempt + 1)
                print(f"\n  Error embedding batch {i}: {e}. Waiting {wait}s...")
                time.sleep(wait)

        time.sleep(0.3)  # gentle rate limiting

    return all_embeddings


def get_or_create_index(pc: Pinecone, index_name: str):
    """Get existing Pinecone index or create it if it doesn't exist."""
    existing = [idx.name for idx in pc.list_indexes()]

    if index_name not in existing:
        print(f"Creating Pinecone index '{index_name}'...")
        pc.create_index(
            name=index_name,
            dimension=VECTOR_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        # Wait for index to be ready
        print("Waiting for index to initialize...")
        while not pc.describe_index(index_name).status["ready"]:
            time.sleep(2)
        print("Index ready.")
    else:
        print(f"Using existing Pinecone index '{index_name}'")

    return pc.Index(index_name)


def build_pinecone_vectors(chunks: list[dict], embeddings: list[list[float]]) -> list[dict]:
    """Build Pinecone upsert records with metadata."""
    vectors = []
    for chunk, embedding in zip(chunks, embeddings):
        # Pinecone metadata values must be str, int, float, bool, or list of str
        vectors.append({
            "id": chunk["id"],
            "values": embedding,
            "metadata": {
                "episode_id": chunk["episode_id"],
                "episode_title": chunk["episode_title"][:200],  # Pinecone metadata limit
                "guest": chunk["guest"][:100],
                "youtube_url": chunk["youtube_url"],
                "primary_topic": chunk["primary_topic"],
                "text": chunk["text"][:1000],  # Store truncated text in metadata for retrieval
                "start_seconds": chunk["start_seconds"],
                "end_seconds": chunk["end_seconds"],
                "chunk_index": chunk["chunk_index"],
            },
        })
    return vectors


def upsert_to_pinecone(index, vectors: list[dict]):
    """Upsert vectors to Pinecone in batches."""
    batches = [vectors[i : i + PINECONE_BATCH_SIZE] for i in range(0, len(vectors), PINECONE_BATCH_SIZE)]
    print(f"Upserting {len(vectors)} vectors in {len(batches)} batches...")

    for batch in tqdm(batches, desc="Upserting"):
        retries = 3
        for attempt in range(retries):
            try:
                index.upsert(vectors=batch)
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise
                print(f"\n  Upsert error: {e}. Retrying...")
                time.sleep(5)

        time.sleep(0.2)


def main():
    print("=" * 60)
    print("Embed & Index — Step 6 of 7")
    print("=" * 60)

    # Validate env vars
    voyage_key = os.getenv("VOYAGE_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME", "doac-knowledge-engine")

    if not voyage_key:
        raise EnvironmentError("VOYAGE_API_KEY not set in .env")
    if not pinecone_key:
        raise EnvironmentError("PINECONE_API_KEY not set in .env")

    # Load chunks
    print(f"Loading chunks from {CHUNKS_FILE}...")
    chunks = load_chunks()
    if not chunks:
        print("No chunks found. Run 05_chunk.py first.")
        return
    print(f"Loaded {len(chunks)} chunks across {len(set(c['episode_id'] for c in chunks))} episodes")

    # Embed
    voyage_client = voyageai.Client(api_key=voyage_key)
    embeddings = embed_chunks(chunks, voyage_client)
    print(f"Generated {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    # Save embeddings locally as backup (useful for re-indexing without re-embedding)
    embeddings_cache = DATA_DIR / "_embeddings_cache.jsonl"
    print(f"Saving embedding cache to {embeddings_cache}...")
    with open(embeddings_cache, "w") as f:
        for chunk, emb in zip(chunks, embeddings):
            f.write(json.dumps({"id": chunk["id"], "embedding": emb}) + "\n")

    # Index to Pinecone
    pc = Pinecone(api_key=pinecone_key)
    index = get_or_create_index(pc, index_name)

    vectors = build_pinecone_vectors(chunks, embeddings)
    upsert_to_pinecone(index, vectors)

    # Verify
    time.sleep(2)  # let Pinecone catch up
    stats = index.describe_index_stats()
    print(f"\nPinecone index stats:")
    print(f"  Total vectors: {stats.total_vector_count}")
    print(f"  Dimension: {stats.dimension}")

    print("\nStep 6 complete. RAG pipeline is ready.")
    print(f"Index: {index_name} | {stats.total_vector_count} vectors searchable")


if __name__ == "__main__":
    main()
