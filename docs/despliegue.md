# Despliegue

El servicio corre en **Cloud Run, bajo demanda** (0 instancias en reposo), en
`us-central1`. La imagen lleva solo codigo y dependencias; la base y los modelos de cada
version se bajan del bucket al arrancar.

## Lo que ya existe en `act-cicd-stage-prueba`

| Recurso | Que es |
|---|---|
| `gs://act-cicd-stage-prueba-benchmarking/benchmarking/v1.3/` | artefactos de la v1.3: `base/base_v31.npz`, `base/prima_direccion.json`, `modelos/juez/`, `modelos/opus-mt-en-es/` |
| BigQuery `benchmarking` | `cargas`, `nomina_filas`, `homologaciones` (nominas guardadas), `versiones`, `marco_v31` y vistas `v_*` |

Los crea (idempotente) `infra/crear_dataset_benchmarking.sh`; con `BUCKET=...` sube
ademas los artefactos y registra la version.

## Desplegar

```bash
gcloud auth login
CORS_ORIGINS=https://<dominio-del-front> infra/desplegar_cloud_run.sh
```

El script habilita las APIs, crea la cuenta de servicio `benchmarking-api` con lo minimo
(Vertex, BigQuery sobre el dataset `benchmarking`, lectura del bucket), construye la imagen
con Cloud Build desde el `Dockerfile`, y despliega:

| Ajuste | Valor | Por que |
|---|---|---|
| CPU / memoria | 4 vCPU / 8 GiB | ~3,3 GB el motor + ~1,6 GB de artefactos en `/tmp` (memoria en Cloud Run) |
| Instancias | min 0, max 3 | bajo demanda; sin estado entre peticiones, puede escalar |
| Concurrencia | 8 | el informe ocupa la CPU 20-35 s |
| Timeout | 300 s | el informe es sincrono |
| `--cpu-boost` | si | mas CPU durante el arranque en frio |
| Acceso | autenticado (`PUBLICO=no`) | ver abajo |

## Acceso desde el front

Por defecto el servicio exige una identidad de Google (`--no-allow-unauthenticated`):
quien lo llame necesita el rol `roles/run.invoker` y manda
`Authorization: Bearer <ID token>`. Lo natural es que lo llame el **backend del front**
con su cuenta de servicio. Si el navegador tiene que llamarlo directo, hay que decidir
otra puerta (IAP o un balanceador con Cloud Armor) antes de usar `PUBLICO=si`: el
servicio devuelve referencias salariales y no debe quedar abierto.

## Una version nueva de la base

1. Construir la base (fuera de este repo) y precalcular su prima:
   `BASE_REFERENCIA=artefactos/base/base_vNN.npz uv run python infra/precalcular_prima.py`
2. Subirla como `v1.N`: `BUCKET=act-cicd-stage-prueba-benchmarking VERSION=v1.N infra/crear_dataset_benchmarking.sh`
3. Desplegar apuntando a ella: `ARTEFACTOS=gs://.../benchmarking/v1.N infra/desplegar_cloud_run.sh`
4. Antes de dar la version por buena, comparar contra la foto (`tests/foto/foto.py`):
   una base nueva CAMBIA numeros, asi que la foto se vuelve a grabar y las diferencias se
   revisan a mano.

## Pendiente de medir

El arranque en frio en Cloud Run (bajar ~1,6 GB, crear el cliente de Vertex, calentar).
Desde fuera de Google tardo ~100 s; en la red de Google deberia ser bastante menos. Si
resulta largo, las opciones son `--min-instances 1` en horario laboral o meter los
artefactos en la imagen.
