# app/routes/schedule.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt, jwt_required, get_jwt_identity
from datetime import datetime
from functools import wraps

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
    return datetime.strptime(t_str, '%H:%M').time()  

def parse_date_str(d_str):
    return datetime.strptime(d_str, '%Y-%m-%d').date()

def validate_days(dias):
    valid = {'Lun','Mar','Mie','Jue','Vie','Sab','Dom'} 
    if not isinstance(dias, (list, tuple)) or not dias:
        raise ValueError("dias debe ser una lista con al menos un día")
    for d in dias:
        if d not in valid:
            raise ValueError(f"día inválido: {d}")
    return ','.join(dias)

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


@schedule_bp.route('/<int:schedule_id>', methods=['PUT'])
@jwt_required()
@admin_required
def update_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    data = request.get_json() or {}
    cambios = []
    for field in ['nombre', 'hora_entrada', 'tolerancia_entrada', 'hora_salida', 'tolerancia_salida', 'dias', 'tipo']:
        if field not in data:
            continue
        old = getattr(schedule, field)
        new = data[field]
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
            return jsonify(msg=f'Valor inválido para {field}', detail=str(e)), 400

    db.session.commit()
    admin = _get_user_from_identity(get_jwt_identity())
    record_audit(schedule_id=schedule.id, admin_id=admin.id if admin else None,
                 change_type='update', details='; '.join(cambios) or 'sin cambios')
    return jsonify(msg='Horario actualizado'), 200


@schedule_bp.route('/<int:schedule_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def delete_schedule(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    active_us = UserSchedule.query.filter(
        UserSchedule.schedule_id == schedule_id
    ).first()
    if active_us:
        return jsonify(msg='No se puede eliminar: existen asignaciones activas'), 400

    db.session.delete(schedule)
    db.session.commit()

    admin = _get_user_from_identity(get_jwt_identity())
    record_audit(schedule_id=schedule_id, admin_id=admin.id if admin else None,
                 change_type='delete', details=f'Eliminado schedule {schedule_id}')
    return jsonify(msg='Horario eliminado'), 200


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
