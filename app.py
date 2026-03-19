from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import requests

TZ = ZoneInfo("America/Costa_Rica")
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "secret_key_123")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BARBEROS = {
    "1": {"nombre": "Sebastian", "telefono": "50660840460"},
    "2": {"nombre": "Barbero 2", "telefono": "50600000000"},
    "3": {"nombre": "Barbero 3", "telefono": "50600000000"}
}

SERVICIOS = {
    "Corte de cabello": {"precio": 5000, "duracion": 30},
    "Corte + barba": {"precio": 7000, "duracion": 60},
}

def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

def obtener_citas_barbero_fecha(barbero_id, fecha):
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero_id=eq.{barbero_id}&fecha=eq.{fecha}&order=hora.asc"
    res = requests.get(url, headers=_headers())
    try:
        data = res.json()
        return data if isinstance(data, list) else []
    except:
        return []

def calcular_precio(servicio):
    return SERVICIOS.get(servicio, {}).get("precio", 0)

def calcular_duracion(servicio):
    return SERVICIOS.get(servicio, {}).get("duracion", 30)

def hora_choque(hora_nueva, duracion_nueva, hora_existente, duracion_existente):
    inicio_nueva = datetime.strptime(hora_nueva.upper(), "%I:%M%p")
    fin_nueva = inicio_nueva + timedelta(minutes=duracion_nueva)

    inicio_existente = datetime.strptime(hora_existente.upper(), "%H:%M:%S")
    fin_existente = inicio_existente + timedelta(minutes=duracion_existente)

    return inicio_nueva < fin_existente and fin_nueva > inicio_existente

@app.route("/")
def index():
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    c_id = request.cookies.get("cliente_id") or str(uuid.uuid4())

    resp = make_response(
        render_template(
            "index.html",
            barberos=BARBEROS,
            servicios=SERVICIOS,
            hoy_iso=hoy,
            cliente_id=c_id
        )
    )
    resp.set_cookie("cliente_id", c_id, max_age=31536000)
    return resp

@app.route("/", methods=["POST"])
def agendar():
    try:
        cliente = request.form.get("cliente", "").strip()
        barbero_id = request.form.get("barbero_id", "").strip()
        servicio = request.form.get("servicio", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()

        if not cliente or not barbero_id or not servicio or not fecha or not hora:
            flash("Faltan datos para agendar la cita.")
            return redirect(url_for("index"))

        if barbero_id not in BARBEROS:
            flash("El barbero seleccionado no es válido.")
            return redirect(url_for("index"))

        if servicio not in SERVICIOS:
            flash("El servicio seleccionado no es válido.")
            return redirect(url_for("index"))

        citas_existentes = obtener_citas_barbero_fecha(barbero_id, fecha)
        duracion_nueva = calcular_duracion(servicio)

        for cita in citas_existentes:
            estado = str(cita.get("estado", "")).lower()
            if estado == "cancelada":
                continue

            hora_existente = str(cita.get("hora"))
            servicio_existente = cita.get("servicio", "")
            duracion_existente = calcular_duracion(servicio_existente)

            if hora_choque(hora, duracion_nueva, hora_existente, duracion_existente):
                flash("Ese barbero ya tiene una cita en ese horario.")
                return redirect(url_for("index"))

        hora_db = datetime.strptime(hora.upper(), "%I:%M%p").strftime("%H:%M:%S")

        data = {
            "cliente_nombre": cliente,
            "servicio": servicio,
            "fecha": fecha,
            "hora": hora_db,
            "barbero_id": int(barbero_id),
            "estado": "pendiente"
        }

        r = requests.post(f"{SUPABASE_URL}/rest/v1/citas", headers=_headers(), json=data)

        if r.status_code not in [200, 201]:
            print("Error Supabase:", r.status_code, r.text)
            flash("No se pudo guardar la cita.")
            return redirect(url_for("index"))

        flash("¡Cita agendada correctamente!")
    except Exception as e:
        print(f"Error agendando: {e}")
        flash("Ocurrió un error al agendar.")
    return redirect(url_for("index"))

@app.route("/horas")
def horas():
    fecha = request.args.get("fecha")
    barbero_id = request.args.get("barbero_id")
    servicio = request.args.get("servicio")

    if not all([fecha, barbero_id, servicio]):
        return jsonify([])

    if servicio not in SERVICIOS:
        return jsonify([])

    duracion_nueva = calcular_duracion(servicio)
    citas = obtener_citas_barbero_fecha(barbero_id, fecha)

    ocupados = []
    for cita in citas:
        estado = str(cita.get("estado", "")).lower()
        if estado == "cancelada":
            continue

        hora_existente = str(cita.get("hora"))
        servicio_existente = cita.get("servicio", "")
        duracion_existente = calcular_duracion(servicio_existente)

        inicio = datetime.strptime(hora_existente, "%H:%M:%S")
        fin = inicio + timedelta(minutes=duracion_existente)
        ocupados.append((inicio, fin))

    disponibles = []
    actual = datetime.strptime("09:00AM", "%I:%M%p")
    cierre = datetime.strptime("07:00PM", "%I:%M%p")

    while actual + timedelta(minutes=duracion_nueva) <= cierre:
        fin_actual = actual + timedelta(minutes=duracion_nueva)

        libre = True
        for inicio_ocupado, fin_ocupado in ocupados:
            if actual < fin_ocupado and fin_actual > inicio_ocupado:
                libre = False
                break

        if libre:
            disponibles.append(actual.strftime("%I:%M%p").lower())

        actual += timedelta(minutes=15)

    return jsonify(disponibles)

@app.route("/panel/<id_barbero>")
def panel_barbero(id_barbero):
    if id_barbero not in BARBEROS:
        flash("Barbero no encontrado.")
        return redirect(url_for("index"))

    url = f"{SUPABASE_URL}/rest/v1/citas?barbero_id=eq.{id_barbero}&order=fecha.asc,hora.asc"
    res = requests.get(url, headers=_headers())

    try:
        citas = res.json()
        citas = citas if isinstance(citas, list) else []
    except:
        citas = []

    for cita in citas:
        try:
            cita["hora_formateada"] = datetime.strptime(str(cita["hora"]), "%H:%M:%S").strftime("%I:%M %p")
        except:
            cita["hora_formateada"] = str(cita.get("hora", ""))

        cita["precio"] = calcular_precio(cita.get("servicio", ""))

    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    manana = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    modo = request.args.get("solo", "hoy")

    if modo == "hoy":
        filtradas = [c for c in citas if str(c.get("fecha")) == hoy]
    elif modo == "manana":
        filtradas = [c for c in citas if str(c.get("fecha")) == manana]
    else:
        filtradas = citas

    hoy_citas = [c for c in citas if str(c.get("fecha")) == hoy]
    hoy_atendidas = [c for c in hoy_citas if str(c.get("estado", "")).lower() == "atendida"]
    ganancia = sum(calcular_precio(c.get("servicio", "")) for c in hoy_atendidas)

    stats = {
        "id": id_barbero,
        "nombre": BARBEROS[id_barbero]["nombre"],
        "total": len(hoy_citas),
        "ganancia": ganancia,
        "modo": modo
    }

    return render_template("barbero.html", citas=filtradas, stats=stats)

@app.route("/atendida", methods=["POST"])
def atendida():
    cita_id = request.form.get("id")
    barbero_id = request.form.get("barbero_id")

    if not cita_id:
        flash("No se encontró la cita.")
        return redirect(url_for("index"))

    requests.patch(
        f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}",
        headers=_headers(),
        json={"estado": "atendida"}
    )

    flash("Cita marcada como atendida.")
    return redirect(url_for("panel_barbero", id_barbero=barbero_id))

@app.route("/dueno")
def panel_dueno():
    url = f"{SUPABASE_URL}/rest/v1/citas?order=fecha.asc,hora.asc"
    res = requests.get(url, headers=_headers())

    try:
        citas = res.json()
        citas = citas if isinstance(citas, list) else []
    except:
        citas = []

    for cita in citas:
        barbero_id = str(cita.get("barbero_id", ""))
        cita["barbero_nombre"] = BARBEROS.get(barbero_id, {}).get("nombre", "Sin asignar")
        cita["precio"] = calcular_precio(cita.get("servicio", ""))

        try:
            cita["hora_formateada"] = datetime.strptime(str(cita["hora"]), "%H:%M:%S").strftime("%I:%M %p")
        except:
            cita["hora_formateada"] = str(cita.get("hora", ""))

    return render_template("citas.html", citas=citas)

if __name__ == "__main__":
    app.run(debug=True)


