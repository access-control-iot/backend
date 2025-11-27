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


def register_attendance_from_access(access_log: AccessLog):
    if not access_log or not access_log.user_id:
        return {'ok': False, 'reason': 'no_access_log_or_user'}

    ts = access_log.timestamp
    if ts is None:
        ts = datetime.utcnow()


    if ts.tzinfo is None:
        ts = pytz.utc.localize(ts)
    
    lima_dt = ts.astimezone(LIMA_TZ)
    user_id = access_log.user_id

    start_of_day = lima_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    
    start_of_day_utc = start_of_day.astimezone(pytz.utc)
    end_of_day_utc = end_of_day.astimezone(pytz.utc)
    
    registros_hoy = Attendance.query.filter(
        Attendance.user_id == user_id,
        Attendance.entry_time >= start_of_day_utc,
        Attendance.entry_time < end_of_day_utc
    ).order_by(Attendance.entry_time.desc()).all()

    schedule = get_user_schedule(user_id, lima_dt)
    schedule_info = check_schedule_status(schedule, lima_dt) if schedule else {'state': 'sin_horario', 'minutes_diff': None}


    if not registros_hoy:
        estado = schedule_info.get('state') or 'sin_horario'
        att = Attendance(
            user_id=user_id, 
            entry_time=ts, 
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
            'message': 'Entrada registrada - Inicio de jornada'
        }
    

    ultimo_registro = registros_hoy[0]
    

    if ultimo_registro.exit_time is None:
        
        tiempo_minimo = timedelta(minutes=1)  
        
        if ts - ultimo_registro.entry_time < tiempo_minimo:
            return {
                'ok': False,
                'reason': 'tiempo_minimo_no_alcanzado',
                'message': 'Espere al menos 1 minuto para marcar salida'
            }
        
        ultimo_registro.exit_time = ts
        db.session.commit()
        
 
        duracion = ultimo_registro.exit_time - ultimo_registro.entry_time
        horas = int(duracion.total_seconds() // 3600)
        minutos = int((duracion.total_seconds() % 3600) // 60)
        
        return {
            'ok': True, 
            'action': 'exit', 
            'attendance_id': ultimo_registro.id, 
            'schedule': schedule_info,
            'duracion': f"{horas}h {minutos}m",
            'message': f'Salida registrada - Jornada: {horas}h {minutos}m'
        }
    
    else:
   
        tiempo_entre_registros = ts - ultimo_registro.exit_time
        tiempo_minimo_reingreso = timedelta(minutes=5)  
        
        if tiempo_entre_registros < tiempo_minimo_reingreso:
            return {
                'ok': False,
                'reason': 'reingreso_demasiado_rapido',
                'message': f'Espere {int((tiempo_minimo_reingreso - tiempo_entre_registros).total_seconds() / 60)} minutos para reingresar'
            }
        
        estado = schedule_info.get('state') or 'sin_horario'
       
        if estado == 'presente' and len(registros_hoy) > 0:
            estado = 'reingreso'
        
        nueva_entrada = Attendance(
            user_id=user_id, 
            entry_time=ts, 
            estado_entrada=estado
        )
        db.session.add(nueva_entrada)
        db.session.commit()
        
        return {
            'ok': True, 
            'action': 'entry', 
            'attendance_id': nueva_entrada.id, 
            'schedule': schedule_info, 
            'estado': estado,
            'message': 'Entrada registrada - Reingreso a jornada',
            'tipo': 'reingreso'
        }


@bp.route('/attendance/history', methods=['GET'])
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


@bp.route('/attendance/exit', methods=['POST'])
@jwt_required()
def log_exit():
    identity = get_jwt_identity()
    user = _get_user_from_identity(identity)
    if not user:
        return jsonify({'msg': 'Usuario no autenticado'}), 401

    open_att = Attendance.query.filter_by(user_id=user.id, exit_time=None).order_by(Attendance.entry_time.desc()).first()
    if not open_att:
        return jsonify({'message': 'No entry record found'}), 404
    open_att.exit_time = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Exit time logged successfully', 'attendance': _serialize_attendance(open_att)}), 200


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
            import pytz
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


@bp.route('/summary', methods=['GET'])
@jwt_required()
def attendance_summary():
    identity = get_jwt_identity()
    caller = _get_user_from_identity(identity)
    if not caller:
        return jsonify({'msg': 'Usuario no autenticado'}), 401
    if not caller.is_admin:
        return jsonify({'msg': 'Solo admin'}, 403)

    mode = request.args.get('mode', 'daily')
    area = request.args.get('area')
    user_id = request.args.get('user_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    q = AccessLog.query.join(User_iot, AccessLog.user_id == User_iot.id)

    if area:
        q = q.filter(User_iot.area_trabajo == area)
    if user_id:
        q = q.filter(AccessLog.user_id == int(user_id))
    if start_date:
        q = q.filter(AccessLog.timestamp >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(AccessLog.timestamp <= datetime.fromisoformat(end_date) + timedelta(days=1))

    if mode == 'daily':
        group_by_expr = func.date(AccessLog.timestamp)
    elif mode == 'weekly':
        group_by_expr = func.strftime('%Y-%W', AccessLog.timestamp)
    elif mode == 'monthly':
        group_by_expr = func.strftime('%Y-%m', AccessLog.timestamp)
    else:
        return jsonify({'msg': 'mode inválido'}), 400

    resumen = q.with_entities(
        AccessLog.user_id,
        group_by_expr.label('period'),
        func.count(AccessLog.id).label('total')
    ).group_by(AccessLog.user_id, 'period').all()

    result = []
    for user_id, period, total in resumen:
        result.append({'user_id': user_id, 'period': str(period), 'total_registros': total})
    return jsonify(result), 200


@bp.route('/summary/export/csv', methods=['GET'])
@jwt_required()
def summary_export_csv():
    identity = get_jwt_identity()
    caller = _get_user_from_identity(identity)
    if not caller:
        return jsonify({'msg': 'Usuario no autenticado'}), 401
    if not caller.is_admin:
        return jsonify({'msg': 'Solo admin'}, 403)

    mode = request.args.get('mode', 'daily')
    area = request.args.get('area')
    user_id = request.args.get('user_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    q = AccessLog.query.join(User_iot, AccessLog.user_id == User_iot.id)
    if area:
        q = q.filter(User_iot.area_trabajo == area)
    if user_id:
        q = q.filter(AccessLog.user_id == int(user_id))
    if start_date:
        q = q.filter(AccessLog.timestamp >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(AccessLog.timestamp <= datetime.fromisoformat(end_date) + timedelta(days=1))

    if mode == 'daily':
        group_by_expr = func.date(AccessLog.timestamp)
    elif mode == 'weekly':
        group_by_expr = func.strftime('%Y-%W', AccessLog.timestamp)
    elif mode == 'monthly':
        group_by_expr = func.strftime('%Y-%m', AccessLog.timestamp)
    else:
        return jsonify({'msg': 'mode inválido'}), 400

    resumen = q.with_entities(
        AccessLog.user_id,
        group_by_expr.label('period'),
        func.count(AccessLog.id).label('total')
    ).group_by(AccessLog.user_id, 'period').all()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['user_id', 'period', 'total_registros'])
    for user_id, period, total in resumen:
        cw.writerow([user_id, period, total])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=attendance_summary.csv"})

@bp.route('/admin/report', methods=['GET'])
@jwt_required()
def admin_attendance_report():

    identity = get_jwt_identity()
    caller = _get_user_from_identity(identity)
    if not caller:
        return jsonify({'msg': 'Usuario no autenticado'}), 401
    if not caller.is_admin:
        return jsonify({'msg': 'Solo administradores pueden ver este reporte'}), 403


    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    user_id = request.args.get('user_id')
    area = request.args.get('area')

 
    query = Attendance.query.join(User_iot, Attendance.user_id == User_iot.id)

   
    if start_date:
        start_dt = datetime.fromisoformat(start_date)
        query = query.filter(Attendance.entry_time >= start_dt)
    
    if end_date:
        end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        query = query.filter(Attendance.entry_time <= end_dt)
    
    if user_id:
        query = query.filter(Attendance.user_id == int(user_id))
    
    if area:
        query = query.filter(User_iot.area_trabajo == area)

 
    attendances = query.order_by(Attendance.entry_time.desc()).all()

    result = []
    for att in attendances:
        user = User_iot.query.get(att.user_id)
        result.append({
            'attendance_id': att.id,
            'user_id': att.user_id,
            'username': user.username if user else 'N/A',
            'nombre': user.nombre if user else 'N/A',
            'apellido': user.apellido if user else 'N/A',
            'area_trabajo': user.area_trabajo if user else 'N/A',
            'entry_time': att.entry_time.isoformat() if att.entry_time else None,
            'exit_time': att.exit_time.isoformat() if att.exit_time else None,
            'estado_entrada': att.estado_entrada,
            'duracion_jornada': _calculate_work_duration(att.entry_time, att.exit_time),
            'created_at': att.created_at.isoformat() if att.created_at else None
        })

    return jsonify({
        'total_registros': len(result),
        'filtros': {
            'start_date': start_date,
            'end_date': end_date,
            'user_id': user_id,
            'area': area
        },
        'asistencias': result
    }), 200


def _calculate_work_duration(entry_time, exit_time):

    if not entry_time or not exit_time:
        return None
    
    duration = exit_time - entry_time
    hours = int(duration.total_seconds() // 3600)
    minutes = int((duration.total_seconds() % 3600) // 60)
    
    return f"{hours}h {minutes}m"