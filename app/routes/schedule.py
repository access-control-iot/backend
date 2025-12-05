# app/routes/schedule.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt, jwt_required, get_jwt_identity
from datetime import date, datetime
from functools import wraps
from sqlalchemy import or_

from app import db
from app.models import Schedule, UserSchedule, ScheduleAudit, User_iot

schedule_bp = Blueprint('schedule', __name__, url_prefix='/schedules')


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


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("role") != "admin":
            return jsonify(msg="Solo administradores"), 403
        return fn(*args, **kwargs)
    return wrapper


def parse_time_str(t_str):
    if isinstance(t_str, (datetime,)):
        return t_str.time()
    if not t_str:
        raise ValueError("Hora vacía")
    return datetime.strptime(t_str, '%H:%M').time()


def parse_date_str(d_str):
    if not d_str:
        raise ValueError("Fecha vacía")
    return datetime.strptime(d_str, '%Y-%m-%d').date()


def validate_days(dias):
    valid = {'Lun','Mar','Mie','Jue','Vie','Sab','Dom'}
    if dias is None:
        raise ValueError("dias es requerido")
    if isinstance(dias, str):
        dias_list = [d.strip() for d in dias.split(',') if d.strip()]
    else:
        dias_list = list(dias)

    if not dias_list:
        raise ValueError("dias debe tener al menos un día")
    for d in dias_list:
        if d not in valid:
            raise ValueError(f"día inválido: {d}")
    return ','.join(dias_list)


def validate_tipo(tipo):
    if tipo not in ('fijo', 'rotativo'):
        raise ValueError("tipo inválido, debe ser 'fijo' o 'rotativo'")
    return tipo


def record_audit(schedule_id=None, user_id=None, admin_id=None, change_type='', details=''):
    a = ScheduleAudit(
        schedule_id=schedule_id,
        user_id=user_id,
        admin_id=admin_id,
        change_type=change_type,
        details=details
    )
    db.session.add(a)
    db.session.commit()
    return a


@schedule_bp.route('/', methods=['POST'])
@jwt_required()
@admin_required
def create_schedule():
    data = request.get_json() or {}
    try:
        nombre = data.get('nombre')
        if not nombre:
            return jsonify(msg='nombre es requerido'), 400

        if not data.get("hora_entrada") or not data.get("hora_salida"):
            return jsonify(msg="hora_entrada y hora_salida son requeridos"), 400

        hora_entrada = parse_time_str(data.get('hora_entrada'))
        hora_salida = parse_time_str(data.get('hora_salida'))
        tolerancia_entrada = int(data.get('tolerancia_entrada', 0))
        tolerancia_salida = int(data.get('tolerancia_salida', 0))
        dias_csv = validate_days(data.get('dias'))
        tipo = validate_tipo(data.get('tipo'))

    except ValueError as e:
        return jsonify(msg=str(e)), 400
    except Exception as e:
        return jsonify(msg='Error en datos de entrada', detail=str(e)), 400

    schedule = Schedule(
        nombre=nombre,
        hora_entrada=hora_entrada,
        tolerancia_entrada=tolerancia_entrada,
        hora_salida=hora_salida,
        tolerancia_salida=tolerancia_salida,
        dias=dias_csv,
        tipo=tipo
    )
    db.session.add(schedule)
    db.session.commit()

    admin = _get_user_from_identity(get_jwt_identity())
    record_audit(schedule_id=schedule.id, admin_id=admin.id if admin else None,
                 change_type='create', details=f'Creación horario {nombre}')

    return jsonify(msg='Horario creado', id=schedule.id), 201


@schedule_bp.route('/assign', methods=['POST'])
@jwt_required()
@admin_required
def assign_schedule():
    data = request.get_json() or {}
    try:
        user_id = int(data.get('user_id'))
        schedule_id = int(data.get('schedule_id'))
        start_date = parse_date_str(data.get('start_date'))
        end_date = parse_date_str(data.get('end_date')) if data.get('end_date') else None
    except (TypeError, ValueError) as e:
        return jsonify(msg='Parámetros inválidos', detail=str(e)), 400

    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(msg='Usuario no existe'), 404

    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return jsonify(msg='Schedule no existe'), 404

    existing_schedules = UserSchedule.query.filter(
        UserSchedule.user_id == user_id,
        UserSchedule.start_date <= (end_date or date.max),
        or_(
            UserSchedule.end_date == None,
            UserSchedule.end_date >= start_date
        )
    ).all()

    def _to_time(t):
        if isinstance(t, str):
            return datetime.strptime(t, "%H:%M").time()
        return t

    def horarios_chocan(h1: Schedule, h2: Schedule):
        dias1 = set([d.strip() for d in h1.dias.split(",")])
        dias2 = set([d.strip() for d in h2.dias.split(",")])
        if dias1.isdisjoint(dias2):
            return False

        e1 = _to_time(h1.hora_entrada)
        s1 = _to_time(h1.hora_salida)
        e2 = _to_time(h2.hora_entrada)
        s2 = _to_time(h2.hora_salida)

        return not (s1 <= e2 or s2 <= e1)

    for us in existing_schedules:
        if horarios_chocan(schedule, us.schedule):
            return jsonify(msg="El usuario ya tiene un horario asignado que se cruza en días y horas"), 400

    us = UserSchedule(
        user_id=user_id,
        schedule_id=schedule_id,
        start_date=start_date,
        end_date=end_date
    )
    db.session.add(us)
    db.session.commit()

    admin = _get_user_from_identity(get_jwt_identity())
    details = f'Asignado schedule {schedule_id} a user {user_id} desde {start_date} hasta {end_date}'
    record_audit(schedule_id=schedule_id, user_id=user_id, admin_id=admin.id if admin else None,
                 change_type='assign', details=details)

    return jsonify(msg='Horario asignado'), 201


@schedule_bp.route('/<int:schedule_id>', methods=['GET'])
@jwt_required()
@admin_required
def get_schedule(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return jsonify(msg='Horario no encontrado'), 404
    
    return jsonify({
        'id': schedule.id,
        'nombre': schedule.nombre,
        'hora_entrada': schedule.hora_entrada.strftime('%H:%M'),
        'tolerancia_entrada': schedule.tolerancia_entrada,
        'hora_salida': schedule.hora_salida.strftime('%H:%M'),
        'tolerancia_salida': schedule.tolerancia_salida,
        'dias': schedule.dias,
        'tipo': schedule.tipo
    }), 200


@schedule_bp.route('/<int:schedule_id>', methods=['PUT'])
@jwt_required()
@admin_required
def update_schedule(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return jsonify(msg='Horario no encontrado'), 404
        
    data = request.get_json() or {}
    cambios = []

    for field in ['nombre', 'hora_entrada', 'tolerancia_entrada', 'hora_salida',
                  'tolerancia_salida', 'dias', 'tipo']:

        if field not in data:
            continue

        new = data[field]
        old = getattr(schedule, field)

        if new is None or (isinstance(new, str) and new.strip() == ""):
            return jsonify(msg=f"Valor inválido para {field}", detail="No puede estar vacío"), 400

        try:
            if field in ['hora_entrada', 'hora_salida']:
                new_parsed = parse_time_str(new)
                setattr(schedule, field, new_parsed)
                cambios.append(f"{field}: {old} -> {new_parsed}")
            elif field in ['tolerancia_entrada', 'tolerancia_salida']:
                new_int = int(new)
                setattr(schedule, field, new_int)
                cambios.append(f"{field}: {old} -> {new_int}")
            elif field == 'dias':
                new_days = validate_days(new)
                setattr(schedule, field, new_days)
                cambios.append(f"{field}: {old} -> {new_days}")
            elif field == 'tipo':
                new_tipo = validate_tipo(new)
                setattr(schedule, field, new_tipo)
                cambios.append(f"{field}: {old} -> {new_tipo}")
            else:
                setattr(schedule, field, new)
                cambios.append(f"{field}: {old} -> {new}")
        except ValueError as e:
            return jsonify(msg=f"Valor inválido para {field}", detail=str(e)), 400

    db.session.commit()
    admin = _get_user_from_identity(get_jwt_identity())
    record_audit(
        schedule_id=schedule.id,
        admin_id=admin.id if admin else None,
        change_type='update',
        details='; '.join(cambios) or 'sin cambios'
    )
    return jsonify(msg='Horario actualizado'), 200


@schedule_bp.route('/<int:schedule_id>/force', methods=['DELETE', 'OPTIONS'])
@jwt_required()
@admin_required
def force_delete_schedule(schedule_id):
    """Elimina el horario y todas sus asignaciones"""
    # Manejar preflight request
    if request.method == 'OPTIONS':
        return jsonify({'msg': 'OK'}), 200
    
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return jsonify(msg='Horario no encontrado'), 404
        
    try:
        # 1. Eliminar todas las asignaciones primero
        UserSchedule.query.filter_by(schedule_id=schedule_id).delete()
        
        # 2. Ahora eliminar el horario
        db.session.delete(schedule)
        db.session.commit()
        
        admin = _get_user_from_identity(get_jwt_identity())
        record_audit(schedule_id=schedule_id, admin_id=admin.id if admin else None,
                    change_type='force_delete', details=f'Eliminado forzado schedule {schedule_id} con todas sus asignaciones')
        
        return jsonify({
            'success': True,
            'msg': 'Horario y asignaciones eliminados correctamente'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'msg': f'Error al eliminar: {str(e)}'
        }), 500


@schedule_bp.route('/<int:schedule_id>/reassign', methods=['POST', 'OPTIONS'])
@jwt_required()
@admin_required
def reassign_and_delete_schedule(schedule_id):
    """Reasigna usuarios a otro horario y luego elimina"""
    # Manejar preflight request
    if request.method == 'OPTIONS':
        return jsonify({'msg': 'OK'}), 200
    
    data = request.get_json() or {}
    
    # Validar datos
    if not data:
        return jsonify(success=False, msg='Datos JSON requeridos'), 400
        
    new_schedule_id = data.get('new_schedule_id')
    if not new_schedule_id:
        return jsonify(success=False, msg='Se requiere nuevo horario (new_schedule_id)'), 400
        
    try:
        schedule = Schedule.query.get(schedule_id)
        if not schedule:
            return jsonify(success=False, msg='Horario no encontrado'), 404
            
        new_schedule = Schedule.query.get(new_schedule_id)
        if not new_schedule:
            return jsonify(success=False, msg='Nuevo horario no encontrado'), 404
            
        # 1. Reasignar todos los usuarios
        assignments = UserSchedule.query.filter_by(schedule_id=schedule_id).all()
        reassigned = 0
        
        for assignment in assignments:
            assignment.schedule_id = new_schedule_id
            reassigned += 1
        
        # 2. Eliminar el horario original
        db.session.delete(schedule)
        db.session.commit()
        
        admin = _get_user_from_identity(get_jwt_identity())
        record_audit(
            schedule_id=schedule_id,
            admin_id=admin.id if admin else None,
            change_type='reassign_delete',
            details=f'Reasignados {reassigned} usuarios a schedule {new_schedule_id} y eliminado schedule {schedule_id}'
        )
        
        return jsonify({
            'success': True,
            'msg': f'Horario eliminado y {reassigned} usuarios reasignados',
            'reassigned_count': reassigned
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'msg': f'Error en reasignación: {str(e)}'
        }), 500
@schedule_bp.route('/<int:schedule_id>/end-assignments', methods=['POST', 'OPTIONS'])
@jwt_required()
@admin_required
def end_schedule_assignments(schedule_id):
    """Termina todas las asignaciones del horario (cambia fecha fin a hoy)"""
    # Manejar preflight request
    if request.method == 'OPTIONS':
        return jsonify({'msg': 'OK'}), 200
    
    try:
        schedule = Schedule.query.get(schedule_id)
        if not schedule:
            return jsonify(success=False, msg='Horario no encontrado'), 404
            
        # Cambiar fecha fin de todas las asignaciones activas a hoy
        today = date.today()
        assignments = UserSchedule.query.filter(
            UserSchedule.schedule_id == schedule_id,
            (UserSchedule.end_date == None) | (UserSchedule.end_date >= today)
        ).all()
        
        ended_count = 0
        for assignment in assignments:
            assignment.end_date = today
            ended_count += 1
        
        db.session.commit()
        
        admin = _get_user_from_identity(get_jwt_identity())
        record_audit(
            schedule_id=schedule_id,
            admin_id=admin.id if admin else None,
            change_type='end_assignments',
            details=f'Terminadas {ended_count} asignaciones del schedule {schedule_id}'
        )
        
        return jsonify({
            'success': True,
            'msg': f'Terminadas {ended_count} asignaciones',
            'ended_count': ended_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'msg': f'Error terminando asignaciones: {str(e)}'
        }), 500



@schedule_bp.route('/<int:schedule_id>/assignments', methods=['GET', 'OPTIONS'])
@jwt_required()
@admin_required
def get_schedule_assignments(schedule_id):
    """Obtiene todas las asignaciones de un horario"""
    # Manejar preflight request
    if request.method == 'OPTIONS':
        return jsonify({'msg': 'OK'}), 200
    
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return jsonify(success=False, msg='Horario no encontrado'), 404
        
    assignments = UserSchedule.query.filter_by(schedule_id=schedule_id).all()
    result = []
    
    for assignment in assignments:
        user = assignment.user
        result.append({
            'user_id': user.id,
            'user_name': f'{user.nombre} {user.apellido}',
            'username': user.username,
            'start_date': assignment.start_date.isoformat() if assignment.start_date else None,
            'end_date': assignment.end_date.isoformat() if assignment.end_date else None,
            'is_active': assignment.end_date is None or assignment.end_date >= date.today()
        })
    
    return jsonify({
        'success': True,
        'schedule_id': schedule_id,
        'schedule_name': schedule.nombre,
        'assignments': result,
        'total_count': len(result),
        'active_count': len([a for a in result if a['is_active']])
    }), 200
@schedule_bp.route('/audit', methods=['GET'])
@jwt_required()
@admin_required
def schedule_audit():
    audits = ScheduleAudit.query.order_by(ScheduleAudit.timestamp.desc()).all()
    result = []
    for a in audits:
        result.append({
            'id': a.id,
            'schedule_id': a.schedule_id,
            'user_id': a.user_id,
            'admin_id': a.admin_id,
            'timestamp': a.timestamp.isoformat(),
            'change_type': a.change_type,
            'details': a.details
        })
    return jsonify(result), 200


@schedule_bp.route('/', methods=['GET'])
@jwt_required()
@admin_required
def list_schedules():
    schedules = Schedule.query.order_by(Schedule.nombre).all()
    result = []
    for s in schedules:
        result.append({
            'id': s.id,
            'nombre': s.nombre,
            'hora_entrada': s.hora_entrada.strftime('%H:%M'),
            'tolerancia_entrada': s.tolerancia_entrada,
            'hora_salida': s.hora_salida.strftime('%H:%M'),
            'tolerancia_salida': s.tolerancia_salida,
            'dias': s.dias,
            'tipo': s.tipo
        })
    return jsonify(result), 200


@schedule_bp.route('/my', methods=['GET'])
@jwt_required()
def get_my_schedule():
    identity = get_jwt_identity()
    user = _get_user_from_identity(identity)

    if not user:
        return jsonify(msg="Usuario no encontrado"), 404

    user_schedules = UserSchedule.query.filter_by(user_id=user.id).all()

    result = []
    for us in user_schedules:
        s = us.schedule
        result.append({
            "schedule_id": s.id,
            "nombre": s.nombre,
            "hora_entrada": s.hora_entrada.strftime('%H:%M'),
            "tolerancia_entrada": s.tolerancia_entrada,
            "hora_salida": s.hora_salida.strftime('%H:%M'),
            "tolerancia_salida": s.tolerancia_salida,
            "dias": s.dias,
            "tipo": s.tipo,
            "start_date": us.start_date.isoformat() if us.start_date else None,
            "end_date": us.end_date.isoformat() if us.end_date else None
        })

    return jsonify(result), 200
@schedule_bp.route('/<int:schedule_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def delete_schedule(schedule_id):
    schedule = Schedule.query.get(schedule_id)
    if not schedule:
        return jsonify(msg='Horario no encontrado'), 404
        
    # Verificar si hay asignaciones activas
    active_us = UserSchedule.query.filter(
        UserSchedule.schedule_id == schedule_id,
        (UserSchedule.end_date == None) | (UserSchedule.end_date >= date.today())
    ).first()

    if active_us:
        return jsonify(msg='No se puede eliminar: existen asignaciones activas'), 400

    db.session.delete(schedule)
    db.session.commit()

    admin = _get_user_from_identity(get_jwt_identity())
    record_audit(schedule_id=schedule_id, admin_id=admin.id if admin else None,
                 change_type='delete', details=f'Eliminado schedule {schedule_id}')
    return jsonify(msg='Horario eliminado'), 200