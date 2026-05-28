from __future__ import annotations

from typing import Any

import pandas as pd


class DataConnector:
    """Loads tabular data from files and SQL, with basic normalization."""

    def load_csv(self, file_path: str, **kwargs: Any) -> pd.DataFrame:
        df = pd.read_csv(file_path, **kwargs)
        return self._normalize_dataframe(df)

    def load_excel(self, file_path: str, sheet_name: str | int = 0, **kwargs: Any) -> pd.DataFrame:
        df = pd.read_excel(file_path, sheet_name=sheet_name, **kwargs)
        return self._normalize_dataframe(df)

    def load_sql(self, connection_string: str, query: str) -> pd.DataFrame:
        try:
            from sqlalchemy import create_engine
        except Exception as exc:
            raise ImportError("sqlalchemy is required to load SQL data") from exc

        engine = create_engine(connection_string)
        with engine.connect() as conn:
            df = pd.read_sql_query(query, conn)
        return self._normalize_dataframe(df)

    def digitalize_pdf(self, file_path: str) -> pd.DataFrame:
        """Extract text rows from PDF. Uses pdfplumber first, OCR as optional fallback."""
        text = ""

        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except Exception as exc:
            raise RuntimeError(f"Unable to extract PDF text: {exc}") from exc

        if not text.strip():
            try:
                from pdf2image import convert_from_path
                import pytesseract

                pages = convert_from_path(file_path)
                ocr_text = []
                for page_image in pages:
                    ocr_text.append(pytesseract.image_to_string(page_image))
                text = "\n".join(ocr_text)
            except Exception:
                pass

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        df = pd.DataFrame({"text": lines})
        return self._normalize_dataframe(df)

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply lightweight type normalization and missing value handling."""
        normalized = df.copy()
        normalized.columns = [str(c).strip() for c in normalized.columns]

        for col in normalized.columns:
            series = normalized[col]
            if series.dtype == "object":
                dt_try = pd.to_datetime(series, errors="coerce")
                if dt_try.notna().mean() > 0.7:
                    normalized[col] = dt_try
                    continue

                numeric_try = pd.to_numeric(series, errors="coerce")
                if numeric_try.notna().mean() > 0.7:
                    normalized[col] = numeric_try
                    continue

                normalized[col] = series.fillna("").astype(str).str.strip()
            else:
                if pd.api.types.is_numeric_dtype(series):
                    normalized[col] = series.fillna(0)
                elif pd.api.types.is_datetime64_any_dtype(series):
                    normalized[col] = pd.to_datetime(series, errors="coerce")

        return normalized

    def ingestion_report(self, df: pd.DataFrame, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "rows": int(len(df)),
            "columns": list(df.columns),
            "dtypes": {k: str(v) for k, v in df.dtypes.items()},
            "missing_per_column": {k: int(v) for k, v in df.isna().sum().items()},
        }
