from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import requests

# Configuración Costa Rica
TZ = ZoneInfo("America/Costa_Rica")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "barberia_final_safe_2026")

# --- Credenciales ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# Diccionario de Barberos por ID
BARBEROS = {
    "1": {"nombre": "Sebastian", "telefono": "50660840460"},
    "2": {"nombre": "Barbero 2", "telefono": "50600000000"},
    "3": {"nombre": "Barbero 3", "telefono": "50600000000"}
}

SERVICIOS_DATA = {
    "Corte de cabello": {"precio": 5000, "duracion": 30},
    "Corte + barba": {"precio": 7000, "duracion": 60},
    "Solo barba": {"precio": 5000, "duracion": 30},
    "Solo cejas": {"precio": 2000, "duracion": 15},
}

def _supabase_headers():
    return {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}

# --- RUTAS CLIENTE ---

@app.route("/")
def index():
    ahora_cr = datetime.now(TZ)
    hoy_iso = ahora_cr.strftime("%Y-%m-%d")
    cliente_id = request.cookies.get("cliente_id") or str(uuid.uuid4())
    resp = make_response(render_template("index.html", barberos=BARBEROS, servicios=SERVICIOS_DATA, hoy_iso=hoy_iso, cliente_id=cliente_id))
    resp.set_cookie("cliente_id", cliente_id, max_age=31536000)
    return resp

@app.route("/", methods=["POST"])
def agendar():
    cliente = request.form.get("cliente", "").strip()
    b_id = request.form.get("barbero_id")
    serv_nom = request.form.get("servicio")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")
    c_id = request.form.get("cliente_id")

    b_info = BARBEROS.get(b_id, BARBEROS["1"])
    precio = SERVICIOS_DATA.get(serv_nom, {"precio": 0})["precio"]

    # Guardar por ID (Más seguro)
    url = f"{SUPABASE_URL}/rest/v1/citas"
    payload = {
        "cliente": cliente, "cliente_id": c_id, "barbero": b_id, 
        "servicio": serv_nom, "precio": precio, "fecha": fecha, "hora": hora
    }
    requests.post(url, headers=_supabase_headers(), json=payload)
    return redirect(url_for('index'))

@app.route("/horas")
def horas():
    fecha, b_id, serv_nom = request.args.get("fecha"), request.args.get("barbero_id"), request.args.get("servicio")
    if not all([fecha, b_id, serv_nom]): return jsonify([])

    dur_n = SERVICIOS_DATA.get(serv_nom, {"duracion": 30})["duracion"]
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{b_id}&fecha=eq.{fecha}&servicio=neq.CITA%20CANCELADA"
    
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
    ahora_cr = datetime.now(TZ)
    curr = datetime.strptime("09:00am", "%I:%M%p")
    fin_d = datetime.strptime("07:00pm", "%I:%M%p")

    while curr + timedelta(minutes=dur_n) <= fin_d:
        ini_p, fin_p = curr.time(), (curr + timedelta(minutes=dur_n)).time()
        es_futuro = True
        if fecha == ahora_cr.strftime("%Y-%m-%d"):
            if ini_p < ahora_cr.time(): es_futuro = False
        if es_futuro and all(not (fin_p > o_ini and ini_p < o_fin) for o_ini, o_fin in ocupados):
            disponibles.append(curr.strftime("%I:%M%p").lower())
        curr += timedelta(minutes=15)
    return jsonify(disponibles)

# --- RUTA PANEL BARBERO ---

@app.route("/panel/<id_barbero>")
def panel_barbero(id_barbero):
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{id_barbero}&order=fecha.asc,hora.asc"
    res = requests.get(url, headers=_supabase_headers()).json()
    if not isinstance(res, list): res = []

    # Fechas Costa Rica
    ahora_cr = datetime.now(TZ)
    hoy_str = ahora_cr.strftime("%Y-%m-%d")
    manana_str = (ahora_cr + timedelta(days=1)).strftime("%Y-%m-%d")

    # Filtro del selector
    solo = request.args.get("solo", "hoy")
    if solo == "hoy":
        citas_mostrar = [c for c in res if str(c.get("fecha")) == hoy_str]
    elif solo == "manana":
        citas_mostrar = [c for c in res if str(c.get("fecha")) == manana_str]
    else:
        citas_mostrar = res

    # Stats fijas de HOY
    citas_hoy = [c for c in res if str(c.get("fecha")) == hoy_str]
    ganancia = sum(int(float(str(c.get("precio", "0")).replace("₡", "").replace(",", ""))) 
                   for c in citas_hoy if c.get("servicio") == "CITA ATENDIDA")

    stats = {
        "nombre": BARBEROS.get(id_barbero, {"nombre": "Barbero"})["nombre"],
        "cant_total": len(citas_hoy),
        "cant_activas": len([c for c in citas_hoy if c.get("servicio") not in ["CITA ATENDIDA", "CITA CANCELADA"]]),
        "cant_atendidas": len([c for c in citas_hoy if c.get("servicio") == "CITA ATENDIDA"]),
        "total_atendido": ganancia,
        "solo": solo
    }

    return render_template("barbero.html", citas=citas_mostrar, stats=stats)

@app.route("/atendida", methods=["POST"])
def atendida():
    c_id = request.form.get("id")
    url = f"{SUPABASE_URL}/rest/v1/citas?id=eq.{c_id}"
    requests.patch(url, headers=_supabase_headers(), json={"servicio": "CITA ATENDIDA"})
    return redirect(request.referrer)

if __name__ == "__main__":
    app.run(debug=True)




