# IoT Attendance Backend

This project is an IoT access and attendance system built using Flask and JWT for authentication. It provides functionalities for user management, access logging, and attendance tracking through IoT devices.

## Features

- User registration and login with JWT authentication
- RFID validation for access control
- Logging of access attempts
- Attendance tracking with entry and exit times
- Querying attendance history

## Project Structure

```
iot-attendance-backend
├── app
│   ├── __init__.py
│   ├── models.py
│   ├── routes
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── access.py
│   │   └── attendance.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── jwt_service.py
│   │   └── iot_service.py
│   └── utils
│       ├── __init__.py
│       └── helpers.py
├── migrations
│   └── README.md
├── requirements.txt
├── config.py
├── run.py
└── README.md
```

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd iot-attendance-backend
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

## Configuration

Update the `config.py` file with your database URI and JWT secret key.

## Running the Application

To run the application, execute:
```
python run.py
```

## API Endpoints

- **Authentication**
  - `POST /auth/register`: Register a new user
  - `POST /auth/login`: Login and receive a JWT token

- **Access Management**
  - `POST /access/validate`: Validate RFID and log access attempts

- **Attendance Management**
  - `POST /attendance/log`: Log entry and exit times
  - `GET /attendance/history`: Query attendance history

## License

This project is licensed under the MIT License.