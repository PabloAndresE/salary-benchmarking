_VIEW = "`act-actuafast.actuafastv2.estudios_actuariales`"
_BAL = "`act-actuafast.actuafastv2.scvs_balances_anuales`"

SQL_ESTUDIOS = f"""
SELECT numero_proceso, ANY_VALUE(id_version) id_version,
       ANY_VALUE(anio_valoracion) anio_valoracion,
       ANY_VALUE(CAST(empresa_identificacion AS STRING)) empresa_ruc
FROM {_VIEW}
WHERE es_ultima_version AND numero_proceso IS NOT NULL AND id_version IS NOT NULL
GROUP BY numero_proceso
"""

# La base por-persona (grano persona-estudio). Nombres de columna verificados contra
# INFORMATION_SCHEMA de la view. No se selecciona nombre_completo_persona (PII).
SQL_PERSONAS = f"""
SELECT
  CAST(identificacion_persona AS STRING) identificacion,
  numero_proceso, id_version, anio_valoracion,
  CAST(empresa_identificacion AS STRING) empresa_ruc,
  cargo,
  centro_de_costo,
  UPPER(sexo_persona) sexo,
  SAFE_CAST(edad AS INT64) edad,
  sueldo,
  COALESCE(remuneracion_promedio_desahucio, remuneracion_promedio_jubilacion) remuneracion_promedio,
  COALESCE(fecha_ingreso_desahucio, fecha_ingreso_jubilacion) fecha_ingreso
FROM {_VIEW}
WHERE es_ultima_version AND numero_proceso IS NOT NULL
  AND id_version IS NOT NULL AND identificacion_persona IS NOT NULL
"""

SQL_SCVS = f"""
WITH b AS (SELECT ruc, segmento, ciiu_n1, ciiu_n6, n_empleados,
             ROW_NUMBER() OVER(PARTITION BY ruc ORDER BY anio DESC) rn
           FROM {_BAL} WHERE segmento IS NOT NULL)
SELECT CAST(ruc AS STRING) ruc, segmento, ciiu_n1, ciiu_n6, n_empleados
FROM b WHERE rn = 1
"""
# ruc se castea a STRING para que el join con empresa_ruc (tambien STRING en
# SQL_PERSONAS) no falle en RUCs con provincia 01-09 por desajuste de dtype.

def listar_estudios(runner, limite=None):
    sql = SQL_ESTUDIOS + (f"\nLIMIT {int(limite)}" if limite else "")
    return runner.query(sql).to_dataframe()

def leer_personas(runner, limite=None):
    # limite filtra por ESTUDIO (los primeros N numero_proceso), no por fila:
    # así una muestra trae estudios completos, no personas sueltas.
    sql = SQL_PERSONAS
    if limite:
        sql += f"\nQUALIFY DENSE_RANK() OVER (ORDER BY numero_proceso) <= {int(limite)}"
    return runner.query(sql).to_dataframe()

def leer_scvs(runner):
    return runner.query(SQL_SCVS).to_dataframe()
