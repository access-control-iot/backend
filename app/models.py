import enum
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Text
from app import db

from sqlalchemy import Index

from werkzeug.security import generate_password_hash, check_password_hash

class AccessStatusEnum(enum.Enum):
    Permitido = "Permitido"
    Denegado = "Denegado"
    Tarde = "Tarde"
    Presente = "Presente"
    FueraHorario = "FueraHorario"

class UserRoleEnum(enum.Enum):
    admin = "admin"
    supervisor = "supervisor"
    empleado = "empleado"
    administrador = "administrador"

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)

class User_iot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.Text, nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    role = db.relationship('Role', backref='users')
    nombre = db.Column(db.String(80), nullable=False)
    apellido = db.Column(db.String(80), nullable=False)
    genero = db.Column(db.String(10))
    fecha_nacimiento = db.Column(db.Date)
    fecha_contrato = db.Column(db.Date)
    area_trabajo = db.Column(db.String(80), index=True)
    huella_id = db.Column(db.Integer, db.ForeignKey('huella.id'), unique=True, nullable=True, index=True)
    huella = db.relationship('Huella', backref='user', uselist=False)
    rfid = db.Column(db.String(64), unique=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def as_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "nombre": self.nombre,
            "apellido": self.apellido,
            "role": self.role.name if self.role else None
        }


class AccessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_iot.id'), nullable=True, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    sensor_type = db.Column(db.String(20)) 
    status = db.Column(db.Enum(AccessStatusEnum, name="access_status_enum"), default=AccessStatusEnum.Permitido)
    rfid = db.Column(db.String(64), nullable=True)
    huella_id = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.String(255), nullable=True)

    user = db.relationship('User_iot', backref='access_logs')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_iot.id'), nullable=False, index=True)
    entry_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    exit_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    estado_entrada = db.Column(db.String(50))

class Huella(db.Model):
    __tablename__ = 'huella'
    id = db.Column(db.Integer, primary_key=True)  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    hora_entrada = db.Column(db.Time, nullable=False)
    tolerancia_entrada = db.Column(db.Integer, default=0) 
    hora_salida = db.Column(db.Time, nullable=False)
    tolerancia_salida = db.Column(db.Integer, default=0)   
    dias = db.Column(db.String(50), nullable=False)        
    tipo = db.Column(db.String(20), nullable=False)       

class UserSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_iot.id'))
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'))
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    schedule = db.relationship("Schedule", backref="user_schedules")

class ScheduleAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user_iot.id'))
    admin_id = db.Column(db.Integer, db.ForeignKey('user_iot.id'))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    change_type = db.Column(db.String(20))  
    details = db.Column(db.Text)
class FailedAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_iot.id'), nullable=True)
    identifier = db.Column(db.String(128))  
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.String(255))

Index('ix_access_user_date', AccessLog.user_id, AccessLog.timestamp)