import os
import google.generativeai as genai
from dotenv import load_dotenv

from models.portfolio import Portfolio

load_dotenv()

SYSTEM_PROMPT = """Eres un asesor financiero experto en inversiones.
Analizas portafolios de inversión y das recomendaciones claras, prácticas y honestas.
Consideras diversificación, riesgo, rentabilidad y contexto del mercado.
Responde siempre en español, de forma concisa y accionable.
No das consejos legales ni garantizas retornos. Eres informativo y educativo."""


def get_recommendation(portfolio: Portfolio) -> str:
    """Envía el portafolio a Gemini y retorna una recomendación."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Falta GEMINI_API_KEY en el .env. Obtén una gratis en aistudio.google.com")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    fintual_total = portfolio.fintual_total_usd()
    binance_total = portfolio.binance_total_usd()
    total = portfolio.total_usd

    lines = [
        f"Fecha del análisis: {portfolio.timestamp.strftime('%Y-%m-%d %H:%M')}",
        f"Valor total del portafolio: ${total:,.2f} USD",
        "",
        f"=== FINTUAL (Fondos mutuos) === ${fintual_total:,.2f} USD ({fintual_total/total*100:.1f}%)" if total > 0 else "=== FINTUAL ===",
    ]
    for p in portfolio.fintual_positions():
        lines.append(f"  - {p.name}: ${p.value_usd:,.2f} USD (CLP {p.amount:,.0f})")

    lines += [
        "",
        f"=== BINANCE (Crypto) === ${binance_total:,.2f} USD ({binance_total/total*100:.1f}%)" if total > 0 else "=== BINANCE ===",
    ]
    for p in portfolio.binance_positions():
        lines.append(f"  - {p.name}: {p.amount:.6f} unidades = ${p.value_usd:,.2f} USD")

    portfolio_text = "\n".join(lines)
    prompt = (
        f"Analiza mi portafolio de inversiones y dame tus recomendaciones:\n\n{portfolio_text}\n\n"
        "Por favor analiza: 1) Diversificación actual, 2) Riesgos identificados, "
        "3) Oportunidades de mejora, 4) Acciones concretas que podría tomar."
    )

    response = model.generate_content(prompt)
    return response.text
