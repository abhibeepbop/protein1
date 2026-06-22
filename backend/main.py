from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional
import json
import os
import difflib
import numpy as np
import faiss
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, value, PULP_CBC_CMD, LpStatus
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Food data ---
try:
    with open("foodtiers.json", "r", encoding="utf-8") as f:
        food_data = json.load(f)
except FileNotFoundError:
    food_data = {"tier1": [], "tier2": [], "tier3": []}

food_lookup = {
    item["name"].lower(): item
    for tier_items in food_data.values()
    for item in tier_items
}

all_foods_flat = [item for tier_items in food_data.values() for item in tier_items]

# --- FAISS ---
INDEX_PATH = os.path.join(os.path.dirname(__file__), "food_index.faiss")
ITEMS_PATH = os.path.join(os.path.dirname(__file__), "food_index_items.json")

try:
    faiss_index = faiss.read_index(INDEX_PATH)
    with open(ITEMS_PATH, "r", encoding="utf-8") as f:
        indexed_items = json.load(f)
    embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=OPENAI_API_KEY)
    USE_FAISS = True
    print(f"FAISS index loaded — {faiss_index.ntotal} items available")
except Exception as e:
    USE_FAISS = False
    print(f"FAISS index not found, using default selection ({e})")

# --- LLM ---
llm = ChatOpenAI(model="gpt-5.4-mini-2026-03-17", openai_api_key=OPENAI_API_KEY)

# --- Category system ---
CATEGORY_KEYWORDS = {
    'chicken':      ['chicken'],
    'beef_pork':    ['beef', 'pork', 'mince', 'steak', 'lamb'],
    'turkey':       ['turkey'],
    'fish':         ['tuna', 'salmon', 'mackerel', 'cod', 'fish', 'sardine', 'haddock', 'prawn'],
    'eggs':         ['egg'],
    'peas_beans':   ['peas', 'bean', 'lentil', 'chickpea'],
    'vegetables':   ['broccoli', 'carrot', 'spinach', 'tomato', 'cucumber', 'pepper', 'onion',
                     'courgette', 'cabbage', 'kale', 'sweet potato', 'mixed veg', 'vegetables',
                     'sweetcorn', 'mushroom', 'lettuce', 'celery'],
    'oats':         ['oat', 'porridge'],
    'rice':         ['rice'],
    'pasta':        ['pasta', 'penne', 'spaghetti', 'macaroni', 'noodle'],
    'bread':        ['bread', 'wrap', 'tortilla'],
    'dairy_yogurt': ['yogurt', 'yoghurt'],
    'dairy_cheese': ['cheese', 'cottage'],
    'dairy_milk':   ['milk'],
    'fruit':        ['apple', 'banana', 'berr', 'orange', 'mango', 'pineapple'],
}

PROTEIN_CATS = {'chicken', 'beef_pork', 'turkey', 'fish', 'eggs'}
VEG_CATS = {'vegetables', 'peas_beans', 'fruit'}
STAPLE_CATS = {'oats', 'rice', 'pasta', 'bread'}
DAIRY_CATS = {'dairy_yogurt', 'dairy_cheese', 'dairy_milk'}
STAPLE_KEYWORDS = ['oat', 'porridge', 'bread', 'wrap', 'tortilla', 'pitta', 'bagel']

# Maps LP internal categories → frontend category strings
_LP_TO_FRONTEND = {
    'chicken': 'meat_poultry', 'beef_pork': 'meat_poultry',
    'turkey': 'meat_poultry', 'fish': 'meat_poultry', 'eggs': 'meat_poultry',
    'vegetables': 'fruits_veg', 'peas_beans': 'fruits_veg', 'fruit': 'fruits_veg',
    'oats': 'staples', 'rice': 'staples', 'pasta': 'staples', 'bread': 'staples',
    'dairy_yogurt': 'dairy', 'dairy_cheese': 'dairy', 'dairy_milk': 'dairy',
    'other': 'staples',
}


def _get_category(name: str) -> str:
    name_lower = name.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return cat
    return 'other'


def _has_reliable_nutrition(item: dict) -> bool:
    if item.get("caloriesTotal", 0) < 50:
        return False
    if item.get("caloriesTotal", 0) > 5000:
        return False
    if item.get("weight", 0) != 100:
        return True
    name_lower = item.get("name", "").lower()
    return "100g" in name_lower or "100 g" in name_lower


def _build_base_pool(items: list) -> list:
    """Build a category-balanced base pool from tier-1 items."""
    LIMITS = {
        'chicken': 15, 'beef_pork': 12, 'turkey': 5, 'fish': 12,
        'eggs': 5, 'peas_beans': 8, 'vegetables': 15, 'oats': 3,
        'rice': 8, 'pasta': 8, 'bread': 6, 'dairy_yogurt': 5,
        'dairy_cheese': 5, 'dairy_milk': 4, 'fruit': 6, 'other': 10,
    }

    counts = {cat: 0 for cat in LIMITS}
    selected = []
    seen = set()

    for item in items:
        if item['name'] in seen:
            continue
        cat = _get_category(item['name'])
        if counts.get(cat, 0) < LIMITS.get(cat, 5):
            selected.append(item)
            seen.add(item['name'])
            counts[cat] = counts.get(cat, 0) + 1

    return selected


# Category-balanced base pool — tier 1 + tier 2 bread/wraps
_tier1_reliable = [
    item for item in all_foods_flat
    if item.get("tier") == 1 and _has_reliable_nutrition(item)
]
_tier2_bread = [
    item for item in all_foods_flat
    if item.get("tier") == 2 and _has_reliable_nutrition(item)
    and any(kw in item["name"].lower() for kw in ["bread", "wrap", "tortilla", "pitta", "bagel"])
]
_base_pool = _build_base_pool(_tier1_reliable + _tier2_bread)


def get_candidate_foods(preferences: str) -> list:
    """Return a balanced pool: base pool + FAISS preference-matched items."""
    if not USE_FAISS:
        print("[FAISS] NOT active — using first 100 items from foodtiers.json")
        return all_foods_flat[:100]

    if not preferences.strip():
        print(f"[FAISS] No preferences — using base pool only ({len(_base_pool)} items)")
        return _base_pool

    query = preferences.strip()
    print(f"[FAISS] Searching with query: '{query}'")

    query_vector = np.array([embeddings_model.embed_query(query)], dtype=np.float32)
    faiss.normalize_L2(query_vector)
    _, indices = faiss_index.search(query_vector, 150)

    FAISS_CAT_LIMITS = {
        "vegetables": 5, "peas_beans": 3, "fruit": 3,
        "oats": 2, "rice": 2, "pasta": 2, "bread": 2,
    }

    faiss_counts = {}
    faiss_results = []
    for i in indices[0]:
        if len(faiss_results) >= 40:
            break
        if i >= len(indexed_items):
            continue
        item = indexed_items[i]
        if item.get("tier", 3) not in (1, 2) or not _has_reliable_nutrition(item):
            continue
        cat = _get_category(item["name"])
        limit = FAISS_CAT_LIMITS.get(cat, 40)
        if faiss_counts.get(cat, 0) < limit:
            faiss_results.append(item)
            faiss_counts[cat] = faiss_counts.get(cat, 0) + 1

    print(f"[FAISS] Returned {len(faiss_results)} preference-matched items")
    for item in faiss_results:
        print(f"  - {item['name']} (tier {item['tier']})")

    seen = {item["name"] for item in _base_pool}
    combined = list(_base_pool)
    for item in faiss_results:
        if item["name"] not in seen:
            seen.add(item["name"])
            combined.append(item)

    print(f"[FAISS] Final pool: {len(combined)} items ({len(_base_pool)} base + {len(combined) - len(_base_pool)} FAISS unique)")
    return combined


def _lookup_product(name: str) -> dict | None:
    all_keys = list(food_lookup.keys())
    product = food_lookup.get(name.lower())
    if not product:
        close = difflib.get_close_matches(name.lower(), all_keys, n=1, cutoff=0.85)
        if close:
            product = food_lookup[close[0]]
    return product if product and product.get("caloriesTotal", 0) > 0 else None


def lp_select_basket(candidate_pool: list, weekly_calories: int, weekly_protein: int, budget: float) -> list:
    """
    Phase 1: LP selects items AND quantities from the full candidate pool.
    qty[i] ∈ {0, 1, 2} — items with qty=0 are excluded. Never goes infeasible
    because the LP can always satisfy constraints by picking the right mix.
    Objective: minimise cost.
    """
    # Deduplicate pool by name — duplicate entries cause LP to pick the same
    # product twice at different prices, breaking the budget constraint.
    seen_names: set[str] = set()
    deduped_pool = []
    for item in candidate_pool:
        if item['name'] not in seen_names:
            seen_names.add(item['name'])
            deduped_pool.append(item)

    items = [item for item in deduped_pool if _has_reliable_nutrition(item)]
    n = len(items)
    cats = [_get_category(item['name']) for item in items]

    # Max total quantities per LP category (prevents buying 10 chicken packs)
    CATEGORY_MAX_QTY = {
        'chicken': 8, 'beef_pork': 6, 'turkey': 4, 'fish': 6,
        'eggs': 4, 'peas_beans': 4, 'vegetables': 10, 'oats': 2,
        'rice': 4, 'pasta': 4, 'bread': 3, 'dairy_yogurt': 4,
        'dairy_cheese': 4, 'dairy_milk': 4, 'fruit': 6, 'other': 2,
    }

    # Exclude condiments and sauces — low calorie, low protein, waste of budget
    EXCLUDE_KEYWORDS = ['mustard', 'ketchup', 'sauce', 'seasoning', 'dressing',
                        'vinegar', 'mayo', 'syrup', 'jam', 'pickle', 'relish']
    items = [item for item in items if not any(kw in item['name'].lower() for kw in EXCLUDE_KEYWORDS)]
    cats = [_get_category(item['name']) for item in items]
    n = len(items)

    print(f"[LP] Running on pool of {n} items | targets: {weekly_calories} cal, {weekly_protein}g protein, £{budget}")

    prob = LpProblem("basket_select", LpMinimize)

    # qty[i] ∈ {0, 1, 2} for all items
    qty = [LpVariable(f"q{i}", lowBound=0, upBound=2, cat="Integer") for i in range(n)]

    # Objective: minimise cost
    prob += lpSum(items[i]["price"] * qty[i] for i in range(n))

    # Calorie band: 97–103% of target
    prob += lpSum(items[i]["caloriesTotal"] * qty[i] for i in range(n)) >= weekly_calories * 0.97
    prob += lpSum(items[i]["caloriesTotal"] * qty[i] for i in range(n)) <= weekly_calories * 1.03

    # Protein: must hit target
    prob += lpSum(items[i]["proteinTotal"] * qty[i] for i in range(n)) >= weekly_protein

    # Budget: hard ceiling
    prob += lpSum(items[i]["price"] * qty[i] for i in range(n)) <= budget

    # Minimum spend (forces variety — can't hit 85% budget with one item)
    prob += lpSum(items[i]["price"] * qty[i] for i in range(n)) >= budget * 0.85

    # Animal protein: at least 50% of protein target from meat/fish/eggs
    animal_idx = [i for i in range(n) if cats[i] in PROTEIN_CATS]
    if animal_idx:
        prob += lpSum(items[i]["proteinTotal"] * qty[i] for i in animal_idx) >= weekly_protein * 0.5

    # Variety minimums — at least some qty from each food group
    protein_idx = [i for i in range(n) if cats[i] in PROTEIN_CATS]
    veg_idx     = [i for i in range(n) if cats[i] in VEG_CATS]
    staple_idx  = [i for i in range(n) if cats[i] in STAPLE_CATS]
    dairy_idx   = [i for i in range(n) if cats[i] in DAIRY_CATS]

    if protein_idx: prob += lpSum(qty[i] for i in protein_idx) >= 3
    if veg_idx:     prob += lpSum(qty[i] for i in veg_idx) >= 2
    if staple_idx:  prob += lpSum(qty[i] for i in staple_idx) >= 1
    if dairy_idx:   prob += lpSum(qty[i] for i in dairy_idx) >= 1

    # Per-category max quantities
    for cat, max_qty in CATEGORY_MAX_QTY.items():
        cat_idx = [i for i in range(n) if cats[i] == cat]
        if cat_idx:
            prob += lpSum(qty[i] for i in cat_idx) <= max_qty

    prob.solve(PULP_CBC_CMD(msg=0))
    status = LpStatus[prob.status]
    print(f"[LP] Status: {status}")

    basket = []
    for i, item in enumerate(items):
        q = int(round(value(qty[i])))
        if q > 0:
            basket.append({**item, "quantity": q, "lp_category": cats[i]})

    # Dedup: for single-item categories, keep only the highest-qty item
    DEDUP_CATS = {'oats', 'rice', 'pasta', 'bread', 'dairy_milk', 'dairy_yogurt'}
    seen_dedup: dict[str, dict] = {}
    for item in basket:
        cat = item["lp_category"]
        if cat not in DEDUP_CATS:
            continue
        prev = seen_dedup.get(cat)
        if prev is None:
            seen_dedup[cat] = item
        elif item["quantity"] > prev["quantity"] or (
            item["quantity"] == prev["quantity"]
            and item.get("proteinTotal", 0) > prev.get("proteinTotal", 0)
        ):
            prev["quantity"] = 0  # old winner loses
            seen_dedup[cat] = item
        else:
            item["quantity"] = 0  # current item loses

    basket = [item for item in basket if item.get("quantity", 0) > 0]

    print(f"[LP] Selected {len(basket)} items (after dedup)")
    return basket


def ai_curate_basket(lp_basket: list, candidate_pool: list, preferences: str) -> list:
    """
    Phase 2: AI swaps up to 30% of items to match user preferences.
    Quantities are fixed — only item identity can change.
    Same-category swaps only.
    """
    if not preferences or not preferences.strip():
        return lp_basket

    max_swaps = max(1, int(len(lp_basket) * 0.3))

    basket_names = {item["name"] for item in lp_basket}
    basket_cats = {item.get("lp_category", "other") for item in lp_basket}

    # Only allow swaps within protein categories — swapping staples (bread, flour,
    # rice) destroys the LP's calorie guarantee since calorie density varies wildly.
    # Protein items (chicken, beef, fish) have similar cal/pack profiles so swaps
    # don't move the calorie total significantly.
    swappable_cats = PROTEIN_CATS & basket_cats

    # Build swap alternatives: pool items not in basket, protein categories only
    alternatives: dict[str, list] = {}
    for item in candidate_pool:
        if not _has_reliable_nutrition(item):
            continue
        cat = _get_category(item["name"])
        if cat in swappable_cats and item["name"] not in basket_names:
            if cat not in alternatives:
                alternatives[cat] = []
            if len(alternatives[cat]) < 8:
                alternatives[cat].append({"name": item["name"], "price": round(item["price"], 2)})

    basket_summary = [
        {"name": item["name"], "quantity": item["quantity"], "category": item.get("lp_category", "other")}
        for item in lp_basket
        if item.get("lp_category", "other") in swappable_cats
    ]

    messages = [
        SystemMessage(content="You are a food curator. Make small preference-based swaps to a shopping basket. Never change quantities. Output valid JSON only."),
        HumanMessage(content=f"""Current basket (quantities fixed — do not change):
{json.dumps(basket_summary, indent=2)}

User preferences: {preferences.strip()}

Swap up to {max_swaps} items to better match preferences.
Rules:
- Same category only (chicken -> chicken, veg -> veg, etc.)
- Replacement must come from the alternatives list below
- Never change quantities

Available alternatives by category:
{json.dumps(alternatives, indent=2)}

Output JSON: {{"swaps": [{{"from": "exact item name", "to": "exact item name"}}]}}
If no swaps needed: {{"swaps": []}}"""),
    ]

    parser = JsonOutputParser()
    result = parser.parse(llm.invoke(messages).content)

    swaps = result.get("swaps", [])[:max_swaps]
    print(f"[AI] {len(swaps)} swap(s): {[(s['from'], '->', s['to']) for s in swaps]}")

    swap_map = {s["from"]: s["to"] for s in swaps}
    new_basket = []
    for item in lp_basket:
        if item["name"] in swap_map:
            new_name = swap_map[item["name"]]
            new_product = _lookup_product(new_name)
            if new_product:
                cat = _get_category(new_name)
                new_basket.append({**item, "name": new_name, "lp_category": cat})
                print(f"[AI] Swapped: {item['name']} → {new_name}")
            else:
                print(f"[AI] Swap target '{new_name}' not found in DB — keeping original")
                new_basket.append(item)
        else:
            new_basket.append(item)

    return new_basket


@app.get("/generate-basket")
def generate_basket(
    calories: int = Query(..., description="Target calories per day"),
    protein: int = Query(..., description="Target protein per day (g)"),
    budget: float = Query(..., description="Budget in GBP"),
    preferences: Optional[str] = Query("", description="User dietary preferences"),
) -> Dict[str, Any]:

    weekly_calories = calories * 7
    weekly_protein = protein * 7

    # Phase 1: get candidate pool
    candidate_pool = get_candidate_foods(preferences or "")

    # Phase 2: LP selects items and quantities
    basket = lp_select_basket(candidate_pool, weekly_calories, weekly_protein, budget)

    # Phase 3: AI curates (swaps up to 30% for preferences)
    basket = ai_curate_basket(basket, candidate_pool, preferences or "")

    # Enrich with real DB prices and nutrition
    all_lookup_keys = list(food_lookup.keys())
    for item in basket:
        name_lower = item["name"].lower()
        product = food_lookup.get(name_lower)
        if not product:
            close = difflib.get_close_matches(name_lower, all_lookup_keys, n=1, cutoff=0.85)
            if close:
                product = food_lookup[close[0]]

        qty = item.get("quantity", 1)
        lp_cat = item.get("lp_category", "other")
        item["category"] = _LP_TO_FRONTEND.get(lp_cat, "staples")

        if product:
            item["subtotal_price"] = round(product["price"] * qty, 2)
            item["protein_g"] = round(product["proteinTotal"] * qty, 1)
            item["calories"] = round(product["caloriesTotal"] * qty)
        else:
            print(f"[LOOKUP MISS] '{item['name']}' — nutrition will be null")
            item["subtotal_price"] = None
            item["protein_g"] = None
            item["calories"] = None

    # Recalculate totals
    totals = {
        "total_calories": round(sum(i.get("calories") or 0 for i in basket)),
        "total_protein": round(sum(i.get("protein_g") or 0 for i in basket), 1),
        "total_spend": round(sum(i.get("subtotal_price") or 0 for i in basket), 2),
    }

    cal_diff = totals["total_calories"] - weekly_calories
    prot_diff = totals["total_protein"] - weekly_protein
    spend_left = round(budget - totals["total_spend"], 2)

    print(f"\n{'='*50}")
    print(f"[TARGETS]  Calories: {weekly_calories} kcal | Protein: {weekly_protein}g | Budget: £{budget}")
    print(f"[OUTPUT]   Calories: {totals['total_calories']} kcal | Protein: {totals['total_protein']}g | Spend: £{totals['total_spend']}")
    print(f"[DIFF]     Calories: {'+' if cal_diff >= 0 else ''}{cal_diff} kcal | Protein: {'+' if prot_diff >= 0 else ''}{prot_diff}g | Budget remaining: £{spend_left}")
    print(f"[BASKET]   {len(basket)} items selected")
    for item in basket:
        print(f"  {item.get('quantity', 1)}x {item['name']} — £{item.get('subtotal_price', '?')} | {item.get('protein_g', '?')}g protein | {item.get('calories', '?')} cal")
    print(f"{'='*50}\n")

    return {
        "user_targets": {
            "weekly_calories": weekly_calories,
            "weekly_protein": weekly_protein,
            "budget": budget,
        },
        "ai_selection": {
            "basket": basket,
            "totals": totals,
            "comparison": {
                "calories_diff": f"{'+' if cal_diff >= 0 else ''}{cal_diff} kcal",
                "protein_diff": f"{'+' if prot_diff >= 0 else ''}{prot_diff}g",
                "budget_remaining": spend_left,
            },
        },
    }


@app.get("/")
def root():
    return {"message": "FastAPI backend is running!"}
