import os
import json
import smtplib
import time
import google.generativeai as genai
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

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
modelo = genai.GenerativeModel("gemini-1.5-flash")

EMAIL_DESTINO  = os.environ["EMAIL_DESTINO"]
EMAIL_ORIGEN   = os.environ["EMAIL_ORIGEN"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

def obtener_novedades():
    fallos = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://sjconsulta.csjn.gov.ar/sjconsulta/novedades/consulta.html")
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        items = page.query_selector_all(".novedad, .item-novedad, tr.fila")
        for item in items:
            texto = item.inner_text().strip()
            if texto:
                link_el = item.query_selector("a")
                link = link_el.get_attribute("href") if link_el else ""
                fallos.append({"texto": texto, "link": link})
        browser.close()
    return fallos

def filtrar_con_gemini(fallos):
    if not fallos:
        return []
    fallos_texto = "\n\n---\n\n".join(
        [f"FALLO #{i+1}:\n{f['texto']}" for i, f in enumerate(fallos)]
    )
    prompt = f"""Sos un asistente especializado en derecho penal económico argentino.
Analizá los siguientes fallos de la CSJN y determiná cuáles son relevantes para:

{TEMAS_DE_INTERES}

FALLOS:
{fallos_texto}

Respondé ÚNICAMENTE con JSON válido, sin texto adicional ni bloques de código:
{{"relevantes": [{{"numero": 1, "motivo": "por qué es relevante en una línea", "resumen": "resumen en 2-3 oraciones"}}]}}

Si ninguno es relevante: {{"relevantes": []}}"""

    respuesta = modelo.generate_content(prompt)
    texto = respuesta.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    resultado = json.loads(texto)
    relevantes = []
    indices = {r["numero"] - 1: r for r in resultado["relevantes"]}
    for idx, fallo in enumerate(fallos):
        if idx in indices:
            fallo["analisis"] = indices[idx]
            relevantes.append(fallo)
    return relevantes

def enviar_email(relevantes):
    hoy = date.today().strftime("%d/%m/%Y")
    if not relevantes:
        asunto = f"[CSJN] {hoy} — Sin novedades de penal económico"
        cuerpo = f"<h2>Monitor CSJN – {hoy}</h2><p>Sin fallos relevantes hoy.</p>"
    else:
        asunto = f"[CSJN] {hoy} — {len(relevantes)} fallo(s) de penal económico"
        items = ""
        for f in relevantes:
            link_html = f'<a href="{f["link"]}">Ver fallo</a>' if f.get("link") else ""
            items += f"""
            <div style="border-left:4px solid #c0392b; padding-left:16px; margin-bottom:24px;">
                <p><strong>Por qué es relevante:</strong> {f["analisis"]["motivo"]}</p>
                <p><strong>Resumen:</strong> {f["analisis"]["resumen"]}</p>
                <p style="color:#666;font-size:12px">{f["texto"][:300]}...</p>
                {link_html}
            </div>"""
        cuerpo = f"""
        <h2>Monitor CSJN – {hoy}</h2>
        <h3 style="color:#c0392b">{len(relevantes)} fallo(s) — Fuero Penal Económico</h3>
        {items}
        <hr><small>Fuente: sj.csjn.gov.ar</small>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = EMAIL_ORIGEN
    msg["To"]      = EMAIL_DESTINO
    msg.attach(MIMEText(cuerpo, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())
    print(f"✓ Email enviado: {asunto}")

if __name__ == "__main__":
    print("Scrapeando novedades CSJN...")
    fallos = obtener_novedades()
    print(f"→ {len(fallos)} fallos encontrados")
    print("Analizando con Gemini...")
    relevantes = filtrar_con_gemini(fallos)
    print(f"→ {len(relevantes)} relevantes")
    print("Enviando email...")
    enviar_email(relevantes)
