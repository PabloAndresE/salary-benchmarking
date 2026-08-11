# Banco de validación y baseline — Plan de implementación

> **Para trabajadores agénticos:** SUB-SKILL REQUERIDO: usar `superpowers:subagent-driven-development`
> (recomendado) o `superpowers:executing-plans` para ejecutar este plan tarea por tarea. Los pasos
> usan casillas (`- [ ]`) para seguimiento.

**Objetivo:** Construir el instrumento que mide si una forma de agrupar personas predice el salario
mejor que la etiqueta `CARGO`, y estrenarlo con dos baselines de k-means.

**Arquitectura:** Un paquete `src/benchmarking/evaluacion/` con seis módulos de responsabilidad
única, encadenados por DataFrames de pandas. El flujo es: cargar marco → partir empresas →
construir particiones rivales → estimar la referencia salarial de cada celda con donantes de otras
empresas → puntuar error y cobertura → informar. Un subcomando `benchmarking evaluar` lo orquesta.
Todo se prueba con data sintética de estructura conocida; nada de data real en el repo.

**Stack:** Python 3.11, pandas, numpy, scikit-learn (TF-IDF y k-means), matplotlib (la curva),
pytest. BigQuery solo como origen de lectura.

## Restricciones globales

- **Frontera de privacidad:** nada aguas abajo de `anonimizacion` ve identificadores. El banco
  trabaja con `id_hash`; jamás con `identificacion`. Data real nunca al repositorio.
- **Unidad estadística = empresa.** Todos los splits y remuestreos son por `empresa_ruc`, nunca por
  fila. Una persona recurre entre años y una empresa aporta muchas personas.
- **Determinismo:** toda semilla fija y explícita. Semilla del proyecto: `20260805`.
- **Anti-circularidad:** el salario no entra jamás como característica de agrupamiento. La
  granularidad y la familia se eligen por estabilidad, nunca por acierto salarial (D-005).
- **Estilo del repositorio:** código directo y legible sobre abstracciones ingeniosas; comentarios
  en español explicando el porqué, no el qué; tests con data sintética.
- Tabla origen: `act-cicd-stage-prueba.benchmarking_tesis.nomina_features`.

## Dos trampas heredadas que este plan evita

**1. `sueldo_sbu` no es `sueldo/SBU`.** En `features_base.py:28` se define como `total / SBU`. Quien
la use por su nombre medirá otra cosa. Este plan **calcula el objetivo explícitamente** y no toca
esa columna. (Renombrarla queda como limpieza aparte: exige reprocesar.)

**2. La mediana con leave-company-out no escala.** Excluir la empresa de cada persona obliga a
recalcular la mediana por cada par (celda, empresa); con las 55.920 celdas de `CARGO` son cientos de
miles de medianas. **Se usa la media en espacio logarítmico**, que es la media geométrica en niveles
—justo lo robusto a la asimetría que motivaba la mediana— y permite quitar una empresa con una
resta O(1). Desviación explícita del spec §5, registrada en el pre-registro, con la variante mediana
como chequeo de robustez sobre submuestra (Tarea 12).

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/benchmarking/evaluacion/__init__.py` | paquete vacío |
| `src/benchmarking/evaluacion/datos.py` | leer el marco desde BigQuery y calcular la variable objetivo |
| `src/benchmarking/evaluacion/splits.py` | partir empresas estratificado, con persistencia |
| `src/benchmarking/evaluacion/referencia.py` | donantes leave-company-out, abstención, predicción |
| `src/benchmarking/evaluacion/metricas.py` | error, cobertura, curva, ω², bootstrap por empresa |
| `src/benchmarking/evaluacion/particiones.py` | los cuatro rivales de la escalera |
| `src/benchmarking/evaluacion/estabilidad.py` | test-retest 2024↔2025 y ARI entre submuestras |
| `src/benchmarking/evaluacion/informe.py` | tabla comparativa y gráfico de la curva |
| `src/benchmarking/cli.py` | subcomando `evaluar` (modificar) |
| `tests/sintetico.py` | generador de data sintética con respuesta conocida |
| `tests/test_evaluacion_*.py` | uno por módulo |
| `docs/preregistro.md` | documento congelado antes de tocar el test |

---

### Tarea 1: Generador de data sintética con respuesta conocida

Todo lo demás se prueba contra esto, así que va primero. Genera personas con rol conocido, para
poder exigirle al banco que reconozca la partición verdadera.

**Archivos:**
- Crear: `tests/sintetico.py`
- Test: `tests/test_sintetico.py`

**Interfaces:**
- Consume: nada
- Produce: `generar(n_empresas=40, personas_por_empresa=25, n_roles=3, semilla=20260805) -> pd.DataFrame`
  con columnas `id_hash, empresa_ruc, numero_proceso, anio_valoracion, rol_verdadero, cargo,
  cargo_norm, sueldo, comisiones, extras, otros, total, pct_fijo, pct_comisiones, pct_extras,
  pct_otros, antiguedad_total, segmento, ciiu_n1, provincia, en_clean, tiene_composicion`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_sintetico.py
import pandas as pd
from sintetico import generar


def test_estructura_basica():
    df = generar(n_empresas=10, personas_por_empresa=20, n_roles=3)
    assert len(df) == 200
    assert df["empresa_ruc"].nunique() == 10
    assert df["rol_verdadero"].nunique() == 3
    assert df["id_hash"].is_unique
    # la frontera de privacidad tambien aplica a la data de prueba
    assert "identificacion" not in df.columns


def test_los_roles_se_distinguen_por_composicion_no_solo_por_sueldo():
    # Si los roles solo se distinguieran por el sueldo, el banco no probaria nada:
    # cualquier particion por bandas salariales lo resolveria.
    df = generar(n_empresas=30, personas_por_empresa=20, n_roles=3)
    medias = df.groupby("rol_verdadero")["pct_comisiones"].mean().sort_values()
    assert medias.iloc[-1] - medias.iloc[0] > 0.25, "los roles deben separarse por composicion"


def test_hay_efecto_empresa():
    # Sin efecto empresa el leave-company-out no probaria nada.
    df = generar(n_empresas=30, personas_por_empresa=20, n_roles=3)
    import numpy as np
    y = np.log(df["sueldo"])
    total = ((y - y.mean()) ** 2).sum()
    medias = df.assign(y=y).groupby("empresa_ruc")["y"].agg(["mean", "size"])
    entre = (medias["size"] * (medias["mean"] - y.mean()) ** 2).sum()
    assert 0.10 < entre / total < 0.70, "el efecto empresa debe existir y no dominarlo todo"


def test_determinista():
    a = generar(n_empresas=5, personas_por_empresa=10, semilla=7)
    b = generar(n_empresas=5, personas_por_empresa=10, semilla=7)
    pd.testing.assert_frame_equal(a, b)
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_sintetico.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'sintetico'`

- [ ] **Paso 3: Implementar el generador**

```python
# tests/sintetico.py
"""Data sintetica con la respuesta conocida.

El banco de validacion se prueba contra esto: si no ordena correctamente la particion
verdadera frente a una aleatoria, el banco esta mal. Descubrirlo aqui cuesta segundos;
descubrirlo tras nueve semanas de medir con una regla torcida, no.

Los roles se separan por COMPOSICION del pago y antiguedad, no por nivel salarial, para
que una particion por bandas de sueldo no resuelva el problema por la puerta de atras.
"""
import numpy as np
import pandas as pd

# (nombre, pct_comisiones medio, pct_extras medio, antiguedad media, multiplicador salarial)
_ROLES = [
    ("comercial",     0.45, 0.02,  6.0, 1.8),
    ("operativo",     0.01, 0.28,  9.0, 1.0),
    ("administrativo", 0.02, 0.03, 11.0, 1.3),
    ("tecnico",       0.05, 0.15,  7.0, 1.5),
]
_CARGOS = {                       # etiquetas sucias: la misma vale para varios roles
    "comercial": ["VENDEDOR", "ASESOR COMERCIAL", "TRABAJADOR EN GENERAL"],
    "operativo": ["OPERARIO", "TRABAJADOR EN GENERAL", "OBRERO"],
    "administrativo": ["ASISTENTE", "TRABAJADOR EN GENERAL", "AUXILIAR"],
    "tecnico": ["TECNICO", "ASISTENTE", "OPERARIO"],
}


def generar(n_empresas=40, personas_por_empresa=25, n_roles=3, semilla=20260805,
            anio=2025, sbu=470):
    rng = np.random.default_rng(semilla)
    roles = _ROLES[:n_roles]
    filas = []
    for e in range(n_empresas):
        ruc = f"179{e:07d}001"
        # efecto empresa: cada empleador paga en un nivel propio (~34% de la varianza real)
        nivel_empresa = rng.normal(0.0, 0.35)
        segmento = ["MICRO", "PEQUENA", "MEDIANA", "GRANDE"][e % 4]
        provincia = f"{(e % 24) + 1:02d}"
        for p in range(personas_por_empresa):
            i = (e * personas_por_empresa + p) % len(roles)
            nombre, m_com, m_ext, m_ant, mult = roles[i]
            base = sbu * mult * np.exp(nivel_empresa + rng.normal(0.0, 0.18))
            pc = float(np.clip(rng.normal(m_com, 0.08), 0.0, 0.85))
            pe = float(np.clip(rng.normal(m_ext, 0.05), 0.0, 0.60))
            po = float(np.clip(rng.normal(0.02, 0.02), 0.0, 0.30))
            pf = max(1.0 - pc - pe - po, 0.05)
            total = base / pf                       # `base` es la parte fija
            filas.append({
                "id_hash": f"h{e:04d}{p:04d}",
                "empresa_ruc": ruc,
                "numero_proceso": f"P{e:05d}",
                "anio_valoracion": anio,
                "rol_verdadero": nombre,
                "cargo": _CARGOS[nombre][p % len(_CARGOS[nombre])],
                "sueldo": round(base, 2),
                "comisiones": round(total * pc, 2),
                "extras": round(total * pe, 2),
                "otros": round(total * po, 2),
                "total": round(total, 2),
                "pct_fijo": pf, "pct_comisiones": pc, "pct_extras": pe, "pct_otros": po,
                "antiguedad_total": int(max(0, rng.normal(m_ant, 3.0))),
                "segmento": segmento,
                "ciiu_n1": chr(ord("A") + (e % 8)),
                "provincia": provincia,
                "en_clean": True,
                "tiene_composicion": True,
            })
    df = pd.DataFrame(filas)
    df["cargo_norm"] = df["cargo"]
    return df
```

- [ ] **Paso 4: Permitir importar `sintetico` desde los tests**

Modificar `pyproject.toml`, sección `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "tests"]
```

- [ ] **Paso 5: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_sintetico.py -v`
Esperado: 4 passed

- [ ] **Paso 6: Commit**

```bash
git add tests/sintetico.py tests/test_sintetico.py pyproject.toml
git commit -m "test: generador de data sintetica con rol conocido para el banco"
```

---

### Tarea 2: Carga del marco y variable objetivo

**Archivos:**
- Crear: `src/benchmarking/evaluacion/__init__.py` (vacío)
- Crear: `src/benchmarking/evaluacion/datos.py`
- Test: `tests/test_evaluacion_datos.py`

**Interfaces:**
- Consume: `benchmarking.config.settings.Settings` (método `get_sbu(anio) -> int`)
- Produce:
  - `SQL_MARCO: str`
  - `cargar_marco(runner, proyecto, dataset, anios=(2024, 2025)) -> pd.DataFrame`
  - `agregar_objetivo(df, settings) -> pd.DataFrame` — añade la columna `y`
  - `marco_evaluable(df) -> pd.DataFrame` — filas con `y` e `cargo` utilizable

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_datos.py
import numpy as np
import pandas as pd
import pytest
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion.datos import agregar_objetivo, marco_evaluable, SQL_MARCO


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT", "x")
    return cargar_settings()


def test_objetivo_es_log_de_sueldo_sobre_sbu_no_de_total(s):
    # Trampa heredada: la columna `sueldo_sbu` de la tabla es total/SBU, NO sueldo/SBU
    # (features_base.py:28). El objetivo se calcula aparte para no medir otra cosa.
    df = pd.DataFrame({"sueldo": [940.0], "total": [1880.0], "anio_valoracion": [2025]})
    out = agregar_objetivo(df, s)
    assert abs(out["y"].iloc[0] - np.log(940.0 / 470)) < 1e-9   # SBU 2025 = 470
    assert abs(out["y"].iloc[0] - np.log(1880.0 / 470)) > 0.5   # y no el total


def test_objetivo_nulo_si_el_sueldo_no_es_positivo(s):
    df = pd.DataFrame({"sueldo": [0.0, -5.0, np.nan, 500.0],
                       "total": [1.0, 1.0, 1.0, 500.0],
                       "anio_valoracion": [2025] * 4})
    out = agregar_objetivo(df, s)
    assert out["y"].isna().tolist() == [True, True, True, False]


def test_marco_evaluable_exige_objetivo_y_cargo():
    # El baseline CARGO no puede competir donde no hay etiqueta: esas filas se
    # reportan aparte como cobertura exclusiva, no entran a la comparacion.
    df = pd.DataFrame({
        "y": [1.0, 1.0, np.nan, 1.0],
        "cargo_norm": ["CONTADOR", "", "CONTADOR", "0"],
    })
    out = marco_evaluable(df)
    assert len(out) == 1 and out["cargo_norm"].iloc[0] == "CONTADOR"


def test_sql_no_pide_identificadores():
    # frontera de privacidad
    assert "identificacion" not in SQL_MARCO
    assert "id_hash" in SQL_MARCO
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_datos.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion'`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/__init__.py
```

```python
# src/benchmarking/evaluacion/datos.py
"""Carga del marco de evaluacion y calculo de la variable objetivo."""
import re
import numpy as np
import pandas as pd

_PLACEHOLDERS = {"0", "-", "NA", "N/A", ".", "--", "S/N", "SN", "X", "", "NAN", "NONE"}

SQL_MARCO = """
SELECT id_hash, empresa_ruc, numero_proceso, anio_valoracion,
       cargo_norm, centro_de_costo, sueldo, total,
       pct_fijo, pct_comisiones, pct_extras, pct_otros,
       antiguedad_total, tiene_composicion, en_clean,
       segmento, ciiu_n1, provincia
FROM `{proyecto}.{dataset}.nomina_features`
WHERE en_clean AND anio_valoracion IN ({anios})
"""


def cargar_marco(runner, proyecto, dataset, anios=(2024, 2025)):
    sql = SQL_MARCO.format(proyecto=proyecto, dataset=dataset,
                           anios=", ".join(str(int(a)) for a in anios))
    return runner.query(sql).to_dataframe()


def agregar_objetivo(df, settings):
    """Anade `y` = log(sueldo / SBU del anio).

    Se usa `sueldo` y no `total` porque `total` solo esta bien definido donde hay
    composicion; un objetivo que cambia de definicion entre filas no es comparable.

    OJO: la columna `sueldo_sbu` de la tabla NO sirve para esto: vale total/SBU
    (features_base.py:28). Se calcula aqui explicitamente.
    """
    out = df.copy()
    sbu = out["anio_valoracion"].map(
        lambda a: settings.get_sbu(0 if pd.isna(a) else int(a)))
    sueldo = pd.to_numeric(out["sueldo"], errors="coerce")
    with np.errstate(invalid="ignore", divide="ignore"):
        out["y"] = np.log((sueldo / sbu).where(sueldo > 0))
    return out


def _cargo_utilizable(c):
    s = str(c or "").strip().upper()
    return s not in _PLACEHOLDERS and not re.fullmatch(r"[0-9]+", s)


def marco_evaluable(df):
    """Filas donde la comparacion contra CARGO es posible: objetivo y etiqueta.

    Las filas sin cargo NO se descartan del proyecto: se reportan aparte como
    cobertura exclusiva del arquetipo (spec §6.3). Simplemente no entran en una
    comparacion donde el rival no puede jugar.
    """
    return df[df["y"].notna() & df["cargo_norm"].map(_cargo_utilizable)].copy()
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_datos.py -v`
Esperado: 4 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion tests/test_evaluacion_datos.py
git commit -m "feat(evaluacion): carga del marco y variable objetivo log(sueldo/SBU)"
```

---

### Tarea 3: Split por empresa, estratificado y persistente

**Archivos:**
- Crear: `src/benchmarking/evaluacion/splits.py`
- Test: `tests/test_evaluacion_splits.py`

**Interfaces:**
- Consume: DataFrame con `empresa_ruc`, `segmento`, `ciiu_n1`
- Produce:
  - `empresas_test(df, frac=0.2, semilla=20260805) -> set[str]`
  - `partir(df, empresas_de_test) -> tuple[pd.DataFrame, pd.DataFrame]` (train, test)
  - `guardar(empresas, ruta) -> str` (devuelve el hash sha256 del listado)
  - `cargar(ruta) -> set[str]`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_splits.py
from benchmarking.evaluacion.splits import empresas_test, partir, guardar, cargar
from sintetico import generar


def test_ninguna_empresa_cruza():
    # Si una empresa apareciera en los dos lados, el leave-company-out no serviria
    # de nada: el modelo habria visto a los companeros de la persona evaluada.
    df = generar(n_empresas=40, personas_por_empresa=10)
    te = empresas_test(df, frac=0.25)
    tr, ts = partir(df, te)
    assert set(tr["empresa_ruc"]) & set(ts["empresa_ruc"]) == set()
    assert len(tr) + len(ts) == len(df)


def test_proporcion_aproximada():
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert 8 <= len(empresas_test(df, frac=0.2)) <= 12


def test_estratifica_por_segmento_y_sector():
    # Sin estratificar, el test podria quedar sesgado a un tipo de empresa y la
    # comparacion mediria eso en vez del metodo.
    df = generar(n_empresas=40, personas_por_empresa=10)
    te = empresas_test(df, frac=0.25)
    ts = df[df["empresa_ruc"].isin(te)]
    assert ts["segmento"].nunique() == df["segmento"].nunique()


def test_determinista():
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert empresas_test(df, frac=0.2, semilla=7) == empresas_test(df, frac=0.2, semilla=7)
    assert empresas_test(df, frac=0.2, semilla=7) != empresas_test(df, frac=0.2, semilla=8)


def test_persistencia_con_hash(tmp_path):
    # El hash entra en el pre-registro: prueba de que el test-set no se cambio despues.
    df = generar(n_empresas=20, personas_por_empresa=5)
    te = empresas_test(df, frac=0.2)
    ruta = tmp_path / "split.json"
    h = guardar(te, ruta)
    assert len(h) == 64 and cargar(ruta) == te
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_splits.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion.splits'`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/splits.py
"""Particion train/test por EMPRESA.

Por empresa y no por fila: una persona pertenece a una empresa y recurre entre anios,
asi que partir por filas dejaria a la misma persona (y a sus companeros) en los dos
lados, y el leave-company-out de la referencia salarial no probaria nada.
"""
import hashlib
import json
import numpy as np
import pandas as pd

SEMILLA = 20260805


def empresas_test(df, frac=0.2, semilla=SEMILLA):
    """Elige el conjunto de empresas apartadas, estratificando por segmento x sector."""
    emp = (df[["empresa_ruc", "segmento", "ciiu_n1"]]
           .drop_duplicates(subset=["empresa_ruc"])
           .sort_values("empresa_ruc")                      # orden estable
           .reset_index(drop=True))
    emp["estrato"] = emp["segmento"].astype(str) + "|" + emp["ciiu_n1"].astype(str)
    rng = np.random.default_rng(semilla)
    elegidas = []
    for _, grupo in emp.groupby("estrato", sort=True):
        rucs = grupo["empresa_ruc"].tolist()
        # al menos una por estrato: con estratos pequenos, round() los dejaria fuera
        n = max(1, int(round(len(rucs) * frac)))
        idx = rng.permutation(len(rucs))[:n]
        elegidas.extend(rucs[i] for i in sorted(idx))
    return set(elegidas)


def partir(df, empresas_de_test):
    en_test = df["empresa_ruc"].isin(empresas_de_test)
    return df[~en_test].copy(), df[en_test].copy()


def guardar(empresas, ruta):
    """Persiste el listado y devuelve su sha256, que va al pre-registro."""
    lista = sorted(str(e) for e in empresas)
    payload = json.dumps({"empresas_test": lista}, ensure_ascii=False, indent=2)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(payload)
    return hashlib.sha256("\n".join(lista).encode("utf-8")).hexdigest()


def cargar(ruta):
    with open(ruta, encoding="utf-8") as fh:
        return set(json.load(fh)["empresas_test"])
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_splits.py -v`
Esperado: 5 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/splits.py tests/test_evaluacion_splits.py
git commit -m "feat(evaluacion): split por empresa estratificado, con hash para el pre-registro"
```

---

### Tarea 4: Referencia salarial con donantes de otras empresas

El corazón del banco. Dada una partición, estima el salario de referencia de cada persona de test
usando solo gente de su misma celda **en otras empresas**, y se abstiene si no hay donantes
suficientes.

**Archivos:**
- Crear: `src/benchmarking/evaluacion/referencia.py`
- Test: `tests/test_evaluacion_referencia.py`

**Interfaces:**
- Consume: train y test con columnas `empresa_ruc`, `y`, y una columna de celda
- Produce: `predecir(train, test, col_celda, min_donantes=5, min_empresas=3) -> pd.DataFrame`
  con columnas `y_ref` (NaN = abstención), `n_donantes`, `n_empresas_donantes`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_referencia.py
import numpy as np
import pandas as pd
from benchmarking.evaluacion.referencia import predecir


def _marco(filas):
    return pd.DataFrame(filas, columns=["empresa_ruc", "celda", "y"])


def test_excluye_la_propia_empresa():
    # El efecto empresa explica ~34% de la varianza del salario: si la referencia
    # incluyera a los companeros, se acertaria por la razon equivocada.
    train = _marco([("E1", "c", 10.0), ("E1", "c", 10.0), ("E1", "c", 10.0),
                    ("E2", "c", 1.0), ("E3", "c", 1.0), ("E4", "c", 1.0),
                    ("E5", "c", 1.0), ("E6", "c", 1.0)])
    test = _marco([("E1", "c", 10.0)])
    out = predecir(train, test, "celda", min_donantes=5, min_empresas=3)
    assert abs(out["y_ref"].iloc[0] - 1.0) < 1e-9      # 1.0, no la media con E1
    assert out["n_donantes"].iloc[0] == 5


def test_se_abstiene_con_pocos_donantes():
    train = _marco([("E2", "c", 1.0), ("E3", "c", 1.0)])
    test = _marco([("E1", "c", 1.0)])
    out = predecir(train, test, "celda", min_donantes=5, min_empresas=3)
    assert pd.isna(out["y_ref"].iloc[0])
    assert out["n_donantes"].iloc[0] == 2


def test_se_abstiene_con_pocas_empresas_aunque_sobren_personas():
    # Diez personas de dos empresas no son una referencia de mercado.
    train = _marco([("E2", "c", 1.0)] * 5 + [("E3", "c", 1.0)] * 5)
    test = _marco([("E1", "c", 1.0)])
    out = predecir(train, test, "celda", min_donantes=5, min_empresas=3)
    assert pd.isna(out["y_ref"].iloc[0])
    assert out["n_empresas_donantes"].iloc[0] == 2


def test_se_abstiene_en_celda_no_vista_en_train():
    train = _marco([("E2", "c", 1.0)] * 8)
    test = _marco([("E1", "otra", 1.0)])
    out = predecir(train, test, "celda", min_donantes=5, min_empresas=3)
    assert pd.isna(out["y_ref"].iloc[0])
    assert out["n_donantes"].iloc[0] == 0


def test_una_celda_por_persona_no_predice_nada():
    # La trampa que la balanza debe castigar: partir de mas deja los cajones vacios.
    train = pd.DataFrame({"empresa_ruc": [f"E{i}" for i in range(20)],
                          "celda": [f"c{i}" for i in range(20)],
                          "y": np.linspace(0, 2, 20)})
    test = pd.DataFrame({"empresa_ruc": ["E0"], "celda": ["c0"], "y": [0.0]})
    out = predecir(train, test, "celda", min_donantes=5, min_empresas=3)
    assert pd.isna(out["y_ref"].iloc[0])


def test_media_en_espacio_log():
    train = _marco([(f"E{i}", "c", float(i)) for i in range(1, 7)])
    test = _marco([("E99", "c", 0.0)])
    out = predecir(train, test, "celda", min_donantes=5, min_empresas=3)
    assert abs(out["y_ref"].iloc[0] - 3.5) < 1e-9      # media de 1..6
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_referencia.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion.referencia'`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/referencia.py
"""Referencia salarial de una celda, con donantes de OTRAS empresas.

Por que la media y no la mediana: el objetivo ya esta en logaritmos, asi que la media
en ese espacio es la media geometrica en niveles — justo lo robusto a la asimetria
salarial que motivaba la mediana en el spec §5. Ademas permite quitar la propia empresa
con una resta O(1); con mediana habria que recalcular por cada par (celda, empresa), y
CARGO tiene 55.920 celdas. La variante con mediana se reporta como chequeo de robustez.
"""
import numpy as np
import pandas as pd


def predecir(train, test, col_celda, min_donantes=5, min_empresas=3):
    """Devuelve `y_ref`, `n_donantes` y `n_empresas_donantes` alineados con `test`.

    `y_ref` es NaN cuando el metodo se ABSTIENE: eso no cuenta como error, cuenta
    contra su cobertura (spec §6.2).
    """
    tr = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])

    por_celda = tr.groupby(col_celda)["y"].agg(suma="sum", n="size")
    por_celda["n_emp"] = tr.groupby(col_celda)["empresa_ruc"].nunique()

    ce = tr.groupby([col_celda, "empresa_ruc"])["y"].agg(suma="sum", n="size")

    celdas = test[col_celda]
    empresas = test["empresa_ruc"]

    suma_c = celdas.map(por_celda["suma"]).fillna(0.0).to_numpy(float)
    n_c = celdas.map(por_celda["n"]).fillna(0).to_numpy(float)
    nemp_c = celdas.map(por_celda["n_emp"]).fillna(0).to_numpy(float)

    idx = pd.MultiIndex.from_arrays([celdas, empresas])
    suma_ce = ce["suma"].reindex(idx).fillna(0.0).to_numpy(float)
    n_ce = ce["n"].reindex(idx).fillna(0).to_numpy(float)
    # si la propia empresa aporta al menos una persona a la celda, deja de contar
    nemp_ce = np.where(n_ce > 0, 1.0, 0.0)

    n_don = n_c - n_ce
    nemp_don = nemp_c - nemp_ce
    suma_don = suma_c - suma_ce

    apto = (n_don >= min_donantes) & (nemp_don >= min_empresas)
    with np.errstate(invalid="ignore", divide="ignore"):
        y_ref = np.where(apto, suma_don / np.where(n_don > 0, n_don, np.nan), np.nan)

    return pd.DataFrame({
        "y_ref": y_ref,
        "n_donantes": n_don.astype(int),
        "n_empresas_donantes": nemp_don.astype(int),
    }, index=test.index)
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_referencia.py -v`
Esperado: 6 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/referencia.py tests/test_evaluacion_referencia.py
git commit -m "feat(evaluacion): referencia por celda con donantes leave-company-out y abstencion"
```

---

### Tarea 5: Error, cobertura y curva error-cobertura

**Archivos:**
- Crear: `src/benchmarking/evaluacion/metricas.py`
- Test: `tests/test_evaluacion_metricas.py`

**Interfaces:**
- Consume: `predecir` de la Tarea 4
- Produce:
  - `error_y_cobertura(test, pred) -> dict` con claves `mae`, `cobertura`, `n_evaluadas`, `n_total`
  - `curva_error_cobertura(train, test, col_celda, umbrales=range(1, 31)) -> pd.DataFrame`
    con columnas `min_donantes`, `cobertura`, `mae`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_metricas.py
import numpy as np
import pandas as pd
from benchmarking.evaluacion.metricas import error_y_cobertura, curva_error_cobertura


def test_las_abstenciones_no_cuentan_como_error():
    # Si contaran, un metodo que se calla saldria peor que uno que responde mal,
    # y la comparacion premiaria opinar de todo.
    test = pd.DataFrame({"y": [1.0, 2.0, 3.0]})
    pred = pd.DataFrame({"y_ref": [1.1, np.nan, np.nan]})
    r = error_y_cobertura(test, pred)
    assert abs(r["mae"] - 0.1) < 1e-9
    assert abs(r["cobertura"] - 1 / 3) < 1e-9
    assert r["n_evaluadas"] == 1 and r["n_total"] == 3


def test_cobertura_cero_no_revienta():
    test = pd.DataFrame({"y": [1.0, 2.0]})
    pred = pd.DataFrame({"y_ref": [np.nan, np.nan]})
    r = error_y_cobertura(test, pred)
    assert r["cobertura"] == 0.0 and np.isnan(r["mae"])


def test_curva_la_cobertura_baja_al_exigir_mas_donantes():
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=40, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    c = curva_error_cobertura(tr, ts, "rol_verdadero", umbrales=[1, 5, 10, 20])
    assert list(c["min_donantes"]) == [1, 5, 10, 20]
    assert c["cobertura"].is_monotonic_decreasing
    assert (c["cobertura"] <= 1.0).all()
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_metricas.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion.metricas'`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/metricas.py
"""Error, cobertura y la curva que los relaciona."""
import numpy as np
import pandas as pd
from .referencia import predecir


def error_y_cobertura(test, pred):
    """MAE sobre las filas donde el metodo NO se abstuvo, mas su cobertura.

    Se reportan juntos siempre: comparar solo el error favorece al metodo que se
    abstiene mas, porque acierta mas donde solo opina teniendo datos (spec §6.2).
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    ref = pd.to_numeric(pred["y_ref"], errors="coerce").to_numpy(float)
    evaluable = ~np.isnan(ref) & ~np.isnan(y)
    n_total = len(y)
    n_eval = int(evaluable.sum())
    mae = float(np.abs(y[evaluable] - ref[evaluable]).mean()) if n_eval else float("nan")
    return {"mae": mae,
            "cobertura": n_eval / n_total if n_total else 0.0,
            "n_evaluadas": n_eval,
            "n_total": n_total}


def curva_error_cobertura(train, test, col_celda, umbrales=range(1, 31), min_empresas=3):
    """Barre el umbral de donantes: es la perilla de confianza, igual para los dos
    metodos, y permite compararlos A COBERTURA IGUALADA (spec §6.3)."""
    filas = []
    for m in umbrales:
        pred = predecir(train, test, col_celda, min_donantes=int(m), min_empresas=min_empresas)
        r = error_y_cobertura(test, pred)
        filas.append({"min_donantes": int(m), "cobertura": r["cobertura"], "mae": r["mae"]})
    return pd.DataFrame(filas)
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_metricas.py -v`
Esperado: 3 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/metricas.py tests/test_evaluacion_metricas.py
git commit -m "feat(evaluacion): error, cobertura y curva error-cobertura"
```

---

### Tarea 6: Bootstrap por empresa y ω² intra-empresa

**Archivos:**
- Modificar: `src/benchmarking/evaluacion/metricas.py`
- Test: `tests/test_evaluacion_metricas.py` (añadir)

**Interfaces:**
- Produce:
  - `ic_bootstrap_empresas(train, test, col_celda, n=1000, semilla=20260805, min_donantes=5) -> dict`
    con claves `mae`, `ic_bajo`, `ic_alto`
  - `omega2_intra_empresa(df, col_celda) -> float`

- [ ] **Paso 1: Escribir el test que falla**

```python
# anadir a tests/test_evaluacion_metricas.py
from benchmarking.evaluacion.metricas import ic_bootstrap_empresas, omega2_intra_empresa


def test_bootstrap_remuestrea_empresas_no_filas():
    # Remuestrear filas fingiria independencia que no existe: una empresa aporta
    # muchas personas y una persona recurre entre anios. El IC saldria irrealmente
    # estrecho y cualquier diferencia pareceria significativa.
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=40, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    r = ic_bootstrap_empresas(tr, ts, "rol_verdadero", n=80, semilla=1)
    assert r["ic_bajo"] < r["mae"] < r["ic_alto"]
    assert r["ic_alto"] - r["ic_bajo"] > 0


def test_bootstrap_determinista():
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=30, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    a = ic_bootstrap_empresas(tr, ts, "rol_verdadero", n=40, semilla=3)
    b = ic_bootstrap_empresas(tr, ts, "rol_verdadero", n=40, semilla=3)
    assert a == b


def test_omega2_premia_la_particion_verdadera():
    from sintetico import generar
    df = generar(n_empresas=30, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    rng = np.random.default_rng(0)
    df["azar"] = rng.integers(0, 3, len(df)).astype(str)
    assert omega2_intra_empresa(df, "rol_verdadero") > omega2_intra_empresa(df, "azar")


def test_omega2_no_premia_una_celda_por_persona():
    # omega2 penaliza los grados de libertad: una particion con una celda por
    # persona explica "todo" pero no debe salir premiada.
    from sintetico import generar
    df = generar(n_empresas=20, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    df["cada_uno"] = df["id_hash"]
    assert omega2_intra_empresa(df, "cada_uno") < omega2_intra_empresa(df, "rol_verdadero")
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_metricas.py -v`
Esperado: FAIL con `ImportError: cannot import name 'ic_bootstrap_empresas'`

- [ ] **Paso 3: Implementar**

```python
# anadir a src/benchmarking/evaluacion/metricas.py

def ic_bootstrap_empresas(train, test, col_celda, n=1000, semilla=20260805,
                          min_donantes=5, min_empresas=3, alfa=0.05):
    """IC del MAE remuestreando EMPRESAS del test con reemplazo.

    Nunca filas: la fila no es la unidad independiente (una empresa aporta muchas
    personas, una persona recurre entre anios). Remuestrear filas produciria un IC
    irrealmente estrecho y haria significativa cualquier diferencia.
    """
    pred = predecir(train, test, col_celda, min_donantes=min_donantes,
                    min_empresas=min_empresas)
    base = test.assign(_ref=pred["y_ref"].to_numpy())
    base = base[base["_ref"].notna() & base["y"].notna()]
    base = base.assign(_abs=(base["y"] - base["_ref"]).abs())

    por_empresa = base.groupby("empresa_ruc")["_abs"].agg(suma="sum", n="size")
    rucs = por_empresa.index.to_numpy()
    sumas = por_empresa["suma"].to_numpy(float)
    enes = por_empresa["n"].to_numpy(float)

    rng = np.random.default_rng(semilla)
    muestras = []
    for _ in range(int(n)):
        i = rng.integers(0, len(rucs), len(rucs))
        tot_n = enes[i].sum()
        if tot_n > 0:
            muestras.append(sumas[i].sum() / tot_n)
    muestras = np.array(muestras)
    return {
        "mae": float(sumas.sum() / enes.sum()) if enes.sum() else float("nan"),
        "ic_bajo": float(np.quantile(muestras, alfa / 2)) if len(muestras) else float("nan"),
        "ic_alto": float(np.quantile(muestras, 1 - alfa / 2)) if len(muestras) else float("nan"),
    }


def omega2_intra_empresa(df, col_celda):
    """omega2 de la celda sobre el residuo INTRA-empresa del objetivo.

    Se residualiza contra la empresa primero porque el efecto empleador explica ~39%
    de la varianza del log-salario en estos datos: sin quitarlo se mediria sobre todo
    a la empresa. omega2 (Hays, 1994) en vez de eta2 porque penaliza los grados de
    libertad, y las particiones aqui comparadas tienen cardinalidades muy distintas.
    """
    d = df[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"]).copy()
    if d.empty:
        return float("nan")
    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")
    k = d[col_celda].nunique()
    n = len(d)
    if k < 2 or n <= k:
        return float("nan")
    gran = d["r"].mean()
    g = d.groupby(col_celda)["r"].agg(["mean", "size"])
    ss_entre = float((g["size"] * (g["mean"] - gran) ** 2).sum())
    ss_total = float(((d["r"] - gran) ** 2).sum())
    ms_dentro = (ss_total - ss_entre) / (n - k)
    denom = ss_total + ms_dentro
    return float((ss_entre - (k - 1) * ms_dentro) / denom) if denom > 0 else float("nan")
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_metricas.py -v`
Esperado: 7 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/metricas.py tests/test_evaluacion_metricas.py
git commit -m "feat(evaluacion): bootstrap por empresa y omega2 intra-empresa"
```

---

### Tarea 7: Las particiones rivales

**Archivos:**
- Crear: `src/benchmarking/evaluacion/particiones.py`
- Modificar: `pyproject.toml` (añadir `scikit-learn`)
- Test: `tests/test_evaluacion_particiones.py`

**Interfaces:**
- Produce, todas devolviendo una `pd.Series` de etiquetas de celda alineada al índice del DataFrame:
  - `cargo_crudo(df) -> pd.Series`
  - `aleatoria(df, k, semilla=20260805) -> pd.Series`
  - `solo_texto(df, k, semilla=20260805) -> pd.Series`
  - `techo_supervisado(df, k, semilla=20260805) -> pd.Series`

- [ ] **Paso 1: Añadir la dependencia**

Modificar `pyproject.toml`, lista `dependencies`, añadiendo al final:

```toml
  "scikit-learn>=1.4", "matplotlib>=3.8",
```

Ejecutar: `.venv\Scripts\python.exe -m pip install -e .`

- [ ] **Paso 2: Escribir el test que falla**

```python
# tests/test_evaluacion_particiones.py
import numpy as np
import pandas as pd
from sintetico import generar
from benchmarking.evaluacion.particiones import (
    cargo_crudo, aleatoria, solo_texto, techo_supervisado)


def test_cargo_crudo_no_poda_nada():
    # Podar CARGO a sus top-k dejaria al 74% de la gente en una celda "otros":
    # ganarle a ese rival no demostraria nada (D-005). Compite entero.
    df = pd.DataFrame({"cargo_norm": ["VENDEDOR"] * 3 + [f"RARO{i}" for i in range(50)]})
    c = cargo_crudo(df)
    assert c.nunique() == 51
    assert (c == "VENDEDOR").sum() == 3


def test_aleatoria_respeta_k_y_es_determinista():
    df = generar(n_empresas=20, personas_por_empresa=10)
    a = aleatoria(df, k=7, semilla=5)
    assert a.nunique() == 7
    pd.testing.assert_series_equal(a, aleatoria(df, k=7, semilla=5))


def test_solo_texto_agrupa_titulos_parecidos():
    # El nulo de cardinalidad igualada bien construido: agrupa por similitud del
    # texto, no por frecuencia, asi que nadie queda tirado en un cajon "otros".
    df = pd.DataFrame({"cargo_norm": ["VENDEDOR", "VENDEDORA", "VENDEDOR 1",
                                      "CONTADOR", "CONTADORA", "CONTADOR GENERAL"]})
    c = solo_texto(df, k=2, semilla=1)
    assert c.nunique() == 2
    assert c.iloc[0] == c.iloc[1] == c.iloc[2]
    assert c.iloc[3] == c.iloc[4] == c.iloc[5]
    assert c.iloc[0] != c.iloc[3]


def test_techo_supervisado_agrupa_por_salario():
    # Hace trampa a proposito: es la cota superior alcanzable, y la alarma de que
    # el arquetipo pueda estar derivando hacia bandas salariales.
    df = pd.DataFrame({"y": [0.0, 0.05, 0.1, 5.0, 5.05, 5.1]})
    c = techo_supervisado(df, k=2, semilla=1)
    assert c.iloc[0] == c.iloc[1] == c.iloc[2]
    assert c.iloc[3] == c.iloc[4] == c.iloc[5]
    assert c.iloc[0] != c.iloc[3]


def test_todas_devuelven_serie_alineada():
    df = generar(n_empresas=10, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    for s in (cargo_crudo(df), aleatoria(df, 3), solo_texto(df, 3), techo_supervisado(df, 3)):
        assert isinstance(s, pd.Series) and s.index.equals(df.index) and s.notna().all()
```

- [ ] **Paso 3: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_particiones.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion.particiones'`

- [ ] **Paso 4: Implementar**

```python
# src/benchmarking/evaluacion/particiones.py
"""Las particiones rivales de la escalera de referencias (spec §4).

Cada una contesta una pregunta distinta:
  aleatoria         -> ¿supero al azar?
  cargo_crudo       -> ¿supero lo que se usa hoy, entero y sin podar?
  solo_texto        -> ¿la composicion aporta algo mas alla del nombre del puesto?
  techo_supervisado -> ¿cuanto es lo maximo posible con estos datos?
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

SEMILLA = 20260805


def cargo_crudo(df):
    """CARGO tal cual, con todas sus etiquetas. No se poda (D-005)."""
    return df["cargo_norm"].astype(str).rename("celda")


def aleatoria(df, k, semilla=SEMILLA):
    """Piso de la escalera: k celdas sin ninguna informacion."""
    rng = np.random.default_rng(semilla)
    return pd.Series(rng.integers(0, int(k), len(df)).astype(str),
                     index=df.index, name="celda")


def solo_texto(df, k, semilla=SEMILLA):
    """Agrupa por similitud del texto del cargo, en k celdas.

    TF-IDF de n-gramas de caracteres (3-5) y k-means: capta variantes ortograficas
    y morfologicas ("VENDEDOR"/"VENDEDORA"/"VENDEDOR 1") sin depender de un modelo
    de embeddings externo, lo que mantiene la corrida determinista y reproducible.
    """
    texto = df["cargo_norm"].astype(str).fillna("")
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    X = vec.fit_transform(texto)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10)
    return pd.Series(km.fit_predict(X).astype(str), index=df.index, name="celda")


def techo_supervisado(df, k, semilla=SEMILLA):
    """Agrupa DIRECTAMENTE por el salario: circular por diseno.

    No es un metodo candidato. Sirve para fijar la escala del resultado propio (un
    MAE de 0,18 no se interpreta sin saber cuanto logra la trampa) y como alarma:
    si el arquetipo se le acerca demasiado, sospechar deriva a bandas salariales.
    """
    y = pd.to_numeric(df["y"], errors="coerce").fillna(0.0).to_numpy(float).reshape(-1, 1)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10)
    return pd.Series(km.fit_predict(y).astype(str), index=df.index, name="celda")
```

- [ ] **Paso 5: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_particiones.py -v`
Esperado: 5 passed

- [ ] **Paso 6: Commit**

```bash
git add src/benchmarking/evaluacion/particiones.py tests/test_evaluacion_particiones.py pyproject.toml
git commit -m "feat(evaluacion): las cuatro particiones de la escalera de referencias"
```

---

### Tarea 8: El banco se valida a sí mismo

Un instrumento que nadie verificó no sirve para verificar nada. Antes de usarlo con datos reales, se
le exige ordenar correctamente particiones cuya calidad conocemos.

**Archivos:**
- Test: `tests/test_evaluacion_banco.py`

**Interfaces:**
- Consume: todo lo anterior. No produce código nuevo: es la prueba de aceptación del banco.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_banco.py
"""Prueba de aceptacion: el banco debe ordenar bien particiones de calidad conocida.

Si falla, esta mal el BANCO, no el modelo. Es infinitamente mas barato descubrirlo
aqui que tras nueve semanas midiendo con una regla torcida.
"""
import numpy as np
import pandas as pd
import pytest
from sintetico import generar
from benchmarking.evaluacion.splits import empresas_test, partir
from benchmarking.evaluacion.referencia import predecir
from benchmarking.evaluacion.metricas import error_y_cobertura
from benchmarking.evaluacion.particiones import aleatoria


@pytest.fixture
def marco():
    df = generar(n_empresas=60, personas_por_empresa=20, n_roles=3)
    df["y"] = np.log(df["sueldo"] / 470)
    return df


def _mae(df, col):
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    return error_y_cobertura(ts, predecir(tr, ts, col, min_donantes=5, min_empresas=3))


def test_la_particion_verdadera_gana_a_la_aleatoria(marco):
    marco = marco.copy()
    marco["azar"] = aleatoria(marco, k=3)
    buena = _mae(marco, "rol_verdadero")
    mala = _mae(marco, "azar")
    assert buena["mae"] < mala["mae"], "el banco no reconoce la particion verdadera"


def test_la_particion_deliberadamente_mala_pierde(marco):
    # Agrupar por la inicial del hash: tantas celdas como la verdadera, cero informacion.
    marco = marco.copy()
    marco["tonta"] = marco["id_hash"].str[-1]
    assert _mae(marco, "rol_verdadero")["mae"] < _mae(marco, "tonta")["mae"]


def test_una_celda_por_persona_no_gana(marco):
    # La trampa que hundio a la Balanza 1: partir de mas debe COSTAR, no premiar.
    marco = marco.copy()
    marco["cada_uno"] = marco["id_hash"]
    r = _mae(marco, "cada_uno")
    assert r["cobertura"] == 0.0, "con una celda por persona no debe poder predecir nada"


def test_la_abstencion_cuenta_en_cobertura_y_no_en_error(marco):
    r = _mae(marco, "rol_verdadero")
    assert 0.0 < r["cobertura"] <= 1.0
    assert r["n_evaluadas"] <= r["n_total"]
    assert not np.isnan(r["mae"])
```

- [ ] **Paso 2: Ejecutar los tests**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_banco.py -v`
Esperado: 4 passed. **Si alguno falla, el defecto está en el banco (Tareas 3-7), no en el test:
arreglar el módulo correspondiente antes de seguir.**

- [ ] **Paso 3: Commit**

```bash
git add tests/test_evaluacion_banco.py
git commit -m "test(evaluacion): prueba de aceptacion del banco con data de respuesta conocida"
```

---

### Tarea 9: Estabilidad — test-retest y ARI

**Archivos:**
- Crear: `src/benchmarking/evaluacion/estabilidad.py`
- Test: `tests/test_evaluacion_estabilidad.py`

**Interfaces:**
- Produce:
  - `test_retest(df, col_celda, col_persona="id_hash", col_anio="anio_valoracion") -> dict`
    con claves `n_personas_repetidas`, `acuerdo`
  - `ari_submuestras(df, asignador, n=20, frac=0.5, semilla=20260805) -> dict`
    con claves `ari_medio`, `ari_min`, donde `asignador(sub_df) -> pd.Series`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_estabilidad.py
import numpy as np
import pandas as pd
from benchmarking.evaluacion.estabilidad import test_retest, ari_submuestras


def test_retest_perfecto_da_uno():
    # 478.522 personas aparecen en 2024 y 2025: son dos mediciones REALES de la
    # misma persona, evidencia mas fuerte que un ARI de bootstrap simulado.
    df = pd.DataFrame({"id_hash": ["a", "a", "b", "b"],
                       "anio_valoracion": [2024, 2025, 2024, 2025],
                       "celda": ["x", "x", "y", "y"]})
    r = test_retest(df, "celda")
    assert r["n_personas_repetidas"] == 2 and r["acuerdo"] == 1.0


def test_retest_detecta_desacuerdo():
    df = pd.DataFrame({"id_hash": ["a", "a", "b", "b"],
                       "anio_valoracion": [2024, 2025, 2024, 2025],
                       "celda": ["x", "z", "y", "y"]})
    assert test_retest(df, "celda")["acuerdo"] == 0.5


def test_retest_ignora_a_quien_solo_aparece_una_vez():
    df = pd.DataFrame({"id_hash": ["a", "a", "c"],
                       "anio_valoracion": [2024, 2025, 2025],
                       "celda": ["x", "x", "q"]})
    assert test_retest(df, "celda")["n_personas_repetidas"] == 1


def test_ari_alto_para_un_asignador_estable():
    from sintetico import generar
    df = generar(n_empresas=40, personas_por_empresa=10)
    estable = lambda d: d["rol_verdadero"]
    r = ari_submuestras(df, estable, n=5, frac=0.5)
    assert r["ari_medio"] > 0.95


def test_ari_bajo_para_un_asignador_aleatorio():
    from sintetico import generar
    df = generar(n_empresas=40, personas_por_empresa=10)
    contador = {"i": 0}

    def inestable(d):
        contador["i"] += 1
        rng = np.random.default_rng(contador["i"])
        return pd.Series(rng.integers(0, 3, len(d)).astype(str), index=d.index)

    assert ari_submuestras(df, inestable, n=5, frac=0.5)["ari_medio"] < 0.2
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_estabilidad.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion.estabilidad'`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/estabilidad.py
"""Estabilidad de una asignacion: test-retest real y ARI entre submuestras."""
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

SEMILLA = 20260805


def test_retest(df, col_celda, col_persona="id_hash", col_anio="anio_valoracion"):
    """Acuerdo de la celda asignada a la MISMA persona en dos anios distintos.

    Es re-medicion real, no simulada: mas convincente que un bootstrap. Solo entran
    las personas presentes en los dos anios.
    """
    d = df[[col_persona, col_anio, col_celda]].dropna()
    pares = (d.sort_values(col_anio)
               .groupby(col_persona)[col_celda]
               .agg(list))
    pares = pares[pares.map(len) >= 2]
    if pares.empty:
        return {"n_personas_repetidas": 0, "acuerdo": float("nan")}
    coincide = pares.map(lambda v: v[0] == v[-1])
    return {"n_personas_repetidas": int(len(pares)),
            "acuerdo": float(coincide.mean())}


def ari_submuestras(df, asignador, n=20, frac=0.5, semilla=SEMILLA,
                    col_empresa="empresa_ruc"):
    """Reproducibilidad de la particion entre submuestras DE EMPRESAS.

    Es la regla con la que se elige la granularidad y la familia (D-005): nunca por
    acierto salarial. Se comparan solo las filas que caen en las dos submuestras.
    """
    rng = np.random.default_rng(semilla)
    empresas = np.array(sorted(df[col_empresa].unique()))
    aris = []
    for _ in range(int(n)):
        a = set(rng.choice(empresas, max(1, int(len(empresas) * frac)), replace=False))
        b = set(rng.choice(empresas, max(1, int(len(empresas) * frac)), replace=False))
        da = df[df[col_empresa].isin(a)]
        db = df[df[col_empresa].isin(b)]
        comun = da.index.intersection(db.index)
        if len(comun) < 2:
            continue
        ea = asignador(da).reindex(comun).astype(str)
        eb = asignador(db).reindex(comun).astype(str)
        aris.append(adjusted_rand_score(ea, eb))
    if not aris:
        return {"ari_medio": float("nan"), "ari_min": float("nan")}
    return {"ari_medio": float(np.mean(aris)), "ari_min": float(np.min(aris))}
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_estabilidad.py -v`
Esperado: 5 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/estabilidad.py tests/test_evaluacion_estabilidad.py
git commit -m "feat(evaluacion): test-retest entre anios y ARI entre submuestras de empresas"
```

---

### Tarea 10: Informe — tabla comparativa y curva

**Archivos:**
- Crear: `src/benchmarking/evaluacion/informe.py`
- Test: `tests/test_evaluacion_informe.py`

**Interfaces:**
- Produce:
  - `comparar(train, test, particiones, min_donantes=5, n_bootstrap=1000) -> pd.DataFrame`
    donde `particiones` es `dict[str, pd.Series]`; columnas de salida `metodo, n_celdas,
    cobertura, mae, ic_bajo, ic_alto, omega2`
  - `tabla_texto(comparacion) -> str`
  - `guardar_curvas(curvas, ruta_png) -> None` donde `curvas` es `dict[str, pd.DataFrame]`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_informe.py
import numpy as np
import pandas as pd
from sintetico import generar
from benchmarking.evaluacion.splits import empresas_test, partir
from benchmarking.evaluacion.particiones import aleatoria
from benchmarking.evaluacion.informe import comparar, tabla_texto, guardar_curvas
from benchmarking.evaluacion.metricas import curva_error_cobertura


def _datos():
    df = generar(n_empresas=50, personas_por_empresa=14)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def test_comparar_devuelve_una_fila_por_metodo():
    tr, ts = _datos()
    parts = {"verdadera": ts["rol_verdadero"], "azar": aleatoria(ts, k=3)}
    parts_tr = {"verdadera": tr["rol_verdadero"], "azar": aleatoria(tr, k=3)}
    c = comparar(tr, ts, parts, particiones_train=parts_tr, n_bootstrap=30)
    assert list(c["metodo"]) == ["verdadera", "azar"]
    assert {"cobertura", "mae", "ic_bajo", "ic_alto", "omega2", "n_celdas"} <= set(c.columns)
    assert c.loc[c.metodo == "verdadera", "mae"].iloc[0] < c.loc[c.metodo == "azar", "mae"].iloc[0]


def test_tabla_texto_es_legible():
    tr, ts = _datos()
    parts = {"verdadera": ts["rol_verdadero"]}
    parts_tr = {"verdadera": tr["rol_verdadero"]}
    t = tabla_texto(comparar(tr, ts, parts, particiones_train=parts_tr, n_bootstrap=10))
    assert "verdadera" in t and "cobertura" in t.lower()


def test_guardar_curvas_escribe_el_png(tmp_path):
    tr, ts = _datos()
    curvas = {"verdadera": curva_error_cobertura(
        tr.assign(celda=tr["rol_verdadero"]), ts.assign(celda=ts["rol_verdadero"]),
        "celda", umbrales=[1, 5, 10])}
    ruta = tmp_path / "curva.png"
    guardar_curvas(curvas, ruta)
    assert ruta.exists() and ruta.stat().st_size > 0
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_informe.py -v`
Esperado: FAIL con `ModuleNotFoundError: No module named 'benchmarking.evaluacion.informe'`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/informe.py
"""Tabla comparativa y grafico de la curva error-cobertura."""
import matplotlib
matplotlib.use("Agg")                       # sin ventana: corre en job y en CI
import matplotlib.pyplot as plt
import pandas as pd
from .metricas import error_y_cobertura, ic_bootstrap_empresas, omega2_intra_empresa
from .referencia import predecir


def comparar(train, test, particiones, particiones_train, min_donantes=5,
             min_empresas=3, n_bootstrap=1000):
    """Una fila por metodo, con error, cobertura, IC por empresa y omega2.

    `particiones` y `particiones_train` son dict[nombre -> Series de celdas] alineadas
    a `test` y `train` respectivamente.
    """
    filas = []
    for nombre, celdas_ts in particiones.items():
        ts = test.assign(_celda=celdas_ts.astype(str).to_numpy())
        tr = train.assign(_celda=particiones_train[nombre].astype(str).to_numpy())
        pred = predecir(tr, ts, "_celda", min_donantes=min_donantes,
                        min_empresas=min_empresas)
        base = error_y_cobertura(ts, pred)
        ic = ic_bootstrap_empresas(tr, ts, "_celda", n=n_bootstrap,
                                   min_donantes=min_donantes, min_empresas=min_empresas)
        filas.append({
            "metodo": nombre,
            "n_celdas": int(tr["_celda"].nunique()),
            "cobertura": base["cobertura"],
            "mae": base["mae"],
            "ic_bajo": ic["ic_bajo"],
            "ic_alto": ic["ic_alto"],
            "omega2": omega2_intra_empresa(ts, "_celda"),
        })
    return pd.DataFrame(filas)


def tabla_texto(comparacion):
    c = comparacion.copy()
    c["cobertura"] = (100 * c["cobertura"]).round(1).astype(str) + "%"
    for col in ("mae", "ic_bajo", "ic_alto", "omega2"):
        c[col] = c[col].round(4)
    return c.to_string(index=False)


def guardar_curvas(curvas, ruta_png):
    """La curva error-cobertura: comparar A COBERTURA IGUALADA es lo unico honesto
    cuando dos metodos se abstienen de forma distinta (spec §6.3)."""
    fig, ax = plt.subplots(figsize=(7, 5))
    for nombre, c in curvas.items():
        ax.plot(c["cobertura"], c["mae"], marker="o", label=nombre)
    ax.set_xlabel("cobertura (fracción de personas con referencia)")
    ax.set_ylabel("error (MAE en log-SBU)")
    ax.set_title("Error frente a cobertura")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_informe.py -v`
Esperado: 3 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/informe.py tests/test_evaluacion_informe.py
git commit -m "feat(evaluacion): informe con tabla comparativa y curva error-cobertura"
```

---

### Tarea 11: Subcomando `benchmarking evaluar`

**Archivos:**
- Modificar: `src/benchmarking/cli.py`
- Test: `tests/test_cli.py` (añadir)

**Interfaces:**
- Consume: todo lo anterior
- Produce: `benchmarking evaluar --particion <parquet> [--salida <dir>] [--anios 2024,2025]`
  El parquet debe tener columnas `id_hash`, `numero_proceso`, `celda`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# anadir a tests/test_cli.py
def test_evaluar_exige_columnas_de_la_particion(tmp_path, monkeypatch):
    # Un parquet sin `celda` debe fallar con un mensaje claro, no con un KeyError
    # cincuenta lineas mas abajo.
    import pandas as pd
    import pytest
    from benchmarking.cli import _validar_particion
    mala = pd.DataFrame({"id_hash": ["a"], "numero_proceso": ["P1"]})
    with pytest.raises(SystemExit, match="celda"):
        _validar_particion(mala)
    buena = pd.DataFrame({"id_hash": ["a"], "numero_proceso": ["P1"], "celda": ["c"]})
    _validar_particion(buena)     # no lanza
```

- [ ] **Paso 2: Ejecutar el test y verificar que falla**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Esperado: FAIL con `ImportError: cannot import name '_validar_particion'`

- [ ] **Paso 3: Implementar**

En `src/benchmarking/cli.py`, añadir tras los imports existentes:

```python
_COLS_PARTICION = ("id_hash", "numero_proceso", "celda")


def _validar_particion(df):
    faltan = [c for c in _COLS_PARTICION if c not in df.columns]
    if faltan:
        raise SystemExit(
            f"la particion debe tener las columnas {list(_COLS_PARTICION)}; faltan: {faltan}")
```

En `main()`, tras el parser `cu`, añadir:

```python
    ev = sub.add_parser("evaluar")
    ev.add_argument("--particion", required=True, help="parquet con id_hash, numero_proceso, celda")
    ev.add_argument("--salida", default="research/experimentos/e0_banco",
                    help="carpeta donde dejar tabla y grafico")
    ev.add_argument("--anios", default="2024,2025")
    ev.add_argument("--bootstrap", type=int, default=1000)
```

Y en el cuerpo, tras la rama `construir-universo`:

```python
    elif args.cmd == "evaluar":
        import pathlib
        import pandas as pd
        from .evaluacion import datos, splits, particiones, informe, metricas

        salida = pathlib.Path(args.salida)
        salida.mkdir(parents=True, exist_ok=True)
        anios = tuple(int(a) for a in args.anios.split(","))

        part = pd.read_parquet(args.particion)
        _validar_particion(part)

        marco = datos.agregar_objetivo(
            datos.cargar_marco(client, s.bq_project, s.bq_dataset, anios=anios), s)
        marco = datos.marco_evaluable(marco)
        marco = marco.merge(part[["id_hash", "numero_proceso", "celda"]],
                            on=["id_hash", "numero_proceso"], how="inner")
        print(f"marco evaluable: {len(marco)} filas, {marco.empresa_ruc.nunique()} empresas")

        te = splits.empresas_test(marco)
        h = splits.guardar(te, salida / "empresas_test.json")
        print(f"test bloqueado: {len(te)} empresas  sha256={h[:16]}...")
        tr, ts = splits.partir(marco, te)

        k = int(marco["celda"].nunique())
        parts_ts = {
            "arquetipo": ts["celda"].astype(str),
            "CARGO crudo": particiones.cargo_crudo(ts),
            "aleatoria (k igualado)": particiones.aleatoria(ts, k),
            "solo-texto (k igualado)": particiones.solo_texto(ts, k),
            "techo supervisado": particiones.techo_supervisado(ts, k),
        }
        parts_tr = {
            "arquetipo": tr["celda"].astype(str),
            "CARGO crudo": particiones.cargo_crudo(tr),
            "aleatoria (k igualado)": particiones.aleatoria(tr, k),
            "solo-texto (k igualado)": particiones.solo_texto(tr, k),
            "techo supervisado": particiones.techo_supervisado(tr, k),
        }

        comp = informe.comparar(tr, ts, parts_ts, particiones_train=parts_tr,
                                n_bootstrap=args.bootstrap)
        comp.to_csv(salida / "comparacion.csv", index=False)
        print(informe.tabla_texto(comp))

        curvas = {}
        for nombre in parts_ts:
            curvas[nombre] = metricas.curva_error_cobertura(
                tr.assign(_c=parts_tr[nombre].to_numpy()),
                ts.assign(_c=parts_ts[nombre].to_numpy()), "_c")
        informe.guardar_curvas(curvas, salida / "curva_error_cobertura.png")
        print(f"resultados en {salida}")
```

- [ ] **Paso 4: Ejecutar los tests y verificar que pasan**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Esperado: todos pasan

- [ ] **Paso 5: Verificar que el CLI sigue arrancando**

Ejecutar: `.venv\Scripts\python.exe -m benchmarking.cli --help`
Esperado: aparecen `construir-base`, `construir-universo` y `evaluar`

- [ ] **Paso 6: Commit**

```bash
git add src/benchmarking/cli.py tests/test_cli.py
git commit -m "feat(cli): subcomando evaluar que corre el banco completo"
```

---

### Tarea 12: Pre-registro

Se congela **antes** de tocar el conjunto de test. Es lo que impide acomodar la vara al resultado.

**Archivos:**
- Crear: `docs/preregistro.md`

- [ ] **Paso 1: Escribir el documento**

```markdown
# Pre-registro — Sub-proyecto 1 (banco de validación)

Congelado el <FECHA> antes de ejecutar nada contra el conjunto de test.
Commit de congelación: <HASH>.
Hash sha256 del listado de empresas apartadas: <HASH_SPLIT>.

## Métrica primaria

Error absoluto medio (MAE) de `y = log(sueldo / SBU(año))`, fuera de muestra, prediciendo
cada persona de test con la **media de `y` de su celda entre donantes de OTRAS empresas**
(leave-company-out).

Desviación explícita del spec §5, que decía mediana: el objetivo ya está en logaritmos, así
que la media en ese espacio es la media geométrica en niveles —lo robusto a la asimetría que
motivaba la mediana— y permite quitar la propia empresa en O(1). Con las 55.920 celdas de
`CARGO`, la mediana con leave-company-out es inviable. Se reporta la variante con mediana
como chequeo de robustez sobre submuestra.

## Métrica co-primaria

**Cobertura**: fracción de personas de test para las que el método emite referencia. Se
reporta siempre junto al error, y la comparación entre métodos se lee **a cobertura
igualada** sobre la curva error-cobertura.

## Regla de abstención

Un método se abstiene si la celda tiene menos de **5 donantes** de al menos **3 empresas**
distintas. El umbral de 5 coincide con la práctica del programa OEWS del BLS y con la
supresión de celda mínima del spec §12. La curva completa se reporta barriendo el umbral de
1 a 30, así que ninguna conclusión depende de ese valor.

## Criterio de éxito (D-004)

**Éxito = A o B.**

- **A**: a cobertura igualada, el arquetipo tiene MAE menor que `CARGO`, con el intervalo de
  confianza de la diferencia sin cruzar el cero.
- **B**: MAE equivalente, pero cobertura sustancialmente mayor.
- **C** (complementariedad: `CARGO` mejor donde su etiqueta es buena, arquetipo mejor donde
  está rota) **se reporta como hallazgo, no como victoria**.
- **D** (no gana en ningún lado) se reporta como resultado negativo.

## Regla de selección de modelo (D-005)

La granularidad (k en k-means/GMM, altura de corte en jerárquico, tamaño mínimo de grupo en
HDBSCAN) y la familia se eligen **por estabilidad** — ARI entre submuestras de empresas —,
**nunca por el acierto salarial**. El techo supervisado se reporta siempre como escala y como
alarma; el test de validez externa (predecir ISCO-08) comprueba que las celdas son
ocupaciones y no bandas de sueldo.

## Incertidumbre

Todos los intervalos por bootstrap de **empresas** con reemplazo, 1.000 réplicas. Nunca por
filas: la fila no es la unidad independiente.

## Conjunto de test

20% de las empresas, estratificado por segmento SCVS y sección CIIU, semilla 20260805.
Bloqueado: no se mira hasta la validación final. Su identidad queda fijada por el hash de
arriba.
```

- [ ] **Paso 2: Commit**

```bash
git add docs/preregistro.md
git commit -m "docs: pre-registro del banco de validacion, congelado antes del test"
```

---

### Tarea 13: Los dos baselines (experimento E0)

Estrena el banco y resuelve en la semana 4 la objeción sobre si la composición aporta
(enmienda de D-003).

**Archivos:**
- Crear: `research/experimentos/e0_banco/construir_baselines.py`
- Crear: `research/experimentos/e0_banco/README.md`

**Interfaces:**
- Consume: `benchmarking.evaluacion.*`
- Produce: dos parquets de partición consumibles por `benchmarking evaluar`

- [ ] **Paso 1: Escribir el script**

```python
# research/experimentos/e0_banco/construir_baselines.py
"""E0 — dos baselines de k-means, para estrenar el banco y medir si la composicion aporta.

Baseline A: con composicion, sobre 2024-2025.
Baseline B: sin composicion, sobre todos los anios.

Ambos se evaluan sobre el MISMO held-out de empresas. Si B iguala o supera a A, la
composicion no aporta y media arquitectura del spec de clustering se puede retirar CON
EVIDENCIA. Es el experimento E1/E2 del spec §10, adelantado de la semana ~12 a la ~4.

El salario NO entra en ninguno de los dos vectores (anti-circularidad, D-005).
"""
import argparse
import pathlib
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import TruncatedSVD
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos

SEMILLA = 20260805


def baseline_a(df, k):
    """Composicion (4 proporciones) + antiguedad. Solo filas con composicion real."""
    d = df[df["tiene_composicion"]].copy()
    X = d[["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros", "antiguedad_total"]]
    X = X.fillna(X.median(numeric_only=True))
    modelo = make_pipeline(StandardScaler(),
                           MiniBatchKMeans(n_clusters=k, random_state=SEMILLA, n_init=10))
    d["celda"] = modelo.fit_predict(X).astype(str)
    return d[["id_hash", "numero_proceso", "celda"]]


def baseline_b(df, k):
    """Sin composicion: texto del cargo + centro de costo + antiguedad."""
    d = df.copy()
    texto = (d["cargo_norm"].astype(str) + " " + d["centro_de_costo"].astype(str)).fillna("")
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=20000)
    T = TruncatedSVD(n_components=40, random_state=SEMILLA).fit_transform(vec.fit_transform(texto))
    ant = d[["antiguedad_total"]].fillna(d["antiguedad_total"].median()).to_numpy(float)
    X = np.hstack([StandardScaler().fit_transform(T), StandardScaler().fit_transform(ant)])
    d["celda"] = MiniBatchKMeans(n_clusters=k, random_state=SEMILLA,
                                 n_init=10).fit_predict(X).astype(str)
    return d[["id_hash", "numero_proceso", "celda"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=50)
    ap.add_argument("--salida", default="research/experimentos/e0_banco")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    salida = pathlib.Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    ab = datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025))
    todos = datos.cargar_marco(cl, s.bq_project, s.bq_dataset,
                               anios=(2019, 2020, 2021, 2022, 2023, 2024, 2025))

    pa = baseline_a(ab, args.k)
    pb = baseline_b(todos, args.k)
    pa.to_parquet(salida / "baseline_a.parquet", index=False)
    pb.to_parquet(salida / "baseline_b.parquet", index=False)
    print(f"A: {len(pa)} filas, {pa.celda.nunique()} celdas")
    print(f"B: {len(pb)} filas, {pb.celda.nunique()} celdas")


if __name__ == "__main__":
    main()
```

- [ ] **Paso 2: Escribir el README del experimento**

```markdown
# E0 — Estreno del banco con dos baselines

## Qué contesta

1. ¿El banco funciona sobre datos reales? (ya validado con data sintética en
   `tests/test_evaluacion_banco.py`)
2. **¿La composición aporta?** — enmienda de D-003. Si B iguala a A, media arquitectura del
   spec de clustering (ILR, gate, residualización, IPW) se puede retirar con evidencia.

## Cómo se corre

```bash
python research/experimentos/e0_banco/construir_baselines.py --k 50
benchmarking evaluar --particion research/experimentos/e0_banco/baseline_a.parquet \
                     --salida research/experimentos/e0_banco/a
benchmarking evaluar --particion research/experimentos/e0_banco/baseline_b.parquet \
                     --salida research/experimentos/e0_banco/b
```

## Cómo se lee

La comparación honesta es **a cobertura igualada**, sobre la curva. Ninguno de los dos
baselines pretende ser el modelo bueno: son la vara contra la que se medirá el sub-proyecto 2.

Recordatorio del pre-registro: **k no se elige por el resultado salarial.** Aquí está fijo en
50 por convención; la elección real de granularidad se hará por estabilidad en el
sub-proyecto 4.
```

- [ ] **Paso 3: Commit**

```bash
git add research/experimentos/e0_banco
git commit -m "feat(research): E0 — dos baselines para estrenar el banco y medir la composicion"
```

---

### Tarea 14: Verificación final

- [ ] **Paso 1: Toda la suite en verde**

Ejecutar: `.venv\Scripts\python.exe -m pytest -q`
Esperado: todos los tests pasan (los 54 previos más los ~30 nuevos)

- [ ] **Paso 2: La prueba de aceptación del banco, explícita**

Ejecutar: `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_banco.py -v`
Esperado: 4 passed. Es la que autoriza a fiarse de las mediciones.

- [ ] **Paso 3: Confirmar que no entró data real al repositorio**

Ejecutar: `git log --stat -20 | grep -iE "\.parquet|\.csv|\.xlsx" || echo "sin data real"`
Esperado: solo rutas bajo `research/experimentos/` ignoradas, o "sin data real"

- [ ] **Paso 4: Commit final**

```bash
git commit --allow-empty -m "chore: sub-proyecto 1 completo — banco de validacion operativo"
```

---

## Qué queda fuera, y a dónde va

| Fuera de este plan | Sub-proyecto |
|---|---|
| Residualización contra empleador×sector, ILR, gate de masa fija, pesos de bloque | 2 |
| Modelo de nivel (banda de seniority) | 3 |
| GMM, HDBSCAN, jerárquico y la selección por estabilidad | 4 |
| Etiquetado LLM y mapeo ISCO-08 | 5 |
| IPW para el sesgo de selección del ajuste | 2 |
| Referencia ISCO-08 para el test de validez externa | 5 (empezar antes: es trabajo manual) |
