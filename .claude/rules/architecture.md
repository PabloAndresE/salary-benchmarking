# Arquitectura

## Estructura <!-- FROZEN: verificar literal contra plantilla-backend-python -->

```
src/
  main.py                  app FastAPI, CORS, handlers de excepciones, routers
  api/routers/             <recurso>_router.py, un APIRouter por recurso
  api/requests/            DTOs Pydantic de entrada
  api/responses/           DTOs Pydantic de salida (vacio hoy: ver technical-debt)
  services/                logica de aplicacion como FUNCIONES de modulo
  domain/                  el modelo de referencia, sin HTTP ni red
  persistence/             unico acceso a la BD (BigQuery)
  integrations/<servicio>/ clientes de servicios externos (Vertex)
  infrastructure/          carga de artefactos y modelos
  shared/                  HOJA: contratos, excepciones, utilidades, constantes
  middleware/logger.py     request-logging con request_id
  config/                  ajustes por entorno y setup_logging()
tests/                     tests/fakes/ con los builders make_fake_*
```

## Direccion de dependencias <!-- FROZEN -->

- `persistence/` solo se importa desde `services/`.
- `shared/` es una hoja: no importa nada de capas superiores.
- `integrations/` solo desde `services/` (y `infrastructure/`, ver desviaciones).

## Este servicio

| Capa | Que hay |
|---|---|
| `api/routers/` | `informe_router` (`POST /informes`), `referencia_router` (`GET /referencia`), `puesto_router` (`GET /puestos`), `salud_router` (`/health`, `/salud`) |
| `services/` | `informe_service`, `referencia_service`, `puesto_service`, `salud_service`, `registro_nomina_service` |
| `domain/` | `base_referencia` (la base y `referenciar`), `capa0`, `nivel`, `sinonimos`, `idioma`, `tipeo`, `comparacion`, `antiguedad`, `formato`, `estadistica`, `ciiu`, `presentacion`, `nomina`, `columnas_nomina`; datos versionados en `domain/datos/` |
| `persistence/` | `bigquery_client` (streaming con `insertId`), `tablas` (esquema de `cargas`, `nomina_filas`, `homologaciones`) |
| `integrations/vertex/` | `vertex_client` (embeddings) |
| `infrastructure/` | `motor` (el estado pesado), `artefactos` (descarga del bucket), `modelos/juez` |

Flujo de `POST /informes`: router -> `informe_service.crear_informe` (valida, arma el
informe con el `Motor`, guarda la carga) -> sobre `BaseResponseModel`. El router traduce
`status != 0` a `HTTPRequestException`; los handlers de `main.py` arman la respuesta.

## Decisiones

- **Informe SINCRONO** (2026-10-23, decision del autor). 20-35 s, dentro de los 300 s de
  Cloud Run. Sin trabajos en memoria: con instancia bajo demanda se perderian al apagarse.
- **El sobre y el contrato de errores**: codigo HTTP = `status` del sobre (el de
  actuafast). Claves en camelCase; las columnas del cliente viajan tal cual.
- **Artefactos fuera de la imagen**: se bajan de GCS al arrancar (`ARTEFACTOS_GCS`).
- **Las nominas se guardan siempre** (cargo y sueldo, nunca nombres) en BigQuery, por
  streaming dentro de la peticion; si falla, el informe sale igual.
- **Region us-central1** para todo (servicio, dataset, bucket, Vertex).

## Known Deviations

1. **`infrastructure/motor.py` es una CLASE con estado**, no funciones. Tiene la base, el
   juez y el traductor (~3 GB) cargados una vez por instancia, y el cache de embeddings con
   cerrojo. Se crea en el arranque (`iniciar_motor`) y los services lo reciben por nombre
   (`obtener_motor`).
2. **`infrastructure/motor.py` importa `integrations/vertex`** para embeber los titulos
   nuevos: el embedding es parte de cargar y usar el modelo, no una llamada de negocio.
3. **Persistencia en BigQuery, no Firestore.** Las nominas son para analizar con SQL.
   No hay `documents/`: el esquema vive en `persistence/tablas.py`.
4. **`integrations/vertex/` no tiene `dtos/` ni `mapper.py`**: es el SDK de Vertex, no
   un cliente HTTP.
5. **`domain/` tiene estado y numpy**: `BaseReferencia` es el modelo entrenado, no un
   modelo Pydantic.
6. **Region us-central1** y no us-east1 (decision del autor, 2026-10-23).
