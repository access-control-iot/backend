# app/routes/attendance.py
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from sqlalchemy import func
from io import StringIO
import csv

from app import db
from app.models import Attendance, AccessLog, User_iot, Schedule, UserSchedule

bp = Blueprint('attendance', __name__)

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
    us = UserSchedule.query.filter(
        UserSchedule.user_id == user_id,
        UserSchedule.start_date <= dt.date(),
        (UserSchedule.end_date == None) | (UserSchedule.end_date >= dt.date())
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
        'exit_time': record.exit_time.isoformat() if record.exit_time else None
    }

def register_attendance_from_access(access_log: AccessLog):
   
    if not access_log or not access_log.user_id:
        return {'ok': False, 'reason': 'no_user'}

    user_id = access_log.user_id
    now = access_log.timestamp or datetime.utcnow()
    open_att = Attendance.query.filter_by(user_id=user_id, exit_time=None).order_by(Attendance.entry_time.desc()).first()
    schedule = get_user_schedule(user_id, now)
    schedule_info = check_schedule_status(schedule, now) if schedule else {'state': 'sin_horario', 'minutes_diff': None}

    if open_att:
        open_att.exit_time = now
        db.session.commit()
        return {'ok': True, 'action': 'exit', 'attendance_id': open_att.id, 'schedule': schedule_info}
    else:
        att = Attendance(user_id=user_id, entry_time=now)
        db.session.add(att)
        db.session.commit()
        return {'ok': True, 'action': 'entry', 'attendance_id': att.id, 'schedule': schedule_info}

@bp.route('/attendance/log', methods=['POST'])
def log_attendance():
    data = request.get_json() or {}

    huella_id = data.get("huella_id")
    if not huella_id:
        return jsonify({"msg": "huella_id es requerido"}), 400


    user = User_iot.query.filter_by(huella_id=huella_id).first()
    if not user:
        return jsonify({"msg": "Usuario con esa huella no encontrado"}), 404

    now = datetime.utcnow()


    open_att = Attendance.query.filter_by(
        user_id=user.id,
        exit_time=None
    ).order_by(Attendance.entry_time.desc()).first()

 
    if not open_att:
        new_att = Attendance(
            user_id=user.id,
            entry_time=now
        )
        db.session.add(new_att)
        db.session.commit()

        return jsonify({
            "msg": "Entrada registrada",
            "user": user.username,
            "entry_time": new_att.entry_time.isoformat()
        }), 201


    open_att.exit_time = now
    db.session.commit()

    return jsonify({
        "msg": "Salida registrada",
        "user": user.username,
        "entry_time": open_att.entry_time.isoformat(),
        "exit_time": open_att.exit_time.isoformat()
    }), 200

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
        schedule = get_user_schedule(user_id, log.timestamp) if log.timestamp else None
        schedule_status = check_schedule_status(schedule, log.timestamp) if schedule else {'state': 'sin_horario', 'minutes_diff': None}
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
            'schedule_state': (check_schedule_status(get_user_schedule(user_id, a.entry_time), a.entry_time)['state'] if a.entry_time else None),
            'minutes_diff': (check_schedule_status(get_user_schedule(user_id, a.entry_time), a.entry_time)['minutes_diff'] if a.entry_time else None),
        })
        if a.exit_time:
            events.append({
                'type': 'attendance_exit',
                'id': a.id,
                'timestamp': a.exit_time.isoformat(),
                'sensor': None,
                'access_status': 'Exit',
                'schedule_state': (check_schedule_status(get_user_schedule(user_id, a.exit_time), a.exit_time)['state'] if a.exit_time else None),
                'minutes_diff': (check_schedule_status(get_user_schedule(user_id, a.exit_time), a.exit_time)['minutes_diff'] if a.exit_time else None),
            })
    events_sorted = sorted([e for e in events if e['timestamp'] is not None], key=lambda x: x['timestamp'], reverse=True)
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
