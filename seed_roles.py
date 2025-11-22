from app import create_app, db
from app.models import Role, UserRoleEnum, User_iot

app = create_app()

with app.app_context():

    for role_name in [role.value for role in UserRoleEnum]:
        if not Role.query.filter_by(name=role_name).first():
            db.session.add(Role(name=role_name))
            print(f"Rol '{role_name}' creado.")

    db.session.commit()
    print("Todos los roles del Enum están actualizados.")
    admin_role = Role.query.filter_by(name=UserRoleEnum.admin.value).first()
    admin_user = User_iot.query.filter_by(username="admin").first()
    if not admin_user:
        admin_user = User_iot(
            username="admin",
            nombre="Administrador",
            apellido="Principal",
            role=admin_role,
            huella=b"huella_binaria_admin"
        )
        admin_user.set_password("admin123")
        db.session.add(admin_user)
        db.session.commit()
        print("Usuario admin creado.")
    else:
        print("El usuario admin ya existe.")
