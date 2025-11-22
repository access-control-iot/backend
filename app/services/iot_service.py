# app/services/iot_service.py
from flask import jsonify
from datetime import datetime
from app import db
from app.models import User, AccessLog, AccessStatusEnum, Attendance

class IoTService:

    def __init__(self):
        pass

    def log_rfid_attempt(self, rfid, success, user_id=None, reason=None):

        log = AccessLog(
            user_id=user_id,
            timestamp=datetime.utcnow(),
            sensor_type='RFID',
            status=AccessStatusEnum.Permitido if success else AccessStatusEnum.Denegado,
            rfid=rfid,
            reason=reason
        )
        db.session.add(log)
        db.session.commit()

        if success and user_id:
            self._register_attendance(user_id)

        return jsonify({
            "message": "RFID access attempt logged",
            "user_id": user_id,
            "success": success,
            "reason": reason
        })

    def log_fingerprint_attempt(self, user_id=None, success=False, reason=None):
  
        log = AccessLog(
            user_id=user_id,
            timestamp=datetime.utcnow(),
            sensor_type='Huella',
            status=AccessStatusEnum.Permitido if success else AccessStatusEnum.Denegado,
            reason=reason
        )
        db.session.add(log)
        db.session.commit()

        if success and user_id:
            self._register_attendance(user_id)

        return jsonify({
            "message": "Fingerprint access attempt logged",
            "user_id": user_id,
            "success": success,
            "reason": reason
        })

    def _register_attendance(self, user_id):

        now = datetime.utcnow()
        today = now.date()

    
        last_attendance = Attendance.query.filter_by(user_id=user_id) \
                            .order_by(Attendance.entry_time.desc()).first()

        
        if not last_attendance:
            new_att = Attendance(user_id=user_id, entry_time=now)
            db.session.add(new_att)
            db.session.commit()
            return

    
        if last_attendance.entry_time.date() != today:
            new_att = Attendance(user_id=user_id, entry_time=now)
            db.session.add(new_att)
            db.session.commit()
            return


        if last_attendance.entry_time.date() == today and not last_attendance.exit_time:
            last_attendance.exit_time = now
            db.session.commit()
            return

    
        new_att = Attendance(user_id=user_id, entry_time=now)
        db.session.add(new_att)
        db.session.commit()

