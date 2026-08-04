# Concurrencia de descargas de plantillas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Paralelizar la descarga+parseo de plantillas en `construir_base` con un `ThreadPoolExecutor` configurable (default 8), sin cambiar los resultados ni el esquema de salida.

**Architecture:** Se extrae un worker puro `_una_plantilla` (download+parse resiliente por estudio) y `_composicion_estudios` lo corre en un pool de hilos. La concurrencia se configura vía `Settings.descargas_concurrentes` (env) y flag CLI `--concurrencia`. Todo lo demás del pipeline queda intacto.

**Tech Stack:** Python 3.11, `concurrent.futures.ThreadPoolExecutor`, pandas, pytest.

## Global Constraints

- Python **3.11+**; usar el `.venv` de la raíz (`.venv/Scripts/python.exe`). No `pip install`.
- Tests con `pytest`; correr focalizado por archivo y la suite completa (`pytest -q`) antes de cada commit. Salida pristina.
- **Sin red en tests:** el downloader (`descargar`) se inyecta como mock; el pool corre con la función mock.
- **Resultado idéntico** al secuencial (el orden de descarga no importa; el enlace es por `(numero_proceso, cédula)`).
- **Preservar** la resiliencia por estudio (skip+log) y el dedup por `(numero_proceso, identificacion)`.
- **No** tocar el esquema de salida ni la lógica de features/validación/anonimización/escritura.
- Cada commit incluye la línea `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

```
src/benchmarking/config/settings.py   # + campo descargas_concurrentes
src/benchmarking/orquestador.py       # _una_plantilla (nuevo) + _composicion_estudios concurrente + construir_base(max_workers)
src/benchmarking/cli.py               # + flag --concurrencia
tests/test_settings.py                # + test del default/override
tests/test_orquestador.py             # + equivalencia concurrente y resiliencia concurrente
tests/test_cli.py                     # NUEVO: --concurrencia se pasa a construir_base
```

---

### Task 1: Campo de configuración `descargas_concurrentes`

**Files:**
- Modify: `src/benchmarking/config/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `Settings.descargas_concurrentes: int` (default `8`, env `PIPELINE_DESCARGAS_CONCURRENTES`).

- [ ] **Step 1: Escribir el test**

```python
# añadir a tests/test_settings.py
def test_descargas_concurrentes_default_y_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    monkeypatch.delenv("PIPELINE_DESCARGAS_CONCURRENTES", raising=False)
    from benchmarking.config.settings import cargar_settings
    assert cargar_settings().descargas_concurrentes == 8
    monkeypatch.setenv("PIPELINE_DESCARGAS_CONCURRENTES","15")
    assert cargar_settings().descargas_concurrentes == 15
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py::test_descargas_concurrentes_default_y_override -v`
Expected: FAIL (`AttributeError`/campo inexistente)

- [ ] **Step 3: Implementar**

En `Settings` (junto a los otros campos), añadir:

```python
    descargas_concurrentes: int = 8      # PIPELINE_DESCARGAS_CONCURRENTES
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/config/settings.py tests/test_settings.py
git commit -m "feat: settings.descargas_concurrentes (default 8)"
```

---

### Task 2: `_composicion_estudios` concurrente (núcleo)

**Files:**
- Modify: `src/benchmarking/orquestador.py`
- Test: `tests/test_orquestador.py`

**Interfaces:**
- Consumes: `Settings.descargas_concurrentes` (vía `construir_base`).
- Produces: `_una_plantilla(e, base_url, descargar) -> pd.DataFrame | None` (montos `[identificacion, comisiones, extras, otros, numero_proceso]`, `identificacion` como `str`; `None` ante fallo/plantilla ausente, con log). `_composicion_estudios(estudios, base_url, descargar, max_workers=8)` (mismo retorno que antes: concat + dedup, o DataFrame vacío tipado). `construir_base(..., max_workers=None)` usa `settings.descargas_concurrentes` cuando `max_workers is None`.

- [ ] **Step 1: Escribir el test de equivalencia (concurrente == secuencial) y resiliencia concurrente**

```python
# añadir a tests/test_orquestador.py
from pandas.testing import assert_frame_equal

def _fake_runner_multi():
    # 3 estudios, cada uno con las 2 cedulas del fixture de plantilla
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        else:
            filas = []
            for proc in ("P1","P2","P3"):
                for ced in ("1700000001","1700000002"):
                    filas.append({"identificacion":ced,"numero_proceso":proc,"id_version":"v",
                                  "anio_valoracion":2024,"empresa_ruc":"1790011111001",
                                  "cargo":"VENDEDOR","centro_de_costo":"Ventas","sexo":"F",
                                  "edad":30,"sueldo":600.0,"remuneracion_promedio":None,
                                  "fecha_ingreso":dt.date(2014,1,1)})
            m.to_dataframe.return_value = pd.DataFrame(filas)
        return m
    runner.query.side_effect = fake_query
    return runner

def test_construir_base_concurrente_equivale_a_secuencial(monkeypatch, plantilla_xlsx_bytes):
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    desc = lambda *a, **k: plantilla_xlsx_bytes
    df1 = construir_base(_fake_runner_multi(), "http://x", s, descargar=desc, max_workers=1)
    df4 = construir_base(_fake_runner_multi(), "http://x", s, descargar=desc, max_workers=4)
    key = ["numero_proceso","id_hash"]
    assert_frame_equal(df1.sort_values(key).reset_index(drop=True),
                       df4.sort_values(key).reset_index(drop=True))
    assert len(df4) == 6   # 3 estudios x 2 personas, sin fan-out

def test_construir_base_concurrente_resiliente(monkeypatch, plantilla_xlsx_bytes):
    # un estudio falla al descargar; con concurrencia el lote no cae y se conservan sus filas
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    def desc(numero_proceso, id_version, base_url):
        if numero_proceso == "P2":
            raise ValueError("XLSX corrupto")
        return plantilla_xlsx_bytes
    df = construir_base(_fake_runner_multi(), "http://x", s, descargar=desc, max_workers=4)
    assert len(df) == 6                                   # nadie se pierde
    # P2 sin composición; P1/P3 con composición
    assert (~df[df.numero_proceso=="P2"]["tiene_composicion"]).all()
    assert df[df.numero_proceso=="P1"]["tiene_composicion"].all()
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_orquestador.py::test_construir_base_concurrente_equivale_a_secuencial -v`
Expected: FAIL (`construir_base() got an unexpected keyword argument 'max_workers'`)

- [ ] **Step 3: Implementar en `orquestador.py`**

Añadir el import arriba y reemplazar `_composicion_estudios` por el worker + versión concurrente; añadir `max_workers` a `construir_base`.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

```python
def _una_plantilla(e, base_url, descargar):
    """Descarga+parsea la plantilla de un estudio. Devuelve montos por cédula, o None
    (con aviso) ante 5xx agotado / XLSX corrupto / columna ausente / plantilla inexistente.
    Worker aislado y sin estado compartido: seguro para correr en hilos."""
    try:
        raw = descargar(e.numero_proceso, e.id_version, base_url)
        if not raw:
            return None
        m = parsear_plantilla(raw)[["identificacion", "comisiones", "extras", "otros"]].copy()
    except Exception as exc:                              # noqa: BLE001 — omitir estudio, no el lote
        print(f"[composicion] estudio {e.numero_proceso} omitido: {type(exc).__name__}: {exc}")
        return None
    m["identificacion"] = m["identificacion"].astype(str)
    m["numero_proceso"] = e.numero_proceso
    return m

def _composicion_estudios(estudios, base_url, descargar, max_workers=8):
    filas = list(estudios.itertuples())
    partes = []
    if max_workers and max_workers > 1 and len(filas) > 1:
        # I/O de red -> hilos. Cada worker crea su propia requests.Session (no se comparte).
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futuros = [ex.submit(_una_plantilla, e, base_url, descargar) for e in filas]
            for fut in as_completed(futuros):
                m = fut.result()
                if m is not None:
                    partes.append(m)
    else:
        for e in filas:
            m = _una_plantilla(e, base_url, descargar)
            if m is not None:
                partes.append(m)
    if partes:
        comp = pd.concat(partes, ignore_index=True)
        # protege el grano: una plantilla con cedula duplicada no debe inflar el merge
        return comp.drop_duplicates(subset=["numero_proceso", "identificacion"], keep="first")
    # Sin ninguna plantilla en el lote: columnas numéricas explícitas (no "object")
    return pd.DataFrame({
        "identificacion": pd.Series(dtype=str),
        "comisiones": pd.Series(dtype=float),
        "extras": pd.Series(dtype=float),
        "otros": pd.Series(dtype=float),
        "numero_proceso": pd.Series(dtype=str),
    })
```

En `construir_base`, cambiar la firma y el llamado a `_composicion_estudios`:

```python
def construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla, max_workers=None):
    base = leer_personas(runner, limite)               # BASE = estudios BQ, todas las filas
    if base.empty:
        return base
    base["identificacion"] = base["identificacion"].astype(str)
    # tamaño de la nómina del estudio: contexto para juzgar la fiabilidad de la etiqueta de cargo
    base["n_personas_estudio"] = base.groupby("numero_proceso")["identificacion"].transform("size")
    estudios = base[["numero_proceso", "id_version"]].drop_duplicates()
    workers = settings.descargas_concurrentes if max_workers is None else max_workers
    comp = _composicion_estudios(estudios, base_url, descargar, max_workers=workers)
    # enlace por cédula (cruda) ANTES de anonimizar; left join: NaN donde no hubo plantilla
    df = base.merge(comp, how="left", on=["numero_proceso", "identificacion"])
    df["cargo_norm"] = df["cargo"].map(_norm)
    df = anonimizar(df, settings.salt)                 # FRONTERA: elimina cédula (+ nombres si hubiera)
    df = agregar_features(df, settings)                # total/pct NULL-safe, sueldo_sbu, antiguedad...
    df = marcar_cuarentena(df, settings)               # depende de total -> corre despues de features
    df = unir_scvs(df, leer_scvs(runner))
    return df
```

- [ ] **Step 4: Ejecutar (debe pasar) — tests nuevos y los existentes del orquestador**

Run: `.venv/Scripts/python -m pytest tests/test_orquestador.py -v`
Expected: PASS (incluye `test_construir_base_end_to_end`, `..._tolera_fallo_de_plantilla`, `..._dedup_composicion_evita_fanout`, y los dos nuevos)

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/orquestador.py tests/test_orquestador.py
git commit -m "feat: descarga concurrente de plantillas (ThreadPoolExecutor), resultado identico"
```

---

### Task 3: Flag CLI `--concurrencia`

**Files:**
- Modify: `src/benchmarking/cli.py`
- Test: `tests/test_cli.py` (nuevo)

**Interfaces:**
- Consumes: `construir_base(..., max_workers=...)` (Task 2).
- Produces: `construir-base --concurrencia N` (int, default `None`) que se pasa como `max_workers`.

- [ ] **Step 1: Escribir el test (todo mockeado, sin red ni BQ)**

```python
# tests/test_cli.py
import sys
from unittest.mock import MagicMock
import pandas as pd

def test_cli_pasa_concurrencia_y_muestra(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    capturado = {}
    def fake_construir_base(runner, base_url, s, limite=None, max_workers=None):
        capturado["limite"] = limite
        capturado["max_workers"] = max_workers
        return pd.DataFrame()          # vacío -> dry-run no escribe
    monkeypatch.setattr("benchmarking.cli.construir_base", fake_construir_base)
    monkeypatch.setattr("benchmarking.cli.bigquery.Client", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sys, "argv",
                        ["benchmarking","construir-base","--muestra","2","--concurrencia","12","--dry-run"])
    from benchmarking.cli import main
    main()
    assert capturado["limite"] == 2
    assert capturado["max_workers"] == 12
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: FAIL (`--concurrencia` no reconocido / `max_workers` no capturado)

- [ ] **Step 3: Implementar en `cli.py`**

Añadir el argumento y pasarlo a `construir_base`:

```python
    cb.add_argument("--concurrencia", type=int, default=None,
                    help="descargas de plantilla en paralelo (default: settings.descargas_concurrentes)")
```

y en la llamada:

```python
    df = construir_base(client, s.actuafast_base_url, s,
                        limite=args.muestra, max_workers=args.concurrencia)
```

- [ ] **Step 4: Ejecutar (debe pasar) + suite completa**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v && .venv/Scripts/python -m pytest -q`
Expected: PASS (suite completa verde)

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/cli.py tests/test_cli.py
git commit -m "feat: flag CLI --concurrencia para descargas de plantilla"
```

---

## Notas de verificación final (opcional, requiere GCP)

Smoke real contra un dataset desechable, comparando tiempos:
`PYTHONPATH=src PIPELINE_SALT=<salt> PIPELINE_BQ_DATASET=<throwaway> .venv/Scripts/python -m benchmarking.cli construir-base --muestra 40 --concurrencia 8` (sin `--dry-run`) — debe producir el mismo conteo/filas que la versión secuencial pero notablemente más rápido, tolerando 404s.
