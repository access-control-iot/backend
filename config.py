import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'jwt_secret'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt_secret_key'

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql+psycopg2://postgres:Sebastianalonso19@localhost:5432/asistencia_iot'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEBUG = os.environ.get('DEBUG', 'False') == 'True'
    PROPAGATE_EXCEPTIONS = True

    JWT_ALGORITHM = 'HS256'  
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1) 
