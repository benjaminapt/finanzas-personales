import sys
import os

# Permite importar módulos desde la raíz del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import typer
from rich.console import Console
from rich.table import Table
from rich import box
from datetime import datetime

app = typer.Typer(help="Gestor de inversiones personales — Fintual + Binance")
console = Console()


@app.command()
def status():
    """Muestra el portafolio actual obteniendo datos en tiempo real."""
    from services.aggregator import get_portfolio

    console.print("\n[bold cyan]Obteniendo portafolio...[/bold cyan]")
    portfolio, _ = get_portfolio()

    if not portfolio.positions:
        console.print("[red]No se encontraron posiciones. Verifica tu .env[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Portafolio al {portfolio.timestamp.strftime('%d/%m/%Y %H:%M')}", box=box.ROUNDED)
    table.add_column("Plataforma", style="cyan")
    table.add_column("Asset / Fondo", style="white")
    table.add_column("Cantidad", justify="right")
    table.add_column("Valor USD", justify="right", style="green")
    table.add_column("% del total", justify="right")

    for p in sorted(portfolio.positions, key=lambda x: x.value_usd, reverse=True):
        pct = (p.value_usd / portfolio.total_usd * 100) if portfolio.total_usd > 0 else 0
        table.add_row(
            p.platform.upper(),
            p.name,
            f"{p.amount:,.4f}" if p.platform == "binance" else f"CLP {p.amount:,.0f}",
            f"${p.value_usd:,.2f}",
            f"{pct:.1f}%",
        )

    table.add_section()
    table.add_row("", "[bold]TOTAL[/bold]", "", f"[bold]${portfolio.total_usd:,.2f}[/bold]", "[bold]100%[/bold]")

    console.print(table)
    fintual_pct = portfolio.fintual_total_usd() / portfolio.total_usd * 100 if portfolio.total_usd > 0 else 0
    binance_pct = portfolio.binance_total_usd() / portfolio.total_usd * 100 if portfolio.total_usd > 0 else 0
    console.print(f"\n  Fintual: [cyan]${portfolio.fintual_total_usd():,.2f}[/cyan] ({fintual_pct:.1f}%)  |  Binance: [yellow]${portfolio.binance_total_usd():,.2f}[/yellow] ({binance_pct:.1f}%)\n")


@app.command()
def sync():
    """Obtiene datos actuales y guarda un snapshot en la base de datos local."""
    from services.aggregator import get_portfolio
    from services import cache

    console.print("\n[bold cyan]Sincronizando portafolio...[/bold cyan]")
    portfolio, _ = get_portfolio()
    cache.save_snapshot(portfolio)
    console.print(f"[green]✓ Snapshot guardado — Total: ${portfolio.total_usd:,.2f} USD[/green]")

    # Guardar flujos Binance en DB (para que el cloud los lea)
    try:
        from services.flows import get_binance_flows
        flows = get_binance_flows()
        if flows:
            saved = cache.save_binance_flows(flows)
            console.print(f"[green]✓ {len(flows)} flujos Binance guardados en DB[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠ Flujos Binance no guardados: {e}[/yellow]")

    # Guardar flujos Fintual en DB (para que el cloud los lea sin Playwright)
    try:
        from services.flows import get_fintual_flows
        fintual_names = [p.name for p in portfolio.positions if p.platform == "fintual"]
        total_fintual = 0
        for name in fintual_names:
            fflows = get_fintual_flows(name)
            if fflows:
                cache.save_fintual_flows(name, fflows)
                total_fintual += len(fflows)
        if total_fintual:
            console.print(f"[green]✓ {total_fintual} flujos Fintual guardados en DB[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠ Flujos Fintual no guardados: {e}[/yellow]")
    console.print()


@app.command()
def analyze():
    """Obtiene el portafolio actual y pide recomendaciones a la IA (Claude)."""
    from services.aggregator import get_portfolio
    from services.ai_advisor import get_recommendation
    from services import cache

    console.print("\n[bold cyan]Analizando portafolio con IA...[/bold cyan]")
    portfolio, _ = get_portfolio()

    if not portfolio.positions:
        console.print("[red]No se encontraron posiciones. Verifica tu .env[/red]")
        raise typer.Exit(1)

    console.print("[dim]Consultando a Claude...[/dim]")
    recommendation = get_recommendation(portfolio)
    cache.save_snapshot(portfolio, ai_recommendation=recommendation)

    console.print("\n[bold green]Recomendación de la IA:[/bold green]")
    console.print("─" * 60)
    console.print(recommendation)
    console.print("─" * 60 + "\n")


@app.command()
def history(days: int = typer.Option(30, help="Número de días a mostrar")):
    """Muestra la evolución del portafolio en los últimos N días."""
    from services import cache

    snapshots = cache.get_history(days=days)

    if not snapshots:
        console.print(f"[yellow]No hay historial de los últimos {days} días. Ejecuta 'sync' primero.[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Historial ({days} días)", box=box.SIMPLE)
    table.add_column("Fecha", style="dim")
    table.add_column("Total USD", justify="right", style="green")
    table.add_column("Variación", justify="right")
    table.add_column("IA", style="dim")

    prev_total = None
    for snap in snapshots:
        ts = datetime.fromisoformat(snap["timestamp"]).strftime("%d/%m/%Y %H:%M")
        total = snap["total_usd"]
        has_ia = "✓" if snap["ai_recommendation"] else ""

        if prev_total is not None:
            diff = total - prev_total
            pct = diff / prev_total * 100 if prev_total > 0 else 0
            color = "green" if diff >= 0 else "red"
            variacion = f"[{color}]{'+' if diff >= 0 else ''}{diff:,.2f} ({pct:+.1f}%)[/{color}]"
        else:
            variacion = "—"

        table.add_row(ts, f"${total:,.2f}", variacion, has_ia)
        prev_total = total

    console.print(table)
    console.print(f"\n  Total de snapshots: {len(snapshots)}\n")


@app.command()
def setup_fintual():
    """Abre el browser para que inicies sesión en Fintual (necesario la primera vez)."""
    import json
    from pathlib import Path
    from connectors.fintual import setup_session, SESSION_PATH
    setup_session()
    # Mostrar cookie de sesión para copiar a Streamlit Cloud secrets
    try:
        session = json.loads(SESSION_PATH.read_text())
        cookies = {c["name"]: c["value"] for c in session.get("cookies", [])}
        cookie = cookies.get("_fintual_session_cookie", "")
        if cookie:
            console.print("\n[bold yellow]─── Para Streamlit Cloud ─────────────────────────────────[/bold yellow]")
            console.print("Agrega este secret en Streamlit Cloud → Settings → Secrets:")
            console.print(f"\n[bold green]FINTUAL_SESSION_COOKIE = \"{cookie}\"[/bold green]\n")
            console.print("[dim](Dura ~30 días; cuando expire, vuelve a ejecutar setup-fintual)[/dim]\n")
    except Exception:
        pass


if __name__ == "__main__":
    app()
