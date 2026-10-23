# Testing

## Reglas <!-- FROZEN: verificar literal contra plantilla-backend-python -->

| Tipo | Mockea | Marker |
|---|---|---|
| Endpoint (router) | services, con TestClient | `endpoint` |
| Service | persistencia y clientes de integracion | `service` |
| Cliente de integracion | el SDK / requests | `integration` |
| Persistencia | el SDK (`_cliente()`) | `persistence` |
| Logica pura / dominio | nada | `function` / `model` |

- `pytestmark = pytest.mark.<categoria>` a nivel de modulo.
- `_PATCH = "src.<modulo>"` y `unittest.mock.patch`; no pytest-mock.
- Fakes compartidos en `tests/fakes/` (`make_fake_<entidad>`).
- Los tests corren sin credenciales ni red: los clientes de GCP se crean en el primer uso.

## Este servicio

- `tests/conftest.py`: `base_npz` (una base SINTETICA de tres puestos) y `cliente` (la app
  arrancada sobre ella). Apaga `CALENTAR` y `GUARDAR_NOMINAS`: los tests nunca llaman a
  Vertex ni escriben en BigQuery.
- `tests/test_contrato.py`: el contrato HTTP directo (sobre, camelCase, codigos, Excel, logs).
- `tests/fakes/cliente_v13.py`: ADAPTADOR que deja a los tests de comportamiento de la v1.3
  (`test_servicio.py`, `test_segmento_del_ruc.py`, `test_registro_nominas.py`) hablar el
  contrato viejo contra la API nueva. Deuda registrada.
- `tests/foto/foto.py`: la foto de respuestas contra datos reales (fuera del repo).
  No corre con `pytest`: se ejecuta contra una API en marcha.

## Trampas conocidas

- Un form de FastAPI con un `UploadFile` APARTE de un form model no funciona: el archivo
  va dentro del `CrearInformeRequestModel`.
- `uv sync` con bytecode en un host de 224 nucleos puede agotar los descriptores dentro de
  un chroot de buildah: `--ulimit nofile=65536:65536`.
