from flask import Flask, render_template, request, redirect, flash, url_for, jsonify, make_response
from dotenv import load_dotenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import uuid
import requests
import threading
import time

load_dotenv()

try:
    TZ = ZoneInfo("America/Costa_Rica")
except Exception:
    TZ = ZoneInfo("UTC")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "secret_key_123")
session = requests.Session()
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "barberia123")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

BARBEROS = {
    "1": {"nombre": "William", "telefono": "50672314147"},
    "2": {"nombre": "Jose Luis", "telefono": "50672314147"},
    "3": {"nombre": "Juan Carlos", "telefono": "50672314147"}
}
ALIAS_SERVICIOS = {
    "Corte de cabello": "Corte premium",
    "Corte": "Corte premium",
    "Corte + barba": "Corte y barba premium",
    "Barba": "Barba premium",
}
HORARIOS_ALMUERZO = {
    "1": {"inicio": "11:30AM", "fin": "12:30PM"},  # William
    "2": {"inicio": "12:00PM", "fin": "01:00PM"},  # Jose Luis
    "3": {"inicio": "12:00PM", "fin": "01:00PM"},  # Juan Carlos
}
SERVICIOS = {
    "Corte premium": {"precio": 6000, "duracion": 30},
    "Corte de cabello": {"precio": 6000, "duracion": 30},
    "Corte y barba premium": {"precio": 11000, "duracion": 60},
    "Corte y marcado de barba": {"precio": 8000, "duracion": 60},
    "Barba premium": {"precio": 6000, "duracion": 30},
}

HORARIO_SEMANA = {"inicio": "10:00AM", "fin": "07:00PM"}
HORARIO_SABADO = {"inicio": "09:00AM", "fin": "06:00PM"}

MESES_2026 = {
    "01": "Enero",
    "02": "Febrero",
    "03": "Marzo",
    "04": "Abril",
    "05": "Mayo",
    "06": "Junio",
    "07": "Julio",
    "08": "Agosto",
    "09": "Septiembre",
    "10": "Octubre",
    "11": "Noviembre",
    "12": "Diciembre",
}


def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

def obtener_almuerzo_barbero(barbero_id):
    return HORARIOS_ALMUERZO.get(str(barbero_id))

def cita_choca_con_almuerzo(barbero_id, hora, servicio):
    almuerzo = obtener_almuerzo_barbero(barbero_id)
    if not almuerzo:
        return False

    inicio_cita = datetime.strptime(hora.upper(), "%I:%M%p")
    fin_cita = inicio_cita + timedelta(minutes=calcular_duracion(servicio))

    inicio_almuerzo = datetime.strptime(almuerzo["inicio"], "%I:%M%p")
    fin_almuerzo = datetime.strptime(almuerzo["fin"], "%I:%M%p")

    return inicio_cita < fin_almuerzo and fin_cita > inicio_almuerzo
def normalizar_numero_cr(numero):
    numero = str(numero).strip().replace(" ", "").replace("-", "").replace("+", "")
    if numero.startswith("506"):
        return numero
    return f"506{numero}"

def normalizar_servicio_nombre(servicio):
    servicio = str(servicio).strip()
    return ALIAS_SERVICIOS.get(servicio, servicio)

def calcular_precio(servicio):
    servicio = normalizar_servicio_nombre(servicio)
    return SERVICIOS.get(servicio, {}).get("precio", 0)

def calcular_duracion(servicio):
    servicio = normalizar_servicio_nombre(servicio)
    return SERVICIOS.get(servicio, {}).get("duracion", 30)


def formatear_hora(hora_db):
    try:
        return datetime.strptime(str(hora_db), "%H:%M:%S").strftime("%I:%M %p")
    except Exception:
        return str(hora_db)

def obtener_horario_por_fecha(fecha_str):
    try:
        fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        dia = fecha_dt.weekday()  # lunes=0 ... domingo=6
    except Exception:
        return None

    if dia == 6:  # domingo
        return None
    if dia == 5:  # sábado
        return HORARIO_SABADO

    return HORARIO_SEMANA

def hora_choque(hora_nueva, duracion_nueva, hora_existente, duracion_existente):
    inicio_nueva = datetime.strptime(hora_nueva.upper(), "%I:%M%p")
    fin_nueva = inicio_nueva + timedelta(minutes=duracion_nueva)

    inicio_existente = datetime.strptime(hora_existente, "%H:%M:%S")
    fin_existente = inicio_existente + timedelta(minutes=duracion_existente)

    return inicio_nueva < fin_existente and fin_nueva > inicio_existente


def obtener_barbero_info(barbero_id):
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/barberos?id=eq.{barbero_id}",
            headers=_headers(),
            timeout=20
        )
        if res.status_code == 200:
            data = res.json()
            if data:
                return data[0]
    except Exception:
        pass
    return None


def barbero_disponible_hoy(barbero_id):
    barbero = obtener_barbero_info(barbero_id)
    if not barbero:
        return False
    return bool(barbero.get("activo", False)) and bool(barbero.get("disponible_hoy", False))


def obtener_todos_barberos():
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/barberos?order=id.asc",
            headers=_headers(),
            timeout=20
        )
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def obtener_citas_barbero_fecha(barbero_id, fecha):
    url = (
        f"{SUPABASE_URL}/rest/v1/citas"
        f"?barbero_id=eq.{barbero_id}"
        f"&fecha=eq.{fecha}"
        f"&order=hora.asc"
        f"&select=id,hora,servicio,estado,cliente_nombre,cliente_telefono,barbero_id"
    )
    try:
        res = session.get(url, headers=_headers(), timeout=20)
        data = res.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


    
def obtener_todas_citas_barbero(barbero_id):
    url = f"{SUPABASE_URL}/rest/v1/citas?barbero_id=eq.{barbero_id}&order=fecha.asc,hora.asc"
    try:
        res = requests.get(url, headers=_headers(), timeout=20)
        data = res.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []
def obtener_citas_barbero_filtradas(barbero_id, modo="hoy", mes=None):
    hoy_dt = datetime.now(TZ).date()

    if modo == "hoy":
        fecha_inicio = fecha_fin = hoy_dt.strftime("%Y-%m-%d")
    elif modo == "manana":
        manana = hoy_dt + timedelta(days=1)
        fecha_inicio = fecha_fin = manana.strftime("%Y-%m-%d")
    elif modo == "historial_2026":
        mes = mes or datetime.now(TZ).strftime("%m")
        fecha_inicio = f"2026-{mes}-01"

        if mes == "12":
            fecha_fin = "2026-12-31"
        else:
            anio = 2026
            mes_int = int(mes)
            if mes_int == 12:
                siguiente_mes = datetime(anio + 1, 1, 1)
            else:
                siguiente_mes = datetime(anio, mes_int + 1, 1)
            fecha_fin = (siguiente_mes - timedelta(days=1)).strftime("%Y-%m-%d")

    elif modo == "todas":
        fecha_inicio = None
        fecha_fin = None
    else:
        fecha_inicio = fecha_fin = hoy_dt.strftime("%Y-%m-%d")

    params = [
        f"barbero_id=eq.{barbero_id}",
        "order=fecha.asc,hora.asc",
        "select=id,cliente_nombre,servicio,fecha,hora,estado,barbero_id,origen"
    ]

    if fecha_inicio and fecha_fin:
        params.append(f"fecha=gte.{fecha_inicio}")
        params.append(f"fecha=lte.{fecha_fin}")

    url = f"{SUPABASE_URL}/rest/v1/citas?{'&'.join(params)}"

    try:
        res = session.get(url, headers=_headers(), timeout=20)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        print("Error obteniendo citas filtradas:", e)

    return []

def obtener_cita_por_id(cita_id):
    url = f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}"
    try:
        res = session.get(url, headers=_headers(), timeout=20)
        data = res.json()
        if isinstance(data, list) and data:
            return data[0]
    except Exception:
        pass
    return None


def enviar_whatsapp_texto(numero, mensaje):
    try:
        if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            print("WhatsApp no configurado en variables de entorno.")
            return None

        numero = normalizar_numero_cr(numero)

        url = f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "text",
            "text": {"body": mensaje}
        }
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print("WHATSAPP STATUS:", r.status_code)
        print("WHATSAPP RESPUESTA:", r.text)
        return r
    except Exception as e:
        print("Error enviando WhatsApp:", e)
        return None

def enviar_whatsapp_template_confirmacion(numero, nombre_cliente, nombre_barbero, servicio, fecha, hora, link_cancelacion):
    try:
        if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            print("WhatsApp no configurado en variables de entorno.")
            return None

        numero = normalizar_numero_cr(numero)

        url = f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "template",
            "template": {
                "name": "confirmacion_cita",
                "language": {
                    "code": "es_CR"
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(nombre_cliente)},
                            {"type": "text", "text": str(nombre_barbero)},
                            {"type": "text", "text": str(servicio)},
                            {"type": "text", "text": str(fecha)},
                            {"type": "text", "text": str(hora)},
                            {"type": "text", "text": str(link_cancelacion)}
                        ]
                    }
                ]
            }
        }

        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print("WHATSAPP TEMPLATE STATUS:", r.status_code)
        print("WHATSAPP TEMPLATE RESPUESTA:", r.text)
        return r

    except Exception as e:
        print("Error enviando template de WhatsApp:", e)
        return None
    
def enviar_whatsapp_template_recordatorio(numero, nombre_cliente, nombre_barbero, hora, servicio):
    try:
        if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            print("WhatsApp no configurado en variables de entorno.")
            return None

        numero = normalizar_numero_cr(numero)

        url = f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "template",
            "template": {
                "name": "recordatorio_cita_30min_cr",
                "language": {
                    "code": "es_CR"
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(nombre_cliente)},
                            {"type": "text", "text": str(nombre_barbero)},
                            {"type": "text", "text": str(hora)},
                            {"type": "text", "text": str(servicio)}
                        ]
                    }
                ]
            }
        }

        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print("WHATSAPP RECORDATORIO TEMPLATE STATUS:", r.status_code)
        print("WHATSAPP RECORDATORIO TEMPLATE RESPUESTA:", r.text)
        return r

    except Exception as e:
        print("Error enviando template de recordatorio:", e)
        return None
    
def enviar_whatsapp_template_barbero(numero, cliente, servicio, fecha, hora, barbero):
    try:
        if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            print("WhatsApp no configurado en variables de entorno.")
            return None

        numero = normalizar_numero_cr(numero)

        url = f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "template",
            "template": {
                "name": "nueva_cita_barbero_cr",
                "language": {
                    "code": "es_CR"
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(cliente)},
                            {"type": "text", "text": str(servicio)},
                            {"type": "text", "text": str(fecha)},
                            {"type": "text", "text": str(hora)},
                            {"type": "text", "text": str(barbero)}
                        ]
                    }
                ]
            }
        }

        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print("WHATSAPP BARBERO TEMPLATE STATUS:", r.status_code)
        print("WHATSAPP BARBERO TEMPLATE RESPUESTA:", r.text)
        return r

    except Exception as e:
        print("Error enviando template al barbero:", e)
        return None

def enviar_whatsapp_template_cancelacion_barbero(numero, cliente, servicio, fecha, hora, barbero):
    try:
        if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            print("WhatsApp no configurado en variables de entorno.")
            return None

        numero = normalizar_numero_cr(numero)

        url = f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "template",
            "template": {
                "name": "cancelacion_cliente_barbero_cr",
                "language": {
                    "code": "es_CR"
                },
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(cliente)},
                            {"type": "text", "text": str(servicio)},
                            {"type": "text", "text": str(fecha)},
                            {"type": "text", "text": str(hora)},
                            {"type": "text", "text": str(barbero)}
                        ]
                    }
                ]
            }
        }

        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print("WHATSAPP CANCELACION BARBERO STATUS:", r.status_code)
        print("WHATSAPP CANCELACION BARBERO RESPUESTA:", r.text)
        return r

    except Exception as e:
        print("Error enviando template de cancelación al barbero:", e)
        return None        
    
def inicializar_barberos():
    try:
        for b_id, info in BARBEROS.items():
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/barberos?id=eq.{b_id}",
                headers=_headers(),
                timeout=20
            )
            if res.status_code == 200 and res.json():
                continue

            data = {
                "id": int(b_id),
                "nombre": info["nombre"],
                "activo": True,
                "disponible_hoy": True,
                "created_at": datetime.now(TZ).isoformat()
            }
            requests.post(
                f"{SUPABASE_URL}/rest/v1/barberos",
                headers=_headers(),
                json=data,
                timeout=20
            )
        print("Barberos inicializados correctamente")
    except Exception as e:
        print(f"Error inicializando barberos: {e}")


@app.route("/")
def index():
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    c_id = request.cookies.get("cliente_id") or str(uuid.uuid4())

    barberos_info = obtener_todos_barberos()

    barberos_visibles = {}
    for barbero in barberos_info:
        bid = str(barbero.get("id"))

        # Disponible = acepta citas en general (hoy o futuro)
        if bool(barbero.get("disponible_hoy", False)):
            nombre = BARBEROS.get(bid, {}).get("nombre", barbero.get("nombre", "Barbero"))
            barberos_visibles[bid] = {
                "nombre": nombre,
                "telefono": BARBEROS.get(bid, {}).get("telefono", "")
            }

    resp = make_response(
        render_template(
            "index.html",
            barberos=barberos_visibles,
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
        cliente_telefono = request.form.get("cliente_telefono", "").strip()
        barbero_id = request.form.get("barbero_id", "").strip()
        servicio = normalizar_servicio_nombre(request.form.get("servicio", "").strip())
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()

        if not cliente or not cliente_telefono or not barbero_id or not servicio or not fecha or not hora:
            flash("Faltan datos para agendar la cita.")
            return redirect(url_for("index"))

        if barbero_id not in BARBEROS:
            flash("El barbero seleccionado no es válido.")
            return redirect(url_for("index"))

        barbero = obtener_barbero_info(barbero_id)
        if not barbero:
            flash("No se encontró el barbero seleccionado.")
            return redirect(url_for("index"))

        if not bool(barbero.get("disponible_hoy", False)):
            flash("Ese barbero no está disponible para agenda.")
            return redirect(url_for("index"))

        if servicio not in SERVICIOS:
            flash("El servicio seleccionado no es válido.")
            return redirect(url_for("index"))

        if cita_choca_con_almuerzo(barbero_id, hora, servicio):
            flash("Ese horario no está disponible porque coincide con la hora de comida del barbero.")
            return redirect(url_for("index"))

        hoy_cr = datetime.now(TZ).strftime("%Y-%m-%d")
        if fecha < hoy_cr:
            flash("No puedes agendar en una fecha pasada.")
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
        token_cancelacion = str(uuid.uuid4())
        link_cancelacion = f"{request.host_url.rstrip('/')}/cancelar/{token_cancelacion}"

        data = {
            "cliente_nombre": cliente,
            "cliente_telefono": normalizar_numero_cr(cliente_telefono),
            "servicio": servicio,
            "fecha": fecha,
            "hora": hora_db,
            "barbero_id": int(barbero_id),
            "estado": "pendiente",
            "origen": "online",
            "recordatorio_30_enviado": False,
            "token_cancelacion": token_cancelacion
        }

        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/citas",
            headers=_headers(),
            json=data,
            timeout=20
        )

        if r.status_code not in [200, 201]:
            print("STATUS SUPABASE:", r.status_code)
            print("RESPUESTA SUPABASE:", r.text)
            flash("No se pudo guardar la cita.")
            return redirect(url_for("index"))

        nombre_barbero = BARBEROS[barbero_id]["nombre"]
        telefono_barbero = BARBEROS[barbero_id]["telefono"]

        r_barbero = enviar_whatsapp_template_barbero(
            numero=telefono_barbero,
            cliente=cliente,
            servicio=servicio,
            fecha=fecha,
            hora=hora,
            barbero=nombre_barbero
        )

        if r_barbero is None or r_barbero.status_code not in [200, 201]:
            print("No se pudo enviar la notificación template al barbero.")

        enviar_whatsapp_template_confirmacion(
            numero=cliente_telefono,
            nombre_cliente=cliente,
            nombre_barbero=nombre_barbero,
            servicio=servicio,
            fecha=fecha,
            hora=hora,
            link_cancelacion=link_cancelacion
        )

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
    print("ARGS /horas:", fecha, barbero_id, servicio)

    if not all([fecha, barbero_id, servicio]):
        return jsonify([])

    if barbero_id not in BARBEROS:
        return jsonify([])

    servicio = normalizar_servicio_nombre(servicio)
    if servicio not in SERVICIOS:
        return jsonify([])

    horario = obtener_horario_por_fecha(fecha)
    if not horario:
        return jsonify([])

    barbero = obtener_barbero_info(barbero_id)
    if not barbero:
        return jsonify([])

    if not bool(barbero.get("disponible_hoy", False)):
        return jsonify([])

    duracion_nueva = calcular_duracion(servicio)
    citas = obtener_citas_barbero_fecha(barbero_id, fecha)

    ocupados = []

    # Citas existentes
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

    # Almuerzo: solo cliente
    almuerzo = obtener_almuerzo_barbero(barbero_id)
    if almuerzo:
        inicio_almuerzo = datetime.strptime(almuerzo["inicio"], "%I:%M%p")
        fin_almuerzo = datetime.strptime(almuerzo["fin"], "%I:%M%p")
        ocupados.append((inicio_almuerzo, fin_almuerzo))

    disponibles = []
    apertura = datetime.strptime(horario["inicio"], "%I:%M%p")
    cierre = datetime.strptime(horario["fin"], "%I:%M%p")

    fecha_hoy_cr = datetime.now(TZ).strftime("%Y-%m-%d")
    ahora_cr = datetime.now(TZ)

    actual = apertura
    while actual + timedelta(minutes=duracion_nueva) <= cierre:
        fin_actual = actual + timedelta(minutes=duracion_nueva)
        libre = True

        for inicio_ocupado, fin_ocupado in ocupados:
            if actual < fin_ocupado and fin_actual > inicio_ocupado:
                libre = False
                break

        if libre:
            if fecha == fecha_hoy_cr:
                hora_slot_hoy = ahora_cr.replace(
                    hour=actual.hour,
                    minute=actual.minute,
                    second=0,
                    microsecond=0
                )
                if hora_slot_hoy > ahora_cr:
                    disponibles.append(actual.strftime("%I:%M%p").lower())
            else:
                disponibles.append(actual.strftime("%I:%M%p").lower())

        actual += timedelta(minutes=15)

    print("HORAS DISPONIBLES CLIENTE:", disponibles)
    return jsonify(disponibles)

@app.route("/horas_admin")
def horas_admin():
    fecha = request.args.get("fecha")
    barbero_id = request.args.get("barbero_id")
    servicio = request.args.get("servicio")
    print("ARGS /horas_admin:", fecha, barbero_id, servicio)

    if not all([fecha, barbero_id, servicio]):
        return jsonify([])

    if barbero_id not in BARBEROS:
        return jsonify([])

    servicio = normalizar_servicio_nombre(servicio)
    if servicio not in SERVICIOS:
        return jsonify([])

    horario = obtener_horario_por_fecha(fecha)
    if not horario:
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
    apertura = datetime.strptime(horario["inicio"], "%I:%M%p")
    cierre = datetime.strptime(horario["fin"], "%I:%M%p")

    fecha_hoy_cr = datetime.now(TZ).strftime("%Y-%m-%d")
    ahora_cr = datetime.now(TZ)

    actual = apertura
    while actual + timedelta(minutes=duracion_nueva) <= cierre:
        fin_actual = actual + timedelta(minutes=duracion_nueva)
        libre = True

        for inicio_ocupado, fin_ocupado in ocupados:
            if actual < fin_ocupado and fin_actual > inicio_ocupado:
                libre = False
                break

        if libre:
            if fecha == fecha_hoy_cr:
                hora_slot_hoy = ahora_cr.replace(
                    hour=actual.hour,
                    minute=actual.minute,
                    second=0,
                    microsecond=0
                )
                if hora_slot_hoy > ahora_cr:
                    disponibles.append(actual.strftime("%I:%M%p").lower())
            else:
                disponibles.append(actual.strftime("%I:%M%p").lower())

        actual += timedelta(minutes=15)

    print("HORAS DISPONIBLES ADMIN:", disponibles)
    return jsonify(disponibles)


@app.route("/cancelar_cliente", methods=["POST"])
def cancelar_cliente():
    try:
        cliente = request.form.get("cliente", "").strip()
        barbero_id = request.form.get("barbero_id", "").strip()
        fecha = request.form.get("fecha", "").strip()
        hora = request.form.get("hora", "").strip()

        if not cliente or not barbero_id or not fecha or not hora:
            flash("Completa todos los datos para cancelar.")
            return redirect(url_for("index"))

        hora_db = datetime.strptime(hora.upper(), "%I:%M%p").strftime("%H:%M:%S")

        buscar_url = (
            f"{SUPABASE_URL}/rest/v1/citas"
            f"?cliente_nombre=eq.{cliente}"
            f"&barbero_id=eq.{barbero_id}"
            f"&fecha=eq.{fecha}"
            f"&hora=eq.{hora_db}"
        )

        res = requests.get(buscar_url, headers=_headers(), timeout=20)
        data = res.json() if res.ok else []

        if not data:
            flash("No se encontró una cita con esos datos.")
            return redirect(url_for("index"))

        cita = data[0]
        cita_id = cita["id"]

        patch = requests.patch(
            f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}",
            headers=_headers(),
            json={"estado": "cancelada"},
            timeout=20
        )

        if patch.status_code not in [200, 204]:
            flash("No se pudo cancelar la cita.")
            return redirect(url_for("index"))

        nombre_barbero = BARBEROS[barbero_id]["nombre"]
        telefono_barbero = BARBEROS[barbero_id]["telefono"]
        cliente_telefono = cita.get("cliente_telefono", "")

        mensaje_barbero = (
            f"❌ Cita cancelada\n"
            f"Cliente: {cliente}\n"
            f"Fecha: {fecha}\n"
            f"Hora: {hora}\n"
            f"Barbero: {nombre_barbero}"
        )

        mensaje_cliente = (
            f"❌ Tu cita fue cancelada correctamente\n"
            f"Barbero: {nombre_barbero}\n"
            f"Fecha: {fecha}\n"
            f"Hora: {hora}"
        )

        enviar_whatsapp_texto(telefono_barbero, mensaje_barbero)
        if cliente_telefono:
            enviar_whatsapp_texto(cliente_telefono, mensaje_cliente)

        flash("Cita cancelada correctamente.")
    except Exception as e:
        print("Error cancelando cliente:", e)
        flash("Ocurrió un error al cancelar la cita.")

    return redirect(url_for("index"))

@app.route("/cancelar/<token>", methods=["GET", "POST"])
def cancelar_por_token(token):
    try:
        url = f"{SUPABASE_URL}/rest/v1/citas?token_cancelacion=eq.{token}"
        res = requests.get(url, headers=_headers(), timeout=20)

        if res.status_code != 200:
            flash("No se pudo validar la cita.")
            return redirect(url_for("index"))

        data = res.json()
        citas = data if isinstance(data, list) else []

        if not citas:
            flash("No se encontró una cita válida para cancelar.")
            return redirect(url_for("index"))

        cita = citas[0]

        if request.method == "GET":
            return render_template(
                "cancelar_cita.html",
                cita={
                    "id": cita.get("id"),
                    "cliente_nombre": cita.get("cliente_nombre", ""),
                    "barbero_id": str(cita.get("barbero_id", "")),
                    "barbero_nombre": BARBEROS.get(str(cita.get("barbero_id", "")), {}).get("nombre", "Barbero"),
                    "servicio": cita.get("servicio", ""),
                    "fecha": cita.get("fecha", ""),
                    "hora": formatear_hora(cita.get("hora", "")),
                    "estado": cita.get("estado", "")
                }
            )

        if str(cita.get("estado", "")).lower() == "cancelada":
            return render_template(
                "cancelar_cita.html",
                cita={
                    "id": cita.get("id"),
                    "cliente_nombre": cita.get("cliente_nombre", ""),
                    "barbero_id": str(cita.get("barbero_id", "")),
                    "barbero_nombre": BARBEROS.get(str(cita.get("barbero_id", "")), {}).get("nombre", "Barbero"),
                    "servicio": cita.get("servicio", ""),
                    "fecha": cita.get("fecha", ""),
                    "hora": formatear_hora(cita.get("hora", "")),
                    "estado": cita.get("estado", "")
                }
            )

        cita_id = cita.get("id")
        barbero_id = str(cita.get("barbero_id", ""))
        cliente_nombre = cita.get("cliente_nombre", "")
        fecha = cita.get("fecha", "")
        hora = formatear_hora(cita.get("hora", ""))
        servicio = cita.get("servicio", "")

        patch = requests.patch(
            f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}",
            headers=_headers(),
            json={"estado": "cancelada"},
            timeout=20
        )

        if patch.status_code not in [200, 204]:
            flash("No se pudo cancelar la cita.")
            return redirect(url_for("index"))

        nombre_barbero = BARBEROS.get(barbero_id, {}).get("nombre", "Barbero")
        telefono_barbero = BARBEROS.get(barbero_id, {}).get("telefono", "")

        if telefono_barbero:
            r_cancelacion_barbero = enviar_whatsapp_template_cancelacion_barbero(
                numero=telefono_barbero,
                cliente=cliente_nombre,
                servicio=servicio,
                fecha=fecha,
                hora=hora,
                barbero=nombre_barbero
            )

            if r_cancelacion_barbero is None or r_cancelacion_barbero.status_code not in [200, 201]:
                print("No se pudo enviar la notificación de cancelación al barbero.")

        return render_template(
            "cancelacion_exitosa.html",
            cliente_nombre=cliente_nombre,
            barbero_nombre=nombre_barbero,
            servicio=servicio,
            fecha=fecha,
            hora=hora
        )

    except Exception as e:
        print("Error cancelando por token:", e)
        flash("Ocurrió un error al cancelar la cita.")
        return redirect(url_for("index"))


@app.route("/panel/<id_barbero>")
def panel_barbero(id_barbero):
    if id_barbero not in BARBEROS:
        flash("Barbero no encontrado.")
        return redirect(url_for("index"))

    citas = obtener_todas_citas_barbero(id_barbero)

    for cita in citas:
        cita["hora_formateada"] = formatear_hora(cita.get("hora"))
        cita["precio"] = calcular_precio(cita.get("servicio", ""))

    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    manana = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    modo = request.args.get("solo", "hoy")
    mes = request.args.get("mes", datetime.now(TZ).strftime("%m"))

    if modo == "hoy":
        filtradas = [c for c in citas if str(c.get("fecha")) == hoy and str(c.get("estado", "")).lower() != "cancelada"]
    elif modo == "manana":
        filtradas = [c for c in citas if str(c.get("fecha")) == manana and str(c.get("estado", "")).lower() != "cancelada"]
    elif modo == "historial_2026":
        filtradas = [c for c in citas if str(c.get("fecha", "")).startswith(f"2026-{mes}-")]
    else:
        filtradas = [c for c in citas if str(c.get("estado", "")).lower() != "cancelada"]

    hoy_citas = [c for c in citas if str(c.get("fecha")) == hoy and str(c.get("estado", "")).lower() != "cancelada"]
    hoy_atendidas = [c for c in hoy_citas if str(c.get("estado", "")).lower() == "atendida"]
    hoy_canceladas = [c for c in citas if str(c.get("fecha")) == hoy and str(c.get("estado", "")).lower() == "cancelada"]

    ganancia = sum(calcular_precio(c.get("servicio", "")) for c in hoy_atendidas)

    stats = {
        "id": id_barbero,
        "nombre": BARBEROS[id_barbero]["nombre"],
        "total": len(hoy_citas),
        "ganancia": ganancia,
        "canceladas_hoy": len(hoy_canceladas),
        "modo": modo,
        "mes": mes
    }

    return render_template(
        "barbero.html",
        citas=filtradas,
        stats=stats,
        meses_2026=MESES_2026
    )


@app.route("/atendida", methods=["POST"])
def atendida():
    cita_id = request.form.get("id")
    barbero_id = request.form.get("barbero_id")
    desde_dueno = request.form.get("desde_dueno")

    if not cita_id:
        flash("No se encontró la cita.")
        return redirect(url_for("index"))

    requests.patch(
        f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}",
        headers=_headers(),
        json={"estado": "atendida"},
        timeout=20
    )

    flash("Cita marcada como atendida.")

    if desde_dueno == "1":
        return redirect(url_for("panel_dueno"))

    return redirect(url_for("panel_barbero", id_barbero=barbero_id))


@app.route("/cancelar_barbero", methods=["POST"])
def cancelar_barbero():
    cita_id = request.form.get("id")
    barbero_id = request.form.get("barbero_id")
    desde_dueno = request.form.get("desde_dueno")

    if not cita_id:
        flash("No se encontró la cita.")
        return redirect(url_for("index"))

    cita = obtener_cita_por_id(cita_id)

    requests.patch(
        f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita_id}",
        headers=_headers(),
        json={"estado": "cancelada"},
        timeout=20
    )

    if cita:
        cliente_telefono = cita.get("cliente_telefono", "")
        cliente_nombre = cita.get("cliente_nombre", "")
        fecha = cita.get("fecha", "")
        hora = formatear_hora(cita.get("hora", ""))
        nombre_barbero = BARBEROS.get(barbero_id, {}).get("nombre", "Barbero")

        mensaje_cliente = (
            f"❌ Tu cita fue cancelada por la barbería\n"
            f"Barbero: {nombre_barbero}\n"
            f"Fecha: {fecha}\n"
            f"Hora: {hora}\n"
            f"Cliente: {cliente_nombre}"
        )

        if cliente_telefono:
            enviar_whatsapp_texto(cliente_telefono, mensaje_cliente)

    flash("Cita cancelada correctamente.")

    if desde_dueno == "1":
        return redirect(url_for("panel_dueno"))

    return redirect(url_for("panel_barbero", id_barbero=barbero_id))

def obtener_rango_vista(vista):
    ahora = datetime.now(TZ)
    hoy = ahora.date()

    if vista == "manana":
        inicio = hoy + timedelta(days=1)
        fin = inicio
        titulo = "Agenda de mañana"
        subtitulo = "Citas agendadas para el día siguiente"
        label_citas = "Citas mañana"
        empty_text = "Sin citas mañana"
    elif vista == "semana":
        inicio = hoy - timedelta(days=hoy.weekday())  # lunes
        fin = inicio + timedelta(days=6)              # domingo
        titulo = "Resumen semanal"
        subtitulo = "Productividad y citas de la semana"
        label_citas = "Citas semana"
        empty_text = "Sin citas esta semana"
    elif vista == "mes":
        inicio = hoy.replace(day=1)
        if inicio.month == 12:
            siguiente_mes = inicio.replace(year=inicio.year + 1, month=1, day=1)
        else:
            siguiente_mes = inicio.replace(month=inicio.month + 1, day=1)
        fin = siguiente_mes - timedelta(days=1)
        titulo = "Resumen mensual"
        subtitulo = "Ingresos y citas del mes actual"
        label_citas = "Citas mes"
        empty_text = "Sin citas este mes"
    else:
        inicio = hoy
        fin = hoy
        titulo = "Panel Administrativo"
        subtitulo = "Vista general de la barbería y citas de hoy"
        label_citas = "Citas hoy"
        empty_text = "Sin citas hoy"
        vista = "inicio"

    return {
        "vista": vista,
        "inicio": inicio.strftime("%Y-%m-%d"),
        "fin": fin.strftime("%Y-%m-%d"),
        "titulo": titulo,
        "subtitulo": subtitulo,
        "label_citas": label_citas,
        "empty_text": empty_text
    }


def obtener_citas_rango(fecha_inicio, fecha_fin):
    url = (
        f"{SUPABASE_URL}/rest/v1/citas"
        f"?fecha=gte.{fecha_inicio}&fecha=lte.{fecha_fin}"
        f"&order=fecha.asc,hora.asc"
    )

    try:
        res = requests.get(url, headers=_headers(), timeout=20)
        if res.status_code == 200:
            data = res.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass

    return []


def enriquecer_cita(cita, barberos_dict):
    barbero_id = str(cita.get("barbero_id", ""))
    cita["barbero_nombre"] = barberos_dict.get(barbero_id, {}).get("nombre", "Sin asignar")
    cita["barbero_activo"] = barberos_dict.get(barbero_id, {}).get("activo", False)
    cita["precio"] = calcular_precio(cita.get("servicio", ""))
    cita["hora_formateada"] = formatear_hora(cita.get("hora"))
    cita["origen"] = cita.get("origen", "online")
    cita["tipo_visual"] = "online" if cita.get("origen") == "online" else "manual"
    return cita

@app.route("/dueno")
def panel_dueno():
    vista = request.args.get("vista", "inicio")
    rango = obtener_rango_vista(vista)

    fecha_inicio = rango["inicio"]
    fecha_fin = rango["fin"]
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")

    citas_periodo = obtener_citas_rango(fecha_inicio, fecha_fin)

    barberos_info = obtener_todos_barberos()
    barberos_dict = {str(b.get("id")): b for b in barberos_info}

    for cita in citas_periodo:
        enriquecer_cita(cita, barberos_dict)

    citas_no_canceladas = [
        c for c in citas_periodo
        if str(c.get("estado", "")).lower() != "cancelada"
    ]

    citas_canceladas = [
        c for c in citas_periodo
        if str(c.get("estado", "")).lower() == "cancelada"
    ]

    citas_por_barbero = {}
    canceladas_por_barbero = {}

    for cita in citas_no_canceladas:
        bid = str(cita.get("barbero_id", ""))
        citas_por_barbero.setdefault(bid, []).append(cita)

    for cita in citas_canceladas:
        bid = str(cita.get("barbero_id", ""))
        canceladas_por_barbero.setdefault(bid, []).append(cita)

    stats = {}
    for barbero in barberos_info:
        bid = str(barbero.get("id"))
        citas_barbero = citas_por_barbero.get(bid, [])
        canceladas_barbero = canceladas_por_barbero.get(bid, [])

        atendidas = [
            c for c in citas_barbero
            if str(c.get("estado", "")).lower() == "atendida"
        ]

        ganancia = sum(calcular_precio(c.get("servicio", "")) for c in atendidas)

        stats[bid] = {
            "nombre": barbero.get("nombre"),
            "total": len(citas_barbero),
            "ganancia": ganancia,
            "activo": barbero.get("activo", False),
            "disponible_hoy": barbero.get("disponible_hoy", False),
            "citas": citas_barbero,
            "canceladas": canceladas_barbero,
            "canceladas_total": len(canceladas_barbero)
        }

    resumen = {
        "total_citas": len(citas_no_canceladas),
        "total_canceladas": len(citas_canceladas),
        "total_atendidas": len([
            c for c in citas_no_canceladas
            if str(c.get("estado", "")).lower() == "atendida"
        ]),
        "total_ingresos": sum(
            calcular_precio(c.get("servicio", ""))
            for c in citas_no_canceladas
            if str(c.get("estado", "")).lower() == "atendida"
        )
    }

    return render_template(
        "panel_admin.html",
        stats=stats,
        barberos_info=barberos_info,
        citas_activas=citas_no_canceladas,
        citas_canceladas=citas_canceladas,
        servicios=SERVICIOS,
        hoy=hoy,
        vista_actual=rango["vista"],
        titulo_panel=rango["titulo"],
        subtitulo_panel=rango["subtitulo"],
        label_citas_panel=rango["label_citas"],
        empty_text_panel=rango["empty_text"],
        resumen=resumen,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin
    )
@app.route("/dueno/nueva-cita")
def nueva_cita_dueno():
    hoy = datetime.now(TZ).strftime("%Y-%m-%d")
    barberos_info = obtener_todos_barberos()

    return render_template(
        "nueva_cita_admin.html",
        barberos_info=barberos_info,
        servicios=SERVICIOS,
        hoy=hoy
    )

@app.route("/api/barbero/<barbero_id>/toggle_disponibilidad", methods=["POST"])
def toggle_disponibilidad(barbero_id):
    try:
        barbero = obtener_barbero_info(barbero_id)
        if not barbero:
            return jsonify({"error": "Barbero no encontrado"}), 404

        nuevo_estado = not bool(barbero.get("disponible_hoy", False))

        res = requests.patch(
            f"{SUPABASE_URL}/rest/v1/barberos?id=eq.{barbero_id}",
            headers=_headers(),
            json={"disponible_hoy": nuevo_estado},
            timeout=20
        )

        if res.status_code not in [200, 204]:
            print("ERROR toggle_disponibilidad:", res.status_code, res.text)
            return jsonify({"error": "No se pudo actualizar en Supabase"}), 500

        return jsonify({"success": True, "disponible_hoy": nuevo_estado})
    except Exception as e:
        print("ERROR toggle_disponibilidad:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/barbero/<barbero_id>/toggle_activo", methods=["POST"])
def toggle_activo(barbero_id):
    try:
        barbero = obtener_barbero_info(barbero_id)
        if not barbero:
            return jsonify({"error": "Barbero no encontrado"}), 404

        nuevo_estado = not bool(barbero.get("activo", False))

        res = requests.patch(
            f"{SUPABASE_URL}/rest/v1/barberos?id=eq.{barbero_id}",
            headers=_headers(),
            json={"activo": nuevo_estado},
            timeout=20
        )

        if res.status_code not in [200, 204]:
            print("ERROR toggle_activo:", res.status_code, res.text)
            return jsonify({"error": "No se pudo actualizar en Supabase"}), 500

        return jsonify({"success": True, "activo": nuevo_estado})
    except Exception as e:
        print("ERROR toggle_activo:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/cita_manual", methods=["POST"])
def crear_cita_manual():
    try:
        payload = request.get_json(silent=True) or {}

        barbero_id = str(payload.get("barbero_id", "")).strip()
        fecha = str(payload.get("fecha", "")).strip()
        hora = str(payload.get("hora", "")).strip()
        servicio = str(payload.get("servicio", "")).strip()
        cliente_nombre = str(payload.get("cliente_nombre", "Cliente presencial")).strip() or "Cliente presencial"
        observacion = str(payload.get("observacion", "")).strip()

        if not barbero_id or not fecha or not hora:
            return jsonify({"error": "Faltan datos requeridos"}), 400

        citas_existentes = obtener_citas_barbero_fecha(barbero_id, fecha)
        duracion_nueva = calcular_duracion(servicio) if servicio else 30

        for cita in citas_existentes:
            if str(cita.get("estado", "")).lower() == "cancelada":
                continue

            if hora_choque(hora, duracion_nueva, str(cita.get("hora")), calcular_duracion(cita.get("servicio", ""))):
                return jsonify({"error": "Ese horario ya está ocupado"}), 409

        hora_db = datetime.strptime(hora.upper(), "%I:%M%p").strftime("%H:%M:%S")

        data = {
    "cliente_nombre": cliente_nombre,
    "cliente_telefono": "",
    "servicio": servicio if servicio else "Bloqueo manual",
    "fecha": fecha,
    "hora": hora_db,
    "barbero_id": int(barbero_id),
    "estado": "atendida",
    "origen": "manual",
    "observacion": observacion,
    "recordatorio_30_enviado": True
}

        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/citas",
            headers=_headers(),
            json=data,
            timeout=20
        )

        if res.status_code not in [200, 201]:
            print("ERROR crear_cita_manual:", res.status_code, res.text)
            return jsonify({"error": "No se pudo guardar la cita en Supabase"}), 500

        return jsonify({"success": True})
    except Exception as e:
        print("ERROR crear_cita_manual:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/recordatorios", methods=["POST"])
def procesar_recordatorios():
    auth = request.headers.get("X-CRON-TOKEN")
    if auth != os.getenv("CRON_SECRET"):
        return jsonify({"error": "No autorizado"}), 401

    try:
        ahora = datetime.now(TZ)
        ventana_inicio = ahora + timedelta(minutes=25)
        ventana_fin = ahora + timedelta(minutes=35)

        hoy = ahora.strftime("%Y-%m-%d")
        url = (
            f"{SUPABASE_URL}/rest/v1/citas"
            f"?fecha=eq.{hoy}"
            f"&estado=eq.pendiente"
            f"&recordatorio_30_enviado=eq.false"
            f"&select=id,cliente_nombre,cliente_telefono,hora,origen,barbero_id,servicio"
        )
        res = session.get(url, headers=_headers(), timeout=20)

        if res.status_code != 200:
            return jsonify({"error": "No se pudo obtener citas"}), 500

        data = res.json()
        citas = data if isinstance(data, list) else []
        recordatorios_enviados = 0

        for cita in citas:
            if cita.get("origen") != "online":
                continue

            hora_str = cita.get("hora", "")
            try:
                hora_cita = datetime.strptime(hora_str, "%H:%M:%S").time()
                hora_cita_dt = datetime.combine(ahora.date(), hora_cita).replace(tzinfo=TZ)
            except Exception:
                continue

            if ventana_inicio <= hora_cita_dt <= ventana_fin:
                cliente_telefono = cita.get("cliente_telefono", "")
                if cliente_telefono:
                    nombre_cliente = cita.get("cliente_nombre", "")
                    nombre_barbero = BARBEROS.get(str(cita.get("barbero_id", "")), {}).get("nombre", "tu barbero")
                    servicio = cita.get("servicio", "tu servicio")
                    hora_formateada = formatear_hora(hora_str)

                    r = enviar_whatsapp_template_recordatorio(
                        numero=cliente_telefono,
                        nombre_cliente=nombre_cliente,
                        nombre_barbero=nombre_barbero,
                        hora=hora_formateada,
                        servicio=servicio
                    )

                    if r is not None and r.status_code in [200, 201]:
                        recordatorios_enviados += 1

                        try:
                            session.patch(
                                f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita.get('id')}",
                                headers=_headers(),
                                json={
                                    "recordatorio_30_enviado": True,
                                    "fecha_recordatorio_30": datetime.now(TZ).isoformat()
                                },
                                timeout=20
                            )
                        except Exception:
                            pass
                    else:
                        print("No se marcó recordatorio como enviado porque WhatsApp no confirmó éxito.")

        return jsonify({"success": True, "recordatorios_enviados": recordatorios_enviados})

    except Exception as e:
        print(f"Error procesar_recordatorios: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return challenge, 200
    return "Token inválido", 403


@app.route("/webhook", methods=["POST"])
def recibir_webhook():
    data = request.get_json(silent=True)
    print("WEBHOOK RECIBIDO:", data)
    return "EVENT_RECEIVED", 200


def tarea_recordatorios_automaticos():
    while True:
        try:
            ahora = datetime.now(TZ)

            if 8 <= ahora.hour < 19:
                hoy = ahora.strftime("%Y-%m-%d")
                ventana_inicio = ahora + timedelta(minutes=25)
                ventana_fin = ahora + timedelta(minutes=35)

                url = f"{SUPABASE_URL}/rest/v1/citas?fecha=eq.{hoy}&estado=eq.pendiente&recordatorio_30_enviado=eq.false"
                res = requests.get(url, headers=_headers(), timeout=20)

                if res.status_code == 200:
                    data = res.json()
                    citas = data if isinstance(data, list) else []

                    for cita in citas:
                        if cita.get("origen") != "online":
                            continue

                        hora_str = cita.get("hora", "")
                        try:
                            hora_cita = datetime.strptime(hora_str, "%H:%M:%S").time()
                            hora_cita_dt = datetime.combine(ahora.date(), hora_cita).replace(tzinfo=TZ)
                        except Exception:
                            continue

                        if ventana_inicio <= hora_cita_dt <= ventana_fin:
                            cliente_telefono = cita.get("cliente_telefono", "")
                            if cliente_telefono:
                                mensaje = (
                                    f"Hola, te recordamos que tienes una cita agendada en la barbería "
                                    f"hoy a las {formatear_hora(hora_str)}. Te esperamos."
                                )
                                enviar_whatsapp_texto(cliente_telefono, mensaje)

                                try:
                                    requests.patch(
                                        f"{SUPABASE_URL}/rest/v1/citas?id=eq.{cita.get('id')}",
                                        headers=_headers(),
                                        json={
                                            "recordatorio_30_enviado": True,
                                            "fecha_recordatorio_30": datetime.now(TZ).isoformat()
                                        },
                                        timeout=20
                                    )
                                except Exception:
                                    pass

        except Exception as e:
            print(f"Error en tarea_recordatorios_automaticos: {e}")

        time.sleep(120)


if __name__ == "__main__":
    inicializar_barberos()
    hilo_recordatorios = threading.Thread(target=tarea_recordatorios_automaticos, daemon=True)
    hilo_recordatorios.start()
    app.run(debug=True)


