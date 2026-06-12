# config/afip.py
import os

AFIP_CONFIG = {
    'cuit':         os.getenv('AFIP_CUIT', '').strip(),
    'cert_path':    os.getenv('AFIP_CERT_PATH', 'cert/afip.crt').strip(),
    'key_path':     os.getenv('AFIP_KEY_PATH', 'cert/afip.key').strip(),
    'modo':         os.getenv('AFIP_MODO', 'homologacion').strip(),
    'razon_social': os.getenv('AFIP_RAZON_SOCIAL', 'COMENDA DECO SRL').strip(),
    'domicilio':    os.getenv('AFIP_DOMICILIO', '').strip(),
    'punto_venta':  int(os.getenv('AFIP_PUNTO_VENTA', '1') or '1'),
}

WSAA_WSDL = {
    'homologacion': 'https://wsaahomo.afip.gov.ar/ws/services/LoginCms?wsdl',
    'produccion':   'https://wsaa.afip.gov.ar/ws/services/LoginCms?wsdl',
}

WSFE_WSDL = {
    'homologacion': 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL',
    'produccion':   'https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL',
}

# Tipos de comprobante AFIP
CBTE_TIPO_FACTURA_A = 1
CBTE_TIPO_FACTURA_B = 6
CBTE_TIPO_NC_A      = 3
CBTE_TIPO_NC_B      = 8

# IVA alícuota id=5 → 21%
IVA_ALICUOTA_21 = 5
IVA_PCT_21 = 0.21

WS_PADRON_A13_WSDL = {
    'homologacion': 'https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL',
    'produccion':   'https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13?WSDL',
}
