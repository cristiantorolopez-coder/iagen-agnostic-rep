from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnMapping:
    """Business mapping for a physical data column."""

    column_name: str
    aliases: list[str]
    business_description: str
    data_type: str
    examples: list[Any] = field(default_factory=list)
    category: str = "general"
