"""El esquema de las tablas del dataset del producto (`benchmarking`). Una sola fuente:
de aqui salen el `CREATE TABLE` del script de infraestructura y las filas que escribe la
API."""

# El contrato de las tablas, en el orden de las columnas en BigQuery. Las tres llevan
# `fecha_carga`: es la columna de particion, y sin ella cada join leeria la tabla entera.
ESQUEMAS = {
    "cargas": (
        ("id_carga", "STRING"),  # el id del informe
        ("fecha_carga", "TIMESTAMP"),
        ("carga_hash", "STRING"),  # sha256 del archivo: la misma nomina subida dos veces
        ("anio", "INTEGER"),  # el ano del SBU con que se pidio el informe
        ("empresa_ruc", "STRING"),  # el que mando el cliente; NULL si no lo mando
        ("ciiu", "STRING"),  # el del padron para ese RUC
        ("segmento", "STRING"),  # el que se uso (pedido o del RUC)
        ("rubro", "STRING"),  # la seccion CIIU con que se comparo
        ("n_filas", "INTEGER"),
        ("columna_cargo", "STRING"),  # como se llamaban en el archivo
        ("columna_sueldo", "STRING"),
        ("correcciones", "INTEGER"),  # filas corregidas por el usuario (`mapeo`)
        ("version_api", "STRING"),
        ("version_base", "STRING"),
    ),
    "nomina_filas": (
        ("id_carga", "STRING"),
        ("fecha_carga", "TIMESTAMP"),
        ("fila", "INTEGER"),  # orden en el archivo
        ("cargo", "STRING"),  # tal como lo escribio el cliente
        ("cargo_corregido_usuario", "STRING"),
        ("sueldo", "FLOAT"),  # NULL si no habia columna o no era un numero
    ),
    "homologaciones": (
        ("id_carga", "STRING"),
        ("fecha_carga", "TIMESTAMP"),
        ("fila", "INTEGER"),
        ("cargo_normalizado", "STRING"),
        ("puesto_asignado", "STRING"),  # el puesto de la base; NULL por analogia
        ("via", "STRING"),  # datos directos / rubro X / por analogia / por traduccion
        ("estado", "STRING"),
        ("similitud", "FLOAT"),
        ("p_juez", "FLOAT"),
        ("referencia", "FLOAT"),  # lo que le dijimos, en dolares
        ("p25", "FLOAT"),
        ("p75", "FLOAT"),
        ("confianza", "STRING"),
        ("rubro", "STRING"),  # el CIIU al que se bajo en la cascada
        ("rubro_nivel", "STRING"),
    ),
}
# Se escriben las filas antes que la cabecera: una carga en `cargas` esta completa.
ORDEN = ("nomina_filas", "homologaciones", "cargas")


def ddl(dataset: str) -> str:
    """El `CREATE TABLE IF NOT EXISTS` de las tres tablas, desde `ESQUEMAS`: el esquema
    tiene una sola fuente, la misma que usa la API al escribir."""
    tipos = {"FLOAT": "FLOAT64", "INTEGER": "INT64"}
    sentencias = []
    for nombre, cols in ESQUEMAS.items():
        campos = ",\n  ".join(f"{n} {tipos.get(t, t)}" for n, t in cols)
        sentencias.append(
            f"CREATE TABLE IF NOT EXISTS `{dataset}.{nombre}` (\n  {campos}\n)\n"
            f"PARTITION BY DATE(fecha_carga)\nCLUSTER BY id_carga;"
        )
    return "\n\n".join(sentencias)
