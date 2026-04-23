# Changelog — Proyecto Finanzas Personales

## [v0.14] — 2026-04-22 — Fix flujos vacíos en cloud (transaction state + name mismatch)

### Bugs encontrados y corregidos
- **Transaction state corruption**: `_ensure_*_flows_table()` se llamaba dentro de funciones de lectura. Si fallaba en PostgreSQL, la transacción quedaba abortada y TODOS los SELECT posteriores fallaban silenciosamente. Fix: eliminar `_ensure_*_table` de funciones de lectura, solo usarlas en escritura. Agregar `conn.rollback()` en except.
- **Name mismatch Fintual**: La API devuelve `"💰 Muy Arriesgada"` (con emoji), sync guardaba `"Muy Arriesgada"` (sin emoji). Fix: función `_clean_fund_name()` normaliza nombres quitando emojis del inicio.
- **Silent exception swallowing**: Todos los `except Exception: pass` en dashboard reemplazados con logging para diagnóstico.

### Archivos modificados
- `services/cache.py` — `_clean_fund_name()`, rollback en `_ensure_*_table`, quitar `_ensure_*_table` de funciones de lectura
- `dashboard/app.py` — logging en fallbacks de flows
- `CLAUDE.md` — v0.14
- `CHANGELOG.md` — esta entrada

---

## [v0.13] — 2026-04-22 — Flujos Fintual cacheados en DB + resilencia cloud

### ✅ Logrado
- **Flujos Fintual cacheados en DB**: nueva tabla `fintual_flows` en Supabase. `sync` guarda flujos de cada fondo Fintual. El cloud los lee de DB sin necesitar Playwright
- **`load_fintual_flows` resiliente**: try/except + fallback a DB cache (mismo patrón que Binance)
- **`load_binance_history` con logging**: si CoinGecko retorna vacío en cloud, ahora se loguea para diagnóstico
- **`sync` sincroniza flujos Fintual**: además de Binance, ahora guarda flujos de cada fondo Fintual en Supabase

### Archivos modificados
- `services/cache.py` — tabla `fintual_flows` + `_ensure_fintual_flows_table()` + `save_fintual_flows()` + `get_fintual_flows_cached()`
- `dashboard/app.py` — `load_fintual_flows` resiliente con DB fallback + logging en `load_binance_history`
- `cli/main.py` — sync guarda flujos Fintual en DB
- `CLAUDE.md` — v0.13, flujos Fintual cacheados
- `CHANGELOG.md` — esta entrada

---

## [v0.12] — 2026-04-22 — Cloud: fallback DB Binance, CoinGecko, login persistente

### ✅ Logrado
- **Fix `cannot unpack non-iterable Portfolio object`**: unpacking defensivo en `load_live_portfolio()` para manejar tanto retorno simple como tupla de `get_portfolio()`
- **Fallback Binance balances a DB**: cuando la API de Binance falla (geo-restricción desde cloud), el dashboard rellena desde el último snapshot de Supabase — igual que Fintual
- **Login persistente**: el token de autenticación se guarda en `st.query_params` (URL). Al refrescar el browser, el usuario sigue logueado sin re-ingresar credenciales
- **Historial de precios crypto → CoinGecko**: `get_binance_price_history()` ahora usa `api.coingecko.com` en vez de `api.binance.com/api/v3/klines`. CoinGecko es público, sin auth y sin geo-restricción — funciona desde cloud
- **Flujos Binance P2P cacheados en DB**: nueva tabla `binance_flows` en Supabase. `sync` guarda los flujos P2P. El dashboard lee de DB cuando la API de Binance no está disponible
- **Banner simplificado**: "Algunos datos provienen del último sync (fecha)" en vez de mensajes separados para cada plataforma

### Causa raíz de los fallos en cloud
`api.binance.com` está **completamente bloqueado** desde servidores EEUU (donde vive Streamlit Cloud). Esto incluye endpoints públicos y autenticados. La solución fue:
- Balances → fallback a DB
- Historial precios → CoinGecko (API alternativa pública)
- Flujos P2P → cache en DB via `sync`

### Archivos modificados
- `dashboard/app.py` — fallback Binance, login persistente, banner simplificado, load_binance_flows con fallback DB
- `services/historical.py` — CoinGecko en vez de Binance klines
- `services/cache.py` — tabla `binance_flows` + `save_binance_flows()` + `get_binance_flows_cached()`
- `cli/main.py` — sync guarda flujos Binance en DB
- `CLAUDE.md` — v0.12, documentación geo-restricción Binance
- `CHANGELOG.md` — esta entrada

---

## [v0.11] — 2026-04-20 — Auth, Binance errors, Fintual API via cookie

### ✅ Logrado
- **Autenticación usuario+contraseña** en el dashboard
  - Gate de login con `st.session_state` + `AUTH_USERNAME`/`AUTH_PASSWORD` en secrets
  - Botón "Cerrar sesión" en sidebar
- **Errores Binance visibles**: `get_portfolio()` devuelve `(portfolio, errors)` — dashboard muestra `st.warning` cuando un conector falla en vez de mostrar 0 silenciosamente
- **Fintual via API REST directa** (sin Playwright en cloud):
  - `GET /api/goals` con cookie de sesión `_fintual_session_cookie` funciona sin OTP
  - `FintualAPIClient` en `connectors/fintual.py` — connector HTTP puro
  - `aggregator.py` usa `FintualAPIClient` si `FINTUAL_SESSION_COOKIE` está en env/secrets
  - `setup-fintual` ahora imprime la cookie para copiar a Streamlit Cloud
  - Cloud ya puede obtener datos Fintual en vivo (no depende de cron en Mac)

### 🔑 Secrets en Streamlit Cloud
```toml
AUTH_USERNAME = "benjaminapt"
AUTH_PASSWORD = "tu_clave"
FINTUAL_SESSION_COOKIE = "valor_de_setup-fintual"  # dura ~30 días
```

### Archivos modificados
- `dashboard/app.py` — auth gate + logout + connector_errors display + banner actualizado
- `services/aggregator.py` — get_portfolio() devuelve (Portfolio, errors_dict)
- `connectors/fintual.py` — nueva clase FintualAPIClient
- `cli/main.py` — setup-fintual imprime cookie; get_portfolio() desempacado con _

---

## [v0.10] — 2026-04-20 — Deploy Streamlit Community Cloud + Supabase

### ✅ Logrado
- **Deploy en Streamlit Community Cloud**: app pública en `https://dcdymygparwpmzqlcykrvn.streamlit.app/`
- **Base de datos Supabase**: PostgreSQL cloud gratuita (proyecto `jxwaxheeyfgaszrftpjv`)
  - Conexión via **Transaction Pooler** (`aws-1-us-west-2.pooler.supabase.com:6543`) para compatibilidad IPv4
  - La conexión directa (`db.*.supabase.co:5432`) usa IPv6, no compatible con Streamlit Cloud
- **Fix crítico**: `dashboard/app.py` ahora sincroniza `st.secrets` → `os.environ` al arrancar
  - Streamlit Cloud expone secrets via `st.secrets`, no `os.environ`; `services/cache.py` usa `os.getenv("DATABASE_URL")`
  - Sin este fix, `_DB_URL` quedaba en `None` y el app usaba SQLite vacío
- **GitHub**: repo público `benjaminapt/finanzas-personales` con 3 commits
- **Cron Mac**: sync diario a las 8am → `~/.finanzas/sync.log`
  - Fintual requiere Playwright (no automatizable en cloud) → se sincroniza desde Mac
  - Binance se consulta en vivo desde Streamlit Cloud
- **`requirements.txt`**: versiones con `>=` (no `==`) para compatibilidad con Python 3.14
- **`packages.txt`**: `libpq-dev` + `python3-dev` para compilar psycopg2 en cloud

### Archivos modificados
- `dashboard/app.py` — sync st.secrets → os.environ al inicio
- `requirements.txt` — pins con `>=`
- `packages.txt` — nuevo, dependencias del sistema para Supabase

---

## [v0.9] — 2026-04-19 — Fix flujos Binance P2P en CLP

### ✅ Logrado
- **Fix crítico `get_binance_flows()`** en `services/flows.py`
  - **Causa raíz**: compras de ADA/BTC se hicieron via P2P pagando en **CLP** (pesos chilenos). El endpoint C2C de Binance solo devuelve los últimos 30 días sin parámetros de fecha → se recuperaban 0 transacciones
  - **Fix**: paginación por ventanas de tiempo de 30 días hacia atrás (últimos 30 meses) usando `startTimestamp`/`endTimestamp` en cada request C2C
  - **Agregado**: endpoint `/sapi/v1/fiat/orders` para capturar compras via Binance Pay / tarjeta / transferencia bancaria con CLP
  - **Deduplicación**: `seen_ids` evita duplicados cuando múltiples ventanas de tiempo se solapan
  - **Log mejorado**: ahora imprime status code y texto de error en requests fallidos
- **Dashboard**: columna "Monto fiat" muestra el CLP pagado en cada compra P2P (campo `totalPrice` del response C2C)
- **CLAUDE.md**: nota crítica sobre compras P2P en CLP y la necesidad de paginar por tiempo

### ⚠️ Si sigue sin mostrar datos
Si el dashboard sigue en "Sin movimientos registrados", el motivo más probable es que la **API key de Binance no tiene permiso C2C/P2P habilitado**. Para verificar:
1. Binance → Perfil → Gestión de API → editar la API key
2. Habilitar "Enable C2C" o "Enable Reading" (según versión de la UI)
3. También verificar que `startTimestamp` y `endTimestamp` sean aceptados por la versión de la API

### Archivos modificados
- `services/flows.py` — lógica C2C con ventanas de tiempo + endpoint fiat orders
- `dashboard/app.py` — columna "Monto fiat" en tabla de flujos Binance

---

## [v0.8] — 2026-04-19 — Arquitectura cloud: Supabase + Streamlit Community Cloud

### ✅ Logrado
- **`services/cache.py`** ahora soporta PostgreSQL (Supabase) y SQLite en paralelo:
  - Si `DATABASE_URL` env var está definida → usa `psycopg2` con PostgreSQL
  - Si no → SQLite local sin cambios (comportamiento idéntico al anterior)
  - Misma interfaz pública: `save_snapshot`, `get_history`, `get_last_snapshot`
- **`requirements.txt`**: agregado `psycopg2-binary==2.9.9`
- **`dashboard/app.py`**: modo cloud con fallback automático
  - Si Playwright/Fintual no está disponible (Streamlit Cloud), rellena posiciones Fintual desde el último snapshot de la DB
  - Banner informativo: "Fintual: datos del último sync (fecha). Ejecuta sync en tu Mac para actualizar."
  - Binance siempre se consulta en vivo (API no requiere Playwright)
- **`.streamlit/config.toml`**: configuración base para Streamlit Cloud (headless, dark theme)
- **`.streamlit/secrets.toml.example`**: plantilla de secrets para configurar en Streamlit Cloud UI
- **`.gitignore`**: agregado `.streamlit/secrets.toml`

### Arquitectura resultante
```
Tu Mac (cron diario)                    Streamlit Community Cloud (gratis)
──────────────────────                  ──────────────────────────────────
python3 -m cli.main sync                dashboard/app.py
  │                                       │
  ├─ Playwright → Fintual                 ├─ Lee historial de Supabase
  ├─ API → Binance                        ├─ Lee Binance en vivo (API)
  └─ Guarda en Supabase ─────────────────┤
                                          └─ URL pública, siempre disponible
```

### Próximos pasos para activar el hosting
1. Crear proyecto gratis en supabase.com → copiar `DATABASE_URL`
2. Agregar `DATABASE_URL` al `.env` local → `python3 -m cli.main sync` (crea tabla y primer snapshot)
3. Subir proyecto a GitHub (sin `.env`, sin `*.db`)
4. En share.streamlit.io → New app → conectar repo → `dashboard/app.py` → configurar secrets
5. Configurar cron en Mac: `0 8 * * * cd "ruta" && python3 -m cli.main sync`

### Archivos modificados
- `services/cache.py`, `requirements.txt`, `dashboard/app.py`
- `.streamlit/config.toml` (nuevo), `.streamlit/secrets.toml.example` (nuevo), `.gitignore`

---

## [v0.7] — 2026-04-19 — Fix definitivo de flujos Fintual

### ✅ Logrado
- **Fix definitivo `get_fintual_flows()`** en `services/flows.py`
  - Enfoque anterior (intercepción de red): fallaba porque Fintual usa SSR, no API calls desde el browser
  - Enfoque nuevo:
    1. Llama a `/api/goals` con cookies de sesión → obtiene `goal_id` del goal por nombre
    2. Navega a `https://fintual.cl/f/mutual-funds/investible-objects-visualization/show-goal/{id}/movements/`
    3. Parsea el texto estructurado (patrón consistente: Tipo → Fecha DD/MM/YYYY → Monto $X.XXX)
  - Verificado: 10 aportes extraídos correctamente para "Arriesgado" (2025-07 a 2026-04)
  - Fix typo Python 3.9: `int | None` → sin anotación de tipo

### Archivos modificados
- `services/flows.py` — nueva implementación `get_fintual_flows()` con `_get_fintual_goal_id()` y `_parse_movements_text()`

---

## [v0.6] — 2026-04-19 — Fix historial Fintual + Flujos por producto

### ✅ Logrado
- **Fix bug crítico historial Fintual**: `_find_real_asset_id()` en `services/historical.py`
  - Bug anterior: se pasaba `conceptual_asset_id` al endpoint `/api/real_assets/{id}/days` → 404 silencioso → gráficos vacíos
  - Fix: dos llamadas — primero obtener `conceptual_id`, luego buscar `real_assets?conceptual_asset_id={id}` y seleccionar Serie A
  - Los gráficos de rentabilidad de Fintual ahora funcionan correctamente
- **Nuevo servicio `services/flows.py`**: aportes y retiros por instrumento
  - **Fintual**: intercepción de respuestas de red del SPA al navegar `/app/movements` (más robusto que text scraping)
  - **Binance**: depósitos directos + retiros + **compras/ventas P2P** (`/sapi/v1/c2c/orderMatch/listUserOrderHistory`) con paginación automática
  - Fix helper `signed_request`: maneja respuestas tipo lista Y tipo `{"data":[...]}` (formato P2P)
- **Dashboard actualizado**: sección "Aportes y retiros" en cada tab de instrumento
  - Fintual: tabla verde/rojo con fecha, tipo (aporte/retiro), monto CLP
  - Binance: tabla con fecha, tipo (deposito/retiro/p2p_compra/p2p_venta), cantidad
- **CLAUDE.md actualizado**: refleja estado real del proyecto, arquitectura completa, limitaciones

### Archivos modificados
- `services/historical.py` — `_find_real_asset_id()` con doble llamada API
- `services/flows.py` — **nuevo servicio** con Fintual (intercepción) + Binance (depósitos + P2P)
- `dashboard/app.py` — sección de flujos en tabs de instrumento
- `CLAUDE.md` — reescrito con estado actualizado

---

## [v0.5] — 2026-04-19 — Rentabilidad histórica por instrumento

### ✅ Logrado
- **Rentabilidad histórica por instrumento** en el dashboard (nueva sección con tabs)
  - **Fintual**: NAV diario vía API pública (`/api/real_assets/{id}/days`) — sin auth requerido
    - Mapeo automático de nombre de meta → fondo Fintual (Risky Norris, Moderate Pitt, Very Risky Clooney)
    - Gráfico de % retorno acumulado para cada fondo
    - Métricas: retorno del período, NAV inicio vs. actual
  - **Binance**: precio histórico vía API pública de klines (`/api/v3/klines`)
    - BTC y ADA con historial de hasta 5 años
    - Gráfico de % retorno acumulado en USD
    - Métricas: retorno del período, precio inicio vs. actual
  - Selector de período: 30d / 90d / 1 año / 2 años / 5 años
- **Historial del portafolio sin límite de días**: eliminado el cap de 90 días
  - Opciones: 7d / 30d / 90d / 1 año / **Todo el historial**
  - `get_history(days=None)` retorna todos los snapshots cuando `days=None`
- **Nuevo servicio**: `services/historical.py` — descarga y normaliza datos históricos externos

### Archivos modificados
- `services/cache.py` — `get_history(days=None)` soporta todo el historial
- `services/historical.py` — nuevo servicio de rentabilidad histórica
- `dashboard/app.py` — sección de rentabilidad por instrumento, selector de período extendido

---

## Contexto del Proyecto

Sistema personal para consolidar y analizar inversiones en **Fintual** (fondos mutuos chilenos) y **Binance** (crypto). El objetivo a largo plazo es tener trazabilidad completa del portafolio y usar IA para tomar mejores decisiones de inversión.

---

## [v0.4] — 2026-04-19 — Portafolio completo funcionando

### ✅ Logrado
- **Binance Funding wallet** conectada (ADA + BTC estaban en Funding, no en Spot)
  - ADA: 6,475.80 (~$1,603 USD)
  - BTC: 0.03559 (~$2,683 USD)
  - Total Binance: ~$4,287 USD
- **Portafolio total consolidado: ~$39,835 USD**
  - Fintual 89.2% | Binance 10.8%
- `connectors/binance_client.py` ahora consulta Spot + Funding wallet en paralelo

---

## [v0.3] — 2026-04-19 — Fintual via Playwright (FUNCIONANDO)

### ✅ Logrado
- **Fintual conectado** mediante scraping con Playwright (browser headless)
  - `python3 -m cli.main setup-fintual` → abre browser visible para login manual con OTP
  - La sesión se guarda en `~/.finanzas/fintual_session.json` (cookies + localStorage)
  - Las sesiones se reutilizan automáticamente en ejecuciones futuras
  - Si la sesión expira → re-ejecutar `setup-fintual`
- Portafolio Fintual actual (19/04/2026):
  - Arriesgado: CLP $16,319,750 (~$18,408 USD)
  - Moderado: CLP $11,409,669 (~$12,870 USD)
  - Muy Arriesgada: CLP $3,784,722 (~$4,269 USD)
  - **Total Fintual: ~$35,548 USD**

### ⚠️ Pendiente
- **Binance**: API key actual (`D4nRsG7...`) es de cuenta vacía/incorrecta
  - La cuenta real tiene ~$4,284 en BTC + ADA (UID: 1151626763)
  - **Acción requerida**: crear nueva API key desde la cuenta correcta en binance.com → Perfil → Gestión de API → Crear API Key (solo permiso "Leer información")
  - Reemplazar en `.env`: `BINANCE_API_KEY` y `BINANCE_API_SECRET`
- **Gemini API key**: pendiente para análisis IA (gratis en aistudio.google.com)

---

## [v0.2] — 2026-04-19 — Cambio de arquitectura

### Cambios
- Reemplazado cliente REST de Fintual por Playwright (API `/goals` devuelve 401 de forma persistente)
- Cambiado proveedor de IA de Anthropic SDK → Google Gemini (`google-generativeai`)
- Agregado comando `setup-fintual` al CLI
- Tipo de cambio USD/CLP obtenido de `open.er-api.com` (fallback: 950)

---

## [v0.1] — 2026-04-19 — Estructura inicial

### Creado
- `requirements.txt`, `.env`, `.env.example`, `.gitignore`
- `connectors/fintual.py` — cliente Fintual
- `connectors/binance_client.py` — cliente Binance
- `models/portfolio.py` — dataclasses Portfolio, Position
- `services/aggregator.py` — consolida Fintual + Binance en USD
- `services/cache.py` — SQLite para historial de snapshots
- `services/ai_advisor.py` — análisis con Gemini
- `cli/main.py` — comandos: `status`, `sync`, `analyze`, `history`, `setup-fintual`
- `dashboard/app.py` — Streamlit con gráficos, tabla, historial y botón IA

---

## Stack Técnico

| Componente | Herramienta |
|---|---|
| Lenguaje | Python 3.9 (macOS system) |
| Fintual | `playwright` (Chromium headless) |
| Binance | `python-binance` |
| Dashboard | `streamlit` + `plotly` |
| CLI | `typer` + `rich` |
| IA | `google-generativeai` (Gemini 1.5 Flash) |
| DB local | `sqlite3` |
| Secrets | `python-dotenv` |

## Comandos Principales

```bash
cd "Proyecto Finanzas Personales"

# Primera vez: login en Fintual (abre browser, necesita código OTP del email)
python3 -m cli.main setup-fintual

# Ver portafolio completo
python3 -m cli.main status

# Guardar snapshot en historial
python3 -m cli.main sync

# Análisis IA (requiere GEMINI_API_KEY en .env)
python3 -m cli.main analyze

# Historial de N días
python3 -m cli.main history --days 30

# Dashboard web
streamlit run dashboard/app.py
```

## Archivos Importantes

| Archivo | Descripción |
|---|---|
| `.env` | Credenciales (nunca committear) |
| `~/.finanzas/fintual_session.json` | Sesión Playwright de Fintual |
| `db/portfolio.db` | Historial de snapshots (SQLite) |
| `connectors/fintual.py` | Scraper Fintual con Playwright |
| `connectors/binance_client.py` | Cliente Binance API |
| `services/aggregator.py` | Consolidación del portafolio |
| `dashboard/app.py` | Dashboard Streamlit |
