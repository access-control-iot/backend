# app/routes/access.py
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from io import StringIO
import csv

import pytz

from app import db
from app.models import User_iot, AccessLog,Role, UserSchedule, Schedule, FailedAttempt
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
            "reason": "Huella no registrada",
            "trigger_buzzer": (failed_count >= 3)
        }), 403

    try:
       
        log = AccessLog(
            user_id=user.id,
            timestamp=datetime.utcnow(),
            sensor_type='Huella',
            status='Permitido',
            huella_id=huella_id,
            reason=None
        )
        db.session.add(log)
        db.session.commit()

 
        from app.routes.attendance import register_attendance_from_access
        attendance_info = register_attendance_from_access(log)

   
        resp = {
            "success": True,
            "user_id": user.id,
            "nombre": user.nombre,
            "apellido": user.apellido,
            "trigger_buzzer": False
        }

        if attendance_info and attendance_info.get('ok'):
            resp["attendance_action"] = attendance_info.get('action')  
            resp["attendance_id"] = attendance_info.get('attendance_id')
            
       
            if 'schedule' in attendance_info:
                schedule_data = attendance_info['schedule']
                resp["estado_horario"] = schedule_data.get('state') 
                resp["minutes_diff"] = schedule_data.get('minutes_diff')
            
       
            if attendance_info.get('action') == 'entry':
                if attendance_info.get('tipo') == 'reingreso':
                    resp["message"] = "Reingreso registrado"
                elif resp.get("estado_horario") == 'tarde':
                    resp["message"] = f"Entrada registrada - Llegó {resp.get('minutes_diff', 0)} min tarde"
                elif resp.get("estado_horario") == 'presente':
                    resp["message"] = "Entrada registrada - A tiempo"
                else:
                    resp["message"] = attendance_info.get('message', 'Entrada registrada')
                    
            elif attendance_info.get('action') == 'exit':
                resp["message"] = attendance_info.get('message', 'Salida registrada')
                if 'duracion' in attendance_info:
                    resp["duracion_jornada"] = attendance_info['duracion']
        
        
        elif attendance_info and not attendance_info.get('ok'):
            resp["success"] = False
            resp["reason"] = attendance_info.get('reason')
            resp["message"] = attendance_info.get('message')
            resp["trigger_buzzer"] = True
            
        return jsonify(resp), 200

    except Exception as e:
        print(f"Error en fingerprint-access: {e}")
        db.session.rollback()
        return jsonify({
            "success": False,
            "reason": "Error interno del sistema",
            "trigger_buzzer": True
        }), 500
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
@bp.route('/setup', methods=['POST'])
def setup_system():
    if User_iot.query.first():
        return jsonify({"msg": "System already setup"}), 400
    
    # Crear roles
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
        "buzzer": "success"
    }), 200