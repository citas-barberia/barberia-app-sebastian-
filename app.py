from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import requests

# Configuración de Zona Horaria
TZ = ZoneInfo("America/Costa_Rica")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "clave_temporal_123")

# =========================
# CONFIGURACIÓN DE CREDENCIALES
# Reemplaza los valores entre comillas si no usas variables de entorno en Render
# =========================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# 1. Definición de los 3 Barberos
BARBEROS = {
    "1": {"nombre": "Sebastian", "telefono": "50660840460"},
    "2": {"nombre": "Barbero 2", "telefono": "50600000000"},
    "3": {"nombre": "Barbero 3", "telefono": "50600000000"}
}

# 2. Servicios con Duración (30 min y 1 hora)
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
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

def enviar_whatsapp(to_numero, mensaje):
    if not WHATSAPP_TOKEN: return
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to_numero, "type": "text", "text": {"body": mensaje}}
    try: requests.post(url, headers=headers, json=data, timeout=5)
    except: pass

@app.route("/", methods=["GET", "POST"])
def index():
    cliente_id = request.args.get("cliente_id") or request.cookies.get("cliente_id") or str(uuid.uuid4())
    hoy_iso = datetime.now(TZ).strftime("%Y-%m-%d")

    if request.method == "POST":
        cliente = request.form.get("cliente")
        b_id = request.form.get("barbero_id")
        serv_nom = request.form.get("servicio")
        fecha = request.form.get("fecha")
        hora = request.form.get("hora")
        
        b_info = BARBEROS.get(b_id, BARBEROS["1"])
        precio = SERVICIOS_DATA[serv_nom]["precio"]

        # Guardar en Supabase
        url = f"{SUPABASE_URL}/rest/v1/citas"
        payload = {
            "cliente": cliente,
            "cliente_id": cliente_id,
            "barbero": b_info["nombre"],
            "servicio": serv_nom,
            "precio": precio,
            "fecha": fecha,
            "hora": hora
        }
        requests.post(url, headers=_supabase_headers(), json=payload)

        # WhatsApp
        msg = f"💈 Cita: {cliente}\nBarbero: {b_info['nombre']}\nServicio: {serv_nom}\nHora: {hora}"
        enviar_whatsapp(b_info["telefono"], msg)

        flash("¡Cita agendada!")
        resp = make_response(redirect(url_for("index", cliente_id=cliente_id)))
        resp.set_cookie("cliente_id", cliente_id, max_age=31536000)
        return resp

    return render_template("index.html", barberos=BARBEROS, servicios=SERVICIOS_DATA, hoy_iso=hoy_iso)

@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    b_id = request.args.get("barbero_id")
    serv_nom = request.args.get("servicio")

    if not all([fecha, b_id, serv_nom]): return jsonify([])

    b_nom = BARBEROS[b_id]["nombre"]
    duracion_nueva = SERVICIOS_DATA[serv_nom]["duracion"]

    # Consultar Supabase
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{b_nom}&fecha=eq.{fecha}"
    try:
        res = requests.get(url, headers=_supabase_headers()).json()
        ocupados = []
        for c in res:
            if c.get("servicio") == "CITA CANCELADA": continue
            h_ini = datetime.strptime(c['hora'], "%I:%M%p")
            d_ocu = SERVICIOS_DATA.get(c['servicio'], {"duracion": 30})["duracion"]
            h_fin = h_ini + timedelta(minutes=d_ocu)
            ocupados.append((h_ini.time(), h_fin.time()))
    except:
        return jsonify([])

    disponibles = []
    curr = datetime.strptime("09:00am", "%I:%M%p")
    fin_dia = datetime.strptime("07:00pm", "%I:%M%p")

    while curr + timedelta(minutes=duracion_nueva) <= fin_dia:
        ini_p = curr.time()
        fin_p = (curr + timedelta(minutes=duracion_nueva)).time()
        
        es_libre = True
        for o_ini, o_fin in ocupados:
            if not (fin_p <= o_ini or ini_p >= o_fin):
                es_libre = False; break
        
        if es_libre: disponibles.append(curr.strftime("%I:%M%p").lower())
        curr += timedelta(minutes=15)

    return jsonify(disponibles)

@app.route("/panel/<nombre>")
def panel_barbero(nombre):
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero=eq.{nombre}&order=hora.asc"
    res = requests.get(url, headers=_supabase_headers()).json()
    
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    citas_hoy = [c for c in res if c.get("fecha") == hoy]
    
    stats = {
        "nombre": nombre,
        "total": len(citas_hoy),
        "ganancia": sum(int(c['precio']) for c in citas_hoy if c['servicio'] == "CITA ATENDIDA")
    }
    return render_template("barbero.html", citas=res, stats=stats)

if __name__ == "__main__":
    app.run(debug=True)




