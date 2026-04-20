# Proyecto Finanzas Personales

> **IMPORTANTE para Claude**: Actualizar `CLAUDE.md` y `CHANGELOG.md` al final de CADA sesión con los cambios realizados. No esperar que el usuario lo pida.

Sistema personal para consolidar, visualizar y analizar inversiones usando IA.

## ¿Qué hace?

- **Fintual** → fondos mutuos chilenos (Arriesgado, Moderado, Muy Arriesgada)
- **Binance** → crypto (BTC, ADA, etc.) — Spot + Funding wallet
- **Dashboard Streamlit** con portafolio consolidado en USD/CLP, gráficos, historial, rentabilidad por instrumento
- **Aportes/retiros** por producto (Fintual via intercepción de red, Binance via API + P2P)
- **Análisis con IA** (Gemini) con recomendaciones de diversificación

## Uso rápido

```bash
cd "Proyecto Finanzas Personales"

# Ver portafolio ahora
python3 -m cli.main status

# Guardar snapshot histórico
python3 -m cli.main sync

# Análisis IA (requiere GEMINI_API_KEY en .env)
python3 -m cli.main analyze

# Ver evolución en el tiempo
python3 -m cli.main history --days 30

# Dashboard visual en el browser
streamlit run dashboard/app.py
# o doble clic en abrir_dashboard.command
```

## Primera vez / sesión Fintual expirada

```bash
python3 -m cli.main setup-fintual
# Se abre el browser → ingresas email, contraseña y código OTP del email
# La sesión se guarda en ~/.finanzas/fintual_session.json
```

## Configuración (.env)

Copia `.env.example` → `.env` y llena:

| Variable | Descripción |
|---|---|
| `FINTUAL_EMAIL` | Tu email de Fintual |
| `FINTUAL_PASSWORD` | Tu contraseña de Fintual |
| `BINANCE_API_KEY` | API key de Binance (permiso "Leer información") |
| `BINANCE_API_SECRET` | API secret de Binance |
| `GEMINI_API_KEY` | Gratis en aistudio.google.com |

## Arquitectura

```
connectors/
  fintual.py          → scraping con Playwright (login + extracción de metas)
  binance_client.py   → Binance REST API (balances Spot + Funding, precios)

models/
  portfolio.py        → dataclasses Portfolio, Position

services/
  aggregator.py       → consolida Fintual + Binance en USD (con tipo de cambio)
  cache.py            → SQLite: guarda/lee snapshots históricos
  historical.py       → NAV diario Fintual + precio histórico Binance (APIs públicas)
  flows.py            → aportes/retiros por producto (intercepción red + P2P API)
  ai_advisor.py       → análisis del portafolio con Gemini

cli/main.py           → comandos: status, sync, analyze, history, setup-fintual
dashboard/app.py      → Streamlit: gráficos, tabla, historial, rentabilidad, flujos, IA
db/
  schema.sql          → estructura SQLite
  portfolio.db        → datos (no committear)
```

## Estado actual del proyecto (v0.11 — 2026-04-20)

### ✅ Funcionando
- Fintual: scraping autenticado con Playwright (3 fondos + Reserva)
- Binance: balances Spot + Funding wallet (BTC, ADA)
- Dashboard: portafolio en USD/CLP, evolución histórica, rentabilidad por instrumento
- Historial de NAV Fintual y precio Binance (APIs públicas, sin auth)
- Flujos Fintual: API `/api/goals` con cookies → URL `/show-goal/{id}/movements/` → text parsing
- Flujos Binance: depósitos directos + retiros + compras/ventas P2P (`/sapi/v1/c2c/orderMatch/...`)
- Análisis IA con Gemini (botón en dashboard)
- **Modo cloud**: sin Playwright, rellena Fintual desde último snapshot de DB; Binance en vivo
- **DB dual**: SQLite local (`DATABASE_URL` no definida) o PostgreSQL/Supabase (cloud)
- **Deploy Streamlit Community Cloud**: `https://dcdymygparwpmzqlcykrvn.streamlit.app/`
- **Auth**: username+password via `AUTH_USERNAME`/`AUTH_PASSWORD` en secrets
- **Fintual en cloud**: via `GET /api/goals` con `FINTUAL_SESSION_COOKIE` (sin Playwright)
- **Cron Mac**: sync diario 8am → fallback si cookie expira

### ⚠️ Limitaciones conocidas
- **Sesión Fintual expira ~30 días** → re-ejecutar `setup-fintual`
- **Flujos Fintual**: dependen de lo que el SPA cargue en /app/movements; si Fintual cambia su API interna puede fallar
- **API Fintual REST** (`/api/goals`): retorna 401 para cuentas normales → usamos Playwright
- **Tipo de cambio USD/CLP**: de open.er-api.com, fallback a 950 si el servicio falla
- **Streamlit Cloud**: no puede ejecutar Playwright → Fintual siempre sale del último snapshot; solo Binance es en vivo

### 🔑 Nota crítica — Streamlit Cloud + Supabase
- **Secrets**: Streamlit Cloud expone via `st.secrets`, no `os.environ`. `dashboard/app.py` sincroniza al inicio con un loop `for k,v in st.secrets.items(): os.environ[k] = str(v)`
- **Conexión DB**: usar **Transaction Pooler** (`aws-1-us-west-2.pooler.supabase.com:6543`), NO la conexión directa (`db.*.supabase.co:5432`) que usa IPv6 y Streamlit Cloud no puede alcanzar
- **GitHub**: repo público `benjaminapt/finanzas-personales` (Streamlit Cloud requiere acceso público o cuenta Teams)

### 🔑 Nota crítica — Fintual API via cookie de sesión
- **`FINTUAL_SESSION_COOKIE`**: valor de `_fintual_session_cookie` del browser tras login en Fintual
- **Cómo obtenerla**: ejecutar `python3 -m cli.main setup-fintual` en Mac → el comando imprime la cookie
- **Duración**: ~30 días. Cuando expira, el dashboard muestra advertencia y cae al último snapshot
- **Por qué no funciona el token REST**: `POST /api/access_tokens` devuelve token pero `GET /api/goals` retorna 401 (requiere 2FA verificado). La cookie de sesión del browser sí funciona.
- **Secrets requeridos**: `AUTH_USERNAME`, `AUTH_PASSWORD`, `DATABASE_URL`, `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `FINTUAL_SESSION_COOKIE`

### 🔑 Nota crítica — Flujos Binance (compras P2P en CLP)
- **Las compras de ADA y BTC se hicieron via P2P pagando en CLP** (pesos chilenos)
- El endpoint C2C (`/sapi/v1/c2c/orderMatch/listUserOrderHistory`) solo devuelve los últimos 30 días **sin** `startTimestamp`/`endTimestamp` → hay que paginar en ventanas de 30 días para recuperar historial completo
- Si la API key no tiene permiso C2C/P2P habilitado en Binance, el endpoint devuelve 0 resultados aunque haya transacciones
- También se consulta `/sapi/v1/fiat/orders` por si las compras se hicieron via Binance Pay/tarjeta/transferencia bancaria
- Columna "Monto fiat" en el dashboard muestra el CLP pagado en cada compra P2P

## Notas técnicas

- **Python**: 3.9 (macOS system)
- **Fintual**: Playwright (Chromium headless) porque la API REST devuelve 401
- **Binance P2P**: endpoint `/sapi/v1/c2c/orderMatch/listUserOrderHistory` (separado de depósitos)
- **Historial Fintual**: usa `real_asset_id` (Serie A), NO `conceptual_asset_id`
- **Sesión**: guardada en `~/.finanzas/fintual_session.json` (cookies + localStorage)

## Archivos importantes

| Archivo | Descripción |
|---|---|
| `.env` | Credenciales (nunca committear) |
| `~/.finanzas/fintual_session.json` | Sesión Playwright de Fintual |
| `db/portfolio.db` | Historial de snapshots (SQLite) |
| `CHANGELOG.md` | Historial detallado de cambios por versión |
