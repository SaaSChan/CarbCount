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
    macros: dict
    warsaw: dict
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
