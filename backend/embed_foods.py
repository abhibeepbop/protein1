import json
import os
import numpy as np
import faiss
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FOODTIERS_PATH = os.path.join(os.path.dirname(__file__), "foodtiers.json")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "food_index.faiss")
ITEMS_PATH = os.path.join(os.path.dirname(__file__), "food_index_items.json")

CATEGORY_LABELS = {
    "food_cupboard": "pantry staple",
    "frozen_foods": "frozen food",
    "bakery": "bakery bread",
    "drinks": "drink beverage",
    "general": "grocery item",
}

TIER_LABELS = {1: "high quality lean protein", 2: "good protein source", 3: "processed food"}

def make_text(item: dict) -> str:
    cat = CATEGORY_LABELS.get(item.get("category", ""), "grocery item")
    tier_desc = TIER_LABELS.get(item.get("tier", 3), "food")
    return f"{item['name']} - {cat} - {tier_desc}"

def build_index():
    with open(FOODTIERS_PATH, encoding="utf-8") as f:
        data = json.load(f)

    all_items = [item for tier_items in data.values() for item in tier_items]
    print(f"Loaded {len(all_items)} items from foodtiers.json")

    texts = [make_text(item) for item in all_items]

    embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)

    batch_size = 500
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embeddings = embeddings_model.embed_documents(batch)
        all_embeddings.extend(batch_embeddings)
        print(f"  Embedded {min(i + batch_size, len(texts))}/{len(texts)} items...")

    vectors = np.array(all_embeddings, dtype=np.float32)
    faiss.normalize_L2(vectors)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    faiss.write_index(index, INDEX_PATH)
    with open(ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_items, f)

    print(f"\nDone. Index saved with {index.ntotal} items.")
    print(f"  {INDEX_PATH}")
    print(f"  {ITEMS_PATH}")

if __name__ == "__main__":
    build_index()
