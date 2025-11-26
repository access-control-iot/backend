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

    # IMPORTAR BLUEPRINTS
    from app.routes.auth import bp as auth_bp
    from app.routes.access import bp as access_bp
    from app.routes.attendance import bp as attendance_bp
    from app.routes.user import user_bp
    from app.routes.schedule import schedule_bp   

  
    app.register_blueprint(auth_bp)  # si quieres puedes añadir un url_prefix para auth también
    app.register_blueprint(access_bp, url_prefix='/access')  # <- aquí va el cambio
    app.register_blueprint(attendance_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(schedule_bp)


    print("\n=== ROUTES LOADED ===")
    for rule in app.url_map.iter_rules():
        print(rule)
    print("=====================\n")

    return app
