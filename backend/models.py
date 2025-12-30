from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255))
    nombre_completo = Column(String(100))
    rol = Column(String(20), default="empleado")

class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100))
    apellidos = Column(String(100))
    telefono = Column(String(20))
    ine = Column(String(50))
    direccion = Column(String(200))
    # Vinculamos el cliente con su usuario de login
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Relación con empeños
    empenos = relationship("Empeno", back_populates="cliente")

class Empeno(Base):
    __tablename__ = "empenos"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    
    # Datos Articulo
    categoria = Column(String(50))
    marca_modelo = Column(String(150))
    descripcion = Column(Text)
    num_serie_peso = Column(String(100), nullable=True)
    observaciones = Column(String(200), nullable=True)
    
    # Datos Financieros
    valor_valuo = Column(Float)
    monto_prestamo = Column(Float)
    interes_mensual_pct = Column(Float)
    
    # Fechas y Estado
    fecha_empeno = Column(Date)
    fecha_vencimiento = Column(Date)
    estado = Column(String(20), default="Vigente") # Vigente, Vencido, Desempeñado, Rematado, Vendido
    
    # Relaciones
    cliente = relationship("Cliente", back_populates="empenos")
