# routes/ventas.py
import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import get_producto_by_id, registrar_venta
from routes import login_required

ventas_bp = Blueprint('ventas', __name__)

@ventas_bp.route('/guardar_cliente', methods=['POST'])
@login_required
def guardar_cliente():
    cliente_id = request.form.get('cliente_id')
    if cliente_id:
        session['cliente_id_seleccionado'] = int(cliente_id)
    return redirect(url_for('ventas.ventas'))

@ventas_bp.route('/ventas')
@login_required
def ventas():
    cliente_id = session.get('cliente_id_seleccionado')
    conn = sqlite3.connect('negocio.db')
    clientes  = conn.execute("SELECT id, nombre FROM clientes").fetchall()
    productos = conn.execute(
        "SELECT id, sku, descripcion, precio, stock FROM productos WHERE stock > 0 OR stock IS NULL"
    ).fetchall()
    conn.close()
    carrito = session.get('carrito', [])
    total   = sum(item['precio'] * item['cantidad'] for item in carrito)
    return render_template('ventas.html', clientes=clientes, productos=productos,
                           carrito=carrito, total=total,
                           cliente_id_seleccionado=cliente_id)

@ventas_bp.route('/cliente/<int:cliente_id>')
@login_required
def historial_cliente(cliente_id):
    conn = sqlite3.connect('negocio.db')
    cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not cliente:
        flash("Cliente no encontrado", "error")
        conn.close()
        return redirect(url_for('clientes.clientes'))
    ventas = conn.execute("""
        SELECT v.id, v.fecha, v.total FROM ventas v
        WHERE v.cliente_id = ? ORDER BY v.fecha DESC
    """, (cliente_id,)).fetchall()
    ventas_detalle = []
    for venta in ventas:
        detalle = conn.execute("""
            SELECT p.descripcion, dv.cantidad, dv.precio_unitario
            FROM detalle_venta dv
            JOIN productos p ON dv.producto_id = p.id
            WHERE dv.venta_id = ?
        """, (venta[0],)).fetchall()
        ventas_detalle.append({'id': venta[0], 'fecha': venta[1], 'total': venta[2], 'detalle': detalle})
    conn.close()
    return render_template('historial_cliente.html', cliente=cliente, ventas=ventas_detalle)

@ventas_bp.route('/agregar_al_carrito', methods=['POST'])
@login_required
def agregar_al_carrito():
    producto_id = request.form.get('producto_id')
    cantidad    = int(request.form.get('cantidad', 1))
    if not producto_id or cantidad <= 0:
        flash("❌ Cantidad o producto inválido", "error")
        return redirect(url_for('ventas.ventas'))
    p = get_producto_by_id(producto_id)
    if not p:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for('ventas.ventas'))
    # Acceso por nombre de columna gracias a sqlite3.Row
    stock = p['stock']
    if stock is not None and cantidad > stock:
        flash(f"❌ Stock insuficiente. Disponible: {stock}", "error")
        return redirect(url_for('ventas.ventas'))
    carrito = session.get('carrito', [])
    for item in carrito:
        if item['id'] == p['id']:
            nueva_cant = item['cantidad'] + cantidad
            if stock is None or nueva_cant <= stock:
                item['cantidad'] = nueva_cant
                flash(f"✅ {p['descripcion']} cantidad actualizada", "success")
            else:
                flash(f"❌ No hay suficiente stock para {p['descripcion']}", "error")
            session['carrito'] = carrito
            return redirect(url_for('ventas.ventas'))
    carrito.append({
        'id':              p['id'],
        'sku':             p['sku'],
        'descripcion':     p['descripcion'],
        'precio_original': float(p['precio']),
        'precio':          float(p['precio']),
        'cantidad':        cantidad
    })
    session['carrito'] = carrito
    flash(f"✅ {p['descripcion']} agregado al carrito", "success")
    return redirect(url_for('ventas.ventas'))

@ventas_bp.route('/actualizar_precio_carrito', methods=['POST'])
@login_required
def actualizar_precio_carrito():
    index        = int(request.form.get('index'))
    nuevo_precio = float(request.form.get('nuevo_precio'))
    carrito = session.get('carrito', [])
    if 0 <= index < len(carrito) and nuevo_precio > 0:
        carrito[index]['precio'] = nuevo_precio
        session['carrito'] = carrito
        flash("✅ Precio actualizado", "success")
    else:
        flash("❌ Error al actualizar el precio", "error")
    return redirect(url_for('ventas.ventas'))

@ventas_bp.route('/actualizar_carrito', methods=['POST'])
@login_required
def actualizar_carrito():
    index          = int(request.form.get('index'))
    nueva_cantidad = int(request.form.get('cantidad'))
    carrito = session.get('carrito', [])
    if not (0 <= index < len(carrito)) or nueva_cantidad <= 0:
        flash("❌ Datos inválidos", "error")
        return redirect(url_for('ventas.ventas'))
    item  = carrito[index]
    p     = get_producto_by_id(item['id'])
    stock = p['stock'] if p else 0
    if not p or (stock is not None and nueva_cantidad > stock):
        flash(f"❌ Stock insuficiente. Disponible: {stock}", "error")
        return redirect(url_for('ventas.ventas'))
    item['cantidad'] = nueva_cantidad
    session['carrito'] = carrito
    flash("✅ Cantidad actualizada", "success")
    return redirect(url_for('ventas.ventas'))

@ventas_bp.route('/eliminar_del_carrito/<int:index>')
@login_required
def eliminar_del_carrito(index):
    carrito = session.get('carrito', [])
    if 0 <= index < len(carrito):
        carrito.pop(index)
        session['carrito'] = carrito
    return redirect(url_for('ventas.ventas'))

@ventas_bp.route('/vaciar_carrito')
@login_required
def vaciar_carrito():
    session.pop('carrito', None)
    return redirect(url_for('ventas.ventas'))

@ventas_bp.route('/seleccionar_pago', methods=['GET', 'POST'])
@login_required
def seleccionar_pago():
    carrito    = session.get('carrito', [])
    cliente_id = session.get('cliente_id_seleccionado')
    if not carrito or not cliente_id:
        flash("❌ Carrito vacío o cliente no seleccionado", "error")
        return redirect(url_for('ventas.ventas'))
    if request.method == 'POST':
        metodo = request.form.get('metodo_pago')
        cuotas = request.form.get('cuotas', type=int)
        if metodo not in ['efectivo', 'transferencia', 'tarjeta']:
            flash("❌ Método de pago inválido", "error")
            return redirect(request.url)
        if metodo == 'tarjeta' and cuotas not in [2, 3, 6]:
            flash("❌ Cuotas inválidas", "error")
            return redirect(request.url)
        session['metodo_pago'] = metodo
        session['cuotas_pago'] = cuotas if metodo == 'tarjeta' else None
        return redirect(url_for('ventas.confirmar_venta'))
    total = sum(item['precio'] * item['cantidad'] for item in carrito)
    return render_template('seleccionar_pago.html', total=total)

@ventas_bp.route('/confirmar_venta', methods=['POST'])
@login_required
def confirmar_venta():
    metodo_pago = request.form.get('metodo_pago')
    cuotas      = request.form.get('cuotas', type=int)
    carrito     = session.get('carrito', [])
    cliente_id  = session.get('cliente_id_seleccionado')
    if not carrito or not cliente_id or not metodo_pago:
        flash("❌ Datos incompletos", "error")
        return redirect(url_for('ventas.ventas'))
    if metodo_pago not in ['efectivo', 'transferencia', 'tarjeta']:
        flash("❌ Método de pago inválido", "error")
        return redirect(url_for('ventas.ventas'))
    if metodo_pago == 'tarjeta' and cuotas not in [2, 3, 6]:
        flash("❌ Cuotas inválidas", "error")
        return redirect(url_for('ventas.seleccionar_pago'))
    if metodo_pago != 'tarjeta':
        cuotas = None
    success, result = registrar_venta(cliente_id, carrito, metodo_pago, cuotas)
    if success:
        session.pop('carrito', None)
        session.pop('cliente_id_seleccionado', None)
        session.pop('metodo_pago', None)
        session.pop('cuotas_pago', None)
        flash("✅ Venta registrada con éxito", "success")
    else:
        flash(f"❌ Error al registrar venta: {result}", "error")
    return redirect(url_for('ventas.ventas'))
