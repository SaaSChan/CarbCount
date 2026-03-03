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
                "description": "Itemized breakdown -- one entry per distinct food component",
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
