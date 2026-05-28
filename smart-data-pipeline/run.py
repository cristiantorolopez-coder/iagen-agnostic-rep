"""Entry point. Just run: python run.py

Flow:
  1. Load all CSV/Excel from  input_data/
  2. Load all JSON mappings from mappings/
  3. Load all context docs from  context_docs/
  4. Start interactive chat
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from pipeline_orchestrator import SmartDataPipeline

BASE = Path(__file__).resolve().parent
# Buscar .env en la carpeta del proyecto o en la raíz del repo (un nivel arriba).
for _env_path in (BASE / ".env", BASE.parent / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path)
        break


def main() -> None:
    pipeline = SmartDataPipeline()

    # ── 1. Datos tabulares ────────────────────────────────────────────────
    input_dir = BASE / "input_data"
    pipeline.load_data_from_folder(str(input_dir))
    if pipeline.data_dfs:
        print(f"[OK] Tablas cargadas: {list(pipeline.data_dfs.keys())}")
    else:
        print("[WARN] No se encontraron archivos en input_data/")

    # ── 2. Mapeos de columnas ─────────────────────────────────────────────
    mappings_dir = BASE / "mappings"
    n = pipeline.data_registry.load_from_folder(str(mappings_dir))
    if n:
        names = [m.column_name for m in pipeline.data_registry.list_mappings()]
        print(f"[OK] {n} mapeo(s) cargado(s): {names}")
    else:
        print("[WARN] No se encontraron JSONs en mappings/")

    # ── 3. Contexto de negocio ────────────────────────────────────────────
    context_dir = BASE / "context_docs"
    pipeline.load_context(str(context_dir))
    ctx_preview = pipeline.context_manager.get_all_context()
    if ctx_preview.strip():
        print(f"[OK] Contexto cargado ({len(ctx_preview)} caracteres)")
    else:
        print("[INFO] Sin documentos de contexto — podés agregar PDFs/TXT en context_docs/")

    # ── 4. Chat ───────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("  Chat listo. Escribe /salir para terminar.")
    print("=" * 55)
    pipeline.interactive_mode()


if __name__ == "__main__":
    main()
