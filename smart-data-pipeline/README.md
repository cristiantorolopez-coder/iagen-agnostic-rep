# Smart Data Pipeline

API de análisis de datos en lenguaje natural. Carga archivos o conecta Databricks Delta y consulta tus datos en español vía REST.

**Stack:** Django 6 · Django REST Framework · Pandas · Anthropic / GitHub Models · Databricks SQL Connector

---

## Estructura

```
smart-data-pipeline/
├── manage.py               ← entry point Django
├── config/                 ← settings, urls, wsgi, asgi
├── api/                    ← endpoints REST (views, serializers, urls)
├── core/                   ← lógica de negocio
│   ├── pipeline_orchestrator.py
│   ├── query_agent.py
│   ├── data_connector.py   ← CSV, Excel, SQL, Databricks Delta
│   ├── mapping_registry.py
│   ├── context_manager.py
│   └── smart_data_models.py
├── input_data/             ← tus archivos CSV / Excel
├── mappings/               ← JSONs con aliases de columnas
└── context_docs/           ← TXT, PDF, PPTX, DOCX de contexto
```

---

## 1. Instalación

```bash
pip install -r requirements.txt
copy .env.example .env      # Windows
```

Edita `.env` con tu proveedor LLM (ver sección abajo).

---

## 2. Levantar la API

```bash
python manage.py migrate
python manage.py runserver 8000
```

Servidor listo en → `http://127.0.0.1:8000`

> En Windows usa la ruta completa si da error:
> `python "C:\...\smart-data-pipeline\manage.py" runserver 8000`

---

## 3. Endpoints

| Método | URL | Descripción |
|---|---|---|
| `GET` | `/api/health/` | Estado del pipeline |
| `POST` | `/api/chat/` | Consulta en lenguaje natural |
| `POST` | `/api/databricks/load/` | Carga una Delta table en runtime |

---

## 4. Usar desde Bruno (o Postman)

### Health check
```
GET  http://127.0.0.1:8000/api/health/
```

### Chat
```
POST  http://127.0.0.1:8000/api/chat/
Body → JSON:
```
```json
{
  "question": "cual es el total de ventas?",
  "session_id": "yo"
}
```

> En Bruno: pestaña **Body** → dropdown **`No Body`** → selecciona **`JSON`** → pega el body → **Send**.

Respuesta:
```json
{
  "answer": "El total de ventas es USD 12,730...",
  "source": "LLM",
  "session_id": "yo"
}
```

### Cargar tabla Databricks
```
POST  http://127.0.0.1:8000/api/databricks/load/
Body → JSON:
```
```json
{
  "query": "SELECT * FROM catalog.schema.tabla LIMIT 10000",
  "table_name": "ventas_delta"
}
```
> El token se lee de `DATABRICKS_TOKEN` en `.env`, nunca del body.

---

## 5. Variables de entorno (`.env`)

```env
# Django
DJANGO_SECRET_KEY=cambia-esto-en-produccion
DJANGO_DEBUG=True

# LLM — Opción A: Anthropic (tiene prioridad)
ANTHROPIC_API_KEY=sk-ant-...

# LLM — Opción B: GitHub Models / Copilot
GITHUB_TOKEN=github_pat_...
GITHUB_MODEL=gpt-4o-mini

# Databricks Delta (opcional)
DATABRICKS_HOST=adb-xxx.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxx
DATABRICKS_TOKEN=dapi...
```

Sin LLM configurado, el agente responde igual usando solo Pandas (modo local).

---

## 6. Agregar tus datos

**Archivos:** copia CSV o Excel a `input_data/` — se cargan automáticamente al iniciar.

**Mapeos** (`mappings/mis_mapeos.json`): le enseñan al agente cómo se llaman tus columnas:

```json
[
  {
    "column_name": "amount_usd",
    "aliases": ["ventas", "total", "monto", "revenue"],
    "business_description": "Monto de venta en USD",
    "data_type": "float",
    "examples": [1200.5, 850.0],
    "category": "finanzas"
  }
]
```

**Contexto** (`context_docs/`): TXT, PDF, PPTX, DOCX con información del negocio. El LLM lo usa para enriquecer las respuestas.

---

## 7. Tipos de consulta soportados

| Pregunta | Operación |
|---|---|
| "total de ventas" | suma |
| "promedio de ventas" | media |
| "cuántos registros hay" | conteo |
| "ventas por zona" | groupby |
| "háblame de cliente X" | perfil de entidad (lookup) |
| "y el mes pasado?" | filtro temporal + follow-up |

