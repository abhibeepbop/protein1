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
from langchain_core.prompts import ChatPromptTemplate
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

# --- FAISS semantic index ---
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


def _has_reliable_nutrition(item: dict) -> bool:
    """Filter out items with unreliable nutrition data:
    - weight=100 items that aren't actually 100g packs (per-100g pricing scraped as weight)
    - items with zero calories (data error)
    - items with more than 5000 calories (e.g. 5kg rice bags) — too large for a weekly basket
    """
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
    LIMITS = {
        'chicken': 15, 'beef_pork': 12, 'turkey': 5, 'fish': 12,
        'eggs': 5, 'peas_beans': 8, 'vegetables': 15, 'oats': 3,
        'rice': 8, 'pasta': 8, 'bread': 6, 'dairy_yogurt': 5,
        'dairy_cheese': 5, 'dairy_milk': 4, 'fruit': 6, 'other': 10,
    }

    def get_category(item):
        name_lower = item['name'].lower()
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                return cat
        return 'other'

    counts = {cat: 0 for cat in LIMITS}
    selected = []
    seen = set()

    for item in items:
        if item['name'] in seen:
            continue
        cat = get_category(item)
        if counts.get(cat, 0) < LIMITS.get(cat, 5):
            selected.append(item)
            seen.add(item['name'])
            counts[cat] = counts.get(cat, 0) + 1

    return selected

# Category-balanced base pool — tier 1 items + tier 2 for bread/wraps (bread is mostly tier 2)
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
    """
    Always return a balanced 100-item pool:
      - 60 items from the fixed tier-1 base (staples, veg, meat, dairy)
      - 40 items from FAISS matching the user's preferences, filtered to tier 1 & 2 only
    Deduplication ensures no item appears twice.
    Falls back to first 100 items if FAISS index isn't built yet.
    """
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

    # Cap each category in FAISS results for diversity
    FAISS_CAT_LIMITS = {
        "vegetables": 5, "peas_beans": 3, "fruit": 3,
        "oats": 2, "rice": 2, "pasta": 2, "bread": 2,
    }
    VEG_KEYWORDS     = ["broccoli","carrot","spinach","tomato","cucumber","pepper","onion",
                        "courgette","cabbage","kale","sweet potato","mixed veg","vegetable",
                        "sweetcorn","mushroom","lettuce","celery","leek","bean sprout","beetroot",
                        "greens","beans","watercress"]
    PEAS_KEYWORDS    = ["peas","lentil","chickpea"]
    FRUIT_KEYWORDS   = ["apple","banana","berr","orange","mango","pineapple","grape","melon","strawberr"]
    OAT_KEYWORDS     = ["oat","porridge"]
    RICE_KEYWORDS    = ["rice"]
    PASTA_KEYWORDS   = ["pasta","penne","spaghetti","macaroni","noodle"]
    BREAD_KEYWORDS   = ["bread","wrap","tortilla","pitta","bagel"]

    def faiss_category(name: str) -> str:
        n = name.lower()
        if any(k in n for k in VEG_KEYWORDS):   return "vegetables"
        if any(k in n for k in PEAS_KEYWORDS):  return "peas_beans"
        if any(k in n for k in FRUIT_KEYWORDS): return "fruit"
        if any(k in n for k in OAT_KEYWORDS):   return "oats"
        if any(k in n for k in RICE_KEYWORDS):  return "rice"
        if any(k in n for k in PASTA_KEYWORDS): return "pasta"
        if any(k in n for k in BREAD_KEYWORDS): return "bread"
        return "other"

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
        cat = faiss_category(item["name"])
        limit = FAISS_CAT_LIMITS.get(cat, 40)
        if faiss_counts.get(cat, 0) < limit:
            faiss_results.append(item)
            faiss_counts[cat] = faiss_counts.get(cat, 0) + 1

    print(f"[FAISS] Returned {len(faiss_results)} preference-matched items (category capped):")
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
    """Look up a food item by name in the DB with fuzzy fallback."""
    all_keys = list(food_lookup.keys())
    product = food_lookup.get(name.lower())
    if not product:
        close = difflib.get_close_matches(name.lower(), all_keys, n=1, cutoff=0.85)
        if close:
            product = food_lookup[close[0]]
    return product if product and product.get("caloriesTotal", 0) > 0 else None


def _build_items_data(items: list) -> tuple[list, list]:
    """Convert basket items to LP data format, separating unresolved items."""
    resolved, unresolved = [], []
    for item in items:
        product = _lookup_product(item["name"])
        if product:
            resolved.append({
                "item": item,
                "price": product["price"],
                "protein": product["proteinTotal"],
                "calories": product["caloriesTotal"],
            })
        else:
            unresolved.append(item)
    return resolved, unresolved


def _run_lp(items_data: list, budget_limit: float, cal_target: float = 0,
            prot_target: float = 0, budget_min: float = 0) -> bool:
    """Run LP on items_data and update quantities in place. Returns True if optimal."""
    if not items_data:
        return True
    n = len(items_data)
    prob = LpProblem("stage", LpMinimize)
    qty = [LpVariable(f"q{i}", lowBound=1, upBound=2, cat="Integer") for i in range(n)]
    prob += lpSum(items_data[i]["price"] * qty[i] for i in range(n))
    if cal_target > 0:
        prob += lpSum(items_data[i]["calories"] * qty[i] for i in range(n)) >= cal_target
    if prot_target > 0:
        prob += lpSum(items_data[i]["protein"] * qty[i] for i in range(n)) >= prot_target
    prob += lpSum(items_data[i]["price"] * qty[i] for i in range(n)) <= budget_limit
    if budget_min > 0:
        prob += lpSum(items_data[i]["price"] * qty[i] for i in range(n)) >= budget_min
    prob.solve(PULP_CBC_CMD(msg=0))
    if LpStatus[prob.status] == "Optimal":
        for i, data in enumerate(items_data):
            data["item"]["quantity"] = max(1, int(round(value(qty[i]))))
        return True
    return False


def optimize_quantities(ai_basket: list, weekly_calories: int, weekly_protein: int, budget: float) -> list:
    """
    Three-stage LP pipeline:
      Stage 1 — Meat/poultry: hit 70% of protein target (soft — falls back to 50% if needed)
      Stage 2 — Staples/veg: hit remaining calories with remaining budget
      Stage 3 — Dairy: use leftover budget on dairy items
    """
    STAPLE_CAP_KEYWORDS = ["oat", "porridge", "bread", "wrap", "tortilla", "pitta", "bagel"]

    # Split AI basket by category
    meat_items    = [i for i in ai_basket if i.get("category") == "meat_poultry"]
    staples_items = [i for i in ai_basket if i.get("category") in ("staples", "fruits_veg")]
    dairy_items   = [i for i in ai_basket if i.get("category") == "dairy"]
    other_items   = [i for i in ai_basket if i.get("category") not in
                     ("meat_poultry", "staples", "fruits_veg", "dairy")]

    # ── Stage 1: Meat ─────────────────────────────────────────────
    meat_data, meat_unresolved = _build_items_data(meat_items)
    prot_target_meat = weekly_protein * 0.7
    meat_budget = budget * 0.65

    print(f"\n[STAGE 1 - MEAT] {len(meat_data)} items | protein target: {round(prot_target_meat)}g | budget: £{round(meat_budget,2)}")
    if not _run_lp(meat_data, budget_limit=meat_budget, prot_target=prot_target_meat):
        print("[STAGE 1] Relaxing to 50% protein")
        if not _run_lp(meat_data, budget_limit=meat_budget, prot_target=weekly_protein * 0.5):
            print("[STAGE 1] Could not solve — keeping AI quantities")

    # Cap oats/porridge at qty=1 in meat stage (shouldn't be here but safety net)
    for d in meat_data:
        if any(kw in d["item"]["name"].lower() for kw in STAPLE_CAP_KEYWORDS):
            d["item"]["quantity"] = 1

    meat_spend    = sum(d["price"] * d["item"].get("quantity", 1) for d in meat_data)
    meat_calories = sum(d["calories"] * d["item"].get("quantity", 1) for d in meat_data)
    meat_protein  = sum(d["protein"] * d["item"].get("quantity", 1) for d in meat_data)
    print(f"[STAGE 1] Spend: £{round(meat_spend,2)} | Calories: {round(meat_calories)} | Protein: {round(meat_protein,1)}g")

    # ── Stage 2: Staples & Veg ────────────────────────────────────
    remaining_budget   = budget - meat_spend
    remaining_calories = max(weekly_calories - meat_calories, 0)
    staples_data, staples_unresolved = _build_items_data(staples_items)

    print(f"[STAGE 2 - STAPLES/VEG] {len(staples_data)} items | cal target: {round(remaining_calories)} | budget: £{round(remaining_budget,2)}")
    if not _run_lp(staples_data, budget_limit=remaining_budget * 0.85,
                   cal_target=remaining_calories, budget_min=remaining_budget * 0.4):
        print("[STAGE 2] Relaxing constraints")
        if not _run_lp(staples_data, budget_limit=remaining_budget * 0.85,
                       cal_target=remaining_calories * 0.8):
            print("[STAGE 2] Could not solve — keeping AI quantities")

    # Cap oats/porridge at qty=1
    for d in staples_data:
        if any(kw in d["item"]["name"].lower() for kw in STAPLE_CAP_KEYWORDS):
            d["item"]["quantity"] = 1

    staples_spend    = sum(d["price"] * d["item"].get("quantity", 1) for d in staples_data)
    staples_calories = sum(d["calories"] * d["item"].get("quantity", 1) for d in staples_data)
    print(f"[STAGE 2] Spend: £{round(staples_spend,2)} | Calories: {round(staples_calories)}")

    # ── Stage 3: Dairy ────────────────────────────────────────────
    remaining_budget_2 = remaining_budget - staples_spend
    dairy_data, dairy_unresolved = _build_items_data(dairy_items)

    print(f"[STAGE 3 - DAIRY] {len(dairy_data)} items | budget: £{round(remaining_budget_2,2)}")
    if not _run_lp(dairy_data, budget_limit=remaining_budget_2,
                   budget_min=remaining_budget_2 * 0.5):
        if not _run_lp(dairy_data, budget_limit=remaining_budget_2):
            print("[STAGE 3] Could not solve — keeping AI quantities")

    dairy_spend = sum(d["price"] * d["item"].get("quantity", 1) for d in dairy_data)
    print(f"[STAGE 3] Spend: £{round(dairy_spend,2)}")

    # ── Stage 4: Smart gap fill ───────────────────────────────────
    total_spend    = meat_spend + staples_spend + dairy_spend
    total_calories = (meat_calories + staples_calories +
                      sum(d["calories"] * d["item"].get("quantity", 1) for d in dairy_data))
    total_protein  = (meat_protein +
                      sum(d["protein"] * d["item"].get("quantity", 1) for d in staples_data) +
                      sum(d["protein"] * d["item"].get("quantity", 1) for d in dairy_data))
    leftover_budget = budget - total_spend
    calorie_gap  = weekly_calories - total_calories
    protein_gap  = weekly_protein - total_protein

    print(f"[STAGE 4 - GAP FILL] Leftover: £{round(leftover_budget,2)} | Cal gap: {round(calorie_gap)} | Protein gap: {round(protein_gap,1)}g")

    if leftover_budget > 1:
        if calorie_gap > weekly_calories * 0.05:
            # Bump up quantities of highest-calorie staples already in basket
            print(f"[STAGE 4] Calorie gap {round(calorie_gap)} kcal — increasing staple quantities")
            cal_sorted = sorted(staples_data, key=lambda d: d["calories"], reverse=True)
            for d in cal_sorted:
                if calorie_gap <= 0 or leftover_budget < d["price"]:
                    break
                name_lower = d["item"]["name"].lower()
                if any(kw in name_lower for kw in STAPLE_CAP_KEYWORDS):
                    continue  # never bump oats above qty=1
                current_qty = d["item"].get("quantity", 1)
                if current_qty < 3:
                    d["item"]["quantity"] = current_qty + 1
                    calorie_gap -= d["calories"]
                    leftover_budget -= d["price"]
                    print(f"[STAGE 4] {d['item']['name']} → qty {current_qty + 1}")

        elif protein_gap > weekly_protein * 0.05:
            # Bump up quantities of highest-protein meat already in basket
            print(f"[STAGE 4] Protein gap {round(protein_gap)}g — increasing meat quantities")
            prot_sorted = sorted(meat_data, key=lambda d: d["protein"], reverse=True)
            for d in prot_sorted:
                if protein_gap <= 0 or leftover_budget < d["price"]:
                    break
                current_qty = d["item"].get("quantity", 1)
                if current_qty < 3:
                    d["item"]["quantity"] = current_qty + 1
                    protein_gap -= d["protein"]
                    leftover_budget -= d["price"]
                    print(f"[STAGE 4] {d['item']['name']} → qty {current_qty + 1}")
        else:
            print("[STAGE 4] No significant gap — budget unspent is fine")

    return ([d["item"] for d in meat_data] + meat_unresolved +
            [d["item"] for d in staples_data] + staples_unresolved +
            [d["item"] for d in dairy_data] + dairy_unresolved +
            other_items)


@app.get("/generate-basket")
def generate_basket(
    calories: int = Query(..., description="Target calories per day"),
    protein: int = Query(..., description="Target protein per day (g)"),
    budget: float = Query(..., description="Budget in GBP"),
    preferences: Optional[str] = Query("", description="User dietary preferences e.g. 'more beef' or 'Mediterranean'")
) -> Dict[str, Any]:

    candidate_foods = get_candidate_foods(preferences or "")


    slim_foods = [
        {"name": p["name"], "price": p["price"], "protein": p["proteinTotal"], "calories": p["caloriesTotal"], "tier": p["tier"]}
        for p in candidate_foods
    ]
    foods_context = json.dumps(slim_foods)

    weekly_calories_target = calories * 7
    weekly_protein_target = protein * 7

    parser = JsonOutputParser()

    preferences_line = f"\n        User preferences: {preferences.strip()}\n        Keep these preferences in mind when selecting items." if preferences and preferences.strip() else ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a world-class chef and nutritionist building a weekly meal plan for a real person.
Your primary job is to think like a chef — pick ingredients that work together as complete, delicious meals.
Think breakfast, lunch and dinner for 7 days. Every protein needs a carb and a vegetable to make a proper meal.
You always output valid JSON."""),
        ("human", f"""
        You have the following ingredients available (from a Tesco database):
        {{foods_context}}
        Each item has: name, price (£), protein (g per pack), calories (per pack), tier (1=whole food, 2=lightly processed, 3=ultra-processed).
        Always prefer tier 1. Use tier 2 if needed. Avoid tier 3.
        {preferences_line}

        Build a weekly shopping basket that hits these targets:
        - Weekly Budget: £{{budget}}
        - Weekly Calories: {{weekly_calories_target}} kcal
        - Weekly Protein: {{weekly_protein_target}}g

        THINK LIKE A CHEF FIRST:
        Before picking items, think about what meals you are making this week. For example:
        - If you pick chicken breast → you need rice or pasta + a vegetable to cook with it
        - If you pick beef mince → you need pasta or wraps + a vegetable
        - If you pick tuna → you need pasta or wraps + something to go with it
        - If you pick eggs → you need oats or bread for a proper breakfast
        - If you pick salmon → you need rice or potatoes + a green veg
        Pick ingredients that work together and make real meals people would enjoy.
        Never pick the same vegetable in two forms (e.g. fresh broccoli AND frozen broccoli — pick one).

        THINK LIKE A HUMAN:
        Would a real person actually eat all of this in one week? Even if the numbers fit, be realistic.
        6kg of potatoes is not realistic. 1-2kg of a single vegetable is plenty for a week.
        Spread calories across a variety of foods — do not over-buy one ingredient just to hit the numbers.

        HARD CONSTRAINTS (the system enforces these mathematically — your quantities must satisfy them):
        0. NAMES: Copy item names EXACTLY as written. Do not change a single character.
        1. BUDGET: Total spend must not exceed £{{budget}}. This is a hard limit.
        2. CALORIES: Your basket total must land between 97% and 103% of {{weekly_calories_target}} kcal ({{weekly_calories_target}} ± 3%). Calculate: sum of (calories × quantity) for every item.
        3. PROTEIN: Hit the protein target. Up to 20% over is fine. At least 60% of protein must come from meat, fish or eggs — not from grains or vegetables.
        4. ONE TYPE PER CATEGORY: Pick only ONE oat product, ONE rice product, ONE bread product, ONE yogurt product, ONE type of peas. Do not buy the same thing from two brands.
        5. CATEGORIES: Every item needs a category — "meat_poultry", "fruits_veg", "staples", or "dairy". Include all four categories every time.

        Output strictly in this JSON format:
        {{{{
            "basket": [
                {{{{"name": "Food Name", "quantity": 2, "subtotal_price": 4.50, "category": "meat_poultry"}}}}
            ],
            "totals": {{{{
                "total_calories": 0,
                "total_protein": 0,
                "total_spend": 0
            }}}},
            "comparison": {{{{
                "calories_diff": "diff vs target",
                "protein_diff": "diff vs target",
                "budget_remaining": 0
            }}}}
        }}}}
        """)
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "foods_context": foods_context,
        "weekly_calories_target": weekly_calories_target,
        "weekly_protein_target": weekly_protein_target,
        "budget": budget,
    })

    # LP: tighten quantities to hit calorie/protein targets (upBound=2 keeps it realistic)
    result["basket"] = optimize_quantities(
        result.get("basket", []),
        weekly_calories_target,
        weekly_protein_target,
        budget,
    )

    # Enrich each basket item with real DB prices and nutrition
    all_lookup_keys = list(food_lookup.keys())
    for basket_item in result.get("basket", []):
        name_lower = basket_item["name"].lower()
        product = food_lookup.get(name_lower)

        if not product:
            close = difflib.get_close_matches(name_lower, all_lookup_keys, n=1, cutoff=0.85)
            if close:
                product = food_lookup[close[0]]

        qty = basket_item.get("quantity", 1)
        if product:
            basket_item["subtotal_price"] = round(product["price"] * qty, 2)
            basket_item["protein_g"] = round(product["proteinTotal"] * qty, 1)
            basket_item["calories"] = round(product["caloriesTotal"] * qty)
        else:
            print(f"[LOOKUP MISS] '{basket_item['name']}' — nutrition will be null")
            basket_item["protein_g"] = None
            basket_item["calories"] = None

    # Recalculate totals from real per-item values
    basket = result.get("basket", [])
    result["totals"] = {
        "total_calories": round(sum(i.get("calories") or 0 for i in basket)),
        "total_protein": round(sum(i.get("protein_g") or 0 for i in basket), 1),
        "total_spend": round(sum(i.get("subtotal_price") or 0 for i in basket), 2),
    }

    print(f"\n{'='*50}")
    print(f"[TARGETS]  Calories: {weekly_calories_target} kcal | Protein: {weekly_protein_target}g | Budget: £{budget}")
    print(f"[OUTPUT]   Calories: {result['totals']['total_calories']} kcal | Protein: {result['totals']['total_protein']}g | Spend: £{result['totals']['total_spend']}")
    cal_diff = result['totals']['total_calories'] - weekly_calories_target
    prot_diff = result['totals']['total_protein'] - weekly_protein_target
    spend_left = round(budget - result['totals']['total_spend'], 2)
    print(f"[DIFF]     Calories: {'+' if cal_diff >= 0 else ''}{cal_diff} kcal | Protein: {'+' if prot_diff >= 0 else ''}{prot_diff}g | Budget remaining: £{spend_left}")
    print(f"[BASKET]   {len(basket)} items selected")
    for item in basket:
        print(f"  {item.get('quantity', 1)}x {item['name']} — £{item.get('subtotal_price', '?')} | {item.get('protein_g', '?')}g protein | {item.get('calories', '?')} cal")
    print(f"{'='*50}\n")

    return {
        "user_targets": {
            "weekly_calories": weekly_calories_target,
            "weekly_protein": weekly_protein_target,
            "budget": budget,
        },
        "ai_selection": result,
    }


@app.get("/")
def root():
    return {"message": "FastAPI backend is running!"}
