# Corrida del universo por lotes (reanudable) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un modo `construir-universo` que procese el universo de estudios por lotes, escribiendo cada lote con `WRITE_APPEND` a `benchmarking_tesis.nomina_features`, reanudable automáticamente (salta lo ya escrito), con memoria acotada y sin persistir identificadores.

**Architecture:** Se refactoriza el armado por-lote en `_ensamblar` (reusado por `construir_base` y por el nuevo `construir_universo`). El estado es la propia tabla destino (`DISTINCT numero_proceso`). Cada lote es un load job atómico → idempotente. La escritura (create/append) y el conjunto "hechos" se inyectan al orquestador para mantenerlo testeable sin BQ.

**Tech Stack:** Python 3.11, pandas, google-cloud-bigquery, pytest.

## Global Constraints

- Python **3.11+**; usar `.venv/Scripts/python.exe`. No `pip install`.
- Correr el archivo de test focalizado y la **suite completa** (`pytest -q`) antes de cada commit. Salida pristina.
- **Sin red/BQ en tests:** `runner`, `escribir_lote` y las funciones de sink se mockean/inyectan.
- **Frontera de privacidad:** nada con cédula/nombres se persiste; la anonimización ocurre en memoria por lote antes de escribir.
- **`construir_base` no cambia de comportamiento** (mismo resultado; solo refactor interno vía `_ensamblar`); sus tests existentes deben seguir verdes.
- **Grano** persona-estudio y esquema idénticos a `construir_base`.
- Cada commit incluye `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

```
src/benchmarking/adquisicion/bigquery_source.py  # + leer_personas_por_proceso
src/benchmarking/escritura/bigquery_sink.py       # + write_disposition param, tabla_existe, procesos_existentes
src/benchmarking/orquestador.py                    # _ensamblar (refactor) + construir_universo
src/benchmarking/cli.py                            # + subcomando construir-universo
tests/test_bigquery_source.py                      # + test IN
tests/test_bigquery_sink.py                        # + write_disposition, tabla_existe, procesos_existentes
tests/test_orquestador.py                          # + construir_universo (lotea + reanuda)
tests/test_cli.py                                  # + wiring construir-universo
```

---

### Task 1: `leer_personas_por_proceso`

**Files:**
- Modify: `src/benchmarking/adquisicion/bigquery_source.py`
- Test: `tests/test_bigquery_source.py`

**Interfaces:**
- Produces: `leer_personas_por_proceso(runner, procesos: list[str]) -> pd.DataFrame` — `SQL_PERSONAS` + `AND numero_proceso IN (...)` sobre `procesos`; mismas columnas/casts que `leer_personas`. Con lista vacía devuelve un DataFrame vacío (sin consultar).

- [ ] **Step 1: Escribir el test**

```python
# añadir a tests/test_bigquery_source.py
from benchmarking.adquisicion.bigquery_source import leer_personas_por_proceso

def test_leer_personas_por_proceso_filtra_IN():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"identificacion":["1"],"numero_proceso":["140672"],"id_version":["v"],
         "anio_valoracion":[2024],"empresa_ruc":["17"],"cargo":["X"],"centro_de_costo":["C"],
         "sexo":["F"],"edad":[30],"sueldo":[500.0],"remuneracion_promedio":[None],"fecha_ingreso":[None]})
    df = leer_personas_por_proceso(runner, ["140672","140673"])
    sql = runner.query.call_args[0][0]
    assert "numero_proceso IN (" in sql
    assert "'140672'" in sql and "'140673'" in sql
    assert "identificacion_persona" in sql
    assert not df.empty

def test_leer_personas_por_proceso_vacio_no_consulta():
    runner = MagicMock()
    df = leer_personas_por_proceso(runner, [])
    assert df.empty
    runner.query.assert_not_called()
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_source.py::test_leer_personas_por_proceso_filtra_IN -v`
Expected: FAIL (import/función inexistente)

- [ ] **Step 3: Implementar**

Añadir `import pandas as pd` al tope del módulo (si no está) y la función tras `leer_personas`:

```python
def leer_personas_por_proceso(runner, procesos):
    lista = [str(p) for p in procesos]
    if not lista:
        return pd.DataFrame()
    en = ", ".join("'" + p.replace("'", "") + "'" for p in lista)   # procesos provienen de BQ
    sql = SQL_PERSONAS + f"\nAND numero_proceso IN ({en})"
    return runner.query(sql).to_dataframe()
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/adquisicion/bigquery_source.py tests/test_bigquery_source.py
git commit -m "feat: leer_personas_por_proceso (lectura por lote de estudios)"
```

---

### Task 2: Sink — `write_disposition`, `tabla_existe`, `procesos_existentes`

**Files:**
- Modify: `src/benchmarking/escritura/bigquery_sink.py`
- Test: `tests/test_bigquery_sink.py`

**Interfaces:**
- `escribir(..., write_disposition="WRITE_TRUNCATE")` — nuevo parámetro (default preserva `construir_base`); se usa en el `LoadJobConfig`. Guardia PII + cast `Int64` + partición/cluster sin cambios.
- `tabla_existe(client, table_id) -> bool`.
- `procesos_existentes(client, table_id) -> set[str]` — `DISTINCT numero_proceso` de la tabla; `set()` si no existe.

- [ ] **Step 1: Escribir el test**

```python
# añadir a tests/test_bigquery_sink.py
from unittest.mock import MagicMock
from google.api_core.exceptions import NotFound
from benchmarking.escritura.bigquery_sink import escribir, tabla_existe, procesos_existentes

def test_escribir_respeta_write_disposition():
    df = pd.DataFrame({"id_hash":["a"], "anio_valoracion":[2024], "empresa_ruc":["17"]})
    client = MagicMock()
    escribir(df, client, "proj", "ds", write_disposition="WRITE_APPEND")
    jc = client.load_table_from_dataframe.call_args.kwargs["job_config"]
    assert jc.write_disposition == "WRITE_APPEND"

def test_tabla_existe():
    client = MagicMock()
    client.get_table.return_value = object()
    assert tabla_existe(client, "p.d.t") is True
    client.get_table.side_effect = NotFound("x")
    assert tabla_existe(client, "p.d.t") is False

def test_procesos_existentes():
    client = MagicMock()
    # existe -> devuelve set de procesos
    client.get_table.return_value = object()
    client.query.return_value.result.return_value = [{"numero_proceso":"P1"},{"numero_proceso":"P2"}]
    assert procesos_existentes(client, "p.d.t") == {"P1","P2"}
    # no existe -> set vacío, sin query
    client2 = MagicMock(); client2.get_table.side_effect = NotFound("x")
    assert procesos_existentes(client2, "p.d.t") == set()
    client2.query.assert_not_called()
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_sink.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar**

Añadir el parámetro a `escribir` (firma y `LoadJobConfig`) y las dos funciones nuevas:

```python
from google.api_core.exceptions import NotFound
```

En `escribir`, cambiar la firma a incluir `write_disposition="WRITE_TRUNCATE"` y usarlo:

```python
def escribir(df, client, project, dataset, tabla="nomina_features",
             location="us-central1", write_disposition="WRITE_TRUNCATE"):
    fugas = _PII.intersection(df.columns)
    if fugas:
        raise ValueError(f"Frontera de privacidad violada: columnas PII presentes {fugas}")
    if "anio_valoracion" in df.columns:
        df = df.copy()
        df["anio_valoracion"] = df["anio_valoracion"].astype("Int64")
    table_id = f"{project}.{dataset}.{tabla}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        clustering_fields=["empresa_ruc"] if "empresa_ruc" in df.columns else None,
    )
    if "anio_valoracion" in df.columns:
        job_config.range_partitioning = bigquery.RangePartitioning(
            field="anio_valoracion",
            range_=bigquery.PartitionRange(start=2016, end=2027, interval=1))
    client.load_table_from_dataframe(df, table_id, job_config=job_config, location=location).result()
    return table_id

def tabla_existe(client, table_id):
    try:
        client.get_table(table_id)
        return True
    except NotFound:
        return False

def procesos_existentes(client, table_id):
    if not tabla_existe(client, table_id):
        return set()
    sql = f"SELECT DISTINCT numero_proceso FROM `{table_id}`"
    return {str(r["numero_proceso"]) for r in client.query(sql).result()}
```

(Nota: conservar el bloque de cast `Int64` que ya existía; arriba está integrado en la nueva firma. No dupliques el cast.)

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_sink.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/escritura/bigquery_sink.py tests/test_bigquery_sink.py
git commit -m "feat: sink write_disposition + tabla_existe/procesos_existentes (estado=tabla)"
```

---

### Task 3: Orquestador — `_ensamblar` (refactor) + `construir_universo`

**Files:**
- Modify: `src/benchmarking/orquestador.py`
- Test: `tests/test_orquestador.py`

**Interfaces:**
- Consumes: `listar_estudios`, `leer_personas_por_proceso`, `leer_scvs` (bigquery_source); `_composicion_estudios` (existente).
- Produces: `_ensamblar(base, scvs, base_url, settings, descargar, max_workers) -> pd.DataFrame` (lógica de armado por subconjunto). `construir_base` reusa `_ensamblar` (comportamiento idéntico). `construir_universo(runner, base_url, settings, escribir_lote, batch_size=500, max_workers=None, descargar=descargar_plantilla, hechos=frozenset()) -> int` — lotea estudios pendientes, arma cada lote y llama `escribir_lote(df)`; devuelve total de filas.

- [ ] **Step 1: Escribir el test**

```python
# añadir a tests/test_orquestador.py
from benchmarking.orquestador import construir_universo

def _fake_universo_runner():
    personas_all = pd.DataFrame([
        {"identificacion":ced,"numero_proceso":proc,"id_version":"v","anio_valoracion":2024,
         "empresa_ruc":"1790011111001","cargo":"VENDEDOR","centro_de_costo":"Ventas","sexo":"F",
         "edad":30,"sueldo":600.0,"remuneracion_promedio":700.0,"fecha_ingreso":dt.date(2014,1,1)}
        for proc in ("P1","P2","P3") for ced in ("1700000001","1700000002")])
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock(); s = sql.lower()
        if "scvs" in s or "balances" in s:
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        elif "numero_proceso in (" in s:
            procs = [p for p in ("P1","P2","P3") if f"'{p}'" in sql]
            m.to_dataframe.return_value = personas_all[personas_all.numero_proceso.isin(procs)].reset_index(drop=True)
        else:  # listar_estudios
            m.to_dataframe.return_value = pd.DataFrame(
                {"numero_proceso":["P1","P2","P3"],"id_version":["v","v","v"],
                 "anio_valoracion":[2024,2024,2024],"empresa_ruc":["1790011111001"]*3})
        return m
    runner.query.side_effect = fake_query
    return runner

def test_construir_universo_lotea_y_reanuda(monkeypatch, plantilla_xlsx_bytes):
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = _fake_universo_runner()
    escritos = []
    total = construir_universo(runner, "http://x", s, escribir_lote=escritos.append,
                               batch_size=1, max_workers=2,
                               descargar=lambda *a, **k: plantilla_xlsx_bytes, hechos={"P1"})
    # P1 ya hecho -> solo P2 y P3, en 2 lotes (batch_size=1)
    assert len(escritos) == 2
    procesados = pd.concat(escritos)["numero_proceso"].unique().tolist()
    assert set(procesados) == {"P2","P3"}
    assert total == sum(len(d) for d in escritos)
    # frontera: sin PII, con id_hash y composición armada
    for d in escritos:
        assert "identificacion" not in d.columns and "id_hash" in d.columns
        assert {"pct_fijo","total","segmento","n_personas_estudio"}.issubset(d.columns)
    # SCVS leído una sola vez
    scvs_calls = [c for c in runner.query.call_args_list
                  if "scvs" in c[0][0].lower() or "balances" in c[0][0].lower()]
    assert len(scvs_calls) == 1
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_orquestador.py::test_construir_universo_lotea_y_reanuda -v`
Expected: FAIL (`construir_universo` inexistente)

- [ ] **Step 3: Implementar**

Ampliar el import de bigquery_source y refactorizar. Cambiar:

```python
from .adquisicion.bigquery_source import leer_personas, leer_scvs
```
por:
```python
from .adquisicion.bigquery_source import (
    leer_personas, leer_scvs, listar_estudios, leer_personas_por_proceso)
```

Extraer `_ensamblar` y reescribir `construir_base` para reusarla; añadir `construir_universo`:

```python
def _ensamblar(base, scvs, base_url, settings, descargar, max_workers):
    base = base.copy()
    base["identificacion"] = base["identificacion"].astype(str)
    # tamaño de la nómina del estudio (contexto de fiabilidad de la etiqueta de cargo)
    base["n_personas_estudio"] = base.groupby("numero_proceso")["identificacion"].transform("size")
    estudios = base[["numero_proceso", "id_version"]].drop_duplicates()
    comp = _composicion_estudios(estudios, base_url, descargar, max_workers=max_workers)
    df = base.merge(comp, how="left", on=["numero_proceso", "identificacion"])
    df["cargo_norm"] = df["cargo"].map(_norm)
    df = anonimizar(df, settings.salt)                 # FRONTERA
    df = agregar_features(df, settings)
    df = marcar_cuarentena(df, settings)
    return unir_scvs(df, scvs)

def construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla, max_workers=None):
    base = leer_personas(runner, limite)
    if base.empty:
        return base
    workers = settings.descargas_concurrentes if max_workers is None else max_workers
    return _ensamblar(base, leer_scvs(runner), base_url, settings, descargar, workers)

def construir_universo(runner, base_url, settings, escribir_lote, batch_size=500,
                       max_workers=None, descargar=descargar_plantilla, hechos=frozenset()):
    workers = settings.descargas_concurrentes if max_workers is None else max_workers
    estudios = listar_estudios(runner)
    pendientes = [p for p in estudios["numero_proceso"].astype(str).tolist() if p not in hechos]
    scvs = leer_scvs(runner)                            # una sola vez para toda la corrida
    total = 0
    for i in range(0, len(pendientes), batch_size):
        lote = pendientes[i:i + batch_size]
        base = leer_personas_por_proceso(runner, lote)
        if base.empty:
            continue
        df = _ensamblar(base, scvs, base_url, settings, descargar, workers)
        escribir_lote(df)                              # append atómico (inyectado)
        total += len(df)
        print(f"[universo] lote {i // batch_size + 1}: {len(df)} filas (acumulado {total})")
    return total
```

Mantener intactas las funciones `_una_plantilla` y `_composicion_estudios`.

- [ ] **Step 4: Ejecutar (debe pasar) — nuevos + existentes**

Run: `.venv/Scripts/python -m pytest tests/test_orquestador.py -v`
Expected: PASS (incluye los 5 tests previos de `construir_base` — el refactor no los rompe)

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/orquestador.py tests/test_orquestador.py
git commit -m "feat: construir_universo por lotes reanudable + refactor _ensamblar (DRY)"
```

---

### Task 4: CLI — subcomando `construir-universo`

**Files:**
- Modify: `src/benchmarking/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `construir_universo`, `escribir`, `tabla_existe`, `procesos_existentes`.
- Produces: `benchmarking construir-universo --batch-size 500 --concurrencia N --reset`. Reanuda por defecto (calcula `hechos`), crea la tabla en la primera escritura y hace append después. `construir-base` se mantiene igual.

- [ ] **Step 1: Escribir el test**

```python
# añadir a tests/test_cli.py
def test_cli_universo_wire(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    cap = {}
    def fake_universo(runner, base_url, s, escribir_lote=None, batch_size=None, max_workers=None, hechos=None):
        cap["batch_size"] = batch_size; cap["max_workers"] = max_workers; cap["hechos"] = hechos
        return 0
    monkeypatch.setattr("benchmarking.cli.construir_universo", fake_universo)
    monkeypatch.setattr("benchmarking.cli.bigquery.Client", lambda *a, **k: MagicMock())
    monkeypatch.setattr("benchmarking.cli.tabla_existe", lambda *a, **k: True)
    monkeypatch.setattr("benchmarking.cli.procesos_existentes", lambda *a, **k: {"P9"})
    monkeypatch.setattr(sys, "argv",
                        ["benchmarking","construir-universo","--batch-size","250","--concurrencia","6"])
    from benchmarking.cli import main
    main()
    assert cap["batch_size"] == 250
    assert cap["max_workers"] == 6
    assert cap["hechos"] == {"P9"}
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py::test_cli_universo_wire -v`
Expected: FAIL (subcomando inexistente)

- [ ] **Step 3: Implementar en `cli.py`**

Actualizar imports y `main` para soportar ambos subcomandos:

```python
import argparse
import sys
from google.cloud import bigquery
from .config.settings import cargar_settings
from .orquestador import construir_base, construir_universo
from .escritura.bigquery_sink import escribir, tabla_existe, procesos_existentes

def main():
    ap = argparse.ArgumentParser(prog="benchmarking")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cb = sub.add_parser("construir-base")
    cb.add_argument("--muestra", type=int, default=None, help="limitar a N estudios (desarrollo)")
    cb.add_argument("--dry-run", action="store_true", help="no escribir a BigQuery")
    cb.add_argument("--concurrencia", type=int, default=None,
                    help="descargas de plantilla en paralelo (default: settings.descargas_concurrentes)")

    cu = sub.add_parser("construir-universo")
    cu.add_argument("--batch-size", type=int, default=500, help="estudios por lote")
    cu.add_argument("--concurrencia", type=int, default=None, help="descargas en paralelo por lote")
    cu.add_argument("--reset", action="store_true", help="borrar y recrear la tabla destino")

    args = ap.parse_args()
    s = cargar_settings()
    client = bigquery.Client()

    if args.cmd == "construir-base":
        df = construir_base(client, s.actuafast_base_url, s,
                            limite=args.muestra, max_workers=args.concurrencia)
        print(f"nomina_features: {len(df)} filas")
        if not args.dry_run and len(df):
            tid = escribir(df, client, s.bq_project, s.bq_dataset)
            print(f"escrito en {tid}")

    elif args.cmd == "construir-universo":
        table_id = f"{s.bq_project}.{s.bq_dataset}.nomina_features"
        if args.reset and tabla_existe(client, table_id):
            client.delete_table(table_id)
        hechos = procesos_existentes(client, table_id)
        estado = {"creada": tabla_existe(client, table_id)}
        def escribir_lote(df):
            disp = "WRITE_APPEND" if estado["creada"] else "WRITE_TRUNCATE"
            escribir(df, client, s.bq_project, s.bq_dataset, write_disposition=disp)
            estado["creada"] = True
        total = construir_universo(client, s.actuafast_base_url, s,
                                   escribir_lote=escribir_lote, batch_size=args.batch_size,
                                   max_workers=args.concurrencia, hechos=hechos)
        print(f"universo: {total} filas escritas (reanudó saltando {len(hechos)} estudios)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ejecutar (debe pasar) + suite completa**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v && .venv/Scripts/python -m pytest -q`
Expected: PASS (suite completa verde)

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/cli.py tests/test_cli.py
git commit -m "feat: CLI construir-universo (lotes, reanudable, --reset)"
```

---

## Notas de ejecución final (requiere GCP)

1. **Smoke reanudable** contra un dataset desechable: correr `construir-universo --batch-size 5 --concurrencia 8` apuntando a un dataset de prueba, **matarlo a mitad**, relanzarlo y verificar que **salta** los estudios ya escritos y completa sin duplicar (`SELECT COUNT(*), COUNT(DISTINCT CONCAT(numero_proceso,id_hash))` deben coincidir).
2. **Universo real** → crear `benchmarking_tesis` (us-central1) y correr `construir-universo` (default batch 500, concurrencia 8), reanudable.
