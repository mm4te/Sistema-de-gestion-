# registrar_webhook.py
# Uso: python registrar_webhook.py https://a1b2c3d4.ngrok.io
#
# Registra (o actualiza) el webhook de order/paid en TiendaNube.
# Ejecutar cada vez que cambie la URL de ngrok.

import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("TN_ACCESS_TOKEN")
STORE_ID = os.getenv("TN_STORE_ID")

if not TOKEN or not STORE_ID:
    print("❌ Faltan TN_ACCESS_TOKEN o TN_STORE_ID en el .env")
    sys.exit(1)

if len(sys.argv) < 2:
    print("❌ Uso: python registrar_webhook.py https://<tu-url-ngrok>")
    sys.exit(1)

ngrok_url   = sys.argv[1].rstrip("/")
webhook_url = f"{ngrok_url}/webhook/tiendanube"

HEADERS = {
    "Authentication": f"bearer {TOKEN}",
    "User-Agent":     "Comenda App (mateopatatian@gmail.com)",
    "Content-Type":   "application/json"
}

BASE = f"https://api.tiendanube.com/v1/{STORE_ID}/webhooks"

# -------------------------------------------------------------------
# 1. Listar webhooks existentes y eliminar los de order/paid viejos
# -------------------------------------------------------------------
print("🔍 Buscando webhooks existentes...")
r = requests.get(BASE, headers=HEADERS)

if r.status_code != 200:
    print(f"❌ Error al listar webhooks: {r.status_code} - {r.text}")
    sys.exit(1)

webhooks = r.json()
for wh in webhooks:
    if wh.get("event") == "order/paid":
        wh_id = wh["id"]
        rd = requests.delete(f"{BASE}/{wh_id}", headers=HEADERS)
        if rd.status_code in (200, 204):
            print(f"🗑  Webhook viejo eliminado (id={wh_id}, url={wh.get('url')})")
        else:
            print(f"⚠️  No se pudo eliminar webhook {wh_id}: {rd.text}")

# -------------------------------------------------------------------
# 2. Registrar el nuevo webhook
# -------------------------------------------------------------------
print(f"\n📡 Registrando webhook en: {webhook_url}")
payload = {
    "event": "order/paid",
    "url":   webhook_url
}
r = requests.post(BASE, json=payload, headers=HEADERS)

if r.status_code in (200, 201):
    data = r.json()
    print(f"✅ Webhook registrado correctamente")
    print(f"   ID:    {data.get('id')}")
    print(f"   Event: {data.get('event')}")
    print(f"   URL:   {data.get('url')}")
else:
    print(f"❌ Error al registrar: {r.status_code} - {r.text}")
    sys.exit(1)