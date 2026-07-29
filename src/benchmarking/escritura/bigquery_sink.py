from google.cloud import bigquery

_PII = {"identificacion", "cedula", "nombres", "apellidos", "nombre_completo_persona"}


def escribir(df, client, project, dataset, tabla="nomina_features", location="us-central1"):
    fugas = _PII.intersection(df.columns)
    if fugas:
        raise ValueError(f"Frontera de privacidad violada: columnas PII presentes {fugas}")
    table_id = f"{project}.{dataset}.{tabla}"
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        clustering_fields=["empresa_ruc"] if "empresa_ruc" in df.columns else None,
    )
    if "anio_valoracion" in df.columns:
        job_config.range_partitioning = bigquery.RangePartitioning(
            field="anio_valoracion",
            range_=bigquery.PartitionRange(start=2016, end=2027, interval=1))
    client.load_table_from_dataframe(df, table_id, job_config=job_config, location=location).result()
    return table_id
