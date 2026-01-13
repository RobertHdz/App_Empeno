from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from datetime import timedelta, date
import time
from sqlalchemy.exc import OperationalError
import os

from . import models, database, auth, schemas

# --- FUNCIONES DE LIMPIEZA (SANITIZACIÓN) ---
def limpiar_texto(s: str):
    if not s: return ""
    return s.strip().upper() # Convertimos a mayúsculas para evitar errores de "Juan" vs "juan"

def limpiar_telefono(s: str):
    if not s: return ""
    # Quita espacios, guiones y paréntesis
    return s.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()

# --- FUNCIÓN PARA ACTUALIZAR ESTADOS AUTOMÁTICAMENTE ---
def actualizar_estados_empenos(db: Session):
    hoy = date.today()
    
    cambios = False
    
    # 0. CORRECCIÓN: Renombrar "Días de Gracia" (con espacios) a "Dias_Gracia" (seguro)
    legacy_items = db.query(models.Empeno).filter(models.Empeno.estado == "Días de Gracia").all()
    for item in legacy_items:
        item.estado = "Dias_Gracia"
        cambios = True

    # Buscamos empeños activos para verificar si cambian
    empenos_activos = db.query(models.Empeno).filter(models.Empeno.estado.in_(["Vigente", "Dias_Gracia"])).all()
    
    for empeno in empenos_activos:
        fecha_venc = empeno.fecha_vencimiento
        fecha_limite_gracia = fecha_venc + timedelta(days=5)
        
        # 1. Verificar si ya pasó el tiempo de gracia (Vencimiento + 5 días) -> REMATE
        if hoy > fecha_limite_gracia:
            if empeno.estado != "Remate":
                print(f"🔄 AUTO-CORRECCIÓN: Empeño {empeno.id} venció gracia el {fecha_limite_gracia}. Pasando a REMATE.")
                empeno.estado = "Remate"
                cambios = True
        
        # 2. Verificar si está vencido pero dentro de los días de gracia -> Dias_Gracia
        elif hoy > fecha_venc:
            if empeno.estado != "Dias_Gracia":
                print(f"⚠️ AUTO-CORRECCIÓN: Empeño {empeno.id} venció el {fecha_venc}. Entrando a DÍAS DE GRACIA.")
                empeno.estado = "Dias_Gracia"
                cambios = True
            
    if cambios:
        db.commit()

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir Frontend (Archivos estáticos)
# Usamos ruta absoluta para evitar errores en Docker si el contexto cambia
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
print(f"Iniciando servidor... Montando frontend desde: {frontend_path}")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# --- INICIO DE BASE DE DATOS (CON REINTENTO) ---
while True:
    try:
        models.Base.metadata.create_all(bind=database.engine)
        print("✅ Base de datos conectada y tablas listas.")
        
        # --- CREAR ADMIN POR DEFECTO AUTOMÁTICAMENTE ---
        db_temp = database.SessionLocal()
        try:
            if not db_temp.query(models.User).filter(models.User.username == "admin").first():
                print("👤 Creando usuario 'admin' por defecto...")
                admin_user = models.User(
                    username="admin",
                    hashed_password=auth.get_password_hash("123"),
                    password_plain="123",
                    nombre_completo="Administrador Sistema",
                    rol="admin"
                )
                db_temp.add(admin_user)
                db_temp.commit()
                print("✅ Usuario admin creado: User='admin', Pass='123'")
        finally:
            db_temp.close()
        # -----------------------------------------------
        
        break
    except OperationalError:
        print("⏳ La base de datos se está iniciando, reintentando en 5 segundos...")
        time.sleep(5)

# --- RUTAS DE AUTENTICACIÓN ---

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Usuario o contraseña incorrectos")
    
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer", "rol": user.rol}

@app.post("/registrar-empleado-seguro")
async def registrar(payload: schemas.RegistroEmpleadoSchema, db: Session = Depends(database.get_db)):
    # Contraseña maestra simple para demostración
    if payload.admin_password != "ADMIN123": 
        raise HTTPException(status_code=403, detail="Contraseña de administrador incorrecta")
    
    if db.query(models.User).filter(models.User.username == payload.nuevo_usuario.usuario).first():
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    
    new_user = models.User(
        username=payload.nuevo_usuario.usuario,
        hashed_password=auth.get_password_hash(payload.nuevo_usuario.password),
        password_plain=payload.nuevo_usuario.password,
        nombre_completo=payload.nuevo_usuario.nombre_completo,
        rol=payload.nuevo_usuario.rol
    )
    db.add(new_user)
    db.commit()
    return {"mensaje": "Usuario creado"}

@app.post("/registrar-cliente")
async def registrar_cliente(payload: schemas.ClienteRegistroSchema, db: Session = Depends(database.get_db)):
    # 1. Limpiar datos de entrada
    tel_limpio = limpiar_telefono(payload.telefono)
    nom_limpio = limpiar_texto(payload.nombre)
    ape_limpio = limpiar_texto(payload.apellidos)

    # Verificar si ya existe el usuario de login
    if db.query(models.User).filter(models.User.username == payload.usuario).first():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya está en uso.")
    
    # Crear el usuario de login
    new_user = models.User(
        username=payload.usuario,
        hashed_password=auth.get_password_hash(payload.password),
        password_plain=payload.password,
        nombre_completo=f"{nom_limpio} {ape_limpio}",
        rol="cliente" # Forzamos el rol de cliente
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    print(f"🔍 REGISTRO: Buscando perfil de cliente para vincular. Criterios: Tel='{tel_limpio}', Apellidos='{ape_limpio}'")

    cliente_existente = None
    # Criterio 1 (Más Fuerte): Teléfono Y Apellidos
    if tel_limpio and ape_limpio:
        print("  -> Intentando por Teléfono Y Apellidos...")
        cliente_existente = db.query(models.Cliente).filter(
            models.Cliente.telefono == tel_limpio,
            models.Cliente.apellidos == ape_limpio,
            models.Cliente.user_id.is_(None)
        ).first()

    # Criterio 2: Solo Teléfono (si el primero falla)
    if not cliente_existente and tel_limpio:
        print("  -> No se encontró. Intentando solo por Teléfono...")
        cliente_existente = db.query(models.Cliente).filter(
            models.Cliente.telefono == tel_limpio,
            models.Cliente.user_id.is_(None)
        ).first()

    if cliente_existente:
        print(f"✅ ÉXITO: Perfil de cliente encontrado (ID: {cliente_existente.id}). Vinculando con nuevo usuario (ID: {new_user.id}).")
        cliente_existente.user_id = new_user.id
        # Actualizamos con los datos más recientes del registro
        cliente_existente.direccion = payload.direccion
        cliente_existente.nombre = nom_limpio 
        db.commit()
    else:
        print("✨ AVISO: No se encontró historial previo. Creando perfil de cliente nuevo y vinculándolo.")
        new_cliente = models.Cliente(
            nombre=nom_limpio,
            apellidos=ape_limpio,
            direccion=payload.direccion,
            telefono=tel_limpio,
            user_id=new_user.id
        )
        db.add(new_cliente)
        db.commit()

    return {"mensaje": "Cliente registrado exitosamente"}

# --- RUTAS DE EMPEÑOS ---

@app.post("/empenos/nuevo", response_model=schemas.EmpenoResponse)
async def crear_empeno(payload: schemas.NuevoEmpenoSchema, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_user)):
    print(f"📝 CREAR_EMPENO: Petición recibida.")
    
    # 1. Limpiar datos del cliente del payload
    tel_limpio = limpiar_telefono(payload.cliente.telefono)
    nom_limpio = limpiar_texto(payload.cliente.nombre)
    ape_limpio = limpiar_texto(payload.cliente.apellidos)
    print(f"  -> Buscando cliente con: Tel='{tel_limpio}', Apellidos='{ape_limpio}'")

    cliente = None
    # Criterio 1 (Más Fuerte): Teléfono Y Apellidos
    if tel_limpio and ape_limpio:
        print("    -> Intentando por Teléfono Y Apellidos...")
        cliente = db.query(models.Cliente).filter(
            models.Cliente.telefono == tel_limpio,
            models.Cliente.apellidos == ape_limpio
        ).first()

    # Criterio 2: Solo Teléfono (si el primero falla)
    if not cliente and tel_limpio:
        print("    -> No se encontró. Intentando solo por Teléfono...")
        cliente = db.query(models.Cliente).filter(models.Cliente.telefono == tel_limpio).first()
    
    if cliente:
        print(f"  -> ✅ Cliente existente encontrado (ID: {cliente.id}).")
    if not cliente:
        print("  -> ✨ No se encontró cliente. Creando uno nuevo.")
        cliente = models.Cliente(
            nombre=nom_limpio,
            apellidos=ape_limpio,
            telefono=tel_limpio,
            ine=payload.cliente.ine,
            direccion=payload.cliente.direccion
        )
        db.add(cliente)
        db.commit()
        db.refresh(cliente)
        print(f"  -> ✅ Nuevo cliente creado (ID: {cliente.id}).")
    
    # 2. Crear Empeño
    # Usamos model_dump() que es la forma correcta en Pydantic V2
    empeno_data = payload.empeno.model_dump()
    
    nuevo_empeno = models.Empeno(**empeno_data, cliente_id=cliente.id)
    db.add(nuevo_empeno)
    db.commit()
    db.refresh(nuevo_empeno)
    print(f"  -> ✅ Nuevo empeño creado (ID: {nuevo_empeno.id}) y asignado al cliente (ID: {cliente.id}).")
    
    return nuevo_empeno

@app.get("/empenos/todos", response_model=List[schemas.EmpenoResponse])
async def leer_empenos(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_user)):
    # Actualizamos estados antes de devolver la lista para que el usuario vea la info real
    actualizar_estados_empenos(db)
    return db.query(models.Empeno).all()

@app.get("/empenos/mis-empenos", response_model=List[schemas.EmpenoResponse])
async def mis_empenos(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_user)):
    print(f"🔍 MIS_EMPENOS: Usuario ID {current_user.id} ({current_user.username}) solicitando empeños.")
    # Actualizamos estados antes de devolver la lista
    actualizar_estados_empenos(db)
    
    # Buscar al cliente conectado usando su ID de usuario
    cliente = db.query(models.Cliente).filter(models.Cliente.user_id == current_user.id).first()
    if not cliente:
        print("❌ No se encontró perfil de cliente vinculado a este usuario.")
        return [] # Si no tiene perfil de cliente, retorna lista vacía
    print(f"✅ Cliente encontrado: ID {cliente.id} ({cliente.nombre}). Tiene {len(cliente.empenos)} empeños.")
    return cliente.empenos

# --- NUEVO ENDPOINT: VER CREDENCIALES (SOLO ADMIN/DUEÑOS) ---
@app.get("/admin/clientes/{cliente_id}/credenciales")
async def obtener_credenciales_cliente(
    cliente_id: int, 
    db: Session = Depends(database.get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
    # Verificar si es admin o dueño
    if current_user.rol not in ["admin", "dueño"]:
        raise HTTPException(status_code=403, detail="No tiene permisos para ver contraseñas.")
    
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente or not cliente.user_id:
        raise HTTPException(status_code=404, detail="Cliente no encontrado o sin usuario web.")
        
    user = db.query(models.User).filter(models.User.id == cliente.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        
    return {
        "username": user.username,
        "password": user.password_plain if user.password_plain else "No disponible (Encriptada)"
    }

# --- RUTA DE DIAGNÓSTICO (NUEVA) ---
@app.get("/debug/clientes")
async def debug_clientes(db: Session = Depends(database.get_db)):
    clientes = db.query(models.Cliente).all()
    resultado = []
    for c in clientes:
        resultado.append({
            "id": c.id,
            "nombre": c.nombre,
            "apellidos": c.apellidos,
            "telefono": c.telefono,
            "user_id": c.user_id, # Si esto es null, no tiene usuario. Si tiene numero, ya tiene dueño.
            "empenos_count": len(c.empenos)
        })
    return resultado

@app.get("/debug/generar_empeno_prueba")
async def debug_generar_empeno(db: Session = Depends(database.get_db)):
    # Buscar un cliente que tenga usuario vinculado
    cliente = db.query(models.Cliente).filter(models.Cliente.user_id != None).first()
    if not cliente:
        return {"error": "No hay clientes registrados con usuario para asignarles el empeño."}
    
    # Crear un empeño falso
    dummy_empeno = models.Empeno(
        cliente_id=cliente.id,
        categoria="electronicos",
        marca_modelo="Laptop HP (Prueba Automática)",
        descripcion="Generada automáticamente para verificar el dashboard",
        valor_valuo=5000,
        monto_prestamo=3000,
        interes_mensual_pct=10,
        fecha_empeno=date.today(),
        fecha_vencimiento=date.today() + timedelta(days=30),
        estado="Vigente"
    )
    db.add(dummy_empeno)
    db.commit()
    return {"mensaje": f"✅ Empeño de prueba creado para el cliente: {cliente.nombre} (Tel: {cliente.telefono})"}

# Ruta raíz redirige al login
from fastapi.responses import RedirectResponse
@app.get("/")
async def root():
    return RedirectResponse(url="/static/login.html")
