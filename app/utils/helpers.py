def validate_email(email):
    import re
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(pattern, email) is not None

def format_timestamp(timestamp):
    from datetime import datetime
    return timestamp.strftime('%Y-%m-%d %H:%M:%S')

def generate_response(message, status_code):
    return {
        'message': message,
        'status_code': status_code
    }
def validate_user_credentials(user, password):

    if not user:
        return False

    if hasattr(user, "check_password"):
        return user.check_password(password)


    return user.password == password

