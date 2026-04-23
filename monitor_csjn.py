import os
import json
import smtplib
import time
from google import genai
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright

TEMAS_DE_INTERES = """
Fuero en lo Penal Económico. Incluye:
- Competencia del fuero penal económico (BCRA, CNV, UIF, AFIP, Aduana)
- Lavado de activos (Ley 25.246)
- Evasión fiscal y contrabando
- Delitos cambiarios, financieros, tributarios
- Resoluciones de incompetencia hacia/desde el fuero penal económico
- Cualquier mención a la Cámara Nacional en lo Penal Económico (CNPE)
- Recursos extraordinarios que vengan de ese fuero
"""

cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

EMAIL_DESTINO  = os.environ["EMAIL_DESTINO"]
EMAIL_ORIGEN   = os.environ["EMAIL_ORIGEN"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

# ─── SCRAPING ─────────────────────────────────────────────────

def scrape_pagina(page, url, selectores):
    items = []
    page.goto(url)
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    for selector in selectores:
        elementos = page.query_selector_all(selector)
        for el in elementos:
            texto = el.inner_text().strip()
            if texto:
                link_el = el.query_selector("a")
                link = link_el.get_attribute("href") if link_el else ""
                items.append({"texto": texto, "link": link})
    return items

def obtener_todo():
    resultados = {"sentencias": [], "acordadas": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Scrapeando sentencias...")
        resultados["sentencias"] = scrape_pagina(
            page,
            "https://sjconsulta.csjn.gov.ar/sjconsulta/novedades/consulta.html",
            [".novedad", ".item-novedad", "tr.fila"]
        )

        print("Scrapeando acordadas...")
        resultados["acordadas"] = scrape_pagina(
            page,
            "https://www.csjn.gov.ar/decisiones/acordadas",
            [".acordada", ".item-acordada", "tr.fila", "table tr"]
        )

        browser.close()
    return resultados

# ─── ANÁLISIS CON GEMINI ───────────────────────────────────────

def filtrar_con_gemini(items, tipo):
    if not items:
        return []

    texto = "\n\n---\n\n".join(
        [f"#{i+1}:\n{f['texto']}" for i, f in enumerate(items)]
    )

    prompt = f"""Sos un asistente especializado en derecho penal económico argentino.
Analizá los siguientes {tipo} de la CSJN y determiná cuáles son relevantes para:

{TEMAS_DE_INTERES}

{tipo.upper()}:
{texto}

Respondé ÚNICAMENTE con JSON válido, sin texto adicional ni bloques de código:
{{"relevantes": [{{"numero": 1, "motivo": "por qué es relevante en una línea", "resumen": "resumen en 2-3 oraciones"}}]}}

Si ninguno es relevante: {{"relevantes": []}}"""

    respuesta = cliente.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )
    txt = respuesta.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    resultado = json.loads(txt)

    relevantes = []
    indices = {r["numero"] - 1: r for r in resultado["relevantes"]}
    for idx, item in enumerate(items):
        if idx in indices:
            item["analisis"] = indices[idx]
            relevantes.append(item)
    return relevantes

# ─── EMAIL ─────────────────────────────────────────────────────

def construir_seccion(titulo, items, color):
    if not items:
        return f"<p><strong>{titulo}:</strong> Sin novedades relevantes.</p>"
    html = f"<h3 style='color:{color}'>{titulo} — {len(items)} novedad(es)</h3>"
    for f in items:
        link_html = f'<a href="{f["link"]}">Ver documento</a>' if f.get("link") else ""
        html += f"""
        <div style="border-left:4px solid {color}; padding-left:16px; margin-bottom:20px;">
            <p><strong>Por qué es relevante:</strong> {f["analisis"]["motivo"]}</p>
            <p><strong>Resumen:</strong> {f["analisis"]["resumen"]}</p>
            <p style="color:#666;font-size:12px">{f["texto"][:300]}...</p>
            {link_html}
        </div>"""
    return html

def enviar_email(sentencias, acordadas):
    hoy = date.today().strftime("%d/%m/%Y")
    total = len(sentencias) + len(acordadas)

    if total == 0:
        asunto = f"[CSJN] {hoy} — Sin novedades de penal económico"
    else:
        asunto = f"[CSJN] {hoy} — {total} novedad(es) de penal económico"

    cuerpo = f"""
    <h2>Monitor CSJN – {hoy}</h2>
    {construir_seccion("Sentencias", sentencias, "#c0392b")}
    <br>
    {construir_seccion("Acordadas", acordadas, "#2471a3")}
    <hr><small>Fuente: sj.csjn.gov.ar — csjn.gov.ar</small>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = EMAIL_ORIGEN
    msg["To"]      = EMAIL_DESTINO
    msg.attach(MIMEText(cuerpo, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())
    print(f"✓ Email enviado: {asunto}")

# ─── MAIN ──────────────────────────────────────────────────────

if __name__ == "__main__":
    datos = obtener_todo()

    print("Analizando sentencias con Gemini...")
    sentencias = filtrar_con_gemini(datos["sentencias"], "sentencias")

    print("Analizando acordadas con Gemini...")
    acordadas = filtrar_con_gemini(datos["acordadas"], "acordadas")

    print(f"→ {len(sentencias)} sentencias relevantes")
    print(f"→ {len(acordadas)} acordadas relevantes")

    enviar_email(sentencias, acordadas)
