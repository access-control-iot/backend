# app/routes/access.py
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from io import StringIO
import csv

import pytz

from app import db
from app.models import User_iot, AccessLog, UserSchedule, Schedule, FailedAttempt
bp = Blueprint('access', __name__)

UTC = pytz.utc
LIMA_TZ = pytz.timezone("America/Lima")


def _get_current_user_from_jwt():
    identity = get_jwt_identity()
    if isinstance(identity, dict):
        user_id = identity.get('id')
    else:
        user_id = identity
    return User_iot.query.get(user_id) if user_id else None


def _record_failed_attempt(identifier, identifier_type, device_id=None, user_id=None, reason=None):
   
    fa = FailedAttempt.query.filter_by(identifier=identifier, identifier_type=identifier_type).first()
    if not fa:
        fa = FailedAttempt(
            user_id=user_id,
            identifier=identifier,
            identifier_type=identifier_type,
            device_id=device_id,
            count=1,
            reason=reason
        )
        db.session.add(fa)
    else:
        fa.count = fa.count + 1
        fa.timestamp = datetime.utcnow()
        fa.reason = reason or fa.reason
    db.session.commit()
    return fa.count


@bp.route('/assign-rfid', methods=['POST'])
@jwt_required()
def assign_rfid():
    current_user = _get_current_user_from_jwt()
    if not current_user or not current_user.is_admin:
        return jsonify(msg='Solo administradores'), 403

    data = request.get_json() or {}
    user = User_iot.query.get_or_404(data.get('user_id'))
    rfid = data.get('rfid')
    if not rfid:
        return jsonify(msg='Falta campo rfid'), 400


    if User_iot.query.filter(User_iot.rfid == rfid, User_iot.id != user.id).first():
        return jsonify(msg='RFID ya asignado a otro usuario'), 400

    user.rfid = rfid
    db.session.commit()
    return jsonify(msg='RFID asignado/reasignado'), 200


@bp.route('/rfid-access', methods=['POST'])
def rfid_access():
    data = request.get_json() or {}
    rfid = data.get('rfid')
    if not rfid:
        return jsonify(status='Denegado', reason='No se envió rfid'), 400

    user = User_iot.query.filter_by(rfid=rfid).first()
    now = datetime.utcnow()
    status = 'Permitido' if (user and user.is_admin) else 'Denegado'
    reason = None if status == 'Permitido' else ('RFID no registrado' if not user else 'RFID no autorizado')

    log = AccessLog(
        user_id=user.id if (user and user.is_admin) else (user.id if user else None),
        timestamp=now,
        sensor_type='RFID',
        status=status,
        rfid=rfid,
        reason=reason
    )
    db.session.add(log)
    db.session.commit()

    trigger_buzzer = False
    failed_count = None
    if status == 'Denegado':
 
        failed_count = _record_failed_attempt(identifier=rfid, identifier_type='rfid', device_id=None, user_id=(user.id if user else None), reason=reason)
        if failed_count >= 3:
            trigger_buzzer = True

    attendance_info = None
    if status == 'Permitido':
        try:
            from app.routes.attendance import register_attendance_from_access
            attendance_info = register_attendance_from_access(log)
        except Exception:
            attendance_info = None

    resp = {
        'status': status,
        'reason': reason,
        'trigger_buzzer': trigger_buzzer,
        'failed_count': failed_count
    }

    if user:
        resp['user_id'] = user.id

        if 'attendance_info' in locals() and attendance_info:
            resp['attendance_action'] = attendance_info.get('action')
            resp['attendance_id'] = attendance_info.get('attendance_id')
            if 'schedule' in attendance_info:
                resp['estado_horario'] = attendance_info['schedule'].get('state')
                resp['minutes_diff'] = attendance_info['schedule'].get('minutes_diff')

    if status == 'Permitido':
        return jsonify(resp), 200
    else:
        return jsonify(resp), 403


@bp.route('/fingerprint-access', methods=['POST'])
def fingerprint_access():
    data = request.get_json() or {}
    huella_id = data.get('huella_id')

    if huella_id is None:
        return jsonify(status='Denegado', reason='Falta huella_id'), 400

    user = User_iot.query.filter_by(huella_id=huella_id).first()
    now = datetime.utcnow()
    status = 'Permitido' if user else 'Denegado'
    reason = None if user else 'Huella no válida'

    log = AccessLog(
        user_id=user.id if user else None,
        timestamp=now,
        sensor_type='Huella',
        status=status,
        huella_id=huella_id if user else None,
        reason=reason
    )
    db.session.add(log)
    db.session.commit()

    trigger_buzzer = False
    failed_count = None
    if status == 'Denegado':
  
        failed_count = _record_failed_attempt(identifier=str(huella_id), identifier_type='huella', device_id=None, user_id=None, reason=reason)
        if failed_count >= 3:
            trigger_buzzer = True

    attendance_info = None
    if status == 'Permitido':
        try:
            from app.routes.attendance import register_attendance_from_access
            attendance_info = register_attendance_from_access(log)
        except Exception:
            attendance_info = None

    resp = {
        'status': status,
        'reason': reason,
        'trigger_buzzer': trigger_buzzer,
        'failed_count': failed_count
    }
    if user:
        resp['user_id'] = user.id
    if attendance_info:
        resp['attendance_action'] = attendance_info.get('action')
        resp['attendance_id'] = attendance_info.get('attendance_id')
        if 'schedule' in attendance_info:
            resp['estado_horario'] = attendance_info['schedule'].get('state')
            resp['minutes_diff'] = attendance_info['schedule'].get('minutes_diff')

    return (jsonify(resp), 200) if status == 'Permitido' else (jsonify(resp), 403)


@bp.route('/history', methods=['GET'])
@jwt_required()
def access_history():
    user_id = request.args.get('user_id')
    date = request.args.get('date') 
    sensor_type = request.args.get('sensor_type')
    query = AccessLog.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    if date:
        query = query.filter(db.func.date(AccessLog.timestamp) == date)
    if sensor_type:
        query = query.filter_by(sensor_type=sensor_type)

    logs = query.order_by(AccessLog.timestamp.desc()).all()
    result = []
    for log in logs:
        result.append({
            'id': log.id,
            'user_id': log.user_id,
            'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            'sensor_type': log.sensor_type,
            'status': str(log.status) if hasattr(log.status, 'value') else log.status,
            'rfid': log.rfid,
            'reason': log.reason
        })
    return jsonify(result), 200


@bp.route('/export/csv', methods=['GET'])
@jwt_required()
def export_csv():
    query = AccessLog.query
    user_id = request.args.get('user_id')
    date = request.args.get('date')
    sensor_type = request.args.get('sensor_type')
    if user_id:
        query = query.filter_by(user_id=user_id)
    if date:
        query = query.filter(db.func.date(AccessLog.timestamp) == date)
    if sensor_type:
        query = query.filter_by(sensor_type=sensor_type)
    logs = query.order_by(AccessLog.timestamp.desc()).all()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['id', 'user_id', 'timestamp', 'sensor_type', 'status', 'rfid', 'reason'])
    for log in logs:
        cw.writerow([
            log.id,
            log.user_id,
            log.timestamp.isoformat() if log.timestamp else '',
            log.sensor_type,
            str(log.status) if hasattr(log.status, 'value') else log.status,
            log.rfid,
            log.reason
        ])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=access_logs.csv"})
