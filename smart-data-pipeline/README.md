# Smart Data Pipeline

Pipeline de análisis de datos en lenguaje natural. Cargás tus archivos, definís los mapeos de columnas y hacés preguntas en español (o inglés) sobre tus datos.

---

## Estructura del proyecto

```
smart-data-pipeline/
├── run.py                    ← Punto de entrada
├── pipeline_orchestrator.py  ← Orquestador principal
├── query_agent.py            ← Motor de consultas NL + LLM
├── data_connector.py         ← Carga de CSV, Excel, SQL
├── mapping_registry.py       ← Registro de aliases de columnas
├── context_manager.py        ← Ingesta de documentos de contexto
├── smart_data_models.py      ← Modelos de datos (ColumnMapping)
├── requirements.txt
├── .env.example
│
├── input_data/               ← Tus archivos CSV / Excel
├── mappings/                 ← JSONs con mapeos de columnas
└── context_docs/             ← PDFs, PPTX, DOCX, TXT de contexto
```

---

## Instalación

```bash
pip install -r requirements.txt
```

Copiá `.env.example` a `.env` y completá con tu proveedor LLM:

```bash
cp .env.example .env
```

---

## Configuración del LLM (`.env`)

El agente soporta dos proveedores. Si configurás ambos, **Anthropic tiene prioridad**.

### Opción A — GitHub Models (Copilot)
```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxx   # PAT con scope models:read
GITHUB_MODEL=gpt-4o-mini        # opcional, default: gpt-4o-mini
```

### Opción B — Anthropic
```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxx
```

> Sin LLM configurado el agente igual responde, usando solo el motor local (Pandas).

---

## Uso rápido

1. Copiá tus archivos a las carpetas correspondientes:

   | Carpeta | Contenido |
   |---|---|
   | `input_data/` | CSV, XLSX, XLS, TSV |
   | `mappings/` | JSONs con aliases de columnas |
   | `context_docs/` | TXT, PDF, PPTX, DOCX con contexto de negocio |

2. Ejecutá:

```bash
python run.py
```

3. Escribí preguntas en lenguaje natural:

```
You: que equipo tiene mayor produccion
You: dame el promedio de toneladas por turno
You: quien es juan perez
You: produccion por zona
```

---

## Mapeos de columnas

Los mapeos le indican al agente cómo llamar a las columnas del archivo. Sin mapeos, el agente no puede resolver aliases.

**Formato JSON** (`mappings/mis_mapeos.json`):

```json
[
  {
    "column_name": "toneladas_producidas",
    "aliases": ["produccion", "toneladas", "output", "tons"],
    "business_description": "Toneladas producidas por turno",
    "data_type": "float",
    "examples": [120.5, 98.3],
    "category": "produccion"
  },
  {
    "column_name": "equipo_minero",
    "aliases": ["equipo", "maquina", "team", "flota"],
    "business_description": "Identificador del equipo o máquina",
    "data_type": "string",
    "examples": ["Equipo-A", "Equipo-B"],
    "category": "operaciones"
  }
]
```

Podés tener múltiples archivos JSON en `mappings/` — todos se cargan automáticamente.

---

## Tipos de consulta soportados

El agente detecta automáticamente el tipo de operación según la pregunta y el tipo de columna detectada.

| Tipo | Ejemplo | Lógica |
|---|---|---|
| **Suma** | "dame el total de produccion" | `sum()` sobre columna numérica |
| **Promedio** | "cual es el promedio de toneladas" | `mean()` sobre columna numérica |
| **Conteo** | "cuantos turnos hay" | `count()` |
| **Agrupación** | "produccion por equipo" | `groupby(cat) → agg(num)` |
| **Lista** | "que equipos tenemos" | valores únicos + agrupación con numérica |
| **Perfil de entidad** | "quien es equipo-a" / "hablame del turno norte" | lookup de valor en datos + stats |
| **Filtro temporal** | "produccion del mes pasado" | filtra por columna datetime |
| **Follow-up** | "y el promedio?" | reutiliza el último mapeo detectado |

---

## Arquitectura del flujo

```
Pregunta del usuario
        │
        ▼
_detect_value_lookup()          ← ¿alguna palabra de la pregunta
        │                          aparece como valor en los datos?
        │  (prioridad alta)        Ej: "norte", "equipo-a", "juan"
        │
        ▼ (si no hay valor exacto)
_detect_all_mappings()          ← detecta columnas mencionadas vía aliases
        │
        ├── 1 columna numérica   → sum / mean / count
        ├── 1 columna categórica → groupby con numérica disponible
        └── cat + num detectadas → groupby explícito
        │
        ▼
local_answer  (Pandas, determinístico)
        │
        ▼
_try_generate_with_llm()        ← enriquece la respuesta con narrativa
        │  (opcional, requiere token)
        │
        ▼
Respuesta final  [LLM] o [Local]
```

### Cómo se usa el contexto de negocio

El contexto **no filtra ni modifica los datos**. Se entrega al LLM junto con los números ya calculados para que los interprete con vocabulario de negocio:

```
DataFrame (Pandas) → cálculo → local_answer
                                      ↘
                                       LLM prompt → respuesta narrativa
                                      ↗
context_docs/ → texto plano → context[:6000 chars]
```

---

## API programática

```python
from pipeline_orchestrator import SmartDataPipeline

p = SmartDataPipeline()

# Cargar datos
p.load_data_from_folder("input_data")          # CSV, Excel
p.load_sql_query("sqlite:///db.sqlite", "SELECT * FROM tabla", "mi_tabla")

# Cargar mapeos y contexto
p.data_registry.load_from_folder("mappings")
p.load_context("context_docs")

# Iniciar agente (lee LLM config desde .env automáticamente)
p.initialize_agent()

# Consulta única
respuesta = p.ask("que equipo produce mas?")

# Modo chat interactivo
p.interactive_mode()
```

---

## Fuentes de datos soportadas

| Formato | Método |
|---|---|
| CSV / TSV | `load_data_from_folder()` |
| Excel (.xlsx, .xls) | `load_data_from_folder()` |
| SQL (cualquier DB via SQLAlchemy) | `load_sql_query(connection_string, query, nombre)` |

**Documentos de contexto:**

| Formato | Notas |
|---|---|
| TXT, MD | Lectura directa |
| PDF | Requiere `pdfplumber` |
| PPTX | Requiere `python-pptx` |
| DOCX | Requiere `python-docx` |

---

## Dependencias principales

| Librería | Uso |
|---|---|
| `pandas` | Motor de cálculo sobre datos tabulares |
| `rapidfuzz` | Matching fuzzy de aliases (umbral 70%) |
| `openai` | Cliente para GitHub Models (endpoint Azure) |
| `anthropic` | Cliente para Claude |
| `python-dotenv` | Carga de `.env` |
| `sqlalchemy` | Conexión a bases de datos SQL |
| `pdfplumber` | Extracción de texto de PDFs |
| `python-pptx` | Extracción de texto de PowerPoints |
| `python-docx` | Extracción de texto de Word |
