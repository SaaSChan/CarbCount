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


async def get_estimate_by_id(
    session: AsyncSession,
    estimate_id: str
) -> Optional[Estimate]:
    """Return a single estimate by ID."""
    result = await session.execute(
        select(Estimate).where(Estimate.id == estimate_id)
    )
    return result.scalar_one_or_none()


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
        "worst_categories": [],
    }
