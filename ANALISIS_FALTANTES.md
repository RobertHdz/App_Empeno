# Análisis de Funcionalidades Faltantes - App Empeño

## Estado Actual del Proyecto

La aplicación de empeño es un sistema completo con:
- **Backend**: FastAPI con SQLAlchemy
- **Frontend**: HTML/CSS/JavaScript vanilla
- **Base de datos**: MySQL 8.0
- **Arquitectura**: Cliente-Servidor con API REST

## Funcionalidades Faltantes Identificadas

### 1. **Endpoint `/dashboard/tabla` - CRÍTICO**
**Ubicación**: `backend/main.py`
**Problema**: El frontend (`index.html` línea 139) hace una petición a `/dashboard/tabla` pero este endpoint NO existe en el backend.
**Impacto**: El dashboard principal no puede mostrar las acciones rápidas/recientes.
**Solución requerida**: Crear endpoint que retorne las últimas acciones (empeños, refrendos, desempeños, etc.)

### 2. **Funcionalidad de Revalúo - INCOMPLETA**
**Archivos afectados**: 
- `frontend/reevaluo.html` (existe pero sin lógica)
- Backend: NO existe endpoint `/empenos/{id}/reevaluo`
**Problema**: La página de revalúo existe pero no tiene funcionalidad implementada
**Solución requerida**: 
- Crear endpoint POST para actualizar el valor de avalúo de un empeño
- Implementar lógica JavaScript en el frontend

### 3. **Funcionalidad de Remate/Venta - INCOMPLETA**
**Archivos afectados**:
- `frontend/remate.html` (existe pero sin lógica completa)
- Backend: NO existe endpoint `/empenos/{id}/vender` o `/empenos/{id}/rematar`
**Problema**: No se puede marcar un empeño como "Vendido" o "Rematado"
**Solución requerida**:
- Crear endpoint POST para cambiar estado a "Vendido" con monto de venta
- Implementar lógica JavaScript en el frontend

### 4. **Gestión Completa de Clientes - PARCIAL**
**Archivos afectados**:
- `frontend/clientes.html` (existe)
- Backend: Existe búsqueda pero falta edición/actualización
**Problema**: No se pueden editar datos de clientes existentes
**Solución requerida**:
- Crear endpoint PUT `/clientes/{id}` para actualizar información
- Agregar formulario de edición en el frontend

### 5. **Historial de Empeños - PARCIAL**
**Archivos afectados**:
- `frontend/history.html` (existe)
- Backend: Existe `/empenos/todos` pero sin filtros avanzados
**Problema**: No hay filtros por fecha, estado, o cliente específico
**Solución requerida**:
- Mejorar endpoint con parámetros de query para filtrado
- Implementar filtros en el frontend

### 6. **Sistema de Registro de Acciones/Auditoría - NO EXISTE**
**Problema**: No hay tabla ni modelo para registrar las acciones realizadas (necesario para `/dashboard/tabla`)
**Solución requerida**:
- Crear modelo `Accion` o `HistorialAcciones` en la base de datos
- Registrar automáticamente cada operación (nuevo empeño, refrendo, desempeño, etc.)
- Crear endpoint para consultar estas acciones

## Prioridades de Implementación

### **ALTA PRIORIDAD** (Bloquean funcionalidad principal)
1. Endpoint `/dashboard/tabla` + Modelo de Acciones
2. Endpoint de Revalúo
3. Endpoint de Venta/Remate

### **MEDIA PRIORIDAD** (Mejoran experiencia)
4. Edición de clientes
5. Filtros avanzados en historial

### **BAJA PRIORIDAD** (Mejoras futuras)
6. Reportes en PDF
7. Notificaciones de vencimiento
8. Dashboard con gráficas

## Archivos que Necesitan Modificación

### Backend (`backend/main.py`)
- ✅ Crear modelo `Accion` en `models.py`
- ✅ Crear endpoint `GET /dashboard/tabla`
- ✅ Crear endpoint `POST /empenos/{id}/reevaluo`
- ✅ Crear endpoint `POST /empenos/{id}/vender`
- ✅ Crear endpoint `PUT /clientes/{id}`
- ✅ Agregar registro automático de acciones en operaciones existentes

### Frontend
- ✅ Completar `reevaluo.html` con lógica JavaScript
- ✅ Completar `remate.html` con lógica JavaScript
- ✅ Agregar formulario de edición en `clientes.html`
- ✅ Agregar filtros en `history.html`

## Estimación de Trabajo
- **Tiempo estimado**: 3-4 horas de desarrollo
- **Complejidad**: Media
- **Riesgo**: Bajo (estructura ya establecida)
