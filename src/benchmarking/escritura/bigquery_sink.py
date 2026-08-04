from google.cloud import bigquery
from google.api_core.exceptions import NotFound

_PII = {"identificacion", "cedula", "nombres", "apellidos", "nombre_completo_persona"}


def escribir(df, client, project, dataset, tabla="nomina_features", location="us-central1",
             write_disposition="WRITE_TRUNCATE"):
    fugas = _PII.intersection(df.columns)
    if fugas:
        raise ValueError(f"Frontera de privacidad violada: columnas PII presentes {fugas}")
    if "anio_valoracion" in df.columns:
        # Int64 nullable: si hay NaN, la columna es float64 y BQ autodetecta FLOAT,
        # lo que rompe el RangePartitioning (exige un campo INTEGER). Los NULL
        # ruteados a Int64 caen en la particion no-particionada.
        df = df.copy()
        df["anio_valoracion"] = df["anio_valoracion"].astype("Int64")
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
