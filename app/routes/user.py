from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt, jwt_required, get_jwt_identity
from datetime import datetime
from functools import wraps
import base64

from ..models import User_iot, Role, Huella

from app import db


user_bp = Blueprint('user', __name__, url_prefix="/users")


def get_admin_identity():
    identity = get_jwt_identity()
    if isinstance(identity, dict):
        return identity
    return None


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()

        if claims.get("role") != "admin":
            return jsonify(msg="Solo administradores"), 403

        return fn(*args, **kwargs)
    return wrapper


def parse_date(date_str):
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d").date()



@user_bp.route("/create", methods=["POST"])
@jwt_required()
@admin_required
def create_user():
    data = request.get_json() or {}

    
    required = ["username", "password", "nombre", "apellido"]
    for field in required:
        if field not in data:
            return jsonify(msg=f"Campo requerido: {field}"), 400

    
    if User_iot.query.filter_by(username=data["username"]).first():
        return jsonify(msg="El username ya existe"), 400

    if data.get("rfid") and User_iot.query.filter_by(rfid=data["rfid"]).first():
        return jsonify(msg="El RFID ya está asignado"), 400
    
    huella_id = data.get("huella_id")
    if huella_id is not None:
        try:
            huella_id = int(huella_id)
        except:
            return jsonify(msg="huella_id debe ser un número entero"), 400


    role_name = data.get("role", "empleado")
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return jsonify(msg=f"Rol inválido: {role_name}"), 400

   
    user = User_iot(
        username=data["username"],
        nombre=data["nombre"],
        apellido=data["apellido"],
        genero=data.get("genero"),
        fecha_nacimiento=parse_date(data.get("fecha_nacimiento")),
        fecha_contrato=parse_date(data.get("fecha_contrato")),
        area_trabajo=data.get("area_trabajo"),
        huella_id=huella_id,
        rfid=data.get("rfid"),
        role=role  
    )

    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    return jsonify(msg="Usuario creado"), 201


@user_bp.route("/<int:user_id>", methods=["PUT"])
@jwt_required()
@admin_required
def update_user(user_id):
    user = User_iot.query.get_or_404(user_id)
    data = request.get_json() or {}


    if "rfid" in data:
        new_rfid = data.get("rfid")
        if new_rfid:
            existing_rfid = User_iot.query.filter_by(rfid=new_rfid).first()
            if existing_rfid and existing_rfid.id != user_id:
                return jsonify(msg="Este RFID ya pertenece a otro usuario"), 400


    if "huella_id" in data:
            huella_id = data.get("huella_id")
            if huella_id is not None:
                try:
                    user.huella_id = int(huella_id)
                except:
                    return jsonify(msg="huella_id debe ser un número entero"), 400
    user.username = data.get("username", user.username)
    user.nombre = data.get("nombre", user.nombre)
    user.apellido = data.get("apellido", user.apellido)
    user.genero = data.get("genero", user.genero)
    user.fecha_nacimiento = parse_date(data.get("fecha_nacimiento")) or user.fecha_nacimiento
    user.fecha_contrato = parse_date(data.get("fecha_contrato")) or user.fecha_contrato
    user.area_trabajo = data.get("area_trabajo", user.area_trabajo)
    user.rfid = data.get("rfid", user.rfid)

    if "password" in data:
        user.set_password(data["password"])

    db.session.commit()
    return jsonify(msg="Usuario actualizado"), 200



@user_bp.route("/<int:user_id>", methods=["DELETE"])
@jwt_required()
@admin_required
def delete_user(user_id):
    user = User_iot.query.get_or_404(user_id)

    if user.is_admin:
        admins = User_iot.query.filter_by(is_admin=True).count()
        if admins <= 1:
            return jsonify(msg="No se puede eliminar el último administrador"), 400

    db.session.delete(user)
    db.session.commit()
    return jsonify(msg="Usuario eliminado"), 200


@user_bp.route("/assign_rfid/<int:user_id>", methods=["PUT"])
@jwt_required()
@admin_required
def assign_rfid(user_id):
    user = User_iot.query.get_or_404(user_id)
    data = request.get_json() or {}

    rfid = data.get("rfid")
    if not rfid:
        return jsonify(msg="rfid es requerido"), 400

    if User_iot.query.filter(User_iot.rfid == rfid, User_iot.id != user_id).first():
        return jsonify(msg="El RFID ya está asignado a otro usuario"), 400

    user.rfid = rfid
    db.session.commit()

    return jsonify(msg="RFID asignado correctamente"), 200

@user_bp.route("/huella/register", methods=["POST"])
def register_huella():
    data = request.get_json() or {}

    if "huella_id" not in data:
        return jsonify(msg="Se requiere huella_id"), 400

    try:
        hid = int(data["huella_id"])
    except:
        return jsonify(msg="huella_id debe ser entero"), 400


    if Huella.query.get(hid):
        return jsonify(msg="Esta huella ya está registrada"), 400

    nueva = Huella(id=hid)
    db.session.add(nueva)
    db.session.commit()

    return jsonify(msg="Huella registrada correctamente", huella_id=hid), 201
