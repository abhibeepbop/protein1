from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import json
import os
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
    
    # We pass the full JSON of the foods (names, prices, macros) so the AI can actually calculate
    # We'll take the first 50 to keep it within reason
    foods_context = json.dumps(candidate_foods[:50])

    weekly_calories_target = calories * 7
    weekly_protein_target = protein * 7

    # 1. Define the Parser
    parser = JsonOutputParser()

    # 2. Updated Prompt to allow multiples and request totals
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an elite nutritionist and chef. You always output valid JSON."),
        ("human", """
        Given the following list of foods with their nutritional data and prices: {foods_context}
        
        Create a weekly shopping basket for a user with these targets:
        - Weekly Budget: £{budget}
        - Weekly Calories: {weekly_calories_target}
        - Weekly Protein: {weekly_protein_target}g

        Rules:
        1. You CAN and SHOULD suggest multiple quantities of an item if needed (e.g., 3x Chicken Mince).
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
                {{"name": "Food Name", "quantity": 2, "subtotal_price": 4.50}}
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