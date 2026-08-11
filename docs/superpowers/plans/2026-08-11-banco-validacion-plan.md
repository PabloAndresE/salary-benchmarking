# Banco de validación y baseline — Plan de implementación (v2)

> **Para trabajadores agénticos:** SUB-SKILL REQUERIDO: usar `superpowers:subagent-driven-development`
> (recomendado) o `superpowers:executing-plans`, tarea por tarea. Los pasos usan casillas (`- [ ]`).
>
> Sustituye a `2026-08-07-banco-validacion-plan.md`, que quedó obsoleto tras la revisión de las 16
> decisiones (D-006) y la revisión de jueces (D-009). Contexto obligatorio antes de ejecutar:
> [`../../registro_decisiones.md`](../../registro_decisiones.md) y
> [`../../revision_jueces.md`](../../revision_jueces.md).

**Objetivo:** construir el instrumento que mide si una forma de agrupar personas predice el salario
mejor que la etiqueta `CARGO`, y estrenarlo con dos baselines.

**Arquitectura:** un paquete `src/benchmarking/evaluacion/` de módulos con responsabilidad única,
encadenados por DataFrames. Flujo: cargar marco → partir empresas → construir particiones rivales →
estimar la referencia salarial de cada celda **ponderando por empresa** → puntuar error y cobertura
→ informar. Un subcomando `benchmarking evaluar` lo orquesta. Todo se prueba con data sintética de
estructura conocida.

**Stack:** Python 3.11, pandas, numpy, scikit-learn, matplotlib, Vertex AI (embeddings), pytest.

## Restricciones globales

- **Frontera de privacidad:** nada aguas abajo de `anonimizacion` ve identificadores. El banco
  trabaja con `id_hash`. Data real nunca al repositorio.
- **Unidad estadística = empresa.** Splits, remuestreos y **la referencia salarial** son por
  `empresa_ruc`, nunca por fila.
- **Anti-circularidad:** el salario no entra jamás como característica de agrupamiento. Granularidad,
  familia **y pesos** se eligen sin la métrica salarial (D-005 Enmienda 1, los tres elementos).
- **Determinismo:** semilla del proyecto `20260805`, fija y explícita en cada punto aleatorio.
- Tabla origen: `act-cicd-stage-prueba.benchmarking_tesis.nomina_features`.

## Tres trampas heredadas que este plan evita

**1. `sueldo_sbu` no es `sueldo/SBU`.** En `features_base.py:28` vale `total / SBU`. Quien la use por
su nombre medirá otra cosa. El objetivo se calcula explícitamente (Tarea 2).

**2. La referencia estaba ponderada por persona.** Una empresa con 3.000 personas en una celda
definía el mercado aunque hubiese ≥3 empresas. Con el empleador explicando el 39% del salario, eso
es medir a un empleador y llamarlo mercado. **Se pondera por empresa** (Tarea 4) — corrección 1 de
D-009, bloqueante.

**3. El emparejamiento de texto por caracteres invierte la jerarquía.** Medido sobre datos propios:
`AUXILIAR DE SERVICIOS GENERALES → JEFE DE SERVICIOS GENERALES` con similitud 0,79. Por eso el nulo
solo-texto usa **embeddings**, no TF-IDF (Tarea 7).

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/benchmarking/evaluacion/datos.py` | leer el marco y calcular la variable objetivo |
| `src/benchmarking/evaluacion/splits.py` | partir empresas estratificado, con persistencia y hash |
| `src/benchmarking/evaluacion/referencia.py` | mediana ponderada por empresa, leave-company-out, abstención |
| `src/benchmarking/evaluacion/metricas.py` | MAE, RMSE, cobertura, curva, ω², bootstrap por empresa |
| `src/benchmarking/evaluacion/embeddings.py` | embeddings de Vertex con caché por revisión de modelo |
| `src/benchmarking/evaluacion/particiones.py` | los cuatro rivales de la escalera |
| `src/benchmarking/evaluacion/representacion.py` | normalización MFA de bloques |
| `src/benchmarking/evaluacion/estabilidad.py` | test-retest y ARI entre submuestras |
| `src/benchmarking/evaluacion/informe.py` | tabla comparativa y curva |
| `tests/sintetico.py` | generador con respuesta conocida |
| `docs/preregistro.md` | documento congelado |

---

### Tarea 1: Generador de data sintética

**Archivos:** Crear `tests/sintetico.py` · Test `tests/test_sintetico.py`

**Interfaces:** produce `generar(n_empresas=40, personas_por_empresa=25, n_roles=3, semilla=20260805)
-> pd.DataFrame` con `id_hash, empresa_ruc, numero_proceso, anio_valoracion, rol_verdadero, cargo,
cargo_norm, sueldo, pct_*, antiguedad_total, segmento, ciiu_n1, provincia, en_clean,
tiene_composicion`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_sintetico.py
import numpy as np
import pandas as pd
from sintetico import generar


def test_estructura_basica():
    df = generar(n_empresas=10, personas_por_empresa=20, n_roles=3)
    assert len(df) == 200
    assert df["empresa_ruc"].nunique() == 10
    assert df["rol_verdadero"].nunique() == 3
    assert df["id_hash"].is_unique
    assert "identificacion" not in df.columns          # frontera de privacidad


def test_los_roles_se_separan_por_composicion_no_por_sueldo():
    # Si se separaran por sueldo, una particion por bandas salariales aprobaria el
    # examen del banco y no probariamos nada.
    df = generar(n_empresas=30, personas_por_empresa=20, n_roles=3)
    comp = df.groupby("rol_verdadero")["pct_comisiones"].mean().sort_values()
    assert comp.iloc[-1] - comp.iloc[0] > 0.25


def test_hay_efecto_empresa():
    df = generar(n_empresas=30, personas_por_empresa=20, n_roles=3)
    y = np.log(df["sueldo"])
    g = df.assign(y=y).groupby("empresa_ruc")["y"].agg(["mean", "size"])
    entre = (g["size"] * (g["mean"] - y.mean()) ** 2).sum()
    assert 0.10 < entre / ((y - y.mean()) ** 2).sum() < 0.70


def test_tamanos_de_empresa_desiguales():
    # Necesario para que la ponderacion por empresa sea testeable: si todas las
    # empresas aportan lo mismo, ponderar por persona y por empresa coinciden.
    df = generar(n_empresas=20, personas_por_empresa=25, desiguales=True)
    n = df.groupby("empresa_ruc").size()
    assert n.max() >= 4 * n.min()


def test_determinista():
    pd.testing.assert_frame_equal(generar(n_empresas=5, personas_por_empresa=10, semilla=7),
                                  generar(n_empresas=5, personas_por_empresa=10, semilla=7))
```

- [ ] **Paso 2: Ejecutar y verificar que falla**

`.venv\Scripts\python.exe -m pytest tests/test_sintetico.py -v` → `ModuleNotFoundError: sintetico`

- [ ] **Paso 3: Implementar**

```python
# tests/sintetico.py
"""Data sintetica con la respuesta conocida.

Si el banco no ordena correctamente la particion verdadera frente a una aleatoria,
esta mal el BANCO. Descubrirlo aqui cuesta segundos.

Los roles se separan por COMPOSICION y antiguedad, con los sueldos solapandose por el
ruido individual y el efecto empresa, para que una particion por bandas de sueldo NO
apruebe el examen.
"""
import numpy as np
import pandas as pd

# (nombre, pct_comisiones, pct_extras, antiguedad, multiplicador salarial)
_ROLES = [("comercial", 0.45, 0.02, 6.0, 1.8),
          ("operativo", 0.01, 0.28, 9.0, 1.0),
          ("administrativo", 0.02, 0.03, 11.0, 1.3),
          ("tecnico", 0.05, 0.15, 7.0, 1.5)]
_CARGOS = {"comercial": ["VENDEDOR", "ASESOR COMERCIAL", "TRABAJADOR EN GENERAL"],
           "operativo": ["OPERARIO", "TRABAJADOR EN GENERAL", "OBRERO"],
           "administrativo": ["ASISTENTE", "TRABAJADOR EN GENERAL", "AUXILIAR"],
           "tecnico": ["TECNICO", "ASISTENTE", "OPERARIO"]}


def generar(n_empresas=40, personas_por_empresa=25, n_roles=3, semilla=20260805,
            anio=2025, sbu=470, desiguales=False):
    rng = np.random.default_rng(semilla)
    roles = _ROLES[:n_roles]
    filas = []
    for e in range(n_empresas):
        ruc = f"179{e:07d}001"
        nivel_empresa = rng.normal(0.0, 0.35)      # el empleador explica ~1/3 del salario
        # tamanos desiguales: sin esto, ponderar por persona y por empresa coinciden
        n = personas_por_empresa * (1 + 4 * (e % 5)) // 3 if desiguales else personas_por_empresa
        for p in range(n):
            nombre, m_com, m_ext, m_ant, mult = roles[(e * n + p) % len(roles)]
            base = sbu * mult * np.exp(nivel_empresa + rng.normal(0.0, 0.18))
            pc = float(np.clip(rng.normal(m_com, 0.08), 0.0, 0.85))
            pe = float(np.clip(rng.normal(m_ext, 0.05), 0.0, 0.60))
            po = float(np.clip(rng.normal(0.02, 0.02), 0.0, 0.30))
            pf = max(1.0 - pc - pe - po, 0.05)
            filas.append({
                "id_hash": f"h{e:04d}{p:04d}", "empresa_ruc": ruc,
                "numero_proceso": f"P{e:05d}", "anio_valoracion": anio,
                "rol_verdadero": nombre,
                "cargo": _CARGOS[nombre][p % len(_CARGOS[nombre])],
                "sueldo": round(base, 2),
                "pct_fijo": pf, "pct_comisiones": pc, "pct_extras": pe, "pct_otros": po,
                "antiguedad_total": int(max(0, rng.normal(m_ant, 3.0))),
                "segmento": ["MICRO", "PEQUENA", "MEDIANA", "GRANDE"][e % 4],
                "ciiu_n1": chr(ord("A") + (e % 8)),
                "provincia": f"{(e % 24) + 1:02d}",
                "en_clean": True, "tiene_composicion": True})
    df = pd.DataFrame(filas)
    df["cargo_norm"] = df["cargo"]
    return df
```

- [ ] **Paso 4: Permitir importar `sintetico`** — en `pyproject.toml`:
`pythonpath = ["src", "tests"]`

- [ ] **Paso 5: Verificar** → 5 passed

- [ ] **Paso 6: Commit**

```bash
git add tests/sintetico.py tests/test_sintetico.py pyproject.toml
git commit -m "test: generador de data sintetica con rol conocido"
```

---

### Tarea 2: Carga del marco y variable objetivo

**Archivos:** Crear `src/benchmarking/evaluacion/{__init__,datos}.py` · Test `tests/test_evaluacion_datos.py`

**Interfaces:** `SQL_MARCO`, `cargar_marco(runner, proyecto, dataset, anios=(2024,2025))`,
`agregar_objetivo(df, settings)` (añade `y`), `marco_evaluable(df)`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_datos.py
import numpy as np, pandas as pd, pytest
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion.datos import agregar_objetivo, marco_evaluable, SQL_MARCO


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv("PIPELINE_SALT", "x")
    return cargar_settings()


def test_objetivo_es_log_de_sueldo_sobre_sbu_no_de_total(s):
    # Trampa heredada: la columna sueldo_sbu de la tabla es total/SBU (features_base.py:28)
    df = pd.DataFrame({"sueldo": [940.0], "total": [1880.0], "anio_valoracion": [2025]})
    out = agregar_objetivo(df, s)
    assert abs(out["y"].iloc[0] - np.log(940.0 / 470)) < 1e-9
    assert abs(out["y"].iloc[0] - np.log(1880.0 / 470)) > 0.5


def test_objetivo_nulo_si_el_sueldo_no_es_positivo(s):
    df = pd.DataFrame({"sueldo": [0.0, -5.0, np.nan, 500.0], "total": [1.0]*3 + [500.0],
                       "anio_valoracion": [2025]*4})
    assert agregar_objetivo(df, s)["y"].isna().tolist() == [True, True, True, False]


def test_marco_evaluable_exige_objetivo_y_cargo():
    df = pd.DataFrame({"y": [1.0, 1.0, np.nan, 1.0],
                       "cargo_norm": ["CONTADOR", "", "CONTADOR", "0"]})
    out = marco_evaluable(df)
    assert len(out) == 1 and out["cargo_norm"].iloc[0] == "CONTADOR"


def test_sql_no_pide_identificadores():
    assert "identificacion" not in SQL_MARCO and "id_hash" in SQL_MARCO
```

- [ ] **Paso 2: Verificar que falla** → `ModuleNotFoundError: benchmarking.evaluacion`

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/__init__.py
```

```python
# src/benchmarking/evaluacion/datos.py
"""Carga del marco de evaluacion y variable objetivo."""
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
    composicion. OJO: la columna `sueldo_sbu` de la tabla NO sirve: vale total/SBU.
    """
    out = df.copy()
    sbu = out["anio_valoracion"].map(lambda a: settings.get_sbu(0 if pd.isna(a) else int(a)))
    sueldo = pd.to_numeric(out["sueldo"], errors="coerce")
    with np.errstate(invalid="ignore", divide="ignore"):
        out["y"] = np.log((sueldo / sbu).where(sueldo > 0))
    return out


def _cargo_utilizable(c):
    s = str(c or "").strip().upper()
    return s not in _PLACEHOLDERS and not re.fullmatch(r"[0-9]+", s)


def marco_evaluable(df):
    """Filas donde la comparacion contra CARGO es posible.

    Las filas sin cargo NO se descartan del proyecto: se reportan aparte como cobertura
    exclusiva del arquetipo. Simplemente no entran donde el rival no puede jugar.
    """
    return df[df["y"].notna() & df["cargo_norm"].map(_cargo_utilizable)].copy()
```

- [ ] **Paso 4: Verificar** → 4 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion tests/test_evaluacion_datos.py
git commit -m "feat(evaluacion): carga del marco y objetivo log(sueldo/SBU)"
```

---

### Tarea 3: Split por empresa, estratificado y persistente

**Archivos:** Crear `src/benchmarking/evaluacion/splits.py` · Test `tests/test_evaluacion_splits.py`

**Interfaces:** `empresas_test(df, frac=0.2, semilla=20260805) -> set[str]`,
`partir(df, empresas) -> (train, test)`, `guardar(empresas, ruta) -> str` (sha256), `cargar(ruta)`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_splits.py
from benchmarking.evaluacion.splits import empresas_test, partir, guardar, cargar
from sintetico import generar


def test_ninguna_empresa_cruza():
    df = generar(n_empresas=40, personas_por_empresa=10)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    assert set(tr["empresa_ruc"]) & set(ts["empresa_ruc"]) == set()
    assert len(tr) + len(ts) == len(df)


def test_proporcion_aproximada():
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert 8 <= len(empresas_test(df, frac=0.2)) <= 12


def test_estratifica_por_segmento():
    df = generar(n_empresas=40, personas_por_empresa=10)
    ts = df[df["empresa_ruc"].isin(empresas_test(df, frac=0.25))]
    assert ts["segmento"].nunique() == df["segmento"].nunique()


def test_determinista():
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert empresas_test(df, semilla=7) == empresas_test(df, semilla=7)
    assert empresas_test(df, semilla=7) != empresas_test(df, semilla=8)


def test_persistencia_con_hash(tmp_path):
    # El hash entra en el pre-registro: prueba de que el test-set no se cambio despues.
    df = generar(n_empresas=20, personas_por_empresa=5)
    te = empresas_test(df, frac=0.2)
    h = guardar(te, tmp_path / "split.json")
    assert len(h) == 64 and cargar(tmp_path / "split.json") == te
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/splits.py
"""Particion train/test por EMPRESA.

Por empresa y no por fila: una persona pertenece a una empresa y recurre entre anios,
asi que partir por filas dejaria a sus companeros en los dos lados y el
leave-company-out de la referencia no probaria nada.
"""
import hashlib
import json
import numpy as np

SEMILLA = 20260805


def empresas_test(df, frac=0.2, semilla=SEMILLA):
    emp = (df[["empresa_ruc", "segmento", "ciiu_n1"]]
           .drop_duplicates(subset=["empresa_ruc"]).sort_values("empresa_ruc")
           .reset_index(drop=True))
    emp["estrato"] = emp["segmento"].astype(str) + "|" + emp["ciiu_n1"].astype(str)
    rng = np.random.default_rng(semilla)
    elegidas = []
    for _, grupo in emp.groupby("estrato", sort=True):
        rucs = grupo["empresa_ruc"].tolist()
        # al menos una por estrato: sin esto, 5 de los 70 estratos reales desaparecen
        # del test y la estratificacion falla donde mas hace falta. Cuesta 0,1 puntos.
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
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"empresas_test": lista}, fh, ensure_ascii=False, indent=2)
    return hashlib.sha256("\n".join(lista).encode("utf-8")).hexdigest()


def cargar(ruta):
    with open(ruta, encoding="utf-8") as fh:
        return set(json.load(fh)["empresas_test"])
```

- [ ] **Paso 4: Verificar** → 5 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/splits.py tests/test_evaluacion_splits.py
git commit -m "feat(evaluacion): split por empresa estratificado con hash"
```

---

### Tarea 4: Referencia salarial — mediana ponderada por empresa

El corazón del banco, y la corrección bloqueante de D-009.

**Archivos:** Crear `src/benchmarking/evaluacion/referencia.py` · Test `tests/test_evaluacion_referencia.py`

**Interfaces:** `predecir(train, test, col_celda, min_donantes=5, min_empresas=3) -> pd.DataFrame`
con `y_ref` (NaN = abstención), `n_donantes`, `n_empresas_donantes`.

**Cómo funciona la ponderación por empresa.** Cada empresa donante aporta **un voto**: la mediana de
sus personas en esa celda. La referencia es la **mediana de esos votos**, excluyendo el de la
empresa de la persona evaluada.

Efecto secundario feliz: la mediana con leave-company-out **se vuelve barata**. Ya no hay que
recalcular sobre miles de personas, sino sobre el puñado de votos de empresa de cada celda —
ordenados una vez, quitar un elemento es un ajuste de índice O(1).

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_referencia.py
import numpy as np, pandas as pd
from benchmarking.evaluacion.referencia import predecir, _mediana_sin_indice


def _m(filas):
    return pd.DataFrame(filas, columns=["empresa_ruc", "celda", "y"])


def test_excluye_la_propia_empresa():
    # El efecto empresa explica ~39% de la varianza: usando a los companeros se
    # acertaria por la razon equivocada.
    train = _m([("E1","c",10.0)]*3 + [(f"E{i}","c",1.0) for i in range(2,7)])
    out = predecir(train, _m([("E1","c",10.0)]), "celda")
    assert abs(out["y_ref"].iloc[0] - 1.0) < 1e-9


def test_una_empresa_grande_no_define_el_mercado():
    # LA correccion de D-009. Con ponderacion por persona, E1 (100 personas a 5.0)
    # arrastraria la mediana; ponderando por empresa vale un voto igual que las demas.
    train = _m([("E1","c",5.0)]*100 + [(f"E{i}","c",1.0) for i in range(2,7)])
    out = predecir(train, _m([("E9","c",1.0)]), "celda")
    assert abs(out["y_ref"].iloc[0] - 1.0) < 1e-9, "una empresa = un voto"
    assert out["n_empresas_donantes"].iloc[0] == 6


def test_la_mediana_de_una_empresa_resume_a_sus_personas():
    train = _m([("E1","c",1.0),("E1","c",3.0),("E1","c",5.0)] +
               [(f"E{i}","c",100.0) for i in range(2,6)])
    # votos: E1=3.0, E2..E5=100.0 -> mediana de [3,100,100,100,100] = 100
    out = predecir(train, _m([("E9","c",0.0)]), "celda")
    assert abs(out["y_ref"].iloc[0] - 100.0) < 1e-9


def test_se_abstiene_con_pocos_donantes():
    out = predecir(_m([("E2","c",1.0),("E3","c",1.0)]), _m([("E1","c",1.0)]), "celda")
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_donantes"].iloc[0] == 2


def test_se_abstiene_con_pocas_empresas_aunque_sobren_personas():
    train = _m([("E2","c",1.0)]*5 + [("E3","c",1.0)]*5)
    out = predecir(train, _m([("E1","c",1.0)]), "celda")
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_empresas_donantes"].iloc[0] == 2


def test_se_abstiene_en_celda_no_vista():
    out = predecir(_m([("E2","c",1.0)]*8), _m([("E1","otra",1.0)]), "celda")
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_donantes"].iloc[0] == 0


def test_una_celda_por_persona_no_predice_nada():
    # La trampa que la balanza debe castigar: partir de mas deja los cajones vacios.
    train = pd.DataFrame({"empresa_ruc": [f"E{i}" for i in range(20)],
                          "celda": [f"c{i}" for i in range(20)],
                          "y": np.linspace(0, 2, 20)})
    out = predecir(train, pd.DataFrame({"empresa_ruc":["E0"],"celda":["c0"],"y":[0.0]}), "celda")
    assert pd.isna(out["y_ref"].iloc[0])


def test_mediana_sin_indice():
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _mediana_sin_indice(v, 0) == 3.5      # [2,3,4,5]
    assert _mediana_sin_indice(v, 2) == 3.0      # [1,2,4,5] -> (2+4)/2
    assert _mediana_sin_indice(v, 4) == 2.5      # [1,2,3,4]
    assert np.isnan(_mediana_sin_indice(np.array([7.0]), 0))
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/referencia.py
"""Referencia salarial de una celda, ponderada por EMPRESA y con leave-company-out.

Dos decisiones que definen este modulo:

1. **Una empresa = un voto.** Cada empresa donante aporta la mediana de sus personas en
   la celda, y la referencia es la mediana de esos votos. Ponderar por persona dejaria
   que una empresa con 3.000 personas definiera el mercado aunque se cumpla la regla de
   >=3 empresas — y el empleador explica el 39% de la varianza del salario. Es la
   correccion 1 de D-009, y cambia todos los numeros.

2. **Mediana, no media.** Medido sobre 498.653 personas: la diferencia entre ambas es
   0,0533 en log, un sexto del error esperado, y NO es neutral — aparece en las celdas
   mezcladas, asi que la media castiga mas a las particiones que mezclan, que es CARGO.
   Seria un sesgo a favor de la hipotesis propia.

Efecto secundario de (1): la mediana con leave-company-out deja de ser cara. Se opera
sobre el punado de votos de empresa de cada celda, no sobre miles de personas.
"""
import numpy as np
import pandas as pd


def _mediana_sin_indice(v_ordenado, j):
    """Mediana de `v_ordenado` quitando la posicion j. O(1) sobre el array ya ordenado."""
    m = len(v_ordenado)
    n = m - 1
    if n <= 0:
        return np.nan
    # el elemento i del array reducido es v[i] si i < j, y v[i+1] si i >= j
    tomar = lambda i: v_ordenado[i + 1] if i >= j else v_ordenado[i]
    if n % 2:
        return float(tomar(n // 2))
    return float((tomar(n // 2 - 1) + tomar(n // 2)) / 2.0)


def predecir(train, test, col_celda, min_donantes=5, min_empresas=3):
    """`y_ref`, `n_donantes` y `n_empresas_donantes` alineados con `test`.

    `y_ref` es NaN cuando el metodo se ABSTIENE: no cuenta como error, cuenta contra su
    cobertura. `n_donantes` cuenta PERSONAS (el umbral del BLS es de personas);
    `n_empresas_donantes` cuenta empresas distintas.
    """
    tr = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])

    # voto de cada empresa en cada celda + cuantas personas lo sostienen
    votos = (tr.groupby([col_celda, "empresa_ruc"])["y"]
               .agg(voto="median", n="size").reset_index())

    # por celda: los votos ordenados, el total de personas, y el indice de cada empresa
    orden = {}
    personas = {}
    pos = {}
    for celda, g in votos.groupby(col_celda, sort=False):
        g = g.sort_values("voto", kind="mergesort")
        orden[celda] = g["voto"].to_numpy(float)
        personas[celda] = int(g["n"].sum())
        pos[celda] = {ruc: i for i, ruc in enumerate(g["empresa_ruc"])}

    n_pers_emp = {(r[col_celda], r.empresa_ruc): int(r.n) for r in votos.itertuples()}

    y_ref, n_don, n_emp = [], [], []
    for celda, emp in zip(test[col_celda], test["empresa_ruc"]):
        v = orden.get(celda)
        if v is None:
            y_ref.append(np.nan); n_don.append(0); n_emp.append(0)
            continue
        j = pos[celda].get(emp)                       # -1 logico: la propia empresa
        propias = n_pers_emp.get((celda, emp), 0)
        d = personas[celda] - propias
        e = len(v) - (1 if j is not None else 0)
        if d >= min_donantes and e >= min_empresas:
            m = (_mediana_sin_indice(v, j) if j is not None
                 else float(np.median(v)))
        else:
            m = np.nan
        y_ref.append(m); n_don.append(d); n_emp.append(e)

    return pd.DataFrame({"y_ref": y_ref, "n_donantes": n_don,
                         "n_empresas_donantes": n_emp}, index=test.index)
```

- [ ] **Paso 4: Verificar** → 8 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/referencia.py tests/test_evaluacion_referencia.py
git commit -m "feat(evaluacion): referencia con mediana ponderada por empresa y leave-company-out"
```

---

### Tarea 5: Error, cobertura y curva

**Archivos:** Crear `src/benchmarking/evaluacion/metricas.py` · Test `tests/test_evaluacion_metricas.py`

**Interfaces:** `error_y_cobertura(test, pred) -> dict` con `mae`, `rmse`, `cobertura`,
`n_evaluadas`, `n_total` · `curva_error_cobertura(train, test, col_celda, umbrales=UMBRALES)`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_metricas.py
import numpy as np, pandas as pd
from benchmarking.evaluacion.metricas import error_y_cobertura, curva_error_cobertura, UMBRALES


def test_las_abstenciones_no_cuentan_como_error():
    # Si contaran, un metodo que se calla saldria peor que uno que responde mal.
    r = error_y_cobertura(pd.DataFrame({"y": [1.0, 2.0, 3.0]}),
                          pd.DataFrame({"y_ref": [1.1, np.nan, np.nan]}))
    assert abs(r["mae"] - 0.1) < 1e-9 and abs(r["cobertura"] - 1/3) < 1e-9
    assert r["n_evaluadas"] == 1 and r["n_total"] == 3


def test_reporta_mae_y_rmse():
    # MAE es la principal por coherencia con la mediana (la mediana minimiza el error
    # absoluto); RMSE acompana para ver si un metodo esconde fallos grandes.
    r = error_y_cobertura(pd.DataFrame({"y": [0.0, 0.0]}),
                          pd.DataFrame({"y_ref": [1.0, 3.0]}))
    assert abs(r["mae"] - 2.0) < 1e-9
    assert abs(r["rmse"] - np.sqrt(5.0)) < 1e-9


def test_cobertura_cero_no_revienta():
    r = error_y_cobertura(pd.DataFrame({"y": [1.0, 2.0]}), pd.DataFrame({"y_ref": [np.nan]*2}))
    assert r["cobertura"] == 0.0 and np.isnan(r["mae"])


def test_curva_ocho_umbrales_y_cobertura_decreciente():
    # 8 puntos bastan para dibujarla; 30 multiplicaban por cuatro el costo de la mediana.
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=40, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    c = curva_error_cobertura(tr, ts, "rol_verdadero")
    assert list(c["min_donantes"]) == list(UMBRALES) and len(UMBRALES) == 8
    assert c["cobertura"].is_monotonic_decreasing and (c["cobertura"] <= 1.0).all()
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/metricas.py
"""Error, cobertura y la curva que los relaciona."""
import numpy as np
import pandas as pd
from .referencia import predecir

# 8 puntos dibujan la curva igual que 30 y dividen por cuatro el costo de la mediana.
UMBRALES = (1, 2, 3, 5, 8, 12, 20, 30)


def error_y_cobertura(test, pred):
    """MAE y RMSE sobre las filas donde el metodo NO se abstuvo, mas su cobertura.

    Se reportan juntos siempre: comparar solo el error favorece al metodo que se
    abstiene mas, porque acierta mas donde unicamente opina teniendo datos.
    MAE es la principal — la mediana minimiza el error absoluto, asi que estimador y
    metrica van emparejados.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    ref = pd.to_numeric(pred["y_ref"], errors="coerce").to_numpy(float)
    ok = ~np.isnan(ref) & ~np.isnan(y)
    n_total, n_eval = len(y), int(ok.sum())
    err = y[ok] - ref[ok]
    return {"mae": float(np.abs(err).mean()) if n_eval else float("nan"),
            "rmse": float(np.sqrt((err ** 2).mean())) if n_eval else float("nan"),
            "cobertura": n_eval / n_total if n_total else 0.0,
            "n_evaluadas": n_eval, "n_total": n_total}


def curva_error_cobertura(train, test, col_celda, umbrales=UMBRALES, min_empresas=3):
    """Barre el umbral de donantes: es la perilla de confianza, y es la unica que
    CARGO y el arquetipo pueden compartir (CARGO no emite score propio). Permite
    compararlos a COBERTURA IGUALADA."""
    filas = []
    for m in umbrales:
        r = error_y_cobertura(test, predecir(train, test, col_celda,
                                             min_donantes=int(m), min_empresas=min_empresas))
        filas.append({"min_donantes": int(m), "cobertura": r["cobertura"],
                      "mae": r["mae"], "rmse": r["rmse"]})
    return pd.DataFrame(filas)
```

- [ ] **Paso 4: Verificar** → 4 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/metricas.py tests/test_evaluacion_metricas.py
git commit -m "feat(evaluacion): MAE, RMSE, cobertura y curva de 8 umbrales"
```

---

### Tarea 6: Bootstrap por empresa y ω² intra-empresa

**Archivos:** Modificar `metricas.py` · Test: añadir a `tests/test_evaluacion_metricas.py`

**Interfaces:** `ic_bootstrap_empresas(train, test, col_celda, n=1000, semilla=20260805) -> dict`
con `mae`, `ic_bajo`, `ic_alto` · `omega2_intra_empresa(df, col_celda) -> float`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# anadir a tests/test_evaluacion_metricas.py
from benchmarking.evaluacion.metricas import ic_bootstrap_empresas, omega2_intra_empresa


def _datos():
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=40, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def test_bootstrap_remuestrea_empresas_no_filas():
    # Remuestrear filas fingiria independencia inexistente: el IC saldria irrealmente
    # estrecho y cualquier diferencia pareceria significativa.
    tr, ts = _datos()
    r = ic_bootstrap_empresas(tr, ts, "rol_verdadero", n=80, semilla=1)
    assert r["ic_bajo"] < r["mae"] < r["ic_alto"]


def test_bootstrap_determinista():
    tr, ts = _datos()
    assert (ic_bootstrap_empresas(tr, ts, "rol_verdadero", n=40, semilla=3) ==
            ic_bootstrap_empresas(tr, ts, "rol_verdadero", n=40, semilla=3))


def test_omega2_premia_la_particion_verdadera():
    from sintetico import generar
    df = generar(n_empresas=30, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    df["azar"] = np.random.default_rng(0).integers(0, 3, len(df)).astype(str)
    assert omega2_intra_empresa(df, "rol_verdadero") > omega2_intra_empresa(df, "azar")


def test_omega2_no_premia_una_celda_por_persona():
    from sintetico import generar
    df = generar(n_empresas=20, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    df["cada_uno"] = df["id_hash"]
    assert omega2_intra_empresa(df, "cada_uno") < omega2_intra_empresa(df, "rol_verdadero")
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# anadir a src/benchmarking/evaluacion/metricas.py

def ic_bootstrap_empresas(train, test, col_celda, n=1000, semilla=20260805,
                          min_donantes=5, min_empresas=3, alfa=0.05):
    """IC del MAE remuestreando EMPRESAS del test con reemplazo.

    Nunca filas: la fila no es la unidad independiente (una empresa aporta cientos de
    personas, una persona recurre entre anios).
    """
    pred = predecir(train, test, col_celda, min_donantes=min_donantes,
                    min_empresas=min_empresas)
    base = test.assign(_ref=pred["y_ref"].to_numpy())
    base = base[base["_ref"].notna() & base["y"].notna()]
    base = base.assign(_abs=(base["y"] - base["_ref"]).abs())

    g = base.groupby("empresa_ruc")["_abs"].agg(suma="sum", n="size")
    sumas, enes = g["suma"].to_numpy(float), g["n"].to_numpy(float)
    if enes.sum() == 0:
        return {"mae": float("nan"), "ic_bajo": float("nan"), "ic_alto": float("nan")}

    rng = np.random.default_rng(semilla)
    muestras = []
    for _ in range(int(n)):
        i = rng.integers(0, len(sumas), len(sumas))
        tot = enes[i].sum()
        if tot > 0:
            muestras.append(sumas[i].sum() / tot)
    muestras = np.array(muestras)
    return {"mae": float(sumas.sum() / enes.sum()),
            "ic_bajo": float(np.quantile(muestras, alfa / 2)),
            "ic_alto": float(np.quantile(muestras, 1 - alfa / 2))}


def omega2_intra_empresa(df, col_celda):
    """omega2 de la celda sobre el residuo INTRA-empresa del objetivo.

    Se residualiza contra la empresa primero porque el empleador explica ~39% de la
    varianza del log-salario. Sin encogimiento: medido sobre 2025, el 76,6% de la gente
    esta en empresas de 100 o mas personas, asi que la correccion del modelo mixto
    apenas mueve nada (D-006 #3). omega2 y no eta2 porque penaliza los grados de
    libertad, y aqui se comparan cardinalidades muy distintas.
    """
    d = df[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"]).copy()
    if d.empty:
        return float("nan")
    d["r"] = d["y"] - d.groupby("empresa_ruc")["y"].transform("mean")
    k, n = d[col_celda].nunique(), len(d)
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

- [ ] **Paso 4: Verificar** → 8 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/metricas.py tests/test_evaluacion_metricas.py
git commit -m "feat(evaluacion): bootstrap por empresa y omega2 intra-empresa"
```

---

### Tarea 7: Embeddings de Vertex con caché

**Archivos:** Crear `src/benchmarking/evaluacion/embeddings.py` · Test `tests/test_evaluacion_embeddings.py`
· Modificar `settings.py`

**Interfaces:** `embeber(textos, cliente, modelo, cache=None) -> np.ndarray` (n × d, filas alineadas
con `textos`) · `CacheEmbeddings` con `leer(clave)` / `guardar(clave, matriz)`.

**Por qué embeddings y no TF-IDF.** Medido sobre datos propios: la similitud de caracteres
**invierte la jerarquía** — `AUXILIAR DE SERVICIOS GENERALES → JEFE DE SERVICIOS GENERALES` puntúa
0,79. Un nulo solo-texto construido así sería más flojo de lo necesario, y vencer a un rival flojo
no demuestra nada.

- [ ] **Paso 1: Añadir la configuración** — en `settings.py`:

```python
    # La revision del modelo entra en la clave de cache: si Google la cambia sin avisar,
    # los resultados dejan de ser reproducibles y hay que enterarse (spec de clustering §11).
    vertex_embedding_model: str = "text-multilingual-embedding-002"
    vertex_location: str = "us-central1"
```

- [ ] **Paso 2: Escribir el test que falla**

```python
# tests/test_evaluacion_embeddings.py
import numpy as np
from unittest.mock import MagicMock
from benchmarking.evaluacion.embeddings import embeber, CacheMemoriaEmb


def _cliente_falso(dim=4):
    cl = MagicMock()
    def responder(textos, **kw):
        return [MagicMock(values=[float(len(t)), 1.0, 0.0, 0.0]) for t in textos]
    cl.get_embeddings.side_effect = responder
    return cl


def test_solo_embebe_textos_unicos():
    # 56.000 titulos distintos entre 1,3 M de filas: embeber por fila seria 20x mas caro.
    cl = _cliente_falso()
    textos = ["VENDEDOR", "VENDEDOR", "CONTADOR", "VENDEDOR"]
    X = embeber(textos, cl, "m")
    assert X.shape == (4, 4)
    enviados = [t for c in cl.get_embeddings.call_args_list for t in c.args[0]]
    assert sorted(enviados) == ["CONTADOR", "VENDEDOR"]
    np.testing.assert_array_equal(X[0], X[1])          # filas repetidas, mismo vector


def test_el_cache_evita_volver_a_llamar():
    cache = CacheMemoriaEmb()
    cl = _cliente_falso()
    embeber(["VENDEDOR"], cl, "m", cache=cache)
    n1 = cl.get_embeddings.call_count
    embeber(["VENDEDOR"], cl, "m", cache=cache)
    assert cl.get_embeddings.call_count == n1


def test_la_revision_del_modelo_entra_en_la_clave():
    # Si Google cambia el modelo, el cache no debe devolver vectores del anterior.
    cache = CacheMemoriaEmb()
    cl = _cliente_falso()
    embeber(["VENDEDOR"], cl, "modelo-A", cache=cache)
    n1 = cl.get_embeddings.call_count
    embeber(["VENDEDOR"], cl, "modelo-B", cache=cache)
    assert cl.get_embeddings.call_count > n1
```

- [ ] **Paso 3: Verificar que falla**

- [ ] **Paso 4: Implementar**

```python
# src/benchmarking/evaluacion/embeddings.py
"""Embeddings del texto de cargo, via Vertex AI, con cache.

Dos cuidados que no son opcionales:

- **Solo se embeben textos unicos.** Hay ~56.000 titulos distintos entre 1,3 M de filas:
  embeber por fila seria 20x mas caro y lento sin ganar nada.
- **La revision del modelo entra en la clave de cache.** El spec de clustering §11 lo
  exige: si Google cambia el modelo sin avisar, los resultados dejan de ser
  reproducibles y hay que enterarse.
"""
import numpy as np

LOTE = 250          # limite practico de la API por peticion


class CacheMemoriaEmb:
    def __init__(self):
        self._d = {}

    def leer(self, clave):
        return self._d.get(clave)

    def guardar(self, clave, vector):
        self._d[clave] = vector


def embeber(textos, cliente, modelo, cache=None, lote=LOTE):
    """Devuelve una matriz (len(textos) x d) alineada con `textos`."""
    unicos = sorted({str(t) for t in textos})
    vectores = {}
    pendientes = []
    for t in unicos:
        v = cache.leer((modelo, t)) if cache is not None else None
        if v is None:
            pendientes.append(t)
        else:
            vectores[t] = np.asarray(v, dtype=float)

    for i in range(0, len(pendientes), lote):
        trozo = pendientes[i:i + lote]
        for t, emb in zip(trozo, cliente.get_embeddings(trozo)):
            v = np.asarray(emb.values, dtype=float)
            vectores[t] = v
            if cache is not None:
                cache.guardar((modelo, t), v)

    return np.vstack([vectores[str(t)] for t in textos])


def cliente_vertex(modelo, proyecto, location):
    """Cliente real de Vertex. Se aisla aqui para que los tests no lo importen."""
    import vertexai
    from vertexai.language_models import TextEmbeddingModel
    vertexai.init(project=proyecto, location=location)
    return TextEmbeddingModel.from_pretrained(modelo)
```

- [ ] **Paso 5: Verificar** → 3 passed

- [ ] **Paso 6: Commit**

```bash
git add src/benchmarking/evaluacion/embeddings.py tests/test_evaluacion_embeddings.py src/benchmarking/config/settings.py
git commit -m "feat(evaluacion): embeddings de Vertex con cache por revision de modelo"
```

---

### Tarea 8: Normalización MFA de bloques

**Archivos:** Crear `src/benchmarking/evaluacion/representacion.py` · Test `tests/test_evaluacion_representacion.py`

**Interfaces:** `normalizar_mfa(bloques: list[np.ndarray]) -> np.ndarray`

**Por qué MFA.** Sustituye el peso de bloque como hiperparámetro (corrección 2 de D-009). Divide
cada bloque por su **primer valor singular**, de modo que la dirección dominante de cada bloque mide
1 y ninguno impone su forma sobre el primer eje. Es **invariante al número de dimensiones** del
bloque — que es la propiedad que hace falta con ~100 de texto frente a 4 de composición. **Cero
parámetros libres**, y por tanto nada que afinar contra el salario.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_representacion.py
import numpy as np
from benchmarking.evaluacion.representacion import normalizar_mfa


def test_ningun_bloque_domina_por_numero_de_dimensiones():
    # El fallo que MFA corrige: un bloque ancho gana por sumar mas dimensiones,
    # no por ser mas informativo.
    rng = np.random.default_rng(0)
    estrecho = rng.normal(0, 1, (200, 3))
    ancho = rng.normal(0, 1, (200, 100))
    X = normalizar_mfa([estrecho, ancho])
    d_estrecho = np.linalg.norm(X[:, :3] - X[:1, :3], axis=1).mean()
    d_ancho = np.linalg.norm(X[:, 3:] - X[:1, 3:], axis=1).mean()
    assert 0.2 < d_estrecho / d_ancho < 5.0, "las contribuciones deben ser del mismo orden"


def test_invariante_a_la_escala_del_bloque():
    rng = np.random.default_rng(1)
    a, b = rng.normal(0, 1, (100, 4)), rng.normal(0, 1, (100, 6))
    np.testing.assert_allclose(normalizar_mfa([a, b]), normalizar_mfa([a * 1000, b]), atol=1e-8)


def test_primer_valor_singular_unitario_por_bloque():
    from sklearn.utils.extmath import randomized_svd
    rng = np.random.default_rng(2)
    X = normalizar_mfa([rng.normal(0, 3, (150, 5)), rng.normal(0, 0.1, (150, 20))])
    for ini, fin in ((0, 5), (5, 25)):
        B = X[:, ini:fin]
        s = randomized_svd(B - B.mean(axis=0), n_components=1, random_state=0)[1][0]
        assert abs(s - 1.0) < 1e-6


def test_bloque_constante_no_revienta():
    X = normalizar_mfa([np.ones((10, 3)), np.random.default_rng(3).normal(0, 1, (10, 2))])
    assert np.isfinite(X).all()
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/representacion.py
"""Normalizacion de bloques heterogeneos por Analisis Factorial Multiple (MFA).

El problema: al concatenar bloques de tamanos distintos, la distancia euclidea suma una
diferencia por dimension, asi que un bloque de 100 columnas domina a uno de 4 aunque
cada columna aporte poco. Normalizar a varianza unitaria no lo arregla: dos bloques con
la misma varianza total pero repartida de forma distinta influyen de forma distinta
sobre los primeros ejes, que son los que k-means y GMM usan.

MFA divide cada bloque por su **primer valor singular**, de modo que la direccion
dominante de cada uno mide 1. Es invariante al numero de dimensiones y a la escala, no
tiene parametros libres, y es citable (Escofier & Pages 1994; Abdi et al. 2013).

Sustituye al peso de bloque como hiperparametro (correccion 2 de D-009): sin
hiperparametro no hay nada que afinar contra el salario.
"""
import numpy as np
from sklearn.utils.extmath import randomized_svd


def normalizar_mfa(bloques, semilla=20260805):
    """Concatena los bloques, cada uno centrado y dividido por su primer valor singular."""
    partes = []
    for B in bloques:
        B = np.asarray(B, dtype=float)
        Bc = B - B.mean(axis=0)
        if not np.any(Bc):                       # bloque constante: nada que escalar
            partes.append(Bc)
            continue
        s1 = randomized_svd(Bc, n_components=1, random_state=int(semilla))[1][0]
        partes.append(Bc / s1 if s1 > 0 else Bc)
    return np.hstack(partes)
```

- [ ] **Paso 4: Verificar** → 4 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/representacion.py tests/test_evaluacion_representacion.py
git commit -m "feat(evaluacion): normalizacion MFA de bloques, sin hiperparametros"
```

---

### Tarea 9: Las particiones rivales

**Archivos:** Crear `src/benchmarking/evaluacion/particiones.py` · Modificar `pyproject.toml`
(`scikit-learn`, `matplotlib`) · Test `tests/test_evaluacion_particiones.py`

**Interfaces:** todas devuelven `pd.Series` alineada al índice del DataFrame:
`cargo_crudo(df)` · `aleatoria(df, k, semilla)` · `solo_texto(df, k, embeddings, semilla)` ·
`techo_supervisado(df, k, semilla)`.

- [ ] **Paso 1: Añadir dependencias** — en `pyproject.toml`, a `dependencies`:
`"scikit-learn>=1.4", "matplotlib>=3.8",` · luego `.venv\Scripts\python.exe -m pip install -e .`

- [ ] **Paso 2: Escribir el test que falla**

```python
# tests/test_evaluacion_particiones.py
import numpy as np, pandas as pd
from sintetico import generar
from benchmarking.evaluacion.particiones import (
    cargo_crudo, aleatoria, solo_texto, techo_supervisado)


def test_cargo_crudo_no_poda_nada():
    # Podar CARGO a sus top-50 dejaria a 429.000 personas en una celda "otros":
    # ganarle a ese rival no demostraria nada (D-005). Compite entero.
    df = pd.DataFrame({"cargo_norm": ["VENDEDOR"]*3 + [f"RARO{i}" for i in range(50)]})
    c = cargo_crudo(df)
    assert c.nunique() == 51 and (c == "VENDEDOR").sum() == 3


def test_aleatoria_respeta_k_y_es_determinista():
    df = generar(n_empresas=20, personas_por_empresa=10)
    a = aleatoria(df, k=7, semilla=5)
    assert a.nunique() == 7
    pd.testing.assert_series_equal(a, aleatoria(df, k=7, semilla=5))


def test_solo_texto_agrupa_por_los_embeddings_dados():
    # Se le inyectan los embeddings: el modulo no llama a Vertex.
    df = pd.DataFrame({"cargo_norm": ["A", "A", "B", "B"]})
    emb = np.array([[0., 0.], [0.1, 0.], [9., 9.], [9.1, 9.]])
    c = solo_texto(df, k=2, embeddings=emb, semilla=1)
    assert c.iloc[0] == c.iloc[1] and c.iloc[2] == c.iloc[3] and c.iloc[0] != c.iloc[2]


def test_techo_supervisado_agrupa_por_salario():
    # Hace trampa a proposito: es la cota superior y la alarma de deriva a bandas.
    df = pd.DataFrame({"y": [0.0, 0.05, 0.1, 5.0, 5.05, 5.1]})
    c = techo_supervisado(df, k=2, semilla=1)
    assert c.iloc[0] == c.iloc[2] and c.iloc[3] == c.iloc[5] and c.iloc[0] != c.iloc[3]


def test_todas_devuelven_serie_alineada():
    df = generar(n_empresas=10, personas_por_empresa=10)
    df["y"] = np.log(df["sueldo"] / 470)
    emb = np.random.default_rng(0).normal(0, 1, (len(df), 8))
    for s in (cargo_crudo(df), aleatoria(df, 3), solo_texto(df, 3, emb), techo_supervisado(df, 3)):
        assert isinstance(s, pd.Series) and s.index.equals(df.index) and s.notna().all()
```

- [ ] **Paso 3: Verificar que falla**

- [ ] **Paso 4: Implementar**

```python
# src/benchmarking/evaluacion/particiones.py
"""Las particiones rivales de la escalera de referencias.

  aleatoria         -> ¿supero al azar?
  cargo_crudo       -> ¿supero lo que se usa hoy, entero y sin podar?
  solo_texto        -> ¿la composicion aporta algo mas alla del nombre del puesto?
  techo_supervisado -> ¿cuanto es lo maximo posible con estos datos?
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

SEMILLA = 20260805


def cargo_crudo(df):
    """CARGO tal cual, con todas sus etiquetas. No se poda (D-005)."""
    return df["cargo_norm"].astype(str).rename("celda")


def aleatoria(df, k, semilla=SEMILLA):
    """Piso de la escalera: k celdas sin ninguna informacion."""
    rng = np.random.default_rng(semilla)
    return pd.Series(rng.integers(0, int(k), len(df)).astype(str),
                     index=df.index, name="celda")


def solo_texto(df, k, embeddings, semilla=SEMILLA):
    """Agrupa por el significado del titulo, en k celdas.

    Los embeddings se inyectan ya calculados (ver `embeddings.py`): este modulo no habla
    con Vertex. Se usan embeddings y no TF-IDF porque la similitud de caracteres invierte
    la jerarquia — medido: AUXILIAR DE SERVICIOS GENERALES -> JEFE DE SERVICIOS GENERALES
    puntua 0,79 — y eso produciria un rival mas flojo del necesario.
    """
    X = np.asarray(embeddings, dtype=float)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10)
    return pd.Series(km.fit_predict(X).astype(str), index=df.index, name="celda")


def techo_supervisado(df, k, semilla=SEMILLA):
    """Agrupa DIRECTAMENTE por el salario: circular por diseno.

    No es un metodo candidato. Fija la escala del resultado propio (un MAE de 0,18 no se
    interpreta sin saber cuanto logra la trampa) y es la alarma: si el arquetipo se le
    acerca demasiado, sospechar deriva a bandas salariales.
    """
    y = pd.to_numeric(df["y"], errors="coerce").fillna(0.0).to_numpy(float).reshape(-1, 1)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10)
    return pd.Series(km.fit_predict(y).astype(str), index=df.index, name="celda")
```

- [ ] **Paso 5: Verificar** → 5 passed

- [ ] **Paso 6: Commit**

```bash
git add src/benchmarking/evaluacion/particiones.py tests/test_evaluacion_particiones.py pyproject.toml
git commit -m "feat(evaluacion): las cuatro particiones de la escalera"
```

---

### Tarea 10: El banco se valida a sí mismo

**Archivos:** Test `tests/test_evaluacion_banco.py`

Un instrumento que nadie verificó no sirve para verificar nada. **Si algún test falla aquí, está mal
el banco (Tareas 3–9), no el test.**

- [ ] **Paso 1: Escribir la prueba de aceptación**

```python
# tests/test_evaluacion_banco.py
"""Prueba de aceptacion: el banco debe ordenar bien particiones de calidad conocida."""
import numpy as np, pandas as pd, pytest
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


def _r(df, col):
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    return error_y_cobertura(ts, predecir(tr, ts, col))


def test_la_particion_verdadera_gana_a_la_aleatoria(marco):
    m = marco.assign(azar=aleatoria(marco, k=3))
    assert _r(m, "rol_verdadero")["mae"] < _r(m, "azar")["mae"]


def test_la_particion_deliberadamente_mala_pierde(marco):
    m = marco.assign(tonta=marco["id_hash"].str[-1])
    assert _r(m, "rol_verdadero")["mae"] < _r(m, "tonta")["mae"]


def test_una_celda_por_persona_no_gana(marco):
    # La trampa que hundio a la Balanza 1: partir de mas debe COSTAR.
    assert _r(marco.assign(cada_uno=marco["id_hash"]), "cada_uno")["cobertura"] == 0.0


def test_la_abstencion_cuenta_en_cobertura_y_no_en_error(marco):
    r = _r(marco, "rol_verdadero")
    assert 0.0 < r["cobertura"] <= 1.0 and not np.isnan(r["mae"])


def test_una_empresa_dominante_no_secuestra_la_referencia():
    # La correccion 1 de D-009, extremo a extremo: una empresa con 20x mas gente y un
    # nivel salarial atipico no debe mover la referencia de las demas.
    df = generar(n_empresas=30, personas_por_empresa=10, desiguales=True)
    df["y"] = np.log(df["sueldo"] / 470)
    grande = df["empresa_ruc"].value_counts().idxmax()
    df.loc[df["empresa_ruc"] == grande, "y"] += 3.0        # paga muchisimo mas
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    ts = ts[ts["empresa_ruc"] != grande]
    r = error_y_cobertura(ts, predecir(tr, ts, "rol_verdadero"))
    assert r["mae"] < 0.6, "la empresa atipica no debe arrastrar la referencia del resto"
```

- [ ] **Paso 2: Ejecutar** → 5 passed. **Si falla alguno, arreglar el módulo correspondiente
antes de seguir.**

- [ ] **Paso 3: Commit**

```bash
git add tests/test_evaluacion_banco.py
git commit -m "test(evaluacion): prueba de aceptacion del banco"
```

---

### Tarea 11: Estabilidad — test-retest y ARI

**Archivos:** Crear `src/benchmarking/evaluacion/estabilidad.py` · Test `tests/test_evaluacion_estabilidad.py`

**Interfaces:** `test_retest(df, col_celda, col_persona="id_hash", col_anio="anio_valoracion") -> dict`
· `ari_submuestras(df, asignador, n=20, frac=0.5, semilla=20260805) -> dict`

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_estabilidad.py
import numpy as np, pandas as pd
from benchmarking.evaluacion.estabilidad import test_retest, ari_submuestras


def test_retest_perfecto_da_uno():
    # 478.522 personas aparecen en 2024 y 2025: dos mediciones REALES de la misma
    # persona, mas fuertes que cualquier ARI de bootstrap simulado.
    df = pd.DataFrame({"id_hash": ["a","a","b","b"], "anio_valoracion": [2024,2025,2024,2025],
                       "celda": ["x","x","y","y"]})
    r = test_retest(df, "celda")
    assert r["n_personas_repetidas"] == 2 and r["acuerdo"] == 1.0


def test_retest_detecta_desacuerdo():
    df = pd.DataFrame({"id_hash": ["a","a","b","b"], "anio_valoracion": [2024,2025,2024,2025],
                       "celda": ["x","z","y","y"]})
    assert test_retest(df, "celda")["acuerdo"] == 0.5


def test_retest_ignora_a_quien_solo_aparece_una_vez():
    df = pd.DataFrame({"id_hash": ["a","a","c"], "anio_valoracion": [2024,2025,2025],
                       "celda": ["x","x","q"]})
    assert test_retest(df, "celda")["n_personas_repetidas"] == 1


def test_ari_alto_para_un_asignador_estable():
    from sintetico import generar
    df = generar(n_empresas=40, personas_por_empresa=10)
    assert ari_submuestras(df, lambda d: d["rol_verdadero"], n=5)["ari_medio"] > 0.95


def test_ari_bajo_para_un_asignador_aleatorio():
    from sintetico import generar
    df = generar(n_empresas=40, personas_por_empresa=10)
    c = {"i": 0}
    def inestable(d):
        c["i"] += 1
        return pd.Series(np.random.default_rng(c["i"]).integers(0, 3, len(d)).astype(str),
                         index=d.index)
    assert ari_submuestras(df, inestable, n=5)["ari_medio"] < 0.2
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/estabilidad.py
"""Estabilidad: test-retest real y ARI entre submuestras de empresas."""
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

SEMILLA = 20260805


def test_retest(df, col_celda, col_persona="id_hash", col_anio="anio_valoracion"):
    """Acuerdo de la celda asignada a la MISMA persona en dos anios distintos.

    Re-medicion real, no simulada. Solo entran las personas presentes en ambos anios.
    """
    d = df[[col_persona, col_anio, col_celda]].dropna()
    pares = d.sort_values(col_anio).groupby(col_persona)[col_celda].agg(list)
    pares = pares[pares.map(len) >= 2]
    if pares.empty:
        return {"n_personas_repetidas": 0, "acuerdo": float("nan")}
    return {"n_personas_repetidas": int(len(pares)),
            "acuerdo": float(pares.map(lambda v: v[0] == v[-1]).mean())}


def ari_submuestras(df, asignador, n=20, frac=0.5, semilla=SEMILLA, col_empresa="empresa_ruc"):
    """Reproducibilidad de la particion entre submuestras DE EMPRESAS.

    Es la regla con la que se elige la granularidad y la familia (D-005): nunca por
    acierto salarial.
    """
    rng = np.random.default_rng(semilla)
    empresas = np.array(sorted(df[col_empresa].unique()))
    tam = max(1, int(len(empresas) * frac))
    aris = []
    for _ in range(int(n)):
        a = set(rng.choice(empresas, tam, replace=False))
        b = set(rng.choice(empresas, tam, replace=False))
        da, db = df[df[col_empresa].isin(a)], df[df[col_empresa].isin(b)]
        comun = da.index.intersection(db.index)
        if len(comun) < 2:
            continue
        aris.append(adjusted_rand_score(asignador(da).reindex(comun).astype(str),
                                        asignador(db).reindex(comun).astype(str)))
    if not aris:
        return {"ari_medio": float("nan"), "ari_min": float("nan")}
    return {"ari_medio": float(np.mean(aris)), "ari_min": float(np.min(aris))}
```

- [ ] **Paso 4: Verificar** → 5 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/estabilidad.py tests/test_evaluacion_estabilidad.py
git commit -m "feat(evaluacion): test-retest entre anios y ARI entre submuestras"
```

---

### Tarea 12: Informe

**Archivos:** Crear `src/benchmarking/evaluacion/informe.py` · Test `tests/test_evaluacion_informe.py`

**Interfaces:** `comparar(train, test, particiones, particiones_train, n_bootstrap=1000) -> pd.DataFrame`
(columnas `metodo, n_celdas, cobertura, mae, rmse, ic_bajo, ic_alto, omega2`) ·
`tabla_texto(comp) -> str` · `guardar_curvas(curvas, ruta_png)`.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_informe.py
import numpy as np
from sintetico import generar
from benchmarking.evaluacion.splits import empresas_test, partir
from benchmarking.evaluacion.particiones import aleatoria
from benchmarking.evaluacion.informe import comparar, tabla_texto, guardar_curvas
from benchmarking.evaluacion.metricas import curva_error_cobertura


def _datos():
    df = generar(n_empresas=50, personas_por_empresa=14)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def test_comparar_una_fila_por_metodo():
    tr, ts = _datos()
    c = comparar(tr, ts,
                 {"verdadera": ts["rol_verdadero"], "azar": aleatoria(ts, 3)},
                 {"verdadera": tr["rol_verdadero"], "azar": aleatoria(tr, 3)},
                 n_bootstrap=30)
    assert list(c["metodo"]) == ["verdadera", "azar"]
    assert {"cobertura","mae","rmse","ic_bajo","ic_alto","omega2","n_celdas"} <= set(c.columns)
    assert c.loc[c.metodo=="verdadera","mae"].iloc[0] < c.loc[c.metodo=="azar","mae"].iloc[0]


def test_tabla_texto_legible():
    tr, ts = _datos()
    t = tabla_texto(comparar(tr, ts, {"v": ts["rol_verdadero"]},
                             {"v": tr["rol_verdadero"]}, n_bootstrap=10))
    assert "v" in t and "cobertura" in t.lower()


def test_guardar_curvas_escribe_png(tmp_path):
    tr, ts = _datos()
    curvas = {"v": curva_error_cobertura(tr.assign(c=tr["rol_verdadero"]),
                                         ts.assign(c=ts["rol_verdadero"]), "c")}
    guardar_curvas(curvas, tmp_path / "curva.png")
    assert (tmp_path / "curva.png").stat().st_size > 0
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/informe.py
"""Tabla comparativa y grafico de la curva error-cobertura."""
import matplotlib
matplotlib.use("Agg")                     # sin ventana: corre en job y en CI
import matplotlib.pyplot as plt
import pandas as pd
from .metricas import error_y_cobertura, ic_bootstrap_empresas, omega2_intra_empresa
from .referencia import predecir


def comparar(train, test, particiones, particiones_train, min_donantes=5,
             min_empresas=3, n_bootstrap=1000):
    filas = []
    for nombre, celdas_ts in particiones.items():
        ts = test.assign(_celda=celdas_ts.astype(str).to_numpy())
        tr = train.assign(_celda=particiones_train[nombre].astype(str).to_numpy())
        base = error_y_cobertura(ts, predecir(tr, ts, "_celda", min_donantes=min_donantes,
                                              min_empresas=min_empresas))
        ic = ic_bootstrap_empresas(tr, ts, "_celda", n=n_bootstrap,
                                   min_donantes=min_donantes, min_empresas=min_empresas)
        filas.append({"metodo": nombre, "n_celdas": int(tr["_celda"].nunique()),
                      "cobertura": base["cobertura"], "mae": base["mae"],
                      "rmse": base["rmse"], "ic_bajo": ic["ic_bajo"],
                      "ic_alto": ic["ic_alto"],
                      "omega2": omega2_intra_empresa(ts, "_celda")})
    return pd.DataFrame(filas)


def tabla_texto(comparacion):
    c = comparacion.copy()
    c["cobertura"] = (100 * c["cobertura"]).round(1).astype(str) + "%"
    for col in ("mae", "rmse", "ic_bajo", "ic_alto", "omega2"):
        c[col] = c[col].round(4)
    return c.to_string(index=False)


def guardar_curvas(curvas, ruta_png):
    """Comparar A COBERTURA IGUALADA es lo unico honesto cuando dos metodos se
    abstienen de forma distinta."""
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

- [ ] **Paso 4: Verificar** → 3 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/informe.py tests/test_evaluacion_informe.py
git commit -m "feat(evaluacion): informe con tabla y curva error-cobertura"
```

---

### Tarea 13: Subcomando `benchmarking evaluar`

**Archivos:** Modificar `src/benchmarking/cli.py` · Test: añadir a `tests/test_cli.py`

- [ ] **Paso 1: Escribir el test que falla**

```python
# anadir a tests/test_cli.py
def test_evaluar_exige_columnas_de_la_particion():
    import pandas as pd, pytest
    from benchmarking.cli import _validar_particion
    with pytest.raises(SystemExit, match="celda"):
        _validar_particion(pd.DataFrame({"id_hash": ["a"], "numero_proceso": ["P1"]}))
    _validar_particion(pd.DataFrame({"id_hash": ["a"], "numero_proceso": ["P1"], "celda": ["c"]}))
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar** — en `cli.py`, tras `_con_cache`:

```python
_COLS_PARTICION = ("id_hash", "numero_proceso", "celda")


def _validar_particion(df):
    faltan = [c for c in _COLS_PARTICION if c not in df.columns]
    if faltan:
        raise SystemExit(
            f"la particion debe tener {list(_COLS_PARTICION)}; faltan: {faltan}")
```

En `main()`, tras el parser `cu`:

```python
    ev = sub.add_parser("evaluar")
    ev.add_argument("--particion", required=True, help="parquet con id_hash, numero_proceso, celda")
    ev.add_argument("--salida", default="research/experimentos/e0_banco")
    ev.add_argument("--anios", default="2024,2025")
    ev.add_argument("--bootstrap", type=int, default=1000)
```

Y en el cuerpo, tras la rama `construir-universo`:

```python
    elif args.cmd == "evaluar":
        import pathlib
        import pandas as pd
        from .evaluacion import datos, splits, particiones, informe, metricas, embeddings

        salida = pathlib.Path(args.salida); salida.mkdir(parents=True, exist_ok=True)
        anios = tuple(int(a) for a in args.anios.split(","))

        part = pd.read_parquet(args.particion)
        _validar_particion(part)

        marco = datos.marco_evaluable(datos.agregar_objetivo(
            datos.cargar_marco(client, s.bq_project, s.bq_dataset, anios=anios), s))
        marco = marco.merge(part[list(_COLS_PARTICION)],
                            on=["id_hash", "numero_proceso"], how="inner")
        print(f"marco evaluable: {len(marco)} filas, {marco.empresa_ruc.nunique()} empresas")

        te = splits.empresas_test(marco)
        h = splits.guardar(te, salida / "empresas_test.json")
        print(f"test bloqueado: {len(te)} empresas  sha256={h[:16]}...")
        tr, ts = splits.partir(marco, te)

        k = int(marco["celda"].nunique())
        cl_emb = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                           s.vertex_location)
        emb_tr = embeddings.embeber(tr["cargo_norm"].tolist(), cl_emb, s.vertex_embedding_model)
        emb_ts = embeddings.embeber(ts["cargo_norm"].tolist(), cl_emb, s.vertex_embedding_model)

        p_ts = {"arquetipo": ts["celda"].astype(str),
                "CARGO crudo": particiones.cargo_crudo(ts),
                "aleatoria (k igualado)": particiones.aleatoria(ts, k),
                "solo-texto (k igualado)": particiones.solo_texto(ts, k, emb_ts),
                "techo supervisado": particiones.techo_supervisado(ts, k)}
        p_tr = {"arquetipo": tr["celda"].astype(str),
                "CARGO crudo": particiones.cargo_crudo(tr),
                "aleatoria (k igualado)": particiones.aleatoria(tr, k),
                "solo-texto (k igualado)": particiones.solo_texto(tr, k, emb_tr),
                "techo supervisado": particiones.techo_supervisado(tr, k)}

        comp = informe.comparar(tr, ts, p_ts, p_tr, n_bootstrap=args.bootstrap)
        comp.to_csv(salida / "comparacion.csv", index=False)
        print(informe.tabla_texto(comp))

        curvas = {n: metricas.curva_error_cobertura(
                      tr.assign(_c=p_tr[n].to_numpy()), ts.assign(_c=p_ts[n].to_numpy()), "_c")
                  for n in p_ts}
        informe.guardar_curvas(curvas, salida / "curva_error_cobertura.png")
        print(f"resultados en {salida}")
```

- [ ] **Paso 4: Verificar** — tests pasan y `python -m benchmarking.cli --help` muestra `evaluar`

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/cli.py tests/test_cli.py
git commit -m "feat(cli): subcomando evaluar"
```

---

### Tarea 14: Pre-registro

Se congela **antes** de tocar el conjunto de test. Cierra los **tres** elementos de D-005 Enmienda 1
— el plan anterior dejaba los pesos fuera, y ese fue el agujero que encontró el panel.

**Archivos:** Crear `docs/preregistro.md`

- [ ] **Paso 1: Escribir el documento**

```markdown
# Pre-registro — Sub-proyecto 1 (banco de validación)

Congelado el <FECHA>, antes de ejecutar nada contra el conjunto de test.
Commit de congelación: <HASH>. Hash sha256 del listado de empresas apartadas: <HASH_SPLIT>.

## Métrica primaria

**MAE** de `y = log(sueldo / SBU(año))` fuera de muestra. La referencia de cada persona de
test es la **mediana de los votos de empresa** de su celda, donde el voto de una empresa es
la mediana de sus personas en esa celda, **excluyendo la empresa de la persona evaluada**
(leave-company-out).

Una empresa = un voto. Ponderar por persona dejaría que un empleador grande definiera el
mercado, y el empleador explica ~39% de la varianza del salario.

Se reporta también **RMSE**, para detectar métodos que esconden fallos grandes tras un
promedio decente.

## Métrica co-primaria

**Cobertura**: fracción de personas de test con referencia. Se reporta siempre junto al
error, y la comparación entre métodos se lee **a cobertura igualada** sobre la curva.

## Regla de abstención

Menos de **5 donantes** (personas) o menos de **3 empresas** donantes → el método se
abstiene. El 5 coincide con la práctica del programa OEWS del BLS y con la supresión de
celda mínima del spec §12; el 3 evita que una sola empresa defina la referencia. La curva
barre 8 umbrales (1, 2, 3, 5, 8, 12, 20, 30), así que ninguna conclusión depende del valor.

## Criterio de éxito

**Éxito = A o B.**

- **A**: a cobertura igualada, el arquetipo tiene MAE menor que `CARGO`, con el IC de la
  diferencia sin cruzar el cero.
- **B**: MAE equivalente, pero cobertura sustancialmente mayor.
- **C** (complementariedad) **se reporta como hallazgo, no como victoria**.
- **D** (no gana en ningún lado) se reporta como resultado negativo.

## Regla de selección de modelo — los tres elementos

Ninguno de estos tres se elige con la métrica salarial:

1. **Granularidad** (k, altura de corte, tamaño mínimo de grupo) → por **estabilidad**: ARI
   entre submuestras de empresas.
2. **Familia** de clustering → por **estabilidad**, igual.
3. **Pesos de bloque** → **no se eligen**. Se aplica normalización MFA (cada bloque dividido
   por su primer valor singular), que no tiene parámetros libres.

El **techo supervisado** se reporta siempre: fija la escala y actúa como alarma si el
arquetipo se le acerca. El **test de validez externa** (predecir ISCO-08) comprueba que las
celdas son ocupaciones y no bandas de sueldo.

## Incertidumbre

Intervalos por bootstrap de **empresas** con reemplazo, 1.000 réplicas. Nunca por filas.

## Conjunto de test

20% de las empresas, estratificado por segmento SCVS y sección CIIU, con mínimo una empresa
por estrato, semilla 20260805. Bloqueado hasta la validación final; su identidad queda
fijada por el hash de arriba.
```

- [ ] **Paso 2: Commit**

```bash
git add docs/preregistro.md
git commit -m "docs: pre-registro del banco, congelado antes del test"
```

---

### Tarea 15: Los dos baselines (experimento E0)

Estrena el banco y responde en la semana ~4 si la composición aporta (enmienda de D-003).

**Archivos:** Crear `research/experimentos/e0_banco/construir_baselines.py` y su `README.md`

- [ ] **Paso 1: Escribir el script**

```python
# research/experimentos/e0_banco/construir_baselines.py
"""E0 — dos baselines de k-means para estrenar el banco y medir si la composicion aporta.

Baseline A: con composicion, sobre 2024-2025.
Baseline B: sin composicion (texto + centro + antiguedad), sobre todos los anios.

Ambos se evaluan sobre el MISMO held-out. Si B iguala o supera a A, la composicion no
aporta y media arquitectura del spec de clustering (ILR, gate, residualizacion, IPW) se
puede retirar CON EVIDENCIA.

Dos reglas que vienen del pre-registro y no se negocian:
- El salario NO entra en ningun vector.
- k se elige por ESTABILIDAD (ARI entre submuestras de empresas), nunca por acierto
  salarial. Los bloques se normalizan con MFA, sin pesos que afinar.
"""
import argparse
import pathlib
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.cluster import MiniBatchKMeans
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, estabilidad
from benchmarking.evaluacion.representacion import normalizar_mfa

SEMILLA = 20260805
REJILLA_K = (20, 30, 40, 50, 70, 100)


def _bloques_a(df):
    """Composicion (4 proporciones) + antiguedad."""
    comp = df[["pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]]
    comp = comp.fillna(comp.median(numeric_only=True)).to_numpy(float)
    ant = df[["antiguedad_total"]].fillna(df["antiguedad_total"].median()).to_numpy(float)
    return [comp, ant]


def _bloques_b(df, emb):
    """Sin composicion: texto + antiguedad."""
    ant = df[["antiguedad_total"]].fillna(df["antiguedad_total"].median()).to_numpy(float)
    return [np.asarray(emb, dtype=float), ant]


def elegir_k(df, X, rejilla=REJILLA_K):
    """k por estabilidad: gana el que mas se reproduce entre submuestras de empresas."""
    mejor, mejor_ari = None, -1.0
    for k in rejilla:
        def asignar(sub):
            idx = df.index.get_indexer(sub.index)
            km = MiniBatchKMeans(n_clusters=k, random_state=SEMILLA, n_init=10)
            return pd.Series(km.fit_predict(X[idx]).astype(str), index=sub.index)
        ari = estabilidad.ari_submuestras(df, asignar, n=5, frac=0.5)["ari_medio"]
        print(f"   k={k:>3}  ARI={ari:.3f}")
        if ari > mejor_ari:
            mejor, mejor_ari = k, ari
    print(f"   -> elegido k={mejor} (ARI={mejor_ari:.3f})")
    return mejor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="research/experimentos/e0_banco")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    salida = pathlib.Path(args.salida); salida.mkdir(parents=True, exist_ok=True)
    cl_emb = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)

    print("== Baseline A: con composicion, 2024-2025 ==")
    ab = datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025))
    ab = ab[ab["tiene_composicion"]].reset_index(drop=True)
    Xa = normalizar_mfa(_bloques_a(ab))
    ka = elegir_k(ab, Xa)
    ab["celda"] = MiniBatchKMeans(n_clusters=ka, random_state=SEMILLA,
                                  n_init=10).fit_predict(Xa).astype(str)
    ab[["id_hash", "numero_proceso", "celda"]].to_parquet(salida / "baseline_a.parquet",
                                                          index=False)

    print("\n== Baseline B: sin composicion, todos los anios ==")
    todos = datos.cargar_marco(cl, s.bq_project, s.bq_dataset,
                               anios=(2019, 2020, 2021, 2022, 2023, 2024, 2025))
    todos = todos.reset_index(drop=True)
    texto = (todos["cargo_norm"].astype(str) + " " +
             todos["centro_de_costo"].astype(str)).tolist()
    emb = embeddings.embeber(texto, cl_emb, s.vertex_embedding_model)
    Xb = normalizar_mfa(_bloques_b(todos, emb))
    kb = elegir_k(todos, Xb)
    todos["celda"] = MiniBatchKMeans(n_clusters=kb, random_state=SEMILLA,
                                     n_init=10).fit_predict(Xb).astype(str)
    todos[["id_hash", "numero_proceso", "celda"]].to_parquet(salida / "baseline_b.parquet",
                                                             index=False)

    print(f"\nA: {len(ab)} filas, k={ka}    B: {len(todos)} filas, k={kb}")


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
   spec de clustering se puede retirar con evidencia.

## Cómo se corre

```bash
python research/experimentos/e0_banco/construir_baselines.py
benchmarking evaluar --particion research/experimentos/e0_banco/baseline_a.parquet --salida research/experimentos/e0_banco/a
benchmarking evaluar --particion research/experimentos/e0_banco/baseline_b.parquet --salida research/experimentos/e0_banco/b
```

## Cómo se lee

La comparación honesta es **a cobertura igualada**, sobre la curva. Ninguno de los dos
baselines pretende ser el modelo bueno: son la vara contra la que se medirá el
sub-proyecto 2.

Recordatorio del pre-registro: **k se eligió por estabilidad, no por resultado salarial**, y
los bloques se normalizaron con MFA, sin pesos afinados.
```

- [ ] **Paso 3: Commit**

```bash
git add research/experimentos/e0_banco
git commit -m "feat(research): E0 — dos baselines con MFA y k por estabilidad"
```

---

### Tarea 16: Medir la ruta de servicio

Corrección 6 de D-009. El spec §12 promete mapeo online por título y departamento **sin** composición
del cliente. Si eso es cierto, lo que se vende es un **clasificador de texto**, no el clusterer. Si
el título predice el arquetipo al 85%, el clustering fue una forma cara de construir una taxonomía
de texto; si al 40%, el producto no se puede servir. **Hoy no está en ninguna métrica.**

**Archivos:** Crear `research/experimentos/e0_banco/ruta_servicio.py`

- [ ] **Paso 1: Escribir el script**

```python
# research/experimentos/e0_banco/ruta_servicio.py
"""¿Se puede servir el arquetipo con lo que un cliente nuevo SI tiene?

En produccion el cliente aporta titulo, departamento y antiguedad — no composicion. Si el
arquetipo no se puede predecir desde eso, el producto del spec 12 no existe.

Se entrena sobre empresas de train y se mide sobre empresas held-out: la misma frontera
que usa el banco, por la misma razon.
"""
import argparse
import pathlib
import pandas as pd
from google.cloud import bigquery
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, top_k_accuracy_score
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, embeddings, splits
from benchmarking.evaluacion.representacion import normalizar_mfa

SEMILLA = 20260805


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--particion", required=True)
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    marco = datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s)
    part = pd.read_parquet(args.particion)
    marco = marco.merge(part, on=["id_hash", "numero_proceso"], how="inner").reset_index(drop=True)

    cl_emb = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    texto = (marco["cargo_norm"].astype(str) + " " +
             marco["centro_de_costo"].astype(str)).tolist()
    emb = embeddings.embeber(texto, cl_emb, s.vertex_embedding_model)
    ant = marco[["antiguedad_total"]].fillna(marco["antiguedad_total"].median()).to_numpy(float)
    X = normalizar_mfa([emb, ant])

    te = splits.empresas_test(marco)
    en_test = marco["empresa_ruc"].isin(te).to_numpy()
    y = marco["celda"].astype(str).to_numpy()

    modelo = LogisticRegression(max_iter=1000, n_jobs=-1, random_state=SEMILLA)
    modelo.fit(X[~en_test], y[~en_test])
    proba = modelo.predict_proba(X[en_test])

    print(f"personas de test: {int(en_test.sum())}   arquetipos: {len(modelo.classes_)}")
    print(f"acierto top-1 : {accuracy_score(y[en_test], modelo.predict(X[en_test])):.3f}")
    print(f"acierto top-3 : {top_k_accuracy_score(y[en_test], proba, k=3, labels=modelo.classes_):.3f}")
    print("\nLectura: >0,80 en top-1 significa que el titulo casi determina el arquetipo, "
          "y hay que preguntarse que aporto el clustering. <0,50 significa que el producto "
          "del spec 12 no se puede servir sin pedirle composicion al cliente.")


if __name__ == "__main__":
    main()
```

- [ ] **Paso 2: Commit**

```bash
git add research/experimentos/e0_banco/ruta_servicio.py
git commit -m "feat(research): medir la ruta de servicio titulo -> arquetipo"
```

---

### Tarea 17: Verificación final

- [ ] **Paso 1: Toda la suite en verde** — `.venv\Scripts\python.exe -m pytest -q`
  Esperado: los 63 previos más ~45 nuevos.

- [ ] **Paso 2: La prueba de aceptación, explícita** —
  `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_banco.py -v` → 5 passed.
  Es la que autoriza a fiarse de las mediciones.

- [ ] **Paso 3: Sin data real en el repositorio** —
  `git log --stat -25 | grep -iE "\.parquet|\.csv|\.xlsx" || echo "sin data real"`

- [ ] **Paso 4: Commit final**

```bash
git commit --allow-empty -m "chore: sub-proyecto 1 completo — banco de validacion operativo"
```

---

## Qué queda fuera, y a dónde va

| Fuera de este plan | Sub-proyecto |
|---|---|
| Residualización contra empleador×sector, ILR, gate de masa fija | 2 |
| IPW para el sesgo de selección del ajuste | 2 |
| Modelo de nivel — **sin `edad`**, anclado al *work level* del NCS | 3 |
| GMM, HDBSCAN, jerárquico y la selección por estabilidad | 4 |
| Etiquetado LLM y mapeo ISCO-08 | 5 |
| Referencia ISCO desde el catálogo sectorial del MDT | 5 (empezar antes: hay que parsear 249 pp.) |
| Must-links y cannot-links | opcional — dejó de ser cimiento al resolverse los pesos con MFA (D-010) |

## Correcciones de D-009 que este plan NO cubre

Se registran aquí para que no se pierdan:

- **Corrección 5** — escribir el enmarque de novedad frente a Job2Vec, Djumalieva y TWICE. Es texto
  de tesis; el material está en `estado_del_arte.md` §1.
- **Corrección 7** — sacar `edad` del modelo de nivel. Es del sub-proyecto 3.
- Acotar la afirmación central a *"el `CARGO` **tal como se captura en estudios actuariales
  ecuatorianos** no sirve"* (Torres et al. 2018).
- Cuantificar el sesgo de movilidad limitada sobre el η²_empresa.
