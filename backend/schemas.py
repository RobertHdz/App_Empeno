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
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    ine: Optional[str] = None
    direccion: Optional[str] = None

class EmpenoBase(BaseModel):
    categoria: Optional[str] = None
    marca_modelo: Optional[str] = None
    descripcion: Optional[str] = None
    num_serie_peso: Optional[str] = None
    observaciones: Optional[str] = None
    valor_valuo: Optional[float] = None
    monto_prestamo: Optional[float] = None
    interes_mensual_pct: Optional[float] = None
    fecha_empeno: Optional[date] = None
    fecha_vencimiento: Optional[date] = None

class NuevoEmpenoSchema(BaseModel):
    cliente: ClienteBase
    empeno: EmpenoBase

class RefrendoPayload(BaseModel):
    total_pagado: float
    monto_recargos: float = 0
    monto_multa: float = 0
    abono_refrendo: float = 0
    abono_capital: float = 0

class DesempenoPayload(BaseModel):
    total_pagado: float
    monto_capital: float
    monto_interes: float
    monto_recargos: float = 0
    monto_multa: float = 0

class EmpenoEditSchema(BaseModel):
    nombre: str
    apellidos: str
    telefono: str
    direccion: str
    categoria: str
    marca_modelo: str
    estado: str
    fecha_empeno: date
    fecha_vencimiento: date

class VentaPayload(BaseModel):
    precio_venta: float

class ReevaluoPayload(BaseModel):
    nuevo_prestamo: float
    nuevo_valuo: float
    nuevo_interes: float

class EmpenoResponse(EmpenoBase):
    id: int
    estado: str
    cliente_id: int
    cliente: Optional[ClienteBase] = None
    class Config:
        from_attributes = True

class DashboardFila(BaseModel):
    cliente: str
    accion: str
    articulo: str
    monto: float
    fecha: str
