import json
import os
from dotenv import load_dotenv
from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import JsonOutputParser


load_dotenv()  # loads from .env file automatically

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def get_products_from_db():
    """Load products from products.json and return unique, valid products."""
    filepath = os.path.join(os.path.dirname(__file__), "proteinapp", "data", "products.json")
    with open(filepath, "r", encoding="utf-8") as f:
        products = json.load(f)

    # Remove duplicates by ID
    seen_ids = set()
    unique = []
    for p in products:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            unique.append(p)

    # Filter out bad data
    valid = [p for p in unique if p["price"] > 0 and p["proteinTotal"] <= 500]
    print(f"Loaded {len(valid)} valid products from products.json")
    return valid

def classify_products_into_tiers(products, batch_size=50):
    """Send products to GPT in batches and get tier classifications."""
    prompt = create_tierlist_prompt()
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    chain = prompt | llm | JsonOutputParser()

    tier_list = []
    total_batches = (len(products) + batch_size - 1) // batch_size

    for i in range(0, len(products), batch_size):
        batch = products[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} items)...")

        # Format products for the prompt
        formatted = "\n".join(
            f"ID: {p['id']} | Name: {p['name']} | Price: £{p['price']} | "
            f"Protein: {p['proteinTotal']}g | Calories: {p['caloriesTotal']} | "
            f"Category: {p['category']}"
            for p in batch
        )

        try:
            result = chain.invoke({"products": formatted})
            tier_list.extend(result)
        except Exception as e:
            print(f"  Error in batch {batch_num}: {e}")
            # Default failed items to tier 3
            for p in batch:
                tier_list.append({"id": p["id"], "tier": 3})

    print(f"Classified {len(tier_list)} products total")
    return tier_list
    
def add_tier_info_to_db(tier_list, products):
    """Merge tier classifications into product data and save to foodtiers.json."""
    # Build a lookup: id -> tier
    tier_map = {}
    for item in tier_list:
        tier_map[str(item["id"])] = item["tier"]

    # Sort products into tier buckets
    tiered = {"tier1": [], "tier2": [], "tier3": [], "unclassified": []}

    for p in products:
        tier = tier_map.get(str(p["id"]), None)
        product_with_tier = {**p, "tier": tier}

        if tier == 1:
            tiered["tier1"].append(product_with_tier)
        elif tier == 2:
            tiered["tier2"].append(product_with_tier)
        elif tier == 3:
            tiered["tier3"].append(product_with_tier)
        else:
            tiered["unclassified"].append(product_with_tier)

    # Summary
    print(f"\n--- Classification Summary ---")
    print(f"Tier 1 (Best): {len(tiered['tier1'])} items")
    print(f"Tier 2 (Good): {len(tiered['tier2'])} items")
    print(f"Tier 3 (UPF):  {len(tiered['tier3'])} items")
    print(f"Unclassified:  {len(tiered['unclassified'])} items")

    # Save to foodtiers.json
    output_path = os.path.join(os.path.dirname(__file__), "foodtiers.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tiered, f, indent=2)

    print(f"\nSaved to {output_path}")
    return tiered


def create_tierlist_prompt():
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", 
             "You are a helpful assistant that creates tier lists based from a food database."
             " This database consists of food from tescos. Be objective. Use discretion and think when evaluating items."
             " You must respond with valid JSON only — an array of objects with 'id' and 'tier' fields."
             " tier must be 1, 2, or 3."
            ),
            (
                "human",
                "Classify each of the following products into a tier (1, 2, or 3) based on these rules:\n\n"

                "tier 1 - Highest protein per calorie. These items provide the most 'bang for your buck' for muscle growth without blowing your calorie budget. "
                "example : Chicken Breast, Egg Whites, White Fish (Cod/Tilapia), 5% Fat Mince, any unprocessed vegetable/fruits Organic foods with minimum processing. "
                "If a protein source is a tier 1 food, they should have extremeley high protein per calorie and pound (look at examples i've given). If any other food not nescarrily a main source of protein, it should be "
                "generally not processed and and a high contributer to health, example any unprocessed fruits or vegetables. tier 1 carbs include oats, sweet potatoes etc.\n\n"

                "tier 2 - Great protein sources, not as high protein per pound/calorie as tier 1 but still good. might be a bit processed. Top Items: Whole Eggs, Salmon/Mackerel, "
                "Steak (Sirloin), Chicken Thighs, Tofu, Cottage Cheese. Grade 2 (Minimally Processed): Canned beans, plain yogurt, pasta, cheese. Types of carbs include: White pasta, white bread, couscous. Useful for "
                "easy calories when bulking, but less nutrient-dense than tier 1 carbs.\n\n"

                "tier 3 - Grade 3 (Ultra-Processed - UPF): Flavoured protein shakes, ham/salami, most 'ready-meals,' cereals with 15+ ingredients.\n\n"

                "Products to classify:\n{products}\n\n"
                "Respond with a JSON array like: [{{\"id\": \"12345\", \"tier\": 1}}, ...]\n"
                "JSON only, no other text.",
            ),
        ]
    )
    return prompt


if __name__ == "__main__":
    products = get_products_from_db()
    tier_list = classify_products_into_tiers(products)
    add_tier_info_to_db(tier_list, products)