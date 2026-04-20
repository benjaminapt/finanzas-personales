import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SESSION_PATH = Path.home() / ".finanzas" / "fintual_session.json"


def _get_browser_context(playwright, headless: bool = True):
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    # Usar storage_state completo (cookies + localStorage) si existe
    if SESSION_PATH.exists():
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            storage_state=str(SESSION_PATH),
        )
    else:
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
    return browser, ctx


def setup_session() -> None:
    """
    Abre el browser de forma VISIBLE para que el usuario se loguee en Fintual
    (incluyendo el código OTP que llega al email). Luego guarda la sesión.
    """
    from playwright.sync_api import sync_playwright

    print("\n🌐 Abriendo Fintual en el browser para que inicies sesión...")
    print("   Ingresa tu email, contraseña y el código que llegue a tu correo.")
    print("   El browser se cerrará automáticamente cuando detecte que ingresaste.\n")

    with sync_playwright() as p:
        browser, ctx = _get_browser_context(p, headless=False)
        page = ctx.new_page()
        page.goto("https://fintual.cl/f/sign-in/", wait_until="domcontentloaded")

        # Prefill email si está en .env
        email = os.getenv("FINTUAL_EMAIL", "")
        if email:
            try:
                page.fill('input[name=email]', email)
            except Exception:
                pass

        print("   Esperando que completes el login (máx. 5 minutos)...")
        print("   PASOS: 1) Ingresa tu email y contraseña  2) Revisa tu correo y escribe el código OTP\n")

        # Esperar hasta que la URL cambie a algo distinto del login
        try:
            page.wait_for_url(
                lambda url: "sign-in" not in url and "entrar" not in url and "fintual.cl" in url,
                timeout=300_000,  # 5 minutos
            )
        except Exception:
            print("⚠️  Tiempo agotado. Intenta de nuevo con: python3 -m cli.main setup-fintual")
            browser.close()
            return

        time.sleep(2)

        # Guardar estado completo (cookies + localStorage)
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(SESSION_PATH))
        print(f"✅ Sesión guardada en {SESSION_PATH}")
        browser.close()


class FintualClient:
    def get_goals(self) -> list[dict]:
        """
        Extrae metas/portafolios del usuario usando la sesión guardada.
        Si no hay sesión, lanza instrucciones para crearla.
        """
        if not SESSION_PATH.exists():
            raise RuntimeError(
                "No hay sesión de Fintual guardada.\n"
                "Ejecuta primero: python3 -m cli.main setup-fintual\n"
                "Se abrirá el browser para que inicies sesión una sola vez."
            )

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, ctx = _get_browser_context(p, headless=True)
            page = ctx.new_page()

            try:
                page.goto("https://fintual.cl/app/goals", wait_until="networkidle", timeout=30_000)
                time.sleep(3)

                # Si nos redirigió al login, la sesión expiró
                if "sign-in" in page.url or "entrar" in page.url or "f/sign" in page.url:
                    SESSION_PATH.unlink(missing_ok=True)
                    raise RuntimeError(
                        "Sesión de Fintual expirada.\n"
                        "Ejecuta: python3 -m cli.main setup-fintual"
                    )

                goals = _extract_goals(page)

                # Guardar estado actualizado
                ctx.storage_state(path=str(SESSION_PATH))

                return goals

            finally:
                browser.close()


def _extract_goals(page) -> list[dict]:
    """
    Extrae metas de fondos mutuos de la página /app/goals de Fintual.

    La página muestra texto en formato:
        [emoji] Nombre
        Descripción
        $ X.XXX.XXX
    """
    import re

    body_text = page.inner_text("body")
    goals = []

    # Parsear la sección "Inversiones" del texto de la página
    # Buscamos bloques: emoji+nombre, subtítulo opcional, monto CLP
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]

    # Encontrar inicio de sección Inversiones
    try:
        inv_start = next(i for i, l in enumerate(lines) if "Inversiones" in l)
    except StopIteration:
        inv_start = 0

    # Encontrar fin de sección (Acciones o Movimientos)
    try:
        inv_end = next(
            i for i, l in enumerate(lines)
            if i > inv_start and any(k in l for k in ["Acciones", "Movimientos", "Resumen"])
        )
    except StopIteration:
        inv_end = len(lines)

    section = lines[inv_start:inv_end]

    # Patron: línea con $ seguida de número (CLP)
    clp_pattern = re.compile(r"^\$\s*([\d.,]+)$")
    # Patrones a ignorar como nombres
    skip_patterns = re.compile(r"^(Inversiones|Crear|Depositar|Largo plazo|APV|Corto|Mediano)$", re.I)

    i = 0
    while i < len(section):
        line = section[i]
        match = clp_pattern.match(line)
        if match:
            # El valor en CLP está aquí — buscar nombre hacia atrás (1-3 líneas)
            num_str = match.group(1).replace(".", "").replace(",", "")
            try:
                nav_clp = float(num_str)
            except ValueError:
                i += 1
                continue

            # Buscar nombre: la línea anterior no-skip
            name = None
            for j in range(i - 1, max(i - 4, -1), -1):
                candidate = section[j]
                if not skip_patterns.match(candidate) and len(candidate) > 1:
                    # Limpiar emoji del inicio
                    name = re.sub(r"^[\U00010000-\U0010ffff\u2600-\u27BF\U0001F300-\U0001FAFF]+\s*", "", candidate).strip()
                    if name:
                        break

            if name and nav_clp > 1000:
                # Formato compatible con aggregator.py (mismo que la API REST)
                goals.append({"attributes": {"name": name, "nav": nav_clp}})
        i += 1

    if not goals:
        page.screenshot(path="/tmp/fintual_portfolio.png")
        print("[Fintual] ⚠️  No se pudieron extraer metas. Screenshot en /tmp/fintual_portfolio.png")

    return goals


class FintualAPIClient:
    """
    Cliente HTTP directo para la API de Fintual usando cookie de sesión.
    No requiere Playwright — compatible con Streamlit Cloud.

    La cookie `_fintual_session_cookie` se obtiene corriendo `setup-fintual`
    en Mac y copiando el valor al secret FINTUAL_SESSION_COOKIE en Streamlit Cloud.
    Dura ~30 días; cuando expira hay que renovarla.
    """

    BASE = "https://fintual.cl/api"

    def __init__(self, session_cookie: str):
        self._cookie = session_cookie

    def get_goals(self) -> list[dict]:
        """Retorna metas en el mismo formato que FintualClient.get_goals()."""
        import requests as _req
        r = _req.get(
            f"{self.BASE}/goals",
            cookies={"_fintual_session_cookie": self._cookie},
            timeout=10,
        )
        if r.status_code == 401:
            raise RuntimeError(
                "Cookie de sesión Fintual expirada.\n"
                "Ejecuta setup-fintual en tu Mac y actualiza FINTUAL_SESSION_COOKIE en Streamlit Cloud."
            )
        r.raise_for_status()
        return r.json().get("data", [])
