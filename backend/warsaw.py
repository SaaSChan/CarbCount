"""
Warsaw Method Implementation
Reference: Pankowska E, Szypowska A, Lipka M, et al.
"Application of Novel Dual Wave Meal Bolus and Its Impact on Glycated
Hemoglobin A1c in Children with Type 1 Diabetes."
Pediatric Diabetes. 2009;10(5):298-308.

Duration chart (Pankowska 2010, PMC2901033):
  1 FPU -> 3 hours
  2 FPU -> 4 hours
  3 FPU -> 5 hours
  >=4 FPU -> 8 hours

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
    profile: str
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


# Warsaw duration lookup -- empirically established (Pankowska 2010)
WARSAW_DURATION = {
    0: 0.0,
    1: 3.0,
    2: 4.0,
    3: 5.0,
}
WARSAW_DURATION_HIGH = 8.0  # >=4 FPU


def _get_absorption_hours(fpu_rounded: int) -> float:
    """Look up absorption duration from Warsaw chart."""
    if fpu_rounded <= 0:
        return 0.0
    if fpu_rounded in WARSAW_DURATION:
        return WARSAW_DURATION[fpu_rounded]
    return WARSAW_DURATION_HIGH  # >=4 FPU


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
            "High fat ratio will delay gastric emptying -- "
            "expect a delayed and prolonged glucose rise."
        )

    if net_carbs_g > 60.0:
        notes_parts.append(
            "High carb load -- consider pre-bolusing 15-20 minutes before eating."
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
