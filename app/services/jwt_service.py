# app/services/jwt_service.py
from datetime import datetime, timedelta
import jwt
from flask import current_app

def generate_token(user: dict, expires_days: int = 1):

    expiration = datetime.utcnow() + timedelta(days=expires_days)
    payload = {
        'sub': user, 
        'exp': expiration
    }
    token = jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return token

def decode_token(token: str):
    try:
        payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        return payload.get('sub')
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
