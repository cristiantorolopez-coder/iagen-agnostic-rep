from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from typing import Any, Optional

import pandas as pd

from context_manager import ContextManager
from mapping_registry import DataMappingRegistry
from smart_data_models import ColumnMapping


class DataQueryAgent:
    """Natural-language query agent with optional Anthropic integration."""

    def __init__(
        self,
        data_registry: DataMappingRegistry,
        context_manager: ContextManager,
        data_dfs: dict[str, pd.DataFrame],
        anthropic_api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-latest",
    ) -> None:
        self.data_registry = data_registry
        self.context_manager = context_manager
        self.data_dfs = data_dfs
        self.model = model
        self.conversation_history: list[dict[str, str]] = []
        self._last_mapping: Optional[ColumnMapping] = None
        self.last_source: str = "Local"

        # ── Anthropic ────────────────────────────────────────────────────
        anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self._anthropic_client = None
        if anthropic_key:
            try:
                from anthropic import Anthropic
                self._anthropic_client = Anthropic(api_key=anthropic_key)
            except Exception:
                self._anthropic_client = None

        # ── GitHub Models (Copilot) ──────────────────────────────────────
        # Uses the OpenAI-compatible endpoint at models.inference.ai.azure.com.
        # Requires a GitHub PAT with `models:read` scope (or your Copilot token).
        github_token = os.getenv("GITHUB_TOKEN")
        self._github_client = None
        self._github_model = os.getenv("GITHUB_MODEL", "gpt-4o-mini")
        if github_token and self._anthropic_client is None:
            try:
                from openai import OpenAI
                self._github_client = OpenAI(
                    base_url="https://models.inference.ai.azure.com",
                    api_key=github_token,
                )
            except Exception:
                self._github_client = None

    _GREETINGS = {"hola", "hi", "hello", "buenas", "buenos dias", "buenas tardes", "hey"}

    def query(self, user_question: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_question})

        if user_question.strip().lower() in self._GREETINGS:
            aliases = []
            for m in self.data_registry.list_mappings():
                aliases += m.aliases[:2]
            cols = [m.column_name for m in self.data_registry.list_mappings()]
            hint = ", ".join(aliases[:6]) if aliases else ", ".join(cols[:4]) if cols else "las columnas mapeadas"
            final_answer = (
                f"¡Hola! Puedo responder preguntas sobre tus datos. "
                f"Puedes preguntarme por: {hint}."
            )
            self.last_source = "Local (saludo)"
            self.conversation_history.append({"role": "assistant", "content": final_answer})
            return final_answer

        # Lookup by value takes priority over aggregation.
        lookup = self._detect_value_lookup(user_question)
        if lookup is not None:
            local_answer, metadata = lookup
        else:
            local_answer, metadata = self._build_local_answer(user_question)
        llm_answer = self._try_generate_with_llm(user_question, local_answer, metadata)
        if llm_answer:
            self.last_source = "LLM"
            final_answer = llm_answer
        else:
            self.last_source = "Local"
            final_answer = local_answer

        self.conversation_history.append({"role": "assistant", "content": final_answer})
        return final_answer

    def get_conversation_history(self) -> list[dict[str, str]]:
        return list(self.conversation_history)

    def _build_local_answer(self, question: str) -> tuple[str, dict[str, Any]]:
        all_mappings = self._detect_all_mappings(question)
        if not all_mappings and self._last_mapping:
            all_mappings = [self._last_mapping]
        if not all_mappings:
            return (
                "No pude mapear la metrica solicitada a una columna. "
                "Registra aliases en DataMappingRegistry e intenta de nuevo.",
                {"status": "no_mapping"},
            )

        # Determine if this is a groupby question (one categorical + one numeric).
        def _is_numeric_col(df: pd.DataFrame, col: str) -> bool:
            return pd.to_numeric(df[col], errors="coerce").notna().sum() > 0

        # Pick the first mapping as primary to find the table.
        mapping = all_mappings[0]
        self._last_mapping = mapping

        table_name, df = self._find_table_for_column(mapping.column_name)
        if df is None:
            return (
                f"No encontre una tabla que contenga la columna '{mapping.column_name}'.",
                {"status": "column_not_found", "column": mapping.column_name},
            )

        filtered_df, date_filter = self._apply_time_filter_if_needed(df, question)

        # Check for categorical+numeric pair among detected mappings → groupby.
        if len(all_mappings) >= 2:
            cat_mapping = next(
                (m for m in all_mappings if not _is_numeric_col(filtered_df, m.column_name)
                 and m.column_name in filtered_df.columns), None
            )
            num_mapping = next(
                (m for m in all_mappings if _is_numeric_col(filtered_df, m.column_name)
                 and m.column_name in filtered_df.columns), None
            )
            if cat_mapping and num_mapping:
                return self._build_groupby_answer(
                    filtered_df, df, cat_mapping.column_name, num_mapping.column_name,
                    table_name, date_filter
                )

        column = mapping.column_name

        # Detect if the column is numeric or categorical/string.
        numeric_series = pd.to_numeric(filtered_df[column], errors="coerce")
        is_numeric = numeric_series.notna().sum() > 0

        op = self._detect_operation(question)
        value: Any

        if not is_numeric:
            # Categorical column — groupby with available numeric columns.
            num_cols = [
                c for c in filtered_df.columns
                if c != column and pd.to_numeric(filtered_df[c], errors="coerce").notna().sum() > 0
            ]
            if num_cols:
                num_col = num_cols[0]
                tmp = filtered_df[[column, num_col]].copy()
                tmp[num_col] = pd.to_numeric(tmp[num_col], errors="coerce")
                grouped = tmp.groupby(column)[num_col].agg(
                    total="sum", promedio="mean", maximo="max", minimo="min", registros="count"
                ).sort_values("total", ascending=False)
                rows = [
                    f"  {idx}: total={self._format_value(r['total'])}, prom={self._format_value(r['promedio'])}, "
                    f"max={self._format_value(r['maximo'])}, registros={int(r['registros'])}"
                    for idx, r in grouped.iterrows()
                ]
                value = grouped.to_dict("index")
                answer_line = (
                    f"- Agrupación de {num_col} por {column} "
                    f"({len(grouped)} grupos, ordenado por total desc):\n" + "\n".join(rows)
                )
                op = "groupby"
            else:
                # No numeric cols — fallback to unique list.
                unique_vals = filtered_df[column].dropna().unique().tolist()
                value = unique_vals
                answer_line = (
                    f"- Valores únicos de {column} ({len(unique_vals)}): "
                    f"{', '.join(str(v) for v in unique_vals)}"
                )
                op = "list"
        else:
            if op == "sum":
                value = numeric_series.sum()
                label = "Total"
            elif op == "mean":
                value = numeric_series.mean()
                label = "Promedio"
            elif op == "count":
                value = numeric_series.count()
                label = "Conteo"
            else:
                value = numeric_series.sum()
                label = "Total"
            answer_line = f"- {label} de {mapping.column_name}: {self._format_value(value)}"

        response = [
            "DATA ANSWER",
            answer_line,
            f"- Filas procesadas: {len(filtered_df)} de {len(df)}",
            "",
            "DATA SOURCE",
            f"- Tabla: {table_name}",
            f"- Columna: {mapping.column_name}",
            f"- Alias usados: {', '.join(mapping.aliases)}",
            f"- Filtro temporal: {date_filter}",
            "",
            "BUSINESS CONTEXT",
            self._extract_short_context(),
        ]

        metadata = {
            "status": "ok",
            "table": table_name,
            "column": mapping.column_name,
            "operation": op,
            "rows_processed": len(filtered_df),
            "rows_total": len(df),
            "date_filter": date_filter,
            "value": value,
        }
        return "\n".join(response), metadata

    def _try_generate_with_llm(
        self,
        user_question: str,
        local_answer: str,
        metadata: dict[str, Any],
    ) -> Optional[str]:
        if self._anthropic_client is None and self._github_client is None:
            return None

        recent_turns = self.conversation_history[-6:]
        context = self.context_manager.get_all_context()[:6000]

        system_prompt = (
            "You are a data assistant. Use the provided computed result as the only source of truth. "
            "Answer in Spanish. "
            "For 'lookup' operations: give a rich narrative about the entity — "
            "how many records were found, statistics per numeric column, "
            "related categorical attribute values, and any context mentions. "
            "For all other operations (sum, mean, count, groupby, list): "
            "use sections RESPUESTA, ANALISIS CONTEXTUAL, FUENTE DE DATOS. "
            "Do not invent numbers. The data is generic — column names and domain vary per user."
        )
        user_prompt = (
            f"Question: {user_question}\n\n"
            f"Computed result:\n{local_answer}\n\n"
            f"Metadata: {json.dumps(metadata, default=str)}\n\n"
            f"Conversation history: {json.dumps(recent_turns, ensure_ascii=False)}\n\n"
            f"Business context:\n{context}"
        )

        # ── Anthropic ────────────────────────────────────────────────────
        if self._anthropic_client is not None:
            try:
                msg = self._anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=900,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                if msg.content:
                    first = msg.content[0]
                    if hasattr(first, "text"):
                        return first.text
            except Exception:
                return None

        # ── GitHub Models (Copilot) ──────────────────────────────────────
        if self._github_client is not None:
            try:
                resp = self._github_client.chat.completions.create(
                    model=self._github_model,
                    max_tokens=900,
                    temperature=0.1,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                return resp.choices[0].message.content
            except Exception:
                return None

        return None

    # Spanish/English stop words that should never drive alias matching.
    _STOP_WORDS = {
        # articles / prepositions
        "y", "el", "la", "los", "las", "de", "del", "un", "una",
        "es", "en", "que", "fue", "por", "con", "and", "the", "of",
        "a", "e", "o", "al", "lo", "le", "se", "me", "te",
        # Spanish request / question words (common false-positive triggers)
        "dame", "dime", "muestra", "muestrame", "cual", "cuales",
        "como", "cuando", "donde", "quien", "quienes",
        "hay", "son", "tiene", "tienen",
        "mas", "menos", "mayor", "menor",
        "todos", "todas", "cada",
        "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
        "si", "no", "ni", "pero", "para",
    }

    def _build_groupby_answer(
        self,
        filtered_df: pd.DataFrame,
        full_df: pd.DataFrame,
        cat_col: str,
        num_col: str,
        table_name: str,
        date_filter: str,
    ) -> tuple[str, dict[str, Any]]:
        tmp = filtered_df[[cat_col, num_col]].copy()
        tmp[num_col] = pd.to_numeric(tmp[num_col], errors="coerce")
        grouped = tmp.groupby(cat_col)[num_col].agg(
            total="sum", promedio="mean", maximo="max", minimo="min", registros="count"
        ).sort_values("total", ascending=False)
        rows = [
            f"  {idx}: total={self._format_value(r['total'])}, prom={self._format_value(r['promedio'])}, "
            f"max={self._format_value(r['maximo'])}, registros={int(r['registros'])}"
            for idx, r in grouped.iterrows()
        ]
        grouped_dict = grouped.to_dict("index")
        response = [
            "DATA ANSWER",
            f"- Agrupación de {num_col} por {cat_col} ({len(grouped)} grupos, ordenado por total desc):",
            *rows,
            f"- Filas procesadas: {len(filtered_df)} de {len(full_df)}",
            "",
            "DATA SOURCE",
            f"- Tabla: {table_name}",
            f"- Agrupado por: {cat_col}",
            f"- Métrica: {num_col}",
            f"- Filtro temporal: {date_filter}",
            "",
            "BUSINESS CONTEXT",
            self._extract_short_context(),
        ]
        metadata = {
            "status": "ok",
            "table": table_name,
            "column": num_col,
            "group_by": cat_col,
            "operation": "groupby",
            "rows_processed": len(filtered_df),
            "rows_total": len(full_df),
            "date_filter": date_filter,
            "value": grouped_dict,
        }
        return "\n".join(response), metadata

    def _detect_all_mappings(self, question: str) -> list[ColumnMapping]:
        """Return all unique ColumnMappings matched in the question."""
        normalized_tokens = [
            t for t in re.findall(r"[a-zA-Z0-9_]+", question.lower())
            if t not in self._STOP_WORDS and len(t) >= 2
        ]
        seen: set[str] = set()
        results: list[ColumnMapping] = []

        candidate = self.data_registry.find_by_alias(question)
        if candidate and candidate.column_name not in seen:
            seen.add(candidate.column_name)
            results.append(candidate)

        for token in normalized_tokens:
            found = self.data_registry.find_by_alias(token)
            if found and found.column_name not in seen:
                seen.add(found.column_name)
                results.append(found)
        return results

    def _find_table_for_column(self, column_name: str) -> tuple[str, Optional[pd.DataFrame]]:
        for table_name, df in self.data_dfs.items():
            if column_name in df.columns:
                return table_name, df
        return "", None

    @staticmethod
    def _detect_operation(question: str) -> str:
        q = question.lower()
        if any(token in q for token in ["promedio", "average", "mean"]):
            return "mean"
        if any(token in q for token in ["cuantos", "count", "cantidad", "numero"]):
            return "count"
        return "sum"

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{value:,.2f}"
        return str(value)

    def _apply_time_filter_if_needed(
        self,
        df: pd.DataFrame,
        question: str,
    ) -> tuple[pd.DataFrame, str]:
        q = question.lower()
        date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
        if not date_cols:
            return df, "none"

        if "mes pasado" in q or "last month" in q or "ultimos 30" in q or "ultimos 30 dias" in q:
            date_col = date_cols[0]
            max_date = df[date_col].max()
            if pd.isna(max_date):
                return df, "none"
            start = max_date - timedelta(days=30)
            filtered = df[(df[date_col] >= start) & (df[date_col] <= max_date)]
            return filtered, f"{date_col} between {start.date()} and {max_date.date()}"

        return df, "none"

    def _detect_value_lookup(
        self, question: str
    ) -> Optional[tuple[str, dict[str, Any]]]:
        """Detect if the question references a specific data value and build a rich entity profile.

        Scans all string columns for values that appear in the question.
        When found, computes:
          - row count (transactions/occurrences)
          - sum + mean of every numeric column for that subset
          - unique values of every other string column
          - context snippets that mention the entity
        Returns (answer_str, metadata) or None.
        """
        q = question.lower()
        for table_name, df in self.data_dfs.items():
            for col in df.columns:
                if not (df[col].dtype == object or pd.api.types.is_string_dtype(df[col])):
                    continue
                for val in df[col].dropna().unique():
                    val_str = str(val).strip()
                    if len(val_str) < 2:
                        continue
                    if val_str.lower() not in q:
                        continue

                    # ── Entity found → build profile ──────────────────────
                    subset = df[df[col].str.strip().str.lower() == val_str.lower()]
                    if subset.empty:
                        continue

                    profile: dict[str, Any] = {
                        "entity": val_str,
                        "matched_column": col,
                        "table": table_name,
                        "occurrences": len(subset),
                        "total_rows_in_table": len(df),
                        "numeric_stats": {},
                        "related_attributes": {},
                    }

                    # Aggregate every numeric column for this entity.
                    for num_col in df.select_dtypes(include="number").columns:
                        s = pd.to_numeric(subset[num_col], errors="coerce")
                        profile["numeric_stats"][num_col] = {
                            "total": round(float(s.sum()), 2),
                            "mean": round(float(s.mean()), 2),
                            "min": round(float(s.min()), 2),
                            "max": round(float(s.max()), 2),
                        }

                    # Collect unique values of other string/categorical columns.
                    for other_col in df.columns:
                        if other_col == col:
                            continue
                        if df[other_col].dtype == object or pd.api.types.is_string_dtype(df[other_col]):
                            uniques = subset[other_col].dropna().unique().tolist()
                            if uniques:
                                profile["related_attributes"][other_col] = uniques

                    # Search context docs for mentions of this entity.
                    ctx_full = self.context_manager.get_all_context()
                    ctx_mentions: list[str] = []
                    for line in ctx_full.splitlines():
                        if val_str.lower() in line.lower():
                            ctx_mentions.append(line.strip())
                    profile["context_mentions"] = ctx_mentions[:5]

                    # Build a readable local summary (fallback if LLM is unavailable).
                    lines = [
                        f"PERFIL DE '{val_str}' (columna: {col}, tabla: {table_name})",
                        f"- Registros encontrados: {profile['occurrences']} de {len(df)}",
                    ]
                    for num_col, stats in profile["numeric_stats"].items():
                        lines.append(
                            f"- {num_col}: total={stats['total']:,}  "
                            f"prom={stats['mean']:,}  "
                            f"min={stats['min']:,}  max={stats['max']:,}"
                        )
                    for attr_col, vals in profile["related_attributes"].items():
                        lines.append(f"- {attr_col}: {', '.join(str(v) for v in vals)}")
                    if ctx_mentions:
                        lines.append("")
                        lines.append("MENCIONES EN CONTEXTO:")
                        lines.extend(f"  · {m}" for m in ctx_mentions)

                    answer = "\n".join(lines)
                    metadata = {"status": "ok", "operation": "lookup", **profile}
                    return answer, metadata

        return None

    def _extract_short_context(self, max_chars: int = 800) -> str:
        text = self.context_manager.get_all_context().strip()
        if not text:
            return "No business context loaded."
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."
