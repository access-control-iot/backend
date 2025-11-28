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
    local_date = dt.astimezone(LIMA_TZ).date() if dt.tzinfo else dt.date()
    us = UserSchedule.query.filter(
        UserSchedule.user_id == user_id,
        UserSchedule.start_date <= local_date,
        (UserSchedule.end_date == None) | (UserSchedule.end_date >= local_date)
    ).first()
    if not us:
        return None
    return Schedule.query.get(us.schedule_id)


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

    tolerancia = int(schedule.tolerancia_entrada or 0)
    minutes_diff = int((dt - entrada_dt).total_seconds() / 60)

    if dt <= entrada_dt + timedelta(minutes=tolerancia):
        return {'state': 'presente', 'minutes_diff': max(0, minutes_diff)}
    elif entrada_dt + timedelta(minutes=tolerancia) < dt < salida_dt:
        return {'state': 'tarde', 'minutes_diff': minutes_diff}
    elif dt >= salida_dt + timedelta(minutes=(schedule.tolerancia_salida or 0)):
        return {'state': 'fuera_de_horario', 'minutes_diff': minutes_diff}
    else:
        return {'state': 'presente', 'minutes_diff': minutes_diff}


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

    today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    

    open_attendance = Attendance.query.filter(
        Attendance.user_id == user_id,
        Attendance.entry_time >= today_start,
        Attendance.entry_time <= today_end,
        Attendance.exit_time.is_(None)
    ).first()
    
    if open_attendance:
        return 'exit'  
    else:
        return 'entry'  



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
        

        action = determine_attendance_action(user.id, lima_now)
        

        schedule = get_user_schedule(user.id, lima_now)
        schedule_status = check_schedule_status(schedule, lima_now) if schedule else {'state': 'sin_horario', 'minutes_diff': None}

        if action == 'entry':
   
            return register_attendance_entry(user, lima_now, schedule_status)
        else:
          
            return register_attendance_exit(user, lima_now)

    except Exception as e:
        print(f"Error en fingerprint-attendance: {e}")
        db.session.rollback()
        return jsonify({
            "success": False,
            "reason": "Error interno del sistema"
        }), 500


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



@bp.route('/entry', methods=['POST'])
@jwt_required()
def manual_entry():
 
    identity = get_jwt_identity()
    user = _get_user_from_identity(identity)
    
    if not user:
        return jsonify({'success': False, 'reason': 'Usuario no autenticado'}), 401

    lima_now = datetime.now(LIMA_TZ)
    schedule = get_user_schedule(user.id, lima_now)
    schedule_status = check_schedule_status(schedule, lima_now) if schedule else {'state': 'sin_horario', 'minutes_diff': None}
    
    return register_attendance_entry(user, lima_now, schedule_status)


@bp.route('/exit', methods=['POST'])
@jwt_required()
def manual_exit():

    identity = get_jwt_identity()
    user = _get_user_from_identity(identity)
    
    if not user:
        return jsonify({'success': False, 'reason': 'Usuario no autenticado'}), 401

    lima_now = datetime.now(LIMA_TZ)
    return register_attendance_exit(user, lima_now)



def register_attendance_from_access(access_log: AccessLog):
 
    if not access_log or not access_log.user_id:
        return {'ok': False, 'reason': 'Datos insuficientes'}


    ts = access_log.timestamp
    if ts.tzinfo is None:
        ts = pytz.utc.localize(ts)
    lima_dt = ts.astimezone(LIMA_TZ)

    user_id = access_log.user_id
    

    action = determine_attendance_action(user_id, lima_dt)
    
    schedule = get_user_schedule(user_id, lima_dt)
    schedule_info = check_schedule_status(schedule, lima_dt) if schedule else {'state': 'sin_horario', 'minutes_diff': None}

    if action == 'exit':
  
        today_start = lima_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        open_att = Attendance.query.filter(
            Attendance.user_id == user_id,
            Attendance.entry_time >= today_start,
            Attendance.entry_time <= today_end,
            Attendance.exit_time.is_(None)
        ).first()
        
        if open_att:
            open_att.exit_time = access_log.timestamp
            db.session.commit()
            return {'ok': True, 'action': 'exit', 'attendance_id': open_att.id, 'schedule': schedule_info}
        else:
            return {'ok': False, 'reason': 'No se encontró entrada para cerrar'}
    else:
   
        estado = schedule_info.get('state') or 'sin_horario'
        att = Attendance(user_id=user_id, entry_time=access_log.timestamp, estado_entrada=estado)
        db.session.add(att)
        db.session.commit()
        return {'ok': True, 'action': 'entry', 'attendance_id': att.id, 'schedule': schedule_info, 'estado': estado}



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

    users = User_iot.query.filter_by(activo=True).order_by(User_iot.nombre).all()
    
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