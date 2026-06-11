# services/gastos_service.py
import calendar
import logging
import os
from datetime import date, datetime, timedelta

from models import get_conn

logger = logging.getLogger(__name__)

FRECUENCIAS = ['semanal', 'quincenal', 'mensual', 'anual']
METODOS_PAGO = ['Efectivo', 'Transferencia', 'Tarjeta', 'Cheque', 'Débito automático']


# ── Fechas ────────────────────────────────────────────────────────────────────

def _siguiente_fecha(fecha_str, frecuencia):
    d = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    if frecuencia == 'semanal':
        return (d + timedelta(days=7)).strftime('%Y-%m-%d')
    elif frecuencia == 'quincenal':
        return (d + timedelta(days=15)).strftime('%Y-%m-%d')
    elif frecuencia == 'mensual':
        month = d.month + 1
        year  = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(d.day, max_day)).strftime('%Y-%m-%d')
    elif frecuencia == 'anual':
        try:
            return date(d.year + 1, d.month, d.day).strftime('%Y-%m-%d')
        except ValueError:
            return date(d.year + 1, d.month, 28).strftime('%Y-%m-%d')
    return None


# ── Categorías ────────────────────────────────────────────────────────────────

def listar_categorias(solo_activas=True):
    conn = get_conn()
    sql = "SELECT * FROM categorias_gasto"
    if solo_activas:
        sql += " WHERE activo = 1"
    sql += " ORDER BY nombre"
    cats = conn.execute(sql).fetchall()
    conn.close()
    return cats


def get_categoria(cat_id):
    conn = get_conn()
    c = conn.execute("SELECT * FROM categorias_gasto WHERE id = ?", (cat_id,)).fetchone()
    conn.close()
    return c


def crear_categoria(nombre, descripcion=''):
    nombre = nombre.strip()
    if not nombre:
        return False, "El nombre es obligatorio"
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO categorias_gasto (nombre, descripcion) VALUES (?, ?)",
            (nombre, descripcion.strip())
        )
        conn.commit()
        return True, conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as e:
        conn.rollback()
        if 'UNIQUE' in str(e):
            return False, f"La categoría '{nombre}' ya existe"
        return False, str(e)
    finally:
        conn.close()


def actualizar_categoria(cat_id, nombre, descripcion='', activo=1):
    nombre = nombre.strip()
    if not nombre:
        return False, "El nombre es obligatorio"
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE categorias_gasto SET nombre=?, descripcion=?, activo=? WHERE id=?",
            (nombre, descripcion.strip(), activo, cat_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        if 'UNIQUE' in str(e):
            return False, f"La categoría '{nombre}' ya existe"
        return False, str(e)
    finally:
        conn.close()


def eliminar_categoria(cat_id):
    conn = get_conn()
    en_uso = conn.execute(
        "SELECT COUNT(*) FROM gastos WHERE categoria_id = ?", (cat_id,)
    ).fetchone()[0]
    conn.close()
    if en_uso:
        return False, "La categoría tiene gastos asociados; desactivala en lugar de eliminarla"
    conn = get_conn()
    conn.execute("DELETE FROM categorias_gasto WHERE id = ?", (cat_id,))
    conn.commit()
    conn.close()
    return True, None


# ── Gastos ────────────────────────────────────────────────────────────────────

def listar_gastos(categoria_id=None, fecha_desde=None, fecha_hasta=None,
                  solo_recurrentes=False, page=1, per_page=25):
    conn = get_conn()
    conds, params = [], []

    if categoria_id:
        conds.append("g.categoria_id = ?"); params.append(categoria_id)
    if fecha_desde:
        conds.append("g.fecha >= ?");       params.append(fecha_desde)
    if fecha_hasta:
        conds.append("g.fecha <= ?");       params.append(fecha_hasta)
    if solo_recurrentes:
        conds.append("g.es_recurrente = 1")

    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM gastos g {where}", params
    ).fetchone()[0]

    offset = (page - 1) * per_page
    filas = conn.execute(f"""
        SELECT g.*, cg.nombre AS categoria_nombre
        FROM gastos g
        JOIN categorias_gasto cg ON g.categoria_id = cg.id
        {where}
        ORDER BY g.fecha DESC, g.id DESC
        LIMIT ? OFFSET ?
    """, (*params, per_page, offset)).fetchall()

    conn.close()
    return filas, total


def get_gasto(gasto_id):
    conn = get_conn()
    g = conn.execute("""
        SELECT g.*, cg.nombre AS categoria_nombre
        FROM gastos g
        JOIN categorias_gasto cg ON g.categoria_id = cg.id
        WHERE g.id = ?
    """, (gasto_id,)).fetchone()
    conn.close()
    return g


def crear_gasto(categoria_id, descripcion, monto, fecha, metodo_pago=None,
                es_recurrente=False, frecuencia=None, observaciones=None,
                archivo_nombre=None, archivo_ruta=None, usuario_id=None):
    if not descripcion.strip():
        return False, "La descripción es obligatoria"
    if monto <= 0:
        return False, "El monto debe ser mayor a cero"

    fecha_prox = None
    if es_recurrente and frecuencia:
        fecha_prox = _siguiente_fecha(fecha, frecuencia)

    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO gastos
              (categoria_id, descripcion, monto, fecha, metodo_pago,
               es_recurrente, frecuencia, fecha_prox_recurrencia,
               archivo_nombre, archivo_ruta, observaciones, creado_por)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (categoria_id, descripcion.strip(), monto, fecha,
              metodo_pago or None, 1 if es_recurrente else 0,
              frecuencia or None, fecha_prox,
              archivo_nombre or None, archivo_ruta or None,
              observaciones.strip() if observaciones else None,
              usuario_id))
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Registrar egreso en caja (misma transacción)
        from services.caja_service import registrar_movimiento_en_conn
        registrar_movimiento_en_conn(
            conn, 'egreso', 'gasto', new_id,
            f"Gasto: {descripcion.strip()}",
            monto, metodo_pago, usuario_id, fecha
        )
        conn.commit()
        return True, new_id
    except Exception as e:
        conn.rollback()
        logger.error("crear_gasto error: %s", e)
        return False, str(e)
    finally:
        conn.close()


def actualizar_gasto(gasto_id, categoria_id, descripcion, monto, fecha,
                     metodo_pago=None, es_recurrente=False, frecuencia=None,
                     observaciones=None, archivo_nombre=None, archivo_ruta=None):
    if not descripcion.strip():
        return False, "La descripción es obligatoria"
    if monto <= 0:
        return False, "El monto debe ser mayor a cero"

    conn = get_conn()
    try:
        actual = conn.execute("SELECT * FROM gastos WHERE id=?", (gasto_id,)).fetchone()
        if not actual:
            return False, "Gasto no encontrado"

        fecha_prox = actual['fecha_prox_recurrencia']
        if es_recurrente and frecuencia:
            if not fecha_prox:
                fecha_prox = _siguiente_fecha(fecha, frecuencia)
        elif not es_recurrente:
            fecha_prox = None

        # Mantener archivo si no se pasa uno nuevo
        arch_nombre = archivo_nombre or actual['archivo_nombre']
        arch_ruta   = archivo_ruta   or actual['archivo_ruta']

        conn.execute("""
            UPDATE gastos SET
              categoria_id=?, descripcion=?, monto=?, fecha=?,
              metodo_pago=?, es_recurrente=?, frecuencia=?,
              fecha_prox_recurrencia=?, archivo_nombre=?, archivo_ruta=?,
              observaciones=?
            WHERE id=?
        """, (categoria_id, descripcion.strip(), monto, fecha,
              metodo_pago or None, 1 if es_recurrente else 0,
              frecuencia or None, fecha_prox,
              arch_nombre, arch_ruta,
              observaciones.strip() if observaciones else None,
              gasto_id))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("actualizar_gasto error: %s", e)
        return False, str(e)
    finally:
        conn.close()


def eliminar_gasto(gasto_id):
    conn = get_conn()
    try:
        g = conn.execute("SELECT archivo_ruta FROM gastos WHERE id=?", (gasto_id,)).fetchone()
        if not g:
            return False, "Gasto no encontrado"
        conn.execute("DELETE FROM gastos WHERE id=?", (gasto_id,))
        conn.commit()
        # Eliminar archivo físico si existe
        if g['archivo_ruta'] and os.path.isfile(g['archivo_ruta']):
            try:
                os.remove(g['archivo_ruta'])
            except OSError:
                pass
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error("eliminar_gasto error: %s", e)
        return False, str(e)
    finally:
        conn.close()


# ── Recurrentes ───────────────────────────────────────────────────────────────

def generar_recurrentes():
    """Genera instancias de gastos recurrentes vencidos. Llamar al cargar la lista."""
    hoy = date.today().strftime('%Y-%m-%d')
    conn = get_conn()
    try:
        pendientes = conn.execute("""
            SELECT * FROM gastos
            WHERE es_recurrente = 1
              AND fecha_prox_recurrencia IS NOT NULL
              AND fecha_prox_recurrencia <= ?
        """, (hoy,)).fetchall()

        generados = 0
        for g in pendientes:
            # Generar todas las instancias atrasadas (por si pasaron varios períodos)
            prox = g['fecha_prox_recurrencia']
            while prox and prox <= hoy:
                conn.execute("""
                    INSERT INTO gastos
                      (categoria_id, descripcion, monto, fecha, metodo_pago,
                       es_recurrente, gasto_padre_id, observaciones, creado_por)
                    VALUES (?,?,?,?,?,0,?,?,?)
                """, (g['categoria_id'], g['descripcion'], g['monto'],
                      prox, g['metodo_pago'], g['id'],
                      g['observaciones'], None))
                prox = _siguiente_fecha(prox, g['frecuencia'])
                generados += 1

            # Actualizar fecha próxima en el template
            conn.execute(
                "UPDATE gastos SET fecha_prox_recurrencia=? WHERE id=?",
                (prox, g['id'])
            )
        if generados:
            conn.commit()
        return generados
    except Exception as e:
        conn.rollback()
        logger.error("generar_recurrentes error: %s", e)
        return 0
    finally:
        conn.close()


# ── Totales (para Módulo 5) ───────────────────────────────────────────────────

def get_totales_por_categoria(fecha_desde, fecha_hasta):
    conn = get_conn()
    filas = conn.execute("""
        SELECT cg.nombre AS categoria, SUM(g.monto) AS total
        FROM gastos g
        JOIN categorias_gasto cg ON g.categoria_id = cg.id
        WHERE g.fecha BETWEEN ? AND ?
        GROUP BY cg.nombre
        ORDER BY total DESC
    """, (fecha_desde, fecha_hasta)).fetchall()
    conn.close()
    return filas


def get_total_mes(year, month):
    fecha_desde = f"{year}-{month:02d}-01"
    last_day    = calendar.monthrange(year, month)[1]
    fecha_hasta = f"{year}-{month:02d}-{last_day}"
    conn = get_conn()
    total = conn.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha BETWEEN ? AND ?",
        (fecha_desde, fecha_hasta)
    ).fetchone()[0]
    conn.close()
    return total
