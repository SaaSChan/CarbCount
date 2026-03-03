from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class Estimate(Base):
    __tablename__ = "estimates"

    id = Column(String, primary_key=True)
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
