import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

# Streamlit Cloud expone secrets via st.secrets, no os.environ.
# Sincronizamos para que los módulos que usan os.getenv() los reciban.
try:
    for _k, _v in st.secrets.items():
        if _k not in os.environ:
            os.environ[_k] = str(_v)
except Exception:
    pass

# ── Autenticación ────────────────────────────────────────────────────────────
import hashlib as _hl

_AUTH_USER = os.environ.get("AUTH_USERNAME", "")
_AUTH_PASS = os.environ.get("AUTH_PASSWORD", "")
_AUTH_TOKEN = _hl.sha256(f"{_AUTH_USER}:{_AUTH_PASS}:finanzas".encode()).hexdigest()[:16] if _AUTH_USER else ""

# Auto-login si el token está en la URL (persiste entre recargas del browser)
if _AUTH_TOKEN and st.query_params.get("t") == _AUTH_TOKEN:
    st.session_state.authenticated = True

if _AUTH_USER and _AUTH_PASS:
    if not st.session_state.get("authenticated"):
        st.set_page_config(page_title="Finanzas Personales", page_icon="🏦")
        st.markdown("## 🏦 Finanzas Personales")
        with st.form("login_form"):
            username = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Ingresar", use_container_width=True)
        if submitted:
            if username == _AUTH_USER and password == _AUTH_PASS:
                st.session_state.authenticated = True
                st.query_params["t"] = _AUTH_TOKEN
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos")
        st.stop()

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="Finanzas Personales",
    page_icon="📊",
    layout="wide",
)

# ── Estilos ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card { background: #1e1e2e; border-radius: 12px; padding: 1rem 1.5rem; margin-bottom: 1rem; }
    .platform-badge-fintual { background: #2d6a4f; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    .platform-badge-binance { background: #b58900; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
</style>
""", unsafe_allow_html=True)


# ── Funciones de carga ───────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_live_portfolio():
    """
    Carga el portafolio intentando APIs en vivo.
    Si alguna plataforma falla (geo-restricción, cookie expirada, etc.),
    rellena desde el último snapshot guardado en DB.
    Retorna (portfolio, cached_ts, errors) donde cached_ts es el timestamp
    del snapshot usado como fallback, o None si todo es en vivo.
    """
    from services.aggregator import get_portfolio
    from services.cache import get_last_snapshot
    from models.portfolio import Portfolio, Position
    from datetime import datetime

    _result = get_portfolio()
    if isinstance(_result, tuple):
        portfolio, _errors = _result
    else:
        portfolio, _errors = _result, {}
    cached_ts = None
    last = None  # lazy-load snapshot solo si hace falta

    # --- Fallback Fintual: si la API falló, rellenar desde DB ---
    fintual_positions = [p for p in portfolio.positions if p.platform == "fintual"]
    if not fintual_positions:
        last = get_last_snapshot()
        if last:
            import requests as _req
            try:
                r = _req.get("https://open.er-api.com/v6/latest/USD", timeout=5)
                usdclp = r.json()["rates"]["CLP"]
            except Exception:
                usdclp = 950.0

            cached_fintual = [
                Position(
                    platform=p["platform"], name=p["name"], amount=p["amount"],
                    value_usd=p["amount"] / usdclp if p["currency"] == "CLP" else p["value_usd"],
                    currency=p["currency"],
                )
                for p in last["positions"] if p["platform"] == "fintual"
            ]
            non_fintual = [p for p in portfolio.positions if p.platform != "fintual"]
            portfolio = Portfolio(
                timestamp=datetime.now(),
                positions=cached_fintual + non_fintual,
                total_usd=sum(p.value_usd for p in cached_fintual + non_fintual),
            )
            cached_ts = last["timestamp"]

    # --- Fallback Binance: si la API falló (geo-restricción), rellenar desde DB ---
    binance_positions = [p for p in portfolio.positions if p.platform == "binance"]
    if not binance_positions:
        if last is None:
            last = get_last_snapshot()
        if last:
            cached_binance = [
                Position(
                    platform=p["platform"], name=p["name"], amount=p["amount"],
                    value_usd=p["value_usd"], currency=p["currency"],
                )
                for p in last["positions"] if p["platform"] == "binance"
            ]
            non_binance = [p for p in portfolio.positions if p.platform != "binance"]
            portfolio = Portfolio(
                timestamp=datetime.now(),
                positions=non_binance + cached_binance,
                total_usd=sum(p.value_usd for p in non_binance + cached_binance),
            )
            cached_ts = cached_ts or last["timestamp"]

    return portfolio, cached_ts, _errors


def load_history(days=None):
    from services.cache import get_history
    return get_history(days=days)


def load_last_snapshot():
    from services.cache import get_last_snapshot
    return get_last_snapshot()


@st.cache_data(ttl=3600)
def load_fintual_history(fund_name, days):
    from services.historical import get_fintual_nav_history
    return get_fintual_nav_history(fund_name, days=days)


@st.cache_data(ttl=3600)
def load_binance_history(symbol, days):
    from services.historical import get_binance_price_history
    result = get_binance_price_history(symbol, days=days)
    if not result:
        print(f"[Dashboard] CoinGecko retornó vacío para {symbol} ({days} días)")
    return result


@st.cache_data(ttl=3600)
def load_fintual_flows(fund_name):
    flows = []
    try:
        from services.flows import get_fintual_flows
        flows = get_fintual_flows(fund_name)
    except Exception as e:
        print(f"[Dashboard] Fintual flows live failed for '{fund_name}': {e}")
    if not flows:
        try:
            from services.cache import get_fintual_flows_cached
            flows = get_fintual_flows_cached(fund_name)
        except Exception as e:
            print(f"[Dashboard] Fintual flows DB fallback failed for '{fund_name}': {e}")
    return flows


@st.cache_data(ttl=3600)
def load_binance_flows(asset):
    flows = []
    try:
        from services.flows import get_binance_flows
        flows = get_binance_flows(asset=asset)
    except Exception as e:
        print(f"[Dashboard] Binance flows live failed for '{asset}': {e}")
    if not flows:
        try:
            from services.cache import get_binance_flows_cached
            flows = get_binance_flows_cached(asset=asset)
        except Exception as e:
            print(f"[Dashboard] Binance flows DB fallback failed for '{asset}': {e}")
    return flows


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("📊 Finanzas Personales")
    st.divider()

    history_option = st.selectbox(
        "Período de historial",
        ["7 días", "30 días", "90 días", "1 año", "Todo el historial"],
        index=1,
    )
    _days_map = {"7 días": 7, "30 días": 30, "90 días": 90, "1 año": 365, "Todo el historial": None}
    history_days = _days_map[history_option]

    st.divider()

    instrument_option = st.selectbox(
        "Período de rentabilidad por instrumento",
        ["30 días", "90 días", "1 año", "2 años", "5 años"],
        index=2,
    )
    _inst_days_map = {"30 días": 30, "90 días": 90, "1 año": 365, "2 años": 730, "5 años": 1825}
    instrument_days = _inst_days_map[instrument_option]

    st.divider()
    if st.button("🔄 Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if _AUTH_USER and _AUTH_PASS:
        if st.button("🚪 Cerrar sesión", use_container_width=True):
            st.session_state.authenticated = False
            st.query_params.clear()
            st.rerun()

    with st.expander("🔧 Debug DB", expanded=False):
        try:
            from services.cache import _DB_URL, get_fintual_flows_cached, get_binance_flows_cached
            st.text(f"DB: {'PostgreSQL' if _DB_URL else 'SQLite (!)' }")
            fc = len(get_fintual_flows_cached())
            bc = len(get_binance_flows_cached())
            st.text(f"Fintual flows en DB: {fc}")
            st.text(f"Binance flows en DB: {bc}")
        except Exception as e:
            st.text(f"Error: {e}")


# ── Carga de datos ───────────────────────────────────────────────────────────
with st.spinner("Cargando portafolio..."):
    try:
        portfolio, cached_ts, connector_errors = load_live_portfolio()
        error = None
    except Exception as e:
        portfolio = None
        cached_ts = None
        connector_errors = {}
        error = str(e)

history = load_history(days=history_days)
last_snap = load_last_snapshot()

# ── Encabezado ───────────────────────────────────────────────────────────────
st.title("📈 Mi Portafolio de Inversiones")

if error:
    st.error(f"Error al cargar datos: {error}")
    st.info("Verifica que tu archivo `.env` tenga las credenciales correctas.")
    st.stop()

if not portfolio or not portfolio.positions:
    st.warning("No se encontraron posiciones. Verifica tu `.env`.")
    st.stop()

# Mostrar errores de conectores solo si no pudimos recuperar datos de ninguna fuente
if connector_errors.get("binance") and not any(p.platform == "binance" for p in portfolio.positions):
    st.warning(f"⚠️ Binance no disponible: `{connector_errors['binance']}`")
if connector_errors.get("fintual") and not any(p.platform == "fintual" for p in portfolio.positions):
    st.warning(f"⚠️ Fintual no disponible: `{connector_errors['fintual']}`")

if cached_ts:
    from datetime import datetime as _dt
    ts_fmt = _dt.fromisoformat(cached_ts).strftime("%d/%m/%Y %H:%M")
    st.info(f"Algunos datos provienen del último sync ({ts_fmt}).")

# Variación vs último snapshot
variation_delta = None
if last_snap and last_snap["total_usd"] > 0:
    diff = portfolio.total_usd - last_snap["total_usd"]
    pct = diff / last_snap["total_usd"] * 100
    variation_delta = f"{'+' if diff >= 0 else ''}{diff:,.2f} USD ({pct:+.1f}%)"

# ── Métricas principales ──────────────────────────────────────────────────────
from services.aggregator import _get_usdclp
usdclp = _get_usdclp()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Portafolio",
              f"${portfolio.total_usd:,.2f} USD",
              delta=variation_delta)
    st.caption(f"CLP ${portfolio.total_usd * usdclp:,.0f}")
with col2:
    ft = portfolio.fintual_total_usd()
    st.metric("Fintual", f"${ft:,.2f} USD",
              delta=f"{ft/portfolio.total_usd*100:.1f}% del total" if portfolio.total_usd else None)
    st.caption(f"CLP ${ft * usdclp:,.0f}")
with col3:
    bn = portfolio.binance_total_usd()
    st.metric("Binance", f"${bn:,.2f} USD",
              delta=f"{bn/portfolio.total_usd*100:.1f}% del total" if portfolio.total_usd else None)
    st.caption(f"CLP ${bn * usdclp:,.0f}")

st.divider()

# ── Gráficos ──────────────────────────────────────────────────────────────────
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Distribución por plataforma")
    fig_platform = px.pie(
        values=[portfolio.fintual_total_usd(), portfolio.binance_total_usd()],
        names=["Fintual", "Binance"],
        color_discrete_map={"Fintual": "#2d6a4f", "Binance": "#f0b90b"},
        hole=0.45,
    )
    fig_platform.update_traces(textposition="inside", textinfo="percent+label")
    fig_platform.update_layout(showlegend=False, margin=dict(t=20, b=20, l=0, r=0))
    st.plotly_chart(fig_platform, use_container_width=True)

with col_right:
    st.subheader("Posiciones por asset")
    positions_data = [
        {"Asset": p.name, "Plataforma": p.platform.capitalize(), "Valor USD": p.value_usd}
        for p in portfolio.positions
        if p.value_usd > 0.01
    ]
    df_pos = pd.DataFrame(positions_data).sort_values("Valor USD", ascending=False)
    fig_assets = px.bar(
        df_pos, x="Asset", y="Valor USD", color="Plataforma",
        color_discrete_map={"Fintual": "#2d6a4f", "Binance": "#f0b90b"},
    )
    fig_assets.update_layout(margin=dict(t=20, b=20, l=0, r=0), showlegend=True)
    st.plotly_chart(fig_assets, use_container_width=True)

# ── Tabla de posiciones ───────────────────────────────────────────────────────
st.subheader("Detalle de posiciones")
rows = []
for p in sorted(portfolio.positions, key=lambda x: x.value_usd, reverse=True):
    pct = p.value_usd / portfolio.total_usd * 100 if portfolio.total_usd > 0 else 0
    rows.append({
        "Plataforma": p.platform.upper(),
        "Asset / Fondo": p.name,
        "Cantidad": f"{p.amount:,.4f}" if p.platform == "binance" else f"CLP {p.amount:,.0f}",
        "Valor USD": f"${p.value_usd:,.2f}",
        "Valor CLP": f"${p.value_usd * usdclp:,.0f}",
        "% del total": f"{pct:.1f}%",
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()

# ── Historial del portafolio ──────────────────────────────────────────────────
label = history_option if history_option != "Todo el historial" else "todo el historial"
st.subheader(f"Evolución del portafolio — {label}")
if history:
    df_hist = pd.DataFrame([
        {"Fecha": h["timestamp"][:16].replace("T", " "), "Total USD": h["total_usd"]}
        for h in history
    ])
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Scatter(
        x=df_hist["Fecha"], y=df_hist["Total USD"],
        mode="lines+markers", name="Total USD",
        line=dict(color="#52b788", width=2),
        fill="tozeroy", fillcolor="rgba(82,183,136,0.1)",
    ))
    fig_hist.update_layout(
        xaxis_title="Fecha", yaxis_title="USD",
        margin=dict(t=20, b=20, l=0, r=0),
    )
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("Sin historial aún. Ejecuta `python -m cli.main sync` para guardar tu primer snapshot.")

st.divider()

# ── Rentabilidad histórica por instrumento ────────────────────────────────────
st.subheader(f"📈 Rentabilidad por instrumento — {instrument_option}")

fintual_positions = [p for p in portfolio.positions if p.platform == "fintual"]
binance_positions = [p for p in portfolio.positions if p.platform == "binance"]

all_positions = fintual_positions + binance_positions
if all_positions:
    tab_names = [p.name for p in all_positions]
    tabs = st.tabs(tab_names)

    for i, pos in enumerate(fintual_positions):
        with tabs[i]:
            with st.spinner(f"Cargando historial de {pos.name}..."):
                hist = load_fintual_history(pos.name, instrument_days)
            if hist:
                df_i = pd.DataFrame(hist)
                first_price = hist[0]["price"]
                last_price = hist[-1]["price"]
                total_ret = hist[-1]["pct"]
                color = "#52b788" if total_ret >= 0 else "#e05252"

                fig_i = go.Figure()
                fig_i.add_trace(go.Scatter(
                    x=df_i["date"], y=df_i["pct"],
                    mode="lines", name=pos.name,
                    line=dict(color=color, width=2),
                    fill="tozeroy",
                    fillcolor=f"rgba(82,183,136,0.1)" if total_ret >= 0 else "rgba(224,82,82,0.1)",
                ))
                fig_i.update_layout(
                    yaxis_title="Retorno acumulado (%)",
                    xaxis_title="Fecha",
                    margin=dict(t=10, b=20, l=0, r=0),
                    hovermode="x unified",
                )
                st.plotly_chart(fig_i, use_container_width=True)

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Retorno período", f"{total_ret:+.2f}%")
                mc2.metric("NAV inicio período", f"CLP ${first_price:,.2f}")
                mc3.metric("NAV actual", f"CLP ${last_price:,.2f}")
            else:
                st.info(f"No hay datos históricos disponibles para **{pos.name}**.")
                st.caption("El fondo podría no estar en la API pública de Fintual, o hubo un error de red.")

            # ── Flujos (aportes y retiros) ────────────────────────────────────
            st.markdown("#### Aportes y retiros")
            with st.spinner("Cargando movimientos..."):
                flows = load_fintual_flows(pos.name)
            if flows:
                df_flows = pd.DataFrame(flows)
                df_flows.columns = ["Fecha", "Tipo", "Monto CLP"]
                df_flows["Monto CLP"] = df_flows["Monto CLP"].apply(lambda x: f"${x:,.0f}")

                def _highlight_flow(row):
                    color = "#1a472a" if row["Tipo"] == "aporte" else "#4a1a1a"
                    return [f"background-color: {color}"] * len(row)

                st.dataframe(
                    df_flows.style.apply(_highlight_flow, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Sin movimientos registrados (o sesión Fintual expirada).")

    for i, pos in enumerate(binance_positions):
        with tabs[len(fintual_positions) + i]:
            with st.spinner(f"Cargando historial de {pos.name}..."):
                hist = load_binance_history(pos.name, instrument_days)
            if hist:
                df_i = pd.DataFrame(hist)
                first_price = hist[0]["price"]
                last_price = hist[-1]["price"]
                total_ret = hist[-1]["pct"]
                color = "#f0b90b" if total_ret >= 0 else "#e05252"

                fig_i = go.Figure()
                fig_i.add_trace(go.Scatter(
                    x=df_i["date"], y=df_i["pct"],
                    mode="lines", name=pos.name,
                    line=dict(color=color, width=2),
                    fill="tozeroy",
                    fillcolor="rgba(240,185,11,0.1)" if total_ret >= 0 else "rgba(224,82,82,0.1)",
                ))
                fig_i.update_layout(
                    yaxis_title="Retorno acumulado (%)",
                    xaxis_title="Fecha",
                    margin=dict(t=10, b=20, l=0, r=0),
                    hovermode="x unified",
                )
                st.plotly_chart(fig_i, use_container_width=True)

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Retorno período", f"{total_ret:+.2f}%")
                mc2.metric(f"Precio {pos.name} inicio", f"${first_price:,.4f} USD")
                mc3.metric(f"Precio {pos.name} actual", f"${last_price:,.4f} USD")
            else:
                st.info(f"No hay datos históricos disponibles para **{pos.name}**.")
                st.caption("El par de trading podría no existir en Binance, o hubo un error de red.")

            # ── Flujos (depósitos y retiros) ──────────────────────────────────
            st.markdown("#### Depósitos y retiros")
            with st.spinner("Cargando movimientos..."):
                flows = load_binance_flows(pos.name)
            if flows:
                rows = []
                for f in flows:
                    qty = f"{float(f.get('amount', 0)):,.6f} {f.get('asset', '')}"
                    fiat_str = ""
                    if f.get("fiat_amount") and float(f.get("fiat_amount", 0)) > 0:
                        fiat_str = f"${float(f['fiat_amount']):,.0f} {f.get('fiat', 'CLP')}"
                    rows.append({
                        "Fecha": f.get("date", ""),
                        "Tipo": f.get("type", ""),
                        "Cantidad": qty,
                        "Monto fiat": fiat_str,
                    })
                df_flows = pd.DataFrame(rows)

                def _highlight_binance(row):
                    tipo = row["Tipo"]
                    if tipo in ("deposito", "p2p_compra", "fiat_compra"):
                        color = "#1a3a4a"
                    else:
                        color = "#4a1a1a"
                    return [f"background-color: {color}"] * len(row)

                st.dataframe(
                    df_flows.style.apply(_highlight_binance, axis=1),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Sin movimientos registrados. Verifica que la API key tenga permiso de lectura C2C/P2P.")

st.divider()

# ── IA Advisor ────────────────────────────────────────────────────────────────
st.subheader("🤖 Análisis con IA")

if last_snap and last_snap.get("ai_recommendation"):
    with st.expander("Último análisis guardado", expanded=False):
        ts = datetime.fromisoformat(last_snap["timestamp"]).strftime("%d/%m/%Y %H:%M")
        st.caption(f"Generado el {ts}")
        st.write(last_snap["ai_recommendation"])

if st.button("✨ Analizar portafolio actual con Claude", use_container_width=False):
    with st.spinner("Consultando a Claude..."):
        try:
            from services.ai_advisor import get_recommendation
            from services.cache import save_snapshot
            recommendation = get_recommendation(portfolio)
            save_snapshot(portfolio, ai_recommendation=recommendation)
            st.success("Análisis completado")
            st.write(recommendation)
        except Exception as e:
            st.error(f"Error al consultar la IA: {e}")

st.caption(f"Última actualización: {portfolio.timestamp.strftime('%d/%m/%Y %H:%M:%S')}")
