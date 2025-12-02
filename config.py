import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'jwt_secret'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt_secret_key'

    # URL de base de datos Render (External URL)
    database_url = os.environ.get(
        'DATABASE_URL', 
        'postgresql+psycopg2://asistencia_iot_user:3w7J3jRpH0LNSgL02RIA8CQg1K97lYCG@dpg-d4ivk9h5pdvs73866m6g-a.oregon-postgres.render.com:5432/asistencia_iot'
    )

    # Solo por si acaso, cambiar postgres:// por postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = database_url
    
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {
            "options": "-c timezone=America/Lima"
        }
    }
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = os.environ.get('DEBUG', 'False') == 'True'
    PROPAGATE_EXCEPTIONS = True
    JWT_ALGORITHM = 'HS256'  
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
