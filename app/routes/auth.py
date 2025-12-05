# app/routes/auth.py
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity
from werkzeug.security import check_password_hash
from datetime import timedelta
import logging

from app import db
from app.models import User_iot, UserRoleEnum

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    """Endpoint de autenticación de usuarios"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'msg': 'No se proporcionaron datos'}), 400
        
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'msg': 'Se requiere nombre de usuario y contraseña'}), 400
        
        logger.info(f"Intento de login para usuario: {username}")
        
        # Buscar usuario por username
        user = User_iot.query.filter_by(username=username).first()
        
        if not user:
            logger.warning(f"Usuario no encontrado: {username}")
            return jsonify({'msg': 'Usuario o contraseña incorrectos'}), 401
        
        # Verificar si el usuario está activo - CORREGIDO: usar is_active
        if not user.is_active:
            logger.warning(f"Usuario inactivo: {username}")
            return jsonify({'msg': 'Cuenta inactiva. Contacte al administrador.'}), 401
        
        # Verificar contraseña
        if not check_password_hash(user.password_hash, password):
            logger.warning(f"Contraseña incorrecta para usuario: {username}")
            return jsonify({'msg': 'Usuario o contraseña incorrectos'}), 401
        
        # Crear claims para el token JWT
        additional_claims = {
            'id': user.id,
            'role': user.role.name if user.role else 'empleado',  # Usar role.name
            'nombre': user.nombre,
            'apellido': user.apellido,
            'username': user.username
        }
        
        # Crear tokens de acceso y refresh
        access_token = create_access_token(
            identity=user.id,
            additional_claims=additional_claims,
            expires_delta=timedelta(hours=24)
        )
        
        refresh_token = create_refresh_token(
            identity=user.id,
            additional_claims=additional_claims
        )
        
        logger.info(f"Login exitoso para usuario: {username} (rol: {additional_claims['role']})")
        
        return jsonify({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user': {
                'id': user.id,
                'username': user.username,
                'nombre': user.nombre,
                'apellido': user.apellido,
                'role': user.role.name if user.role else 'empleado',
                'is_active': user.is_active,
                'area_trabajo': user.area_trabajo,
                'genero': user.genero,
                'rfid': user.rfid,
                'huella_id': user.huella_id
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error en login: {str(e)}", exc_info=True)
        return jsonify({'msg': 'Error interno del servidor'}), 500


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refrescar token de acceso"""
    try:
        current_user_id = get_jwt_identity()
        user = User_iot.query.get(current_user_id)
        
        if not user or not user.is_active:
            return jsonify({'msg': 'Usuario no encontrado o inactivo'}), 401
        
        # Crear nuevos claims
        additional_claims = {
            'id': user.id,
            'role': user.role.name if user.role else 'empleado',
            'nombre': user.nombre,
            'apellido': user.apellido,
            'username': user.username
        }
        
        new_access_token = create_access_token(
            identity=current_user_id,
            additional_claims=additional_claims,
            expires_delta=timedelta(hours=24)
        )
        
        return jsonify({
            'access_token': new_access_token,
            'user': {
                'id': user.id,
                'username': user.username,
                'nombre': user.nombre,
                'apellido': user.apellido,
                'role': user.role.name if user.role else 'empleado',
                'is_active': user.is_active
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error en refresh token: {str(e)}")
        return jsonify({'msg': 'Error al refrescar token'}), 500


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Obtener información del usuario actual"""
    try:
        current_user_id = get_jwt_identity()
        user = User_iot.query.get(current_user_id)
        
        if not user:
            return jsonify({'msg': 'Usuario no encontrado'}), 404
        
        return jsonify({
            'id': user.id,
            'username': user.username,
            'nombre': user.nombre,
            'apellido': user.apellido,
            'role': user.role.name if user.role else 'empleado',
            'is_active': user.is_active,
            'area_trabajo': user.area_trabajo,
            'genero': user.genero,
            'fecha_nacimiento': user.fecha_nacimiento.isoformat() if user.fecha_nacimiento else None,
            'fecha_contrato': user.fecha_contrato.isoformat() if user.fecha_contrato else None,
            'rfid': user.rfid,
            'huella_id': user.huella_id,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'updated_at': user.updated_at.isoformat() if user.updated_at else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo usuario actual: {str(e)}")
        return jsonify({'msg': 'Error interno del servidor'}), 500


@auth_bp.route('/change-password', methods=['POST'])
@jwt_required()
def change_password():
    """Cambiar contraseña del usuario actual"""
    try:
        current_user_id = get_jwt_identity()
        user = User_iot.query.get(current_user_id)
        
        if not user:
            return jsonify({'msg': 'Usuario no encontrado'}), 404
        
        data = request.get_json()
        if not data:
            return jsonify({'msg': 'No se proporcionaron datos'}), 400
        
        current_password = data.get('current_password')
        new_password = data.get('new_password')
        
        if not current_password or not new_password:
            return jsonify({'msg': 'Se requiere contraseña actual y nueva contraseña'}), 400
        
        # Verificar contraseña actual
        if not check_password_hash(user.password_hash, current_password):
            return jsonify({'msg': 'Contraseña actual incorrecta'}), 401
        
        # Cambiar contraseña
        user.set_password(new_password)
        db.session.commit()
        
        logger.info(f"Contraseña cambiada para usuario: {user.username}")
        
        return jsonify({'msg': 'Contraseña cambiada exitosamente'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error cambiando contraseña: {str(e)}")
        return jsonify({'msg': 'Error interno del servidor'}), 500


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Endpoint de logout (el cliente debe eliminar los tokens)"""
    # En JWT, el logout se maneja del lado del cliente eliminando los tokens
    return jsonify({'msg': 'Logout exitoso. Elimine los tokens del cliente.'}), 200
