"""
commands/calculator.py
======================
Calculator command handler for Nova Voice Assistant.

Safely evaluates mathematical expressions using a whitelist-based
evaluation approach (no exec/unsafe eval).

Handler
-------
    handle(entities: dict) -> str
    entities keys: expression (str)
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from utils.logger import get_logger
from utils.helpers import safe_eval

logger = get_logger(__name__)


def _clean_expression(text: str) -> str:
    """
    Strip spoken filler words and normalise an expression string.

    Examples
    --------
    "What is 245 multiplied by 87?" → "245 * 87"
    "Calculate the square root of 144" → "sqrt(144)"
    """
    # Remove question words / filler
    text = re.sub(
        r"\b(what is|what's|calculate|compute|how much is|equals?|the answer to|solve|find)\b",
        "", text, flags=re.IGNORECASE,
    ).strip().rstrip("?").strip()

    # Spoken "square root of" → sqrt()
    text = re.sub(r"square root of\s+(\d+\.?\d*)", r"sqrt(\1)", text, flags=re.IGNORECASE)
    # "X to the power of Y" → "X ** Y"
    text = re.sub(r"(\d+\.?\d*)\s+to the power of\s+(\d+\.?\d*)", r"\1 ** \2", text, flags=re.IGNORECASE)
    # "X squared" → "X ** 2"
    text = re.sub(r"(\d+\.?\d*)\s+squared", r"\1 ** 2", text, flags=re.IGNORECASE)

    return text.strip()


def _format_result(result: float) -> str:
    """Format a float result for human speech."""
    if result == int(result) and abs(result) < 1e15:
        return str(int(result))
    return f"{result:.6g}"


def handle(entities: Dict[str, Any]) -> str:
    """
    Evaluate a mathematical expression and return the result.

    Parameters
    ----------
    entities:   Should contain 'expression' (str) or 'raw_text'.

    Returns
    -------
    Spoken result string.
    """
    expression: str = entities.get("expression", "") or entities.get("raw_text", "")

    if not expression:
        return "I didn't catch the mathematical expression. Please try again."

    cleaned = _clean_expression(expression)
    logger.info("Calculator: evaluating %r (cleaned: %r)", expression[:60], cleaned[:60])

    result: Optional[float] = safe_eval(cleaned)

    if result is None:
        return (
            "I couldn't evaluate that expression. "
            "Please try saying it differently, for example: 'What is 12 times 8?'"
        )

    formatted = _format_result(result)
    return f"The answer is {formatted}."
