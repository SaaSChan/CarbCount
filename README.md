# CarbCount

**Precision macronutrient estimation for Type 1 Diabetics — powered by AI and the Warsaw Method.**

CarbCount isn't another calorie tracker. It's a single-purpose tool built for people whose insulin dosing depends on accurate carb counts. You describe what you're eating in plain English, and CarbCount returns lab-grade macro estimates with absorption timing — in seconds.

## What Makes CarbCount Different

### The Problem With Existing Apps

Every carb counting app makes you search a database, pick the closest match, manually adjust portions, and hope the entry is accurate. For a Type 1 Diabetic, a 15g carb error means a bad blood sugar for hours.

### How CarbCount Solves It

**You type "Chipotle burrito bowl with white rice, chicken, black beans, fajita veggies, tomato salsa, and cheese" and get back:**

- Per-item macro breakdown with sources cited
- Cross-referenced data from 2-3 nutrition databases per item
- Median values (not single-source guesses)
- Confidence ratings on every number
- Warsaw Method absorption profile telling you *when* the glucose will hit

No searching. No scrolling through 47 entries for "chicken breast." No guessing if that database entry matches your portion.

### The Warsaw Method — The Feature No Other App Has

Most carb counters stop at "here are your carbs." CarbCount goes further with the [Warsaw Method](https://pubmed.ncbi.nlm.nih.gov/19175899/) (Pankowska et al., 2009), which calculates how **fat and protein delay glucose absorption**:

- **Fat-Protein Units (FPU):** Every 100 kcal from fat+protein = 1 FPU = 10g additional "slow carbs"
- **Absorption duration:** 1 FPU = 3h, 2 FPU = 4h, 3 FPU = 5h, 4+ FPU = 8h
- **Absorption profile:** Fast, Medium, Slow, or Mixed — with peak timing estimates
- **Actionable notes:** "Consider extended bolus over 5 hours" or "Pre-bolus 15-20 minutes"

A pizza isn't just 60g carbs. It's 60g fast carbs + 35g slow carbs from fat/protein absorbed over 8 hours. CarbCount tells you both.

## Architecture

```
iPhone (PWA) → HTTPS + Bearer Token → Railway (FastAPI) → Claude AI + Web Search
                                            ↓
                                    Structured JSON macros
                                            ↓
                                    Warsaw Method (pure Python)
                                            ↓
                                    SQLite cache + response
```

### Key Design Decisions

**Two-phase computation.** Claude estimates macros using web search and cross-referencing. The backend computes Warsaw absorption with deterministic Python. Same inputs always produce the same absorption math — zero LLM variance in the critical calculations.

**Structured output, not text parsing.** Claude is forced to respond via a tool call with a strict JSON schema. Every response has the exact same shape — item-by-item breakdown, source values seen, confidence ratings, meal totals, and metadata. No regex. No "sometimes it formats it differently."

**Median of multiple sources.** For every food item, Claude searches at least 2 nutrition databases and records all values found. The final estimate uses the statistical median — not whatever the first Google result says. The raw source values are shown for full transparency.

**24-hour query cache.** Identical queries hit SQLite instead of the API. Same question = same answer = no wasted API calls.

**Query normalization.** "Chicken, Rice, Beans" and "beans, chicken, rice" are the same query. Normalized before cache lookup.

**Correction feedback loop.** Found the real nutrition label? Submit a correction. CarbCount tracks accuracy over time — mean error, median error, bias direction, percentage within 5g and 10g.

### Why These Tech Choices

| Choice | Why |
|--------|-----|
| **FastAPI + SQLite** | Single-user tool. No need for Postgres, no auth layer, no row-level security. SQLite on a persistent volume is perfect. |
| **PWA, not native iOS** | Home screen icon, fullscreen mode, offline shell caching — zero Xcode. Works on any phone. |
| **Railway** | Simple deployment, persistent volumes, straightforward secrets, predictable pricing (~$5/month). |
| **Vanilla HTML/CSS/JS** | The UI is a form and a results display. React would be overhead for overhead's sake. |
| **Bearer token auth** | Single user, one secret token, stored in sessionStorage (clears on close). Simple and sufficient. |
| **Temperature 0** | Greedy decoding for consistency. Same meal description → same macro estimate. |

## Stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, Anthropic SDK, SQLAlchemy + aiosqlite
- **Frontend:** Vanilla HTML/CSS/JS as a PWA
- **Database:** SQLite on Railway persistent volume
- **AI:** Claude with web search + structured output
- **Hosting:** Railway (Hobby plan)

## Self-Hosting

### Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)

### Local Setup

```bash
git clone https://github.com/SaaSChan/CarbCount.git
cd CarbCount

# Create your .env
cp .env.example backend/.env
# Edit backend/.env with your ANTHROPIC_API_KEY and a random APP_SECRET_TOKEN

# Install dependencies
pip install -r backend/requirements.txt

# Run
cd backend && uvicorn main:app --reload --port 8000

# Open http://localhost:8000/app/
```

### Generate an App Secret Token

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Deploy to Railway

1. Fork this repo
2. [railway.app/new](https://railway.app/new) → Deploy from GitHub → select your fork
3. Add a persistent volume: Service → Settings → Volumes → mount at `/app/data`
4. Set environment variables:
   - `ANTHROPIC_API_KEY` — your Anthropic key
   - `APP_SECRET_TOKEN` — your generated token
   - `ALLOWED_ORIGIN` — your Railway URL (e.g., `https://carbcount-production.up.railway.app`)
5. Open `https://your-app.up.railway.app/app/` in Safari → Share → Add to Home Screen

### Set a Spending Limit

This app calls the Anthropic API with web search on every new query. Set a monthly spending limit at [console.anthropic.com](https://console.anthropic.com/) → Billing → Spending Limits as a safety net.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Health check |
| `POST` | `/api/estimate` | Yes | Meal query → macros + Warsaw |
| `GET` | `/api/history` | Yes | Past estimates (filterable, paginated) |
| `GET` | `/api/history/{id}` | Yes | Full estimate detail |
| `PATCH` | `/api/history/{id}/correct` | Yes | Submit actual values as correction |
| `GET` | `/api/accuracy` | Yes | Aggregate accuracy statistics |
| `GET` | `/app/` | No | PWA frontend |

## References

1. Pankowska E, et al. "Application of Novel Dual Wave Meal Bolus and Its Impact on Glycated Hemoglobin A1c in Children with Type 1 Diabetes." *Pediatric Diabetes*. 2009;10(5):298-308.
2. Pankowska E, Blazik M. "Bolus Calculator with Nutrition Database Software..." *J Diabetes Sci Technol*. 2010;4(3):571-576. ([PMC2901033](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2901033/))
3. "Modified fat-protein unit algorithm vs carbohydrate counting..." *Nutrients*. 2023. ([PMC10580506](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10580506/))

## License

MIT — use it, fork it, adapt it for your needs. If it helps you manage your diabetes better, that's all that matters.
