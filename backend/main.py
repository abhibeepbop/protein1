from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, Optional
import json
import os
import difflib
import numpy as np
import faiss
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, value, PULP_CBC_CMD, LpStatus
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  # Still used for FAISS embeddings locally
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

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
llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", google_api_key=GOOGLE_API_KEY)


def _has_reliable_nutrition(item: dict) -> bool:
    """Filter out items where weight=100 but product is clearly not a 100g pack.
    These have proteinTotal/caloriesTotal calculated as per-100g values, making them
    wildly inaccurate for basket nutrition calculations."""
    if item.get("weight", 0) != 100:
        return True
    name_lower = item.get("name", "").lower()
    return "100g" in name_lower or "100 g" in name_lower

# Pre-built balanced base: top tier 1 items with reliable nutrition, deduplicated by name
_base_pool = list({
    item["name"]: item
    for item in all_foods_flat
    if item.get("tier") == 1 and _has_reliable_nutrition(item)
}.values())[:40]


def get_candidate_foods(preferences: str) -> list:
    """
    Always return a balanced 60-item pool:
      - 40 items from the fixed tier-1 base (staples, veg, meat, dairy)
      - 20 items from FAISS matching the user's preferences, filtered to tier 1 & 2 only
    Deduplication ensures no item appears twice.
    Falls back to first 60 items if FAISS index isn't built yet.
    """
    if not USE_FAISS:
        return all_foods_flat[:60]

    query = preferences.strip() if preferences.strip() else "high protein lean meat fish eggs vegetables wholegrains dairy"
    query_vector = np.array([embeddings_model.embed_query(query)], dtype=np.float32)
    faiss.normalize_L2(query_vector)

    # Retrieve more than needed so we have room to filter out tier 3
    _, indices = faiss_index.search(query_vector, 100)
    faiss_results = [
        indexed_items[i]
        for i in indices[0]
        if i < len(indexed_items)
        and indexed_items[i].get("tier", 3) in (1, 2)
        and _has_reliable_nutrition(indexed_items[i])
    ][:20]

    # Merge: base first, then FAISS results, deduplicated by name
    seen = {item["name"] for item in _base_pool}
    combined = list(_base_pool)
    for item in faiss_results:
        if item["name"] not in seen:
            seen.add(item["name"])
            combined.append(item)

    return combined


def optimize_quantities(ai_basket: list, weekly_calories: int, weekly_protein: int, budget: float) -> list:
    """
    Integer linear programming: find the minimum-cost quantities for each AI-selected item
    that meet the weekly calorie and protein targets within budget.
    Falls back to relaxed targets (80%) if infeasible, then keeps AI quantities as last resort.
    """
    all_keys = list(food_lookup.keys())

    # Build per-unit nutritional data from the DB for each item
    items_data = []
    unresolved_items = []
    for item in ai_basket:
        name_lower = item["name"].lower()
        product = food_lookup.get(name_lower)
        if not product:
            close = difflib.get_close_matches(name_lower, all_keys, n=1, cutoff=0.85)
            if close:
                product = food_lookup[close[0]]
        if product and product.get("caloriesTotal", 0) > 0:
            items_data.append({
                "item": item,
                "price": product["price"],
                "protein": product["proteinTotal"],
                "calories": product["caloriesTotal"],
            })
        else:
            unresolved_items.append(item)

    if not items_data:
        return ai_basket

    def _solve(cal_target, prot_target):
        n = len(items_data)
        prob = LpProblem("basket", LpMinimize)
        qty = [LpVariable(f"q{i}", lowBound=1, upBound=6, cat="Integer") for i in range(n)]
        prob += lpSum(items_data[i]["price"] * qty[i] for i in range(n))
        prob += lpSum(items_data[i]["calories"] * qty[i] for i in range(n)) >= cal_target
        prob += lpSum(items_data[i]["protein"] * qty[i] for i in range(n)) >= prot_target
        prob += lpSum(items_data[i]["price"] * qty[i] for i in range(n)) <= budget
        prob.solve(PULP_CBC_CMD(msg=0))
        return prob, qty

    prob, qty = _solve(weekly_calories, weekly_protein)

    if LpStatus[prob.status] == "Optimal":
        print("[LP] Optimal solution found")
        for i, data in enumerate(items_data):
            data["item"]["quantity"] = max(1, int(round(value(qty[i]))))
    else:
        # Relax targets by 20% and retry
        print(f"[LP] {LpStatus[prob.status]} — retrying with relaxed targets")
        prob2, qty2 = _solve(weekly_calories * 0.8, weekly_protein * 0.8)
        if LpStatus[prob2.status] == "Optimal":
            print("[LP] Relaxed solution found")
            for i, data in enumerate(items_data):
                data["item"]["quantity"] = max(1, int(round(value(qty2[i]))))
        else:
            print("[LP] Could not solve — keeping AI quantities")

    return [d["item"] for d in items_data] + unresolved_items


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
        ("system", "You are an elite nutritionist and chef. You always output valid JSON."),
        ("human", f"""
        Given the following list of foods with their nutritional data and prices: {{foods_context}}
        Each food has: name, price (£ per unit), protein (g per unit), calories (per unit), tier (1=best quality, 2=good, 3=ultra-processed).
        Prefer tier 1 foods. Use tier 2 when needed. Avoid tier 3 unless nothing else fits.
        {preferences_line}

        Create a weekly shopping basket for a user with these targets:
        - Weekly Budget: £{{budget}}
        - Weekly Calories: {{weekly_calories_target}}
        - Weekly Protein: {{weekly_protein_target}}g

        Rules:
        0. CRITICAL: You must copy item names EXACTLY as they appear in the list above. Do not rephrase, shorten, or modify any name in any way.
        1. You CAN and SHOULD suggest multiple quantities of an item if needed (e.g., 3x Chicken Mince).
        1a. Each basket item must have a "category" field. Use exactly one of these four values: "meat_poultry", "fruits_veg", "staples", "dairy". Assign the most appropriate category based on the item name.
        2. Do not select only breakfast foods. Ensure the basket contains ingredients for breakfast, lunch, and dinner. Include at least one staple for each meal (e.g., oats or cereal for breakfast, rice or wraps for lunch/dinner, etc.).
        3. Ensure the combination makes for a realistic, healthy, and balanced diet. ALWAYS include items from all four categories: meat/protein, vegetables/fruits, staples (rice/oats/pasta), and dairy/eggs. User preferences should influence the TYPE of protein or meals chosen, not replace entire food groups.
        4. Pick oats and peas only once.
        5. Prioritize value for money.
        6. Meet the budget requirement but do not necessarily spend the entire budget. It's better to be under budget than to go over.
        7. Strictly meet the calorie and protein targets as closely as possible.

        Here are some simple meal ideas to inspire you:
        Tuna salad wraps | Scrambled eggs on toast | Greek yogurt with fruit
        Lentil chili with rice | Stir-fried tofu with veggies and rice
        Chicken breast sandwiches | Protein pancakes (oats, eggs, banana)
        Pasta with lean ground beef | Egg fried rice with peas
        Chickpea and spinach curry | Quesadillas (cheese, beans, chicken)
        Pasta with tuna and sweetcorn | Spaghetti with beef and tomato sauce

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

    # LP: override AI quantities with mathematically optimal values
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
