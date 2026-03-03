import time
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from config import settings
from security import AuthMiddleware, RateLimitMiddleware
from database import init_db, get_session
from crud import get_cached_estimate, save_estimate, get_history, get_estimate_by_id, apply_correction, get_accuracy_stats
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

# Middleware (order matters -- outermost first)
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
app.mount("/app", StaticFiles(directory="../frontend", html=True), name="frontend")


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


@app.get("/api/history/{estimate_id}", response_model=EstimateResponse)
async def get_estimate(estimate_id: str):
    async with get_session() as session:
        record = await get_estimate_by_id(session, estimate_id)
        if not record:
            raise HTTPException(404, "Estimate not found")
        return EstimateResponse.from_record(record, cached=True)


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
