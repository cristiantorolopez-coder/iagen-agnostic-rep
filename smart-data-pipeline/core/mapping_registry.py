from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.smart_data_models import ColumnMapping

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - optional dependency fallback
    fuzz = None


class DataMappingRegistry:
    """Stores business mappings and supports case-insensitive + fuzzy alias search."""

    def __init__(self) -> None:
        self._mappings: dict[str, ColumnMapping] = {}

    def register_column(self, mapping: ColumnMapping) -> None:
        self._mappings[mapping.column_name.lower()] = mapping

    def find_by_alias(self, alias: str, fuzzy_threshold: int = 70) -> Optional[ColumnMapping]:
        alias_norm = alias.strip().lower()
        if not alias_norm:
            return None

        for mapping in self._mappings.values():
            candidates = [mapping.column_name, *mapping.aliases]
            for candidate in candidates:
                c = candidate.lower()
                exact = alias_norm == c
                substr = len(alias_norm) >= 3 and (alias_norm in c or c in alias_norm)
                if exact or substr:
                    return mapping

        best_mapping: Optional[ColumnMapping] = None
        best_score = -1
        for mapping in self._mappings.values():
            candidates = [mapping.column_name, *mapping.aliases]
            for candidate in candidates:
                score = self._score_similarity(alias_norm, candidate.lower())
                if score > best_score:
                    best_score = score
                    best_mapping = mapping

        if best_mapping and best_score >= fuzzy_threshold:
            return best_mapping
        return None

    def list_mappings(self) -> list[ColumnMapping]:
        return list(self._mappings.values())

    def save_to_file(self, file_path: str) -> None:
        payload = [asdict(m) for m in self._mappings.values()]
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def load_from_file(self, file_path: str) -> None:
        with open(file_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        self._mappings.clear()
        for item in items:
            self.register_column(ColumnMapping(**item))

    def load_from_folder(self, folder_path: str) -> int:
        """Load all JSON mapping files from a folder. Returns number of mappings loaded."""
        folder = Path(folder_path)
        if not folder.exists():
            return 0
        loaded = 0
        for file_path in sorted(folder.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, dict):
                items = [items]
            for item in items:
                self.register_column(ColumnMapping(**item))
                loaded += 1
        return loaded

    @staticmethod
    def _score_similarity(left: str, right: str) -> int:
        if fuzz is not None:
            return int(fuzz.ratio(left, right))

        import difflib

        return int(difflib.SequenceMatcher(None, left, right).ratio() * 100)
