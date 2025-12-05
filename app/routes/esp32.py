# app/routes/esp32.py
from flask import Blueprint, request, jsonify
import requests
from datetime import datetime
from urllib.parse import urlparse

esp32_bp = Blueprint('esp32', __name__, url_prefix='/esp32')


@esp32_bp.route('/command', methods=['POST'])
def send_command_to_esp32():
    """Endpoint para enviar comandos al ESP32 (para uso directo)"""
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
    
    if command == 'REGISTER_FINGERPRINT':
        if not huella_id:
            return jsonify({
                "success": False,
                "message": "huella_id requerido para registro de huella"
            }), 400
        
        return jsonify({
            "success": True,
            "message": f"Comando REGISTER_FINGERPRINT listo para huella ID {huella_id}",
            "command": command,
            "huella_id": huella_id,
            "instructions": "Diríjase al dispositivo ESP32 y siga las instrucciones en pantalla"
        }), 200
            
    elif command == 'READ_RFID':
        return jsonify({
            "success": True,
            "message": "Modo lectura RFID activado",
            "command": command,
            "instructions": "Acercar llavero RFID al dispositivo"
        }), 200
            
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
    user_id = data.get('user_id')
    success = data.get('success', False)
    message = data.get('message', '')
    
    if not huella_id:
        return jsonify(success=False, message="huella_id requerido"), 400
    
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
                    if len(template_b64) % 4 == 0:
                        template_bytes = base64.b64decode(template_b64)
                        huella = Huella(id=huella_id, template=template_bytes)
                    else:
                        huella = Huella(id=huella_id, template=b"registered")
                except:
                    huella = Huella(id=huella_id, template=b"registered")
            else:
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
        return jsonify({
            "success": False,
            "message": f"Registro fallido en ESP32: {message}",
            "huella_id": huella_id
        }), 200


@esp32_bp.route('/listen-rfid', methods=['POST'])
def listen_rfid_result():
    """Recibir notificación de lectura RFID desde ESP32"""
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


def build_esp32_url(esp32_ip):
    """Construir URL correcta para el ESP32"""
    # Si ya es una URL completa
    if esp32_ip.startswith('http://') or esp32_ip.startswith('https://'):
        return esp32_ip
    
    # Si es un dominio ngrok, usar HTTPS
    if 'ngrok' in esp32_ip:
        return f"https://{esp32_ip}"
    
    # Para IPs locales, usar HTTP
    return f"http://{esp32_ip}"


@esp32_bp.route('/proxy/command', methods=['POST', 'OPTIONS'])
def proxy_command_to_esp32():
    """Proxy para enviar comandos al ESP32 evitando mixed content"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    data = request.get_json() or {}
    
    esp32_ip = data.get('esp32_ip')
    command = data.get('command')
    huella_id = data.get('huella_id')
    user_id = data.get('user_id')
    
    if not esp32_ip:
        return jsonify({"success": False, "message": "IP del ESP32 requerida"}), 400
    
    try:
        # Construir URL correcta
        esp32_url = build_esp32_url(esp32_ip)
        target_url = f"{esp32_url}/command"
        
        print(f"[PROXY] Enviando comando {command} a {target_url}")
        
        # Enviar comando al ESP32
        response = requests.post(
            target_url,
            json={
                "command": command,
                "huella_id": huella_id,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
                "source": "backend_proxy"
            },
            timeout=15,
            verify=False  # IMPORTANTE: Desactivar verificación SSL para ngrok
        )
        
        print(f"[PROXY] Respuesta del ESP32: {response.status_code}")
        
        if response.status_code == 200:
            try:
                esp32_response = response.json()
                return jsonify({
                    "success": True,
                    "status": "success",
                    "message": f"Comando enviado a ESP32 ({esp32_ip})",
                    "esp32_response": esp32_response
                }), 200
            except ValueError:
                # Si no es JSON, devolver texto
                return jsonify({
                    "success": True,
                    "status": "success",
                    "message": f"Comando enviado a ESP32 ({esp32_ip})",
                    "esp32_response": response.text
                }), 200
        else:
            return jsonify({
                "success": False,
                "message": f"ESP32 respondió con error: {response.status_code}",
                "response_text": response.text[:200]
            }), response.status_code
        
    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "message": f"Timeout - ESP32 en {esp32_ip} no responde en 15 segundos",
            "solution": "Verifique que ngrok esté funcionando y el ESP32 encendido"
        }), 408
        
    except requests.exceptions.ConnectionError as e:
        return jsonify({
            "success": False,
            "message": f"No se puede conectar al ESP32 en {esp32_ip}",
            "error": str(e),
            "solution": "Verifique la URL de ngrok y que el ESP32 esté encendido"
        }), 503
        
    except requests.exceptions.SSLError as e:
        return jsonify({
            "success": False,
            "message": f"Error SSL al conectar a {esp32_ip}",
            "error": str(e),
            "solution": "Ngrok puede tener problemas de certificado. Intente usar verify=False"
        }), 500
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Error inesperado: {str(e)}",
            "error_type": type(e).__name__
        }), 500


@esp32_bp.route('/proxy/status', methods=['POST', 'OPTIONS'])
def proxy_esp32_status():
    """Proxy para verificar estado del ESP32"""
    if request.method == 'OPTIONS':
        return jsonify({"success": True}), 200
    
    data = request.get_json() or {}
    esp32_ip = data.get('esp32_ip')
    
    if not esp32_ip:
        return jsonify({"success": False, "message": "IP del ESP32 requerida"}), 400
    
    try:
        # Construir URL correcta
        esp32_url = build_esp32_url(esp32_ip)
        target_url = f"{esp32_url}/status"
        
        print(f"[PROXY STATUS] Probando conexión a {target_url}")
        
        # Intentar conectar al ESP32
        response = requests.get(
            target_url,
            timeout=8,
            verify=False  # IMPORTANTE: Desactivar verificación SSL para ngrok
        )
        
        print(f"[PROXY STATUS] Respuesta: {response.status_code}")
        
        if response.status_code == 200:
            try:
                esp32_data = response.json()
                return jsonify({
                    "success": True,
                    "status": "online",
                    "esp32_data": esp32_data,
                    "message": f"ESP32 en {esp32_ip} está conectado"
                }), 200
            except ValueError:
                # Si no es JSON válido
                return jsonify({
                    "success": True,
                    "status": "online",
                    "esp32_data": {"raw_response": response.text[:100]},
                    "message": f"ESP32 responde pero no con JSON válido"
                }), 200
        else:
            return jsonify({
                "success": True,
                "status": "offline",
                "message": f"ESP32 respondió con código {response.status_code}"
            }), 200
        
    except requests.exceptions.Timeout:
        return jsonify({
            "success": True,
            "status": "offline",
            "message": "Timeout - ESP32 no responde en 8 segundos"
        }), 200
        
    except requests.exceptions.ConnectionError:
        return jsonify({
            "success": True,
            "status": "offline",
            "message": f"No se puede conectar al ESP32 en {esp32_ip}"
        }), 200
        
    except requests.exceptions.SSLError:
        return jsonify({
            "success": True,
            "status": "offline",
            "message": f"Error SSL al conectar a {esp32_ip}"
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": True,
            "status": "offline",
            "message": f"Error de conexión: {str(e)}"
        }), 200


# ========== ENDPOINT PARA DEBUG ==========
@esp32_bp.route('/debug-test', methods=['GET'])
def debug_test():
    """Endpoint para debug - probar conexión a ESP32"""
    import socket
    
    esp32_ip = request.args.get('esp32_ip', 'f4f12bcf3348.ngrok-free.app')
    
    test_results = {
        "esp32_ip": esp32_ip,
        "tests": []
    }
    
    # Test 1: DNS resolution
    try:
        ip_address = socket.gethostbyname(esp32_ip)
        test_results["tests"].append({
            "test": "DNS Resolution",
            "success": True,
            "message": f"Resuelto a IP: {ip_address}"
        })
    except socket.gaierror as e:
        test_results["tests"].append({
            "test": "DNS Resolution",
            "success": False,
            "message": f"Error DNS: {str(e)}"
        })
    
    # Test 2: Direct HTTP connection
    try:
        esp32_url = build_esp32_url(esp32_ip)
        target_url = f"{esp32_url}/status"
        
        response = requests.get(target_url, timeout=5, verify=False)
        
        test_results["tests"].append({
            "test": "Direct HTTP Connection",
            "success": True,
            "message": f"HTTP {response.status_code}: {response.text[:100]}"
        })
    except Exception as e:
        test_results["tests"].append({
            "test": "Direct HTTP Connection",
            "success": False,
            "message": f"Error: {str(e)}"
        })
    
    # Test 3: Backend connection test
    try:
        response = requests.get(f"https://{esp32_ip}/status", timeout=5, verify=False)
        test_results["tests"].append({
            "test": "HTTPS Connection",
            "success": True,
            "message": f"HTTPS {response.status_code}"
        })
    except Exception as e:
        test_results["tests"].append({
            "test": "HTTPS Connection",
            "success": False,
            "message": f"Error: {str(e)}"
        })
    
    return jsonify(test_results), 200