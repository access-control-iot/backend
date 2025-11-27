from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_cors import CORS  
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


    CORS(app) 
    from app.routes.auth import bp as auth_bp
    from app.routes.access import bp as access_bp
    from app.routes.attendance import bp as attendance_bp
    from app.routes.user import user_bp
    from app.routes.schedule import schedule_bp   


    app.register_blueprint(auth_bp)  
    app.register_blueprint(access_bp, url_prefix='/access')  
    app.register_blueprint(attendance_bp)
    app.register_blueprint(user_bp, url_prefix='/users')
    app.register_blueprint(schedule_bp)


    print("\n=== ROUTES LOADED ===")
    for rule in app.url_map.iter_rules():
        print(rule)
    print("=====================\n")

    return app
