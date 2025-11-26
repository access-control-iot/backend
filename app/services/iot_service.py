# app/services/iot_service.py
from flask import jsonify
from datetime import datetime, time
from app import db
from app.models import User_iot, AccessLog, AccessStatusEnum, Attendance, FailedAttempt


class IoTService:

    def __init__(self):
        pass
    def log_fingerprint_attempt(self, huella_id):

        user = User_iot.query.filter_by(huella_id=huella_id).first()

        if not user:
            return self._failed("Huella no registrada", "Huella", huella_id)


        self._log(user.id, "Huella", True, huella_id=huella_id)

        attendance_info = self._register_attendance(user)

        return jsonify({
            "success": True,
            "user_id": user.id,
            "name": user.name,
            "attendance_action": attendance_info["action"],
            "late": attendance_info["late"],
            "open_door": True
        })

    def log_secure_zone_access(self, huella_id, rfid):

        user = User_iot.query.filter_by(huella_id=huella_id).first()

        if not user:
            return self._failed("Huella no registrada", "Huella", huella_id)
        if user.role.name != "admin":
            return self._failed("Usuario no es administrador", "RFID", rfid)

        if user.rfid != rfid:
            return self._failed("RFID incorrecto para este admin", "RFID", rfid)
        self._log(user.id, "ZonaSegura", True, huella_id=huella_id, rfid=rfid)

        return jsonify({
            "success": True,
            "message": "Acceso permitido a zona segura",
            "user_id": user.id,
            "open_door": True,
            "secure_zone": True
        })

    def _register_attendance(self, user):

        now = datetime.utcnow()
        today = now.date()

        entrada_oficial = time(8, 0, 0)
        tolerancia = time(8, 10, 0)

        last = Attendance.query.filter_by(user_id=user.id)\
            .order_by(Attendance.entry_time.desc()).first()

        if not last or last.entry_time.date() != today:

            is_late = now.time() > tolerancia

            new_att = Attendance(
                user_id=user.id,
                entry_time=now,
                late=is_late
            )
            db.session.add(new_att)
            db.session.commit()

            return {
                "action": "entrada",
                "late": is_late
            }

        if last.exit_time is None:
            last.exit_time = now
            db.session.commit()

            return {
                "action": "salida",
                "late": last.late
            }
        new_att = Attendance(user_id=user.id, entry_time=now, late=False)
        db.session.add(new_att)
        db.session.commit()

        return {
            "action": "entrada",
            "late": False
        }
    def _log(self, user_id, sensor_type, success, huella_id=None, rfid=None, reason=None):
        log = AccessLog(
            user_id=user_id,
            timestamp=datetime.utcnow(),
            sensor_type=sensor_type,
            status=AccessStatusEnum.Permitido if success else AccessStatusEnum.Denegado,
            huella_id=huella_id,
            rfid=rfid,
            reason=reason
        )
        db.session.add(log)
        db.session.commit()

    def _failed(self, reason, sensor_type, identifier):

        failed = FailedAttempt(identifier=identifier, reason=reason)
        db.session.add(failed)
        db.session.commit()

        last_3 = FailedAttempt.query.filter_by(identifier=identifier)\
            .order_by(FailedAttempt.timestamp.desc()).limit(3).count()

        alarm = last_3 >= 3

        return jsonify({
            "success": False,
            "reason": reason,
            "open_door": False,
            "trigger_alarm": alarm
        })
