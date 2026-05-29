from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import json
import os
import difflib
from langchain_openai import ChatOpenAI # Switched to Chat model for better JSON
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv

load_dotenv()

# PRO TIP: Remove the hardcoded key and use os.getenv("OPENAI_API_KEY") 
# after putting your key in the .env file.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-key-here")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    with open("foodtiers.json", "r", encoding="utf-8") as f:
        food_data = json.load(f)
except FileNotFoundError:
    food_data = {"tier1": [], "tier2": [], "tier3": []}

# Name-keyed lookup so we can enrich basket items with per-item nutrition
food_lookup = {
    item["name"].lower(): item
    for tier_items in food_data.values()
    for item in tier_items
}

# Using ChatOpenAI (gpt-4o-mini is cheaper and better at JSON than the old OpenAI class)
llm = ChatOpenAI(model="gpt-4o-mini", openai_api_key=OPENAI_API_KEY)

@app.get("/generate-basket")
def generate_basket(
    calories: int = Query(..., description="Target calories per day"),
    protein: int = Query(..., description="Target protein per day (g)"),
    budget: float = Query(..., description="Budget in GBP")
) -> Dict[str, Any]:
    
    # Combine all food data
    candidate_foods = food_data.get("tier1", []) + food_data.get("tier2", []) + food_data.get("tier3", [])

    # Strip to only what the AI needs — saves ~75% tokens per item, allowing 150 items for same cost as 50
    # Tier is kept so the AI can prioritise quality (tier 1 > tier 2 > tier 3)
    slim_foods = [
        {"name": p["name"], "price": p["price"], "protein": p["proteinTotal"], "calories": p["caloriesTotal"], "tier": p["tier"]}
        for p in candidate_foods[:150]
    ]
    foods_context = json.dumps(slim_foods)

    weekly_calories_target = calories * 7
    weekly_protein_target = protein * 7

    # 1. Define the Parser
    parser = JsonOutputParser()

    # 2. Updated Prompt to allow multiples and request totals
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an elite nutritionist and chef. You always output valid JSON."),
        ("human", """
        Given the following list of foods with their nutritional data and prices: {foods_context}
        Each food has: name, price (£ per unit), protein (g per unit), calories (per unit), tier (1=best quality, 2=good, 3=ultra-processed).
        Prefer tier 1 foods. Use tier 2 when needed. Avoid tier 3 unless nothing else fits.
        
        Create a weekly shopping basket for a user with these targets:
        - Weekly Budget: £{budget}
        - Weekly Calories: {weekly_calories_target}
        - Weekly Protein: {weekly_protein_target}g

        Rules:
        0. CRITICAL: You must copy item names EXACTLY as they appear in the list above. Do not rephrase, shorten, or modify any name in any way.
        1. You CAN and SHOULD suggest multiple quantities of an item if needed (e.g., 3x Chicken Mince).
        1a. Each basket item must have a "category" field. Use exactly one of these four values: "meat_poultry", "fruits_veg", "staples", "dairy". Assign the most appropriate category based on the item name.
        2. Do not select only breakfast foods. Ensure the basket contains ingredients for breakfast, lunch, and dinner. Include at least one staple for each meal (e.g., oats or cereal for breakfast, rice or wraps for lunch/dinner, etc.).
        3. Ensure the combination makes for a realistic, healthy, and balanced diet. Make sure that the combination of items is viable enought that the user can make simple meals out of them (e.g., chicken + rice + veg, not just 7 chicken breasts or chicken burritos or anything simple like that.).
        4. Pick oats and peas only once. 
        5. Prioritize value for money.
        6. Meet the budget requrement but do not necessarily spend the entire budget. It's better to be under budget than to go over.
        7. Strictly meet the calorie and protein targets as closely as possible.
        

         
        Here are some simple meal ideas to inspire you, pick options that can be used to make meals like these:
        Tuna salad wraps (tuna, mayo, lettuce, tortilla)
        Scrambled eggs on whole wheat toast
        Greek yogurt with fruit and granola
        Lentil or bean chili with rice
        Cottage cheese with pineapple or berries
        Stir-fried tofu with frozen veggies and rice
        Turkey or chicken breast sandwiches
        Protein pancakes (oats, eggs, banana)
        Baked potatoes with cottage cheese and beans
        Pasta with tomato sauce and lean ground beef or turkey
        Egg fried rice with peas and carrots
        Chickpea and spinach curry with rice
        Simple quesadillas (cheese, beans, chicken, tortilla)
        Pasta with tuna and sweetcorn (in tomato sauce)
        Whole wheat pasta with pesto and grilled chicken
        Spaghetti with lean ground beef and tomato sauce
        Macaroni with cottage cheese and spinach
        Chicken and veggie stir-fry wraps (tortilla, chicken, frozen veggies)
        Bean and cheese wraps (tortilla, black beans, cheese, salsa)
        Turkey and hummus wraps (tortilla, turkey slices, hummus, lettuce)
        Egg and spinach breakfast wraps (tortilla, scrambled eggs, spinach)
        Pasta salad with chickpeas, cucumber, and feta
        Tuna and egg salad wraps (tortilla, tuna, boiled egg, lettuce, light mayo)
         
        Output strictly in this JSON format:
        {{
            "basket": [
                {{"name": "Food Name", "quantity": 2, "subtotal_price": 4.50, "category": "meat_poultry"}}
            ],
            "totals": {{
                "total_calories": 0,
                "total_protein": 0,
                "total_spend": 0
            }},
            "comparison": {{
                "calories_diff": "diff vs target",
                "protein_diff": "diff vs target",
                "budget_remaining": 0
            }}
        }}
        """)
    ])

    # 3. Build the Chain: Prompt -> LLM -> Parser
    chain = prompt | llm | parser

    result = chain.invoke({
        "foods_context": foods_context,
        "weekly_calories_target": weekly_calories_target,
        "weekly_protein_target": weekly_protein_target,
        "budget": budget
    })

    # Enrich each basket item — override AI-calculated price with real DB price × quantity,
    # and add per-item protein/calorie data from the database
    all_lookup_keys = list(food_lookup.keys())
    for basket_item in result.get("basket", []):
        name_lower = basket_item["name"].lower()
        product = food_lookup.get(name_lower)

        # Fuzzy fallback if exact match fails
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
            basket_item["protein_g"] = None
            basket_item["calories"] = None

    # Recalculate totals from real per-item values — never trust the AI's totals
    basket = result.get("basket", [])
    real_spend = round(sum(i.get("subtotal_price") or 0 for i in basket), 2)
    real_protein = round(sum(i.get("protein_g") or 0 for i in basket), 1)
    real_calories = round(sum(i.get("calories") or 0 for i in basket))
    result["totals"] = {
        "total_calories": real_calories,
        "total_protein": real_protein,
        "total_spend": real_spend,
    }

    return {
        "user_targets": {
            "weekly_calories": weekly_calories_target,
            "weekly_protein": weekly_protein_target,
            "budget": budget
        },
        "ai_selection": result
    }

@app.get("/")
def root():
    return {"message": "FastAPI backend is running!"}