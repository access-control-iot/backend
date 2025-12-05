from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app.models import User_iot
from app.services.jwt_service import generate_token, decode_token
from app.utils.helpers import validate_user_credentials
from app import db
bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if User_iot.query.filter_by(username=username).first():
        return jsonify({"msg": "User already exists"}), 400

    new_user = User_iot(username=username)
    new_user.set_password(password)  

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"msg": "User created successfully"}), 201


@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    user = User_iot.query.filter_by(username=username).first()

    if not user:
        return jsonify({"msg": "Usuario no encontrado"}), 401

    # VERIFICAR SI EL USUARIO ESTÁ ACTIVO
    if not user.isActive:
        return jsonify({
            "msg": "Usuario inactivo - No puede iniciar sesión",
            "detail": "Contacte al administrador para reactivar su cuenta"
        }), 403

    if validate_user_credentials(user, password):
        role_name = user.role.name if user.role else "empleado"

        access_token = create_access_token(
            identity=str(user.id),  
            additional_claims={
                "username": user.username,
                "role": role_name,
                "isActive": user.isActive  # Incluir estado en el token
            }
        )

        user_data = {
            "id": user.id,
            "username": user.username,
            "role": role_name,
            "nombre": user.nombre, 
            "apellido": user.apellido,
            "area_trabajo": user.area_trabajo,
            "isActive": user.isActive,
            "hasFingerprint": bool(user.huella_id),  # Si tiene huella registrada
            "hasRFID": bool(user.rfid)  # Si tiene RFID registrado
        }

        return jsonify({
            "access_token": access_token,
            "user": user_data,
            "msg": "Login exitoso"
        }), 200

    return jsonify({"msg": "Bad username or password"}), 401




@bp.route('/protected', methods=['GET'])
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    
    # Obtener el usuario actual desde la base de datos
    user_id = current_user if isinstance(current_user, str) else current_user.get('id')
    user = User_iot.query.get(user_id)
    
    if not user:
        return jsonify({"msg": "Usuario no encontrado"}), 404
    
    # Verificar si sigue activo (por si cambió después de login)
    if not user.isActive:
        return jsonify({
            "msg": "Acceso denegado - Usuario inactivo",
            "detail": "Su cuenta ha sido desactivada"
        }), 403
    
    return jsonify(logged_in_as=current_user), 200


# Opcional: Endpoint para verificar estado de usuario
@bp.route('/check-status', methods=['GET'])
@jwt_required()
def check_user_status():
    current_user = get_jwt_identity()
    
    if isinstance(current_user, dict):
        user_id = current_user.get('id')
    else:
        user_id = current_user
    
    user = User_iot.query.get(user_id)
    
    if not user:
        return jsonify({"msg": "Usuario no encontrado"}), 404
    
    return jsonify({
        "isActive": user.isActive,
        "username": user.username,
        "nombre": user.nombre,
        "apellido": user.apellido,
        "hasFingerprint": bool(user.huella_id),
        "hasRFID": bool(user.rfid),
        "canLogin": user.isActive
    }), 200
