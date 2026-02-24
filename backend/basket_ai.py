from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import json
import os
from langchain_openai import OpenAI
from langchain.prompts import PromptTemplate
# REMOVED: from langchain.chains import LLMChain (Deprecated)
from dotenv import load_dotenv

load_dotenv()

# Note: Hardcoding keys is risky! Ensure your .env file is working.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-key-here")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load your data
try:
    with open("foodtiers.json", "r", encoding="utf-8") as f:
        food_data = json.load(f)
except FileNotFoundError:
    food_data = {"tier1": [], "tier2": [], "tier3": []}

llm = OpenAI(openai_api_key=OPENAI_API_KEY)

@app.get("/generate-basket")
def generate_basket(
    calories: int = Query(..., description="Target calories per day"),
    protein: int = Query(..., description="Target protein per day (g)"),
    budget: float = Query(..., description="Budget in GBP")
) -> Dict[str, Any]:
    
    candidate_foods = food_data.get("tier1", []) + food_data.get("tier2", []) + food_data.get("tier3", [])
    
    prompt = PromptTemplate(
        input_variables=["foods", "calories", "protein", "budget"],
        template="""
You are a high level elite chef, picking out foods that can best be made into simple, delicious and nutritional meals.
Given the following candidate foods: {foods}, and the constraints of {calories} calories, {protein} grams of protein, and a budget of £{budget}, select a basket of foods that best meets these requirements.
- Meet users nutritional and budget targets.
- Avoid impractical combinations (e.g., only flour, or only oats). 
- Prefer diverse, realistic combinations (e.g., chicken, veggies, grains). That equate to a HEALTHY BALANCED DIET.
- Suggest baskets that can be used for simple, meaningful meals from mostly tier 1.
Output the basket as a JSON array of food names.
"""
    )
    
    # Modern LCEL way (replaces LLMChain)
    chain = prompt | llm
    
    foods_str = ", ".join([item["name"] for item in candidate_foods])
    
    # Invoke the chain
    result = chain.invoke({
        "foods": foods_str, 
        "calories": calories, 
        "protein": protein, 
        "budget": budget
    })
    
    return {"basket": result}

@app.get("/")
def root():
    return {"message": "FastAPI backend is running!"}