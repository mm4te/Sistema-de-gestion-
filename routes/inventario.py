# routes/inventario.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
from models import get_productos, add_producto, update_producto, delete_producto, get_producto_by_id
import csv
import sqlite3

inventario_bp = Blueprint('inventario', __name__)

@inventario_bp.route('/inventario')
def inventario():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    filtro_stock = request.args.get('stock', '')
    orden = request.args.get('orden', '')
    productos, total = get_productos(search_query, filtro_stock, orden, page)
    total_pages = (total + 19) // 20
    return render_template('inventario.html', productos=productos, page=page, total_pages=total_pages,
                           search_query=search_query, filtro_stock=filtro_stock, orden=orden)

@inventario_bp.route('/nuevo_producto', methods=['GET', 'POST'])
def nuevo_producto():
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        stock = request.form.get('stock', '').strip()
        if not all([codigo, descripcion, precio, stock]):
            flash("❌ Todos los campos son obligatorios", "error")
        else:
            try:
                precio = float(precio)
                stock = int(stock)
                if precio <= 0 or stock < 0:
                    raise ValueError
                add_producto(codigo, descripcion, precio, stock)
                flash("✅ Producto creado correctamente", "success")
                return redirect(url_for('inventario.inventario'))
            except sqlite3.IntegrityError:
                flash("❌ El código ya existe. Usa uno único.", "error")
            except Exception as e:
                flash(f"❌ Error al guardar: {str(e)}", "error")
    return render_template('nuevo_producto.html')

@inventario_bp.route('/editar_producto/<int:producto_id>', methods=['GET', 'POST'])
def editar_producto(producto_id):
    producto = get_producto_by_id(producto_id)
    if not producto:
        flash("Producto no encontrado", "error")
        return redirect(url_for('inventario.inventario'))
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        stock = request.form.get('stock', '').strip()
        if not all([codigo, descripcion, precio, stock]):
            flash("❌ Todos los campos son obligatorios", "error")
        else:
            try:
                precio = float(precio)
                stock = int(stock)
                if precio <= 0 or stock < 0:
                    raise ValueError
                update_producto(producto_id, codigo, descripcion, precio, stock)
                flash("✅ Producto actualizado correctamente", "success")
                return redirect(url_for('inventario.inventario'))
            except sqlite3.IntegrityError:
                flash("❌ El código ya existe. Usa uno único.", "error")
            except Exception as e:
                flash(f"❌ Error: {str(e)}", "error")
    return render_template('editar_producto.html', producto=producto)

@inventario_bp.route('/eliminar_producto/<int:producto_id>', methods=['POST'])
def eliminar_producto(producto_id):
    if delete_producto(producto_id):
        flash("✅ Producto eliminado", "success")
    else:
        flash("⚠️ No se puede eliminar: el producto ya fue vendido.", "error")
    return redirect(url_for('inventario.inventario'))

@inventario_bp.route('/cargar_tiendanube', methods=['POST'])
def cargar_tiendanube():
    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        flash("❌ Archivo inválido. Debe ser .csv", "error")
        return redirect(url_for('inventario.inventario'))
    
    try:
        raw_data = file.stream.read()
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                decoded = raw_data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Codificación no soportada")
        
        reader = csv.reader(decoded.splitlines(), delimiter=';')
        next(reader)
        conn = sqlite3.connect('negocio.db')
        cursor = conn.cursor()
        count = 0
        for row in reader:
            if len(row) < 17: continue
            nombre = row[1].strip()
            precio_str = float(row[9].replace(',', '')) if row[9] else 0.0
            stock_str = row[15] if row[15] else '0'
            sku = row[16].strip() or None
            if not sku and not nombre: continue
            try:
                precio = float(precio_str)
                stock = int(float(stock_str))
            except ValueError:
                continue
            codigo = sku or nombre[:20].replace(' ', '_')
            cursor.execute("""
                INSERT INTO productos (codigo, descripcion, precio, stock)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(codigo) DO UPDATE SET
                    descripcion = excluded.descripcion,
                    precio = excluded.precio,
                    stock = excluded.stock
            """, (codigo, nombre, precio, stock))
            count += 1
        conn.commit()
        conn.close()
        flash(f"✅ {count} productos cargados/actualizados desde Tienda Nube", "success")
    except Exception as e:
        flash(f"❌ Error al procesar el archivo: {str(e)}", "error")
    return redirect(url_for('inventario.inventario'))