from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pipeline_orchestrator import SmartDataPipeline
from core.query_agent import DataQueryAgent
from api.serializers import (
    ChatRequestSerializer,
    ChatResponseSerializer,
    DatabricksLoadRequestSerializer,
    DatabricksLoadResponseSerializer,
)

# ── Pipeline singleton ────────────────────────────────────────────────────
# Loaded once on first request; data, mappings and context stay in memory.

_pipeline_lock = threading.Lock()
_pipeline: Optional[SmartDataPipeline] = None

# Per-session agents keep independent conversation histories.
_agents: dict[str, DataQueryAgent] = {}
_agents_lock = threading.Lock()


def _get_pipeline() -> SmartDataPipeline:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                BASE = Path(__file__).resolve().parent.parent
                p = SmartDataPipeline()

                input_dir = BASE / "input_data"
                if input_dir.exists():
                    p.load_data_from_folder(str(input_dir))

                mappings_dir = BASE / "mappings"
                if mappings_dir.exists():
                    p.data_registry.load_from_folder(str(mappings_dir))

                context_dir = BASE / "context_docs"
                if context_dir.exists():
                    p.load_context(str(context_dir))

                _pipeline = p
    return _pipeline


def _get_agent(session_id: str) -> DataQueryAgent:
    with _agents_lock:
        if session_id not in _agents:
            pipeline = _get_pipeline()
            _agents[session_id] = DataQueryAgent(
                data_registry=pipeline.data_registry,
                context_manager=pipeline.context_manager,
                data_dfs=pipeline.data_dfs,
            )
        return _agents[session_id]


# ── Views ─────────────────────────────────────────────────────────────────

class HealthView(APIView):
    """GET /api/health/ — liveness probe."""

    def get(self, request: Request) -> Response:
        pipeline = _get_pipeline()
        return Response(
            {
                "status": "ok",
                "tables_loaded": list(pipeline.data_dfs.keys()),
                "mappings_count": len(pipeline.data_registry.list_mappings()),
            }
        )


class ChatView(APIView):
    """POST /api/chat/ — send a natural-language question to the chatbot.

    Request body:
        {
            "question": "¿Cuál fue el total de ventas del mes pasado?",
            "session_id": "user-abc123"   // optional, defaults to "default"
        }

    Response:
        {
            "answer": "...",
            "source": "LLM | Local",
            "session_id": "user-abc123"
        }
    """

    def post(self, request: Request) -> Response:
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_id: str = serializer.validated_data["session_id"]
        question: str = serializer.validated_data["question"]

        agent = _get_agent(session_id)
        answer = agent.query(question)

        response_data = {
            "answer": answer,
            "source": agent.last_source,
            "session_id": session_id,
        }
        return Response(ChatResponseSerializer(response_data).data)


class DatabricksLoadView(APIView):
    """POST /api/databricks/load/ — pull a Delta table into the pipeline at runtime.

    The Databricks access token is read from the DATABRICKS_TOKEN environment
    variable and is never accepted in the request body.

    Request body:
        {
            "query": "SELECT * FROM catalog.schema.table LIMIT 10000",
            "table_name": "ventas_delta",
            "server_hostname": "adb-xxx.azuredatabricks.net",  // optional
            "http_path": "/sql/1.0/warehouses/xxx"             // optional
        }

    Response:
        {
            "table_name": "ventas_delta",
            "rows": 10000,
            "columns": ["fecha", "producto", "monto", ...]
        }
    """

    def post(self, request: Request) -> Response:
        serializer = DatabricksLoadRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        pipeline = _get_pipeline()
        data = serializer.validated_data

        try:
            pipeline.load_databricks_query(
                query=data["query"],
                table_name=data["table_name"],
                server_hostname=data["server_hostname"] or None,
                http_path=data["http_path"] or None,
                # access_token intentionally not accepted from request body (security)
            )
        except (KeyError, ImportError, RuntimeError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        df = pipeline.data_dfs[data["table_name"]]
        response_data = {
            "table_name": data["table_name"],
            "rows": len(df),
            "columns": list(df.columns),
        }
        return Response(
            DatabricksLoadResponseSerializer(response_data).data,
            status=status.HTTP_201_CREATED,
        )
