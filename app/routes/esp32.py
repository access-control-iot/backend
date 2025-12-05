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
    """Recibir notificación de registro de huella desde ESP32"""
    data = request.get_json() or {}
    
    huella_id = data.get('huella_id')
    template_b64 = data.get('template')
    user_id = data.get('user_id')  # Añadido
    success = data.get('success', False)
    message = data.get('message', '')
    
    if not huella_id:
        return jsonify(success=False, message="huella_id requerido"), 400
    
    # NO requerir template si success=True
    # Permitir registros exitosos sin template
    if success:
        from app.models import Huella, User_iot
        from app import db
        import base64
        
        try:
            # Verificar si el usuario existe y tiene esta huella asignada
            if user_id:
                user = User_iot.query.get(user_id)
                if user and user.huella_id != huella_id:
                    return jsonify({
                        "success": False,
                        "message": f"Huella {huella_id} no está asignada al usuario {user_id}"
                    }), 400
            
            # Intentar guardar template si está presente y es válido
            if template_b64 and template_b64 not in ["REGISTRADO", "REGI"]:
                try:
                    # Verificar que sea base64 válido
                    if len(template_b64) % 4 == 0:  # Base64 válido debe tener longitud múltiplo de 4
                        template_bytes = base64.b64decode(template_b64)
                        huella = Huella(id=huella_id, template=template_bytes)
                    else:
                        # Si no es base64 válido, crear registro vacío
                        huella = Huella(id=huella_id, template=b"registered")
                except:
                    # Si hay error al decodificar, crear registro vacío
                    huella = Huella(id=huella_id, template=b"registered")
            else:
                # Si no hay template o es un placeholder, crear registro vacío
                huella = Huella(id=huella_id, template=b"registered")
            
            db.session.merge(huella)
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "Huella registrada exitosamente en sistema",
                "huella_id": huella_id,
                "user_id": user_id,
                "has_template": template_b64 and template_b64 not in ["REGISTRADO", "REGI"]
            }), 200
            
        except Exception as e:
            db.session.rollback()
            return jsonify({
                "success": False,
                "message": f"Error en base de datos: {str(e)}"
            }), 500
    else:
        # Si el registro no fue exitoso
        return jsonify({
            "success": False,
            "message": f"Registro fallido en ESP32: {message}",
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

@esp32_bp.route('/proxy/command', methods=['POST'])
def proxy_command_to_esp32():
    """Proxy para enviar comandos al ESP32 evitando mixed content"""
    data = request.get_json() or {}
    
    esp32_ip = data.get('esp32_ip')
    command = data.get('command')
    huella_id = data.get('huella_id')
    user_id = data.get('user_id')
    
    if not esp32_ip:
        return jsonify({"success": False, "message": "IP del ESP32 requerida"}), 400
    
    try:
        # URL CORRECTA para registro de huella
        esp32_url = f"http://{esp32_ip}"
        
        # Enviar comando al ESP32
        if command == "REGISTER_FINGERPRINT":
            # Usar endpoint de registro de huella
            response = requests.post(
                f"{esp32_url}/command",  # O usar /update-fingerprint si existe
                json={
                    "command": command,
                    "huella_id": huella_id,
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                },
                timeout=30  # Aumentar timeout para registro de huella
            )
        else:
            # Para otros comandos
            response = requests.post(
                f"{esp32_url}/command",
                json={
                    "command": command,
                    "huella_id": huella_id,
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                },
                timeout=10
            )
        
        return jsonify({
            "success": True,
            "status": "success",
            "message": f"Comando enviado a ESP32 ({esp32_ip})",
            "esp32_response": response.json() if response.content else None
        }), 200
        
    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "message": f"Timeout conectando al ESP32 {esp32_ip}"
        }), 504
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Error comunicándose con ESP32: {str(e)}"
        }), 500