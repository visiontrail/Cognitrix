# Cognitrix — Plataforma de BI y analítica AI-Native

[English](README.md) | [简体中文](README_CN.md) | [हिन्दी](README_HI.md) | Español | [日本語](README_JA.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-powered-yellow.svg)](https://duckdb.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Sube un Excel → pregunta en lenguaje natural → obtén gráficos y paneles.**
> Cognitrix es una plataforma open source de inteligencia empresarial AI-native que convierte hojas de cálculo estructuradas en un espacio de analítica interactivo, sin exigir SQL, un data warehouse ni paneles preparados de antemano.

---

## ¿Qué es Cognitrix?

Cognitrix sustituye la pila tradicional de BI —pipelines ETL, paneles rígidos y conocimientos de SQL— por un agente conversacional. El agente entiende el esquema de las tablas, selecciona métricas semánticas, ejecuta SQL seguro de solo lectura y genera visualizaciones bajo demanda.

| Capacidad | BI tradicional | Cognitrix |
|---|---|---|
| Incorporación de datos | Warehouse y ETL | Carga directa de Excel |
| Consultas | Drag-and-drop o SQL | Conversación en lenguaje natural |
| Creación de gráficos | Configuración manual | Especificaciones generadas por IA |
| Análisis ad hoc | Depende de analistas | Autoservicio |
| Control de acceso | A nivel de panel | RBAC y seguridad por filas |
| Colaboración | Enlaces estáticos | Workspaces persistentes, invitaciones y publicación |

---

## Funciones principales

- **Analítica en lenguaje natural** — Pregunta sobre datos de plantilla, proyectos, ventas, finanzas u operaciones y recibe gráficos, tablas y conclusiones breves.
- **Ingesta agéntica de Excel** — Inspecciona el libro, propone un esquema, confirma la configuración del catálogo, exige aprobación humana y limita la escritura de DuckDB al esquema aprobado.
- **Motor de consultas agéntico** — Un bucle ReAct basado en Claude Agent SDK explora las tablas, elige métricas semánticas y solo ejecuta SQL de lectura.
- **Capa de métricas semánticas** — Las métricas YAML estabilizan el cálculo de KPI como plantilla, rotación, velocidad o consumo de presupuesto.
- **Visualización avanzada** — ECharts renderiza visualizaciones complejas; Recharts cubre gráficos habituales, tablas y tarjetas KPI.
- **Workspace visual y Agent Canvas** — Organiza gráficos manualmente en un lienzo multiformato o permite que el Agent Canvas opcional construya un panel de varias páginas a partir de un esquema aprobado.
- **Varios gráficos y Saved Prompts** — Genera un conjunto confirmado de gráficos con una sola pregunta y reutiliza prompts con variables y capacidades preseleccionadas.
- **Colaboración persistente** — Los workspaces, conversaciones, mensajes, activos gráficos y snapshots del lienzo se guardan en el servidor; localStorage se mantiene como caché rápida y origen de migración.
- **Miembros, invitaciones y publicación** — Roles owner/editor/viewer, invitaciones con caducidad y páginas publicadas con visibilidad `public`, `registered` o `allowlist`.
- **Seguridad** — JWT, RBAC, inyección RLS, ocultación de columnas sensibles, validación de SQL de solo lectura, auditoría y defensas contra jailbreak.
- **Investigación web opcional** — Herramientas Bocha o Tavily protegidas por feature flag y límites explícitos por turno.
- **Panel de administración** — Un superadmin gestiona ajustes de runtime, credenciales de modelos, usuarios, roles, estado de cuentas, telemetría y Agent Skills. Los secretos son de solo escritura.

---

## Arquitectura funcional

[![Arquitectura funcional de Cognitrix](docs/diagrams/functional-architecture-es.svg)](docs/diagrams/functional-architecture-es.html)

### Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI, Pydantic Settings, Python 3.11+ |
| Analítica | DuckDB, Pandas, sqlglot |
| Runtime del agente | Claude Agent SDK, protocolo Anthropic Messages |
| Frontend | Next.js 15, React 18, TypeScript |
| Estado | Zustand, TanStack Query |
| Visualización | ECharts, Recharts, React Flow |
| Seguridad | JWT, RBAC, RLS, validador SQL |
| Almacenamiento | DuckDB, SQLite, filesystem y caché del navegador |

El gateway compatible con Anthropic de DeepSeek es el proveedor predeterminado. Se puede elegir Anthropic/Claude nativo u otro endpoint compatible mediante variables de entorno.

---

## Inicio rápido

Requisitos: Python 3.11+, Node.js 20+, npm 10+ y GNU Make.

```bash
make bootstrap
make env-check
make dev
```

Abre [http://127.0.0.1:3000](http://127.0.0.1:3000) y sube uno de los libros Excel de `sample_data/`.

### Cuenta de administración local

Un entorno de desarrollo local nuevo, creado desde `.env.example`, incluye este superadmin:

- Correo: `admin@cognitrix.local`
- Contraseña: `Admin@123456`
- Consola: `http://127.0.0.1:3000/admin`

Antes del primer arranque, cambia `AUTH_BOOTSTRAP_ADMIN_EMAIL`, `AUTH_BOOTSTRAP_ADMIN_PASSWORD` y `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL`, o déjalos vacíos para desactivar el bootstrap. El backend rechaza la contraseña documentada cuando `APP_ENV=production`.

---

## Estado actual

- El workspace principal ofrece los modos Chat, Canvas, Split y Catalog. Atajos: `Cmd/Ctrl + 1/2/3/4`; `Cmd/Ctrl + B` muestra u oculta la barra lateral.
- El chat emite `planning`, `tool_use`, `tool_result`, `spec`, `final` y `error`. Agent Canvas añade eventos `canvas_op` ordenados y persistentes cuando está habilitado.
- El lienzo admite gráficos, texto, notas, divisores, secciones y grupos; múltiples formatos de página, fondos, cuadrículas web, paneles multipágina, exportación, impresión, guardado automático y undo por ejecución.
- Conversaciones, mensajes, activos y snapshots se guardan en el servidor y se combinan con la caché local durante la recuperación entre dispositivos.
- La plantilla de desarrollo del repositorio desactiva Agent Canvas, la investigación web y los Agent Skills de runtime; cada función requiere configuración explícita.
- El repositorio incluye tests de backend, seguridad, integración, evaluación, rendimiento, scripts, smoke, frontend y Playwright. El producto sigue en evolución activa.

---

## Estructura del repositorio

```text
.
├── apps/api              # Backend FastAPI
├── apps/web              # Frontend Next.js
├── models                # Métricas semánticas YAML
├── sample_data           # Libros Excel de ejemplo
├── tests                 # Tests de backend, seguridad, integración, eval y smoke
├── scripts               # Setup, checks, tests, deploy y mantenimiento
├── deploy                # Guías/activos de despliegue en servidor y Hugging Face
├── docs/adr              # Decisiones de arquitectura
├── infra/docker          # Configuraciones Compose alternativas
├── openspec              # Propuestas de cambio, specs y tareas de implementación
└── packages/shared       # Placeholder del paquete compartido
```

---

## Comandos habituales

```bash
make help              # Targets disponibles
make bootstrap         # Dependencias y archivos .env
make env-check         # Validación del entorno
make dev               # API y Web
make dev-api           # Solo FastAPI
make dev-web           # Solo Next.js
make lint              # Comprobaciones de compilación/lint
make test              # Suite pytest del backend
make build             # Build web de producción + compile check del backend
make smoke-local       # Flujo smoke end-to-end local
make test-all          # Gate previsto; consulta los límites actuales
make docker-up         # Iniciar el stack Compose
make docker-down       # Detener el stack Compose
make docker-publish    # Construir y publicar imágenes API/Web en Docker Hub
make docker-restart    # Rebuild/restart conservando los datos
make deploy            # Despliegue del servidor en un comando
make hf-deploy         # Despliegue en Hugging Face Spaces
make reset-local-data  # Limpiar datos locales de runtime
```

---

## Configuración

`make bootstrap` crea `apps/api/.env` y `apps/web/.env` cuando no existen. Ajustes principales del backend:

```env
DATABASE_URL=sqlite:///./data/uploads/state/ai_views.sqlite3
MODEL_PROVIDER_URL=https://api.deepseek.com
AI_API_KEY=
AI_MODEL=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=
CLAUDE_AGENT_SDK_ENABLED=true
AGENTIC_INGESTION_ENABLED=false
AGENT_CANVAS_MODE_ENABLED=false
WEB_SEARCH_ENABLED=false
AGENT_SKILLS_ENABLED=false
AUTH_SECRET=replace-with-a-strong-secret
UPLOAD_DIR=./data/uploads
CORS_ALLOW_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

Las cargas de Excel siempre siguen el ciclo Agentic Ingestion. `AGENTIC_INGESTION_ENABLED` solo se conserva por compatibilidad con entornos antiguos y ya no desactiva las rutas `/ingestion/*`.

El servidor web reenvía las llamadas del navegador mediante el proxy de mismo origen `/api/backend/*`. Usa `API_BASE_URL` como destino en runtime; la plantilla local conserva `NEXT_PUBLIC_API_BASE_URL` como fallback. No incrustes IP de despliegue en variables `NEXT_PUBLIC_*` durante el build.

---

## Runtime del agente e ingesta

Herramientas BI base:

- `list_tables`
- `describe_table`
- `sample_rows`
- `get_metric_catalog`
- `run_semantic_query`
- `execute_readonly_sql`
- `get_distinct_values`
- `save_view`

La investigación web añade `web_search`, `web_fetch` y `save_web_research` cuando está habilitada. Agent Canvas tiene una superficie separada y restringida; no obtiene acceso arbitrario al filesystem ni a la red.

Ciclo de ingesta:

1. `POST /ingestion/uploads`
2. `POST /ingestion/plan`
3. `POST /ingestion/setup/confirm`, si es necesario
4. `POST /ingestion/approve`
5. `POST /ingestion/execute`

Cada escritura queda limitada al esquema aprobado. Los identificadores y tipos de DuckDB se validan con allowlists estrictas.

---

## Cuentas, colaboración y publicación

- Registro: `POST /auth/register`
- Login: `POST /auth/email-login`
- Miembros del workspace: owner, editor y viewer
- Invitaciones: enlaces con caducidad aceptados por usuarios autenticados
- Publicación: visibilidad `public`, `registered` o `allowlist`
- Ruta publicada: `/p/{token}`
- Saved views heredadas: versionado, rollback y `/share/{view_id}` protegido por permisos

El endpoint heredado y sin credenciales `POST /auth/login` solo funciona en desarrollo y se rechaza en producción.

---

## Tests y despliegue

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tests/security -q
cd apps/web && npx vitest run
cd apps/web && npx playwright test
make smoke-local
```

Despliegue del servidor en un comando:

```bash
PUBLIC_URL=http://172.16.5.38:3000 bash scripts/deploy.sh
```

El script genera secretos y una contraseña aleatoria de superadmin, habilita Agent Canvas, construye e inicia el stack, espera los health checks y muestra las credenciales. Volver a ejecutarlo no elimina el volumen persistente. Consulta [deploy/README.md](deploy/README.md).

---

## Datos de ejemplo y reset

`sample_data/` contiene libros de HR, ventas, finanzas, project management y tablas vinculadas, con muestras en inglés y chino. Tras una carga, usa el `dataset_table` devuelto en el contexto de consultas y chat.

Previsualiza el reset local:

```bash
.venv/bin/python scripts/maintenance/reset_local_data.py --dry-run
```

Ejecuta `make reset-local-data` para el reset local real. Los volúmenes Docker solo se eliminan mediante la opción explícita `--include-docker-volumes` y confirmación; start, stop, restart y rebuild normales conservan los datos.

---

## Límites conocidos

- localStorage sigue siendo la caché síncrona; la sincronización con el servidor es best-effort. Un fallo temporal de red puede dejar una copia local hasta el siguiente commit o hydration correcto.
- Las funciones opcionales del agente necesitan credenciales del proveedor y límites adecuados para producción.
- La calidad del modelo, control de costes, UX de sesiones largas y cobertura de evaluaciones deben ajustarse para cada despliegue.
- Existen suites Vitest y Playwright, pero `apps/web/package.json` aún no expone scripts unificados `npm test`, `test:ui` o `test:e2e`.

---

## Contribuir

Lee [CONTRIBUTING.md](CONTRIBUTING.md) para proponer issues, funciones y pull requests. Cognitrix se distribuye bajo la licencia MIT.
