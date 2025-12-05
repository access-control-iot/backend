from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt, jwt_required, get_jwt_identity
from datetime import datetime
from functools import wraps
import base64
from flask_cors import cross_origin
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

@user_bp.route("/huella/sync-all", methods=["GET"])
def sync_all_fingerprints():

    try:
 
        huellas_data = db.session.query(
            Huella.id,
            Huella.template,
            User_iot.id.label("user_id"),
            User_iot.nombre,
            User_iot.apellido
        ).join(
            User_iot, User_iot.huella_id == Huella.id
        ).filter(
            User_iot.huella_id.isnot(None)
        ).all()
        
        huellas_list = []
        for h in huellas_data:
            if h.template and len(h.template) > 0:
                huellas_list.append({
                    "huella_id": h.id,
                    "user_id": h.user_id,
                    "nombre": h.nombre,
                    "apellido": h.apellido,
                    "template": base64.b64encode(h.template).decode() if h.template else None
                })
        
        return jsonify({
            "success": True,
            "huellas": huellas_list,
            "total": len(huellas_list),
            "message": f"Se encontraron {len(huellas_list)} huellas registradas"
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Error al obtener huellas: {str(e)}"
        }), 500


@user_bp.route("/huella/check/<int:huella_id>", methods=["GET"])
def check_fingerprint(huella_id):

    huella = Huella.query.get(huella_id)
    
    if not huella:
        return jsonify({
            "success": False,
            "exists": False,
            "message": f"Huella ID {huella_id} no encontrada en base de datos"
        }), 404
    
    user = User_iot.query.filter_by(huella_id=huella_id).first()
    
    return jsonify({
        "success": True,
        "exists": True,
        "huella_id": huella_id,
        "has_template": bool(huella.template and len(huella.template) > 0),
        "assigned_to": {
            "user_id": user.id if user else None,
            "nombre": user.nombre if user else None,
            "apellido": user.apellido if user else None
        } if user else None
    }), 200

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
        .filter(User_iot.is_active == True) 
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
@user_bp.route("/all", methods=["GET"])
@jwt_required()
@admin_required
def list_all_users():
  
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    users = User_iot.query.paginate(page=page, per_page=per_page, error_out=False)
    
    users_data = [
        {
            "id": u.id,
            "username": u.username,
            "nombre": u.nombre,
            "apellido": u.apellido,
            "role": u.role.name if u.role else None,
            "area_trabajo": u.area_trabajo,
            "huella_id": u.huella_id,
            "rfid": u.rfid,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "updated_at": u.updated_at.isoformat() if u.updated_at else None
        }
        for u in users.items
    ]
    
    return jsonify({
        "users": users_data,
        "total": users.total,
        "pages": users.pages,
        "current_page": page
    }), 200
@user_bp.route("/huella/assign-id", methods=["POST"])
def assign_huella_id():
    """Asigna un ID de huella disponible a un usuario"""
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    
    if not user_id:
        return jsonify(success=False, message="user_id es requerido"), 400
    
    try:
        user_id = int(user_id)
    except:
        return jsonify(success=False, message="user_id debe ser número entero"), 400
    
    # Verificar que el usuario existe
    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(success=False, message="Usuario no encontrado"), 404
    
    # Verificar si ya tiene huella asignada
    if user.huella_id:
        return jsonify({
            "success": False,
            "message": "Usuario ya tiene huella asignada",
            "huella_id": user.huella_id
        }), 400
    
    # Obtener el siguiente ID disponible
    last_huella = Huella.query.order_by(Huella.id.desc()).first()
    next_id = (last_huella.id + 1) if last_huella else 1
    
    # Verificar que no esté en uso
    while True:
        huella_existente = Huella.query.get(next_id)
        if not huella_existente:
            break
        next_id += 1
    
    return jsonify({
        "success": True,
        "message": "ID de huella asignado",
        "huella_id": next_id,
        "user_id": user_id
    }), 200
@user_bp.route("/huella/assign-manual", methods=["POST"])
@admin_required
def assign_huella_manual():
    data = request.get_json() or {}
    
    user_id = data.get("user_id")
    huella_id = data.get("huella_id")
    
    if not user_id or not huella_id:
        return jsonify(success=False, message="user_id y huella_id son requeridos"), 400
    
    try:
        user_id = int(user_id)
        huella_id = int(huella_id)
    except ValueError:
        return jsonify(success=False, message="IDs deben ser números enteros"), 400
    
    if huella_id <= 0:
        return jsonify(success=False, message="huella_id debe ser mayor a 0"), 400
    
    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(success=False, message="Usuario no encontrado"), 404
    
    # Verificar si ya existe otro usuario con esta huella
    existing_user = User_iot.query.filter_by(huella_id=huella_id).first()
    if existing_user and existing_user.id != user_id:
        return jsonify(success=False, message="Huella ID ya está asignado a otro usuario"), 400
    
    try:
        # VERIFICAR SI EL REGISTRO DE HUELLA EXISTE
        huella_record = Huella.query.get(huella_id)
        
        # Si no existe, crearlo con un template vacío
        if not huella_record:
            huella_record = Huella(id=huella_id, template=b"")
            db.session.add(huella_record)
            print(f"Created huella record with id={huella_id}")
        
        # Asignar la huella al usuario
        user.huella_id = huella_id
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "ID de huella asignado manualmente",
            "huella_id": huella_id,
            "user_id": user_id,
            "username": user.username,
            "nombre": user.nombre,
            "huella_created": huella_record is not None  # True si se creó nuevo
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": f"Error al asignar huella: {str(e)}"
        }), 500
@user_bp.route("/huella/verify-setup", methods=["POST"])
def verify_fingerprint_setup():
    data = request.get_json() or {}
    
    huella_id = data.get("huella_id")
    user_id = data.get("user_id")
    
    if not huella_id or not user_id:
        return jsonify(success=False, message="huella_id y user_id son requeridos"), 400
    
    try:
        huella_id = int(huella_id)
        user_id = int(user_id)
    except:
        return jsonify(success=False, message="IDs deben ser números enteros"), 400
    user = User_iot.query.get(user_id)
    if not user:
        return jsonify(success=False, message="Usuario no encontrado"), 404

    if user.huella_id != huella_id:
        return jsonify(success=False, message="ID de huella no coincide con usuario"), 400
    huella_record = Huella.query.get(huella_id)
    has_template = bool(huella_record and huella_record.template and len(huella_record.template) > 0)
    
    return jsonify({
        "success": True,
        "user_id": user_id,
        "huella_id": huella_id,
        "has_template": has_template,
        "message": "Huella registrada en sistema" if has_template else "Huella asignada pero sin template"
    }), 200


@user_bp.route("/rfid/verify", methods=["POST"])
def verify_rfid():
    data = request.get_json() or {}
    
    rfid = data.get("rfid")
    
    if not rfid:
        return jsonify(success=False, message="RFID requerido"), 400

    user = User_iot.query.filter_by(rfid=rfid).first()
    
    if user:
        return jsonify({
            "success": False,
            "message": f"RFID ya asignado a {user.nombre} {user.apellido}",
            "assigned_to": {
                "id": user.id,
                "nombre": user.nombre,
                "apellido": user.apellido,
                "username": user.username
            }
        }), 200
    else:
        return jsonify({
            "success": True,
            "message": "RFID disponible",
            "available": True
        }), 200
@user_bp.route("/<int:user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
  
    try:
        user = User_iot.query.get_or_404(user_id)
        claims = get_jwt()
        current_user_id = get_jwt_identity()
        if claims.get("role") != "admin" and current_user_id != user_id:
            return jsonify(msg="No autorizado"), 403
        user_data = {
            "id": user.id,
            "username": user.username,
            "nombre": user.nombre,
            "apellido": user.apellido,
            "genero": user.genero,
            "fecha_nacimiento": user.fecha_nacimiento.isoformat() if user.fecha_nacimiento else None,
            "fecha_contrato": user.fecha_contrato.isoformat() if user.fecha_contrato else None,
            "area_trabajo": user.area_trabajo,
            "huella_id": user.huella_id,
            "rfid": user.rfid,
            "role": user.role.name if user.role else None,
            "is_admin": user.is_admin
        }
        
        return jsonify(user_data), 200
        
    except Exception as e:
        return jsonify(msg=f"Error al obtener usuario: {str(e)}"), 500
    

@user_bp.route("/<int:user_id>/suspend", methods=["POST"])
@jwt_required()
@admin_required
def suspend_user(user_id):
    """Suspender un usuario (desactivar)"""
    user = User_iot.query.get_or_404(user_id)
    
    # Verificar si es el último administrador
    if user.is_admin:
        admins = User_iot.query.filter_by(is_admin=True, is_active=True).count()
        if admins <= 1:
            return jsonify(msg="No se puede suspender al último administrador activo"), 400
    
    user.is_active = False
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Usuario suspendido correctamente",
        "user_id": user.id,
        "username": user.username,
        "is_active": user.is_active
    }), 200

@user_bp.route("/<int:user_id>/activate", methods=["POST"])
@jwt_required()
@admin_required
def activate_user(user_id):
    """Activar un usuario suspendido"""
    user = User_iot.query.get_or_404(user_id)
    
    user.is_active = True
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Usuario activado correctamente",
        "user_id": user.id,
        "username": user.username,
        "is_active": user.is_active
    }), 200

@user_bp.route("/<int:user_id>/status", methods=["GET"])
@jwt_required()
@admin_required
def get_user_status(user_id):
    """Obtener estado del usuario"""
    user = User_iot.query.get_or_404(user_id)
    
    return jsonify({
        "id": user.id,
        "username": user.username,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "is_active": user.is_active,
        "role": user.role.name if user.role else None
    }), 200

@user_bp.route("/active", methods=["GET"])
@jwt_required()
@admin_required
def list_active_users():
    """Listar usuarios activos"""
    users = User_iot.query.filter_by(is_active=True).all()
    
    users_data = [
        {
            "id": u.id,
            "username": u.username,
            "nombre": u.nombre,
            "apellido": u.apellido,
            "role": u.role.name if u.role else None,
            "area_trabajo": u.area_trabajo,
            "huella_id": u.huella_id,
            "rfid": u.rfid,
            "is_active": u.is_active
        }
        for u in users
    ]
    
    return jsonify({
        "users": users_data,
        "total": len(users_data)
    }), 200

@user_bp.route("/suspended", methods=["GET"])
@jwt_required()
@admin_required
def list_suspended_users():
    """Listar usuarios suspendidos"""
    users = User_iot.query.filter_by(is_active=False).all()
    
    users_data = [
        {
            "id": u.id,
            "username": u.username,
            "nombre": u.nombre,
            "apellido": u.apellido,
            "role": u.role.name if u.role else None,
            "area_trabajo": u.area_trabajo,
            "huella_id": u.huella_id,
            "rfid": u.rfid,
            "is_active": u.is_active,
            "suspended_since": u.updated_at.isoformat() if u.updated_at else None
        }
        for u in users
    ]
    
    return jsonify({
        "users": users_data,
        "total": len(users_data)
    }), 200

@user_bp.route("/<int:user_id>/update-complete", methods=["PUT"])
@jwt_required()
@admin_required
def update_user_complete(user_id):

    user = User_iot.query.get_or_404(user_id)
    data = request.get_json() or {}
    
    print(f"Actualizando usuario {user_id} con datos:", data)
    

    if "nombre" in data:
        user.nombre = data["nombre"]
    if "apellido" in data:
        user.apellido = data["apellido"]
    if "genero" in data:
        user.genero = data["genero"]
    if "fecha_nacimiento" in data:
        user.fecha_nacimiento = parse_date(data["fecha_nacimiento"])
    if "fecha_contrato" in data:
        user.fecha_contrato = parse_date(data["fecha_contrato"])
    if "area_trabajo" in data:
        user.area_trabajo = data["area_trabajo"]
    
    # 2. Actualizar username
    if "username" in data:
        new_username = data["username"]
        # Verificar si el username ya existe para otro usuario
        existing = User_iot.query.filter_by(username=new_username).first()
        if existing and existing.id != user_id:
            return jsonify({
                "success": False,
                "msg": f"El username '{new_username}' ya está en uso por otro usuario"
            }), 400
        user.username = new_username
    
    # 3. Actualizar RFID con validación
    if "rfid" in data:
        new_rfid = data["rfid"]
        if new_rfid:  # Si se quiere asignar un nuevo RFID
            # Si es None, vacío o "null", no hacer nada
            if new_rfid != "null" and new_rfid != "":
                existing = User_iot.query.filter_by(rfid=new_rfid).first()
                if existing and existing.id != user_id:
                    return jsonify({
                        "success": False,
                        "msg": "Este RFID ya pertenece a otro usuario"
                    }), 400
                user.rfid = new_rfid
                print(f"RFID actualizado: {new_rfid} para usuario {user_id}")
        else:  # Si se quiere eliminar el RFID
            user.rfid = None
            print(f"RFID eliminado para usuario {user_id}")
        
    # 4. Actualizar huella con validación
    if "huella_id" in data:
        new_huella_id = data["huella_id"]
        if new_huella_id is not None and new_huella_id != "" and new_huella_id != "null":
            try:
                new_huella_id = int(new_huella_id)
                if new_huella_id > 0:
                    # Verificar si ya está asignada a otro usuario
                    existing = User_iot.query.filter_by(huella_id=new_huella_id).first()
                    if existing and existing.id != user_id:
                        return jsonify({
                            "success": False,
                            "msg": "Esta huella ya está asignada a otro usuario"
                        }), 400
                    
                    # Verificar si existe el registro de huella
                    huella_record = Huella.query.get(new_huella_id)
                    if not huella_record:
                        # Crear registro de huella vacío si no existe
                        huella_record = Huella(id=new_huella_id, template=b"")
                        db.session.add(huella_record)
                        print(f"Creado registro de huella vacío: {new_huella_id}")
                    
                    user.huella_id = new_huella_id
                    print(f"Asignada huella {new_huella_id} a usuario {user_id}")
            except ValueError:
                # Si no es un número válido, eliminar asignación
                user.huella_id = None
        else:  # Eliminar asignación de huella
            user.huella_id = None
    
    # 5. Actualizar contraseña si se proporciona
    if "password" in data and data["password"]:
        user.set_password(data["password"])
        print(f"Contraseña actualizada para usuario {user_id}")
    
    # 6. Actualizar rol si se proporciona
    if "role" in data:
        role_name = data["role"]
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            return jsonify({
                "success": False,
                "msg": f"Rol inválido: {role_name}"
            }), 400
        
        # Validar que no se suspenda al último administrador
        if user.is_admin and role_name != "admin":
            admins = User_iot.query.filter_by(is_admin=True, is_active=True).count()
            if admins <= 1:
                return jsonify({
                    "success": False,
                    "msg": "No se puede cambiar el rol del último administrador activo"
                }), 400
        
        user.role = role
        print(f"Rol actualizado a {role_name} para usuario {user_id}")
    
    try:
        db.session.commit()
        print(f"Usuario {user_id} actualizado exitosamente")
        
        # Obtener datos actualizados para respuesta
        user_actualizado = User_iot.query.get(user_id)
        
        return jsonify({
            "success": True,
            "message": "Usuario actualizado completamente",
            "user": {
                "id": user_actualizado.id,
                "username": user_actualizado.username,
                "nombre": user_actualizado.nombre,
                "apellido": user_actualizado.apellido,
                "genero": user_actualizado.genero,
                "fecha_nacimiento": user_actualizado.fecha_nacimiento.isoformat() if user_actualizado.fecha_nacimiento else None,
                "fecha_contrato": user_actualizado.fecha_contrato.isoformat() if user_actualizado.fecha_contrato else None,
                "area_trabajo": user_actualizado.area_trabajo,
                "huella_id": user_actualizado.huella_id,
                "rfid": user_actualizado.rfid,
                "role": user_actualizado.role.name if user_actualizado.role else None,
                "is_active": user_actualizado.is_active
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Error al actualizar usuario: {str(e)}")
        return jsonify({
            "success": False,
            "msg": f"Error al actualizar usuario: {str(e)}"
        }), 500

@user_bp.route("/<int:user_id>/remove-huella", methods=["PUT"])
@jwt_required()
@admin_required
def remove_user_huella(user_id):
    """Eliminar la asignación de huella de un usuario"""
    user = User_iot.query.get_or_404(user_id)
    
    user.huella_id = None
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Huella desasignada correctamente",
        "user_id": user.id,
        "huella_id": None
    }), 200

@user_bp.route("/<int:user_id>/remove-rfid", methods=["PUT"])
@jwt_required()
@admin_required
def remove_user_rfid(user_id):
    """Eliminar la asignación de RFID de un usuario"""
    user = User_iot.query.get_or_404(user_id)
    
    user.rfid = None
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "RFID desasignado correctamente",
        "user_id": user.id,
        "rfid": None
    }), 200

@user_bp.route("/bulk-suspend", methods=["POST"])
@jwt_required()
@admin_required
def bulk_suspend_users():
    """Suspender múltiples usuarios a la vez"""
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    
    if not user_ids:
        return jsonify(msg="Se requiere lista de user_ids"), 400
    
    suspended = []
    failed = []
    
    for user_id in user_ids:
        user = User_iot.query.get(user_id)
        if user:
            # Verificar si es el último administrador
            if user.is_admin:
                admins = User_iot.query.filter_by(is_admin=True, is_active=True).count()
                if admins <= 1:
                    failed.append({
                        "user_id": user_id,
                        "reason": "Es el último administrador activo"
                    })
                    continue
            
            user.is_active = False
            suspended.append(user_id)
        else:
            failed.append({
                "user_id": user_id,
                "reason": "Usuario no encontrado"
            })
    
    if suspended:
        db.session.commit()
    
    return jsonify({
        "success": True,
        "message": f"{len(suspended)} usuarios suspendidos, {len(failed)} fallidos",
        "suspended": suspended,
        "failed": failed
    }), 200

@user_bp.route("/bulk-activate", methods=["POST"])
@jwt_required()
@admin_required
def bulk_activate_users():
    """Activar múltiples usuarios a la vez"""
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    
    if not user_ids:
        return jsonify(msg="Se requiere lista de user_ids"), 400
    
    activated = []
    failed = []
    
    for user_id in user_ids:
        user = User_iot.query.get(user_id)
        if user:
            user.is_active = True
            activated.append(user_id)
        else:
            failed.append({
                "user_id": user_id,
                "reason": "Usuario no encontrado"
            })
    
    if activated:
        db.session.commit()
    
    return jsonify({
        "success": True,
        "message": f"{len(activated)} usuarios activados, {len(failed)} fallidos",
        "activated": activated,
        "failed": failed
    }), 200
# En user.py, busca las funciones de huella y añade versiones públicas SIN @jwt_required()

@users_bp.route('/huella/public/register', methods=['POST'])
def public_register_fingerprint():
    """Endpoint público para que ESP32 confirme registro de huella"""
    try:
        data = request.get_json() or {}
        print(f"[PUBLIC REGISTER] Datos recibidos: {data}")
        
        huella_id = data.get('huella_id')
        user_id = data.get('user_id')
        
        if not huella_id:
            return jsonify(success=False, message="huella_id es requerido"), 400
        
        from app.models import Huella, User_iot
        from app import db
        
        # PASO 1: Primero crear/verificar el registro en la tabla Huella
        huella_existente = Huella.query.get(huella_id)
        
        if not huella_existente:
            # Crear registro en Huella (template vacío inicialmente)
            nueva_huella = Huella(id=huella_id, template=b"registered")
            db.session.add(nueva_huella)
            db.session.flush()  # Para obtener el ID sin hacer commit
            print(f"[PUBLIC REGISTER] Registro huella {huella_id} creado en tabla Huella")
        
        # PASO 2: Asignar al usuario si existe user_id
        if user_id:
            usuario = User_iot.query.get(user_id)
            if usuario:
                # Si el usuario ya tiene otra huella asignada, primero limpiar
                if usuario.huella_id and usuario.huella_id != huella_id:
                    print(f"[PUBLIC REGISTER] Usuario {user_id} tenía huella {usuario.huella_id}, cambiando a {huella_id}")
                
                usuario.huella_id = huella_id
                usuario.updated_at = datetime.now()
                db.session.add(usuario)
        
        # PASO 3: Hacer commit de todos los cambios
        db.session.commit()
        
        print(f"[PUBLIC REGISTER] ¡Éxito! Huella {huella_id} registrada para usuario {user_id}")
        
        return jsonify({
            "success": True,
            "message": f"Huella {huella_id} registrada exitosamente",
            "huella_id": huella_id,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"[PUBLIC REGISTER ERROR] {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}",
            "huella_id": data.get('huella_id')
        }), 500
@user_bp.route("/huella/public/check/<int:huella_id>", methods=["GET"])
@cross_origin()
def check_fingerprint_public(huella_id):
    """Verificar huella públicamente"""
    huella = Huella.query.get(huella_id)
    
    if not huella:
        return jsonify({
            "success": True,  # Cambiado a True porque es normal que no exista
            "exists": False,
            "message": f"Huella ID {huella_id} no encontrada"
        }), 200  # Cambiado a 200 para que ESP32 no reciba error
    
    user = User_iot.query.filter_by(huella_id=huella_id).first()
    
    return jsonify({
        "success": True,
        "exists": True,
        "huella_id": huella_id,
        "has_template": bool(huella.template and len(huella.template) > 0),
        "template_size": len(huella.template) if huella.template else 0,
        "assigned_to": {
            "user_id": user.id if user else None,
            "nombre": user.nombre if user else None
        } if user else None
    }), 200

@user_bp.route("/huella/public/confirm", methods=["POST"])
@cross_origin()
def confirm_huella_public():
    """Confirmar registro de huella públicamente"""
    data = request.get_json() or {}
    
    huella_id = data.get("huella_id")
    user_id = data.get("user_id")
    
    if not huella_id:
        return jsonify(success=False, message="huella_id requerido"), 400
    
    try:
        huella_id = int(huella_id)
    except:
        return jsonify(success=False, message="huella_id debe ser número entero"), 400
    
    # Verificar que el registro de huella existe
    huella_record = Huella.query.get(huella_id)
    if not huella_record:
        return jsonify(success=False, message="Registro de huella no encontrado"), 404
    
    # Si se proporciona user_id, asignar al usuario
    if user_id:
        try:
            user_id = int(user_id)
            user = User_iot.query.get(user_id)
            if not user:
                return jsonify(success=False, message="Usuario no encontrado"), 404
            
            # Verificar si ya está asignada a otro usuario
            existing_user = User_iot.query.filter_by(huella_id=huella_id).first()
            if existing_user and existing_user.id != user_id:
                return jsonify(success=False, 
                              message="Huella ya está asignada a otro usuario"), 400
            
            user.huella_id = huella_id
            
        except Exception as e:
            print(f"Error asignando huella a usuario: {str(e)}")
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Registro de huella confirmado",
        "huella_id": huella_id,
        "user_id": user_id,
        "has_template": bool(huella_record.template and len(huella_record.template) > 0)
    }), 200