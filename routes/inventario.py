# routes/inventario.py
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import get_productos, add_producto, update_producto, delete_producto, get_producto_by_id
from services.tiendanube_service import importar_productos_tn
from routes import login_required

inventario_bp = Blueprint('inventario', __name__)

@inventario_bp.route('/inventario')
@login_required
def inventario():
    page         = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    filtro_stock = request.args.get('stock', '')
    orden        = request.args.get('orden', '')
    productos, total = get_productos(search_query, filtro_stock, orden, page)
    total_pages = (total + 19) // 20
    return render_template('inventario.html', productos=productos, page=page,
                           total_pages=total_pages, search_query=search_query,
                           filtro_stock=filtro_stock, orden=orden)

@inventario_bp.route("/sync_tiendanube")
@login_required
def sync_tiendanube():
    resultado = importar_productos_tn()
    if resultado["ok"]:
        flash(resultado["mensaje"], "success")
    else:
        flash("Error: " + resultado["error"], "error")
    return redirect(url_for("inventario.inventario"))

@inventario_bp.route('/nuevo_producto', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    if request.method == 'POST':
        sku         = request.form.get('sku', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio      = request.form.get('precio', '').strip()
        stock       = request.form.get('stock', '').strip()
        if not all([sku, descripcion, precio, stock]):
            flash("❌ Todos los campos son obligatorios", "error")
        else:
            try:
                precio = float(precio)
                stock  = int(stock)
                if precio <= 0 or stock < 0:
                    raise ValueError
                add_producto(sku, descripcion, precio, stock)
                flash("✅ Producto creado correctamente", "success")
                return redirect(url_for('inventario.inventario'))
            except sqlite3.IntegrityError:
                flash("❌ El SKU ya existe. Usa uno único.", "error")
            except Exception as e:
                flash(f"❌ Error al guardar: {str(e)}", "error")
    return render_template('nuevo_producto.html')

@inventario_bp.route('/editar_producto/<int:producto_id>', methods=['GET', 'POST'])
@login_required
def editar_producto(producto_id):
    producto = get_producto_by_id(producto_id)
    if not producto:
        flash("Producto no encontrado", "error")
        return redirect(url_for('inventario.inventario'))
    if request.method == 'POST':
        sku         = request.form.get('sku', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio      = request.form.get('precio', '').strip()
        stock       = request.form.get('stock', '').strip()
        if not all([sku, descripcion, precio, stock]):
            flash("❌ Todos los campos son obligatorios", "error")
        else:
            try:
                precio = float(precio)
                stock  = int(stock)
                if precio <= 0 or stock < 0:
                    raise ValueError
                update_producto(producto_id, sku, descripcion, precio, stock)
                flash("✅ Producto actualizado correctamente", "success")
                return redirect(url_for('inventario.inventario'))
            except sqlite3.IntegrityError:
                flash("❌ El SKU ya existe. Usa uno único.", "error")
            except Exception as e:
                flash(f"❌ Error: {str(e)}", "error")
    return render_template('editar_producto.html', producto=producto)

@inventario_bp.route('/eliminar_producto/<int:producto_id>', methods=['POST'])
@login_required
def eliminar_producto(producto_id):
    if delete_producto(producto_id):
        flash("✅ Producto eliminado", "success")
    else:
        flash("⚠️ No se puede eliminar: el producto ya fue vendido.", "error")
    return redirect(url_for('inventario.inventario'))
