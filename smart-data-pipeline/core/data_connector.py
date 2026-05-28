from __future__ import annotations

import os
from typing import Any, Optional

import pandas as pd


class DataConnector:
    """Loads tabular data from files, SQL, and Databricks Delta Lake."""

    # ── File loaders ──────────────────────────────────────────────────────

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

    # ── Databricks Delta connector ────────────────────────────────────────

    def load_databricks(
        self,
        query: str,
        server_hostname: Optional[str] = None,
        http_path: Optional[str] = None,
        access_token: Optional[str] = None,
        *,
        staging_allowed_local_path: Optional[str] = None,
    ) -> pd.DataFrame:
        """Execute *query* on a Databricks SQL warehouse and return a DataFrame.

        Credentials are resolved in order: explicit args → environment variables.
        Always closes cursor and connection in a finally block to prevent leaks.

        Environment variables:
            DATABRICKS_HOST        — e.g. adb-<id>.azuredatabricks.net
            DATABRICKS_HTTP_PATH   — e.g. /sql/1.0/warehouses/<id>
            DATABRICKS_TOKEN       — personal access token or M2M token
        """
        try:
            from databricks import sql as databricks_sql
        except ImportError as exc:
            raise ImportError(
                "databricks-sql-connector is required: pip install databricks-sql-connector"
            ) from exc

        host = server_hostname or os.environ["DATABRICKS_HOST"]
        path = http_path or os.environ["DATABRICKS_HTTP_PATH"]
        token = access_token or os.environ["DATABRICKS_TOKEN"]

        connect_kwargs: dict[str, Any] = {
            "server_hostname": host,
            "http_path": path,
            "access_token": token,
        }
        if staging_allowed_local_path is not None:
            connect_kwargs["staging_allowed_local_path"] = staging_allowed_local_path

        conn = None
        cursor = None
        try:
            conn = databricks_sql.connect(**connect_kwargs)
            cursor = conn.cursor()
            cursor.execute(query)
            # fetchall_arrow returns a PyArrow table → zero-copy to pandas
            arrow_table = cursor.fetchall_arrow()
            df = arrow_table.to_pandas()
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

        return self._normalize_dataframe(df)

    # ── PDF digitalization ────────────────────────────────────────────────

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

    # ── Internal helpers ──────────────────────────────────────────────────

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply lightweight type normalization and missing-value handling."""
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
