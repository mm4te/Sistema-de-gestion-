# routes/gastos.py
import os
import uuid

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, session, url_for)
from werkzeug.utils import secure_filename

from routes import login_required, require_permiso
from services.gastos_service import (
    FRECUENCIAS, METODOS_PAGO,
    actualizar_categoria, actualizar_gasto,
    crear_categoria, crear_gasto,
    eliminar_categoria, eliminar_gasto,
    generar_recurrentes, get_categoria, get_gasto,
    listar_categorias, listar_gastos,
)

gastos_bp = Blueprint('gastos', __name__)

EXTENSIONES_PERMITIDAS = {'pdf', 'jpg', 'jpeg', 'png', 'webp'}


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in EXTENSIONES_PERMITIDAS


def _guardar_archivo(file):
    """Guarda el archivo subido; devuelve (nombre_original, ruta_absoluta) o (None, None)."""
    if not file or not file.filename:
        return None, None
    if not _allowed(file.filename):
        return None, None
    ext = secure_filename(file.filename).rsplit('.', 1)[-1].lower()
    nombre_guardado = f"{uuid.uuid4().hex}.{ext}"
    carpeta = current_app.config['UPLOAD_FOLDER_GASTOS']
    ruta = os.path.join(carpeta, nombre_guardado)
    file.save(ruta)
    return secure_filename(file.filename), ruta


# ── Lista ─────────────────────────────────────────────────────────────────────

@gastos_bp.route('/gastos')
@login_required
@require_permiso('gastos', 'ver')
def lista():
    generar_recurrentes()

    page         = request.args.get('page', 1, type=int)
    categoria_id = request.args.get('categoria_id', type=int)
    fecha_desde  = request.args.get('fecha_desde', '').strip() or None
    fecha_hasta  = request.args.get('fecha_hasta', '').strip() or None
    solo_recurrentes = request.args.get('recurrentes') == '1'

    filas, total = listar_gastos(
        categoria_id=categoria_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        solo_recurrentes=solo_recurrentes,
        page=page, per_page=25
    )
    total_pages  = (total + 24) // 25
    categorias   = listar_categorias()

    # Total filtrado
    from models import get_conn
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
    total_monto = conn.execute(
        f"SELECT COALESCE(SUM(monto),0) FROM gastos g {where}", params
    ).fetchone()[0]
    conn.close()

    return render_template('gastos/lista.html',
                           filas=filas, total=total,
                           page=page, total_pages=total_pages,
                           total_monto=total_monto,
                           categorias=categorias,
                           categoria_id_filtro=categoria_id or '',
                           fecha_desde=fecha_desde or '',
                           fecha_hasta=fecha_hasta or '',
                           solo_recurrentes=solo_recurrentes)


# ── Nuevo gasto ───────────────────────────────────────────────────────────────

@gastos_bp.route('/gastos/nuevo', methods=['GET', 'POST'])
@login_required
@require_permiso('gastos', 'crear')
def nuevo():
    categorias = listar_categorias()

    if request.method == 'POST':
        categoria_id  = request.form.get('categoria_id', type=int)
        descripcion   = request.form.get('descripcion', '').strip()
        monto_str     = request.form.get('monto', '0').replace(',', '.').strip()
        fecha         = request.form.get('fecha', '').strip()
        metodo_pago   = request.form.get('metodo_pago', '').strip() or None
        es_recurrente = request.form.get('es_recurrente') == '1'
        frecuencia    = request.form.get('frecuencia', '').strip() or None
        observaciones = request.form.get('observaciones', '').strip() or None

        try:
            monto = float(monto_str)
        except ValueError:
            flash("❌ Monto inválido", "error")
            return render_template('gastos/form.html', gasto=None,
                                   categorias=categorias, frecuencias=FRECUENCIAS,
                                   metodos_pago=METODOS_PAGO, titulo="Nuevo Gasto")

        archivo_nombre, archivo_ruta = None, None
        file = request.files.get('archivo')
        if file and file.filename:
            if not _allowed(file.filename):
                flash("❌ Tipo de archivo no permitido (pdf, jpg, png, webp)", "error")
                return render_template('gastos/form.html', gasto=None,
                                       categorias=categorias, frecuencias=FRECUENCIAS,
                                       metodos_pago=METODOS_PAGO, titulo="Nuevo Gasto")
            archivo_nombre, archivo_ruta = _guardar_archivo(file)

        ok, result = crear_gasto(
            categoria_id=categoria_id, descripcion=descripcion,
            monto=monto, fecha=fecha, metodo_pago=metodo_pago,
            es_recurrente=es_recurrente, frecuencia=frecuencia,
            observaciones=observaciones,
            archivo_nombre=archivo_nombre, archivo_ruta=archivo_ruta,
            usuario_id=session.get('user_id')
        )
        if ok:
            flash("✅ Gasto registrado correctamente", "success")
            return redirect(url_for('gastos.lista'))
        # Si falló y se guardó archivo, eliminarlo
        if archivo_ruta and os.path.isfile(archivo_ruta):
            os.remove(archivo_ruta)
        flash(f"❌ {result}", "error")

    from datetime import date
    return render_template('gastos/form.html',
                           gasto=None, categorias=categorias,
                           frecuencias=FRECUENCIAS, metodos_pago=METODOS_PAGO,
                           hoy=date.today().strftime('%Y-%m-%d'),
                           titulo="Nuevo Gasto")


# ── Editar gasto ──────────────────────────────────────────────────────────────

@gastos_bp.route('/gastos/<int:gasto_id>/editar', methods=['GET', 'POST'])
@login_required
@require_permiso('gastos', 'editar')
def editar(gasto_id):
    gasto = get_gasto(gasto_id)
    if not gasto:
        flash("❌ Gasto no encontrado", "error")
        return redirect(url_for('gastos.lista'))

    categorias = listar_categorias()

    if request.method == 'POST':
        categoria_id  = request.form.get('categoria_id', type=int)
        descripcion   = request.form.get('descripcion', '').strip()
        monto_str     = request.form.get('monto', '0').replace(',', '.').strip()
        fecha         = request.form.get('fecha', '').strip()
        metodo_pago   = request.form.get('metodo_pago', '').strip() or None
        es_recurrente = request.form.get('es_recurrente') == '1'
        frecuencia    = request.form.get('frecuencia', '').strip() or None
        observaciones = request.form.get('observaciones', '').strip() or None
        borrar_archivo = request.form.get('borrar_archivo') == '1'

        try:
            monto = float(monto_str)
        except ValueError:
            flash("❌ Monto inválido", "error")
            return render_template('gastos/form.html', gasto=gasto,
                                   categorias=categorias, frecuencias=FRECUENCIAS,
                                   metodos_pago=METODOS_PAGO, titulo="Editar Gasto")

        archivo_nombre, archivo_ruta = None, None
        file = request.files.get('archivo')
        if file and file.filename:
            if not _allowed(file.filename):
                flash("❌ Tipo de archivo no permitido (pdf, jpg, png, webp)", "error")
                return render_template('gastos/form.html', gasto=gasto,
                                       categorias=categorias, frecuencias=FRECUENCIAS,
                                       metodos_pago=METODOS_PAGO, titulo="Editar Gasto")
            # Eliminar archivo anterior
            if gasto['archivo_ruta'] and os.path.isfile(gasto['archivo_ruta']):
                os.remove(gasto['archivo_ruta'])
            archivo_nombre, archivo_ruta = _guardar_archivo(file)
        elif borrar_archivo:
            if gasto['archivo_ruta'] and os.path.isfile(gasto['archivo_ruta']):
                os.remove(gasto['archivo_ruta'])
            archivo_nombre, archivo_ruta = '', ''  # vacío = borrar en servicio

        ok, err = actualizar_gasto(
            gasto_id, categoria_id, descripcion, monto, fecha,
            metodo_pago, es_recurrente, frecuencia, observaciones,
            archivo_nombre or None, archivo_ruta or None
        )
        if ok:
            flash("✅ Gasto actualizado", "success")
            return redirect(url_for('gastos.lista'))
        flash(f"❌ {err}", "error")

    return render_template('gastos/form.html',
                           gasto=gasto, categorias=categorias,
                           frecuencias=FRECUENCIAS, metodos_pago=METODOS_PAGO,
                           titulo="Editar Gasto")


# ── Eliminar gasto ────────────────────────────────────────────────────────────

@gastos_bp.route('/gastos/<int:gasto_id>/eliminar', methods=['POST'])
@login_required
@require_permiso('gastos', 'eliminar')
def eliminar(gasto_id):
    ok, msg = eliminar_gasto(gasto_id)
    if ok:
        flash("✅ Gasto eliminado", "success")
    else:
        flash(f"❌ {msg}", "error")
    return redirect(url_for('gastos.lista'))


# ── Descargar adjunto ─────────────────────────────────────────────────────────

@gastos_bp.route('/gastos/<int:gasto_id>/archivo')
@login_required
@require_permiso('gastos', 'ver')
def descargar_archivo(gasto_id):
    g = get_gasto(gasto_id)
    if not g or not g['archivo_ruta'] or not os.path.isfile(g['archivo_ruta']):
        abort(404)
    return send_file(g['archivo_ruta'], as_attachment=True,
                     download_name=g['archivo_nombre'])


# ── CRUD Categorías ───────────────────────────────────────────────────────────

@gastos_bp.route('/gastos/categorias')
@login_required
@require_permiso('gastos', 'ver')
def categorias():
    cats = listar_categorias(solo_activas=False)
    return render_template('gastos/categorias.html', categorias=cats)


@gastos_bp.route('/gastos/categorias/nueva', methods=['POST'])
@login_required
@require_permiso('gastos', 'crear')
def nueva_categoria():
    nombre = request.form.get('nombre', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    ok, result = crear_categoria(nombre, descripcion)
    if ok:
        flash(f"✅ Categoría '{nombre}' creada", "success")
    else:
        flash(f"❌ {result}", "error")
    return redirect(url_for('gastos.categorias'))


@gastos_bp.route('/gastos/categorias/<int:cat_id>/editar', methods=['POST'])
@login_required
@require_permiso('gastos', 'editar')
def editar_categoria(cat_id):
    nombre      = request.form.get('nombre', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    activo      = 1 if request.form.get('activo') == '1' else 0
    ok, err = actualizar_categoria(cat_id, nombre, descripcion, activo)
    if ok:
        flash("✅ Categoría actualizada", "success")
    else:
        flash(f"❌ {err}", "error")
    return redirect(url_for('gastos.categorias'))


@gastos_bp.route('/gastos/categorias/<int:cat_id>/eliminar', methods=['POST'])
@login_required
@require_permiso('gastos', 'eliminar')
def eliminar_categoria_route(cat_id):
    ok, err = eliminar_categoria(cat_id)
    if ok:
        flash("✅ Categoría eliminada", "success")
    else:
        flash(f"❌ {err}", "error")
    return redirect(url_for('gastos.categorias'))
