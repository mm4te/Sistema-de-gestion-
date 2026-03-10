# listar_webhooks.py - verificar qué webhooks están registrados en TN
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("TN_ACCESS_TOKEN")
STORE_ID = os.getenv("TN_STORE_ID")

headers = {
    "Authentication": f"bearer {TOKEN}",
    "User-Agent": "Comenda App (mateopatatian@gmail.com)",
    "Content-Type": "application/json"
}

r = requests.get(f"https://api.tiendanube.com/v1/{STORE_ID}/webhooks", headers=headers)
print(f"Status: {r.status_code}")
print(f"Webhooks registrados: {r.json()}")