# app/routes/access.py
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from io import StringIO
import csv

import pytz

from app import db
from app.models import User_iot, AccessLog, Role, UserSchedule, Schedule, FailedAttempt

bp = Blueprint('access', __name__)
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




@bp.route('/fingerprint-access', methods=['POST'])
def fingerprint_access():
    data = request.get_json() or {}
    huella_id = data.get('huella_id')

    if huella_id is None:
        return jsonify(success=False, reason='Falta huella_id'), 400

    user = User_iot.query.filter_by(huella_id=huella_id).first()
    
    if not user:
        failed_count = _record_failed_attempt(
            identifier=str(huella_id), 
            identifier_type='huella', 
            reason='Huella no registrada'
        )
        return jsonify({
            "success": False,
            "reason": "Acceso denegado - Huella no registrada",
            "trigger_buzzer": (failed_count >= 3),
            "failed_count": failed_count
        }), 403


    last_access = AccessLog.query.filter(
        AccessLog.user_id == user.id,
        AccessLog.status == 'Permitido'
    ).order_by(AccessLog.timestamp.desc()).first()
    
   
    if not last_access or last_access.action_type == 'SALIDA':
        action_type = 'ENTRADA'
        message = "¡Bienvenido! Entrada permitida"
    else:
        action_type = 'SALIDA'
        message = "¡Hasta pronto! Salida permitida"
    

    log = AccessLog(
        user_id=user.id,
        timestamp=datetime.utcnow(),
        sensor_type='Huella',
        status='Permitido',
        huella_id=huella_id,
        reason=None,
        action_type=action_type
    )
    
    db.session.add(log)
    db.session.commit()

    return jsonify({
        "success": True,
        "user_id": user.id,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "message": message,
        "action_type": action_type,
        "trigger_buzzer": False
    }), 200


@bp.route('/rfid-access', methods=['POST'])
def rfid_access():

    data = request.get_json() or {}
    rfid = data.get('rfid')
    if not rfid:
        return jsonify(success=False, reason='No se envió RFID'), 400

    user = User_iot.query.filter_by(rfid=rfid).first()
    
    
    if not user:
        failed_count = _record_failed_attempt(
            identifier=rfid, 
            identifier_type='rfid', 
            reason='RFID no registrado'
        )
        return jsonify({
            "success": False,
            "reason": "Acceso denegado - RFID no registrado",
            "trigger_buzzer": (failed_count >= 3),
            "failed_count": failed_count
        }), 403

  
    log = AccessLog(
        user_id=user.id,
        timestamp=datetime.utcnow(),
        sensor_type='RFID',
        status='Permitido',
        rfid=rfid,
        reason=None
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        "success": True,
        "user_id": user.id,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "message": "Acceso permitido",
        "trigger_buzzer": False
    }), 200

@bp.route('/secure-zone', methods=['POST'])
def secure_zone_access():

    data = request.get_json() or {}
    huella_id = data.get('huella_id')
    rfid = data.get('rfid')

    user = User_iot.query.filter_by(huella_id=huella_id).first()
    
    if not user:
        return jsonify({
            "access": False,
            "reason": "Huella no registrada",
            "buzzer": "error"
        }), 403

    if user.role.name != "admin":
        return jsonify({
            "access": False,
            "reason": "Solo administradores",
            "buzzer": "error"
        }), 403

    if user.rfid != rfid:
        return jsonify({
            "access": False,
            "reason": "RFID no coincide",
            "buzzer": "error"
        }), 403

    log = AccessLog(
        user_id=user.id,
        timestamp=datetime.utcnow(),
        sensor_type="ZonaSegura",
        status="Permitido",
        huella_id=huella_id,
        rfid=rfid
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({
        "access": True,
        "user_id": user.id,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "buzzer": "success",
        "message": "Acceso a zona segura permitido"
    }), 200


@bp.route('/fingerprint-attendance', methods=['POST'])
def fingerprint_attendance():

    return jsonify({
        "success": False,
        "reason": "Endpoint movido. Use /attendance/fingerprint-attendance",
        "new_endpoint": "/attendance/fingerprint-attendance"
    }), 410  




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
    return Response(output, mimetype="text/csv", 
                   headers={"Content-Disposition": "attachment;filename=access_logs.csv"})



def register_attendance_from_access(access_log):
    from app.routes.attendance import register_attendance_from_access as new_attendance_func
    return new_attendance_func(access_log)

@bp.route('/setup', methods=['POST'])
def setup_system():
    if User_iot.query.first():
        return jsonify({"msg": "System already setup"}), 400
    
 
    admin_role = Role(name="admin")
    empleado_role = Role(name="empleado")
    db.session.add_all([admin_role, empleado_role])
    db.session.flush()
    
    admin = User_iot(
        username="admin",
        nombre="Administrador",
        apellido="Sistema", 
        role=admin_role
    )
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()
    
    return jsonify({
        "msg": "System setup completed", 
        "admin_id": admin.id,
        "next_step": "Register admin fingerprint via /users/huella/register"
    }), 201