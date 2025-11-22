from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
jwt = JWTManager()
migrate = Migrate()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    from app.routes import auth_bp, access_bp, attendance_bp, user_bp, schedule_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(access_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(schedule_bp)
    
    print("\n=== ROUTES LOADED ===")
    for rule in app.url_map.iter_rules():
        print(rule)
    print("=====================\n")

    return app
