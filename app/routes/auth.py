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

    if validate_user_credentials(user, password):

        role_name = user.role.name if user.role else "empleado"

        access_token = create_access_token(
            identity=str(user.id),  
            additional_claims={
                "username": user.username,
                "role": role_name
            }
        )

        user_data = {
            "username": user.username,
            "role": role_name,
            "nombre": user.nombre, 
            "apellido": user.apellido,
            "area_trabajo": user.area_trabajo  # <-- FIX
        }

        return jsonify(
            access_token=access_token,
            user=user_data
        ), 200

    return jsonify({"msg": "Bad username or password"}), 401




@bp.route('/protected', methods=['GET'])
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    return jsonify(logged_in_as=current_user), 200
