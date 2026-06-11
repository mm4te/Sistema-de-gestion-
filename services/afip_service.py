# services/afip_service.py
import base64
import io
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Cache del ticket WSAA en memoria (dura hasta su vencimiento)
_wsaa_cache = {}  # {servicio: {'token': str, 'sign': str, 'expira': datetime}}


# ── Helpers de configuración ─────────────────────────────────────────────────

def _cfg():
    from config.afip import AFIP_CONFIG
    cfg = AFIP_CONFIG
    if not cfg['cuit']:
        raise RuntimeError("AFIP_CUIT no está configurado en .env")
    if not os.path.exists(cfg['cert_path']):
        raise RuntimeError(f"Certificado AFIP no encontrado: {cfg['cert_path']}")
    if not os.path.exists(cfg['key_path']):
        raise RuntimeError(f"Clave privada AFIP no encontrada: {cfg['key_path']}")
    return cfg


# ── Autenticación WSAA ───────────────────────────────────────────────────────

def _crear_tra(servicio='wsfe'):
    """Crea el XML LoginTicketRequest para WSAA."""
    ahora   = datetime.now(timezone.utc)
    gen_t   = (ahora - timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    exp_t   = (ahora + timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    uid     = int(ahora.timestamp())
    xml     = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<loginTicketRequest version="1.0">'
        f'<header>'
        f'<uniqueId>{uid}</uniqueId>'
        f'<generationTime>{gen_t}</generationTime>'
        f'<expirationTime>{exp_t}</expirationTime>'
        f'</header>'
        f'<service>{servicio}</service>'
        f'</loginTicketRequest>'
    )
    return xml.encode('utf-8')


def _firmar_tra(tra_bytes):
    """Firma el TRA con CMS (PKCS#7) y devuelve el resultado en base64."""
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.hazmat.primitives.serialization.pkcs7 import (
        PKCS7Options, PKCS7SignatureBuilder,
    )

    cfg = _cfg()
    with open(cfg['cert_path'], 'rb') as f:
        cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    with open(cfg['key_path'], 'rb') as f:
        key = serialization.load_pem_private_key(f.read(), password=None,
                                                  backend=default_backend())

    cms = (
        PKCS7SignatureBuilder()
        .set_data(tra_bytes)
        .add_signer(cert, key, hashes.SHA256())
        .sign(Encoding.DER, [])          # contenido embebido, certificado incluido
    )
    return base64.b64encode(cms).decode('ascii')


def _obtener_ticket(servicio='wsfe'):
    """Devuelve (token, sign) del ticket WSAA, usando caché si está vigente."""
    from zeep import Client, Settings
    from config.afip import WSAA_WSDL

    ahora = datetime.now(timezone.utc)
    cache = _wsaa_cache.get(servicio)
    if cache and ahora < cache['expira']:
        return cache['token'], cache['sign']

    cfg     = _cfg()
    tra     = _crear_tra(servicio)
    cms_b64 = _firmar_tra(tra)

    client  = Client(
        wsdl=WSAA_WSDL[cfg['modo']],
        settings=Settings(strict=False, xml_huge_tree=True),
    )
    resp_xml = client.service.loginCms(in0=cms_b64)

    root  = ET.fromstring(resp_xml)
    token = root.findtext('credentials/token')
    sign  = root.findtext('credentials/sign')

    try:
        exp_str = root.findtext('header/expirationTime') or ''
        exp_dt  = datetime.fromisoformat(exp_str)
        expira  = exp_dt.astimezone(timezone.utc) - timedelta(minutes=5)
    except Exception:
        expira = ahora + timedelta(hours=11, minutes=50)

    _wsaa_cache[servicio] = {'token': token, 'sign': sign, 'expira': expira}
    logger.info("Ticket WSAA obtenido para servicio '%s' (expira %s)", servicio, expira)
    return token, sign


# ── Cliente WSFE ─────────────────────────────────────────────────────────────

def _wsfe_client():
    from zeep import Client, Settings
    from config.afip import WSFE_WSDL

    cfg = _cfg()
    return Client(
        wsdl=WSFE_WSDL[cfg['modo']],
        settings=Settings(strict=False, xml_huge_tree=True),
    )


def _auth():
    cfg            = _cfg()
    token, sign    = _obtener_ticket('wsfe')
    return {'Token': token, 'Sign': sign, 'Cuit': int(cfg['cuit'])}


# ── Operaciones WSFE ─────────────────────────────────────────────────────────

def obtener_ultimo_numero(cbte_tipo):
    """FECompUltimoAutorizado: retorna el último número emitido (0 si ninguno)."""
    cfg    = _cfg()
    client = _wsfe_client()
    resp   = client.service.FECompUltimoAutorizado(
        Auth=_auth(),
        PtoVta=cfg['punto_venta'],
        CbteTipo=cbte_tipo,
    )
    if resp.Errors:
        msgs = [f"[{e.Code}] {e.Msg}" for e in resp.Errors.Err]
        raise RuntimeError("AFIP FECompUltimoAutorizado: " + "; ".join(msgs))
    return int(resp.CbteNro or 0)


def emitir_factura(venta, cliente, productos):
    """
    Solicita CAE a ARCA para la venta dada.
    Devuelve dict: {tipo, numero, cae, cae_vto, fecha, cbte_tipo, punto_venta}.
    Lanza RuntimeError o ValueError con el mensaje de error para mostrar al usuario.
    """
    from config.afip import (
        CBTE_TIPO_FACTURA_A, CBTE_TIPO_FACTURA_B,
        IVA_ALICUOTA_21, IVA_PCT_21,
    )

    cfg = _cfg()

    # Determinar tipo de comprobante
    condicion = (cliente['condicion_iva'] or 'consumidor_final').lower().strip()
    cbte_tipo = (CBTE_TIPO_FACTURA_A
                 if condicion == 'responsable_inscripto'
                 else CBTE_TIPO_FACTURA_B)

    if cbte_tipo == CBTE_TIPO_FACTURA_A and not (cliente['cuit'] or '').strip():
        raise ValueError("Para emitir Factura A el cliente debe tener CUIT registrado.")

    # Próximo número
    ultimo    = obtener_ultimo_numero(cbte_tipo)
    nro_cbte  = ultimo + 1

    # Importes
    total = round(float(venta['total']), 2)
    if cbte_tipo == CBTE_TIPO_FACTURA_A:
        imp_neto = round(total / (1 + IVA_PCT_21), 2)
        imp_iva  = round(total - imp_neto, 2)         # ajuste por redondeo
    else:
        imp_neto = total
        imp_iva  = 0.0

    fecha_cbte = (str(venta['fecha'] or '')[:10]).replace('-', '')  # YYYYMMDD

    # Datos del receptor
    cuit_limpio = str(cliente['cuit'] or '').replace('-', '').replace(' ', '').strip()
    dni_limpio  = str(cliente['dni']  or '').replace('.', '').replace(' ', '').strip()

    if cbte_tipo == CBTE_TIPO_FACTURA_A:
        doc_tipo, doc_nro = 80, int(cuit_limpio)
    elif cuit_limpio:
        doc_tipo, doc_nro = 80, int(cuit_limpio)
    elif dni_limpio:
        doc_tipo, doc_nro = 96, int(dni_limpio)
    else:
        doc_tipo, doc_nro = 99, 0  # Sin identificar (Consumidor Final)

    # Armar detalle
    det = {
        'Concepto':   1,           # 1=Productos, 2=Servicios, 3=Productos y Servicios
        'DocTipo':    doc_tipo,
        'DocNro':     doc_nro,
        'CbteDesde':  nro_cbte,
        'CbteHasta':  nro_cbte,
        'CbteFch':    fecha_cbte,
        'ImpTotal':   total,
        'ImpTotConc': 0.0,
        'ImpNeto':    imp_neto,
        'ImpOpEx':    0.0,
        'ImpIVA':     imp_iva,
        'ImpTrib':    0.0,
        'MonId':      'PES',
        'MonCotiz':   1.0,
    }
    if cbte_tipo == CBTE_TIPO_FACTURA_A and imp_iva > 0:
        det['Iva'] = {
            'AlicIva': [{'Id': IVA_ALICUOTA_21, 'BaseImp': imp_neto, 'Importe': imp_iva}]
        }

    client = _wsfe_client()
    resp   = client.service.FECAESolicitar(
        Auth=_auth(),
        FeCAEReq={
            'FeCabReq': {
                'CantReg':  1,
                'PtoVta':   cfg['punto_venta'],
                'CbteTipo': cbte_tipo,
            },
            'FeDetReq': {'FECAEDetRequest': [det]},
        },
    )

    if resp.Errors:
        msgs = [f"[{e.Code}] {e.Msg}" for e in resp.Errors.Err]
        raise RuntimeError("AFIP error: " + "; ".join(msgs))

    det_resp = resp.FeDetResp.FECAEDetResponse[0]

    if det_resp.Resultado == 'R':
        obs = []
        if det_resp.Observaciones and det_resp.Observaciones.Obs:
            obs = [f"[{o.Code}] {o.Msg}" for o in det_resp.Observaciones.Obs]
        raise RuntimeError("AFIP rechazó la solicitud: " + ("; ".join(obs) or "sin detalle"))

    tipo_letra = 'A' if cbte_tipo == CBTE_TIPO_FACTURA_A else 'B'
    cae        = det_resp.CAE
    cae_vto_r  = str(det_resp.CAEFchVto or '')

    try:
        cae_vto = datetime.strptime(cae_vto_r, '%Y%m%d').strftime('%Y-%m-%d')
    except Exception:
        cae_vto = cae_vto_r

    logger.info(
        "Factura %s N° %05d-%08d emitida. CAE: %s vto: %s",
        tipo_letra, cfg['punto_venta'], nro_cbte, cae, cae_vto,
    )
    return {
        'tipo':        tipo_letra,
        'numero':      nro_cbte,
        'cae':         cae,
        'cae_vto':     cae_vto,
        'fecha':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'cbte_tipo':   cbte_tipo,
        'punto_venta': cfg['punto_venta'],
        'imp_neto':    imp_neto,
        'imp_iva':     imp_iva,
    }


# ── Generación de PDF ─────────────────────────────────────────────────────────

def generar_pdf_factura(venta_id, venta, cliente, productos, factura):
    """
    Genera el PDF de la factura electrónica y lo guarda en static/facturas/.
    Devuelve la ruta relativa al proyecto (ej: 'static/facturas/venta_5_factura.pdf').
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    from config.afip import AFIP_CONFIG

    cfg       = AFIP_CONFIG
    pv_fmt    = f"{cfg['punto_venta']:04d}"
    nro_fmt   = f"{factura['numero']:08d}"
    tipo      = factura['tipo']          # 'A' o 'B'

    # Directorio de destino
    base_dir  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    facturas_dir = os.path.join(base_dir, 'static', 'facturas')
    os.makedirs(facturas_dir, exist_ok=True)

    filename  = f"venta_{venta_id}_factura.pdf"
    abs_path  = os.path.join(facturas_dir, filename)
    rel_path  = f"static/facturas/{filename}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=1.5*cm, bottomMargin=2*cm)

    styles  = getSampleStyleSheet()
    C_AZUL  = colors.HexColor('#4361EE')
    C_GRIS  = colors.HexColor('#F1F3F9')
    C_BORDE = colors.HexColor('#DEE2E6')
    C_ROJO  = colors.HexColor('#E63946')

    right_st  = ParagraphStyle('r', parent=styles['Normal'], alignment=TA_RIGHT)
    center_st = ParagraphStyle('c', parent=styles['Normal'], alignment=TA_CENTER)
    small_st  = ParagraphStyle('s', parent=styles['Normal'],
                               fontSize=8, textColor=colors.HexColor('#6c757d'),
                               alignment=TA_CENTER)
    bold_st   = ParagraphStyle('b', parent=styles['Normal'], fontName='Helvetica-Bold')

    story = []

    # ── Encabezado: emisor | tipo de comprobante ──────────────────────────────
    tipo_color = '#E63946' if tipo == 'A' else '#2B2D42'
    hdr = Table([[
        Paragraph(
            f"<b><font size='16'>{cfg['razon_social']}</font></b><br/>"
            f"<font size='9'>CUIT: {cfg['cuit']} &nbsp;|&nbsp; Responsable Inscripto</font><br/>"
            f"<font size='9'>{cfg['domicilio']}</font>",
            styles['Normal']
        ),
        Paragraph(
            f"<b><font size='22' color='{tipo_color}'>{tipo}</font></b>",
            center_st
        ),
        Paragraph(
            f"<b><font size='13'>FACTURA</font></b><br/>"
            f"<font size='9'>Punto de Venta: <b>{pv_fmt}</b></font><br/>"
            f"<font size='9'>Comp. N°: <b>{nro_fmt}</b></font><br/>"
            f"<font size='9'>Fecha: <b>{(factura['fecha'] or '')[:10]}</b></font>",
            right_st
        ),
    ]], colWidths=[9*cm, 1.5*cm, 6.5*cm])
    hdr.setStyle(TableStyle([
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEAFTER',    (0, 0), (0, 0),   1, C_BORDE),
        ('LINEBEFORE',   (2, 0), (2, 0),   1, C_BORDE),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 8),
        ('TOPPADDING',   (0, 0), (-1, -1), 8),
        ('BOX',          (1, 0), (1, 0),   2, colors.HexColor(tipo_color)),
        ('ALIGN',        (1, 0), (1, 0),   'CENTER'),
    ]))
    story += [hdr, HRFlowable(width='100%', thickness=2, color=C_AZUL), Spacer(1, .4*cm)]

    # ── Receptor ──────────────────────────────────────────────────────────────
    nombre_rec   = (cliente['razon_social'] or cliente['nombre'] or '—').upper()
    cuit_rec     = cliente['cuit'] or '—'
    cond_rec_map = {
        'responsable_inscripto': 'Responsable Inscripto',
        'monotributista':        'Monotributista',
        'consumidor_final':      'Consumidor Final',
        'exento':                'Exento',
    }
    cond_rec = cond_rec_map.get((cliente['condicion_iva'] or '').lower(), 'Consumidor Final')

    rec = Table([[
        Paragraph(f"<b>Receptor</b>", bold_st),
        Paragraph("", styles['Normal']),
    ], [
        Paragraph(f"<b>Razón social:</b> {nombre_rec}", styles['Normal']),
        Paragraph(f"<b>CUIT / DNI:</b> {cuit_rec}", styles['Normal']),
    ], [
        Paragraph(f"<b>Condición IVA:</b> {cond_rec}", styles['Normal']),
        Paragraph("", styles['Normal']),
    ]], colWidths=[9*cm, 8*cm])
    rec.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), C_GRIS),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOX',           (0, 0), (-1, -1), 0.5, C_BORDE),
    ]))
    story += [rec, Spacer(1, .4*cm)]

    # ── Tabla de ítems ────────────────────────────────────────────────────────
    tbl_data = [['#', 'Descripción', 'Cant.', 'Precio unit.', 'Subtotal']]
    for i, p in enumerate(productos, 1):
        sub = float(p[1]) * float(p[2])
        tbl_data.append([
            str(i),
            str(p[0]),
            f"{int(p[1])}",
            f"${float(p[2]):,.2f}",
            f"${sub:,.2f}",
        ])

    items_tbl = Table(tbl_data, colWidths=[0.8*cm, 9.2*cm, 1.5*cm, 2.8*cm, 2.7*cm])
    items_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), C_AZUL),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, C_GRIS]),
        ('GRID',          (0, 0), (-1, -1), 0.5, C_BORDE),
        ('ALIGN',         (2, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story += [items_tbl, Spacer(1, .4*cm)]

    # ── Totales ───────────────────────────────────────────────────────────────
    total     = float(venta['total'])
    imp_neto  = factura.get('imp_neto', total)
    imp_iva   = factura.get('imp_iva', 0.0)

    tot_rows = []
    if tipo == 'A':
        tot_rows += [
            ['Subtotal neto gravado:', f"${imp_neto:,.2f}"],
            ['IVA 21%:',              f"${imp_iva:,.2f}"],
        ]
    tot_rows.append(['', ''])
    tot_rows.append([
        Paragraph('<b>TOTAL:</b>', right_st),
        Paragraph(f"<b>${total:,.2f}</b>", right_st),
    ])

    tot_tbl = Table(tot_rows, colWidths=[13*cm, 4*cm])
    tot_tbl.setStyle(TableStyle([
        ('ALIGN',         (0, 0), (-1, -1), 'RIGHT'),
        ('FONTSIZE',      (0, 0), (-1, -1), 9),
        ('LINEABOVE',     (0, -1), (-1, -1), 1, C_AZUL),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story += [tot_tbl, Spacer(1, .6*cm)]

    # ── CAE ───────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=1, color=C_BORDE))
    story.append(Spacer(1, .2*cm))

    cae_tbl = Table([[
        Paragraph(
            f"<b>CAE N°:</b> {factura['cae']}&nbsp;&nbsp;&nbsp;"
            f"<b>Fecha vto. CAE:</b> {factura['cae_vto']}",
            styles['Normal']
        ),
        Paragraph(
            '<b><font color="#2ECC71">Comprobante Electrónico Autorizado</font></b>',
            right_st
        ),
    ]], colWidths=[10*cm, 7*cm])
    cae_tbl.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(cae_tbl)
    story.append(Spacer(1, .2*cm))
    story.append(Paragraph(
        "Documento generado por Sistema de Gestión · Comenda Deco",
        small_st,
    ))

    doc.build(story)

    with open(abs_path, 'wb') as f:
        f.write(buf.getvalue())

    logger.info("PDF factura guardado en %s", abs_path)
    return rel_path


# ── Padrón A13 ────────────────────────────────────────────────────────────────

def consultar_cuit_padron(cuit_consultar):
    """
    Consulta el Padrón A13 de AFIP para el CUIT dado.
    Devuelve dict: razon_social, condicion_iva, domicilio, localidad,
                   provincia, codigo_postal, actividad, estado.
    Lanza RuntimeError si el CUIT no existe o si falla la conexión.
    """
    from zeep import Client, Settings
    from config.afip import WS_PADRON_A13_WSDL

    cfg = _cfg()
    token, sign = _obtener_ticket('ws_sr_padron_a13')
    cuit_limpio = str(cuit_consultar).replace('-', '').replace(' ', '').strip()

    client = Client(
        wsdl=WS_PADRON_A13_WSDL[cfg['modo']],
        settings=Settings(strict=False, xml_huge_tree=True),
    )

    try:
        resp = client.service.getPersona(
            token=token,
            sign=sign,
            cuitRepresentada=int(cfg['cuit']),
            idPersona=int(cuit_limpio),
        )
    except Exception as e:
        raise RuntimeError(f"Error consultando padrón AFIP: {e}")

    if resp is None:
        raise RuntimeError("CUIT no encontrado en el padrón AFIP")

    def _attr(obj, *attrs):
        for a in attrs:
            if obj is None:
                return None
            try:
                obj = getattr(obj, a, None)
            except Exception:
                return None
        return obj

    def _s(val):
        return str(val).strip().title() if val else ''

    persona = _attr(resp, 'persona') or resp
    datos_g = _attr(persona, 'datosGenerales') or persona

    razon_social = _s(_attr(datos_g, 'razonSocial')) or _s(_attr(datos_g, 'nombre'))

    estado_raw = str(_attr(datos_g, 'estado') or '').strip().lower()
    estado = {'activo': 'Activo', 'inactivo': 'Inactivo'}.get(estado_raw, _s(_attr(datos_g, 'estado')) or 'Activo')

    dom = _attr(datos_g, 'domicilioFiscal') or _attr(datos_g, 'domicilio')
    direccion  = _s(_attr(dom, 'direccion'))
    localidad  = _s(_attr(dom, 'localidad'))
    provincia  = _s(_attr(dom, 'descripcionProvincia'))
    cod_postal = str(_attr(dom, 'codPostal') or '').strip()

    actividad = ''
    acts_wrap = _attr(datos_g, 'actividades')
    if acts_wrap is not None:
        acts = getattr(acts_wrap, 'actividad', acts_wrap) if hasattr(acts_wrap, 'actividad') else [acts_wrap]
        if not isinstance(acts, list):
            acts = [acts]
        for act in acts:
            if act is None:
                continue
            orden = getattr(act, 'orden', None) or getattr(act, 'actividadPrimaria', None)
            if orden in (1, '1', True):
                actividad = _s(_attr(act, 'descripcionActividad'))
                break
        if not actividad and acts:
            actividad = _s(_attr(acts[0], 'descripcionActividad'))

    _COND_MAP = {
        'responsable inscripto': 'responsable_inscripto',
        'responsable_inscripto': 'responsable_inscripto',
        'monotributista':        'monotributista',
        'monotributo':           'monotributista',
        'exento':                'exento',
        'consumidor final':      'consumidor_final',
        'no categorizado':       'consumidor_final',
        'no responsable':        'exento',
    }

    condicion_iva = 'consumidor_final'
    datos_rg = _attr(persona, 'datosRegimenGeneral')
    datos_mt = _attr(persona, 'datosMonotributo')

    if datos_rg is not None:
        condicion_iva = 'responsable_inscripto'
        imps_wrap = _attr(datos_rg, 'impuesto')
        if imps_wrap is not None:
            imps = imps_wrap if isinstance(imps_wrap, list) else [imps_wrap]
            for imp in imps:
                if _attr(imp, 'idImpuesto') == 30:
                    cat = str(_attr(imp, 'descripcionCategoria') or _attr(imp, 'categoria') or '').lower().strip()
                    condicion_iva = _COND_MAP.get(cat, 'responsable_inscripto')
                    break
    elif datos_mt is not None:
        condicion_iva = 'monotributista'

    logger.info("Padrón A13 consultado para CUIT %s: %s", cuit_limpio, razon_social)
    return {
        'razon_social':  razon_social,
        'condicion_iva': condicion_iva,
        'domicilio':     direccion,
        'localidad':     localidad,
        'provincia':     provincia,
        'codigo_postal': cod_postal,
        'actividad':     actividad,
        'estado':        estado,
    }
