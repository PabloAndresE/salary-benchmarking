# Pipeline Fase 1 — `nomina_features` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir un pipeline modular que transforme estudios actuariales (BigQuery) + composición salarial (endpoint) + SCVS en una única tabla anonimizada `nomina_features` en BigQuery.

**Architecture:** Paquete `src/benchmarking/` con módulos de responsabilidad única: adquisición (BigQuery + endpoint plantilla), ingesta (validación, anonimización, composición, features, enriquecimiento), escritura (BigQuery), orquestados por un CLI. Lógica pura separada de I/O para testear sin red. La anonimización es la frontera: aguas abajo nadie ve identificadores.

**Tech Stack:** Python 3.11, pandas, google-cloud-bigquery, openpyxl, requests, pydantic-settings, pyyaml; pytest + ruff.

## Global Constraints

- Python **3.11+** (usar el `.venv` existente en la raíz del repo, creado con py 3.11).
- `salt` **solo desde variable de entorno `PIPELINE_SALT`** — nunca en código, config ni repo.
- **Privacidad (frontera):** el XLSX de la plantilla se procesa en memoria; nada con cédula/nombre se persiste ni se escribe a disco/repo. Aguas abajo de `anonimizacion` no existen identificadores.
- **Data real jamás al repo:** todos los tests usan data sintética (fixtures generados en código).
- **Destino BigQuery:** dataset nuevo en **us-central1**; nunca escribir en `act-actuafast.actuafastv2` (solo lectura).
- **Grano** de `nomina_features`: una fila por persona-estudio (`id_hash` + `numero_proceso`).
- **Cuarentena, no borrado:** filas inválidas se marcan con `motivo_cuarentena`, nunca se eliminan.

## File Structure

```
pyproject.toml                              # paquete instalable, deps, config pytest/ruff
src/benchmarking/
  __init__.py
  config/
    __init__.py
    settings.py                             # pydantic-settings: salt, SBU, umbrales, destino
    esquema_plantilla.yaml                  # nombres canónicos de columnas de la plantilla
  adquisicion/
    __init__.py
    plantilla_client.py                     # descarga plantilla-modificada (HTTP)
    bigquery_source.py                      # lee estudios_actuariales + SCVS
  ingesta/
    __init__.py
    anonimizacion.py                        # hash cédula, drop nombres (FRONTERA)
    validacion.py                           # sanity checks -> cuarentena
    composicion.py                          # parsea plantilla xlsx -> montos + pct
    features_base.py                        # sueldo_sbu, log_total, antiguedad, tuvo_salidas
    enriquecimiento.py                      # join SCVS
  escritura/
    __init__.py
    bigquery_sink.py                        # escribe nomina_features
  orquestador.py                            # construir_base(): encadena todo
  cli.py                                    # entrypoint: benchmarking construir-base
tests/
  conftest.py                              # fixtures: plantilla xlsx sintética, df estudios sintético
  test_anonimizacion.py
  test_validacion.py
  test_composicion.py
  test_features_base.py
  test_enriquecimiento.py
  test_plantilla_client.py
  test_orquestador.py
```

Orden de dependencias: lógica pura primero (anonimización, validación, composición, features, enriquecimiento), luego I/O (cliente plantilla, fuente/sink BigQuery), luego orquestación.

---

### Task 1: Scaffold del paquete + configuración

**Files:**
- Create: `pyproject.toml`, `src/benchmarking/__init__.py`, `src/benchmarking/config/__init__.py`, `src/benchmarking/config/settings.py`, `src/benchmarking/config/esquema_plantilla.yaml`
- Test: `tests/test_settings.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `Settings` (pydantic) con `.salt: str`, `.sbu: dict[int,int]`, `.min_sbu: float`, `.edad_min/edad_max: int`, `.bq_project: str`, `.bq_dataset: str`, `.actuafast_base_url: str`, `.get_sbu(anio:int)->int`. Función `cargar_settings() -> Settings`.

- [ ] **Step 1: Crear `pyproject.toml`**

```toml
[project]
name = "benchmarking"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pandas>=2.0", "google-cloud-bigquery[pandas]>=3.0", "openpyxl>=3.1",
  "requests>=2.31", "pydantic-settings>=2.0", "pyyaml>=6.0", "db-dtypes>=1.0",
]
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]
[project.scripts]
benchmarking = "benchmarking.cli:main"
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
[tool.setuptools.packages.find]
where = ["src"]
[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 2: Crear `esquema_plantilla.yaml`** (nombres canónicos → patrones de match)

```yaml
# Cada clave es el nombre canónico; el valor es la lista de substrings (mayúsculas, sin tildes)
# que deben aparecer TODOS en el encabezado real para mapearlo.
identificacion: ["IDENTIFICACION"]   # se prioriza el header que EMPIEZA con esto (no "TIPO DE")
cargo:          ["CARGO"]            # match exacto == "CARGO"
centro_costo:   ["CENTRO", "COSTO"]
sexo:           ["SEXO"]
sueldo:         ["SUELDO"]
comisiones:     ["COMISIONES"]
extras:         ["HORAS", "EXTRAS"]
otros:          ["OTROS", "MENSUALES"]
```

- [ ] **Step 3: Escribir el test de settings**

```python
# tests/test_settings.py
import pytest
from benchmarking.config.settings import cargar_settings

def test_salt_requerido(monkeypatch):
    monkeypatch.delenv("PIPELINE_SALT", raising=False)
    with pytest.raises(Exception):
        cargar_settings()

def test_sbu_por_anio(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT", "x")
    s = cargar_settings()
    assert s.get_sbu(2016) == 366
    assert s.get_sbu(2025) == 470
    assert s.get_sbu(2099) == 470  # años futuros usan el último conocido
```

- [ ] **Step 4: Ejecutar el test (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v`
Expected: FAIL (`ModuleNotFoundError: benchmarking.config.settings`)

- [ ] **Step 5: Implementar `settings.py`**

```python
# src/benchmarking/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

_SBU = {2016:366,2017:375,2018:386,2019:394,2020:400,
        2021:400,2022:425,2023:450,2024:460,2025:470}

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIPELINE_", extra="ignore")
    salt: str                                    # PIPELINE_SALT (obligatorio)
    min_sbu: float = 0.5
    edad_min: int = 18
    edad_max: int = 80
    bq_project: str = "act-cicd-stage-prueba"
    bq_dataset: str = "benchmarking_tesis"
    actuafast_base_url: str = "https://actuafast-api-611856784485.us-east1.run.app"
    sbu: dict[int, int] = _SBU

    def get_sbu(self, anio: int) -> int:
        return self.sbu.get(anio, max(self.sbu.values()))

def cargar_settings() -> Settings:
    return Settings()
```

Crear también los `__init__.py` vacíos de `benchmarking/` y `benchmarking/config/`.

- [ ] **Step 6: Ejecutar el test (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/benchmarking tests/test_settings.py
git commit -m "feat: scaffold paquete benchmarking + settings"
```

---

### Task 2: Anonimización (la frontera)

**Files:**
- Create: `src/benchmarking/ingesta/__init__.py`, `src/benchmarking/ingesta/anonimizacion.py`
- Test: `tests/test_anonimizacion.py`

**Interfaces:**
- Produces: `hash_cedula(cedula: str, salt: str) -> str` (16 hex chars). `anonimizar(df: pd.DataFrame, salt: str, col_cedula="identificacion", cols_nombre=("nombres","apellidos")) -> pd.DataFrame` — añade `id_hash`, elimina la cédula y los nombres.

- [ ] **Step 1: Escribir el test**

```python
# tests/test_anonimizacion.py
import pandas as pd
from benchmarking.ingesta.anonimizacion import hash_cedula, anonimizar

def test_hash_determinista_y_16():
    h1 = hash_cedula("1700000001", "sal")
    h2 = hash_cedula("1700000001", "sal")
    assert h1 == h2 and len(h1) == 16

def test_hash_cambia_con_salt():
    assert hash_cedula("1700000001", "a") != hash_cedula("1700000001", "b")

def test_anonimizar_elimina_pii_y_agrega_hash():
    df = pd.DataFrame({"identificacion":["1700000001"], "nombres":["Ana"],
                       "apellidos":["Perez"], "sueldo":[500.0]})
    out = anonimizar(df, salt="sal")
    assert "id_hash" in out.columns
    assert "identificacion" not in out.columns
    assert "nombres" not in out.columns and "apellidos" not in out.columns
    assert out.loc[0, "sueldo"] == 500.0
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_anonimizacion.py -v`
Expected: FAIL (módulo inexistente)

- [ ] **Step 3: Implementar `anonimizacion.py`**

```python
# src/benchmarking/ingesta/anonimizacion.py
import hashlib
import pandas as pd

def hash_cedula(cedula: str, salt: str) -> str:
    return hashlib.sha256((salt + str(cedula)).encode()).hexdigest()[:16]

def anonimizar(df: pd.DataFrame, salt: str, col_cedula: str = "identificacion",
               cols_nombre=("nombres", "apellidos")) -> pd.DataFrame:
    out = df.copy()
    out["id_hash"] = out[col_cedula].map(lambda c: hash_cedula(c, salt))
    a_eliminar = [col_cedula, *[c for c in cols_nombre if c in out.columns]]
    return out.drop(columns=a_eliminar)
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_anonimizacion.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/ingesta tests/test_anonimizacion.py
git commit -m "feat: anonimizacion (hash cedula, drop nombres) - la frontera"
```

---

### Task 3: Validación → cuarentena

**Files:**
- Create: `src/benchmarking/ingesta/validacion.py`
- Test: `tests/test_validacion.py`

**Interfaces:**
- Consumes: `Settings` (min_sbu, edad_min/max), `get_sbu`.
- Produces: `motivo_cuarentena(fila: dict, sbu: int, min_sbu: float, edad_min: int, edad_max: int) -> str | None` (None = válida). `marcar_cuarentena(df, settings) -> pd.DataFrame` que añade columnas `en_clean: bool`, `motivo_cuarentena: str`.

- [ ] **Step 1: Escribir el test**

```python
# tests/test_validacion.py
import pandas as pd
from benchmarking.ingesta.validacion import motivo_cuarentena, marcar_cuarentena
from benchmarking.config.settings import cargar_settings

def test_motivos(monkeypatch):
    base = dict(cargo_norm="CONTADOR", sueldo=500.0, total=500.0, edad=30)
    assert motivo_cuarentena(base, sbu=460, min_sbu=0.5, edad_min=18, edad_max=80) is None
    assert motivo_cuarentena({**base, "cargo_norm":"0"}, 460,0.5,18,80) == "cargo_placeholder"
    assert motivo_cuarentena({**base, "cargo_norm":"JUBILADO"}, 460,0.5,18,80) == "cargo_jubilado"
    assert motivo_cuarentena({**base, "total":100.0}, 460,0.5,18,80) == "sueldo_bajo_sbu"
    assert motivo_cuarentena({**base, "total":0.0}, 460,0.5,18,80) == "sueldo_no_positivo"
    assert motivo_cuarentena({**base, "edad":95}, 460,0.5,18,80) == "edad_fuera_rango"

def test_marcar_cuarentena(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"cargo_norm":"CONTADOR","sueldo":500.0,"total":500.0,"edad":30,"anio_valoracion":2024},
                       {"cargo_norm":"0","sueldo":500.0,"total":500.0,"edad":30,"anio_valoracion":2024}])
    out = marcar_cuarentena(df, s)
    assert out.loc[0,"en_clean"] and not out.loc[1,"en_clean"]
    assert out.loc[1,"motivo_cuarentena"] == "cargo_placeholder"
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_validacion.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `validacion.py`**

```python
# src/benchmarking/ingesta/validacion.py
import re
import pandas as pd

_PLACEHOLDERS = {"0","-","NA","N/A",".","--","S/N","SN","X",""}

def motivo_cuarentena(fila, sbu, min_sbu, edad_min, edad_max):
    cargo = str(fila.get("cargo_norm") or "")
    total = fila.get("total")
    edad = fila.get("edad")
    if cargo in _PLACEHOLDERS or re.fullmatch(r"[0-9]+", cargo):
        return "cargo_placeholder"
    if "JUBILAD" in cargo:
        return "cargo_jubilado"
    if total is None or pd.isna(total) or total <= 0:
        return "sueldo_no_positivo"
    if total < min_sbu * sbu:
        return "sueldo_bajo_sbu"
    if edad is not None and not (edad_min <= edad <= edad_max):
        return "edad_fuera_rango"
    return None

def marcar_cuarentena(df: pd.DataFrame, settings) -> pd.DataFrame:
    out = df.copy()
    motivos = []
    for r in out.to_dict("records"):
        anio = r.get("anio_valoracion")
        anio = 0 if anio is None or pd.isna(anio) else int(anio)   # NaN-safe (data real de BQ)
        motivos.append(
            motivo_cuarentena(r, settings.get_sbu(anio),
                              settings.min_sbu, settings.edad_min, settings.edad_max))
    out["motivo_cuarentena"] = [m or "" for m in motivos]
    out["en_clean"] = [m is None for m in motivos]
    return out
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_validacion.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/ingesta/validacion.py tests/test_validacion.py
git commit -m "feat: validacion -> cuarentena con motivos"
```

---

### Task 4: Composición (parseo de la plantilla)

**Files:**
- Create: `src/benchmarking/ingesta/composicion.py`
- Test: `tests/test_composicion.py`, y fixture en `tests/conftest.py`

**Interfaces:**
- Consumes: `esquema_plantilla.yaml`.
- Produces: `parsear_plantilla(xlsx_bytes: bytes) -> pd.DataFrame` con columnas `identificacion, cargo, centro_costo, sexo, sueldo, comisiones, extras, otros`. `calcular_composicion(df) -> pd.DataFrame` añade `total, pct_fijo, pct_comisiones, pct_extras, pct_otros`.
- **Nota de uso en el pipeline:** el orquestador usa `parsear_plantilla` para tomar solo los **montos** (`comisiones/extras/otros`) y los enlaza por cédula a la base de estudios; los totales y `pct_*` los calcula `features_base` (NULL-safe) tras el enlace. `calcular_composicion` queda como utilidad autónoma para análisis de una plantilla suelta (tests + exploración), no en la ruta del orquestador.

- [ ] **Step 1: Fixture — generar una plantilla xlsx sintética en `conftest.py`**

```python
# tests/conftest.py
import io
import openpyxl
import pytest

@pytest.fixture
def plantilla_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plantilla de empleados"
    ws.append(["Tipo de\nidentificación", "Identificación", "Apellidos", "Nombres",
               "Cargo ", "Centro de costos ", "Sexo",
               "Último sueldo/pensión mensual ", "Comisiones mensuales promedio  ",
               "Horas extras mensuales promedio ", "Otros mensuales promedio "])
    ws.append(["CEDULA", "1700000001", "Perez", "Ana", "VENDEDOR", "Ventas", "F",
               600, 400, 0, 0])
    ws.append(["CEDULA", "1700000002", "Gomez", "Luis", "OPERARIO", "Planta", "M",
               500, 0, 0, 0])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
```

- [ ] **Step 2: Escribir el test**

```python
# tests/test_composicion.py
from benchmarking.ingesta.composicion import parsear_plantilla, calcular_composicion

def test_parsear_columnas(plantilla_xlsx_bytes):
    df = parsear_plantilla(plantilla_xlsx_bytes)
    assert set(["identificacion","cargo","sueldo","comisiones","extras","otros"]).issubset(df.columns)
    assert len(df) == 2
    assert df.loc[0,"comisiones"] == 400

def test_composicion_suma_uno(plantilla_xlsx_bytes):
    df = calcular_composicion(parsear_plantilla(plantilla_xlsx_bytes))
    fila = df.iloc[0]
    assert abs(fila.total - 1000) < 1e-6
    assert abs(fila.pct_fijo + fila.pct_comisiones + fila.pct_extras + fila.pct_otros - 1) < 1e-6
    assert abs(fila.pct_comisiones - 0.4) < 1e-6
```

- [ ] **Step 3: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_composicion.py -v`
Expected: FAIL

- [ ] **Step 4: Implementar `composicion.py`**

```python
# src/benchmarking/ingesta/composicion.py
import io, unicodedata
from pathlib import Path
import pandas as pd
import yaml

_ESQUEMA = yaml.safe_load((Path(__file__).parent.parent / "config" / "esquema_plantilla.yaml").read_text(encoding="utf-8"))

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s)).upper()
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.replace("\n", " ").split()).strip()

def _match_col(cols, patrones, canonico):
    if canonico == "identificacion":
        for c in cols:
            if _norm(c).startswith("IDENTIFICACION"):
                return c
    if canonico == "cargo":
        for c in cols:
            if _norm(c) == "CARGO":
                return c
    for c in cols:
        n = _norm(c)
        if all(p in n for p in patrones):
            return c
    return None

def parsear_plantilla(xlsx_bytes: bytes) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name="Plantilla de empleados")
    mapa = {}
    for canonico, patrones in _ESQUEMA.items():
        col = _match_col(raw.columns, patrones, canonico)
        if col is not None:
            mapa[col] = canonico
    df = raw[list(mapa)].rename(columns=mapa)
    for m in ("sueldo", "comisiones", "extras", "otros"):
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors="coerce")
    df[["comisiones","extras","otros"]] = df[["comisiones","extras","otros"]].fillna(0)
    return df[df["identificacion"].notna() & df["sueldo"].notna()].reset_index(drop=True)

def calcular_composicion(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["total"] = out["sueldo"] + out["comisiones"] + out["extras"] + out["otros"]
    out = out[out["total"] > 0].copy()
    for rubro, pct in [("sueldo","pct_fijo"),("comisiones","pct_comisiones"),
                       ("extras","pct_extras"),("otros","pct_otros")]:
        out[pct] = out[rubro] / out["total"]
    return out.reset_index(drop=True)
```

- [ ] **Step 5: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_composicion.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/benchmarking/ingesta/composicion.py tests/test_composicion.py tests/conftest.py
git commit -m "feat: composicion (parseo plantilla xlsx + pct)"
```

---

### Task 5: Features derivadas de persona

**Files:**
- Create: `src/benchmarking/ingesta/features_base.py`
- Test: `tests/test_features_base.py`

**Interfaces:**
- Consumes: `Settings.get_sbu`.
- Produces: `agregar_features(df: pd.DataFrame, settings) -> pd.DataFrame`. Calcula `total`, `pct_fijo/pct_comisiones/pct_extras/pct_otros`, `tiene_composicion` (bool), `sueldo_sbu` (`total`/SBU año), `log_total` (ln(total)), `antiguedad_total` (años desde `fecha_ingreso`), `tuvo_salidas` (bool). Requiere `sueldo, anio_valoracion, fecha_ingreso` (date/None) y opcionalmente `comisiones/extras/otros` (montos, `NaN`/ausentes = sin composición) y `remuneracion_promedio`. **Regla de `total`:** con composición ⇒ `sueldo+comisiones+extras+otros`; sin ella ⇒ respaldo a `remuneracion_promedio` y luego `sueldo`. Los `pct_*` quedan `NaN` sin composición. `tuvo_salidas` es `False` cuando no hay `fecha_salida` (Fase 1 no dispone de fecha de salida en la view).

- [ ] **Step 1: Escribir el test**

```python
# tests/test_features_base.py
import math, datetime as dt
import pandas as pd
from benchmarking.config.settings import cargar_settings
from benchmarking.ingesta.features_base import agregar_features

def test_features_con_composicion(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"sueldo":600.0,"comisiones":300.0,"extras":20.0,"otros":0.0,
                        "remuneracion_promedio":None,"anio_valoracion":2024,
                        "fecha_ingreso":dt.date(2014,1,1),"fecha_salida":None}])
    out = agregar_features(df, s)
    assert out.loc[0,"total"] == 920.0
    assert out.loc[0,"tiene_composicion"] == True
    assert abs(out.loc[0,"sueldo_sbu"] - 2.0) < 1e-6          # 920 / 460
    assert abs(out.loc[0,"log_total"] - math.log(920)) < 1e-6
    assert abs(out.loc[0,"pct_fijo"] - 600/920) < 1e-6
    assert abs(out.loc[0,"pct_comisiones"] - 300/920) < 1e-6
    assert out.loc[0,"antiguedad_total"] == 10
    assert out.loc[0,"tuvo_salidas"] == False

def test_features_sin_composicion_usa_respaldo(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT","x")
    s = cargar_settings()
    df = pd.DataFrame([{"sueldo":700.0,"comisiones":float("nan"),"extras":float("nan"),
                        "otros":float("nan"),"remuneracion_promedio":800.0,
                        "anio_valoracion":2024,"fecha_ingreso":None,"fecha_salida":None}])
    out = agregar_features(df, s)
    assert out.loc[0,"total"] == 800.0                        # respaldo remuneracion_promedio
    assert out.loc[0,"tiene_composicion"] == False
    assert pd.isna(out.loc[0,"pct_fijo"])                     # sin composición -> NULL
    assert pd.isna(out.loc[0,"antiguedad_total"])            # sin fecha_ingreso
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_features_base.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `features_base.py`**

```python
# src/benchmarking/ingesta/features_base.py
import numpy as np
import pandas as pd

_RUBROS = ("comisiones", "extras", "otros")

def agregar_features(df: pd.DataFrame, settings) -> pd.DataFrame:
    out = df.copy()
    for m in _RUBROS:                       # asegura que los rubros existan
        if m not in out.columns:
            out[m] = np.nan
    # tiene_composicion: al menos un rubro NO nulo (la plantilla aportó montos)
    tiene = out[list(_RUBROS)].notna().any(axis=1)
    out["tiene_composicion"] = tiene
    # total: con composición = sueldo + rubros; sin ella = respaldo remuneracion_promedio -> sueldo
    total_comp = out["sueldo"].fillna(0) + out[list(_RUBROS)].fillna(0).sum(axis=1)
    respaldo = out["remuneracion_promedio"] if "remuneracion_promedio" in out else pd.Series(np.nan, index=out.index)
    respaldo = respaldo.fillna(out["sueldo"])
    out["total"] = total_comp.where(tiene, respaldo)
    # pct_*: solo donde hay composición (NaN en el resto)
    for rubro, pct in [("sueldo","pct_fijo"),("comisiones","pct_comisiones"),
                       ("extras","pct_extras"),("otros","pct_otros")]:
        out[pct] = (out[rubro].fillna(0) / out["total"]).where(tiene)
    sbu = out["anio_valoracion"].map(lambda a: settings.get_sbu(int(a)))
    out["sueldo_sbu"] = out["total"] / sbu
    out["log_total"] = np.log(out["total"].where(out["total"] > 0))
    def _ant(row):
        fi = row.get("fecha_ingreso")
        if fi is None or pd.isna(fi):
            return None
        return int(row["anio_valoracion"]) - fi.year
    out["antiguedad_total"] = out.apply(_ant, axis=1)
    out["tuvo_salidas"] = out.get("fecha_salida").notna() if "fecha_salida" in out else False
    return out
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_features_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/ingesta/features_base.py tests/test_features_base.py
git commit -m "feat: features derivadas (sueldo_sbu, log_total, antiguedad, salidas)"
```

---

### Task 6: Enriquecimiento SCVS (join)

**Files:**
- Create: `src/benchmarking/ingesta/enriquecimiento.py`
- Test: `tests/test_enriquecimiento.py`

**Interfaces:**
- Produces: `unir_scvs(df_base: pd.DataFrame, df_scvs: pd.DataFrame) -> pd.DataFrame`. `df_base` tiene `empresa_ruc`; `df_scvs` tiene `ruc, segmento, ciiu_n1, ciiu_n6, n_empleados` (una fila por ruc). Añade esas columnas + `provincia` (2 primeros dígitos del RUC). Left join (sin match → NULL).

- [ ] **Step 1: Escribir el test**

```python
# tests/test_enriquecimiento.py
import pandas as pd
from benchmarking.ingesta.enriquecimiento import unir_scvs

def test_join_y_provincia():
    base = pd.DataFrame({"empresa_ruc":["1790011111001","0999999999001"], "id_hash":["a","b"]})
    scvs = pd.DataFrame({"ruc":["1790011111001"], "segmento":["GRANDE"],
                         "ciiu_n1":["C"], "ciiu_n6":["C1071"], "n_empleados":[500]})
    out = unir_scvs(base, scvs)
    assert out.loc[0,"segmento"] == "GRANDE"
    assert out.loc[0,"provincia"] == "17"
    assert pd.isna(out.loc[1,"segmento"])          # sin match -> NULL
    assert out.loc[1,"provincia"] == "09"
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_enriquecimiento.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `enriquecimiento.py`**

```python
# src/benchmarking/ingesta/enriquecimiento.py
import pandas as pd

def unir_scvs(df_base: pd.DataFrame, df_scvs: pd.DataFrame) -> pd.DataFrame:
    out = df_base.merge(df_scvs, how="left", left_on="empresa_ruc", right_on="ruc")
    out["provincia"] = out["empresa_ruc"].astype(str).str[:2]
    return out.drop(columns=[c for c in ["ruc"] if c in out.columns])
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_enriquecimiento.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/ingesta/enriquecimiento.py tests/test_enriquecimiento.py
git commit -m "feat: enriquecimiento SCVS (join + provincia)"
```

---

### Task 7: Cliente de plantilla (HTTP)

**Files:**
- Create: `src/benchmarking/adquisicion/__init__.py`, `src/benchmarking/adquisicion/plantilla_client.py`
- Test: `tests/test_plantilla_client.py`

**Interfaces:**
- Consumes: `Settings.actuafast_base_url`.
- Produces: `descargar_plantilla(numero_proceso: str, id_version: str, base_url: str, session=None, reintentos=3) -> bytes | None`. Devuelve los bytes del XLSX, o `None` tras agotar reintentos en 5xx.

- [ ] **Step 1: Escribir el test (con requests mockeado)**

```python
# tests/test_plantilla_client.py
from unittest.mock import MagicMock
from benchmarking.adquisicion.plantilla_client import descargar_plantilla

def _resp(status, content=b"xlsxbytes"):
    r = MagicMock(); r.status_code = status; r.content = content
    r.raise_for_status = MagicMock()
    return r

def test_descarga_ok():
    ses = MagicMock(); ses.get.return_value = _resp(200)
    out = descargar_plantilla("140672","abc","http://x", session=ses)
    assert out == b"xlsxbytes"
    assert "estudios/140672/version/abc/plantilla-modificada" in ses.get.call_args[0][0]

def test_reintenta_y_se_rinde_en_503():
    ses = MagicMock(); ses.get.return_value = _resp(503)
    out = descargar_plantilla("1","v","http://x", session=ses, reintentos=2)
    assert out is None
    assert ses.get.call_count == 2
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_plantilla_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `plantilla_client.py`**

```python
# src/benchmarking/adquisicion/plantilla_client.py
import time
import requests

_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}

def descargar_plantilla(numero_proceso, id_version, base_url, session=None, reintentos=3):
    ses = session or requests.Session()
    url = f"{base_url.rstrip('/')}/estudios/{numero_proceso}/version/{id_version}/plantilla-modificada"
    for intento in range(reintentos):
        resp = ses.get(url, headers=_HEADERS, timeout=60)
        if resp.status_code in (500, 502, 503, 504):
            if intento < reintentos - 1:
                time.sleep(2 * (intento + 1))
            continue
        resp.raise_for_status()
        return resp.content
    return None
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_plantilla_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/adquisicion tests/test_plantilla_client.py
git commit -m "feat: cliente plantilla-modificada con reintentos"
```

---

### Task 8: Fuente BigQuery (lectura)

**Files:**
- Create: `src/benchmarking/adquisicion/bigquery_source.py`
- Test: `tests/test_bigquery_source.py`

**Interfaces:**
- Consumes: un `runner` con método `.query(sql).to_dataframe()` (inyectable = el `bigquery.Client`).
- Produces: `listar_estudios(runner, limite)` (`numero_proceso, id_version, anio_valoracion, empresa_ruc`). `leer_personas(runner, limite)` (la base por-persona: `identificacion, numero_proceso, id_version, anio_valoracion, empresa_ruc, cargo, sexo, edad, sueldo, remuneracion_promedio, fecha_ingreso`). `leer_scvs(runner)` (`ruc, segmento, ciiu_n1, ciiu_n6, n_empleados`). Las SQL son constantes del módulo; el `runner` se inyecta para mockearlo. El `limite` filtra por **estudio** (`numero_proceso IN` los primeros N), no por fila, para que muestra ⇒ estudios completos.

- [ ] **Step 1: Escribir el test (runner mockeado)**

```python
# tests/test_bigquery_source.py
from unittest.mock import MagicMock
import pandas as pd
from benchmarking.adquisicion.bigquery_source import listar_estudios, leer_personas, SQL_ESTUDIOS

def test_listar_estudios_usa_limite_y_devuelve_df():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"numero_proceso":["1"],"id_version":["v"],"anio_valoracion":[2024],"empresa_ruc":["17..."]})
    df = listar_estudios(runner, limite=5)
    assert list(df.columns) == ["numero_proceso","id_version","anio_valoracion","empresa_ruc"]
    sql = runner.query.call_args[0][0]
    assert "LIMIT 5" in sql and "estudios_actuariales" in sql

def test_leer_personas_limita_por_estudio():
    runner = MagicMock()
    runner.query.return_value.to_dataframe.return_value = pd.DataFrame(
        {"identificacion":["1700000001"],"numero_proceso":["1"],"id_version":["v"],
         "anio_valoracion":[2024],"empresa_ruc":["17"],"cargo":["X"],"sexo":["F"],
         "edad":[30],"sueldo":[500.0],"remuneracion_promedio":[None],"fecha_ingreso":[None]})
    df = leer_personas(runner, limite=3)
    sql = runner.query.call_args[0][0]
    assert "DENSE_RANK() OVER (ORDER BY numero_proceso) <= 3" in sql
    assert "identificacion_persona" in sql
    assert set(["identificacion","cargo","sueldo","remuneracion_promedio"]).issubset(df.columns)
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_source.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `bigquery_source.py`**

```python
# src/benchmarking/adquisicion/bigquery_source.py
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
  UPPER(sexo_persona) sexo,
  SAFE_CAST(edad AS INT64) edad,
  sueldo,
  COALESCE(remuneracion_promedio_desahucio, remuneracion_promedio_jubilacion) remuneracion_promedio,
  COALESCE(fecha_ingreso_desahucio, fecha_ingreso_jubilacion) fecha_ingreso
FROM {_VIEW}
WHERE es_ultima_version AND numero_proceso IS NOT NULL
  AND id_version IS NOT NULL AND identificacion_persona IS NOT NULL
"""

SQL_SCVS = f"""
WITH b AS (SELECT ruc, segmento, ciiu_n1, ciiu_n6, n_empleados,
             ROW_NUMBER() OVER(PARTITION BY ruc ORDER BY anio DESC) rn
           FROM {_BAL} WHERE segmento IS NOT NULL)
SELECT CAST(ruc AS STRING) ruc, segmento, ciiu_n1, ciiu_n6, n_empleados
FROM b WHERE rn = 1
"""
# ruc se castea a STRING para que el join con empresa_ruc (tambien STRING en
# SQL_PERSONAS) no falle en RUCs con provincia 01-09 por desajuste de dtype.

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

def leer_scvs(runner):
    return runner.query(SQL_SCVS).to_dataframe()
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/adquisicion/bigquery_source.py tests/test_bigquery_source.py
git commit -m "feat: fuente BigQuery (listar estudios, leer personas base, leer SCVS) con runner inyectable"
```

---

### Task 9: Sink BigQuery (escritura)

**Files:**
- Create: `src/benchmarking/escritura/__init__.py`, `src/benchmarking/escritura/bigquery_sink.py`
- Test: `tests/test_bigquery_sink.py`

**Interfaces:**
- Consumes: `bigquery.Client` (inyectable), `Settings.bq_project`, `.bq_dataset`.
- Produces: `escribir(df: pd.DataFrame, client, project: str, dataset: str, tabla="nomina_features", location="us-central1") -> str` (devuelve el id de tabla). Usa `client.load_table_from_dataframe` con `WRITE_TRUNCATE`, partición por `anio_valoracion`, cluster por `empresa_ruc`. Verifica que ninguna columna PII (`identificacion`, `nombres`, `apellidos`) esté presente (aserción de la frontera).

- [ ] **Step 1: Escribir el test (client mockeado + guardia de PII)**

```python
# tests/test_bigquery_sink.py
from unittest.mock import MagicMock
import pandas as pd, pytest
from benchmarking.escritura.bigquery_sink import escribir

def test_rechaza_pii():
    df = pd.DataFrame({"id_hash":["a"], "identificacion":["1700000001"]})
    with pytest.raises(ValueError):
        escribir(df, MagicMock(), "proj", "ds")

def test_escribe_y_devuelve_tabla():
    df = pd.DataFrame({"id_hash":["a"], "anio_valoracion":[2024], "empresa_ruc":["17"]})
    client = MagicMock(); client.load_table_from_dataframe.return_value.result.return_value = None
    tid = escribir(df, client, "proj", "ds")
    assert tid == "proj.ds.nomina_features"
    assert client.load_table_from_dataframe.called
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_sink.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `bigquery_sink.py`**

```python
# src/benchmarking/escritura/bigquery_sink.py
from google.cloud import bigquery

_PII = {"identificacion", "cedula", "nombres", "apellidos", "nombre_completo_persona"}

def escribir(df, client, project, dataset, tabla="nomina_features", location="us-central1"):
    fugas = _PII.intersection(df.columns)
    if fugas:
        raise ValueError(f"Frontera de privacidad violada: columnas PII presentes {fugas}")
    table_id = f"{project}.{dataset}.{tabla}"
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE",
        clustering_fields=["empresa_ruc"] if "empresa_ruc" in df.columns else None,
    )
    if "anio_valoracion" in df.columns:
        job_config.range_partitioning = bigquery.RangePartitioning(
            field="anio_valoracion",
            range_=bigquery.PartitionRange(start=2016, end=2027, interval=1))
    client.load_table_from_dataframe(df, table_id, job_config=job_config, location=location).result()
    return table_id
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_bigquery_sink.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/benchmarking/escritura tests/test_bigquery_sink.py
git commit -m "feat: sink BigQuery con guardia de frontera (rechaza PII)"
```

---

### Task 10: Orquestador + CLI (integración)

**Files:**
- Create: `src/benchmarking/orquestador.py`, `src/benchmarking/cli.py`
- Test: `tests/test_orquestador.py`

**Interfaces:**
- Consumes: todo lo anterior. `normalizar_cargo(s)` reutiliza `_norm` de `composicion`.
- Produces: `construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla) -> pd.DataFrame`. **Base = estudios BQ** (`leer_personas`, todas las filas persona-estudio); por cada estudio descarga la plantilla y **enlaza la composición** (`comisiones/extras/otros`) por `numero_proceso` + cédula (left join, `NaN` sin plantilla — **no se descartan filas**); normaliza cargo, anonimiza (frontera), calcula features (total/pct NULL-safe), marca cuarentena, enriquece SCVS. Devuelve el DataFrame `nomina_features` (sin escribir). `main()` para el CLI. **Orden clave:** el enlace de composición usa la cédula cruda y ocurre *antes* de `anonimizar`; `agregar_features` corre *antes* de `marcar_cuarentena` (que depende de `total`).

- [ ] **Step 1: Escribir el test de integración (todo mockeado, data sintética)**

El fixture `plantilla_xlsx_bytes` tiene 2 personas (cédulas `1700000001` VENDEDOR y `1700000002` OPERARIO). La base de personas debe traer las mismas cédulas para que el enlace funcione; una tercera persona sin plantilla valida que **no se pierde** aunque no tenga composición.

```python
# tests/test_orquestador.py
import datetime as dt
from unittest.mock import MagicMock
import pandas as pd
from benchmarking.config.settings import cargar_settings
from benchmarking.orquestador import construir_base

def test_construir_base_end_to_end(monkeypatch, plantilla_xlsx_bytes):
    monkeypatch.setenv("PIPELINE_SALT","sal")
    s = cargar_settings()
    runner = MagicMock()
    def fake_query(sql):
        m = MagicMock()
        if "scvs" in sql.lower() or "balances" in sql.lower():
            m.to_dataframe.return_value = pd.DataFrame(
                {"ruc":["1790011111001"],"segmento":["GRANDE"],"ciiu_n1":["G"],
                 "ciiu_n6":["G4711"],"n_empleados":[300]})
        else:  # SQL_PERSONAS -> la base por-persona
            m.to_dataframe.return_value = pd.DataFrame({
                "identificacion":["1700000001","1700000002","1700000009"],
                "numero_proceso":["140672","140672","140672"],
                "id_version":["abc","abc","abc"],
                "anio_valoracion":[2024,2024,2024],
                "empresa_ruc":["1790011111001","1790011111001","1790011111001"],
                "cargo":["VENDEDOR","OPERARIO","GERENTE"],
                "sexo":["F","M","M"],
                "edad":[30,40,50],
                "sueldo":[600.0,500.0,900.0],
                "remuneracion_promedio":[None,None,1100.0],   # esta persona no está en la plantilla
                "fecha_ingreso":[dt.date(2014,1,1),dt.date(2010,1,1),dt.date(2000,1,1)]})
        return m
    runner.query.side_effect = fake_query
    df = construir_base(runner, "http://x", s, limite=1,
                        descargar=lambda *a, **k: plantilla_xlsx_bytes)
    # frontera de privacidad
    assert "id_hash" in df.columns and "identificacion" not in df.columns
    assert {"pct_fijo","tiene_composicion","sueldo_sbu","segmento","provincia","en_clean"}.issubset(df.columns)
    # no se pierde ninguna persona (3 en la base, aunque 1 no tenga plantilla)
    assert len(df) == 3
    # persona con composición: total = sueldo(600) + comisiones(400) = 1000
    fila_vend = df[df.cargo_norm == "VENDEDOR"].iloc[0]
    assert fila_vend.tiene_composicion == True
    assert abs(fila_vend.total - 1000.0) < 1e-6
    assert abs(fila_vend.pct_comisiones - 0.4) < 1e-6
    assert fila_vend.segmento == "GRANDE"
    # persona sin plantilla: se conserva, composición NULL, total = respaldo remuneracion_promedio
    fila_ger = df[df.cargo_norm == "GERENTE"].iloc[0]
    assert fila_ger.tiene_composicion == False
    assert pd.isna(fila_ger.pct_fijo)
    assert abs(fila_ger.total - 1100.0) < 1e-6
```

- [ ] **Step 2: Ejecutar (debe fallar)**

Run: `.venv/Scripts/python -m pytest tests/test_orquestador.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `orquestador.py`**

```python
# src/benchmarking/orquestador.py
import pandas as pd
from .adquisicion.bigquery_source import leer_personas, leer_scvs
from .adquisicion.plantilla_client import descargar_plantilla
from .ingesta.composicion import parsear_plantilla, _norm
from .ingesta.anonimizacion import anonimizar
from .ingesta.validacion import marcar_cuarentena
from .ingesta.features_base import agregar_features
from .ingesta.enriquecimiento import unir_scvs

def _composicion_estudios(estudios, base_url, descargar):
    """Descarga la plantilla de cada estudio y devuelve solo los montos por (numero_proceso, cedula)."""
    partes = []
    for e in estudios.itertuples():
        raw = descargar(e.numero_proceso, e.id_version, base_url)
        if not raw:
            continue                                   # 5xx agotados o sin plantilla: se omite el estudio
        m = parsear_plantilla(raw)[["identificacion", "comisiones", "extras", "otros"]].copy()
        m["identificacion"] = m["identificacion"].astype(str)
        m["numero_proceso"] = e.numero_proceso
        partes.append(m)
    cols = ["identificacion", "comisiones", "extras", "otros", "numero_proceso"]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=cols)

def construir_base(runner, base_url, settings, limite=None, descargar=descargar_plantilla):
    base = leer_personas(runner, limite)               # BASE = estudios BQ, todas las filas
    if base.empty:
        return base
    base["identificacion"] = base["identificacion"].astype(str)
    estudios = base[["numero_proceso", "id_version"]].drop_duplicates()
    comp = _composicion_estudios(estudios, base_url, descargar)
    # enlace por cédula (cruda) ANTES de anonimizar; left join: NaN donde no hubo plantilla
    df = base.merge(comp, how="left", on=["numero_proceso", "identificacion"])
    df["cargo_orig"] = df["cargo"]
    df["cargo_norm"] = df["cargo"].map(_norm)
    df = anonimizar(df, settings.salt)                 # FRONTERA: elimina cédula (+ nombres si hubiera)
    df = agregar_features(df, settings)                # total/pct NULL-safe, sueldo_sbu, antiguedad...
    df = marcar_cuarentena(df, settings)               # depende de total -> corre despues de features
    df = unir_scvs(df, leer_scvs(runner))
    return df
```

- [ ] **Step 4: Ejecutar (debe pasar)**

Run: `.venv/Scripts/python -m pytest tests/test_orquestador.py -v`
Expected: PASS

- [ ] **Step 5: Implementar el CLI `cli.py`**

```python
# src/benchmarking/cli.py
import argparse
from google.cloud import bigquery
from .config.settings import cargar_settings
from .orquestador import construir_base
from .escritura.bigquery_sink import escribir

def main():
    ap = argparse.ArgumentParser(prog="benchmarking")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cb = sub.add_parser("construir-base")
    cb.add_argument("--muestra", type=int, default=None, help="limitar a N estudios (desarrollo)")
    cb.add_argument("--dry-run", action="store_true", help="no escribir a BigQuery")
    args = ap.parse_args()
    s = cargar_settings()
    client = bigquery.Client()
    df = construir_base(client, s.actuafast_base_url, s, limite=args.muestra)
    print(f"nomina_features: {len(df)} filas")
    if not args.dry_run and len(df):
        tid = escribir(df, client, s.bq_project, s.bq_dataset)
        print(f"escrito en {tid}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Verificar smoke del CLI (dry-run con muestra pequeña, requiere auth GCP)**

Run: `PIPELINE_SALT=test .venv/Scripts/python -m benchmarking.cli construir-base --muestra 3 --dry-run`
Expected: imprime "nomina_features: N filas" sin escribir. (Si falla por auth, correr `gcloud auth login` primero.)

- [ ] **Step 7: Commit**

```bash
git add src/benchmarking/orquestador.py src/benchmarking/cli.py tests/test_orquestador.py
git commit -m "feat: orquestador + CLI construir-base (integracion end-to-end)"
```

---

## Notas de ejecución final (fuera de TDD, requieren credenciales)

Tras pasar todos los tests:
1. **Crear el dataset destino:** `bq --location=us-central1 mk -d act-cicd-stage-prueba:benchmarking_tesis` (confirmar permiso; plan B `act-poc-simulador`).
2. **Correr en muestra estratificada** para validar E2 antes del universo.
3. **Correr el universo** (`construir-base`, ~48k estudios, ~1–2 h reanudable) → la única escritura de la base.

La **reanudabilidad** (checkpoint de estudios procesados) y la **concurrencia de descargas** se añaden como refinamiento del orquestador una vez validado el flujo secuencial — no bloquean el v1 funcional.

## Fuera de alcance de este plan (Fase 2, plan aparte)

Enriquecimiento DINARDAP (`profesion_dinardap` vía MERGE incremental), copiando `dinardap_client` de `iess-scrapper`. Vectorización y clustering. Backfill DINARDAP del universo.
