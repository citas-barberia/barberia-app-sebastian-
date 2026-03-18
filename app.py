from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import requests
import urllib.parse

# Configuración de Zona Horaria Costa Rica
TZ = ZoneInfo("America/Costa_Rica")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "barberia_pro_2026_key")

# --- Credenciales desde Render ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# 1. Definición Maestra de Barberos
BARBEROS = {
    "1": {"nombre": "Sebastian", "telefono": "50660840460"},
    "2": {"nombre": "Barbero 2", "telefono": "50600000000"},
    "3": {"nombre": "Barbero 3", "telefono": "50600000000"}
}

# 2. Servicios con Duración (Punto #1: Sin colchón fijo)
SERVICIOS_DATA = {
    "Corte de cabello": {"precio": 5000, "duracion": 30},
    "Corte + barba": {"precio": 7000, "duracion": 60},
    "Solo barba": {"precio": 5000, "duracion": 30},
    "Solo cejas": {"precio": 2000, "duracion": 15},
}

def _supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

def enviar_whatsapp(to_numero, mensaje):
    if not WHATSAPP_TOKEN: return
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_numero, "type": "text", "text": {"body": mensaje}}
    try: requests.post(url, headers=headers, json=payload, timeout=5)
    except: pass

# --- RUTAS ---

@app.route("/")
def index():
    # Hora real CR para el calendario
    hoy_cr = datetime.now(TZ).strftime("%Y-%m-%d")
    cliente_id = request.cookies.get("cliente_id") or str(uuid.uuid4())
    
    resp = make_response(render_template("index.html", 
                                       barberos=BARBEROS, 
                                       servicios=SERVICIOS_DATA, 
                                       hoy_iso=hoy_cr, 
                                       cliente_id=cliente_id))
    resp.set_cookie("cliente_id", cliente_id, max_age=31536000)
    return resp

@app.route("/", methods=["POST"])
def agendar():
    cliente = request.form.get("cliente")
    b_id = request.form.get("barbero_id")
    serv_nom = request.form.get("servicio")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")
    c_id = request.form.get("cliente_id")

    b_info = BARBEROS.get(b_id, BARBEROS["1"])
    precio = SERVICIOS_DATA.get(serv_nom, {"precio": 0})["precio"]

    # Guardar en Supabase
    url = f"{SUPABASE_URL}/rest/v1/citas"
    payload = {
        "cliente": cliente, "cliente_id": c_id, "barbero": b_info["nombre"],
        "servicio": serv_nom, "precio": precio, "fecha": fecha, "hora": hora
    }
    requests.post(url, headers=_supabase_headers(), json=payload)
    
    # Notificación al barbero elegido
    msg = f"💈 Cita Nueva\nCliente: {cliente}\nServicio: {serv_nom}\nFecha: {fecha}\nHora: {hora}"
    enviar_whatsapp(b_info["telefono"], msg)

    flash("¡Cita reservada con éxito!")
    return redirect(url_for('index'))

@app.route("/horas")
def horas():
    fecha, b_id, serv_nom = request.args.get("fecha"), request.args.get("barbero_id"), request.args.get("servicio")
    if not all([fecha, b_id, serv_nom]): return jsonify([])

    b_nom = BARBEROS.get(b_id, {}).get("nombre", "Sebastian")
    dur_n = SERVICIOS_DATA.get(serv_nom, {"duracion": 30})["duracion"]

    # Consultar disponibilidad
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{b_nom}&fecha=eq.{fecha}&servicio=neq.CITA%20CANCELADA"
    try:
        res = requests.get(url, headers=_supabase_headers()).json()
        ocupados = []
        for c in res:
            h_i = datetime.strptime(c['hora'], "%I:%M%p")
            d_o = SERVICIOS_DATA.get(c['servicio'], {"duracion": 30})["duracion"]
            h_f = h_i + timedelta(minutes=d_o)
            ocupados.append((h_i.time(), h_f.time()))
    except: ocupados = []

    disponibles = []
    # Lógica de tiempo real CR para no mostrar horas pasadas hoy
    ahora_cr = datetime.now(TZ)
    curr = datetime.strptime("09:00am", "%I:%M%p")
    fin_d = datetime.strptime("07:00pm", "%I:%M%p")

    while curr + timedelta(minutes=dur_n) <= fin_d:
        ini_p, fin_p = curr.time(), (curr + timedelta(minutes=dur_n)).time()
        
        # Validar si la hora ya pasó hoy
        es_futuro = True
        if fecha == ahora_cr.strftime("%Y-%m-%d"):
            if ini_p < ahora_cr.time(): es_futuro = False

        if es_futuro and all(not (fin_p > o_ini and ini_p < o_fin) for o_ini, o_fin in ocupados):
            disponibles.append(curr.strftime("%I:%M%p").lower())
        curr += timedelta(minutes=15)
        
    return jsonify(disponibles)

@app.route("/panel/<nombre>")
def panel_barbero(nombre):
    nombre_dec = urllib.parse.unquote(nombre)
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{nombre_dec}&order=fecha.asc,hora.asc"
    
    try:
        res = requests.get(url, headers=_supabase_headers()).json()
        if not isinstance(res, list): res = []
    except: res = []

    hoy_cr = datetime.now(TZ).strftime("%Y-%m-%d")
    citas_hoy = [c for c in res if str(c.get("fecha")) == hoy_cr]
    
    ganancia = 0
    for c in citas_hoy:
        if c.get("servicio") == "CITA ATENDIDA":
            try: ganancia += int(float(str(c.get("precio", "0")).replace("₡", "").replace(",", "")))
            except: pass

    stats = {
        "nombre": nombre_dec, 
        "total": len(citas_hoy), 
        "ganancia": ganancia,
        "activas": len([c for c in citas_hoy if c.get("servicio") not in ["CITA ATENDIDA", "CITA CANCELADA"]])
    }
    return render_template("barbero.html", citas=res, stats=stats)

@app.route("/atendida", methods=["POST"])
def atendida():
    c_id = request.form.get("id")
    url = f"{SUPABASE_URL}/rest/v1/citas?id=eq.{c_id}"
    requests.patch(url, headers=_supabase_headers(), json={"servicio": "CITA ATENDIDA"})
    return redirect(request.referrer)

if __name__ == "__main__":
    app.run(debug=True)




