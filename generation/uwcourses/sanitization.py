"""
Sanitization utilities for generating safe filenames and identifiers.
"""

import hashlib
import re
from typing import Union
from logging import getLogger
from anyascii import anyascii
from pathvalidate import validate_filename, ValidationError

logger = getLogger(__name__)


def sanitize_instructor_id(name: str) -> Union[str, None]:
    """Convert instructor name to uppercase URL-safe ID. e.g., "O'Brien Jr." → "OBRIEN_JR" """
    if not name:
        return None

    result = anyascii(name)
    result = (
        result.replace("/", "_")
        .replace(" ", "_")
        .replace("'", "")
        .replace(".", "")
        .upper()
    )
    result = re.sub(r"_+", "_", result).strip("_")

    fallback = (
        "INSTRUCTOR_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:32].upper()
    )
    if not result:
        return fallback

    try:
        validate_filename(result)
    except ValidationError as e:
        logger.debug(f"Invalid instructor ID '{result}': {e}. Using stable fallback.")
        return fallback

    return result
