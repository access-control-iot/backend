# app/routes/attendance.py
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
import pytz
from sqlalchemy import func, or_
from io import StringIO
import csv

from app import db
from app.models import Attendance, AccessLog, User_iot, Schedule, UserSchedule

bp = Blueprint('attendance', __name__)

LIMA_TZ = pytz.timezone("America/Lima")


def _get_user_from_identity(identity):
    if identity is None:
        return None
    if isinstance(identity, dict):
        user_id = identity.get('id')
    else:
        user_id = identity
    if not user_id:
        return None
    return User_iot.query.get(user_id)


def get_user_schedule(user_id, dt):
    """
    Obtiene el horario activo de un usuario para una fecha específica.
    Prioriza el horario más reciente si hay múltiples activos.
    """
    from app.models import UserSchedule, Schedule
    
    # Convertir a fecha local si tiene timezone
    if dt.tzinfo:
        local_date = dt.date()
    else:
        # Si no tiene timezone, asumir UTC y convertir a Lima
        try:
            utc_dt = pytz.utc.localize(dt)
            lima_dt = utc_dt.astimezone(LIMA_TZ)
            local_date = lima_dt.date()
        except:
            local_date = dt.date()
    
    # Obtener TODOS los horarios activos para esta fecha
    active_schedules = UserSchedule.query.filter(
        UserSchedule.user_id == user_id,
        UserSchedule.start_date <= local_date,
        (UserSchedule.end_date == None) | (UserSchedule.end_date >= local_date)
    ).order_by(UserSchedule.start_date.desc()).all()
    
    if not active_schedules:
        return None
    
    # Si hay múltiples horarios activos, usar el más reciente (por start_date)
    # Esto maneja el caso donde se cambió de horario durante el día
    latest_schedule = active_schedules[0]
    
    # Verificar si hay un horario que empiece HOY específicamente
    for schedule in active_schedules:
        if schedule.start_date == local_date:
            # Este horario comenzó hoy, tiene prioridad
            latest_schedule = schedule
            break
    
    return Schedule.query.get(latest_schedule.schedule_id)

def check_schedule_status(schedule, dt):
    if schedule is None:
        return {'state': 'sin_horario', 'minutes_diff': None}

    dias = [d.strip() for d in schedule.dias.split(',')]
    dia_text = ['Lun','Mar','Mie','Jue','Vie','Sab','Dom'][dt.weekday()]
    if dia_text not in dias:
        return {'state': 'fuera_de_horario', 'minutes_diff': None}

    entrada_dt = datetime.combine(dt.date(), schedule.hora_entrada)
    salida_dt = datetime.combine(dt.date(), schedule.hora_salida)

    entrada_dt = LIMA_TZ.localize(entrada_dt)
    salida_dt = LIMA_TZ.localize(salida_dt)

    tolerancia_entrada = int(schedule.tolerancia_entrada or 0)
    tolerancia_salida = int(schedule.tolerancia_salida or 0)
    
    minutes_diff_entrada = int((dt - entrada_dt).total_seconds() / 60)
    minutes_diff_salida = int((dt - salida_dt).total_seconds() / 60)

    # Lógica para entrada
    if dt <= entrada_dt + timedelta(minutes=tolerancia_entrada):
        return {'state': 'presente', 'minutes_diff': max(0, minutes_diff_entrada)}
    elif entrada_dt + timedelta(minutes=tolerancia_entrada) < dt < salida_dt:
        return {'state': 'tarde', 'minutes_diff': minutes_diff_entrada}
    # Lógica para salida (dentro de la tolerancia de salida)
    elif dt >= salida_dt - timedelta(minutes=1) and dt <= salida_dt + timedelta(minutes=tolerancia_salida):
        return {'state': 'presente', 'minutes_diff': None}
    else:
        return {'state': 'fuera_de_horario', 'minutes_diff': None}


def _serialize_attendance(record):
    return {
        'id': record.id,
        'user_id': record.user_id,
        'entry_time': record.entry_time.isoformat() if record.entry_time else None,
        'exit_time': record.exit_time.isoformat() if record.exit_time else None,
        'estado_entrada': record.estado_entrada
    }


def get_attendance_message(schedule_status, action):
    if action == 'entry':
        if schedule_status['state'] == 'presente':
            return 'Entrada registrada - A tiempo'
        elif schedule_status['state'] == 'tarde':
            return f'Entrada registrada - Llegó {schedule_status["minutes_diff"]} minutos tarde'
        elif schedule_status['state'] == 'sin_horario':
            return 'Entrada registrada - Sin horario asignado'
        else:
            return 'Entrada registrada - Fuera de horario'
    elif action == 'exit':
        return 'Salida registrada correctamente'
    return 'Asistencia registrada'


def determine_attendance_action(user_id, current_time):
    """Determina si es entrada o salida considerando el horario del usuario"""
    
    # Primero, verificar si hay una entrada abierta para hoy
    today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    open_attendance = Attendance.query.filter(
        Attendance.user_id == user_id,
        Attendance.entry_time >= today_start,
        Attendance.entry_time <= today_end,
        Attendance.exit_time.is_(None)
    ).first()
    
    # Si NO hay entrada abierta, es una ENTRADA
    if not open_attendance:
        return 'entry'
    
    # Si hay entrada abierta, verificar si es hora de salida
    schedule = get_user_schedule(user_id, current_time)
    
    if schedule:
        # Calcular la hora de salida exacta (sin tolerancia para salidas tempranas)
        salida_dt = datetime.combine(current_time.date(), schedule.hora_salida)
        salida_dt = LIMA_TZ.localize(salida_dt)
        
        # ¡IMPORTANTE! NO permitir salida antes de la hora exacta de salida
        # Solo permitir desde 1 minuto antes como máximo
        salida_permitida_desde = salida_dt - timedelta(minutes=1)
        
        if current_time >= salida_permitida_desde:
            return 'exit'
        else:
            # Aún no es hora de salida, mostrar error
            return 'entry_pending_exit'  # Estado especial
    
    # Sin horario, permitir salida si hay entrada abierta
    return 'exit'

def register_attendance_entry(user, timestamp, schedule_status):
   
    today_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    

    existing_entry = Attendance.query.filter(
        Attendance.user_id == user.id,
        Attendance.entry_time >= today_start,
        Attendance.entry_time <= today_end
    ).first()
    
    if existing_entry:
        return jsonify({
            "success": False,
            "reason": "Ya tiene una entrada registrada hoy"
        }), 400
    

    attendance = Attendance(
        user_id=user.id,
        entry_time=timestamp,
        estado_entrada=schedule_status['state']
    )
    db.session.add(attendance)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "action": "entry",
        "attendance_id": attendance.id,
        "user_id": user.id,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "entry_time": timestamp.isoformat(),
        "estado_entrada": schedule_status['state'],
        "minutes_diff": schedule_status['minutes_diff'],
        "message": get_attendance_message(schedule_status, 'entry')
    }), 201


def register_attendance_exit(user, timestamp):
   
    today_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    open_attendance = Attendance.query.filter(
        Attendance.user_id == user.id,
        Attendance.entry_time >= today_start,
        Attendance.entry_time <= today_end,
        Attendance.exit_time.is_(None)
    ).first()
    
    if not open_attendance:
        return jsonify({
            "success": False,
            "reason": "No se encontró entrada registrada para hoy"
        }), 404
    
    open_attendance.exit_time = timestamp
    db.session.commit()
    
    duration = open_attendance.exit_time - open_attendance.entry_time
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    
    return jsonify({
        "success": True,
        "action": "exit",
        "attendance_id": open_attendance.id,
        "user_id": user.id,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "exit_time": timestamp.isoformat(),
        "duracion_jornada": f"{hours}h {minutes}m",
        "message": get_attendance_message({}, 'exit')
    }), 200


def register_attendance_from_access(access_log: AccessLog):
   
    if not access_log or not access_log.user_id:
        return {'ok': False, 'reason': 'Datos insuficientes'}

    ts = access_log.timestamp
    if ts.tzinfo is None:
        ts = pytz.utc.localize(ts)
    lima_dt = ts.astimezone(LIMA_TZ)

    user_id = access_log.user_id
    
    
    hoy = lima_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    mañana = hoy + timedelta(days=1)
    
    # Buscar asistencia abierta HOY
    open_att = Attendance.query.filter(
        Attendance.user_id == user_id,
        Attendance.entry_time >= hoy,
        Attendance.entry_time < mañana,
        Attendance.exit_time.is_(None)
    ).first()
    
  
    schedule = get_user_schedule(user_id, lima_dt)
    schedule_info = check_schedule_status(schedule, lima_dt) if schedule else {'state': 'sin_horario', 'minutes_diff': None}
    
    if open_att:
        
        open_att.exit_time = access_log.timestamp
        db.session.commit()
        
       
        duracion = open_att.exit_time - open_att.entry_time
        horas = int(duracion.total_seconds() // 3600)
        minutos = int((duracion.total_seconds() % 3600) // 60)
        
        return {
            'ok': True, 
            'action': 'exit', 
            'attendance_id': open_att.id, 
            'schedule': schedule_info,
            'estado': 'salida_registrada',
            'duracion_jornada': f"{horas}h {minutos}m",
            'entry_time': open_att.entry_time,
            'exit_time': access_log.timestamp
        }
    else:
        
        estado = schedule_info.get('state') or 'sin_horario'
        att = Attendance(
            user_id=user_id, 
            entry_time=access_log.timestamp, 
            estado_entrada=estado
        )
        db.session.add(att)
        db.session.commit()
        
        return {
            'ok': True, 
            'action': 'entry', 
            'attendance_id': att.id, 
            'schedule': schedule_info, 
            'estado': estado,
            'minutes_diff': schedule_info.get('minutes_diff')
        }


@bp.route('/fingerprint-attendance', methods=['POST'])
def fingerprint_attendance():
    data = request.get_json() or {}
    huella_id = data.get('huella_id')

    if huella_id is None:
        return jsonify(success=False, reason='Falta huella_id'), 400

    user = User_iot.query.filter_by(huella_id=huella_id).first()
    
    if not user:
        return jsonify({
            "success": False,
            "reason": "Huella no registrada"
        }), 403

    try:
        lima_now = datetime.now(LIMA_TZ)
        
        # Determinar la acción (entrada o salida)
        action = determine_attendance_action(user.id, lima_now)
        
        # Obtener horario para verificar si puede registrar
        schedule = get_user_schedule(user.id, lima_now)
        
        if action == 'exit':
            # Verificar si ya existe una entrada para hoy
            today_start = lima_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            open_attendance = Attendance.query.filter(
                Attendance.user_id == user.id,
                Attendance.entry_time >= today_start,
                Attendance.entry_time <= today_end,
                Attendance.exit_time.is_(None)
            ).first()
            
            if not open_attendance:
                return jsonify({
                    "success": False,
                    "reason": "No tiene una entrada registrada para hoy"
                }), 400
            
            # Verificar si es hora de salida (no permitir antes)
            if schedule:
                salida_dt = datetime.combine(lima_now.date(), schedule.hora_salida)
                salida_dt = LIMA_TZ.localize(salida_dt)
                
                # NO permitir salida antes de la hora de salida (máximo 1 minuto antes)
                salida_permitida_desde = salida_dt - timedelta(minutes=1)
                
                if lima_now < salida_permitida_desde:
                    # Calcular minutos restantes
                    minutos_restantes = int((salida_dt - lima_now).total_seconds() / 60)
                    return jsonify({
                        "success": False,
                        "reason": f"No es hora de salida. Puede registrar salida a partir de las {salida_dt.strftime('%H:%M')} (faltan {minutos_restantes} minutos)"
                    }), 400
            
            # Registrar salida
            return register_attendance_exit(user, lima_now)
        
        elif action == 'entry_pending_exit':
            # Tiene entrada abierta pero aún no es hora de salida
            if schedule:
                salida_dt = datetime.combine(lima_now.date(), schedule.hora_salida)
                salida_dt = LIMA_TZ.localize(salida_dt)
                minutos_restantes = int((salida_dt - lima_now).total_seconds() / 60)
                
                return jsonify({
                    "success": False,
                    "reason": f"Aún no es hora de salida. Puede registrar salida a partir de las {salida_dt.strftime('%H:%M')} (faltan {minutos_restantes} minutos)",
                    "has_open_entry": True,
                    "scheduled_exit_time": salida_dt.strftime('%H:%M'),
                    "minutes_remaining": minutos_restantes
                }), 400
            else:
                return jsonify({
                    "success": False,
                    "reason": "Ya tiene una entrada registrada hoy. No puede registrar otra entrada.",
                    "has_open_entry": True
                }), 400
        else:
            # Es una entrada nueva
            if not schedule:
                return jsonify({
                    "success": False,
                    "reason": "Usuario no tiene horario asignado"
                }), 403
            
            schedule_status = check_schedule_status(schedule, lima_now)
            
            # Verificar si ya tiene entrada hoy
            today_start = lima_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            existing_entry = Attendance.query.filter(
                Attendance.user_id == user.id,
                Attendance.entry_time >= today_start,
                Attendance.entry_time <= today_end
            ).first()
            
            if existing_entry:
                # Si ya tiene entrada, verificar si puede salir
                if schedule:
                    salida_dt = datetime.combine(lima_now.date(), schedule.hora_salida)
                    salida_dt = LIMA_TZ.localize(salida_dt)
                    salida_permitida_desde = salida_dt - timedelta(minutes=1)
                    
                    if lima_now >= salida_permitida_desde:
                        # Es hora de salida, registrar salida
                        return register_attendance_exit(user, lima_now)
                    else:
                        minutos_restantes = int((salida_dt - lima_now).total_seconds() / 60)
                        return jsonify({
                            "success": False,
                            "reason": f"Ya tiene entrada registrada hoy. Puede marcar salida a partir de las {salida_dt.strftime('%H:%M')} (faltan {minutos_restantes} minutos)",
                            "has_open_entry": True
                        }), 400
            
            # Registrar entrada
            return register_attendance_entry(user, lima_now, schedule_status)

    except Exception as e:
        print(f"Error en fingerprint-attendance: {e}")
        db.session.rollback()
        return jsonify({
            "success": False,
            "reason": "Error interno del sistema"
        }), 500

def format_time_for_message(dt):
    """Formatea datetime para mensajes de usuario"""
    return dt.strftime("%H:%M")
@bp.route('/history', methods=['GET'])
@jwt_required()
def get_attendance_history():
    identity = get_jwt_identity()
    user = _get_user_from_identity(identity)
    if not user:
        return jsonify({'msg': 'Usuario no autenticado'}), 401

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    q = Attendance.query.filter_by(user_id=user.id).order_by(Attendance.entry_time.desc())
    pag = q.paginate(page=page, per_page=per_page, error_out=False)

    data = [_serialize_attendance(r) for r in pag.items]
    return jsonify({'items': data, 'page': page, 'total': pag.total}), 200


@bp.route('/user/<int:user_id>', methods=['GET'])
@jwt_required()
def user_attendance(user_id):
    identity = get_jwt_identity()
    caller = _get_user_from_identity(identity)
    if not caller:
        return jsonify({'msg': 'Usuario no autenticado'}), 401
    if not (caller.is_admin or caller.id == user_id):
        return jsonify({'msg': 'No autorizado'}), 403

    access_logs = AccessLog.query.filter_by(user_id=user_id).order_by(AccessLog.timestamp.desc()).all()
    attends = Attendance.query.filter_by(user_id=user_id).order_by(Attendance.entry_time.desc()).all()

    events = []
    for log in access_logs:
        ts = log.timestamp
        if ts.tzinfo is None:
            ts = pytz.utc.localize(ts)
        lima_ts = ts.astimezone(LIMA_TZ)
        schedule = get_user_schedule(user_id, lima_ts) if log.timestamp else None
        schedule_status = check_schedule_status(schedule, lima_ts) if schedule else {'state': 'sin_horario', 'minutes_diff': None}
        events.append({
            'type': 'access',
            'id': log.id,
            'timestamp': log.timestamp.isoformat(),
            'sensor': log.sensor_type,
            'access_status': log.status,
            'schedule_state': schedule_status['state'],
            'minutes_diff': schedule_status['minutes_diff'],
            'rfid': log.rfid,
            'reason': log.reason
        })
    for a in attends:
        events.append({
            'type': 'attendance_entry',
            'id': a.id,
            'timestamp': a.entry_time.isoformat() if a.entry_time else None,
            'sensor': None,
            'access_status': 'Entry',
            'schedule_state': (check_schedule_status(get_user_schedule(user_id, a.entry_time.astimezone(LIMA_TZ) if a.entry_time.tzinfo else pytz.utc.localize(a.entry_time).astimezone(LIMA_TZ)), a.entry_time.astimezone(LIMA_TZ))['state'] if a.entry_time else None) if a.entry_time else None,
            'minutes_diff': None,
            'estado_entrada': a.estado_entrada
        })
        if a.exit_time:
            events.append({
                'type': 'attendance_exit',
                'id': a.id,
                'timestamp': a.exit_time.isoformat(),
                'sensor': None,
                'access_status': 'Exit',
                'schedule_state': None,
                'minutes_diff': None,
            })
    events_sorted = sorted([e for e in events if e.get('timestamp')], key=lambda x: x['timestamp'], reverse=True)
    return jsonify(events_sorted), 200


def _calculate_work_duration(entry_time, exit_time):
    if not entry_time or not exit_time:
        return None
    
    duration = exit_time - entry_time
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    
    return f"{hours}h {minutes}m"


@bp.route('/admin/report', methods=['GET'])
@jwt_required()
def admin_attendance_report():
    identity = get_jwt_identity()
    admin_user = _get_user_from_identity(identity)
    
    if not admin_user or not admin_user.is_admin:
        return jsonify({'msg': 'No autorizado - Se requiere rol de administrador'}), 403

    user_id = request.args.get('user_id', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    area = request.args.get('area', '').strip()

    query = db.session.query(
        Attendance,
        User_iot
    ).join(
        User_iot, Attendance.user_id == User_iot.id
    )

    if user_id:
        query = query.filter(Attendance.user_id == user_id)
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            start_dt = LIMA_TZ.localize(datetime.combine(start_date, datetime.min.time()))
            query = query.filter(Attendance.entry_time >= start_dt)
        except ValueError:
            return jsonify({'msg': 'Formato de fecha inicial inválido'}), 400
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            end_dt = LIMA_TZ.localize(datetime.combine(end_date, datetime.max.time()))
            query = query.filter(Attendance.entry_time <= end_dt)
        except ValueError:
            return jsonify({'msg': 'Formato de fecha final inválido'}), 400
    
    if area:
        query = query.filter(User_iot.area_trabajo.ilike(f'%{area}%'))

    query = query.order_by(Attendance.entry_time.desc())

    results = query.all()

    asistencias = []
    for attendance, user in results:
        duracion_jornada = None
        if attendance.entry_time and attendance.exit_time:
            duration = attendance.exit_time - attendance.entry_time
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            duracion_jornada = f"{hours}h {minutes}m"

        asistencia_data = {
            'id': attendance.id,
            'user_id': user.id,
            'nombre': user.nombre,
            'apellido': user.apellido,
            'username': user.username,
            'area_trabajo': user.area_trabajo,
            'entry_time': attendance.entry_time.isoformat() if attendance.entry_time else None,
            'exit_time': attendance.exit_time.isoformat() if attendance.exit_time else None,
            'estado_entrada': attendance.estado_entrada,
            'duracion_jornada': duracion_jornada
        }
        asistencias.append(asistencia_data)

    return jsonify({
        'success': True,
        'asistencias': asistencias,
        'total': len(asistencias)
    }), 200


@bp.route('/admin/users', methods=['GET'])
@jwt_required()
def get_users_for_admin():
    identity = get_jwt_identity()
    admin_user = _get_user_from_identity(identity)
    
    if not admin_user or not admin_user.is_admin:
        return jsonify({'msg': 'No autorizado'}), 403

    users = User_iot.query.order_by(User_iot.nombre).all()
    
    users_list = [{
        'id': user.id,
        'nombre': user.nombre,
        'apellido': user.apellido,
        'username': user.username,
        'area_trabajo': user.area_trabajo
    } for user in users]

    return jsonify({
        'success': True,
        'users': users_list
    }), 200


@bp.route('/my-attendance', methods=['GET'])
@jwt_required()
def my_attendance_report():
    identity = get_jwt_identity()
    user = _get_user_from_identity(identity)
    
    if not user:
        return jsonify({'success': False, 'reason': 'Usuario no autenticado'}), 401

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = Attendance.query.filter_by(user_id=user.id)

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            start_dt = LIMA_TZ.localize(datetime.combine(start_date, datetime.min.time()))
            query = query.filter(Attendance.entry_time >= start_dt)
        except ValueError:
            return jsonify({'success': False, 'reason': 'Formato de fecha inicial inválido'}), 400
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            end_dt = LIMA_TZ.localize(datetime.combine(end_date, datetime.max.time()))
            query = query.filter(Attendance.entry_time <= end_dt)
        except ValueError:
            return jsonify({'success': False, 'reason': 'Formato de fecha final inválido'}), 400

    results = query.order_by(Attendance.entry_time.desc()).all()

    asistencias = []
    for attendance in results:
        duracion_jornada = _calculate_work_duration(attendance.entry_time, attendance.exit_time)
        
        asistencia_data = {
            'id': attendance.id,
            'entry_time': attendance.entry_time.isoformat() if attendance.entry_time else None,
            'exit_time': attendance.exit_time.isoformat() if attendance.exit_time else None,
            'estado_entrada': attendance.estado_entrada,
            'duracion_jornada': duracion_jornada
        }
        asistencias.append(asistencia_data)

    return jsonify({
        'success': True,
        'asistencias': asistencias,
        'total': len(asistencias),
        'user_info': {
            'id': user.id,
            'nombre': user.nombre,
            'apellido': user.apellido,
            'username': user.username,
            'area_trabajo': user.area_trabajo
        }
    }), 200
