import pandas as pd

# Datos de ejemplo
datos = {
    "codigo": ["P001", "P002", "P003"],
    "descripcion": ["Arroz 1 kg", "Aceite neutro", "Azúcar x1kg"],
    "precio": [2.5, 5.8, 3.2],
    "stock": [100, 50, 200]
}

df = pd.DataFrame(datos)
df.to_excel("productos_ejemplo.xlsx", index=False)
print("Archivo 'productos_ejemplo.xlsx' creado. ¡Úsalo para subir!")