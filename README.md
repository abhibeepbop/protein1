# Protein1

Protein1 is a grocery planning application that generates an optimised weekly Tesco shopping basket from a user's daily calorie target, daily protein target and weekly budget. Median basket generation time is under 400 ms.

Users may also provide dietary preferences in free text. The system searches a database of 10,986 Tesco products and returns a nutritionally balanced basket with item quantities, prices and nutrition totals.

---

## Features

- **Goal-based basket generation:** users specify daily calories, daily protein and a weekly budget in GBP.
- **Preference-aware search:** semantic search interprets free-text dietary preferences rather than relying on exact keyword matches.
- **Nutritional balance:** each basket must include items from four food groups: protein sources, vegetables or fruit, staples and dairy.
- **Real product data:** approximately 16,000 scraped Tesco product listings, cleaned and classified into quality tiers.
- **User accounts:** Supabase handles authentication and saved baskets.

## Performance

Benchmarked across 8 user profiles, from 1,800 to 3,200 kcal per day and £30 to £70 per week:

| Metric | Result |
|---|---|
| Basket generation time | 380 ms median (without preferences) |
| Solver success rate | 8 of 8 profiles solved to optimality |
| Protein accuracy | 99% of target on average (all within ±6%) |
| Budget compliance | 100% of baskets within budget |
| Basket size | 8 to 15 items, with quantities |

## Architecture

```
User targets and preferences
        |
        v
+--------------------------+
| 1. Semantic retrieval    |  OpenAI embeddings + FAISS (10,986 products, 1536 dimensions)
|    Candidate pool        |  Top 150 matches, up to 40 retained, merged with a 106-item base pool
+------------+-------------+
             |
             v
+--------------------------+
| 2. Integer LP optimiser  |  PuLP / CBC: minimise cost subject to
|    Items and quantities  |  calories within ±3%, protein >= target, spend <= budget,
|                          |  >= 50% animal protein, food-group minimums, per-category limits
+------------+-------------+
             |
             v
+--------------------------+
| 3. LLM curation          |  Swaps up to 30% of protein items to reflect preferences
|                          |  (same category, fixed quantities)
+------------+-------------+
             |
             v
   Final basket with prices, protein and calories
```

### Data Pipeline

1. **Collection:** approximately 16,000 Tesco product records were scraped across five categories: bakery, drinks, food cupboard, frozen and general. Each record includes price, weight, protein and calorie data.
2. **Cleaning:** duplicate and invalid entries were removed, and records with unreliable nutritional data were excluded.
3. **Classification:** GPT-4o-mini classified 10,986 products, in batches of 50, into three tiers:
   - **Tier 1** (755 products): whole, meal-oriented staples
   - **Tier 2** (3,257 products): suitable but less optimal items
   - **Tier 3** (6,757 products): snacks and processed foods
4. **Indexing:** each product was embedded with `text-embedding-3-small` and stored in a FAISS inner-product index.

## Technology Stack

| Layer | Technology |
|---|---|
| Mobile application | React Native, Expo 54, TypeScript, NativeWind |
| Authentication and storage | Supabase |
| Backend | Python, FastAPI, Uvicorn |
| Optimisation | PuLP (CBC integer linear programming solver) |
| Retrieval and AI | LangChain, OpenAI (embeddings and chat models), FAISS |
| Deployment | Railway |

## Project Structure

```
protein1/
├── backend/
│   ├── main.py                  # FastAPI application: retrieval, optimisation and curation
│   ├── openai_embed_foods.py    # FAISS index construction
│   ├── foodtiers.json           # Tiered product database
│   ├── food_index.faiss         # Vector index
│   ├── food_index_items.json    # Mapping from index position to product
│   ├── requirements.txt
│   └── Procfile
├── proteinapp/my-expo-app/
│   ├── App.tsx                  # Main application and basket generation
│   ├── basket.tsx               # Basket view
│   ├── screens/                 # Authentication and saved baskets
│   └── lib/supabase.ts
├── tierlist_ai_pipeline.py      # LLM-based product classification
└── tesco_protein*_analysis.csv  # Scraped product data
```

## Installation

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the `backend` directory:

```
OPENAI_API_KEY=your-key-here
```

Start the server:

```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`.

### Mobile Application

```bash
cd proteinapp/my-expo-app
npm install
npx expo start
```

Set `API_URL` in `App.tsx` to the backend address, and set the Supabase project URL and anon key in `lib/supabase.ts`.

## API Reference

### `GET /generate-basket`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `calories` | integer | Yes | Daily calorie target |
| `protein` | integer | Yes | Daily protein target (g) |
| `budget` | float | Yes | Weekly budget (GBP) |
| `preferences` | string | No | Free-text dietary preferences |

**Example request**

```
GET /generate-basket?calories=2500&protein=180&budget=50&preferences=salmon,no pork
```

**Response:** returns the weekly targets, the selected items (quantity, price, protein, calories and category), aggregate totals, and each total's difference from its target.

## Roadmap

- Improve calorie accuracy following post-optimisation deduplication
- Generate meal and recipe suggestions from basket contents
- Support additional supermarkets
- Add dietary filters (vegetarian, halal, dairy-free)

## License

This project is licensed under the MIT License.
