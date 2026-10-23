# API — contrato para el front

Toda respuesta viene en el mismo sobre:

```json
{ "message": "ok", "status": 0, "content": { ... } }
```

- `status = 0` es exito. Si no, `status` es el codigo HTTP con que sale la respuesta
  (400, 404, 422, 503, 500) y `message` dice por que. `content` puede traer el detalle
  (p. ej. los problemas de formato de la nomina).
- Las claves van en **camelCase**. Las columnas propias del cliente (las de su archivo)
  viajan **tal cual** las mando.
- Las unidades de cada campo numerico vienen en `unidades` (`usd`, `ratio`, `percentil`...):
  formatear un ratio como dolares da un numero creible y falso.
- Documentacion interactiva: `GET /docs` (OpenAPI).

## `POST /informes` — el producto

Sube una nomina y devuelve el informe **en la misma respuesta** (20-35 s). Es
`multipart/form-data`:

| Campo | Tipo | Notas |
|---|---|---|
| `archivo` | archivo | Excel o CSV; primera hoja, encabezados en la fila 1 |
| `anio` | int | ano del SBU; por defecto el actual |
| `ruc` | str | resuelve la industria (CIIU) y el tamano del cliente |
| `segmento` | str | `MICROEMPRESA`, `PEQUENA`, `MEDIANA`, `GRANDE` (manda sobre el del RUC) |
| `rubro` | str | seccion CIIU (una letra) |
| `mapeo` | str (JSON) | correcciones del usuario: `{"7": "ODONTOLOGA"}` (clave = `fila`) |
| `formatoLibre` | bool | `false` exige el formato del producto (columna `cargo`) |
| `columnaCargo`, `columnaSueldo` | str | con `formatoLibre=true` |
| `columnasOriginales` | bool | `true` (defecto): el detalle trae las columnas del cliente |
| `columnasExtra` | str | con `columnasOriginales=false`: cuales rescatar, separadas por coma |
| `incluirExcel` | bool | `true`: el Excel del informe en `excelBase64` |

`content`:

| Clave | Que es |
|---|---|
| `idCarga` | id de esta carga (con el se encuentra en BigQuery) |
| `filas`, `columnaCargo` | cuantas filas y que columna se leyo como cargo |
| `empresa` | ficha del RUC: `ruc`, `enLaBase`, `ciiu`, `ciiuSeccion`, `nEmpleados`, `rubroDerivado`, `segmentoDerivado`, avisos |
| `detalle` | una fila por persona: `fila`, `cargo`, `cargoNormalizado`, `estado`, `referencia`, `rangoDesde`, `rangoHasta`, `p10`..`p90` (empresas), `p10Per`..`p90Per` (personas), `confianza`, `base`, `empresas`, `personas`, `sueldoActual`, `vsMercado`, `vsPoliticaInterna`, `lecturaMercado`, `lecturaInterna`, `posicionMercado`, `equivalente`, `rubro`, `rubroNivel`, `antiguedadAnios`, `antiguedadTramo`... y las columnas del cliente |
| `porPuesto` | una fila por puesto: `cargo`, `cargoNormalizado`, `grafias`, `personas`, `sueldoMediano`, `referencia`, `p10Emp`..`p90Emp`, `vsMercado`, `confianza`, `brechaGrafia`, `rubro`, `rubroNivel`, `lectura`, `sectorMasFino` |
| `resumen` | `personas`, `conReferencia`, `nivelVsMercado`, `anclaFiable`, `masaReal`, `masaAMercado`, `masaVsMercado`... |
| `mercado` | tarjetas de cabecera: `cargosDelCliente`, `cargosConDatosEnLaBase`, `trabajadoresAnalizados`, `empresasAnalizadas`, `tamanoDeLasEmpresas`, notas |
| `industria` | contra que sector se comparo (con RUC o rubro): `codigo`, `nivel`, `nombre`, `cargosEnEseNivel`, `niveles`, `ciiuSeccion`, `nombreSeccion`, `gruposCiiu` |
| `meta` | `anio`, `sbu`, `segmento`, `rubro`, `mapeoAplicado`, avisos |
| `repartoEstado`, `repartoConfianza` | conteos; sus claves son VALORES (`directa`, `analogia`, `ALTA`...) |
| `formato` | informe del formato (columnas reconocidas, avisos) |
| `texto` | resumen en prosa |
| `excelBase64` | el Excel, si `incluirExcel=true`; si no, `null` |

## `GET /referencia` — un cargo suelto, para explorar

Query: `cargo` (obligatorio), `anio`, `segmento`, `rubro`, `ruc`. NO es el producto: sin
la nomina completa no hay ancla de empresa ni lectura de equidad interna (lo dice `aviso`).
`content`: las mismas claves de una fila de `detalle` mas `p10Emp`..`p90Emp`,
`sinonimoPrincipal` (si hay un sinonimo con mas empresas) y `unidades`.

## `GET /puestos` — el buscador de correcciones

Query: `q` (obligatorio), `limite` (1-50, defecto 12), `pMin` (defecto 0,5).
`content`: lista de sugerencias con `cargo`, `grafias`, `empresas`, `personas`,
`similitud`, `sobreElRuido`, `pJuez`, `seguro`, `sinonimo`, `equivalente`,
`palabrasDesconocidas`, `cargoSinGrado`, `grados`.

## `GET /salud` y `GET /health`

- `/health`: vivo, sin dependencias (para la sonda). `content: {"ok": true}`.
- `/salud`: que base esta cargada y que sabe hacer (`capacidades`), para encender o
  esconder funciones del front. 503 mientras la instancia arranca.

## Migracion desde el contrato anterior (v1.3)

| Antes | Ahora |
|---|---|
| `POST /informes` -> 202 + `id`; `GET /informes/{id}` hasta `listo` | `POST /informes` -> 200 con el informe |
| `GET /informes/{id}/excel` | `incluirExcel=true` en el mismo `POST`; viene en `excelBase64` |
| respuesta suelta | sobre `{message, status, content}` |
| errores `{"detail": ...}` | `message` (y `content` con el detalle, si lo hay) |
| claves `snake_case` (`rango_desde`) | `camelCase` (`rangoDesde`); columnas del cliente tal cual |
| campos de formulario `formato_libre`, `columna_cargo`... | `formatoLibre`, `columnaCargo`... (un campo desconocido da 422) |
| `p_min` en `/puestos` | `pMin` |
