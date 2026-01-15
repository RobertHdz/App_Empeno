from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from typing import List
from datetime import timedelta, date
import time
from sqlalchemy.exc import OperationalError
import unicodedata
import os
import re

from . import models, database, auth, schemas

# --- FUNCIONES DE LIMPIEZA (SANITIZACIÓN) ---
def limpiar_texto(s: str):
    if not s: return ""
    try:
        s = str(s) # Asegurar que es texto
        # Normalizar para quitar acentos (Pérez -> Perez) y convertir a mayúsculas
        s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
        return s.strip().upper()
    except Exception:
        return ""

def limpiar_telefono(s: str):
    if not s: return ""
    try:
        s = str(s)
        return s.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()
    except Exception:
        return ""

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
            admin_user = db_temp.query(models.User).filter(models.User.username == "admin").first()
            if not admin_user:
                print("👤 Creando usuario 'admin' por defecto...")
                new_admin = models.User(
                    username="admin",
                    hashed_password=auth.get_password_hash("123"),
                    password_plain="123",
                    nombre_completo="Administrador Sistema",
                    rol="admin"
                )
                db_temp.add(new_admin)
                print("✅ Usuario admin creado: User='admin', Pass='123'")
            else:
                # SI YA EXISTE, FORZAMOS LA CONTRASEÑA A "123"
                print("🔄 Usuario 'admin' detectado. Restableciendo contraseña a '123'...")
                admin_user.hashed_password = auth.get_password_hash("123")
                admin_user.password_plain = "123"
                print("✅ Contraseña de admin actualizada a '123'")
            
            db_temp.commit()
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
    empeno_data = payload.empeno.model_dump()
    nuevo_empeno = models.Empeno(**empeno_data, cliente_id=cliente.id)
    db.add(nuevo_empeno)
    db.commit()
    db.refresh(nuevo_empeno)
    
    # 3. Registrar Acción para el Dashboard
    nueva_accion = models.Accion(
        tipo_accion="Nuevo Empeño",
        empeno_id=nuevo_empeno.id,
        cliente_nombre=f"{cliente.nombre} {cliente.apellidos}",
        articulo=nuevo_empeno.marca_modelo,
        monto=nuevo_empeno.monto_prestamo,
        usuario_id=current_user.id
    )
    db.add(nueva_accion)
    db.commit()
    
    print(f"  -> ✅ Nuevo empeño creado (ID: {nuevo_empeno.id}) y acción registrada.")
    return nuevo_empeno

@app.get("/dashboard/tabla")
async def get_dashboard_tabla(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_user)):
    acciones = db.query(models.Accion).order_by(models.Accion.fecha.desc()).limit(10).all()
    resultado = []
    for acc in acciones:
        resultado.append({
            "cliente": acc.cliente_nombre,
            "accion": acc.tipo_accion,
            "articulo": acc.articulo,
            "monto": acc.monto,
            "fecha": acc.fecha.strftime("%Y-%m-%d %H:%M")
        })
    return resultado

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
    
    # Usamos una consulta directa para asegurar que traemos TODO el historial (Vigentes, Vendidos, etc.)
    # Ordenados del más reciente al más antiguo
    empenos = db.query(models.Empeno).filter(models.Empeno.cliente_id == cliente.id).order_by(models.Empeno.id.desc()).all()
    
    # LIMPIEZA DE EMERGENCIA: Quitar espacios en blanco de los estados para evitar errores de CSS
    for emp in empenos:
        if emp.estado:
            emp.estado = emp.estado.strip()
    
    # LOG DE DIAGNÓSTICO: Ver qué estados se están enviando
    estados_log = [e.estado for e in empenos]
    print(f"✅ Cliente encontrado: ID {cliente.id}. Enviando {len(empenos)} contratos. Estados: {estados_log}")
    return empenos

@app.get("/clientes/buscar")
async def buscar_clientes(
    q: str = "",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    print(f"🔍 BUSCAR CLIENTES: q='{q}'")
    if not q:
        return []
    
    # Actualizar estados para que el cliente vea la info real (Vencido/Vigente)
    actualizar_estados_empenos(db)
    
    try:
        q_clean = limpiar_texto(q)
        q_tel = limpiar_telefono(q)
        q_raw = q.strip()
        
        from sqlalchemy import or_, and_
        
        filtros_or = []
        
        # 1. Búsqueda por Teléfono
        if q_tel:
            filtros_or.append(models.Cliente.telefono.like(f"%{q_tel}%"))
            
        # 2. Búsqueda Directa (Raw)
        if q_raw:
            filtros_or.append(models.Cliente.nombre.ilike(f"%{q_raw}%"))
            filtros_or.append(models.Cliente.apellidos.ilike(f"%{q_raw}%"))
            filtros_or.append(models.Cliente.telefono.ilike(f"%{q_raw}%"))

        # 3. Búsqueda por Palabras (Nombre/Apellido)
        if q_clean:
            q_clean_spaces = re.sub(r'[^A-Z0-9]', ' ', q_clean)
            palabras = q_clean_spaces.split()
            
            if palabras:
                condiciones_palabras = []
                for palabra in palabras:
                    condiciones_palabras.append(
                        or_(
                            models.Cliente.nombre.ilike(f"%{palabra}%"),
                            models.Cliente.apellidos.ilike(f"%{palabra}%")
                        )
                    )
                filtros_or.append(and_(*condiciones_palabras))

        if not filtros_or:
            return []

        # Agregamos joinedload para cargar los empeños eficientemente
        clientes = db.query(models.Cliente).options(joinedload(models.Cliente.empenos)).filter(or_(*filtros_or)).all()
        print(f"   -> Encontrados: {len(clientes)}")
        
        # Devolvemos el cliente CON sus empeños detallados
        return [{
            "id": c.id, 
            "nombre": c.nombre, 
            "apellidos": c.apellidos, 
            "telefono": c.telefono, 
            "direccion": c.direccion, 
            "ine": c.ine, 
            "user_id": c.user_id,
            "empenos": [{
                "id": e.id,
                "marca_modelo": e.marca_modelo,
                "monto_prestamo": e.monto_prestamo,
                "interes_mensual_pct": e.interes_mensual_pct,
                "fecha_empeno": e.fecha_empeno,
                "fecha_vencimiento": e.fecha_vencimiento,
                "estado": e.estado,
                "valor_valuo": e.valor_valuo,
                "categoria": e.categoria,
                "descripcion": e.descripcion,
                "num_serie_peso": e.num_serie_peso,
                "observaciones": e.observaciones,
                "cliente_id": e.cliente_id
            } for e in c.empenos]
        } for c in clientes]
    except Exception as e:
        print(f"❌ ERROR CRÍTICO EN BUSCAR CLIENTES: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno al buscar clientes: {str(e)}")

@app.get("/empenos/buscar", response_model=List[schemas.EmpenoResponse])
async def buscar_empenos(
    q: str = "",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    print(f"🔍 BUSCAR EMPENOS: q='{q}'")
    if not q:
        return []
    
    # Actualizar estados antes de buscar para mostrar info real
    actualizar_estados_empenos(db)

    try:
        q_clean = limpiar_texto(q)
        q_tel = limpiar_telefono(q)
        q_raw = q.strip()
        
        from sqlalchemy import or_, and_
        
        filtros_or = []
        
        # 1. Búsqueda por Folio (ID)
        if str(q).strip().isdigit():
            filtros_or.append(models.Empeno.id == int(str(q).strip()))
            
        # 2. Búsqueda por Teléfono del Cliente
        if q_tel:
            filtros_or.append(models.Cliente.telefono.like(f"%{q_tel}%"))
        
        # 3. Búsqueda Directa (Raw)
        if q_raw:
            filtros_or.append(models.Cliente.nombre.ilike(f"%{q_raw}%"))
            filtros_or.append(models.Cliente.apellidos.ilike(f"%{q_raw}%"))
            filtros_or.append(models.Cliente.telefono.ilike(f"%{q_raw}%"))

        # 4. Búsqueda Inteligente por Nombre/Apellido
        if q_clean:
            q_clean_spaces = re.sub(r'[^A-Z0-9]', ' ', q_clean)
            palabras = q_clean_spaces.split()
            
            if palabras:
                condiciones_palabras = []
                for palabra in palabras:
                    condiciones_palabras.append(
                        or_(
                            models.Cliente.nombre.ilike(f"%{palabra}%"),
                            models.Cliente.apellidos.ilike(f"%{palabra}%")
                        )
                    )
                filtros_or.append(and_(*condiciones_palabras))
        
        if not filtros_or:
            return []
        
        resultados = db.query(models.Empeno).join(models.Cliente).options(joinedload(models.Empeno.cliente)).filter(or_(*filtros_or)).all()
        
        # --- SERIALIZACIÓN MANUAL SEGURA (A PRUEBA DE FALLOS) ---
        safe_results = []
        for r in resultados:
            # Construimos los datos del cliente con cuidado
            c_data = None
            if r.cliente:
                c_data = {
                    "nombre": r.cliente.nombre,
                    "apellidos": r.cliente.apellidos,
                    "telefono": r.cliente.telefono,
                    "ine": r.cliente.ine,
                    "direccion": r.cliente.direccion
                }
            
            # Agregamos el empeño a la lista
            safe_results.append({
                "id": r.id,
                "estado": r.estado,
                "cliente_id": r.cliente_id,
                "cliente": c_data,
                "categoria": r.categoria,
                "marca_modelo": r.marca_modelo,
                "descripcion": r.descripcion,
                "num_serie_peso": r.num_serie_peso,
                "observaciones": r.observaciones,
                "valor_valuo": r.valor_valuo,
                "monto_prestamo": r.monto_prestamo,
                "interes_mensual_pct": r.interes_mensual_pct,
                "fecha_empeno": r.fecha_empeno,
                "fecha_vencimiento": r.fecha_vencimiento
            })

        print(f"   -> Encontrados y procesados: {len(safe_results)}")
        return safe_results
    except Exception as e:
        print(f"❌ ERROR CRÍTICO EN BUSCAR EMPENOS: {str(e)}")
        # Retornamos lista vacía en lugar de error 500 para que la app no se congele
        return []

@app.post("/empenos/{id}/refrendo")
async def refrendo_empeno(
    id: int,
    payload: schemas.RefrendoPayload,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    empeno = db.query(models.Empeno).filter(models.Empeno.id == id).first()
    if not empeno:
        raise HTTPException(status_code=404, detail="Empeño no encontrado")
    
    if empeno.estado in ["Desempeñado", "Vendido"]:
        raise HTTPException(status_code=400, detail="El empeño no se puede refrendar en su estado actual.")

    # Lógica: Sumar 30 días. Si ya venció, desde hoy. Si no, desde su vencimiento.
    hoy = date.today()
    if empeno.fecha_vencimiento < hoy:
        empeno.fecha_vencimiento = hoy + timedelta(days=30)
    else:
        empeno.fecha_vencimiento = empeno.fecha_vencimiento + timedelta(days=30)
        
    # Actualizar estado a Vigente (incluso si estaba en Remate/Recuperación)
    if empeno.estado in ["Vencido", "Dias_Gracia", "Remate"]:
        empeno.estado = "Vigente"

    # Aplicar Abono a Capital si existe
    if payload.abono_capital > 0:
        if payload.abono_capital >= empeno.monto_prestamo:
             raise HTTPException(status_code=400, detail="El abono a capital cubre el total. Por favor realice un Desempeño.")
        empeno.monto_prestamo -= payload.abono_capital
        
    # Registrar Acción con el monto total pagado (incluyendo recargos y multas)
    nueva_accion = models.Accion(
        tipo_accion="Refrendo",
        empeno_id=empeno.id,
        cliente_nombre=f"{empeno.cliente.nombre} {empeno.cliente.apellidos}",
        articulo=empeno.marca_modelo,
        monto=payload.total_pagado,
        usuario_id=current_user.id
    )
    db.add(nueva_accion)
    db.commit()
    return {"mensaje": "Refrendo aplicado exitosamente", "nuevo_vencimiento": empeno.fecha_vencimiento, "estado": empeno.estado}

@app.post("/empenos/{id}/desempeno")
async def desempeno_empeno(
    id: int,
    payload: schemas.DesempenoPayload,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    empeno = db.query(models.Empeno).filter(models.Empeno.id == id).first()
    if not empeno:
        raise HTTPException(status_code=404, detail="Empeño no encontrado")
        
    if empeno.estado in ["Desempeñado", "Vendido"]:
        raise HTTPException(status_code=400, detail="El empeño ya está cerrado.")

    empeno.estado = "Desempeñado"
    
    # Registrar Acción con el monto total cobrado (Capital + Interés + Recargos)
    nueva_accion = models.Accion(
        tipo_accion="Desempeño",
        empeno_id=empeno.id,
        cliente_nombre=f"{empeno.cliente.nombre} {empeno.cliente.apellidos}",
        articulo=empeno.marca_modelo,
        monto=payload.total_pagado,
        usuario_id=current_user.id
    )
    db.add(nueva_accion)
    db.commit()
    return {"mensaje": "Desempeño realizado exitosamente", "estado": empeno.estado}

@app.put("/empenos/{id}/editar")
async def editar_empeno(
    id: int,
    payload: schemas.EmpenoEditSchema,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    empeno = db.query(models.Empeno).filter(models.Empeno.id == id).first()
    if not empeno:
        raise HTTPException(status_code=404, detail="Empeño no encontrado")
    
    # Actualizar datos del cliente
    if empeno.cliente:
        empeno.cliente.nombre = payload.nombre
        empeno.cliente.apellidos = payload.apellidos
        empeno.cliente.telefono = payload.telefono
        empeno.cliente.direccion = payload.direccion
    
    # Actualizar datos del empeño
    empeno.categoria = payload.categoria
    empeno.marca_modelo = payload.marca_modelo
    empeno.estado = payload.estado
    empeno.fecha_empeno = payload.fecha_empeno
    empeno.fecha_vencimiento = payload.fecha_vencimiento
    
    db.commit()
    return {"mensaje": "Empeño y cliente actualizados correctamente"}

@app.get("/empenos/remates")
async def leer_remates(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_user)):
    # Actualizamos estados para asegurar que los vencidos pasen a remate
    actualizar_estados_empenos(db)
    # Buscamos empeños en estado Remate o Vendido
    remates = db.query(models.Empeno).filter(models.Empeno.estado.in_(["Remate", "Vendido"])).all()
    resultado = []
    for r in remates:
        resultado.append({
            "id": r.id,
            "cliente": f"{r.cliente.nombre} {r.cliente.apellidos}" if r.cliente else "N/A",
            "marca_modelo": r.marca_modelo,
            "monto_prestamo": r.monto_prestamo,
            "fecha_empeno": r.fecha_empeno,
            "estado": r.estado
        })
    return resultado

@app.post("/empenos/{id}/venta")
async def vender_empeno(
    id: int,
    payload: schemas.VentaPayload,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    empeno = db.query(models.Empeno).filter(models.Empeno.id == id).first()
    if not empeno:
        raise HTTPException(status_code=404, detail="Empeño no encontrado")
    
    empeno.estado = "Vendido"
    
    # Registrar Acción de Venta
    nueva_accion = models.Accion(
        tipo_accion="Venta/Remate",
        empeno_id=empeno.id,
        cliente_nombre=f"{empeno.cliente.nombre} {empeno.cliente.apellidos}" if empeno.cliente else "N/A",
        articulo=empeno.marca_modelo,
        monto=payload.precio_venta,
        usuario_id=current_user.id
    )
    db.add(nueva_accion)
    db.commit()
    return {"mensaje": "Venta registrada exitosamente"}

@app.post("/empenos/{id}/reevaluo")
async def reevaluo_empeno(
    id: int,
    payload: schemas.ReevaluoPayload,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    empeno = db.query(models.Empeno).filter(models.Empeno.id == id).first()
    if not empeno:
        raise HTTPException(status_code=404, detail="Empeño no encontrado")
    
    if empeno.estado in ["Desempeñado", "Vendido"]:
        raise HTTPException(status_code=400, detail="No se puede reevaluar un empeño cerrado.")

    # Calcular diferencia para registrar en la acción
    diferencia = payload.nuevo_prestamo - empeno.monto_prestamo
    
    # Actualizar datos
    empeno.monto_prestamo = payload.nuevo_prestamo
    empeno.valor_valuo = payload.nuevo_valuo
    empeno.interes_mensual_pct = payload.nuevo_interes
    
    # Registrar Acción de Revalúo
    nueva_accion = models.Accion(
        tipo_accion="Revalúo",
        empeno_id=empeno.id,
        cliente_nombre=f"{empeno.cliente.nombre} {empeno.cliente.apellidos}" if empeno.cliente else "N/A",
        articulo=empeno.marca_modelo,
        monto=diferencia,
        usuario_id=current_user.id
    )
    db.add(nueva_accion)
    db.commit()
    return {"mensaje": "Revalúo registrado exitosamente"}

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
    try:
        clientes = db.query(models.Cliente).all()
        resultado = []
        for c in clientes:
            # Buscar el usuario web asociado para mostrar credenciales
            login_info = "SIN USUARIO WEB"
            if c.user_id:
                u = db.query(models.User).filter(models.User.id == c.user_id).first()
                if u:
                    pass_visible = u.password_plain if u.password_plain else "Encriptada (No visible)"
                    login_info = f"Usuario: '{u.username}' | Contraseña: '{pass_visible}'"

            resultado.append({
                "id": c.id,
                "nombre": c.nombre,
                "telefono": c.telefono,
                "CREDENCIALES_LOGIN": login_info,  # <--- AQUÍ VERÁS CON QUÉ ENTRAR
                "empenos_count": len(c.empenos)
            })
        return resultado
    except Exception as e:
        return {"error": "Ocurrió un error al leer la base de datos", "detalle": str(e)}

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

# --- HERRAMIENTA DE CORRECCIÓN DE DUPLICADOS ---
@app.get("/debug/corregir_duplicados")
async def corregir_duplicados(db: Session = Depends(database.get_db)):
    try:
        # 1. Obtener clientes con usuario (Los "Oficiales")
        clientes_con_usuario = db.query(models.Cliente).filter(models.Cliente.user_id != None).all()
        
        # 2. Obtener clientes sin usuario (Los "Huérfanos" que tienen los empeños)
        clientes_huerfanos = db.query(models.Cliente).filter(models.Cliente.user_id == None).all()
        
        log = []
        cambios = False
        procesados = set() 

        for oficial in clientes_con_usuario:
            oficial_tel = limpiar_telefono(oficial.telefono)
            oficial_nom = limpiar_texto(oficial.nombre)
            oficial_ape = limpiar_texto(oficial.apellidos)
            
            for huerfano in clientes_huerfanos:
                if huerfano.id in procesados: continue

                match = False
                razon = ""
                
                # A. Comparar Teléfonos (Prioridad)
                huerfano_tel = limpiar_telefono(huerfano.telefono)
                if oficial_tel and huerfano_tel and oficial_tel == huerfano_tel:
                    match = True
                    razon = f"Teléfono coincidente ({oficial_tel})"
                
                # B. Comparar Nombres (Si no hubo match por teléfono)
                if not match:
                    huerfano_nom = limpiar_texto(huerfano.nombre)
                    huerfano_ape = limpiar_texto(huerfano.apellidos)
                    if oficial_nom and oficial_ape and oficial_nom == huerfano_nom and oficial_ape == huerfano_ape:
                        match = True
                        razon = f"Nombre coincidente ({oficial_nom} {oficial_ape})"
                
                if match:
                    # Mover empeños del huérfano al oficial
                    count = 0
                    for emp in huerfano.empenos:
                        emp.cliente_id = oficial.id
                        count += 1
                    
                    log.append(f"🔧 FUSIONADO: Cliente Huérfano ID {huerfano.id} -> Oficial ID {oficial.id}. Razón: {razon}. Empeños movidos: {count}")
                    db.delete(huerfano)
                    procesados.add(huerfano.id)
                    cambios = True
        
        if cambios: 
            db.commit()
            return {"mensaje": "Proceso de corrección terminado con ÉXITO", "detalles": log}
        
        return {
            "mensaje": "No se encontraron duplicados automáticos.", 
            "diagnostico": f"Se analizaron {len(clientes_con_usuario)} cuentas oficiales y {len(clientes_huerfanos)} perfiles huérfanos."
        }
    except Exception as e:
        return {"error": "Error crítico ejecutando la corrección", "detalle": str(e)}

# --- HERRAMIENTA DE SIMULACIÓN DE HISTORIAL (DEBUG) ---
@app.get("/debug/simular_historial")
async def debug_simular_historial(db: Session = Depends(database.get_db)):
    # Buscamos el primer cliente que tenga usuario web (asumimos que es el tuyo para pruebas)
    cliente = db.query(models.Cliente).filter(models.Cliente.user_id != None).first()
    
    if not cliente:
         return {"error": "No se encontró ningún cliente con usuario web vinculado."}
         
    if not cliente.empenos:
        return {"error": "No tienes contratos registrados para simular el historial."}
    
    empenos = cliente.empenos
    log = []
    
    # Lista de estados para probar que TODOS se ven
    estados_demo = ["Vendido", "Remate", "Desempeñado", "Vigente", "Dias_Gracia"]
    
    for i, emp in enumerate(empenos):
        # Asignamos un estado diferente a cada contrato rotativamente
        estado_nuevo = estados_demo[i % len(estados_demo)]
        emp.estado = estado_nuevo
        
        # AJUSTE DE FECHAS: Para evitar que el sistema los cambie automáticamente
        if estado_nuevo == "Vigente":
            # Vence en 30 días (Futuro)
            emp.fecha_vencimiento = date.today() + timedelta(days=30)
        elif estado_nuevo == "Dias_Gracia":
            # Venció hace 2 días (Dentro del rango de 5 días de gracia)
            emp.fecha_vencimiento = date.today() - timedelta(days=2)
        # Para los demás, la fecha no importa tanto
        
        log.append(f"Contrato {emp.id} ({emp.marca_modelo}) -> {estado_nuevo}")
        
    db.commit()
    return {"mensaje": "✅ Historial simulado correctamente. Recarga tu aplicación para ver los colores.", "cambios": log}

# Ruta raíz redirige al login
from fastapi.responses import RedirectResponse
@app.get("/")
async def root():
    return RedirectResponse(url="/static/login.html")
