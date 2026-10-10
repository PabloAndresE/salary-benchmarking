# Cambios de la API para el front (2026-10-07)

## La banda es la de EMPRESAS

- `p10`, `p25`, `p75`, `p90`: cuánto pagan **las empresas** por el cargo (cada empresa cuenta una vez). Es el
  mercado.
- `p10_per` … `p90_per`: la banda de **personas** (más ancha; incluye las diferencias dentro de cada empresa).
  Solo como detalle.

## Qué mostrar

- **Rango de mercado = `rango_desde` – `rango_hasta`** (p25–p75): el 50 % central de las empresas. Es el
  rango principal. `p10`–`p90` va como detalle («el 80 % de las empresas paga entre …»).
- Rótulo sugerido: «Lo que pagan las empresas por este cargo».
- `referencia`: la mediana del mercado.

## Cada persona de la nómina

- `sueldo_actual` y su `posicion_mercado`: percentil aproximado dentro de la banda de empresas (10 a 90).
  Ejemplo: 62 = gana más que el 62 % de lo que pagan las empresas por ese cargo.
- `lectura_mercado`: «muy por debajo» (< p10), «por debajo» (p10–p25), «en linea» (p25–p75), «por encima»
  (p75–p90), «muy por encima» (> p90).
- Habrá más personas «por encima» o «por debajo» que antes: es lo esperado al compararlas con el mercado de
  empresas.

## Confianza y títulos en inglés

- `confianza` = `BAJA`: mostrar como «referencia orientativa: hay pocos datos de este cargo en el mercado»
  (más tenue, o con aviso).
- `equivalente`: para un título en inglés, el cargo en español de la base donde se resuelve
  (`PAYROLL ANALYST` → `ANALISTA DE NOMINA`). **La banda es la de ese equivalente**: el mismo cargo da la
  misma banda en inglés y en español. Mostrarlo como «equivalente en la base».
- `base` puede ser `datos directos`, `por analogia` o `por traduccion`.

## `/puestos` (buscador del formulario)

- `equivalente: true` y `traduccion`: la primera sugerencia para un título en inglés es su equivalente.
- `sinonimo`, `p_juez`, `seguro`, `grados`, `cargo_sin_grado`, `palabras_desconocidas`: ya existían.

## Tamaño de la empresa del cliente (desde 2026-10-10)

- **Mandar siempre el RUC del cliente,** en `/informes` y en `/referencia` (`ruc=1790...001`). Con el RUC se saca su
  tamaño del padrón de la Superintendencia (MICROEMPRESA, PEQUENA, MEDIANA o GRANDE), y con el tamaño los cargos
  altos tienen sentido entre sí. Sin tamaño, un `GERENTE DE TECNOLOGIA` puede salir sobre el `GERENTE GENERAL`,
  porque se lo ve sobre todo en empresas grandes.
- **La respuesta trae `segmento_del_ruc`.** Si el RUC no está en el padrón, trae además `aviso_segmento`: ahí hay
  que pedir el tamaño a mano (`segmento`).
