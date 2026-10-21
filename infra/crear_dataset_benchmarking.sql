-- El dataset del PRODUCTO, aparte del de la tesis (`benchmarking_tesis`, que no se toca).
-- Idempotente: se puede correr dos veces. Las tres tablas de las cargas las crea
-- `crear_dataset_benchmarking.sh` desde `registro_nominas.ESQUEMAS`; aqui va el resto.
--
-- Parametros (los reemplaza el .sh): {proyecto}, {dataset}, {bucket}, {git_commit}

-- ---- De que esta hecho el producto -------------------------------------------------

-- Catalogo de versiones: que base, que modelos y desde que datos.
CREATE TABLE IF NOT EXISTS `{proyecto}.{dataset}.versiones` (
  version STRING,              -- v1.3
  fecha TIMESTAMP,
  base STRING,                 -- base_v31
  base_gcs STRING,             -- gs://.../base_v31.npz
  base_sha256 STRING,
  juez STRING,
  juez_gcs STRING,
  traductor STRING,
  traductor_gcs STRING,
  marco STRING,                -- la tabla congelada de la que salio la base
  decisiones_hasta STRING,     -- D-092
  git_commit STRING,
  notas STRING
);

-- La copia CONGELADA de las filas con que se construyo la v31: `nomina_features` de la
-- tesis, `en_clean`, anos 2024 y 2025 (research/experimentos/e2_nivel/41_base_v16.py).
-- Con esto el producto deja de depender de una tabla que la tesis puede rehacer.
-- Mismas columnas que `datos.SQL_MARCO`. El resto del filtro (`marco_evaluable`) es
-- codigo y se reaplica igual sobre esta copia.
CREATE TABLE IF NOT EXISTS `{proyecto}.{dataset}.marco_v31`
CLUSTER BY empresa_ruc AS
SELECT id_hash, empresa_ruc, numero_proceso, anio_valoracion,
       cargo_norm, centro_de_costo, sueldo, total,
       pct_fijo, pct_comisiones, pct_extras, pct_otros,
       antiguedad_total, tiene_composicion, en_clean,
       segmento, ciiu_n1, ciiu_n6, n_empleados, provincia, sexo
FROM `{proyecto}.benchmarking_tesis.nomina_features`
WHERE en_clean AND anio_valoracion IN (2024, 2025);

-- ---- Vistas para aprender de las cargas --------------------------------------------

-- Todo junto: una fila por empleado de cada carga, con su empresa y lo que respondimos.
CREATE OR REPLACE VIEW `{proyecto}.{dataset}.v_nominas` AS
SELECT c.id_carga, c.fecha_carga, c.carga_hash, c.anio, c.empresa_ruc, c.ciiu,
       c.segmento, c.version_api, c.version_base,
       f.fila, f.cargo, f.cargo_corregido_usuario, f.sueldo,
       h.cargo_normalizado, h.puesto_asignado, h.via, h.estado, h.similitud, h.p_juez,
       h.referencia, h.p25, h.p75, h.confianza, h.rubro, h.rubro_nivel
FROM `{proyecto}.{dataset}.cargas` c
JOIN `{proyecto}.{dataset}.nomina_filas` f USING (id_carga)
LEFT JOIN `{proyecto}.{dataset}.homologaciones` h USING (id_carga, fila);

-- La misma nomina subida varias veces cuenta UNA: la carga mas reciente de cada archivo.
CREATE OR REPLACE VIEW `{proyecto}.{dataset}.v_nominas_unicas` AS
SELECT * FROM `{proyecto}.{dataset}.v_nominas`
WHERE id_carga IN (
  SELECT ARRAY_AGG(id_carga ORDER BY fecha_carga DESC LIMIT 1)[OFFSET(0)]
  FROM `{proyecto}.{dataset}.cargas` GROUP BY carga_hash);

-- Titulos que la base no sabe resolver bien: por analogia o no reconocidos. Lo que hay
-- que mirar para sinonimos y reglas nuevas.
CREATE OR REPLACE VIEW `{proyecto}.{dataset}.v_no_reconocidos` AS
SELECT UPPER(TRIM(cargo)) AS cargo, via, estado,
       COUNT(*) AS veces, COUNT(DISTINCT empresa_ruc) AS empresas,
       MIN(fecha_carga) AS primera_vez, MAX(fecha_carga) AS ultima_vez
FROM `{proyecto}.{dataset}.v_nominas_unicas`
WHERE via = 'por analogia' OR estado = 'cargo_no_reconocido'
GROUP BY 1, 2, 3;

-- Lo que los usuarios corrigieron a mano: pares etiquetados por personas.
CREATE OR REPLACE VIEW `{proyecto}.{dataset}.v_correcciones` AS
SELECT UPPER(TRIM(cargo)) AS cargo, UPPER(TRIM(cargo_corregido_usuario)) AS corregido,
       COUNT(*) AS veces, COUNT(DISTINCT empresa_ruc) AS empresas
FROM `{proyecto}.{dataset}.v_nominas_unicas`
WHERE cargo_corregido_usuario IS NOT NULL
GROUP BY 1, 2;
