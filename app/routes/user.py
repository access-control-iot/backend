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

@user_bp.route("/rfid/register", methods=["POST"])
def register_rfid():
 
    data = request.get_json() or {}
    
    rfid_uid = data.get("rfid")
    user_id = data.get("user_id")
    
    if not rfid_uid or not user_id:
        return jsonify(success=False, message="Se requiere rfid y user_id"), 400
    
    try:
        user_id = int(user_id)
    except:
        return jsonify(success=False, message="user_id debe ser número entero"), 400
    

    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(success=False, message="Usuario no encontrado"), 404
    
   
    existing_user = User_iot.query.filter_by(rfid=rfid_uid).first()
    if existing_user and existing_user.id != user_id:
        return jsonify(success=False, message="RFID ya está asignado a otro usuario"), 400
    
    user.rfid = rfid_uid
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "RFID registrado correctamente",
        "user_id": user_id,
        "rfid": rfid_uid,
        "username": user.username,
        "nombre": user.nombre
    }), 201

@user_bp.route("/huella/register", methods=["POST"])
def register_huella():
    data = request.get_json() or {}

    huella_id = data.get("huella_id")
    template_b64 = data.get("template")

    if not huella_id or not template_b64:
        return jsonify(msg="Se requiere huella_id y template"), 400

    try:
        huella_id = int(huella_id)
    except:
        return jsonify(msg="huella_id debe ser entero"), 400

    template_bytes = base64.b64decode(template_b64)

    huella = Huella(id=huella_id, template=template_bytes)

    db.session.merge(huella)  
    db.session.commit()

    return jsonify(msg="Huella guardada correctamente", huella_id=huella_id), 201

@user_bp.route("/huella/all", methods=["GET"])
def get_all_huellas():
    huellas = Huella.query.all()

    return jsonify([
        {
            "huella_id": h.id,
            "template": base64.b64encode(h.template).decode()
        }
        for h in huellas
    ]), 200

@user_bp.route("/huella/next-id", methods=["GET"])
def get_next_huella_id():

    last_huella = Huella.query.order_by(Huella.id.desc()).first()
    next_id = (last_huella.id + 1) if last_huella else 1
    
    return jsonify({
        "huella_id": next_id,
        "message": "ID disponible para registro"
    }), 200

@user_bp.route("/huella/confirm-register", methods=["POST"])
def confirm_huella_register():
    data = request.get_json() or {}
    
    huella_id = data.get("huella_id")
    user_id = data.get("user_id")
    
    if not huella_id or not user_id:
        return jsonify(success=False, message="huella_id y user_id requeridos"), 400
    
    try:
        huella_id = int(huella_id)
        user_id = int(user_id)
    except:
        return jsonify(success=False, message="IDs deben ser números enteros"), 400
    
    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(success=False, message="Usuario no encontrado"), 404
    
   
    existing_user = User_iot.query.filter_by(huella_id=huella_id).first()
    if existing_user and existing_user.id != user_id:
        return jsonify(success=False, message="Huella ya está asignada a otro usuario"), 400
    
    huella_existente = Huella.query.get(huella_id)
    if not huella_existente:

        huella = Huella(id=huella_id, template=b"registered")
        db.session.add(huella)
    
    user.huella_id = huella_id
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Huella registrada y asociada al usuario",
        "huella_id": huella_id,
        "user_id": user_id,
        "username": user.username
    }), 201

@user_bp.route("/huella/upload-template", methods=["POST"])
def upload_huella_template():
    data = request.get_json() or {}
    
    huella_id = data.get("huella_id")
    template_b64 = data.get("template")
    
    if not huella_id or not template_b64:
        return jsonify(success=False, message="Se requiere huella_id y template"), 400
    
    try:
        huella_id = int(huella_id)
        template_bytes = base64.b64decode(template_b64)
    except Exception as e:
        return jsonify(success=False, message=f"Error en datos: {str(e)}"), 400
    
    huella = Huella(id=huella_id, template=template_bytes)
    db.session.merge(huella)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Template de huella guardado correctamente",
        "huella_id": huella_id
    }), 201

@user_bp.route("/", methods=["GET"])
@jwt_required()
@admin_required
def list_empleados():
    empleados = (
        User_iot.query
        .join(Role)
        .filter(Role.name == "empleado")
        .all()
    )

    users_data = [
        {
            "id": u.id,
            "username": u.username,
            "nombre": u.nombre,
            "apellido": u.apellido,
            "role": u.role.name if u.role else None,
            "area_trabajo": u.area_trabajo,
            "huella_id": u.huella_id,
            "rfid": u.rfid
        }
        for u in empleados
    ]

    return jsonify({
        "users": users_data,
        "total": len(users_data)
    }), 200
@user_bp.route("/huella/assign-id", methods=["POST"])
@jwt_required()
@admin_required
def assign_fingerprint_id():
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    if not user_id:
        return jsonify(success=False, message="user_id es requerido"), 400
    
    try:
        user_id = int(user_id)
    except:
        return jsonify(success=False, message="user_id debe ser número entero"), 400
    

    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(success=False, message="Usuario no encontrado"), 404
    

    last_huella = Huella.query.order_by(Huella.id.desc()).first()
    next_id = (last_huella.id + 1) if last_huella else 1
    
   
    existing_user = User_iot.query.filter_by(huella_id=next_id).first()
    if existing_user:
      
        next_id += 1
        while User_iot.query.filter_by(huella_id=next_id).first():
            next_id += 1
    
    return jsonify({
        "success": True,
        "huella_id": next_id,
        "user_id": user_id,
        "message": "ID de huella asignado correctamente"
    }), 200