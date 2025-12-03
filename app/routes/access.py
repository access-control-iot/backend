# app/routes/access.py
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from io import StringIO
import csv

import pytz

from app import db
from app.models import User_iot, AccessLog, Role, UserSchedule, Schedule, FailedAttempt, Attendance

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
            "reason": "Huella no registrada",  
            "trigger_buzzer": (failed_count >= 3),
            "failed_count": failed_count
        }), 403

    
    last_access = AccessLog.query.filter(
        AccessLog.user_id == user.id,
        AccessLog.status == 'Permitido'
    ).order_by(AccessLog.timestamp.desc()).first()
    
    
    if not last_access or last_access.action_type == 'SALIDA':
        action_type = 'ENTRADA'
        message = "Entrada permitida"
    else:
        action_type = 'SALIDA'
        message = "Salida permitida"
    
    
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


    last_access = AccessLog.query.filter(
        AccessLog.user_id == user.id,
        AccessLog.status == 'Permitido',
        AccessLog.sensor_type == 'RFID' 
    ).order_by(AccessLog.timestamp.desc()).first()
    

    if not last_access or last_access.action_type == 'SALIDA':
        action_type = 'ENTRADA'
        message = "Entrada permitida por RFID"
    else:
        action_type = 'SALIDA'
        message = "Salida permitida por RFID"


    log = AccessLog(
        user_id=user.id,
        timestamp=datetime.utcnow(),
        sensor_type='RFID',
        status='Permitido',
        rfid=rfid,
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

def determinar_accion_usuario(user_id, sensor_type='Huella'):
 
    last_access = AccessLog.query.filter(
        AccessLog.user_id == user_id,
        AccessLog.status == 'Permitido',
        AccessLog.sensor_type == sensor_type
    ).order_by(AccessLog.timestamp.desc()).first()
    
    if not last_access or last_access.action_type == 'SALIDA':
        return 'ENTRADA'
    else:
        return 'SALIDA'
    
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

def decidir_accion_automatica(user, timestamp):
    if user.role.name == "admin":
        return {
            'tipo': 'ACCESO',
            'registrar_asistencia': False,
            'razon': 'Usuario administrador'
        }
    
    schedule = get_user_schedule(user.id, timestamp)
    
    if not schedule:
        return {
            'tipo': 'ACCESO',
            'registrar_asistencia': False,
            'razon': 'Usuario sin horario asignado'
        }
    
   
    dias = [d.strip() for d in schedule.dias.split(',')]
    dia_text = ['Lun','Mar','Mie','Jue','Vie','Sab','Dom'][timestamp.weekday()]
    
    if dia_text not in dias:
        return {
            'tipo': 'ACCESO',
            'registrar_asistencia': False,
            'razon': f'No es día laboral ({dia_text})'
        }
    
   
    hora_entrada = schedule.hora_entrada
    hora_salida = schedule.hora_salida
    tolerancia_entrada = schedule.tolerancia_entrada or 0
    tolerancia_salida = schedule.tolerancia_salida or 0
    
    
    inicio_jornada = datetime.combine(timestamp.date(), hora_entrada)
    fin_jornada = datetime.combine(timestamp.date(), hora_salida)
    
    inicio_jornada = LIMA_TZ.localize(inicio_jornada)
    fin_jornada = LIMA_TZ.localize(fin_jornada)
    
    
    ventana_entrada_inicio = inicio_jornada - timedelta(minutes=10)  
    ventana_entrada_fin = inicio_jornada + timedelta(minutes=tolerancia_entrada)
    

    ventana_salida_inicio = fin_jornada - timedelta(minutes=1)  
    ventana_salida_fin = fin_jornada + timedelta(minutes=tolerancia_salida)
    
   
    if ventana_entrada_inicio <= timestamp <= ventana_entrada_fin:
        return {
            'tipo': 'ACCESO_Y_ASISTENCIA',
            'registrar_asistencia': True,
            'razon': 'Dentro de ventana de entrada',
            'accion_asistencia': 'entrada',
            'hora_entrada_real': hora_entrada.strftime('%H:%M'),
            'hora_salida_real': hora_salida.strftime('%H:%M')
        }
  
    elif ventana_salida_inicio <= timestamp <= ventana_salida_fin:
        return {
            'tipo': 'ACCESO_Y_ASISTENCIA',
            'registrar_asistencia': True,
            'razon': 'Dentro de ventana de salida',
            'accion_asistencia': 'salida',
            'hora_entrada_real': hora_entrada.strftime('%H:%M'),
            'hora_salida_real': hora_salida.strftime('%H:%M')
        }
    else:
        
        if inicio_jornada <= timestamp <= fin_jornada + timedelta(minutes=tolerancia_salida):
            return {
                'tipo': 'ACCESO',
                'registrar_asistencia': False,
                'razon': 'Dentro de horario laboral, fuera de ventana de asistencia',
                'hora_entrada_real': hora_entrada.strftime('%H:%M'),
                'hora_salida_real': hora_salida.strftime('%H:%M'),
                'hora_actual': timestamp.strftime('%H:%M')
            }
        else:
            return {
                'tipo': 'ACCESO',
                'registrar_asistencia': False,
                'razon': 'Fuera de horario laboral',
                'hora_entrada_real': hora_entrada.strftime('%H:%M'),
                'hora_salida_real': hora_salida.strftime('%H:%M'),
                'hora_actual': timestamp.strftime('%H:%M')
            }
def get_user_schedule(user_id, dt):
    
    from app.models import UserSchedule, Schedule
    local_date = dt.astimezone(LIMA_TZ).date() if dt.tzinfo else dt.date()
    us = UserSchedule.query.filter(
        UserSchedule.user_id == user_id,
        UserSchedule.start_date <= local_date,
        (UserSchedule.end_date == None) | (UserSchedule.end_date >= local_date)
    ).first()
    if not us:
        return None
    return Schedule.query.get(us.schedule_id)
def determinar_accion_acceso(user_id):
    last_access = AccessLog.query.filter(
        AccessLog.user_id == user_id,
        AccessLog.status == 'Permitido',
        AccessLog.sensor_type.in_(['Huella', 'RFID'])
    ).order_by(AccessLog.timestamp.desc()).first()
    
    if not last_access:
        return 'ENTRADA'  
    if last_access.action_type:
        if 'ENTRADA' in last_access.action_type:
            return 'SALIDA'
        elif 'SALIDA' in last_access.action_type:
            return 'ENTRADA'
    
   
    total_accesos = AccessLog.query.filter_by(user_id=user_id, status='Permitido').count()
    return 'SALIDA' if total_accesos % 2 == 1 else 'ENTRADA'

@bp.route('/auto-access', methods=['POST'])
def auto_access():
    data = request.get_json() or {}
    huella_id = data.get('huella_id')
    rfid = data.get('rfid')
    
   
    es_zona_segura = (huella_id is not None and rfid is not None)
    
    if es_zona_segura:
        
        user = User_iot.query.filter_by(huella_id=huella_id).first()
        
        if not user or user.role.name != "admin":
            return jsonify({
                "success": False,
                "reason": "Acceso denegado - Zona solo para administradores",
                "tipo": "ZONA_SEGURA_DENEGADA"
            }), 403
        
        if user.rfid != rfid:
            return jsonify({
                "success": False,
                "reason": "RFID no coincide",
                "tipo": "ZONA_SEGURA_DENEGADA"
            }), 403
        
        log = AccessLog(
            user_id=user.id,
            timestamp=datetime.utcnow(),
            sensor_type="ZonaSegura",
            status="Permitido",
            huella_id=huella_id,
            rfid=rfid,
            action_type="ACCESO_ZONA_SEGURA"
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "tipo": "ZONA_SEGURA",
            "message": "Acceso a zona segura permitido",
            "user_id": user.id,
            "nombre": user.nombre,
            "action_type": "ACCESO_ZONA_SEGURA",
            "registrar_asistencia": False
        }), 200
    
   
    if huella_id:
        user = User_iot.query.filter_by(huella_id=huella_id).first()
        sensor_type = 'Huella'
        identifier = str(huella_id)
    elif rfid:
        user = User_iot.query.filter_by(rfid=rfid).first()
        sensor_type = 'RFID'
        identifier = rfid
    else:
        return jsonify(success=False, reason='Falta huella_id o rfid'), 400
    
    if not user:
        failed_count = _record_failed_attempt(
            identifier=identifier,
            identifier_type='huella' if huella_id else 'rfid',
            reason=f'{sensor_type} no registrado'
        )
        return jsonify({
            "success": False,
            "reason": f"Acceso denegado - {sensor_type} no registrado",
            "trigger_buzzer": (failed_count >= 3),
            "failed_count": failed_count,
            "tipo": "ACCESO_DENEGADO"
        }), 403
    
    timestamp = datetime.utcnow()
    lima_timestamp = timestamp.astimezone(LIMA_TZ)
    
    
    last_access = AccessLog.query.filter(
        AccessLog.user_id == user.id,
        AccessLog.status == 'Permitido',
        AccessLog.sensor_type.in_(['Huella', 'RFID'])
    ).order_by(AccessLog.timestamp.desc()).first()
    
    if not last_access:
        access_action = 'ENTRADA'
    else:
        
        if last_access.action_type:
            if 'ENTRADA' in last_access.action_type:
                access_action = 'SALIDA'
            elif 'SALIDA' in last_access.action_type:
                access_action = 'ENTRADA'
            else:
                access_action = 'SALIDA' if last_access.action_type == 'ENTRADA' else 'ENTRADA'
        else:
            access_action = 'SALIDA' if last_access.action_type == 'ENTRADA' else 'ENTRADA'
    
    
    decision = decidir_accion_automatica(user, lima_timestamp)
    
 
    hoy = lima_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    mañana = hoy + timedelta(days=1)
    
    asistencia_abierta = Attendance.query.filter(
        Attendance.user_id == user.id,
        Attendance.entry_time >= hoy,
        Attendance.entry_time < mañana,
        Attendance.exit_time.is_(None)
    ).first()
    
   
    if decision['registrar_asistencia']:
      
        if decision.get('accion_asistencia') == 'salida' and not asistencia_abierta:
           
            decision['registrar_asistencia'] = False
            decision['tipo'] = 'ACCESO'
            decision['razon'] = 'No tiene entrada registrada para marcar salida'
        elif decision.get('accion_asistencia') == 'entrada' and asistencia_abierta:
            
            decision['registrar_asistencia'] = False
            decision['tipo'] = 'ACCESO'
            decision['razon'] = 'Ya tiene asistencia abierta hoy'
    else:
        
        if access_action == 'SALIDA' and asistencia_abierta:
            
            decision['registrar_asistencia'] = True
            decision['tipo'] = 'ACCESO_Y_ASISTENCIA'
            decision['razon'] = 'Cierre de jornada laboral'
            decision['accion_asistencia'] = 'salida'
            print(f"DEBUG: Forzando cierre de jornada para usuario {user.id}")
    
 
    log = AccessLog(
        user_id=user.id,
        timestamp=timestamp,
        sensor_type=sensor_type,
        status='Permitido',
        huella_id=huella_id if huella_id else None,
        rfid=rfid if rfid else None,
        action_type=f"{access_action}_{decision['tipo']}",
        motivo_decision=decision['razon']
    )
    db.session.add(log)
    
   
    attendance_data = None
    if decision['registrar_asistencia']:
        print(f"DEBUG: Registrando asistencia para usuario {user.id}, acción: {decision.get('accion_asistencia', 'entry')}")
        attendance_data = register_attendance_from_access(log)
        if attendance_data:
            print(f"DEBUG: Resultado asistencia: {attendance_data}")
    
    db.session.commit()
    
    
    response = {
        "success": True,
        "tipo": decision['tipo'],
        "user_id": user.id,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "access_action": access_action,
        "message": f"{access_action} permitida - {decision['razon']}",
        "registrar_asistencia": decision['registrar_asistencia'],
        "decision_razon": decision['razon'],
        "hora_actual": lima_timestamp.strftime('%H:%M'),
        "ultimo_acceso": last_access.timestamp.isoformat() if last_access else None,
        "ultima_accion": last_access.action_type if last_access else None,
        "asistencia_abierta": bool(asistencia_abierta)
    }
    
    
    schedule = get_user_schedule(user.id, lima_timestamp)
    if schedule:
        response.update({
            "hora_entrada": schedule.hora_entrada.strftime('%H:%M'),
            "hora_salida": schedule.hora_salida.strftime('%H:%M'),
            "dias_laborales": schedule.dias,
            "tolerancia_entrada": schedule.tolerancia_entrada,
            "tolerancia_salida": schedule.tolerancia_salida
        })
    

    if attendance_data and attendance_data.get('ok'):
        response['asistencia_registrada'] = True
        response['asistencia_action'] = attendance_data.get('action')
        if attendance_data.get('action') == 'entry':
            response['estado_entrada'] = attendance_data.get('estado', 
                                                           attendance_data.get('schedule', {}).get('state'))
            response['minutes_diff'] = attendance_data.get('schedule', {}).get('minutes_diff')
        else:
            response['estado_entrada'] = 'salida_registrada'
            response['duracion_jornada'] = attendance_data.get('duracion_jornada')
    
    print(f"DEBUG: Respuesta final: {response}")
    return jsonify(response), 200