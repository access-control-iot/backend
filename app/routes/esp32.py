# app/routes/esp32.py
from flask import Blueprint, request, jsonify
import requests
from datetime import datetime

esp32_bp = Blueprint('esp32', __name__, url_prefix='/esp32')


@esp32_bp.route('/command', methods=['POST'])
def send_command_to_esp32():

    data = request.get_json() or {}
    
    command = data.get('command')
    huella_id = data.get('huella_id')
    rfid = data.get('rfid')
    user_id = data.get('user_id')
    

    esp32_ip = data.get('esp32_ip')
    
    if not esp32_ip:
        return jsonify({
            "success": False,
            "message": "IP del ESP32 no especificada"
        }), 400
    
    esp32_url = f"http://{esp32_ip}"
    

    if command == 'REGISTER_FINGERPRINT':
        if not huella_id:
            return jsonify({
                "success": False,
                "message": "huella_id requerido para registro de huella"
            }), 400
        

        try:
           
            return jsonify({
                "success": True,
                "message": f"Comando enviado al ESP32 ({esp32_ip})",
                "command": command,
                "huella_id": huella_id,
                "instructions": "Diríjase al dispositivo ESP32 y siga las instrucciones en pantalla"
            }), 200
            
        except Exception as e:
            return jsonify({
                "success": False,
                "message": f"Error comunicándose con ESP32: {str(e)}"
            }), 500
            
    elif command == 'READ_RFID':

        try:
        
            return jsonify({
                "success": True,
                "message": "Modo lectura RFID activado",
                "command": command,
                "instructions": "Acercar llavero RFID al dispositivo"
            }), 200
        except Exception as e:
            return jsonify({
                "success": False,
                "message": f"Error: {str(e)}"
            }), 500
            
    else:
        return jsonify({
            "success": False,
            "message": f"Comando no soportado: {command}",
            "supported_commands": ["REGISTER_FINGERPRINT", "READ_RFID"]
        }), 400


@esp32_bp.route('/listen-fingerprint', methods=['POST'])
def listen_fingerprint_result():
 
    data = request.get_json() or {}
    
    huella_id = data.get('huella_id')
    template_b64 = data.get('template')
    success = data.get('success', False)
    message = data.get('message', '')
    
    if not huella_id:
        return jsonify(success=False, message="huella_id requerido"), 400
    
    if success and not template_b64:
        return jsonify(success=False, message="template requerido cuando success=True"), 400
    
    if success:
        from app.models import Huella
        from app import db
        import base64
        
        try:
            template_bytes = base64.b64decode(template_b64)
            
            huella = Huella(id=huella_id, template=template_bytes)
            db.session.merge(huella)
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "Template de huella guardado correctamente",
                "huella_id": huella_id
            }), 200
            
        except Exception as e:
            return jsonify({
                "success": False,
                "message": f"Error guardando template: {str(e)}"
            }), 500
    else:
        return jsonify({
            "success": False,
            "message": f"Registro fallido: {message}",
            "huella_id": huella_id
        }), 200


@esp32_bp.route('/listen-rfid', methods=['POST'])
def listen_rfid_result():

    data = request.get_json() or {}
    
    rfid = data.get('rfid')
    user_id = data.get('user_id')  
    
    if not rfid:
        return jsonify(success=False, message="RFID requerido"), 400
    
    from app.models import User_iot
    from app import db
    
    existing_user = User_iot.query.filter_by(rfid=rfid).first()
    
    if existing_user:
        return jsonify({
            "success": False,
            "message": f"RFID ya asignado a {existing_user.nombre} {existing_user.apellido}",
            "assigned_to": {
                "id": existing_user.id,
                "nombre": existing_user.nombre,
                "apellido": existing_user.apellido
            }
        }), 200
    
    if user_id:
        user = User_iot.query.get(user_id)
        if user:
            user.rfid = rfid
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "RFID asignado automáticamente",
                "rfid": rfid,
                "user_id": user_id,
                "nombre": user.nombre,
                "apellido": user.apellido
            }), 200
    
    return jsonify({
        "success": True,
        "message": "RFID leído correctamente",
        "rfid": rfid,
        "available": True,
        "next_step": "Asignar este RFID a un usuario"
    }), 200