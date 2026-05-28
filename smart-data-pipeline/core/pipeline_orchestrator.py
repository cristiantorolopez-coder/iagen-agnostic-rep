from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core.context_manager import ContextManager
from core.data_connector import DataConnector
from core.mapping_registry import DataMappingRegistry
from core.query_agent import DataQueryAgent
from core.smart_data_models import ColumnMapping


class SmartDataPipeline:
    """Main orchestrator: data loading, mapping registry, context, and NL querying."""

    def __init__(self) -> None:
        self.connector = DataConnector()
        self.data_registry = DataMappingRegistry()
        self.context_manager = ContextManager()
        self.data_dfs: dict[str, pd.DataFrame] = {}
        self.ingestion_reports: list[dict[str, Any]] = []
        self.agent: Optional[DataQueryAgent] = None

    # ── File / SQL loaders ────────────────────────────────────────────────

    def load_data_from_folder(self, folder_path: str, file_type: Optional[str] = None) -> None:
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        for file_path in folder.iterdir():
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lower()
            if file_type and ext != f".{file_type.lower().lstrip('.')}":
                continue

            df: Optional[pd.DataFrame] = None
            if ext in {".csv", ".tsv"}:
                kwargs = {"sep": "\t"} if ext == ".tsv" else {}
                df = self.connector.load_csv(str(file_path), **kwargs)
            elif ext in {".xlsx", ".xls"}:
                df = self.connector.load_excel(str(file_path))

            if df is not None:
                table_name = file_path.stem
                self.data_dfs[table_name] = df
                self.ingestion_reports.append(self.connector.ingestion_report(df, table_name))

    def load_sql_query(self, connection_string: str, query: str, table_name: str) -> None:
        df = self.connector.load_sql(connection_string, query)
        self.data_dfs[table_name] = df
        self.ingestion_reports.append(self.connector.ingestion_report(df, table_name))

    # ── Databricks Delta loader ───────────────────────────────────────────

    def load_databricks_query(
        self,
        query: str,
        table_name: str,
        server_hostname: Optional[str] = None,
        http_path: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        """Load data from a Databricks SQL warehouse (Delta Lake) into the pipeline.

        Credentials fall back to DATABRICKS_HOST / DATABRICKS_HTTP_PATH / DATABRICKS_TOKEN
        environment variables when not supplied explicitly.
        """
        df = self.connector.load_databricks(
            query=query,
            server_hostname=server_hostname,
            http_path=http_path,
            access_token=access_token,
        )
        self.data_dfs[table_name] = df
        self.ingestion_reports.append(self.connector.ingestion_report(df, table_name))

    # ── Context loaders ───────────────────────────────────────────────────

    def load_context(self, folder_path: str) -> None:
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"Context folder not found: {folder_path}")

        for file_path in folder.iterdir():
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lower()
            if ext == ".pdf":
                self.context_manager.ingest_pdf(str(file_path))
            elif ext in {".pptx", ".ppt"}:
                self.context_manager.ingest_powerpoint(str(file_path))
            elif ext in {".docx"}:
                self.context_manager.ingest_word(str(file_path))
            elif ext in {".txt", ".md"}:
                self.context_manager.add_raw_context(file_path.name, file_path.read_text(encoding="utf-8"))

    # ── Agent ─────────────────────────────────────────────────────────────

    def register_column_mapping(self, mapping: ColumnMapping) -> None:
        self.data_registry.register_column(mapping)

    def initialize_agent(
        self,
        anthropic_api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-latest",
    ) -> None:
        self.agent = DataQueryAgent(
            data_registry=self.data_registry,
            context_manager=self.context_manager,
            data_dfs=self.data_dfs,
            anthropic_api_key=anthropic_api_key,
            model=model,
        )

    def ask(self, question: str) -> str:
        if self.agent is None:
            self.initialize_agent()
        assert self.agent is not None
        return self.agent.query(question)

    def interactive_mode(self) -> None:
        if self.agent is None:
            self.initialize_agent()

        print("SmartDataPipeline interactive mode. Type '/salir' to exit.")
        while True:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in {"/salir", "/exit", "exit", "quit"}:
                print("Session closed.")
                break
            if not user_input:
                continue
            answer = self.ask(user_input)
            source = getattr(self.agent, "last_source", "Local")
            print(f"\nAgent [{source}]:\n{answer}")
