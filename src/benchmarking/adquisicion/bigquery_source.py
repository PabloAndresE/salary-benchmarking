import pandas as pd

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

# EL ULTIMO ANO DECLARADO NO SIEMPRE ES EL BUENO. Hay balances presentados a medio
# llenar: la plantilla se desploma respecto al ano anterior y a veces ni se declaran
# activos. Tomando el ultimo a secas, esas empresas entran con el segmento equivocado, y
# el segmento alimenta `ajuste_seg` —la correccion que mas pesa justo en los cargos
# altos—. El caso que lo destapo declara 2 empleados en 2025 y 193 en 2024.
#
# MEDIDO sobre las 221.794 filas del registro, por caida de plantilla entre las dos
# ultimas declaraciones:
#
#   caida      empresas   cambia segmento   sin activos declarados
#   >90%            891            61,3%                    37,0%   <- declaracion rota
#   50-90%       10.193            23,1%                    18,1%
#   10-50%       37.581            12,4%                    13,3%
#   estable      90.005             8,8%                    16,6%
#
# El tramo de >90% destaca en las dos columnas: 61% cambia de segmento y el 37% no
# declara activos, el doble que el resto. Eso es un formulario incompleto, no una empresa
# que encogio.
#
# LO QUE **NO** SE CORRIGE, y es deliberado: el 8,8% con plantilla ESTABLE que aun asi
# cambia de segmento. Esas oscilan alrededor del umbral por facturacion y cualquiera de
# las dos clasificaciones es defendible. Suavizarlo seria inventar una estabilidad que el
# registro no tiene.
#
# EFECTO: 942 empresas (0,42%) pasan a un ano anterior, y casi todas SUBEN de segmento
# —MICROEMPRESA->PEQUENA 278, MICROEMPRESA->MEDIANA 129—, que es lo que se espera si lo
# corregido son declaraciones que subestiman. Si metiera ruido, iria en las dos
# direcciones.
#
# Y SE PARTICIONA POR EL RUC YA RELLENADO. La misma empresa aparece con y sin el cero
# inicial —40 casos—, asi que particionar por el `ruc` crudo devolvia dos filas para
# ella. `meta_ruc` es un diccionario: una de las dos ganaba, la ultima, sin criterio.
SQL_SCVS = f"""
WITH x AS (
  SELECT LPAD(CAST(ruc AS STRING), 13, '0') ruc, anio, segmento, ciiu_n1, ciiu_n6,
         n_empleados
  FROM {_BAL}
  -- Sin RUC no sirve de nada: la tabla se usa SOLO para cruzar por RUC. Una fila asi
  -- entraba a `meta_ruc` como una clave basura, y el diccionario no avisa de eso.
  WHERE segmento IS NOT NULL AND ruc IS NOT NULL),
m AS (
  SELECT *, LEAD(n_empleados) OVER(PARTITION BY ruc ORDER BY anio DESC) n_prev
  FROM x),
s AS (
  SELECT *, IFNULL(n_empleados = 0 OR (n_prev >= 10 AND n_empleados < 0.10 * n_prev),
                   FALSE) AS sospechosa
  FROM m),
b AS (
  -- El ano mas reciente NO sospechoso. Si todos lo son, gana el mas reciente igual:
  -- mejor un dato dudoso que ninguno, y no hay forma de saber cual es menos malo.
  --
  -- IFNULL arriba: la declaracion mas antigua no tiene ano previo con que compararse y
  -- su NULL ordenaria PRIMERO en BigQuery, ganando siempre. Se da por buena.
  SELECT *, ROW_NUMBER() OVER(PARTITION BY ruc ORDER BY sospechosa, anio DESC) rn
  FROM s)
SELECT ruc, segmento, ciiu_n1, ciiu_n6, n_empleados
FROM b WHERE rn = 1
"""
# EL LPAD NO ES COSMETICO, y el comentario que habia aqui daba el problema por resuelto
# cuando no lo estaba. `ruc` YA es STRING en origen, asi que el CAST no quitaba ningun
# cero: los ceros ya venian perdidos en la tabla. 49.796 de 221.794 filas (22%) estan
# guardadas con 12 caracteres.
#
# Un RUC ecuatoriano tiene 13 y los dos primeros son la provincia, asi que los que
# empiezan por cero —01 Azuay, 07 El Oro, 08 Esmeraldas, 09 GUAYAS...— quedaban
# inalcanzables para cualquiera que mandase el RUC bien escrito. Medido contra nuestras
# propias empresas: cruzaban 5.003 de 7.105 y con el LPAD cruzan 6.074. Eran 1.071
# empresas sin sector ni tamano por un cero.

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

def leer_personas_por_proceso(runner, procesos):
    lista = [str(p) for p in procesos]
    if not lista:
        return pd.DataFrame()
    en = ", ".join("'" + p.replace("'", "") + "'" for p in lista)   # procesos provienen de BQ
    sql = SQL_PERSONAS + f"\nAND numero_proceso IN ({en})"
    return runner.query(sql).to_dataframe()

def leer_scvs(runner):
    return runner.query(SQL_SCVS).to_dataframe()
