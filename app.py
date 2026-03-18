from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import requests

TZ = ZoneInfo("America/Costa_Rica")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "barberia_secret_2026")

# --- Configuración ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

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

# --- RUTAS ---

@app.route("/")
def index_redirect():
    # Redirigir a la página principal con un ID de cliente si no existe
    cliente_id = request.cookies.get("cliente_id") or str(uuid.uuid4())
    hoy_iso = datetime.now(TZ).strftime("%Y-%m-%d")
    resp = make_response(render_template("index.html", barberos=BARBEROS, servicios=SERVICIOS_DATA, hoy_iso=hoy_iso, cliente_id=cliente_id))
    resp.set_cookie("cliente_id", cliente_id, max_age=31536000)
    return resp

@app.route("/", methods=["POST"])
def agendar():
    cliente = request.form.get("cliente")
    b_id = request.form.get("barbero_id")
    serv_nom = request.form.get("servicio")
    fecha = request.form.get("fecha")
    hora = request.form.get("hora")
    cliente_id = request.form.get("cliente_id")

    b_info = BARBEROS.get(b_id, BARBEROS["1"])
    precio = SERVICIOS_DATA.get(serv_nom, {"precio": 0})["precio"]

    url = f"{SUPABASE_URL}/rest/v1/citas"
    payload = {
        "cliente": cliente, "cliente_id": cliente_id, "barbero": b_info["nombre"],
        "servicio": serv_nom, "precio": precio, "fecha": fecha, "hora": hora
    }
    requests.post(url, headers=_supabase_headers(), json=payload)
    
    flash("¡Cita agendada correctamente!")
    return redirect(url_for('index_redirect'))

@app.route("/horas")
def horas():
    fecha, b_id, serv_nom = request.args.get("fecha"), request.args.get("barbero_id"), request.args.get("servicio")
    if not all([fecha, b_id, serv_nom]): return jsonify([])

    b_nom = BARBEROS.get(b_id, {}).get("nombre", "Sebastian")
    dur_n = SERVICIOS_DATA.get(serv_nom, {"duracion": 30})["duracion"]

    # Traer citas de Supabase
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{b_nom}&fecha=eq.{fecha}"
    try:
        res = requests.get(url, headers=_supabase_headers()).json()
        ocupados = []
        for c in res:
            if "CANCELADA" in str(c.get("servicio")): continue
            h_i = datetime.strptime(c['hora'], "%I:%M%p")
            # Duración de la cita ya guardada
            d_o = SERVICIOS_DATA.get(c['servicio'], {"duracion": 30})["duracion"]
            h_f = h_i + timedelta(minutes=d_o)
            ocupados.append((h_i.time(), h_f.time()))
    except: res = []

    disponibles = []
    curr = datetime.strptime("09:00am", "%I:%M%p")
    fin_d = datetime.strptime("07:00pm", "%I:%M%p")

    while curr + timedelta(minutes=dur_n) <= fin_d:
        ini_p, fin_p = curr.time(), (curr + timedelta(minutes=dur_n)).time()
        if all(not (fin_p > o_ini and ini_p < o_fin) for o_ini, o_fin in ocupados):
            disponibles.append(curr.strftime("%I:%M%p").lower())
        curr += timedelta(minutes=15)
    return jsonify(disponibles)

@app.route("/panel/<nombre>")
def panel_barbero(nombre):
    try:
        url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{nombre}&order=hora.asc"
        res = requests.get(url, headers=_supabase_headers()).json()
        if not isinstance(res, list): res = [] # Seguridad por si falla la red
    except:
        res = []

    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    citas_hoy = [c for c in res if c.get("fecha") == hoy]
    
    # Cálculo de ganancia seguro (evita errores si el precio es texto o nulo)
    ganancia = 0
    for c in citas_hoy:
        if c.get("servicio") == "CITA ATENDIDA":
            try: ganancia += int(c.get("precio", 0))
            except: pass

    stats = {"nombre": nombre, "total": len(citas_hoy), "ganancia": ganancia, "solo": "hoy"}
    return render_template("barbero.html", citas=res, stats=stats)

@app.route("/atendida", methods=["POST"])
def atendida():
    cita_id = request.form.get("id")
    url = f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}"
    requests.patch(url, headers=_supabase_headers(), json={"servicio": "CITA ATENDIDA"})
    return redirect(request.referrer or url_for('index_redirect'))

if __name__ == "__main__":
    app.run(debug=True)




