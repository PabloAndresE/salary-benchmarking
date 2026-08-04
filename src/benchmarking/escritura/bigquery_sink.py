from google.cloud import bigquery
from google.api_core.exceptions import NotFound

_PII = {"identificacion", "cedula", "nombres", "apellidos", "nombre_completo_persona"}

# Dtypes canonicos por columna: bajo WRITE_APPEND con muchos lotes (construir-universo),
# cada lote infiere su propio tipo de BigQuery a partir del dtype de pandas. Un lote con
# contenido distinto (todo-NULL, sin RUC coincidente, sin composicion salarial, columnas SCVS
# all-NaN, etc.) puede derivar a un dtype distinto de otro lote -> BigQuery rechaza el load
# job de WRITE_APPEND ("Field X changed type ...") y ese lote nunca se commitea. Se usan
# dtypes nullable para que los lotes 100% NULL no colapsen a object/float.
_DTYPES_CANONICOS = {
    # enteros nullable
    "anio_valoracion": "Int64", "edad": "Int64", "antiguedad_total": "Int64",
    "n_personas_estudio": "Int64", "n_empleados": "Int64",
    # floats
    "sueldo": "float64", "remuneracion_promedio": "float64", "comisiones": "float64",
    "extras": "float64", "otros": "float64", "total": "float64",
    "pct_fijo": "float64", "pct_comisiones": "float64", "pct_extras": "float64",
    "pct_otros": "float64", "sueldo_sbu": "float64", "log_total": "float64",
    # booleanos nullable
    "tiene_composicion": "boolean", "en_clean": "boolean",
    # strings nullable (evita que columnas SCVS all-NaN deriven a float/object)
    "numero_proceso": "string", "id_version": "string", "empresa_ruc": "string",
    "cargo": "string", "cargo_norm": "string", "sexo": "string", "centro_de_costo": "string",
    "motivo_cuarentena": "string", "segmento": "string", "ciiu_n1": "string",
    "ciiu_n6": "string", "provincia": "string", "id_hash": "string",
    # NOTA: no forzar "fecha_ingreso" -- llega desde BigQuery como DATE (db-dtypes
    # `dbdate`), consistente entre lotes. Castear a datetime64 cambiaria la columna
    # de DATE a TIMESTAMP en BigQuery.
}


def escribir(df, client, project, dataset, tabla="nomina_features", location="us-central1",
             write_disposition="WRITE_TRUNCATE"):
    fugas = _PII.intersection(df.columns)
    if fugas:
        raise ValueError(f"Frontera de privacidad violada: columnas PII presentes {fugas}")
    df = df.copy()
    for col, dtype in _DTYPES_CANONICOS.items():
        if col in df.columns:
            df[col] = df[col].astype(dtype)
    table_id = f"{project}.{dataset}.{tabla}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        clustering_fields=["empresa_ruc"] if "empresa_ruc" in df.columns else None,
    )
    if "anio_valoracion" in df.columns:
        job_config.range_partitioning = bigquery.RangePartitioning(
            field="anio_valoracion",
            range_=bigquery.PartitionRange(start=2016, end=2027, interval=1))
    client.load_table_from_dataframe(df, table_id, job_config=job_config, location=location).result()
    return table_id


def tabla_existe(client, table_id):
    try:
        client.get_table(table_id)
        return True
    except NotFound:
        return False


def procesos_existentes(client, table_id):
    if not tabla_existe(client, table_id):
        return set()
    sql = f"SELECT DISTINCT numero_proceso FROM `{table_id}`"
    return {str(r["numero_proceso"]) for r in client.query(sql).result()}
