from pydantic import BaseModel
from typing import Optional, List
from datetime import date

# --- AUTH ---
class UserCreate(BaseModel):
    usuario: str
    password: str
    nombre_completo: str
    rol: str = "empleado"

class ClienteRegistroSchema(BaseModel):
    usuario: str
    password: str
    nombre: str
    apellidos: str
    direccion: str
    telefono: str

class RegistroEmpleadoSchema(BaseModel):
    nuevo_usuario: UserCreate
    admin_password: str

# --- EMPENOS ---
class ClienteBase(BaseModel):
    nombre: str
    apellidos: str
    telefono: Optional[str] = None
    ine: Optional[str] = None
    direccion: Optional[str] = None

class EmpenoBase(BaseModel):
    categoria: str
    marca_modelo: str
    descripcion: str
    num_serie_peso: Optional[str] = None
    observaciones: Optional[str] = None
    valor_valuo: float
    monto_prestamo: float
    interes_mensual_pct: float
    fecha_empeno: date
    fecha_vencimiento: date

class NuevoEmpenoSchema(BaseModel):
    cliente: ClienteBase
    empeno: EmpenoBase

class EmpenoResponse(EmpenoBase):
    id: int
    estado: str
    cliente_id: int
    cliente: Optional[ClienteBase] = None
    class Config:
        from_attributes = True
