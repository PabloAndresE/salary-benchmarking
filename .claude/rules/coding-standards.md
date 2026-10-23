# Convenciones de codigo

## Nombres y logging <!-- FROZEN: verificar literal contra plantilla-backend-python -->

- `snake_case` para funciones, variables, modulos y archivos; `PascalCase` para clases;
  `UPPER_SNAKE` para constantes.
- Identificadores en espanol. Excepciones: idioms de Python y abreviaturas (`df`, `id`, `url`).
- Sufijo de capa: `_router.py`, `_service.py`, `_client.py`, `*RequestModel`.
- Funciones con verbo: `buscar_`, `crear_`, `obtener_`, `guardar_`, `validar_`, `calcular_`.
- Entre capas, argumentos por nombre (`kw=valor`).
- `logging.getLogger(__name__)`; nada de `print` ni f-strings dentro del logger (`%s`).
- NUNCA se loguean datos personales: ni cedula, ni RUC, ni nombres, ni sueldos. El
  middleware loguea el PATRON de la ruta, no la URL (la query de `/referencia` lleva el RUC).
- Services: INFO al inicio y al final con la duracion en `%.1fms`; WARNING para
  degradaciones; ERROR con `exc_info=True` para fallas inesperadas.

## Pydantic

- Atributos `snake_case` + `Field(alias="camelCase")`; `extra="forbid"` en los requests.
- `Tipo | None`, nunca `Optional`.

## Respuestas y errores

- Toda respuesta va en `BaseResponseModel` (`shared/contracts/responses.py`): `exito(...)`
  o `error(status, mensaje, contenido)`.
- Los services NO lanzan: devuelven el sobre. El router hace
  `if resp.status != 0: raise HTTPRequestException(response_model=resp)`.
- Las claves del contenido se pasan a camelCase con `claves_a_camel`, conservando las
  columnas del cliente y las claves que son valores (`repartoEstado`).

## Dominio

- Los comentarios del dominio citan su decision (`D-0xx`, en `docs/registro_decisiones.md`)
  y la medicion que la sostiene. Se mantienen: son la razon de cada umbral.
- Un cambio que toque una cifra se compara contra la foto (`tests/foto/foto.py`).
