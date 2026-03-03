# CarbCount — Complete Build Spec

## For: Claude Code

Build this entire project from this spec. Work through each file in order. Test locally before preparing for Railway deployment. This is a single-user medical-adjacent tool for a Type 1 Diabetic — accuracy, consistency, and security are the top priorities.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Structure](#2-project-structure)
3. [Backend: Core Logic](#3-backend-core-logic)
4. [Backend: Warsaw Method](#4-backend-warsaw-method)
5. [Backend: Structured Output Schema](#5-backend-structured-output-schema)
6. [Backend: System Prompt](#6-backend-system-prompt)
7. [Backend: API Endpoints](#7-backend-api-endpoints)
8. [Backend: Database](#8-backend-database)
9. [Backend: Security](#9-backend-security)
10. [Backend: Consistency Guarantees](#10-backend-consistency-guarantees)
11. [Frontend: PWA](#11-frontend-pwa)
12. [Deployment: Railway](#12-deployment-railway)
13. [Testing](#13-testing)
14. [References](#14-references)
15. [Future Enhancements (v2+)](#15-future-enhancements)

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                   iPhone (PWA)                        │
│  "Add to Home Screen" — runs fullscreen, app-like    │
│  Stores APP_SECRET_TOKEN in sessionStorage            │
│  Text input → sends query over HTTPS                  │
└──────────────────┬───────────────────────────────────┘
                   │ HTTPS + Bearer Token
                   ▼
┌──────────────────────────────────────────────────────┐
│              Railway (FastAPI Backend)                 │
│                                                       │
│  ┌─────────────┐   ┌─────────────────────────────┐   │
│  │  Security    │   │  /estimate endpoint          │   │
│  │  Middleware  │   │                              │   │
│  │  • Bearer    │──▶│  1. Normalize query          │   │
│  │    auth      │   │  2. Check cache (SQLite)     │   │
│  │  • Rate      │   │  3. If miss → call Claude    │   │
│  │    limiting  │   │  4. Extract structured JSON   │   │
│  │  • CORS      │   │  5. Compute Warsaw (Python)  │   │
│  └─────────────┘   │  6. Cache + return response   │   │
│                     └─────────────────────────────┘   │
│                                                       │
│  ┌──────────┐    ┌──────────────────────────────┐    │
│  │ SQLite   │    │  Environment (Railway Secrets) │    │
│  │ (volume) │    │  • ANTHROPIC_API_KEY           │    │
│  │ • meals  │    │  • APP_SECRET_TOKEN            │    │
│  │ • cache  │    │  • ALLOWED_ORIGIN              │    │
│  │ • fixes  │    └──────────────────────────────┘    │
│  └──────────┘                                        │
│                          │                            │
└──────────────────────────┼────────────────────────────┘
                           │ API call (key in header,
                           │ never in LLM context)
                           ▼
              ┌────────────────────────┐
              │   Anthropic API        │
              │   claude-sonnet-4-5    │
              │   + web_search tool    │
              │   + structured output  │
              │     tool (schema)      │
              └────────────────────────┘
```

### Key Design Decisions

- **Two-phase architecture:** Claude estimates macros (AI + web search). Backend computes Warsaw absorption (deterministic Python). This guarantees reproducible absorption math.
- **SQLite, not Postgres/Supabase.** Single user, simple data. No auth layer, no row-level security, no realtime. SQLite on a Railway persistent volume is perfect.
- **PWA, not native iOS.** Claude Code excels at web tech. PWA gives you a home screen icon, fullscreen mode, and offline caching of the shell — zero Xcode headaches.
- **Railway, not Fly.io.** Simpler deployment, easier persistent volumes, straightforward secrets management, predictable pricing.

### Stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, anthropic SDK, SQLAlchemy + aiosqlite
- **Frontend:** Vanilla HTML/CSS/JS as a PWA (no React needed — the UI is simple)
- **Database:** SQLite on Railway persistent volume
- **Hosting:** Railway (Hobby plan, ~$5/month)
- **AI:** Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) with `web_search_20250305` tool. Can upgrade to Opus 4.6 (`claude-opus-4-6`) by changing one env var if accuracy issues arise.

---

## 2. Project Structure

```
carbcount/
├── backend/
│   ├── main.py                # FastAPI app, routes, startup, CORS, lifespan
│   ├── config.py              # Settings from environment variables
│   ├── security.py            # Auth middleware, rate limiting
│   ├── prompts.py             # System prompt (single source of truth)
│   ├── tools.py               # Structured output tool schema + extraction
│   ├── warsaw.py              # Warsaw Method calculations (pure Python)
│   ├── normalize.py           # Query normalization for caching
│   ├── schemas.py             # Pydantic request/response models
│   ├── database.py            # SQLite async engine + session factory
│   ├── models.py              # SQLAlchemy ORM model
│   ├── crud.py                # Database CRUD operations
│   └── requirements.txt
│
├── frontend/
│   ├── index.html             # Main app shell
│   ├── style.css              # Styles
│   ├── app.js                 # App logic
│   ├── manifest.json          # PWA manifest
│   ├── sw.js                  # Service worker (cache shell for offline)
│   └── icons/
│       ├── icon-192.png       # PWA icon (generate a simple one)
│       └── icon-512.png
│
├── railway.toml               # Railway build configuration
├── Procfile                   # Process command
├── .gitignore
├── .env.example               # Template (never commit real keys)
└── README.md
```

---

## 3. Backend: Core Logic

### `config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Required
    ANTHROPIC_API_KEY: str
    APP_SECRET_TOKEN: str
    
    # Optional with defaults
    ALLOWED_ORIGIN: str = "*"                  # Lock to your Railway URL in prod
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/carbcount.db"
    MODEL: str = "claude-sonnet-4-5-20250929"  # Sonnet is ideal for this task. Swap to "claude-opus-4-6" only if accuracy issues arise.
    MAX_TOKENS: int = 16000
    TEMPERATURE: float = 0.0                   # Greedy decoding for consistency
    API_TIMEOUT: float = 120.0                 # Web search can be slow
    CACHE_HOURS: int = 24                      # Cache window for identical queries
    RATE_LIMIT_PER_HOUR: int = 30
    RATE_LIMIT_PER_DAY: int = 200
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### `main.py` — Core Flow

```python
import time
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from config import settings
from security import AuthMiddleware, RateLimitMiddleware
from database import init_db, get_session
from crud import get_cached_estimate, save_estimate, get_history, apply_correction, get_accuracy_stats
from schemas import EstimateRequest, EstimateResponse, HistoryResponse, CorrectionRequest, CorrectionResponse, AccuracyResponse
from tools import MACRO_RESPONSE_TOOL, extract_macro_response
from warsaw import calculate_warsaw
from normalize import normalize_query
from prompts import SYSTEM_PROMPT

# Initialize Anthropic client
client = anthropic.Anthropic(
    api_key=settings.ANTHROPIC_API_KEY,
    timeout=settings.API_TIMEOUT
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="CarbCount", lifespan=lifespan)

# Middleware (order matters — outermost first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)

# Serve frontend as static files
app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")


@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.MODEL}


@app.post("/api/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest):
    start_time = time.time()
    normalized = normalize_query(request.query)
    
    # 1. Check cache
    async with get_session() as session:
        cached = await get_cached_estimate(session, normalized, hours=settings.CACHE_HOURS)
        if cached:
            return EstimateResponse.from_record(cached, cached=True)
    
    # 2. Build messages for Claude
    user_content = request.query
    if request.user_notes:
        user_content += f"\n\nAdditional context from user: {request.user_notes}"
    
    messages = [{"role": "user", "content": user_content}]
    
    # 3. Call Claude with retry
    macros = None
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=settings.MODEL,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[
                    {"type": "web_search_20250305", "name": "web_search"},
                    MACRO_RESPONSE_TOOL
                ],
                messages=messages
            )
            macros = extract_macro_response(response)
            break
        except ValueError:
            if attempt == max_retries - 1:
                raise HTTPException(
                    status_code=500,
                    detail="Model failed to return structured response after retries"
                )
            # Reinforce tool usage and retry
            messages.append({
                "role": "assistant",
                "content": "I need to provide my estimate using the macro_estimate_response tool."
            })
            messages.append({
                "role": "user", 
                "content": "Please provide your macronutrient estimate now using the macro_estimate_response tool."
            })
    
    # 4. Compute Warsaw Method (deterministic)
    totals = macros["meal_totals"]
    modifier = request.fpu_modifier or 1.0
    
    warsaw = calculate_warsaw(
        net_carbs_g=totals["net_carbs_g"],
        protein_g=totals["protein_g"],
        fat_g=totals["fat_g"],
        fpu_modifier=modifier
    )
    
    # 5. Save to database
    processing_ms = int((time.time() - start_time) * 1000)
    
    async with get_session() as session:
        record = await save_estimate(
            session=session,
            normalized_query=normalized,
            original_query=request.query,
            user_notes=request.user_notes,
            macros=macros,
            warsaw=warsaw,
            fpu_modifier=modifier,
            processing_time_ms=processing_ms
        )
    
    # 6. Return
    return EstimateResponse.from_new(
        record_id=record.id,
        timestamp=record.timestamp,
        query=request.query,
        macros=macros,
        warsaw=warsaw,
        fpu_modifier=modifier,
        processing_time_ms=processing_ms
    )


@app.get("/api/history", response_model=HistoryResponse)
async def history(
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None
):
    async with get_session() as session:
        items, total = await get_history(
            session, limit=min(limit, 100), offset=offset,
            search=search, date_from=date_from, date_to=date_to
        )
    return HistoryResponse(total=total, items=items)


@app.patch("/api/history/{estimate_id}/correct", response_model=CorrectionResponse)
async def correct(estimate_id: str, request: CorrectionRequest):
    async with get_session() as session:
        result = await apply_correction(session, estimate_id, request)
        if not result:
            raise HTTPException(404, "Estimate not found")
    return result


@app.get("/api/accuracy", response_model=AccuracyResponse)
async def accuracy():
    async with get_session() as session:
        return await get_accuracy_stats(session)
```

---

## 4. Backend: Warsaw Method

### `warsaw.py`

This file is **pure Python with zero LLM involvement.** Same inputs always produce same outputs.

```python
"""
Warsaw Method Implementation
Reference: Pańkowska E, Szypowska A, Lipka M, et al.
"Application of Novel Dual Wave Meal Bolus and Its Impact on Glycated
Hemoglobin A1c in Children with Type 1 Diabetes."
Pediatric Diabetes. 2009;10(5):298-308.

Duration chart (Pańkowska 2010, PMC2901033):
  1 FPU → 3 hours
  2 FPU → 4 hours
  3 FPU → 5 hours
  ≥4 FPU → 8 hours

Modified FPU (PMC10580506, 2023):
  Standard: 1 FPU (100 kcal) = 10g carb equivalent
  Modified: 1 FPU (100 kcal) = 5g carb equivalent (fpu_modifier=0.5)
  The modified version reduced hypoglycemia risk in adults on MDI.
"""

from dataclasses import dataclass, asdict
from enum import Enum


class AbsorptionProfile(str, Enum):
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    MIXED = "mixed"


@dataclass
class WarsawResult:
    fpu: float
    fpu_carb_equivalent_g: float
    total_carb_impact_g: float
    absorption_duration_hours: float
    peak_glucose_impact_minutes: int
    profile: str  # Use string for JSON serialization
    notes: str
    
    def to_dict(self) -> dict:
        return asdict(self)


# Warsaw duration lookup — empirically established (Pańkowska 2010)
WARSAW_DURATION = {
    0: 0.0,
    1: 3.0,
    2: 4.0,
    3: 5.0,
}
WARSAW_DURATION_HIGH = 8.0  # ≥4 FPU


def _get_absorption_hours(fpu_rounded: int) -> float:
    """Look up absorption duration from Warsaw chart."""
    if fpu_rounded <= 0:
        return 0.0
    if fpu_rounded in WARSAW_DURATION:
        return WARSAW_DURATION[fpu_rounded]
    return WARSAW_DURATION_HIGH  # ≥4 FPU


def calculate_warsaw(
    net_carbs_g: float,
    protein_g: float,
    fat_g: float,
    fpu_modifier: float = 1.0
) -> WarsawResult:
    """
    Calculate Warsaw Method absorption profile from macronutrients.
    
    Args:
        net_carbs_g: Net carbohydrates (total carbs - fiber)
        protein_g: Protein in grams
        fat_g: Fat in grams
        fpu_modifier: Multiplier for carb equivalents (default 1.0).
                      Use 0.5 for the modified/conservative method.
    
    Returns:
        WarsawResult with all computed values
    """
    # Step 1: Calculate FPU
    # 1g protein = 4 kcal, 1g fat = 9 kcal
    protein_kcal = protein_g * 4.0
    fat_kcal = fat_g * 9.0
    total_fp_kcal = protein_kcal + fat_kcal
    fpu = total_fp_kcal / 100.0
    
    # Step 2: Carb equivalent (1 FPU = 10g, adjusted by modifier)
    fpu_carb_equivalent = fpu * 10.0 * fpu_modifier
    
    # Step 3: Total carb impact = direct carbs + delayed FPU carb equivalent
    total_carb_impact = net_carbs_g + fpu_carb_equivalent
    
    # Step 4: Absorption duration from Warsaw chart
    fpu_rounded = round(fpu)
    absorption_hours = _get_absorption_hours(fpu_rounded)
    
    # Step 5: Peak glucose impact estimation
    # Clinical heuristics based on meal composition:
    #   Pure/mostly carb: peak 30-60 min
    #   Mixed meal: peak 60-90 min
    #   High fat/protein: peak 90-150 min (delayed gastric emptying)
    total_meal_kcal = (net_carbs_g * 4.0) + total_fp_kcal
    fat_kcal_ratio = fat_kcal / max(total_meal_kcal, 1.0)
    
    if net_carbs_g > 0 and fpu < 1.0:
        peak_minutes = 45
        profile = AbsorptionProfile.FAST
    elif fpu < 2.0:
        peak_minutes = 75
        profile = AbsorptionProfile.MEDIUM
    elif fpu < 3.0:
        peak_minutes = 105
        profile = AbsorptionProfile.SLOW
    else:
        peak_minutes = 135
        profile = AbsorptionProfile.SLOW
    
    # Mixed profile: significant carbs AND significant fat/protein
    if net_carbs_g > 20.0 and fpu >= 2.0:
        profile = AbsorptionProfile.MIXED
        peak_minutes = 90  # Dual peak expected
    
    # Edge case: very low carb, high fat/protein
    if net_carbs_g < 5.0 and fpu >= 1.0:
        peak_minutes = max(peak_minutes, 120)
    
    # Step 6: Generate actionable notes
    notes_parts = []
    
    if fpu >= 3.0:
        notes_parts.append(
            f"High fat-protein meal ({fpu:.1f} FPU = {fpu_carb_equivalent:.0f}g carb equivalent). "
            f"Consider extended/dual-wave bolus over {absorption_hours:.0f} hours."
        )
    elif fpu >= 1.0:
        notes_parts.append(
            f"Moderate fat-protein content ({fpu:.1f} FPU = {fpu_carb_equivalent:.0f}g carb equivalent). "
            f"Extended bolus over {absorption_hours:.0f} hours may help prevent late rise."
        )
    else:
        notes_parts.append(
            f"Low fat-protein content ({fpu:.1f} FPU). "
            f"Standard bolus timing should be adequate."
        )
    
    if fat_kcal_ratio > 0.4:
        notes_parts.append(
            "High fat ratio will delay gastric emptying — "
            "expect a delayed and prolonged glucose rise."
        )
    
    if net_carbs_g > 60.0:
        notes_parts.append(
            "High carb load — consider pre-bolusing 15-20 minutes before eating."
        )
    
    if net_carbs_g < 10.0 and fpu >= 2.0:
        notes_parts.append(
            "Low carb, high fat-protein meal. Glucose rise may not appear "
            "for 1.5-3 hours. Monitor for delayed hyperglycemia."
        )
    
    if fpu_modifier != 1.0:
        notes_parts.append(
            f"Using modified FPU factor ({fpu_modifier}x). "
            f"Standard method would estimate {fpu * 10.0:.0f}g carb equivalent."
        )
    
    return WarsawResult(
        fpu=round(fpu, 2),
        fpu_carb_equivalent_g=round(fpu_carb_equivalent, 1),
        total_carb_impact_g=round(total_carb_impact, 1),
        absorption_duration_hours=absorption_hours,
        peak_glucose_impact_minutes=peak_minutes,
        profile=profile.value,
        notes=" ".join(notes_parts)
    )
```

---

## 5. Backend: Structured Output Schema

### `tools.py`

Claude is forced to respond ONLY by calling this tool. This guarantees every response has the exact same JSON shape — zero formatting variance.

```python
"""
Structured output tool for Claude.

Instead of parsing markdown/text, we define a "tool" that Claude must call
as its only valid response. The Anthropic API returns the tool_use block
with perfectly structured JSON matching this schema.
"""


MACRO_RESPONSE_TOOL = {
    "name": "macro_estimate_response",
    "description": (
        "Submit the final macronutrient estimation for the meal. "
        "This is the ONLY way to respond to the user. "
        "You must ALWAYS call this tool as your final action. "
        "Never respond with plain text."
    ),
    "input_schema": {
        "type": "object",
        "required": ["meal_description", "items", "meal_totals", "meta"],
        "properties": {
            "meal_description": {
                "type": "string",
                "description": "Normalized, clear description of the full meal"
            },
            "items": {
                "type": "array",
                "description": "Itemized breakdown — one entry per distinct food component",
                "items": {
                    "type": "object",
                    "required": [
                        "name", "portion",
                        "calories", "total_carbs_g", "fiber_g", "net_carbs_g",
                        "protein_g", "fat_g",
                        "source", "confidence"
                    ],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the individual food item"
                        },
                        "portion": {
                            "type": "string",
                            "description": "Portion size with units (e.g., '1 cup', '4 oz', '1 large')"
                        },
                        "calories": {
                            "type": "number",
                            "description": "Total calories for this item and portion"
                        },
                        "total_carbs_g": {
                            "type": "number",
                            "description": "Total carbohydrates in grams"
                        },
                        "fiber_g": {
                            "type": "number",
                            "description": "Dietary fiber in grams"
                        },
                        "net_carbs_g": {
                            "type": "number",
                            "description": "Net carbs = total_carbs_g - fiber_g"
                        },
                        "protein_g": {
                            "type": "number",
                            "description": "Protein in grams"
                        },
                        "fat_g": {
                            "type": "number",
                            "description": "Total fat in grams"
                        },
                        "source": {
                            "type": "string",
                            "description": "Primary data source used (e.g., 'USDA FoodData Central', 'Chipotle Nutrition Calculator', 'CalorieKing')"
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "high = exact match from official/authoritative source. medium = close match or minor estimation needed. low = significant assumptions or guesswork."
                        },
                        "confidence_note": {
                            "type": "string",
                            "description": "If confidence is medium or low, explain what assumptions were made and why."
                        },
                        "source_values_seen": {
                            "type": "object",
                            "description": "Raw values found across multiple sources BEFORE selecting the median. Include at least 2 data points per macro when possible.",
                            "properties": {
                                "net_carbs_g": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "Net carb values from each source consulted"
                                },
                                "protein_g": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "Protein values from each source consulted"
                                },
                                "fat_g": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "Fat values from each source consulted"
                                }
                            }
                        }
                    }
                }
            },
            "meal_totals": {
                "type": "object",
                "required": [
                    "calories", "total_carbs_g", "fiber_g",
                    "net_carbs_g", "protein_g", "fat_g"
                ],
                "properties": {
                    "calories": {"type": "number", "description": "Sum of all item calories"},
                    "total_carbs_g": {"type": "number", "description": "Sum of all item total carbs"},
                    "fiber_g": {"type": "number", "description": "Sum of all item fiber"},
                    "net_carbs_g": {"type": "number", "description": "Sum of all item net carbs, 1 decimal place"},
                    "protein_g": {"type": "number", "description": "Sum of all item protein, 1 decimal place"},
                    "fat_g": {"type": "number", "description": "Sum of all item fat, 1 decimal place"}
                }
            },
            "meta": {
                "type": "object",
                "required": ["sources_consulted", "clarification_needed"],
                "properties": {
                    "sources_consulted": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "All source names and/or URLs checked during research"
                    },
                    "clarification_needed": {
                        "type": "boolean",
                        "description": "True if input was ambiguous and assumptions were made that the user should verify"
                    },
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific assumptions made (portions, preparation, brand, etc.)"
                    }
                }
            }
        }
    }
}


def extract_macro_response(response) -> dict:
    """
    Extract the structured macro_estimate_response tool call from Claude's response.
    
    Claude may return multiple content blocks (web search results, text, tool calls).
    We iterate to find the specific tool call we defined.
    
    Raises:
        ValueError: If the model did not call the macro_estimate_response tool.
    """
    for block in response.content:
        if hasattr(block, "type") and block.type == "tool_use":
            if block.name == "macro_estimate_response":
                return block.input
    raise ValueError("Model did not return structured macro_estimate_response")
```

---

## 6. Backend: System Prompt

### `prompts.py`

```python
SYSTEM_PROMPT = """You are a precision macronutrient estimation engine for a Type 1 Diabetic. Your estimates directly impact insulin dosing — accuracy is paramount.

You must ALWAYS respond by calling the `macro_estimate_response` tool. Never respond with plain text. Never skip calling the tool.

## YOUR SOLE JOB

Estimate macronutrients (calories, total carbs, fiber, net carbs, protein, fat) for each food item in the user's query. That is ALL you do. Do NOT calculate absorption, FPU, insulin doses, or bolus timing — the backend handles that deterministically.

## ESTIMATION METHODOLOGY

For EACH food item in the query:

### Step 1: Search at least 2 sources per item
Use web search to find macronutrient data from these sources in priority order:
  1. Restaurant's official nutrition page (ALWAYS check this FIRST for any restaurant meal)
  2. USDA FoodData Central (fdc.nal.usda.gov)
  3. Nutrition databases: CalorieKing, Nutritionix, MyFitnessPal

### Step 2: Record ALL values found
Store every value you find across sources in the `source_values_seen` object. You MUST populate this field with at least 2 data points per macro when possible. This is critical for transparency and auditability.

### Step 3: Select the MEDIAN
  - 2 values → average them
  - 3+ values → take the true statistical median
  - 1 value → use it, but set confidence to "medium" and explain in confidence_note
  - 0 values → estimate from the most similar food you CAN find data for, set confidence to "low"

### Step 4: Apply critical reasoning BEFORE finalizing
Consider each of these for every item:
  - Preparation method: fried vs grilled (breading adds carbs, frying adds fat)
  - Hidden macros: sauces, marinades, glazes, dressings, cooking oils
  - Portion context: "bowl" at Chipotle ≠ a homemade bowl. A "large" coffee varies by chain.
  - Regional differences: US vs international serving sizes differ significantly

### Step 5: Calculate net carbs
  net_carbs = total_carbs - dietary_fiber
  Do NOT subtract sugar alcohols unless the user specifically mentions a sugar-free or low-carb product.

## PRECISION RULES
- Round each item's macros to 1 decimal place
- Round meal_totals to 1 decimal place  
- Verify that meal_totals are the correct sum of all items
- If input is ambiguous (e.g., "a burrito" with no restaurant specified), assume standard/default portions, list ALL assumptions in the assumptions array, and set clarification_needed to true
- NEVER guess when you can search. Always search first.
- If a source gives a range (e.g., "25-35g carbs"), use the midpoint (30g)
- Prefer the restaurant's own published nutrition data over any third-party database
- For homemade/generic foods, prefer USDA FoodData Central as the primary source
"""
```

---

## 7. Backend: API Endpoints

See the `main.py` code in Section 3 above. Summary of endpoints:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Health check |
| `POST` | `/api/estimate` | Yes | Primary: query → macros + Warsaw |
| `GET` | `/api/history` | Yes | Past estimates, filterable |
| `PATCH` | `/api/history/{id}/correct` | Yes | Submit real-world correction |
| `GET` | `/api/accuracy` | Yes | Aggregate accuracy statistics |
| `GET` | `/app` | No | Serves the PWA frontend |
| `GET` | `/app/*` | No | Static frontend assets |

### `schemas.py` — Request/Response Models

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


# === Requests ===

class EstimateRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="Food or meal description")
    user_notes: Optional[str] = Field(None, max_length=500, description="Additional context about portions, preparation")
    fpu_modifier: Optional[float] = Field(1.0, ge=0.1, le=2.0, description="FPU carb equivalent multiplier. Default 1.0 (standard). Use 0.5 for conservative/modified method.")


class CorrectionRequest(BaseModel):
    actual_net_carbs_g: Optional[float] = None
    actual_protein_g: Optional[float] = None
    actual_fat_g: Optional[float] = None
    notes: Optional[str] = Field(None, max_length=500)


# === Responses ===

class EstimateResponse(BaseModel):
    id: str
    timestamp: str
    query: str
    cached: bool
    macros: dict          # Full structured output from Claude
    warsaw: dict          # Warsaw calculation results
    processing_time_ms: int
    
    @classmethod
    def from_record(cls, record, cached=False):
        """Build response from a database record."""
        import json
        macros = json.loads(record.macro_response_json)
        warsaw = {
            "fpu": record.fpu,
            "fpu_carb_equivalent_g": record.fpu_carb_equivalent_g,
            "total_carb_impact_g": record.total_carb_impact_g,
            "absorption_duration_hours": record.absorption_hours,
            "peak_glucose_impact_minutes": record.peak_minutes,
            "profile": record.profile_type,
            "notes": record.warsaw_notes,
            "fpu_modifier_used": record.fpu_modifier,
        }
        return cls(
            id=record.id,
            timestamp=record.timestamp.isoformat(),
            query=record.original_query,
            cached=cached,
            macros=macros,
            warsaw=warsaw,
            processing_time_ms=record.processing_time_ms or 0,
        )
    
    @classmethod
    def from_new(cls, record_id, timestamp, query, macros, warsaw, fpu_modifier, processing_time_ms):
        """Build response from fresh computation."""
        return cls(
            id=record_id,
            timestamp=timestamp.isoformat(),
            query=query,
            cached=False,
            macros=macros,
            warsaw={**warsaw.to_dict(), "fpu_modifier_used": fpu_modifier},
            processing_time_ms=processing_time_ms,
        )


class HistoryItem(BaseModel):
    id: str
    timestamp: str
    query: str
    calories: Optional[float]
    net_carbs_g: float
    protein_g: float
    fat_g: float
    fpu: Optional[float]
    profile: Optional[str]
    has_correction: bool


class HistoryResponse(BaseModel):
    total: int
    items: list[HistoryItem]


class CorrectionResponse(BaseModel):
    id: str
    original: dict
    corrected: dict
    delta: dict
    notes: Optional[str]


class AccuracyResponse(BaseModel):
    total_estimates: int
    total_corrected: int
    carb_accuracy: Optional[dict]
    worst_categories: list[dict]
```

---

## 8. Backend: Database

### `models.py`

```python
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Estimate(Base):
    __tablename__ = "estimates"
    
    id = Column(String, primary_key=True)                    # "est_" + uuid4 hex[:12]
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    normalized_query = Column(String, nullable=False, index=True)
    original_query = Column(Text, nullable=False)
    user_notes = Column(Text, nullable=True)
    
    # Full Claude response
    macro_response_json = Column(Text, nullable=False)
    
    # Extracted totals (for fast queries without deserializing JSON)
    calories = Column(Float)
    total_carbs_g = Column(Float, nullable=False)
    fiber_g = Column(Float)
    net_carbs_g = Column(Float, nullable=False)
    protein_g = Column(Float, nullable=False)
    fat_g = Column(Float, nullable=False)
    
    # Warsaw results
    fpu = Column(Float)
    fpu_carb_equivalent_g = Column(Float)
    total_carb_impact_g = Column(Float)
    absorption_hours = Column(Float)
    peak_minutes = Column(Integer)
    profile_type = Column(String)
    warsaw_notes = Column(Text)
    fpu_modifier = Column(Float, default=1.0)
    
    # Performance
    processing_time_ms = Column(Integer)
    cached = Column(Boolean, default=False)
    
    # Corrections
    corrected_net_carbs_g = Column(Float, nullable=True)
    corrected_protein_g = Column(Float, nullable=True)
    corrected_fat_g = Column(Float, nullable=True)
    correction_notes = Column(Text, nullable=True)
    corrected_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_timestamp", timestamp.desc()),
        Index("idx_normalized_query", normalized_query),
        Index("idx_corrected", corrected_at),
    )
```

### `database.py`

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from config import settings
from models import Base

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@asynccontextmanager
async def get_session():
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### `normalize.py`

```python
"""Query normalization for consistent cache matching."""

import re

def normalize_query(query: str) -> str:
    """
    Normalize a food query for cache key matching.
    
    Rules:
      - Lowercase
      - Strip leading/trailing whitespace
      - Collapse multiple spaces to single space
      - Sort comma-separated items (order independence)
      - Remove common filler words that don't affect nutrition
    
    "Chicken, Rice, Beans" == "beans, chicken, rice"
    "Two slices of  pepperoni pizza" == "two slices of pepperoni pizza"
    """
    # Lowercase and strip
    normalized = query.lower().strip()
    
    # Collapse whitespace
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Sort comma-separated items for order independence
    if ',' in normalized:
        parts = [p.strip() for p in normalized.split(',')]
        parts = [p for p in parts if p]  # Remove empty parts
        normalized = ', '.join(sorted(parts))
    
    return normalized
```

### `crud.py`

```python
"""Database CRUD operations."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import Estimate
from schemas import CorrectionRequest
from warsaw import WarsawResult


def _generate_id() -> str:
    return f"est_{uuid.uuid4().hex[:12]}"


async def get_cached_estimate(
    session: AsyncSession,
    normalized_query: str,
    hours: int = 24
) -> Optional[Estimate]:
    """Return cached estimate if an identical normalized query exists within the time window."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await session.execute(
        select(Estimate)
        .where(
            and_(
                Estimate.normalized_query == normalized_query,
                Estimate.timestamp >= cutoff
            )
        )
        .order_by(Estimate.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def save_estimate(
    session: AsyncSession,
    normalized_query: str,
    original_query: str,
    user_notes: Optional[str],
    macros: dict,
    warsaw: WarsawResult,
    fpu_modifier: float,
    processing_time_ms: int
) -> Estimate:
    """Save a new estimate to the database."""
    totals = macros["meal_totals"]
    
    record = Estimate(
        id=_generate_id(),
        timestamp=datetime.utcnow(),
        normalized_query=normalized_query,
        original_query=original_query,
        user_notes=user_notes,
        macro_response_json=json.dumps(macros),
        calories=totals.get("calories"),
        total_carbs_g=totals["total_carbs_g"],
        fiber_g=totals.get("fiber_g"),
        net_carbs_g=totals["net_carbs_g"],
        protein_g=totals["protein_g"],
        fat_g=totals["fat_g"],
        fpu=warsaw.fpu,
        fpu_carb_equivalent_g=warsaw.fpu_carb_equivalent_g,
        total_carb_impact_g=warsaw.total_carb_impact_g,
        absorption_hours=warsaw.absorption_duration_hours,
        peak_minutes=warsaw.peak_glucose_impact_minutes,
        profile_type=warsaw.profile,
        warsaw_notes=warsaw.notes,
        fpu_modifier=fpu_modifier,
        processing_time_ms=processing_time_ms,
    )
    
    session.add(record)
    await session.flush()
    return record


async def get_history(
    session: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Get paginated estimate history with optional filters."""
    query = select(Estimate)
    count_query = select(func.count(Estimate.id))
    
    filters = []
    if search:
        filters.append(Estimate.original_query.ilike(f"%{search}%"))
    if date_from:
        filters.append(Estimate.timestamp >= datetime.fromisoformat(date_from))
    if date_to:
        filters.append(Estimate.timestamp <= datetime.fromisoformat(date_to))
    
    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))
    
    total_result = await session.execute(count_query)
    total = total_result.scalar()
    
    result = await session.execute(
        query.order_by(Estimate.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    records = result.scalars().all()
    
    items = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "query": r.original_query,
            "calories": r.calories,
            "net_carbs_g": r.net_carbs_g,
            "protein_g": r.protein_g,
            "fat_g": r.fat_g,
            "fpu": r.fpu,
            "profile": r.profile_type,
            "has_correction": r.corrected_at is not None,
        }
        for r in records
    ]
    
    return items, total


async def apply_correction(
    session: AsyncSession,
    estimate_id: str,
    correction: CorrectionRequest
) -> Optional[dict]:
    """Apply a real-world correction to an estimate."""
    result = await session.execute(
        select(Estimate).where(Estimate.id == estimate_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        return None
    
    original = {
        "net_carbs_g": record.net_carbs_g,
        "protein_g": record.protein_g,
        "fat_g": record.fat_g,
    }
    
    corrected = {}
    delta = {}
    
    if correction.actual_net_carbs_g is not None:
        record.corrected_net_carbs_g = correction.actual_net_carbs_g
        corrected["net_carbs_g"] = correction.actual_net_carbs_g
        delta["net_carbs_g"] = round(correction.actual_net_carbs_g - record.net_carbs_g, 1)
    
    if correction.actual_protein_g is not None:
        record.corrected_protein_g = correction.actual_protein_g
        corrected["protein_g"] = correction.actual_protein_g
        delta["protein_g"] = round(correction.actual_protein_g - record.protein_g, 1)
    
    if correction.actual_fat_g is not None:
        record.corrected_fat_g = correction.actual_fat_g
        corrected["fat_g"] = correction.actual_fat_g
        delta["fat_g"] = round(correction.actual_fat_g - record.fat_g, 1)
    
    record.correction_notes = correction.notes
    record.corrected_at = datetime.utcnow()
    
    await session.flush()
    
    return {
        "id": estimate_id,
        "original": original,
        "corrected": corrected,
        "delta": delta,
        "notes": correction.notes,
    }


async def get_accuracy_stats(session: AsyncSession) -> dict:
    """Compute aggregate accuracy stats from corrected estimates."""
    # Total counts
    total_result = await session.execute(select(func.count(Estimate.id)))
    total_estimates = total_result.scalar()
    
    corrected_result = await session.execute(
        select(func.count(Estimate.id)).where(Estimate.corrected_at.isnot(None))
    )
    total_corrected = corrected_result.scalar()
    
    if total_corrected == 0:
        return {
            "total_estimates": total_estimates,
            "total_corrected": 0,
            "carb_accuracy": None,
            "worst_categories": [],
        }
    
    # Get all corrected estimates for analysis
    result = await session.execute(
        select(Estimate).where(
            and_(
                Estimate.corrected_at.isnot(None),
                Estimate.corrected_net_carbs_g.isnot(None)
            )
        )
    )
    records = result.scalars().all()
    
    if not records:
        return {
            "total_estimates": total_estimates,
            "total_corrected": total_corrected,
            "carb_accuracy": None,
            "worst_categories": [],
        }
    
    errors = [abs(r.corrected_net_carbs_g - r.net_carbs_g) for r in records]
    signed_errors = [r.corrected_net_carbs_g - r.net_carbs_g for r in records]
    
    errors_sorted = sorted(errors)
    n = len(errors_sorted)
    median_error = errors_sorted[n // 2] if n % 2 == 1 else (errors_sorted[n // 2 - 1] + errors_sorted[n // 2]) / 2
    mean_error = sum(errors) / n
    mean_signed = sum(signed_errors) / n
    within_5 = sum(1 for e in errors if e <= 5.0) / n * 100
    within_10 = sum(1 for e in errors if e <= 10.0) / n * 100
    
    bias_direction = "overestimation" if mean_signed < 0 else "underestimation"
    
    return {
        "total_estimates": total_estimates,
        "total_corrected": total_corrected,
        "carb_accuracy": {
            "mean_absolute_error_g": round(mean_error, 1),
            "median_absolute_error_g": round(median_error, 1),
            "bias": f"{mean_signed:+.1f}g ({bias_direction})",
            "within_5g_pct": round(within_5, 1),
            "within_10g_pct": round(within_10, 1),
        },
        "worst_categories": [],  # v2: cluster by food type and compute per-category accuracy
    }
```

---

## 9. Backend: Security

### `security.py`

```python
"""
Security middleware for CarbCount.

Three layers:
  1. Bearer token authentication (keeps unauthorized users out)
  2. Rate limiting (prevents runaway usage even with valid auth)
  3. CORS (locks down cross-origin requests in production)

The Anthropic API key is NEVER exposed to the LLM context or any client.
It lives only in environment variables (Railway secrets in production).
"""

import time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import settings


# Paths that do NOT require authentication
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json"}
PUBLIC_PREFIXES = ("/app",)  # Frontend static files


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token on all /api/ routes."""
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Skip auth for public paths
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)
        
        # Skip auth for non-API paths
        if not path.startswith("/api/"):
            return await call_next(request)
        
        # Validate Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {settings.APP_SECRET_TOKEN}":
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized. Provide a valid Bearer token."}
            )
        
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting.
    
    Limits:
      - 30 requests per hour to /api/estimate
      - 200 requests per day to /api/estimate
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.hourly_requests: dict[str, list[float]] = defaultdict(list)
        self.daily_requests: dict[str, list[float]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        # Only rate limit the expensive endpoint
        if request.url.path != "/api/estimate" or request.method != "POST":
            return await call_next(request)
        
        now = time.time()
        client_ip = request.client.host if request.client else "unknown"
        
        # Clean old entries
        hour_ago = now - 3600
        day_ago = now - 86400
        self.hourly_requests[client_ip] = [t for t in self.hourly_requests[client_ip] if t > hour_ago]
        self.daily_requests[client_ip] = [t for t in self.daily_requests[client_ip] if t > day_ago]
        
        # Check limits
        if len(self.hourly_requests[client_ip]) >= settings.RATE_LIMIT_PER_HOUR:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Maximum {settings.RATE_LIMIT_PER_HOUR} estimates per hour",
                    "retry_after_seconds": int(3600 - (now - self.hourly_requests[client_ip][0]))
                }
            )
        
        if len(self.daily_requests[client_ip]) >= settings.RATE_LIMIT_PER_DAY:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Daily rate limit exceeded",
                    "detail": f"Maximum {settings.RATE_LIMIT_PER_DAY} estimates per day"
                }
            )
        
        # Record this request
        self.hourly_requests[client_ip].append(now)
        self.daily_requests[client_ip].append(now)
        
        return await call_next(request)
```

### Security Summary

| Layer | What it does | Where |
|-------|-------------|-------|
| **Bearer Token** | Rejects requests without your secret token | `security.py` |
| **Rate Limiting** | 30/hr, 200/day on `/api/estimate` | `security.py` |
| **CORS** | Restricts cross-origin requests to your domain | `main.py` |
| **Railway Secrets** | API keys encrypted at rest, injected at runtime | Railway dashboard |
| **HTTPS** | All traffic encrypted in transit | Railway default |
| **Anthropic Spending Limit** | Hard monthly cap as final safety net | Anthropic dashboard |

**Post-deploy:** Set `ALLOWED_ORIGIN` to your Railway URL (e.g., `https://carbcount.up.railway.app`).

---

## 10. Backend: Consistency Guarantees

| Layer | Mechanism | Variance eliminated |
|-------|-----------|---------------------|
| `temperature: 0` | Greedy decoding | Random sampling variance |
| Structured tool schema | Must output exact JSON fields/types | Format/structure variance |
| Query normalization | `"Chicken, Rice" == "rice, chicken"` | Trivial input differences |
| 24-hour cache | Same normalized query → same DB row | ALL variance (cache hit) |
| Deterministic Warsaw | Pure Python math | Same macros → identical absorption |

---

## 11. Frontend: PWA

A simple, clean PWA served as static files by FastAPI. "Add to Home Screen" on iPhone for an app-like experience.

### Design Direction

**Aesthetic:** Medical-instrument minimalism. Dark background, high-contrast data, monospace numbers. Precise and trustworthy — this is a health tool.

**Color palette:**
- Background: `#0a0f1a` (near-black navy)
- Surface/cards: `#141b2d`
- Primary accent: `#22d3ee` (cyan)
- Warning: `#fbbf24` (amber for low confidence)
- Text primary: `#f1f5f9`
- Text secondary: `#94a3b8`
- Success: `#34d399`
- Borders: `#1e293b`

**Typography:**
- Numbers: `"JetBrains Mono", "Fira Code", monospace`
- Labels: `"DM Sans", system-ui, sans-serif`

### Views

**1. Token Entry (once per session)**
- Input: "Enter your access token"
- Stored in `sessionStorage` (clears on close — security choice)

**2. Main Estimate View**
- Large text input for meal description
- Optional collapsible "notes" field  
- "Estimate" button
- Loading state with elapsed time counter (queries take 10-30 seconds)

**3. Results Display**

```
┌─────────────────────────────────────────┐
│  MEAL TOTAL                             │
│  Net Carbs    57.5g                     │
│  Protein      55.0g                     │
│  Fat          22.5g                     │
│  Calories     665                       │
│                                         │
│  ⏱ ABSORPTION (Warsaw Method)           │
│  FPU: 3.25  │  Duration: 5h            │
│  Profile: Mixed  │  Peak: ~90min       │
│  Carb equiv from F+P: 32.5g            │
│  Total carb impact: 90.0g              │
│  ┌─────────────────────────────────┐    │
│  │ Dosing notes here...            │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ITEM BREAKDOWN                         │
│  ▸ White rice (4oz)           40.0g C   │
│    P: 4.0g  F: 3.5g  [HIGH ✓]         │
│  ▸ Chicken (4oz)               0.0g C   │
│    P: 32.0g  F: 3.5g  [HIGH ✓]        │
│  ...                                    │
│                                         │
│  [Correct This Estimate]   [New Query]  │
└─────────────────────────────────────────┘
```

- `confidence: "low"` items get amber ⚠ marker
- Expandable detail per item showing `source_values_seen`
- "Correct This Estimate" opens modal for actual values

**4. History View** — Scrollable list, search bar, tap to expand

**5. Accuracy View** — Stats from corrections (if any exist)

### `frontend/manifest.json`

```json
{
    "name": "CarbCount",
    "short_name": "CarbCount",
    "description": "Precision macronutrient estimation for Type 1 Diabetics",
    "start_url": "/app/",
    "display": "standalone",
    "background_color": "#0a0f1a",
    "theme_color": "#0a0f1a",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"}
    ]
}
```

### `frontend/sw.js` — Service Worker

Cache the app shell only. API responses are cached by the backend in SQLite.

```javascript
const CACHE_NAME = 'carbcount-v1';
const SHELL_URLS = ['/app/', '/app/style.css', '/app/app.js', '/app/manifest.json'];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_URLS)));
});

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    if (event.request.url.includes('/api/')) return;
    event.respondWith(
        caches.match(event.request).then(cached => cached || fetch(event.request))
    );
});
```

### `frontend/app.js` — Key Patterns

```javascript
// API helper with auth
async function apiRequest(path, options = {}) {
    const token = sessionStorage.getItem('app_token');
    if (!token && path !== '/health') {
        showTokenEntry();
        throw new Error('No token');
    }
    
    const response = await fetch(`/api${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
            ...options.headers,
        },
    });
    
    if (response.status === 401) {
        sessionStorage.removeItem('app_token');
        showTokenEntry();
        throw new Error('Unauthorized');
    }
    
    if (response.status === 429) {
        const data = await response.json();
        showError(`Rate limited: ${data.detail}`);
        throw new Error('Rate limited');
    }
    
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `API error: ${response.status}`);
    }
    
    return response.json();
}
```

### PWA Icons

Generate with Pillow:

```python
from PIL import Image, ImageDraw, ImageFont

for size in [192, 512]:
    img = Image.new('RGB', (size, size), '#0a0f1a')
    draw = ImageDraw.Draw(img)
    margin = size // 8
    draw.ellipse([margin, margin, size-margin, size-margin], outline='#22d3ee', width=size//32)
    font_size = size // 2
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()
    draw.text((size//2, size//2), "C", fill='#22d3ee', font=font, anchor='mm')
    img.save(f'frontend/icons/icon-{size}.png')
```

---

## 12. Deployment: Railway

### `railway.toml`

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3

[build.nixpacks]
providers = ["python"]

[[mounts]]
source = "data"
mountPath = "/app/data"
```

### `Procfile`

```
web: cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

### `backend/requirements.txt`

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
anthropic>=0.45.0
aiosqlite>=0.19.0
sqlalchemy[asyncio]>=2.0.0
python-dotenv>=1.0.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
pillow>=10.0.0
```

### `.gitignore`

```
.env
__pycache__/
*.pyc
data/
*.db
.DS_Store
```

### `.env.example`

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
APP_SECRET_TOKEN=your-random-token-here
ALLOWED_ORIGIN=*
DATABASE_URL=sqlite+aiosqlite:///./data/carbcount.db
MODEL=claude-sonnet-4-5-20250929
TEMPERATURE=0.0
CACHE_HOURS=24
RATE_LIMIT_PER_HOUR=30
RATE_LIMIT_PER_DAY=200
```

### Deployment Steps

```bash
# 1. Generate your app secret token
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Push to GitHub
git init && git add . && git commit -m "CarbCount v1"
git remote add origin git@github.com:YOUR_USER/carbcount.git
git push -u origin main

# 3. Create Railway project
# railway.app/new → "Deploy from GitHub Repo" → select repo

# 4. Add persistent volume
# Railway dashboard → service → Settings → Volumes → mount at /app/data

# 5. Set environment variables (Railway dashboard → Variables)
# ANTHROPIC_API_KEY=sk-ant-...
# APP_SECRET_TOKEN=<generated token>
# ALLOWED_ORIGIN=https://<your-app>.up.railway.app

# 6. Set Anthropic spending limit
# console.anthropic.com → Billing → Spending Limits → e.g. $50/month

# 7. Add to iPhone
# Safari → https://<your-app>.up.railway.app/app/
# Share → "Add to Home Screen"
# Enter APP_SECRET_TOKEN when prompted
```

---

## 13. Testing

```bash
# Local setup
cd backend
pip install -r requirements.txt
cp ../.env.example .env  # Edit with real keys

# Run
uvicorn main:app --reload --port 8000

# Test health
curl http://localhost:8000/health

# Test estimate
TOKEN="your-test-token"
curl -X POST http://localhost:8000/api/estimate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "Two slices of pepperoni pizza from Dominos"}'

# Test cache (same query → cached: true)
curl -X POST http://localhost:8000/api/estimate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "Two slices of pepperoni pizza from Dominos"}'

# Test auth rejection (401)
curl -X POST http://localhost:8000/api/estimate \
  -H "Authorization: Bearer wrong" \
  -d '{"query": "apple"}'

# Test history
curl http://localhost:8000/api/history -H "Authorization: Bearer $TOKEN"
```

### Validation Checklist

- [ ] `/health` returns 200 without auth
- [ ] `/api/estimate` returns 401 without Bearer token
- [ ] `/api/estimate` returns structured macros + Warsaw
- [ ] Second identical query returns `"cached": true`
- [ ] Warsaw math is deterministic
- [ ] `/api/history` returns past estimates
- [ ] Correction endpoint works
- [ ] Rate limiting triggers at threshold
- [ ] PWA loads at `/app/`
- [ ] PWA installable on iPhone home screen

---

## 14. References

### Warsaw Method

1. Pańkowska E, et al. "Application of Novel Dual Wave Meal Bolus..." *Pediatric Diabetes*. 2009;10(5):298-308.
2. Pańkowska E, Blazik M. "Bolus Calculator with Nutrition Database Software..." *J Diabetes Sci Technol*. 2010;4(3):571-576. (PMC2901033)
3. "Modified fat-protein unit algorithm vs carbohydrate counting..." *Nutrients*. 2023. (PMC10580506)

### FPU Formula

```
Protein kcal = protein_g × 4
Fat kcal     = fat_g × 9
FPU          = (protein_kcal + fat_kcal) / 100
Carb equiv   = FPU × 10g × modifier

Duration: 1 FPU→3h, 2→4h, 3→5h, ≥4→8h
```

---

## 15. Future Enhancements (v2+)

- **Correction feedback loop:** Calibrate system prompt from accuracy history
- **Photo input:** Claude vision to identify foods before estimation
- **Favorite meals:** Quick-recall cached estimates
- **CGM integration:** Compare vs Dexcom/Libre curves
- **Barcode scanning:** UPC lookup via device camera
- **Voice input:** Web Speech API for hands-free logging
- **Glycemic index weighting:** Simple vs complex carb peak timing
- **Export:** CSV/JSON for sharing with endocrinologist
