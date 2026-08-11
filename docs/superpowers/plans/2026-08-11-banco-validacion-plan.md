# Banco de validación y baseline — Plan de implementación (v3)

> **Para trabajadores agénticos:** SUB-SKILL REQUERIDO: usar `superpowers:subagent-driven-development`
> (recomendado) o `superpowers:executing-plans`, tarea por tarea. Los pasos usan casillas (`- [ ]`).
>
> **v3 (2026-08-11)** reescribe las tareas 4, 5, 6, 9, 12, 14 y 15 tras la auditoría de métricas
> (**D-011**). Las tareas 1, 2, 3, 7, 8, 11, 13, 16 y 17 no cambian; 10 se amplía.
> Contexto obligatorio antes de ejecutar: [`../../registro_decisiones.md`](../../registro_decisiones.md)
> (leer **D-011 entero**) y [`../../revision_jueces.md`](../../revision_jueces.md) §10–13.

**Objetivo:** construir el instrumento que mide si una forma de agrupar personas predice el salario
mejor que la etiqueta `CARGO`, y estrenarlo con dos baselines.

**El invariante del diseño:** el banco **no mide modelos, mide particiones**. Todos los competidores
comparten el mismo estimador y el mismo split; lo único que cambia entre ellos es cómo se agrupa a la
gente. Sin esto, una diferencia sería atribuible al estimador, al split o al agrupamiento, y no habría
forma de saber a cuál. Cualquier cambio al estimador se aplica **a todos los rivales a la vez**.

**Arquitectura:** un paquete `src/benchmarking/evaluacion/` de módulos con responsabilidad única,
encadenados por DataFrames. Flujo: cargar marco → partir empresas → construir particiones rivales →
estimar la **distribución predictiva** de cada celda con votos ponderados por precisión → puntuar
error, cobertura y riesgo generalizado → informar. Un subcomando `benchmarking evaluar` lo orquesta.
Todo se prueba con data sintética de estructura conocida.

**Stack:** Python 3.11, pandas, numpy, scikit-learn, matplotlib, Vertex AI (embeddings), pytest.

## Restricciones globales

- **Frontera de privacidad:** nada aguas abajo de `anonimizacion` ve identificadores. El banco
  trabaja con `id_hash`. Data real nunca al repositorio.
- **Unidad estadística = empresa.** Splits, remuestreos y **la referencia salarial** son por
  `empresa_ruc`, nunca por fila.
- **Anti-circularidad:** el salario no entra jamás como característica de agrupamiento. Granularidad,
  familia **y pesos** se eligen sin la métrica salarial (D-005 Enmienda 1, los tres elementos).
- **`sexo` nunca es feature.** Se carga sólo para auditar la regla de abstención y para el Oaxaca.
- **El 20% de test se toca una vez, al final.** Ninguna decisión —ni A vs B, ni k, ni el umbral de
  abstención— se resuelve mirándolo. Lo que haya que decidir se decide en CV agrupada por empresa
  **dentro del train**.
- **Determinismo:** semilla del proyecto `20260805`, fija y explícita en cada punto aleatorio.
- Tabla origen: `act-cicd-stage-prueba.benchmarking_tesis.nomina_features`.

## Cinco trampas que este plan evita

**1. `sueldo_sbu` no es `sueldo/SBU`.** En `features_base.py:28` vale `total / SBU`. Quien la use por
su nombre medirá otra cosa. El objetivo se calcula explícitamente (Tarea 2).

**2. El estimador no estimaba lo que la métrica puntuaba.** La mediana de medianas de empresa estima
la paga del *empleador típico*; el MAE se mide contra personas. Se sustituye por el **cuantil
ponderado inverso-varianza** (Tarea 4) — D-011, bloqueante. Nótese que esto **fortalece a `CARGO`**,
porque el encogimiento ayuda más donde las celdas son pequeñas.

**3. El emparejamiento de texto por caracteres invierte la jerarquía.** Medido sobre datos propios:
`AUXILIAR DE SERVICIOS GENERALES → JEFE DE SERVICIOS GENERALES` con similitud 0,79. Por eso el nulo
solo-texto usa **embeddings**, no TF-IDF (Tarea 7).

**4. La curva error-cobertura era un punto.** Barrer `min_donantes` no recorta nada cuando la celda
media tiene ~26.000 donantes. Se barre el **coste de abstenerse** y se compara por riesgo generalizado
con denominador `N` fijo (Tarea 5).

**5. El techo estaba ajustado sobre el test.** k-means sobre `y` de todo el df daba un MAE de ~0,03,
inalcanzable por construcción, y mataba la alarma anti-circularidad. Se separa en **techo alcanzable**
(entrenado en train, es el denominador) y **oráculo** (bandera roja, nunca denominador) — Tarea 9.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/benchmarking/evaluacion/datos.py` | leer el marco y calcular la variable objetivo |
| `src/benchmarking/evaluacion/splits.py` | partir empresas estratificado, con persistencia y hash |
| `src/benchmarking/evaluacion/referencia.py` | componentes de varianza, votos ponderados, predictiva, abstención |
| `src/benchmarking/evaluacion/metricas.py` | MAE, sesgo, MAE intra-empresa, CRPS, riesgo generalizado, AUGRC, ω², bootstrap pareado |
| `src/benchmarking/evaluacion/embeddings.py` | embeddings de Vertex con caché por revisión de modelo |
| `src/benchmarking/evaluacion/particiones.py` | los rivales de la escalera, el techo y el oráculo |
| `src/benchmarking/evaluacion/representacion.py` | normalización MFA de bloques |
| `src/benchmarking/evaluacion/estabilidad.py` | test-retest y ARI entre submuestras |
| `src/benchmarking/evaluacion/informe.py` | tabla comparativa pareada, curvas y desglose por subgrupo |
| `tests/sintetico.py` | generador con respuesta conocida |
| `docs/preregistro.md` | documento congelado |

## Qué se mide, y por qué cada uno

Seis particiones evaluadas más una bandera roja. Todas con **el mismo estimador**.

| Partición | La pregunta que contesta | Qué pasa si pierdo contra ella |
|---|---|---|
| **Aleatoria** (k igualado) | ¿aporta algo la información? | el banco está roto, o el objetivo no tiene señal |
| **CARGO crudo** (sin podar, D-005) | ¿supero lo que se usa hoy? | **la tesis no tiene tesis** |
| **CARGO ingenuo** (mediana simple) | ablación: ¿cuánto del resultado es partición y cuánto estimador? | — |
| **Solo texto** (embeddings, k igualado) | ¿la composición aporta más allá del nombre del puesto? | sobra medio proyecto: bastaba leer el título |
| **Arquetipo** (rol-familia × nivel) | el candidato | — |
| **Techo alcanzable** (GBM sobre observables, train) | ¿cuánto es lo máximo con estos datos? | nada: fija la escala |
| **Oráculo** (k-means sobre `y`, sólo train) | **alarma**, no denominador | si el arquetipo se le acerca → derivó a bandas salariales |

La aleatoria no es trivial: es lo que detecta el artefacto de la masa en el SBU (Tarea 2b). El
solo-texto es el rival difícil y hace dos trabajos — aísla la contribución de la composición **e
iguala la cardinalidad**, que es la primera objeción previsible del tribunal.

En un eje aparte, los **baselines A y B** (Tarea 15) no son rivales: son la bifurcación de
arquitectura de D-003, y se deciden dentro del train.

---

### Tarea 1: Generador de data sintética — ✅ HECHA (`d31d89c`)

> Lo implementado difiere del bloque de abajo en un punto, y el motivo importa: el plan proponía
> `nivel_empresa` con sd 0,35, que daba η²_empresa de 0,46–0,61 frente al **0,388 real**. Data
> sintética más fácil que la realidad justo en el eje que el leave-company-out neutraliza. Recalibrado
> a **0,24** → media 0,373 sobre 16 combinaciones semilla × n_roles, y el test fija la banda.

**Archivos:** Crear `tests/sintetico.py` · Test `tests/test_sintetico.py`

**Interfaces:** produce `generar(n_empresas=40, personas_por_empresa=25, n_roles=3, semilla=20260805)
-> pd.DataFrame` con `id_hash, empresa_ruc, numero_proceso, anio_valoracion, rol_verdadero, cargo,
cargo_norm, sueldo, pct_*, antiguedad_total, segmento, ciiu_n1, provincia, en_clean,
tiene_composicion`.

- [x] **Paso 1: Escribir el test que falla**

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

- [x] **Paso 2: Ejecutar y verificar que falla**

`.venv\Scripts\python.exe -m pytest tests/test_sintetico.py -v` → `ModuleNotFoundError: sintetico`

- [x] **Paso 3: Implementar**

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

- [x] **Paso 4: Permitir importar `sintetico`** — en `pyproject.toml`:
`pythonpath = ["src", "tests"]`

- [x] **Paso 5: Verificar** → 5 passed

- [x] **Paso 6: Commit**

```bash
git add tests/sintetico.py tests/test_sintetico.py pyproject.toml
git commit -m "test: generador de data sintetica con rol conocido"
```

---

### Tarea 2: Carga del marco y variable objetivo — ✅ HECHA (`27fe3e4`, `af0c49e`)

> **Añadido en v3:** `sexo` entra en `SQL_MARCO`, con un test que exige los cuatro ejes de subgrupo
> (`sexo`, `provincia`, `segmento`, `ciiu_n1`). Sin ellos la regla de abstención queda sin auditar y
> puede degradar la referencia justo para quien más la necesita (D-011). **Nunca es feature.**

**Archivos:** Crear `src/benchmarking/evaluacion/{__init__,datos}.py` · Test `tests/test_evaluacion_datos.py`

**Interfaces:** `SQL_MARCO`, `cargar_marco(runner, proyecto, dataset, anios=(2024,2025))`,
`agregar_objetivo(df, settings)` (añade `y`), `marco_evaluable(df)`.

- [x] **Paso 1: Escribir el test que falla**

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

- [x] **Paso 2: Verificar que falla** → `ModuleNotFoundError: benchmarking.evaluacion`

- [x] **Paso 3: Implementar**

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

- [x] **Paso 4: Verificar** → 4 passed

- [x] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion tests/test_evaluacion_datos.py
git commit -m "feat(evaluacion): carga del marco y objetivo log(sueldo/SBU)"
```

---

### Tarea 2b: Diagnóstico del objetivo — la masa en el SBU (NUEVA, v3)

Va antes que todo lo demás porque **puede invalidar el piso de la escalera**, y cuesta una consulta.

`sueldo_bajo_sbu` está en cuarentena, así que `y = log(sueldo/SBU) ≥ 0` está **censurada por abajo con
masa puntual en cero**. Si esa masa supera el 50% en muchas celdas, la mediana de casi cualquier celda
vale 0 — incluida la de la partición aleatoria — y el piso sube hasta tocar al arquetipo. El banco
mediría un artefacto de censura y lo llamaría señal.

**Archivos:** Crear `research/experimentos/e0_banco/diagnostico_objetivo.py`

- [ ] **Paso 1: Escribir el script**

```python
# research/experimentos/e0_banco/diagnostico_objetivo.py
"""Diagnostico del objetivo antes de construir nada encima.

Tres preguntas, una consulta:
  1. Que fraccion de `y` esta exactamente en 0 (sueldo == SBU)?
  2. Como se reparte esa masa entre celdas de CARGO?
  3. Cuantas personas tiene la celda tipica de CARGO en el marco evaluable?

Si la respuesta a (1) es alta, el piso de la escalera es un artefacto de censura y hay
que decidir —ANTES de mirar el test— si la metrica primaria se mide sobre el subconjunto
no censurado, o si se adopta un tratamiento censurado explicito.
"""
import argparse
import numpy as np
import pandas as pd
from google.cloud import bigquery
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anios", default="2024,2025")
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    anios = tuple(int(a) for a in args.anios.split(","))
    m = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=anios), s))

    y = m["y"].to_numpy(float)
    en_cero = np.isclose(y, 0.0, atol=1e-9)
    print(f"filas evaluables      : {len(m):,}")
    print(f"y == 0 (sueldo == SBU): {en_cero.mean():.1%}")
    print(f"cuantiles de y        : {np.percentile(y, [1, 10, 25, 50, 75, 90, 99]).round(3)}")

    por_celda = m.assign(_c=en_cero).groupby("cargo_norm")["_c"].agg(["mean", "size"])
    grandes = por_celda[por_celda["size"] >= 5]
    print(f"\nceldas de CARGO con >=5 personas: {len(grandes):,}")
    print(f"  ...de ellas, con >50% en el SBU: {(grandes['mean'] > 0.5).mean():.1%}")

    tam = m.groupby("cargo_norm").size()
    emp = m.groupby("cargo_norm")["empresa_ruc"].nunique()
    print(f"\ntamano de celda CARGO   mediana={tam.median():.0f}  p90={tam.quantile(.9):.0f}")
    print(f"empresas por celda      mediana={emp.median():.0f}  p90={emp.quantile(.9):.0f}")
    print(f"celdas con >=3 empresas : {(emp >= 3).mean():.1%}")

    print("\nLECTURA: si >50% de las celdas grandes tienen mas de la mitad de su gente en el "
          "SBU, la mediana de casi cualquier particion vale 0 y el piso de la escalera es "
          "un artefacto. Decidir el tratamiento AQUI, y escribirlo en el pre-registro.")


if __name__ == "__main__":
    main()
```

- [ ] **Paso 2: Correrlo y anotar los números en `docs/mediciones.md`**, con fecha y alcance.

- [ ] **Paso 3: Si la masa en cero supera el 30%**, parar y decidir el tratamiento antes de seguir.
Opciones, por orden de preferencia: (a) reportar la métrica primaria sobre `y > 0` y la cobertura
sobre el total, declarándolo en el pre-registro; (b) usar CRPS con predictiva censurada. **No** se
elige mirando cuál favorece al arquetipo.

- [ ] **Paso 4: Commit**

```bash
git add research/experimentos/e0_banco/diagnostico_objetivo.py docs/mediciones.md
git commit -m "feat(research): diagnostico del objetivo — masa en el SBU y tamano de celda"
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

### Tarea 4: Referencia salarial — votos ponderados y distribución predictiva

El corazón del banco. **Reescrita en v3** por D-011: el estimador anterior (mediana simple de las
medianas de empresa) estimaba la paga del *empleador típico*, mientras el MAE se mide contra personas.

**Archivos:** Crear `src/benchmarking/evaluacion/referencia.py` · Test `tests/test_evaluacion_referencia.py`

**Interfaces:**
`componentes_varianza(train, col_celda) -> (tau2, sigma2)` ·
`pesos_empresa(n, tau2, sigma2)` ·
`cuantil_ponderado(valores, pesos, q=0.5)` ·
`predecir(train, test, col_celda, tau2=None, sigma2=None) -> pd.DataFrame` con
`y_ref_bruto`, `sd_pred`, `n_donantes`, `n_empresas_donantes`, `share_max_empresa` ·
`aplicar_abstencion(pred, max_sd=None, min_empresas=3, share_max=0.8) -> pd.Series`

**El modelo.** Por celda `c`, sobre `y = log(sueldo/SBU)`:

```
y_fi = mu_c + a_f + e_fi        a_f ~ (0, tau^2)      e_fi ~ (0, sigma^2)
```

`tau^2` = varianza **entre** empresas dentro de celda (el efecto empleador). `sigma^2` = varianza
**intra** empresa dentro de celda. Se estiman **una sola vez, globalmente** — no por celda —, por el
mismo argumento con el que D-006 #3 descartó el modelo mixto para ω²: con el 76,6% de la gente en
empresas de ≥100, el encogimiento es estable.

**El peso del voto de cada empresa** es inverso-varianza y **derivado, no elegido**:

```
w_f = 1 / (tau^2 + sigma^2 / n_f)
```

| Régimen | `w_f` tiende a | Equivale a |
|---|---|---|
| `n_f` grande | `1/tau^2`, igual para todas | una empresa, un voto (D-009 corrección 1) |
| `tau^2 → 0` | `n_f/sigma^2` | una persona, un voto (lo anterior a D-009) |

El **ratio máximo de pesos está acotado por `1 + sigma^2/tau^2`**, no por 3.000. Ahí muere la
dominancia del empleador grande sin tener que tirar el voto de las empresas pequeñas.

**La distribución predictiva.** Como el split es por empresa, la empresa de test **nunca** está en
train: el objetivo es `y = mu_c + a_nueva + e`, luego

```
sd_pred = raiz( tau^2 + sigma^2 + 1/suma(w_f) )
```

Los dos primeros términos son irreducibles (la empresa nueva y la persona nueva); el tercero es el
error de estimación de `mu_c`, y **es el único que mejora con más donantes**. Esa es la perilla de
confianza correcta: un conteo de donantes no dice nada sobre la precisión — 500 personas de 3 empresas
homogéneas dan una referencia mejor que 20 personas de 10 empresas dispares.

**Dos separaciones deliberadas de responsabilidad:**

1. `predecir` **no aplica la abstención**. Devuelve la referencia bruta y su anchura. La abstención es
   `aplicar_abstencion`, una función pura sobre esa tabla. Así la curva de la Tarea 5 barre el umbral
   **sin recalcular nada**, que era una de las razones por las que la curva vieja costaba tanto.
2. Los **suelos** (≥3 empresas, ninguna >80%) no son criterios de precisión: son identificabilidad de
   `tau^2` y confidencialidad. Precedente: la regla de supresión de QCEW. Van aparte del umbral de
   anchura para que quede claro en el pre-registro que hacen cosas distintas.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_referencia.py
import numpy as np, pandas as pd
from benchmarking.evaluacion.referencia import (
    componentes_varianza, pesos_empresa, cuantil_ponderado, predecir, aplicar_abstencion)


def _m(filas):
    return pd.DataFrame(filas, columns=["empresa_ruc", "celda", "y"])


def _pred(train, test, **kw):
    p = predecir(train, test, "celda", **kw)
    return p.assign(y_ref=aplicar_abstencion(p))


# --- componentes de varianza -------------------------------------------------

def test_componentes_recuperan_las_varianzas_conocidas():
    # Se construye con tau=0,4 y sigma=0,2 y se comprueba que el estimador de momentos
    # los recupera. Si esto falla, TODOS los pesos estan mal y no lo veriamos en ningun
    # otro test: los pesos solo se notan en el tercer decimal del resultado final.
    rng = np.random.default_rng(7)
    filas = []
    for c in range(6):
        for f in range(40):
            a = rng.normal(0, 0.4)
            for i in range(12):
                filas.append((f"E{c}_{f}", f"c{c}", 2.0 + a + rng.normal(0, 0.2)))
    tau2, sigma2 = componentes_varianza(_m(filas), "celda")
    assert abs(np.sqrt(tau2) - 0.4) < 0.06, f"tau={np.sqrt(tau2):.3f}"
    assert abs(np.sqrt(sigma2) - 0.2) < 0.02, f"sigma={np.sqrt(sigma2):.3f}"


def test_sin_efecto_empresa_tau2_es_cero():
    rng = np.random.default_rng(3)
    filas = [(f"E{f}", "c", rng.normal(0, 0.3)) for f in range(50) for _ in range(10)]
    tau2, sigma2 = componentes_varianza(_m(filas), "celda")
    assert tau2 < 0.01 and abs(np.sqrt(sigma2) - 0.3) < 0.03


# --- pesos -------------------------------------------------------------------

def test_los_pesos_interpolan_entre_las_dos_posturas():
    # n grande -> todas pesan igual (una empresa, un voto).
    w = pesos_empresa([1000, 3000], tau2=0.16, sigma2=0.04)
    assert abs(w[0] / w[1] - 1.0) < 0.01
    # tau2 -> 0 -> el peso es proporcional a n (una persona, un voto).
    w = pesos_empresa([1, 10], tau2=1e-12, sigma2=0.04)
    assert abs(w[1] / w[0] - 10.0) < 0.01


def test_el_ratio_de_pesos_esta_acotado():
    # ESTE es el punto de D-011: una empresa de 3.000 no puede pesar 3.000 veces mas
    # que una de 1. La cota es 1 + sigma2/tau2, aqui 1 + 0.04/0.16 = 1,25.
    tau2, sigma2 = 0.16, 0.04
    w = pesos_empresa([1, 3000], tau2, sigma2)
    assert w[1] / w[0] <= 1.0 + sigma2 / tau2 + 1e-9
    assert w[1] / w[0] > 1.0                      # pero sigue premiando a la mas precisa


# --- cuantil ponderado -------------------------------------------------------

def test_con_pesos_iguales_es_la_mediana():
    for v in ([1., 2., 3., 4., 5.], [1., 2., 3., 4.]):
        assert abs(cuantil_ponderado(v, np.ones(len(v))) - float(np.median(v))) < 1e-9


def test_el_peso_desplaza_el_cuantil():
    v = [1.0, 10.0]
    assert cuantil_ponderado(v, [1.0, 99.0]) > 9.0
    assert cuantil_ponderado(v, [99.0, 1.0]) < 2.0


def test_cuantil_ponderado_ignora_pesos_nulos_y_nan():
    assert abs(cuantil_ponderado([1., 5., np.nan], [1., 1., 1.]) - 3.0) < 1e-9
    assert abs(cuantil_ponderado([1., 5., 99.], [1., 1., 0.]) - 3.0) < 1e-9
    assert np.isnan(cuantil_ponderado([], []))


# --- prediccion --------------------------------------------------------------

def test_excluye_la_propia_empresa():
    # El efecto empresa explica ~39% de la varianza: usar a los companeros seria acertar
    # por la razon equivocada.
    train = _m([("E1", "c", 10.0)] * 3 + [(f"E{i}", "c", 1.0) for i in range(2, 8)])
    out = _pred(train, _m([("E1", "c", 10.0)]))
    assert abs(out["y_ref"].iloc[0] - 1.0) < 1e-9


def test_una_empresa_grande_no_define_el_mercado():
    # La correccion 1 de D-009 SIGUE vigente con los pesos nuevos: E1 aporta 100 personas
    # a 5.0 y las otras cinco una a 1.0. Su peso es como mucho 1+sigma2/tau2 veces mayor.
    train = _m([("E1", "c", 5.0)] * 100 + [(f"E{i}", "c", 1.0) for i in range(2, 8)])
    out = _pred(train, _m([("E9", "c", 1.0)]))
    assert abs(out["y_ref"].iloc[0] - 1.0) < 0.2, "un empleador grande no es el mercado"
    assert out["n_empresas_donantes"].iloc[0] == 7


def test_la_mediana_de_una_empresa_resume_a_sus_personas():
    train = _m([("E1", "c", 1.0), ("E1", "c", 3.0), ("E1", "c", 5.0)] +
               [(f"E{i}", "c", 100.0) for i in range(2, 7)])
    out = _pred(train, _m([("E9", "c", 0.0)]))
    assert out["y_ref"].iloc[0] > 50.0        # el voto de E1 es 3.0, y es 1 de 6


def test_mas_empresas_donantes_estrechan_la_predictiva():
    # La anchura predictiva es la perilla de confianza: tiene que MEJORAR con la evidencia.
    rng = np.random.default_rng(11)
    pocas = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(4) for _ in range(5)])
    muchas = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(60) for _ in range(5)])
    t = _m([("EX", "c", 2.0)])
    assert predecir(muchas, t, "celda")["sd_pred"].iloc[0] < \
           predecir(pocas, t, "celda")["sd_pred"].iloc[0]


def test_la_predictiva_no_baja_del_ruido_irreducible():
    # Ni con infinitos donantes: la empresa nueva y la persona nueva no se pueden predecir.
    rng = np.random.default_rng(5)
    tr = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(400) for _ in range(8)])
    tau2, sigma2 = componentes_varianza(tr, "celda")
    sd = predecir(tr, _m([("EX", "c", 2.0)]), "celda")["sd_pred"].iloc[0]
    assert sd >= np.sqrt(tau2 + sigma2) - 1e-9


# --- abstencion --------------------------------------------------------------

def test_suelo_de_empresas():
    out = _pred(_m([("E2", "c", 1.0)] * 9 + [("E3", "c", 1.0)] * 9), _m([("E1", "c", 1.0)]))
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_empresas_donantes"].iloc[0] == 2


def test_suelo_de_dominancia():
    # e>=3 NO impide que una empresa con el 95% de la gente domine. La regla de share si.
    train = _m([("E1", "c", 5.0)] * 95 + [("E2", "c", 1.0), ("E3", "c", 1.0)])
    out = _pred(train, _m([("E9", "c", 1.0)]))
    assert pd.isna(out["y_ref"].iloc[0])
    assert out["share_max_empresa"].iloc[0] > 0.8
    # sin el suelo de dominancia si responde
    p = predecir(train, _m([("E9", "c", 1.0)]), "celda")
    assert not pd.isna(aplicar_abstencion(p, share_max=1.01).iloc[0])


def test_umbral_de_anchura():
    rng = np.random.default_rng(2)
    tr = _m([(f"E{i}", "c", float(rng.normal(2, .3))) for i in range(20) for _ in range(6)])
    p = predecir(tr, _m([("EX", "c", 2.0)]), "celda")
    assert pd.isna(aplicar_abstencion(p, max_sd=0.01).iloc[0])
    assert not pd.isna(aplicar_abstencion(p, max_sd=99.0).iloc[0])


def test_se_abstiene_en_celda_no_vista():
    out = _pred(_m([(f"E{i}", "c", 1.0) for i in range(2, 12)]), _m([("E1", "otra", 1.0)]))
    assert pd.isna(out["y_ref"].iloc[0]) and out["n_donantes"].iloc[0] == 0


def test_una_celda_por_persona_no_predice_nada():
    # La trampa que la balanza debe castigar: partir de mas deja los cajones vacios.
    train = pd.DataFrame({"empresa_ruc": [f"E{i}" for i in range(20)],
                          "celda": [f"c{i}" for i in range(20)],
                          "y": np.linspace(0, 2, 20)})
    out = _pred(train, pd.DataFrame({"empresa_ruc": ["E0"], "celda": ["c0"], "y": [0.0]}))
    assert pd.isna(out["y_ref"].iloc[0])


def test_predecir_no_aplica_abstencion_por_su_cuenta():
    # Separacion de responsabilidades: la curva de la Tarea 5 barre el umbral sin
    # recalcular predecir. Si predecir filtrara, habria que llamarlo una vez por punto.
    out = predecir(_m([("E2", "c", 1.0), ("E3", "c", 1.0)]), _m([("E1", "c", 1.0)]), "celda")
    assert "y_ref" not in out.columns and not pd.isna(out["y_ref_bruto"].iloc[0])
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/referencia.py
"""Referencia salarial de una celda: componentes de varianza, votos ponderados y
distribucion predictiva.

El modelo, por celda c:      y_fi = mu_c + a_f + e_fi
                             a_f ~ (0, tau2)   e_fi ~ (0, sigma2)

De el sale TODO lo que este modulo hace, sin un solo hiperparametro elegido a mano:

1. **El peso del voto de cada empresa**, w_f = 1/(tau2 + sigma2/n_f). Es inverso-varianza.
   Interpola entre "una empresa un voto" (n grande) y "una persona un voto" (tau2->0), y
   acota el ratio maximo de pesos en 1 + sigma2/tau2 — no en 3.000. Ese es el arreglo de
   D-011: la correccion 1 de D-009 elimino la dominancia del empleador grande pero
   desempareo el estimador de la metrica, porque la mediana SIMPLE de medianas de empresa
   estima la paga del empleador tipico y el MAE se mide contra personas.

2. **La referencia**: cuantil ponderado al 50%. Mediana y no media por lo medido sobre
   498.653 personas — la diferencia es 0,0533 en log y NO es neutral entre metodos, asi
   que usar la media seria un sesgo a favor de la hipotesis propia (D-006 #6).

3. **La anchura predictiva**, sd = raiz(tau2 + sigma2 + 1/suma(w_f)). Es la perilla de
   confianza correcta: la regla optima de abstencion en regresion umbraliza la varianza
   condicional (Zaoui, Denis & Hebiri 2020), no un conteo de donantes. 500 personas de 3
   empresas homogeneas dan mejor referencia que 20 de 10 empresas dispares, y la regla
   vieja prefería la segunda.

Este modulo NO decide cuando abstenerse: eso es `aplicar_abstencion`, funcion pura sobre
la tabla que devuelve `predecir`. Asi la curva barre el umbral sin recalcular.
"""
import numpy as np
import pandas as pd

SUELO_EMPRESAS = 3      # identificabilidad de tau2 + confidencialidad (precedente QCEW)
SUELO_SHARE = 0.80      # regla de dominancia (precedente QCEW). Ver D-011.


def componentes_varianza(train, col_celda):
    """(tau2, sigma2) globales, por momentos, sobre el modelo de un factor dentro de celda.

    Estimador ANOVA desbalanceado clasico:
        sigma2 = SSW / (N - G)
        tau2   = max(0, (SSB/(G - C) - sigma2) / n0)
    con G grupos (celda, empresa), C celdas y n0 el tamano efectivo de grupo.

    Globales y no por celda: con el 76,6% de la gente en empresas de >=100, estimar esto
    por celda anadiria ruido sin anadir informacion (mismo argumento que D-006 #3).
    """
    d = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])
    if d.empty:
        return 0.0, 0.0

    g = (d.groupby([col_celda, "empresa_ruc"])["y"]
           .agg(n="size", media="mean", var=lambda v: v.var(ddof=0)).reset_index())
    N, G, C = len(d), len(g), int(g[col_celda].nunique())

    ssw = float((g["n"] * g["var"]).sum())
    sigma2 = ssw / (N - G) if N > G else 0.0

    g["_wn"] = g["n"] * g["media"]
    porc = g.groupby(col_celda).agg(N_c=("n", "sum"), s=("_wn", "sum"),
                                    sn2=("n", lambda v: float((v.astype(float) ** 2).sum())))
    porc["media_c"] = porc["s"] / porc["N_c"]
    g = g.join(porc["media_c"], on=col_celda)
    ssb = float((g["n"] * (g["media"] - g["media_c"]) ** 2).sum())

    df_b = G - C
    if df_b <= 0:
        return 0.0, float(sigma2)
    n0 = (N - float((porc["sn2"] / porc["N_c"]).sum())) / df_b
    tau2 = (ssb / df_b - sigma2) / n0 if n0 > 0 else 0.0
    return float(max(tau2, 0.0)), float(sigma2)


def pesos_empresa(n, tau2, sigma2):
    """w_f = 1/(tau2 + sigma2/n_f). Derivado del modelo, no elegido."""
    n = np.asarray(n, dtype=float)
    denom = tau2 + np.divide(sigma2, n, out=np.full_like(n, np.inf), where=n > 0)
    return np.divide(1.0, denom, out=np.zeros_like(denom), where=denom > 0)


def cuantil_ponderado(valores, pesos, q=0.5):
    """Cuantil empirico ponderado con interpolacion. Con pesos iguales da la mediana."""
    v = np.asarray(valores, dtype=float).ravel()
    w = np.asarray(pesos, dtype=float).ravel()
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[ok], w[ok]
    if v.size == 0:
        return float("nan")
    if v.size == 1:
        return float(v[0])
    o = np.argsort(v, kind="mergesort")
    v, w = v[o], w[o]
    acum = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(q, acum, v))


def predecir(train, test, col_celda, tau2=None, sigma2=None):
    """Referencia bruta y anchura predictiva por fila de `test`, con leave-company-out.

    NO aplica abstencion — eso es `aplicar_abstencion`. Devuelve:
      y_ref_bruto, sd_pred, n_donantes (personas), n_empresas_donantes, share_max_empresa

    `sd_pred` incluye el ruido irreducible (empresa nueva + persona nueva) y el error de
    estimacion de mu_c. Solo el tercero mejora con mas donantes, que es exactamente lo que
    debe ordenar la abstencion.
    """
    tr = train[[col_celda, "empresa_ruc", "y"]].dropna(subset=["y"])
    if tau2 is None or sigma2 is None:
        tau2, sigma2 = componentes_varianza(train, col_celda)
    irreducible = float(tau2 + sigma2)

    votos = (tr.groupby([col_celda, "empresa_ruc"])["y"]
               .agg(voto="median", n="size").reset_index())
    votos["w"] = pesos_empresa(votos["n"], tau2, sigma2)

    porcelda = {}
    for celda, g in votos.groupby(col_celda, sort=False):
        porcelda[celda] = (g["voto"].to_numpy(float), g["w"].to_numpy(float),
                           g["n"].to_numpy(float),
                           {r: i for i, r in enumerate(g["empresa_ruc"])})

    VACIO = (np.nan, np.nan, 0, 0, np.nan)
    cache = {}

    def resolver(celda, emp):
        # Todas las personas de la misma empresa en la misma celda comparten referencia:
        # se calcula una vez por par, no una vez por persona. Con 1,3 M de filas eso es
        # la diferencia entre segundos y horas.
        clave = (celda, emp)
        if clave in cache:
            return cache[clave]
        dat = porcelda.get(celda)
        if dat is None:
            cache[clave] = VACIO
            return VACIO
        v, w, n, pos = dat
        j = pos.get(emp)
        if j is not None:
            keep = np.ones(len(v), dtype=bool)
            keep[j] = False
            v, w, n = v[keep], w[keep], n[keep]
        if len(v) == 0 or w.sum() <= 0:
            cache[clave] = VACIO
            return VACIO
        r = (cuantil_ponderado(v, w),
             float(np.sqrt(irreducible + 1.0 / w.sum())),
             int(n.sum()), int(len(v)), float(n.max() / n.sum()))
        cache[clave] = r
        return r

    filas = [resolver(c, e) for c, e in zip(test[col_celda], test["empresa_ruc"])]
    return pd.DataFrame(filas, index=test.index,
                        columns=["y_ref_bruto", "sd_pred", "n_donantes",
                                 "n_empresas_donantes", "share_max_empresa"])


def aplicar_abstencion(pred, max_sd=None, min_empresas=SUELO_EMPRESAS,
                       share_max=SUELO_SHARE):
    """`y_ref` con NaN donde el metodo se abstiene. Funcion pura: no recalcula nada.

    Tres reglas, y sirven para cosas distintas — el pre-registro las declara por separado:

    - `max_sd`  : el CRITERIO. Anchura predictiva por encima del umbral -> no publico.
                  Se declara en unidades interpretables antes de tocar el test.
    - `min_empresas` y `share_max`: SUELOS de sanidad, no de precision. Con 2 empresas no
                  se separa tau2 de sigma2 y cada donante deduce al otro; con una empresa
                  aportando >80% de la gente, la celda es un empleador con testigos.
    """
    y = pd.to_numeric(pred["y_ref_bruto"], errors="coerce").copy()
    fuera = (pred["n_empresas_donantes"] < int(min_empresas))
    fuera |= pred["share_max_empresa"].fillna(1.0) > float(share_max)
    if max_sd is not None:
        fuera |= pred["sd_pred"].isna() | (pred["sd_pred"] > float(max_sd))
    return y.mask(fuera).rename("y_ref")
```

- [ ] **Paso 4: Verificar** → 18 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/referencia.py tests/test_evaluacion_referencia.py
git commit -m "feat(evaluacion): votos inverso-varianza y distribucion predictiva (D-011)"
```

---

### Tarea 5: Error, cobertura y riesgo generalizado

**Reescrita en v3.** La curva vieja barría `min_donantes` y era **degenerada**: con k≈50 sobre 1,3 M
de filas la celda media tiene ~26.000 donantes, así que ningún umbral hasta 30 recortaba nada. La
curva del arquetipo era **un punto en cobertura 1,0**; sólo `CARGO` tenía curva. No existía ningún
punto del eje donde compararlos, y el pre-registro exigía leerlos "a cobertura igualada".

**Archivos:** Crear `src/benchmarking/evaluacion/metricas.py` · Test `tests/test_evaluacion_metricas.py`

**Interfaces:**
`error_y_cobertura(test, y_ref) -> dict` (`mae`, `rmse`, `sesgo`, `mae_intra`, `cobertura`,
`n_evaluadas`, `n_total`) ·
`crps_normal(y, mu, sd)` ·
`curva_riesgo(test, pred, n_puntos=41, ...) -> pd.DataFrame` ·
`augrc(curva) -> float` ·
`curva_coste(test, pred, costes, ...) -> pd.DataFrame` ·
`por_subgrupo(test, y_ref, col) -> pd.DataFrame`

**El cambio de fondo.** El riesgo selectivo a cobertura fija *"sólo considera el riesgo respecto de
las predicciones aceptadas, asumiendo que una selección específica ya ocurrió"* (Traub et al.,
NeurIPS 2024). El denominador cambia con cada método, así que `CARGO` al 60,5% y el arquetipo al 100%
no se leen en la misma escala aunque fuerces el mismo porcentaje.

**El riesgo generalizado fija el denominador en `N` para todos.** Dos lecturas, ambas útiles:

```
Riesgo_generalizado(t) = (1/N) * suma_TODAS[ |y_i - yhat_i| * 1{acepta} ]      -> AUGRC
Riesgo_coste(c)        = (1/N) * suma_TODAS[ |y_i - yhat_i| * 1{acepta} + c * 1{abstiene} ]
```

La primera da el escalar comparable (área bajo la curva contra cobertura, Traub et al.). La segunda da
la lectura de negocio: `c` es **cuánto cuesta no tener respuesta**. Y el `c` donde se cruzan las
curvas de `CARGO` y del arquetipo **es la frontera entre los escenarios A y B de D-004** — tres
desenlaces narrativos convertidos en un punto de corte medible.

**Cómo se enlazan `c` y el umbral.** Con predictiva normal, `E|y − mu| = sd·raiz(2/pi)`. La regla de
Bayes acepta cuando el error esperado no supera el coste de callarse, luego el umbral óptimo es
`sd <= c/raiz(2/pi)`. Barrer `c` **es** barrer el umbral de anchura, sin perilla extra.

**Tres métricas nuevas que no cuestan nada y tapan agujeros reales:**

- **`sesgo`** — el error medio *con signo*. Hoy no hay ninguna medida de calibración: un método puede
  tener MAE excelente y estar sistemáticamente 5% bajo en el tramo alto.
- **`mae_intra`** — descompone `e_fi = e_barra_f + (e_fi − e_barra_f)` y reporta la segunda parte.
  `e_barra_f` es el efecto empresa: **impredecible bajo leave-company-out e idéntico para todos los
  métodos**. Ahí vive el ~62% de la sd del error y sólo diluye la señal.
- **`crps_normal`** — puntuación estrictamente propia que *"generaliza el error absoluto, al que se
  reduce si el pronóstico es determinista"* (Gneiting & Raftery 2007 §4.2). O sea: **no rompe nada de
  lo pre-registrado**, el MAE es su caso degenerado. Premia acertar la anchura, no sólo el centro.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_metricas.py
import numpy as np, pandas as pd
from benchmarking.evaluacion.metricas import (
    error_y_cobertura, crps_normal, curva_riesgo, augrc, curva_coste, por_subgrupo)
from benchmarking.evaluacion.referencia import predecir


def _test(y, emp=None, **extra):
    n = len(y)
    d = {"y": y, "empresa_ruc": emp if emp is not None else [f"E{i}" for i in range(n)]}
    d.update(extra)
    return pd.DataFrame(d)


def test_las_abstenciones_no_cuentan_como_error():
    # Si contaran, un metodo que se calla saldria peor que uno que responde mal.
    r = error_y_cobertura(_test([1.0, 2.0, 3.0]), pd.Series([1.1, np.nan, np.nan]))
    assert abs(r["mae"] - 0.1) < 1e-9 and abs(r["cobertura"] - 1 / 3) < 1e-9
    assert r["n_evaluadas"] == 1 and r["n_total"] == 3


def test_el_sesgo_con_signo_detecta_descalibracion():
    # MAE identico, sesgo opuesto: sin esta columna los dos casos son indistinguibles.
    alto = error_y_cobertura(_test([0.0, 0.0]), pd.Series([0.5, 0.5]))
    mixto = error_y_cobertura(_test([0.0, 0.0]), pd.Series([0.5, -0.5]))
    assert abs(alto["mae"] - mixto["mae"]) < 1e-9
    assert abs(alto["sesgo"] + 0.5) < 1e-9 and abs(mixto["sesgo"]) < 1e-9


def test_mae_intra_descuenta_el_efecto_empresa():
    # Los cuatro de E1 fallan por +2 exactamente: es nivel de empresa, no de particion, y
    # ningun metodo puede predecirlo bajo leave-company-out.
    t = _test([2.0] * 4, emp=["E1"] * 4)
    r = error_y_cobertura(t, pd.Series([0.0] * 4))
    assert abs(r["mae"] - 2.0) < 1e-9
    assert r["mae_intra"] < 1e-9, "el desplazamiento comun de la empresa debe descontarse"


def test_mae_intra_conserva_el_error_que_si_es_del_metodo():
    t = _test([1.0, -1.0], emp=["E1", "E1"])
    r = error_y_cobertura(t, pd.Series([0.0, 0.0]))
    assert abs(r["mae_intra"] - 1.0) < 1e-9


def test_crps_se_reduce_al_error_absoluto_cuando_no_hay_incertidumbre():
    # G&R 2007 4.2. Es lo que garantiza que adoptar CRPS no rompe el pre-registro.
    assert abs(crps_normal(3.0, 1.0, 1e-8) - 2.0) < 1e-4


def test_crps_premia_la_anchura_bien_calibrada():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1.0, 4000)
    bien = crps_normal(y, 0.0, 1.0).mean()
    estrecho = crps_normal(y, 0.0, 0.2).mean()
    ancho = crps_normal(y, 0.0, 5.0).mean()
    assert bien < estrecho and bien < ancho


def test_el_riesgo_generalizado_usa_denominador_N():
    # EL punto de Traub et al.: quien se abstiene siempre no obtiene riesgo cero, obtiene c.
    t = _test([1.0, 2.0, 3.0, 4.0])
    p = pd.DataFrame({"y_ref_bruto": [np.nan] * 4, "sd_pred": [np.nan] * 4,
                      "n_donantes": [0] * 4, "n_empresas_donantes": [0] * 4,
                      "share_max_empresa": [np.nan] * 4})
    c = curva_coste(t, p, costes=[0.5])
    assert abs(c["riesgo"].iloc[0] - 0.5) < 1e-9 and c["cobertura"].iloc[0] == 0.0


def test_la_curva_de_coste_es_monotona_en_c():
    tr, ts, p = _caso()
    c = curva_coste(ts, p, costes=np.linspace(0.05, 1.5, 12))
    assert c["riesgo"].is_monotonic_increasing
    assert c["cobertura"].is_monotonic_increasing        # mas caro callarse -> hablo mas


def _caso():
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=60, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    return tr, ts, predecir(tr, ts, "rol_verdadero")


def test_augrc_castiga_ordenar_la_confianza_al_azar():
    # Si la anchura predictiva no ordena los errores, abstenerse no ayuda y el area sube.
    tr, ts, p = _caso()
    bueno = augrc(curva_riesgo(ts, p))
    revuelto = p.copy()
    revuelto["sd_pred"] = np.random.default_rng(1).permutation(p["sd_pred"].to_numpy())
    assert bueno <= augrc(curva_riesgo(ts, revuelto)) + 1e-9


def test_la_curva_de_riesgo_cubre_el_rango_de_cobertura():
    tr, ts, p = _caso()
    c = curva_riesgo(ts, p, n_puntos=21)
    assert c["cobertura"].min() < 0.2 and c["cobertura"].max() > 0.8
    assert c["cobertura"].is_monotonic_increasing


def test_por_subgrupo_reporta_error_Y_cobertura():
    # Shah et al. 2022: bajar la cobertura puede empeorar el riesgo de un subgrupo aunque
    # el global mejore. Sin las dos columnas juntas, invisible.
    t = _test([1.0, 2.0, 3.0, 4.0], sexo=["F", "F", "M", "M"])
    r = por_subgrupo(t, pd.Series([1.0, np.nan, 3.5, 4.0]), "sexo")
    f = r.set_index("sexo")
    assert abs(f.loc["F", "cobertura"] - 0.5) < 1e-9
    assert abs(f.loc["M", "cobertura"] - 1.0) < 1e-9
    assert abs(f.loc["F", "mae"] - 0.0) < 1e-9 and abs(f.loc["M", "mae"] - 0.25) < 1e-9


def test_cobertura_cero_no_revienta():
    r = error_y_cobertura(_test([1.0, 2.0]), pd.Series([np.nan] * 2))
    assert r["cobertura"] == 0.0 and np.isnan(r["mae"])
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/metricas.py
"""Error, cobertura, riesgo generalizado y puntuacion propia.

Por que el riesgo GENERALIZADO y no el selectivo a cobertura igualada: el riesgo selectivo
"solo considera el riesgo respecto de las predicciones aceptadas, asumiendo que una
seleccion especifica ya ocurrio" (Traub et al., NeurIPS 2024). Su denominador cambia con
cada metodo, asi que CARGO al 60,5% y el arquetipo al 100% no se leen en la misma escala.
Aqui el denominador es N para todos.

Nota: la version previa de este modulo barria `min_donantes` (1..30) como perilla de
confianza. Era degenerada — con la celda media a ~26.000 donantes ningun umbral recortaba
nada y la curva del arquetipo era un punto. Ver D-011.
"""
import numpy as np
import pandas as pd
from scipy.special import erf
from .referencia import aplicar_abstencion, SUELO_EMPRESAS, SUELO_SHARE

# E|X - mu| para X normal: sd * raiz(2/pi). Enlaza el coste de abstenerse con el umbral
# de anchura, de modo que barrer `c` sea barrer el umbral y no una perilla aparte.
_RAIZ_2_PI = float(np.sqrt(2.0 / np.pi))


def error_y_cobertura(test, y_ref):
    """MAE, RMSE, sesgo con signo, MAE intra-empresa y cobertura.

    Error y cobertura van SIEMPRE juntos: comparar solo el error favorece al metodo que se
    abstiene mas, porque acierta mas donde unicamente opina teniendo datos.

    `mae_intra` descompone e_fi = e_barra_f + (e_fi - e_barra_f) y reporta la segunda
    parte. e_barra_f es el efecto empresa: impredecible bajo leave-company-out e IDENTICO
    para todos los metodos. Ahi vive el grueso de la sd del error y solo diluye la senal.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    ref = pd.to_numeric(pd.Series(y_ref).reindex(test.index), errors="coerce").to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(ref)
    n_total, n_eval = len(y), int(ok.sum())
    if n_eval == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "sesgo": float("nan"),
                "mae_intra": float("nan"), "cobertura": 0.0,
                "n_evaluadas": 0, "n_total": n_total}

    err = y[ok] - ref[ok]
    emp = test["empresa_ruc"].to_numpy()[ok] if "empresa_ruc" in test.columns else np.zeros(n_eval)
    centrado = pd.Series(err).groupby(pd.Series(emp)).transform(lambda v: v - v.mean())
    return {"mae": float(np.abs(err).mean()),
            "rmse": float(np.sqrt((err ** 2).mean())),
            "sesgo": float(err.mean()),
            "mae_intra": float(np.abs(centrado.to_numpy()).mean()),
            "cobertura": n_eval / n_total,
            "n_evaluadas": n_eval, "n_total": n_total}


def crps_normal(y, mu, sd):
    """CRPS de una predictiva normal, forma cerrada.

        CRPS = sd * [ z(2*Phi(z) - 1) + 2*phi(z) - 1/raiz(pi) ],  z = (y - mu)/sd

    Estrictamente propio, y "generaliza el error absoluto, al que se reduce si F es un
    pronostico determinista" (Gneiting & Raftery 2007, 4.2). Es lo que hace que adoptarlo
    no rompa nada de lo pre-registrado: el MAE actual es su caso degenerado.
    """
    y = np.asarray(y, dtype=float)
    mu = np.asarray(mu, dtype=float)
    sd = np.asarray(sd, dtype=float)
    seguro = np.where(sd > 0, sd, np.nan)
    z = (y - mu) / seguro
    cdf = 0.5 * (1.0 + erf(z / np.sqrt(2.0)))
    pdf = np.exp(-0.5 * z ** 2) / np.sqrt(2.0 * np.pi)
    salida = seguro * (z * (2.0 * cdf - 1.0) + 2.0 * pdf - 1.0 / np.sqrt(np.pi))
    return np.where(sd > 0, salida, np.abs(y - mu))


def _riesgo(y, ref, coste):
    """(1/N) * suma sobre TODAS las filas de |err| si acepta, y `coste` si se abstiene."""
    ok = np.isfinite(y) & np.isfinite(ref)
    n = len(y)
    if n == 0:
        return float("nan"), 0.0, float("nan")
    perdida = np.abs(y[ok] - ref[ok]).sum() + float(coste) * (n - int(ok.sum()))
    mae = float(np.abs(y[ok] - ref[ok]).mean()) if ok.any() else float("nan")
    return perdida / n, int(ok.sum()) / n, mae


def curva_coste(test, pred, costes, min_empresas=SUELO_EMPRESAS, share_max=SUELO_SHARE):
    """Riesgo generalizado barriendo el COSTE DE ABSTENERSE.

    `c` es una cantidad de negocio con significado —cuanto cuesta no tener respuesta—, no
    una perilla estadistica. Y el `c` donde se cruzan las curvas de dos metodos es la
    frontera entre los escenarios A y B de D-004.

    Con predictiva normal, E|y - mu| = sd*raiz(2/pi), asi que la regla de Bayes acepta
    cuando sd <= c/raiz(2/pi): barrer `c` ES barrer el umbral de anchura.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    filas = []
    for c in np.atleast_1d(np.asarray(costes, dtype=float)):
        ref = aplicar_abstencion(pred, max_sd=float(c) / _RAIZ_2_PI,
                                 min_empresas=min_empresas, share_max=share_max).to_numpy(float)
        r, cob, mae = _riesgo(y, ref, c)
        filas.append({"coste": float(c), "cobertura": cob, "mae_aceptadas": mae, "riesgo": r})
    return pd.DataFrame(filas)


def curva_riesgo(test, pred, n_puntos=41, min_empresas=SUELO_EMPRESAS, share_max=SUELO_SHARE):
    """Riesgo generalizado (sin termino de coste) frente a cobertura.

    Barre el umbral de anchura por cuantiles de `sd_pred`, para que la curva tenga
    resolucion en todo [0,1] tanto con 55.920 celdas como con 50.
    """
    y = pd.to_numeric(test["y"], errors="coerce").to_numpy(float)
    sd = pd.to_numeric(pred["sd_pred"], errors="coerce").to_numpy(float)
    validas = sd[np.isfinite(sd)]
    if validas.size == 0:
        return pd.DataFrame(columns=["umbral_sd", "cobertura", "riesgo_generalizado",
                                     "mae_aceptadas"])
    umbrales = np.unique(np.quantile(validas, np.linspace(0.0, 1.0, int(n_puntos))))
    filas = []
    for u in umbrales:
        ref = aplicar_abstencion(pred, max_sd=float(u), min_empresas=min_empresas,
                                 share_max=share_max).to_numpy(float)
        r, cob, mae = _riesgo(y, ref, 0.0)
        filas.append({"umbral_sd": float(u), "cobertura": cob,
                      "riesgo_generalizado": r, "mae_aceptadas": mae})
    return pd.DataFrame(filas).sort_values("cobertura").reset_index(drop=True)


def augrc(curva):
    """Area bajo la curva de riesgo generalizado frente a cobertura, normalizada.

    Escalar comparable entre metodos con coberturas distintas, porque el denominador del
    riesgo es N para todos. Sustituye a AURC, que viola monotonicidad por sobreponderar
    los fallos de alta confianza (Traub et al., NeurIPS 2024) — y que este mismo plan
    recomendaba en un borrador previo. Menor es mejor.
    """
    if curva.empty or len(curva) < 2:
        return float("nan")
    x = curva["cobertura"].to_numpy(float)
    z = curva["riesgo_generalizado"].to_numpy(float)
    ancho = x.max() - x.min()
    return float(np.trapz(z, x) / ancho) if ancho > 0 else float(z.mean())


def por_subgrupo(test, y_ref, col, minimo=30):
    """Error Y cobertura por nivel de `col`. Las dos columnas, siempre.

    Al bajar la cobertura el riesgo de un subgrupo puede empeorar aunque el global mejore
    (Shah et al., ICML 2022). Y las celdas que no alcanzan donantes no son un subconjunto
    aleatorio: son ocupaciones raras, empresas pequenas y provincias fuera de Pichincha y
    Guayas. El banco puede reportar un MAE excelente mientras la referencia se degrada
    justo para quien mas la necesita.
    """
    d = test.copy()
    d["_ref"] = pd.to_numeric(pd.Series(y_ref).reindex(test.index), errors="coerce")
    filas = []
    for nivel, g in d.groupby(d[col].astype(str), sort=True):
        if len(g) < int(minimo):
            continue
        r = error_y_cobertura(g, g["_ref"])
        filas.append({col: nivel, "n": len(g), "cobertura": r["cobertura"],
                      "mae": r["mae"], "sesgo": r["sesgo"], "mae_intra": r["mae_intra"]})
    return pd.DataFrame(filas)
```

- [ ] **Paso 4: Añadir `scipy` explícito a `pyproject.toml`** — llega por scikit-learn, pero un
import directo debe declararse: `"scipy>=1.11",`

- [ ] **Paso 5: Verificar** → 12 passed

- [ ] **Paso 6: Commit**

```bash
git add src/benchmarking/evaluacion/metricas.py tests/test_evaluacion_metricas.py pyproject.toml
git commit -m "feat(evaluacion): riesgo generalizado, AUGRC, CRPS y desglose por subgrupo"
```

---

### Tarea 6: Bootstrap pareado de dos etapas y ω² intra-empresa

**Reescrita en v3.** La inferencia anterior **no podía decidir A ni B**, por tres fallos compuestos:

1. `comparar()` emitía **dos IC independientes**, y el pre-registro exige *"el IC de la diferencia sin
   cruzar el cero"*. Leer solapamiento es el error de Schenker & Gentleman (2001): el solapamiento no
   implica no-significancia. Y aquí cuesta especialmente caro, porque el error está dominado por el
   efecto empresa `a_f`, que es **idéntico para los dos métodos** y **se cancela en la diferencia
   pareada** — se pagaba entero en el contraste marginal.
2. `ic_bootstrap_empresas` llamaba a `predecir()` **fuera** del bucle: trataba `mu_c` como fija cuando
   en la mayoría de celdas de `CARGO` se estima con 3–5 empresas. Es la subestimación de varianza de
   Nadeau & Bengio (2003) y la sub-cobertura de Bates, Hastie & Tibshirani (2024), verbatim: *"standard
   confidence intervals for prediction error derived from cross-validation may have coverage far below
   the desired level"*.
3. Dos personas de empresas distintas en la misma celda comparten `mu_c`; agrupar sólo por empresa de
   test no lo captura — es clustering en dos direcciones no anidadas (Cameron, Gelbach & Miller 2011).

**Archivos:** Modificar `metricas.py` · Test: añadir a `tests/test_evaluacion_metricas.py`

**Interfaces:**
`replicas_bootstrap(train, test, particiones_tr, particiones_ts, n=400, semilla=20260805,
remuestrear_train=True, ...) -> pd.DataFrame` (una fila por réplica, una columna por método) ·
`ic_diferencia(replicas, a, b, alfa=0.05) -> dict` ·
`omega2_intra_empresa(df, col_celda) -> float`

**Cómo funciona.** Cada réplica remuestrea **empresas de train** (lo que hace variar `mu_c`) y
**empresas de test** (lo que hace variar a quién se evalúa), y calcula el MAE de **todos los métodos
sobre esa misma réplica** — números aleatorios comunes. Como la partición es lo único que cambia entre
métodos, la diferencia pareada aísla exactamente eso.

El MAE pareado se calcula sobre la **intersección** de filas donde *todos* los métodos respondieron:
comparar sobre conjuntos distintos es precisamente lo que la co-primaria de cobertura existe para
evitar. La cobertura se reporta aparte, por método, sobre el total.

> **Límite que hay que declarar en la tesis.** No existe referencia canónica para *"bootstrap de dos
> niveles con train remuestreado y test clusterizado"*. Bates et al. muestran justamente que ese
> estimando no es lo que estiman los métodos estándar. La construcción es defendible; **descríbase
> explícitamente y no se presente como práctica establecida.** Escribirlo así es más fuerte que fingir
> una cita.

> **Coste.** Cada réplica recalcula `predecir` para cada método. Con `n=400` y 7 métodos son 2.800
> pasadas. Medir el tiempo de una réplica en el marco real **antes** de lanzar las 400 y anotarlo en
> `docs/mediciones.md`; si no cabe, bajar `n` y **decirlo en el informe**, nunca en silencio.

- [ ] **Paso 1: Escribir el test que falla**

```python
# anadir a tests/test_evaluacion_metricas.py
from benchmarking.evaluacion.metricas import (
    replicas_bootstrap, ic_diferencia, omega2_intra_empresa)


def _marco():
    from sintetico import generar
    from benchmarking.evaluacion.splits import empresas_test, partir
    df = generar(n_empresas=50, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def _particiones(tr, ts):
    from benchmarking.evaluacion.particiones import aleatoria
    return ({"verdadera": tr["rol_verdadero"].astype(str), "azar": aleatoria(tr, 3)},
            {"verdadera": ts["rol_verdadero"].astype(str), "azar": aleatoria(ts, 3)})


def test_una_fila_por_replica_y_una_columna_por_metodo():
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    r = replicas_bootstrap(tr, ts, p_tr, p_ts, n=25, semilla=1)
    assert r.shape == (25, 2) and set(r.columns) == {"verdadera", "azar"}


def test_bootstrap_determinista():
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    a = replicas_bootstrap(tr, ts, p_tr, p_ts, n=15, semilla=3)
    b = replicas_bootstrap(tr, ts, p_tr, p_ts, n=15, semilla=3)
    pd.testing.assert_frame_equal(a, b)


def test_la_diferencia_pareada_es_mas_estrecha_que_dos_IC_marginales():
    # EL motivo del cambio. El error esta dominado por el efecto empresa, identico para
    # los dos metodos: se cancela en la diferencia y se paga entero en el contraste
    # marginal. Si esto falla, los numeros aleatorios comunes no se estan aplicando.
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    r = replicas_bootstrap(tr, ts, p_tr, p_ts, n=120, semilla=4)
    d = ic_diferencia(r, "verdadera", "azar")
    ancho_pareado = d["ic_alto"] - d["ic_bajo"]
    ancho_marginal = ((r["azar"].quantile(.975) - r["azar"].quantile(.025)) +
                      (r["verdadera"].quantile(.975) - r["verdadera"].quantile(.025)))
    assert ancho_pareado < ancho_marginal


def test_la_diferencia_detecta_a_la_particion_verdadera():
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    d = ic_diferencia(replicas_bootstrap(tr, ts, p_tr, p_ts, n=120, semilla=6),
                      "verdadera", "azar")
    assert d["dif"] < 0 and d["ic_alto"] < 0, "verdadera - azar debe ser negativa y significativa"


def test_remuestrear_train_ensancha_el_intervalo():
    # El defecto 3b de D-011: tratar mu_c como fija cuando se estima con 3-5 empresas
    # subestima la varianza. La bandera existe para dejarlo demostrado, no para usarla.
    tr, ts = _marco(); p_tr, p_ts = _particiones(tr, ts)
    con = replicas_bootstrap(tr, ts, p_tr, p_ts, n=80, semilla=8, remuestrear_train=True)
    sin = replicas_bootstrap(tr, ts, p_tr, p_ts, n=80, semilla=8, remuestrear_train=False)
    assert con["verdadera"].std() > sin["verdadera"].std()


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
from .referencia import predecir
from .splits import SEMILLA


def _remuestrear(df, empresas, rng):
    """Remuestrea EMPRESAS con reemplazo y devuelve el df concatenado.

    Nunca filas: la fila no es la unidad independiente (una empresa aporta cientos de
    personas y una persona recurre entre anios). Las empresas repetidas se desambiguan
    para que cuenten como donantes distintos, que es lo que el remuestreo simula.
    """
    elegidas = empresas[rng.integers(0, len(empresas), len(empresas))]
    trozos = []
    for k, ruc in enumerate(elegidas):
        t = df[df["empresa_ruc"] == ruc].copy()
        t["empresa_ruc"] = f"{ruc}#{k}"
        trozos.append(t)
    return pd.concat(trozos, ignore_index=True) if trozos else df.iloc[:0].copy()


def replicas_bootstrap(train, test, particiones_tr, particiones_ts, n=400, semilla=SEMILLA,
                       max_sd=None, min_empresas=SUELO_EMPRESAS, share_max=SUELO_SHARE,
                       remuestrear_train=True):
    """MAE de cada metodo, replica a replica, con NUMEROS ALEATORIOS COMUNES.

    Dos etapas: se remuestrean empresas de train (hace variar mu_c, que en CARGO se estima
    con 3-5 empresas) y empresas de test (hace variar a quien se evalua). Todos los metodos
    se evaluan sobre la MISMA replica, asi que la diferencia pareada aisla la particion y
    cancela el efecto empresa, que es comun a los dos.

    El MAE se calcula sobre la INTERSECCION de filas donde todos respondieron: comparar
    sobre conjuntos distintos es lo que la co-primaria de cobertura existe para evitar.

    `remuestrear_train=False` reproduce el estimador defectuoso previo. Existe solo para
    que el test pueda demostrar la subestimacion de varianza; no usar.
    """
    nombres = list(particiones_ts)
    tr0 = train.assign(**{f"_c_{m}": particiones_tr[m].astype(str).to_numpy() for m in nombres})
    ts0 = test.assign(**{f"_c_{m}": particiones_ts[m].astype(str).to_numpy() for m in nombres})
    emp_tr = np.array(sorted(tr0["empresa_ruc"].unique()))
    emp_ts = np.array(sorted(ts0["empresa_ruc"].unique()))

    rng = np.random.default_rng(int(semilla))
    filas = []
    for _ in range(int(n)):
        tr_b = _remuestrear(tr0, emp_tr, rng) if remuestrear_train else tr0
        ts_b = _remuestrear(ts0, emp_ts, rng)
        y = pd.to_numeric(ts_b["y"], errors="coerce").to_numpy(float)

        refs = {}
        for m in nombres:
            p = predecir(tr_b, ts_b, f"_c_{m}")
            refs[m] = aplicar_abstencion(p, max_sd=max_sd, min_empresas=min_empresas,
                                         share_max=share_max).to_numpy(float)
        comun = np.isfinite(y)
        for m in nombres:
            comun &= np.isfinite(refs[m])
        if not comun.any():
            continue
        filas.append({m: float(np.abs(y[comun] - refs[m][comun]).mean()) for m in nombres})
    return pd.DataFrame(filas, columns=nombres)


def ic_diferencia(replicas, a, b, alfa=0.05):
    """IC percentil de la diferencia PAREADA `a - b`, replica a replica.

    Leer el solapamiento de dos IC marginales en su lugar es el error de Schenker &
    Gentleman (2001): el solapamiento no implica no-significancia. Y aqui el contraste
    marginal paga entero el efecto empresa, que la diferencia pareada cancela.
    """
    d = (replicas[a] - replicas[b]).dropna().to_numpy(float)
    if d.size == 0:
        return {"dif": float("nan"), "ic_bajo": float("nan"), "ic_alto": float("nan"),
                "n_replicas": 0}
    return {"dif": float(d.mean()),
            "ic_bajo": float(np.quantile(d, alfa / 2)),
            "ic_alto": float(np.quantile(d, 1 - alfa / 2)),
            "n_replicas": int(d.size)}


def omega2_intra_empresa(df, col_celda):
    """omega2 de la celda sobre el residuo INTRA-empresa del objetivo.

    Se residualiza contra la empresa primero porque el empleador explica ~39% de la
    varianza del log-salario. Sin encogimiento: el 76,6% de la gente esta en empresas de
    100 o mas, asi que la correccion del modelo mixto apenas mueve nada (D-006 #3).
    omega2 y no eta2 porque penaliza los grados de libertad, y aqui se comparan
    cardinalidades muy distintas (55.920 celdas frente a 50).

    Confirmatorio, nunca arbitro: la decision la toma el error fuera de muestra.
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

- [ ] **Paso 4: Verificar** → 7 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/metricas.py tests/test_evaluacion_metricas.py
git commit -m "feat(evaluacion): bootstrap pareado de dos etapas y omega2 intra-empresa"
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

### Tarea 9: Las particiones rivales, el techo y el oráculo

**Reescrita en v3.** El "techo supervisado" anterior corría k-means sobre `y` de **todo el df, test
incluido**. Al definir la celda por la propia `y` de la persona, la mediana de sus donantes ≈ su `y` y
el MAE colapsaba al error de cuantización de 50 bins (~0,01–0,03). Dos consecuencias:

- La frase-resultado *"el arquetipo recorre el __% de la distancia entre `CARGO` y el techo"* tenía un
  **denominador inalcanzable por construcción**.
- **La alarma anti-circularidad moría**: nada puede acercarse a un techo que escapa del efecto empresa
  usando la etiqueta.

Los propios números lo prueban. Con η²_empresa = 0,388 y el efecto empresa inobservable bajo
leave-company-out, `Var(error) ≥ 0,388·Var(y)` para **cualquier** partición: en desviación estándar, el
mejor método posible llega a `√0,388 = 0,623` del MAE aleatorio. **Todo el rango dinámico de la métrica
primaria es el 37,7% del piso**, y el techo que teníamos estaba en ~3%.

**Se separa en dos objetos con papeles distintos:**

| | Qué es | Para qué |
|---|---|---|
| **Techo alcanzable** | GBM sobre observables legítimos, entrenado **en train** | el denominador honesto |
| **Oráculo** | k-means sobre `y`, ajustado **sólo en train** | **bandera roja**, nunca denominador |

El techo no es una partición: es un predictor. No tiene por qué serlo — su papel es acotar cuánta señal
hay en los datos, y un modelo flexible acota mejor que cualquier agrupamiento. El oráculo sí es
partición, y sigue haciendo trampa a propósito: si el arquetipo se le acerca, sospechar deriva a bandas
salariales.

**Archivos:** Crear `src/benchmarking/evaluacion/particiones.py` · Modificar `pyproject.toml`
(`scikit-learn`, `matplotlib`) · Test `tests/test_evaluacion_particiones.py`

**Interfaces:** las particiones devuelven `pd.Series` alineada al índice del DataFrame —
`cargo_crudo(df)` · `aleatoria(df, k, semilla)` · `solo_texto(df, k, embeddings, semilla)` ·
`oraculo_salarial(train, df, k, semilla)`. El techo devuelve predicciones —
`techo_alcanzable(train, test, X_tr, X_ts, semilla)`.

- [ ] **Paso 1: Añadir dependencias** — en `pyproject.toml`, a `dependencies`:
`"scikit-learn>=1.4", "matplotlib>=3.8",` · luego `.venv\Scripts\python.exe -m pip install -e .`

- [ ] **Paso 2: Escribir el test que falla**

```python
# tests/test_evaluacion_particiones.py
import numpy as np, pandas as pd
from sintetico import generar
from benchmarking.evaluacion.particiones import (
    cargo_crudo, aleatoria, solo_texto, oraculo_salarial, techo_alcanzable)
from benchmarking.evaluacion.splits import empresas_test, partir


def _marco():
    df = generar(n_empresas=40, personas_por_empresa=12)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def test_cargo_crudo_no_poda_nada():
    # Podar CARGO a sus top-50 dejaria a 429.000 personas en una celda "otros": ganarle a
    # ese rival no demostraria nada (D-005). Compite entero.
    df = pd.DataFrame({"cargo_norm": ["VENDEDOR"] * 3 + [f"RARO{i}" for i in range(50)]})
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


def test_el_oraculo_se_ajusta_SOLO_en_train():
    # EL defecto 4 de D-011. Ajustarlo sobre todo el df incluia el test y el MAE colapsaba
    # al error de cuantizacion. Prueba: lo que haya en test no puede mover las fronteras.
    tr, ts = _marco()
    a = oraculo_salarial(tr, ts, k=4, semilla=1)
    ts2 = ts.copy()
    ts2.loc[ts2.index[:5], "y"] = 99.0          # atipicos brutales solo en test
    b = oraculo_salarial(tr, ts2, k=4, semilla=1)
    pd.testing.assert_series_equal(a.iloc[5:], b.iloc[5:])


def test_el_oraculo_sigue_haciendo_trampa():
    # Es su trabajo: agrupar por el salario. Si dejara de hacerlo, la alarma no sonaria.
    tr = pd.DataFrame({"y": [0.0, 0.05, 0.1, 5.0, 5.05, 5.1]})
    c = oraculo_salarial(tr, tr, k=2, semilla=1)
    assert c.iloc[0] == c.iloc[2] and c.iloc[3] == c.iloc[5] and c.iloc[0] != c.iloc[3]


def test_el_techo_no_ve_la_y_de_test():
    tr, ts = _marco()
    X_tr = tr[["antiguedad_total", "pct_comisiones", "pct_extras"]].to_numpy(float)
    X_ts = ts[["antiguedad_total", "pct_comisiones", "pct_extras"]].to_numpy(float)
    a = techo_alcanzable(tr, ts, X_tr, X_ts)
    ts2 = ts.copy(); ts2["y"] = -99.0
    pd.testing.assert_series_equal(a, techo_alcanzable(tr, ts2, X_tr, X_ts))


def test_el_techo_es_mejor_que_el_azar_pero_no_es_magia():
    tr, ts = _marco()
    cols = ["antiguedad_total", "pct_comisiones", "pct_extras", "pct_fijo"]
    pred = techo_alcanzable(tr, ts, tr[cols].to_numpy(float), ts[cols].to_numpy(float))
    mae = float((ts["y"] - pred).abs().mean())
    azar = float((ts["y"] - ts["y"].median()).abs().mean())
    assert mae < azar
    assert mae > 0.05, "un techo casi perfecto delata que se colo la y de test"


def test_todas_devuelven_serie_alineada():
    tr, ts = _marco()
    emb = np.random.default_rng(0).normal(0, 1, (len(ts), 8))
    for s in (cargo_crudo(ts), aleatoria(ts, 3), solo_texto(ts, 3, emb),
              oraculo_salarial(tr, ts, 3)):
        assert isinstance(s, pd.Series) and s.index.equals(ts.index) and s.notna().all()
```

- [ ] **Paso 3: Verificar que falla**

- [ ] **Paso 4: Implementar**

```python
# src/benchmarking/evaluacion/particiones.py
"""La escalera de referencias: los rivales, el techo y el oraculo.

  aleatoria         -> aporta algo la informacion?
  cargo_crudo       -> supero lo que se usa hoy, entero y sin podar?
  solo_texto        -> la composicion aporta algo mas alla del nombre del puesto?
  techo_alcanzable  -> cuanto es lo maximo posible con estos datos?   (NO es particion)
  oraculo_salarial  -> BANDERA ROJA: si el arquetipo se le acerca, derivo a bandas

Todos los rivales se puntuan con EL MISMO estimador (`referencia.predecir`). Es el
invariante del banco: lo unico que cambia entre metodos es como se agrupa a la gente.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor

SEMILLA = 20260805


def cargo_crudo(df):
    """CARGO tal cual, con todas sus etiquetas. No se poda (D-005)."""
    return df["cargo_norm"].astype(str).rename("celda")


def aleatoria(df, k, semilla=SEMILLA):
    """Piso de la escalera: k celdas sin ninguna informacion.

    No es trivial. Es lo que detecta el artefacto de la masa en el SBU (Tarea 2b): si la
    mitad de la gente tiene y = 0 por censura, hasta el azar acierta y el piso sube hasta
    tocar al arquetipo.
    """
    rng = np.random.default_rng(semilla)
    return pd.Series(rng.integers(0, int(k), len(df)).astype(str),
                     index=df.index, name="celda")


def solo_texto(df, k, embeddings, semilla=SEMILLA):
    """Agrupa por el significado del titulo, en k celdas. El rival dificil.

    Hace dos trabajos: aisla la contribucion de la composicion frente al puro significado
    del titulo, E IGUALA LA CARDINALIDAD — sin el, la primera objecion del tribunal es
    "gana por tener 50 celdas en vez de 55.920" y no hay respuesta.

    Embeddings y no TF-IDF porque la similitud de caracteres invierte la jerarquia
    —medido: AUXILIAR DE SERVICIOS GENERALES -> JEFE DE SERVICIOS GENERALES puntua 0,79—
    y eso fabricaria un rival mas flojo del necesario, que es el patron de D-006.
    """
    X = np.asarray(embeddings, dtype=float)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10)
    return pd.Series(km.fit_predict(X).astype(str), index=df.index, name="celda")


def oraculo_salarial(train, df, k, semilla=SEMILLA):
    """Agrupa DIRECTAMENTE por el salario: circular por diseno. AJUSTADO SOLO EN TRAIN.

    No es un metodo candidato ni un denominador. Es la alarma: si el arquetipo se le
    acerca, sospechar que derivo a bandas salariales, que es exactamente lo que la tesis
    promete no hacer.

    El ajuste sobre train importa. La version previa corria k-means sobre `y` de todo el
    df, test incluido: definida la celda por la propia y de la persona, el MAE colapsaba
    a ~0,03 —el error de cuantizacion de 50 bins— y la alarma no podia sonar nunca.
    """
    ytr = pd.to_numeric(train["y"], errors="coerce").fillna(0.0).to_numpy(float).reshape(-1, 1)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10).fit(ytr)
    y = pd.to_numeric(df["y"], errors="coerce").fillna(0.0).to_numpy(float).reshape(-1, 1)
    return pd.Series(km.predict(y).astype(str), index=df.index, name="celda")


def techo_alcanzable(train, test, X_train, X_test, semilla=SEMILLA):
    """Cuanta senal hay en los observables legitimos. Devuelve PREDICCIONES, no celdas.

    No tiene por que ser una particion: su papel es acotar el maximo alcanzable, y un
    modelo flexible acota mejor que cualquier agrupamiento. Entrenado en train y evaluado
    en empresas held-out, la misma frontera que usa el banco.

    Perdida absoluta, no cuadratica: si el modelo optimizara MSE estaria estimando la
    media condicional mientras la metrica puntua el error absoluto, y el techo saldria
    mas bajo de lo que realmente es. Es el mismo desemparejamiento que D-011 corrigio en
    el estimador; aqui tambien aplica.

    COTA TEORICA que este numero no puede superar: con eta2_empresa = 0,388 y el efecto
    empresa inobservable bajo leave-company-out, Var(error) >= 0,388*Var(y) para cualquier
    metodo. En sd, el mejor posible llega a raiz(0,388) = 0,623 del MAE aleatorio. Si el
    techo sale muy por debajo de eso, se colo informacion del test.
    """
    modelo = HistGradientBoostingRegressor(loss="absolute_error", random_state=int(semilla))
    modelo.fit(np.asarray(X_train, dtype=float),
               pd.to_numeric(train["y"], errors="coerce").to_numpy(float))
    return pd.Series(modelo.predict(np.asarray(X_test, dtype=float)),
                     index=test.index, name="y_techo")
```

- [ ] **Paso 5: Verificar** → 8 passed

- [ ] **Paso 6: Commit**

```bash
git add src/benchmarking/evaluacion/particiones.py tests/test_evaluacion_particiones.py pyproject.toml
git commit -m "feat(evaluacion): escalera de rivales, techo alcanzable y oraculo separados"
```

---

### Tarea 10: El banco se valida a sí mismo, y declara su sensibilidad

**Archivos:** Test `tests/test_evaluacion_banco.py`

Un instrumento que nadie verificó no sirve para verificar nada. **Si algún test falla aquí, está mal
el banco (Tareas 3–9), no el test.**

**Ampliada en v3** con la **calibración de la magnitud mínima detectable**. El pre-registro fija el
criterio de éxito pero no la magnitud que el banco puede distinguir, y sin eso un empate no significa
"iguales": significa "no medible". Se calibra degradando la partición verdadera —reasignando `x%` de
las personas al azar— y comprobando dos cosas: que el error **responde de forma monótona** a la
degradación, y a partir de qué `x` la **diferencia pareada** separa del cero.

- [ ] **Paso 1: Escribir la prueba de aceptación**

```python
# tests/test_evaluacion_banco.py
"""Prueba de aceptacion: el banco debe ordenar bien particiones de calidad conocida,
y debe declarar cuanta degradacion es capaz de detectar."""
import numpy as np, pandas as pd, pytest
from sintetico import generar
from benchmarking.evaluacion.splits import empresas_test, partir
from benchmarking.evaluacion.referencia import predecir, aplicar_abstencion
from benchmarking.evaluacion.metricas import (
    error_y_cobertura, replicas_bootstrap, ic_diferencia)
from benchmarking.evaluacion.particiones import aleatoria


@pytest.fixture
def marco():
    df = generar(n_empresas=60, personas_por_empresa=20, n_roles=3)
    df["y"] = np.log(df["sueldo"] / 470)
    return df


def _r(df, col):
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    return error_y_cobertura(ts, aplicar_abstencion(predecir(tr, ts, col)))


def _degradar(serie, x, semilla=0):
    """Reasigna al azar una fraccion x de las etiquetas, conservando el reparto."""
    rng = np.random.default_rng(semilla)
    v = serie.astype(str).to_numpy().copy()
    n = int(round(x * len(v)))
    if n:
        i = rng.choice(len(v), n, replace=False)
        v[i] = rng.permutation(v[i])
    return pd.Series(v, index=serie.index)


# --- ordena bien lo que ya sabemos ordenar -----------------------------------

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
    # Correccion 1 de D-009 extremo a extremo, ahora con pesos inverso-varianza: una
    # empresa con 20x mas gente y nivel salarial atipico no mueve la referencia del resto.
    df = generar(n_empresas=30, personas_por_empresa=10, desiguales=True)
    df["y"] = np.log(df["sueldo"] / 470)
    grande = df["empresa_ruc"].value_counts().idxmax()
    df.loc[df["empresa_ruc"] == grande, "y"] += 3.0
    tr, ts = partir(df, empresas_test(df, frac=0.25))
    ts = ts[ts["empresa_ruc"] != grande]
    r = error_y_cobertura(ts, aplicar_abstencion(predecir(tr, ts, "rol_verdadero")))
    assert r["mae"] < 0.6, "la empresa atipica no debe arrastrar la referencia del resto"


def test_el_banco_no_premia_agrupar_por_el_sueldo_si_la_verdad_es_otra(marco):
    # La data sintetica separa los roles por COMPOSICION, con sueldos solapados. Si una
    # particion por bandas de sueldo ganara aqui, el banco estaria midiendo circularidad.
    m = marco.copy()
    m["bandas"] = pd.qcut(m["y"], 3, labels=False).astype(str)
    assert _r(m, "rol_verdadero")["mae"] <= _r(m, "bandas")["mae"] + 0.02


# --- magnitud minima detectable ----------------------------------------------

def test_el_error_responde_de_forma_monotona_a_la_degradacion(marco):
    # Si el banco no distingue 0% de 40% de ruido, no distingue nada.
    maes = [_r(marco.assign(deg=_degradar(marco["rol_verdadero"], x)), "deg")["mae"]
            for x in (0.0, 0.10, 0.25, 0.50)]
    assert all(b >= a - 1e-9 for a, b in zip(maes, maes[1:])), maes
    assert maes[-1] > maes[0] * 1.05


def test_declara_su_magnitud_minima_detectable(marco):
    # ESTE test es el que se cita en el pre-registro. Fija la sensibilidad del
    # instrumento: a partir de que degradacion el IC pareado separa del cero.
    tr, ts = partir(marco, empresas_test(marco, frac=0.25))
    detectados = []
    for x in (0.05, 0.10, 0.20):
        p_tr = {"buena": tr["rol_verdadero"].astype(str),
                "degradada": _degradar(tr["rol_verdadero"], x, semilla=1)}
        p_ts = {"buena": ts["rol_verdadero"].astype(str),
                "degradada": _degradar(ts["rol_verdadero"], x, semilla=1)}
        d = ic_diferencia(replicas_bootstrap(tr, ts, p_tr, p_ts, n=60, semilla=2),
                          "buena", "degradada")
        detectados.append((x, d["ic_alto"] < 0))
    assert any(ok for _, ok in detectados), f"el banco no detecta ni un 20% de ruido: {detectados}"
    print("MDE:", detectados)      # -> al pre-registro
```

- [ ] **Paso 2: Ejecutar** → 9 passed. **Si falla alguno, arreglar el módulo correspondiente antes
de seguir.**

- [ ] **Paso 3: Anotar el MDE observado** en `docs/mediciones.md` y llevarlo al pre-registro
(Tarea 14, campo *Magnitud mínima detectable*).

- [ ] **Paso 4: Commit**

```bash
git add tests/test_evaluacion_banco.py docs/mediciones.md
git commit -m "test(evaluacion): prueba de aceptacion del banco y calibracion del MDE"
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

**Reescrita en v3.** La tabla anterior emitía dos IC independientes por método y dejaba al lector
comparar solapamientos, que es exactamente lo que no se puede hacer. Ahora la columna que decide es
**la diferencia pareada contra `CARGO`**.

**Archivos:** Crear `src/benchmarking/evaluacion/informe.py` · Test `tests/test_evaluacion_informe.py`

**Interfaces:**
`comparar(train, test, particiones_tr, particiones_ts, referencia="CARGO crudo", n_bootstrap=400) -> pd.DataFrame`
(`metodo, n_celdas, cobertura, mae, sesgo, mae_intra, augrc, omega2, dif_vs_ref, ic_bajo, ic_alto`) ·
`tabla_texto(comp) -> str` ·
`frontera_ab(curva_a, curva_b) -> float` ·
`ganador_por_etiqueta(test, refs, col='cargo_norm', minimo=20) -> pd.DataFrame` ·
`guardar_curvas(curvas, ruta_png)` · `guardar_curvas_coste(curvas, ruta_png)`

**Cuatro salidas, y cada una contesta una pregunta del pre-registro:**

1. **La tabla** — con `dif_vs_ref` y su IC. Es el criterio A, literal.
2. **La curva de riesgo generalizado frente a cobertura** — denominador `N` para todos, así que los
   métodos se leen en la misma escala sin intersecar nada. Su área es el AUGRC.
3. **La curva de coste, con la frontera marcada** — el `c` donde se cruzan `CARGO` y el arquetipo
   **es** la frontera A/B de D-004. Por debajo manda la precisión, por encima manda la cobertura.
4. **El ganador por etiqueta** — D-004 declara el desenlace C (complementariedad) el más probable y
   **no había ninguna métrica que lo operacionalizara**. Si ocurre C, esto *es* el entregable: el mapa
   de dónde conviene cada método.

- [ ] **Paso 1: Escribir el test que falla**

```python
# tests/test_evaluacion_informe.py
import numpy as np, pandas as pd
from sintetico import generar
from benchmarking.evaluacion.splits import empresas_test, partir
from benchmarking.evaluacion.particiones import aleatoria
from benchmarking.evaluacion.referencia import predecir, aplicar_abstencion
from benchmarking.evaluacion.metricas import curva_riesgo, curva_coste
from benchmarking.evaluacion.informe import (
    comparar, tabla_texto, frontera_ab, ganador_por_etiqueta,
    guardar_curvas, guardar_curvas_coste)


def _datos():
    df = generar(n_empresas=50, personas_por_empresa=14)
    df["y"] = np.log(df["sueldo"] / 470)
    return partir(df, empresas_test(df, frac=0.25))


def _parts(tr, ts):
    return ({"verdadera": tr["rol_verdadero"].astype(str), "azar": aleatoria(tr, 3)},
            {"verdadera": ts["rol_verdadero"].astype(str), "azar": aleatoria(ts, 3)})


def test_comparar_una_fila_por_metodo_con_las_columnas_nuevas():
    tr, ts = _datos(); p_tr, p_ts = _parts(tr, ts)
    c = comparar(tr, ts, p_tr, p_ts, referencia="azar", n_bootstrap=25)
    assert list(c["metodo"]) == ["verdadera", "azar"]
    assert {"cobertura", "mae", "sesgo", "mae_intra", "augrc", "omega2",
            "dif_vs_ref", "ic_bajo", "ic_alto", "n_celdas"} <= set(c.columns)
    assert c.loc[c.metodo == "verdadera", "mae"].iloc[0] < c.loc[c.metodo == "azar", "mae"].iloc[0]


def test_la_referencia_tiene_diferencia_cero_consigo_misma():
    tr, ts = _datos(); p_tr, p_ts = _parts(tr, ts)
    c = comparar(tr, ts, p_tr, p_ts, referencia="azar", n_bootstrap=20)
    assert abs(c.loc[c.metodo == "azar", "dif_vs_ref"].iloc[0]) < 1e-12


def test_la_diferencia_pareada_decide_el_criterio_A():
    # Criterio A del pre-registro, literal: IC de la DIFERENCIA sin cruzar el cero.
    tr, ts = _datos(); p_tr, p_ts = _parts(tr, ts)
    c = comparar(tr, ts, p_tr, p_ts, referencia="azar", n_bootstrap=120)
    f = c.set_index("metodo").loc["verdadera"]
    assert f["dif_vs_ref"] < 0 and f["ic_alto"] < 0


def test_frontera_ab_encuentra_el_cruce():
    a = pd.DataFrame({"coste": [0., 1., 2.], "riesgo": [0.0, 0.5, 1.0]})
    b = pd.DataFrame({"coste": [0., 1., 2.], "riesgo": [0.4, 0.6, 0.8]})
    assert abs(frontera_ab(a, b) - 1.5) < 0.05


def test_frontera_ab_es_nan_si_no_se_cruzan():
    a = pd.DataFrame({"coste": [0., 1.], "riesgo": [0.0, 0.1]})
    b = pd.DataFrame({"coste": [0., 1.], "riesgo": [0.5, 0.6]})
    assert np.isnan(frontera_ab(a, b))


def test_ganador_por_etiqueta_operacionaliza_el_desenlace_C():
    ts = pd.DataFrame({"y": [1., 1., 1., 5., 5., 5.],
                       "empresa_ruc": list("ABCDEF"),
                       "cargo_norm": ["X"] * 3 + ["Z"] * 3})
    refs = {"a": pd.Series([1., 1., 1., 9., 9., 9.]),      # gana en X
            "b": pd.Series([9., 9., 9., 5., 5., 5.])}      # gana en Z
    g = ganador_por_etiqueta(ts, refs, minimo=3).set_index("cargo_norm")
    assert g.loc["X", "ganador"] == "a" and g.loc["Z", "ganador"] == "b"


def test_tabla_texto_legible():
    tr, ts = _datos(); p_tr, p_ts = _parts(tr, ts)
    t = tabla_texto(comparar(tr, ts, p_tr, p_ts, referencia="azar", n_bootstrap=10))
    assert "verdadera" in t and "cobertura" in t.lower()


def test_guardar_curvas_escribe_png(tmp_path):
    tr, ts = _datos()
    p = predecir(tr, ts.assign(_c=ts["rol_verdadero"]), "_c")
    guardar_curvas({"v": curva_riesgo(ts, p, n_puntos=9)}, tmp_path / "riesgo.png")
    guardar_curvas_coste({"v": curva_coste(ts, p, np.linspace(.1, 1., 5))},
                         tmp_path / "coste.png")
    assert (tmp_path / "riesgo.png").stat().st_size > 0
    assert (tmp_path / "coste.png").stat().st_size > 0
```

- [ ] **Paso 2: Verificar que falla**

- [ ] **Paso 3: Implementar**

```python
# src/benchmarking/evaluacion/informe.py
"""Tabla comparativa pareada, curvas y desglose por etiqueta."""
import matplotlib
matplotlib.use("Agg")                     # sin ventana: corre en job y en CI
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from .metricas import (error_y_cobertura, replicas_bootstrap, ic_diferencia,
                       omega2_intra_empresa, curva_riesgo, augrc)
from .referencia import predecir, aplicar_abstencion


def comparar(train, test, particiones_tr, particiones_ts, referencia="CARGO crudo",
             max_sd=None, n_bootstrap=400, semilla=20260805):
    """Una fila por metodo, con la DIFERENCIA PAREADA contra `referencia`.

    Se reporta la diferencia y no dos IC marginales porque leer solapamiento no es una
    prueba (Schenker & Gentleman 2001) y porque el efecto empresa —que domina el error y
    es identico para los dos metodos— se cancela en la diferencia y se paga entero en el
    contraste marginal.
    """
    nombres = list(particiones_ts)
    replicas = replicas_bootstrap(train, test, particiones_tr, particiones_ts,
                                  n=int(n_bootstrap), semilla=semilla, max_sd=max_sd)
    ref = referencia if referencia in nombres else nombres[0]

    filas = []
    for nombre in nombres:
        ts = test.assign(_celda=particiones_ts[nombre].astype(str).to_numpy())
        tr = train.assign(_celda=particiones_tr[nombre].astype(str).to_numpy())
        p = predecir(tr, ts, "_celda")
        y_ref = aplicar_abstencion(p, max_sd=max_sd)
        base = error_y_cobertura(ts, y_ref)
        d = ic_diferencia(replicas, nombre, ref) if nombre in replicas else {}
        filas.append({"metodo": nombre,
                      "n_celdas": int(tr["_celda"].nunique()),
                      "cobertura": base["cobertura"], "mae": base["mae"],
                      "sesgo": base["sesgo"], "mae_intra": base["mae_intra"],
                      "augrc": augrc(curva_riesgo(ts, p)),
                      "omega2": omega2_intra_empresa(ts.assign(y=ts["y"]), "_celda"),
                      "dif_vs_ref": d.get("dif", float("nan")),
                      "ic_bajo": d.get("ic_bajo", float("nan")),
                      "ic_alto": d.get("ic_alto", float("nan"))})
    return pd.DataFrame(filas)


def tabla_texto(comparacion):
    c = comparacion.copy()
    c["cobertura"] = (100 * c["cobertura"]).round(1).astype(str) + "%"
    for col in ("mae", "sesgo", "mae_intra", "augrc", "omega2",
                "dif_vs_ref", "ic_bajo", "ic_alto"):
        if col in c:
            c[col] = c[col].round(4)
    return c.to_string(index=False)


def frontera_ab(curva_a, curva_b):
    """El coste `c` donde se cruzan dos curvas de riesgo: la frontera A/B de D-004.

    Por debajo de ese coste manda la precision; por encima manda la cobertura. Convierte
    tres desenlaces narrativos en un punto de corte medible. NaN si no se cruzan en el
    rango barrido — que tambien es un resultado: un metodo domina en todo el rango.
    """
    x = curva_a["coste"].to_numpy(float)
    d = curva_a["riesgo"].to_numpy(float) - np.interp(x, curva_b["coste"], curva_b["riesgo"])
    cambio = np.nonzero(np.sign(d[:-1]) * np.sign(d[1:]) < 0)[0]
    if cambio.size == 0:
        return float("nan")
    i = int(cambio[0])
    return float(x[i] + (x[i + 1] - x[i]) * abs(d[i]) / (abs(d[i]) + abs(d[i + 1])))


def ganador_por_etiqueta(test, refs, col="cargo_norm", minimo=20):
    """Por etiqueta de CARGO con suficiente gente en test: MAE de cada metodo y ganador.

    D-004 declara el desenlace C —complementariedad— el mas probable, y hasta v3 no habia
    NINGUNA metrica que lo operacionalizara. Si ocurre C, esta tabla es el entregable: el
    mapa de donde conviene cada metodo.
    """
    y = pd.to_numeric(test["y"], errors="coerce")
    filas = []
    for etiqueta, idx in test.groupby(test[col].astype(str)).groups.items():
        if len(idx) < int(minimo):
            continue
        fila = {col: etiqueta, "n": int(len(idx))}
        maes = {}
        for nombre, r in refs.items():
            e = (y.loc[idx] - pd.to_numeric(pd.Series(r).reindex(test.index).loc[idx],
                                            errors="coerce")).abs()
            maes[nombre] = float(e.mean()) if e.notna().any() else float("nan")
            fila[f"mae_{nombre}"] = maes[nombre]
        validos = {k: v for k, v in maes.items() if np.isfinite(v)}
        fila["ganador"] = min(validos, key=validos.get) if validos else None
        filas.append(fila)
    return pd.DataFrame(filas)


def guardar_curvas(curvas, ruta_png):
    """Riesgo generalizado frente a cobertura. Denominador N para todos los metodos, asi
    que CARGO al 60,5% y el arquetipo al 100% se leen en la misma escala."""
    fig, ax = plt.subplots(figsize=(7, 5))
    for nombre, c in curvas.items():
        ax.plot(c["cobertura"], c["riesgo_generalizado"], marker="o", label=nombre)
    ax.set_xlabel("cobertura (fracción de personas con referencia)")
    ax.set_ylabel("riesgo generalizado (error total / N)")
    ax.set_title("Riesgo generalizado — el área bajo cada curva es su AUGRC")
    ax.grid(alpha=0.3); ax.legend(); fig.tight_layout()
    fig.savefig(ruta_png, dpi=150); plt.close(fig)


def guardar_curvas_coste(curvas, ruta_png, frontera=None):
    """Riesgo frente al coste de abstenerse, con la frontera A/B marcada."""
    fig, ax = plt.subplots(figsize=(7, 5))
    for nombre, c in curvas.items():
        ax.plot(c["coste"], c["riesgo"], marker="o", label=nombre)
    if frontera is not None and np.isfinite(frontera):
        ax.axvline(frontera, ls="--", c="k", alpha=.6)
        ax.annotate(f"frontera A/B\nc = {frontera:.3f}", (frontera, ax.get_ylim()[1] * .9),
                    ha="left", fontsize=9)
    ax.set_xlabel("coste de no dar respuesta (en unidades de log-SBU)")
    ax.set_ylabel("riesgo generalizado")
    ax.set_title("Precisión frente a cobertura: dónde deja de compensar callarse")
    ax.grid(alpha=0.3); ax.legend(); fig.tight_layout()
    fig.savefig(ruta_png, dpi=150); plt.close(fig)
```

- [ ] **Paso 4: Verificar** → 8 passed

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/evaluacion/informe.py tests/test_evaluacion_informe.py
git commit -m "feat(evaluacion): informe con diferencia pareada, frontera A/B y ganador por etiqueta"
```

---

### Tarea 13: Subcomando `benchmarking evaluar`

**Actualizada en v3** a las interfaces nuevas: seis rivales (incluida la ablación de `CARGO`), techo
alcanzable, oráculo, curvas de riesgo, frontera A/B y desgloses por subgrupo.

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
    ev.add_argument("--bootstrap", type=int, default=400)
    ev.add_argument("--max-sd", type=float, default=None,
                    help="umbral de anchura predictiva; el del pre-registro")
```

Y en el cuerpo, tras la rama `construir-universo`:

```python
    elif args.cmd == "evaluar":
        import pathlib
        import numpy as np
        import pandas as pd
        from .evaluacion import datos, splits, particiones, informe, metricas, embeddings
        from .evaluacion.referencia import predecir, aplicar_abstencion
        from .evaluacion.representacion import normalizar_mfa

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
        print("   comprobar contra el hash del pre-registro ANTES de leer nada")
        tr, ts = splits.partir(marco, te)

        k = int(marco["celda"].nunique())
        cl_emb = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project,
                                           s.vertex_location)
        emb_tr = embeddings.embeber(tr["cargo_norm"].tolist(), cl_emb, s.vertex_embedding_model)
        emb_ts = embeddings.embeber(ts["cargo_norm"].tolist(), cl_emb, s.vertex_embedding_model)

        def escalera(df, emb):
            return {"arquetipo": df["celda"].astype(str),
                    "CARGO crudo": particiones.cargo_crudo(df),
                    "solo-texto (k igualado)": particiones.solo_texto(df, k, emb),
                    "aleatoria (k igualado)": particiones.aleatoria(df, k),
                    "oraculo (bandera roja)": particiones.oraculo_salarial(tr, df, k)}

        p_tr, p_ts = escalera(tr, emb_tr), escalera(ts, emb_ts)

        # --- la tabla: diferencia PAREADA contra CARGO --------------------------
        comp = informe.comparar(tr, ts, p_tr, p_ts, referencia="CARGO crudo",
                                max_sd=args.max_sd, n_bootstrap=args.bootstrap)
        comp.to_csv(salida / "comparacion.csv", index=False)
        print(informe.tabla_texto(comp))

        # --- ablacion: cuanto del resultado es particion y cuanto estimador -----
        # El estimador inverso-varianza FORTALECE a CARGO (encoge mas donde las celdas
        # son pequenas). Reportarlo es lo que impide atribuir al agrupamiento una mejora
        # que en realidad vino del estimador.
        p_cargo = predecir(tr.assign(_c=p_tr["CARGO crudo"]), ts.assign(_c=p_ts["CARGO crudo"]), "_c")
        ing = metricas.error_y_cobertura(
            ts, aplicar_abstencion(p_cargo.assign(
                y_ref_bruto=ts.assign(_c=p_ts["CARGO crudo"]).groupby("_c")["y"].transform("median")),
                max_sd=args.max_sd))
        print(f"\nablacion CARGO con estimador ingenuo: MAE={ing['mae']:.4f} "
              f"cobertura={ing['cobertura']:.1%}")

        # --- techo alcanzable: el denominador honesto ---------------------------
        cols = ["antiguedad_total", "pct_fijo", "pct_comisiones", "pct_extras", "pct_otros"]
        X_tr = normalizar_mfa([emb_tr, tr[cols].fillna(tr[cols].median()).to_numpy(float)])
        X_ts = normalizar_mfa([emb_ts, ts[cols].fillna(tr[cols].median()).to_numpy(float)])
        techo = particiones.techo_alcanzable(tr, ts, X_tr, X_ts)
        r_techo = metricas.error_y_cobertura(ts, techo)
        print(f"techo alcanzable: MAE={r_techo['mae']:.4f}  "
              f"(cota teorica: >= 0,623 x MAE aleatorio; por debajo huele a fuga)")

        # --- curvas y frontera A/B ----------------------------------------------
        preds = {n: predecir(tr.assign(_c=p_tr[n]), ts.assign(_c=p_ts[n]), "_c") for n in p_ts}
        curvas = {n: metricas.curva_riesgo(ts, p) for n, p in preds.items()}
        informe.guardar_curvas(curvas, salida / "riesgo_generalizado.png")

        costes = np.linspace(0.05, 1.5, 30)
        cc = {n: metricas.curva_coste(ts, p, costes) for n, p in preds.items()}
        f = informe.frontera_ab(cc["arquetipo"], cc["CARGO crudo"])
        informe.guardar_curvas_coste(cc, salida / "curva_coste.png", frontera=f)
        print(f"\nfrontera A/B: c* = {f:.4f}" if np.isfinite(f)
              else "\nfrontera A/B: no se cruzan — un metodo domina en todo el rango")

        # --- verificacion distributiva (obligatoria) ----------------------------
        refs = {n: aplicar_abstencion(p, max_sd=args.max_sd) for n, p in preds.items()}
        for eje in ("sexo", "provincia", "segmento", "ciiu_n1"):
            if eje not in ts.columns:
                continue
            sub = metricas.por_subgrupo(ts, refs["arquetipo"], eje)
            sub.to_csv(salida / f"subgrupo_{eje}.csv", index=False)
            print(f"\n== {eje} ==\n{sub.round(4).to_string(index=False)}")

        # --- ganador por etiqueta: operacionaliza el desenlace C ----------------
        g = informe.ganador_por_etiqueta(ts, refs)
        g.to_csv(salida / "ganador_por_etiqueta.csv", index=False)
        if not g.empty:
            print("\nreparto de victorias por etiqueta de CARGO:")
            print(g["ganador"].value_counts(normalize=True).round(3).to_string())

        print(f"\nresultados en {salida}")
```

- [ ] **Paso 4: Verificar** — tests pasan y `python -m benchmarking.cli --help` muestra `evaluar`

- [ ] **Paso 5: Commit**

```bash
git add src/benchmarking/cli.py tests/test_cli.py
git commit -m "feat(cli): evaluar con escalera completa, curvas de riesgo y subgrupos"
```

---

### Tarea 14: Pre-registro

Se congela **antes** de tocar el conjunto de test. **Reescrito en v3**: la versión anterior tenía una
regla de abstención justificada con una cita que no se sostiene, un criterio A que no se podía dibujar,
y ninguna magnitud detectable declarada.

**Archivos:** Crear `docs/preregistro.md`

- [ ] **Paso 1: Escribir el documento**

```markdown
# Pre-registro — Sub-proyecto 1 (banco de validación)

Congelado el <FECHA>, antes de ejecutar nada contra el conjunto de test.
Commit de congelación: <HASH>. Hash sha256 del listado de empresas apartadas: <HASH_SPLIT>.

## Qué se compara

**Particiones, no modelos.** Todos los métodos comparten el mismo estimador y el mismo
split; lo único que cambia entre ellos es cómo se agrupa a la gente. Sin esto, una
diferencia sería atribuible al estimador, al split o al agrupamiento, y no habría forma de
saber a cuál.

Compiten: `CARGO` crudo (sin podar), `CARGO` con estimador ingenuo (ablación), arquetipo,
solo-texto a k igualado, y aleatoria a k igualado. Se reportan además el **techo
alcanzable** (GBM sobre observables, entrenado en train) como denominador de escala y el
**oráculo salarial** (k-means sobre `y`, ajustado sólo en train) como bandera roja.

La ablación no es decorativa: el estimador nuevo **fortalece a `CARGO`**, porque el
encogimiento inverso-varianza ayuda más donde las celdas son pequeñas. Reportarla separa
cuánto del resultado viene del agrupamiento y cuánto del estimador.

## Estimador de la referencia

Por celda `c`, sobre `y = log(sueldo / SBU(año))`:

    y_fi = mu_c + a_f + e_fi        a_f ~ (0, tau^2)     e_fi ~ (0, sigma^2)

`tau^2` y `sigma^2` se estiman **una vez, globalmente**, sobre train. El voto de cada
empresa donante es la mediana de sus personas en la celda, y pesa

    w_f = 1 / (tau^2 + sigma^2 / n_f)

La referencia es el **cuantil ponderado al 50%** de esos votos, **excluyendo la empresa de
la persona evaluada** (leave-company-out). El peso es inverso-varianza: **derivado, no
elegido**. Interpola entre "una empresa un voto" y "una persona un voto", y acota el ratio
máximo de pesos en `1 + sigma^2/tau^2`.

La distribución predictiva de una persona de una empresa nueva es
`(mu_c, tau^2 + sigma^2 + 1/suma(w_f))`.

## Métrica primaria

**MAE** de `y` fuera de muestra, sobre las filas donde el método no se abstiene.

Se reportan junto a ella, siempre:
- **sesgo con signo**, global y por decil de la predicción (calibración);
- **MAE intra-empresa**, que descuenta el desplazamiento común de cada empresa —
  impredecible bajo leave-company-out e idéntico para todos los métodos;
- **CRPS** de la predictiva normal. Es estrictamente propio y se reduce al error absoluto
  cuando el pronóstico es determinista, así que no sustituye al MAE: lo contiene.

## Métrica co-primaria

**Cobertura**: fracción de personas de test con referencia.

## Escalar comparable entre métodos con cobertura distinta

**AUGRC** — área bajo la curva de riesgo generalizado frente a cobertura. El riesgo
generalizado promedia sobre **toda** la población (denominador `N` para todos), no sobre
las aceptadas, así que `CARGO` al 60,5% y el arquetipo al 100% se leen en la misma escala.
No se usa AURC: viola monotonicidad.

## Regla de abstención

**El criterio es la anchura predictiva**, no un conteo de donantes. El método se abstiene
cuando `raiz(tau^2 + sigma^2 + 1/suma(w_f))` supera el umbral `X`, declarado en unidades
interpretables (**<X>**, equivalente a un IC al 80% de ±<X>% en dólares) antes de tocar el
test. Un conteo no dice nada sobre la precisión: 500 personas de 3 empresas homogéneas dan
una referencia mejor que 20 personas de 10 empresas dispares.

Se aplican además **dos suelos que no son criterios de precisión**:

- **≥3 empresas donantes** — identificabilidad de `tau^2` (con 2 empresas no se separa la
  varianza entre de la de dentro) y confidencialidad (con 2 donantes, cada uno deduce al
  otro).
- **ninguna empresa con más del 80% de las personas donantes** — dominancia. `e >= 3` no
  impide que una empresa con el 95% de la gente domine si hay otras dos con una persona.

Precedente institucional para ambos: la regla de supresión de **QCEW** (menos de tres
establecimientos, o uno con más del 80% del empleo). Se cita por lo que dice —es una regla
de *disclosure*, no de estimación— y la fuente localizada es secundaria.

> **No se cita OEWS.** La versión anterior de este documento justificaba `m=5` con la
> práctica del programa OEWS del BLS. Esa cita se retira: no pudo verificarse contra el
> documento primario, y hay indicios de que el "5" gobierna la imputación por no respuesta
> y no la publicación. Ver D-011. Una cita que no se puede abrir no sostiene nada.

Ninguna conclusión depende de un valor concreto: se reporta la **curva completa** barriendo
el coste de abstenerse.

## Criterio de éxito

**Éxito = A o B.**

- **A** — el arquetipo tiene **menor MAE** que `CARGO` crudo, con el **IC de la diferencia
  pareada** sin cruzar el cero. Pareada, sobre la intersección de filas donde ambos
  responden, con números aleatorios comunes.
- **B** — MAE equivalente, pero cobertura sustancialmente mayor. Operativamente: el
  arquetipo tiene **menor AUGRC**, y la frontera de coste `c*` donde se cruzan las curvas
  cae **por debajo** del coste plausible de no dar respuesta.
- **C** (complementariedad) **se reporta como hallazgo, no como victoria**, con la tabla de
  ganador por etiqueta.
- **D** (no gana en ningún lado) se reporta como resultado negativo.

## Magnitud mínima detectable

Declarada antes de mirar: el banco debe distinguir la partición verdadera de una con **x%
de las personas reasignadas al azar** para **x = <X>**, calibrado sobre data sintética
(Tarea 10). Un criterio sin MDE no es un criterio: si el instrumento no distingue el 20%
de ruido, un empate no significa "iguales", significa "no medible".

## Verificación distributiva (obligatoria, no opcional)

Se reportan **error y cobertura por subgrupo a lo largo de toda la curva**, no sólo en el
agregado, para: `sexo`, `provincia`, `segmento` (tamaño SCVS) y `ciiu_n1`.

Al bajar la cobertura, el riesgo de un subgrupo puede empeorar aunque el global mejore
(Shah et al., ICML 2022). Las celdas que no alcanzan donantes no son un subconjunto
aleatorio: son ocupaciones raras, empresas pequeñas y provincias fuera de Pichincha y
Guayas. **El banco puede reportar un MAE excelente mientras la referencia se degrada justo
para quien más la necesita.** `sexo` se usa sólo para esto y para el Oaxaca; nunca es
feature.

## Regla de selección de modelo — los tres elementos

Ninguno de estos tres se elige con la métrica salarial:

1. **Granularidad** (k, altura de corte, tamaño mínimo) → por **estabilidad**: ARI entre
   submuestras de empresas.
2. **Familia** de clustering → por **estabilidad**, igual.
3. **Pesos de bloque** → **no se eligen**. Normalización MFA (cada bloque dividido por su
   primer valor singular), sin parámetros libres.

El **test de validez externa** (predecir ISCO-08) comprueba que las celdas son ocupaciones
y no bandas de sueldo.

## Qué se decide dentro del train, y qué toca el test

El **20% de test se toca una vez, al final**. Se deciden en **CV agrupada por empresa
dentro del 80% de train**: la elección A vs B, el valor de `k`, el umbral de abstención `X`
y cualquier ajuste de representación. Seleccionar sobre el conjunto bloqueado invalida el
pre-registro, y ya ocurrió una vez en el plan v2 sin que nadie lo viera.

## Cota teórica del rango dinámico

Con `eta^2_empresa = 0,388` medido y el efecto empresa inobservable bajo leave-company-out,
`Var(error) >= 0,388 * Var(y)` para **cualquier** partición. En desviación estándar, el
mejor método posible llega a `raiz(0,388) = 0,623` del MAE aleatorio: **todo el rango
disponible es el 37,7% del piso**. Cualquier resultado por debajo de esa cota indica fuga
de información, no mérito.

## Incertidumbre

Bootstrap de **dos etapas** con reemplazo: se remuestrean empresas de train (hace variar
`mu_c`, que en `CARGO` se estima con 3–5 empresas) y empresas de test, con **números
aleatorios comunes** entre métodos. Nunca por filas. <N> réplicas.

> **Límite declarado.** No existe referencia canónica para esta construcción. Bates, Hastie
> & Tibshirani (2024) muestran que los métodos estándar no estiman este estimando. La
> construcción es defendible y se describe explícitamente; **no se presenta como práctica
> establecida.**

## Tratamiento de la censura en el SBU

`sueldo_bajo_sbu` está en cuarentena, así que `y >= 0` está censurada con masa puntual en
cero. Medido en la Tarea 2b: **<X>%** de las filas evaluables. Tratamiento declarado:
**<A o B>**. Elegido antes de mirar el test y sin comparar cuál favorece al arquetipo.

## Conjunto de test

20% de las empresas, estratificado por segmento SCVS y sección CIIU, con mínimo una empresa
por estrato, semilla 20260805. Bloqueado hasta la validación final; su identidad queda
fijada por el hash de arriba.
```

- [ ] **Paso 2: Rellenar los seis `<...>`** con los valores medidos y decididos. **Ninguno se
rellena mirando el test.**

- [ ] **Paso 3: Commit**

```bash
git add docs/preregistro.md
git commit -m "docs: pre-registro v3 del banco, congelado antes del test"
```

---

### Tarea 15: Los dos baselines (experimento E0)

Estrena el banco y responde en la semana ~4 si la composición aporta (enmienda de D-003).

> **Corregido en v3.** La versión anterior evaluaba A y B *"sobre el mismo held-out"* y de ahí decidía
> si retirar media arquitectura del spec de clustering. Es **selección sobre el conjunto bloqueado**:
> el mismo fallo que `revision_jueces.md` §3 denunció para los pesos de bloque y que se aceptó como
> corrección 3 de D-009 — **y reapareció dos secciones más abajo sin que nadie lo viera**.
>
> A vs B se decide en **CV agrupada por empresa dentro del 80% de train**. El 20% se toca una vez, al
> final, con el ganador ya elegido.

**Archivos:** Crear `research/experimentos/e0_banco/construir_baselines.py`,
`research/experimentos/e0_banco/decidir_ab.py` y su `README.md`

- [ ] **Paso 1: Escribir el constructor de baselines**

```python
# research/experimentos/e0_banco/construir_baselines.py
"""E0 — dos baselines de k-means para estrenar el banco y medir si la composicion aporta.

Baseline A: con composicion, sobre 2024-2025.
Baseline B: sin composicion (texto + centro + antiguedad), sobre todos los anios.

Este script SOLO construye las particiones. La decision A vs B es de `decidir_ab.py`, y se
toma dentro del train: aqui no se mira ningun resultado.

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
from benchmarking.evaluacion import datos, embeddings, estabilidad, splits
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
    """k por estabilidad: gana el que mas se reproduce entre submuestras DE EMPRESAS.

    Nunca por acierto salarial. Es el elemento 1 de D-005 Enmienda 1.
    """
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

- [ ] **Paso 2: Escribir el decisor A vs B — dentro del train (NUEVO en v3)**

```python
# research/experimentos/e0_banco/decidir_ab.py
"""Decide A vs B en CV agrupada por empresa DENTRO DEL TRAIN. El test no se toca.

Dos precauciones que sin ellas la comparacion no significa nada:

1. **El test se aparta primero y no vuelve a aparecer.** Se reconstruye con la misma
   semilla y se verifica contra el hash del pre-registro.
2. **A y B se comparan sobre la INTERSECCION de personas.** A vive en 2024-2025 con
   composicion, B en todos los anios: sin intersecar, la diferencia mezclaria "que
   representacion es mejor" con "que subpoblacion es mas facil".
"""
import argparse
import pathlib
import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.model_selection import GroupKFold
from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.evaluacion.referencia import predecir, aplicar_abstencion
from benchmarking.evaluacion.metricas import error_y_cobertura, curva_riesgo, augrc

SEMILLA = 20260805


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="research/experimentos/e0_banco")
    ap.add_argument("--pliegues", type=int, default=5)
    args = ap.parse_args()

    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    d = pathlib.Path(args.dir)

    marco = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    te = splits.empresas_test(marco)
    train, _ = splits.partir(marco, te)
    print(f"train: {len(train):,} filas, {train.empresa_ruc.nunique():,} empresas "
          f"(test apartado: {len(te)} empresas, NO se toca aqui)")

    partes = {}
    for nombre in ("a", "b"):
        p = pd.read_parquet(d / f"baseline_{nombre}.parquet")
        partes[nombre] = p.rename(columns={"celda": f"celda_{nombre}"})

    m = train.merge(partes["a"], on=["id_hash", "numero_proceso"], how="inner")
    m = m.merge(partes["b"], on=["id_hash", "numero_proceso"], how="inner")
    print(f"interseccion A n B: {len(m):,} filas — la comparacion se hace SOLO aqui")

    grupos = m["empresa_ruc"].to_numpy()
    filas = []
    for pliegue, (i_tr, i_va) in enumerate(GroupKFold(n_splits=args.pliegues).split(m, groups=grupos)):
        tr, va = m.iloc[i_tr], m.iloc[i_va]
        for nombre in ("a", "b"):
            col = f"celda_{nombre}"
            pred = predecir(tr, va, col)
            r = error_y_cobertura(va, aplicar_abstencion(pred))
            filas.append({"pliegue": pliegue, "baseline": nombre.upper(),
                          "mae": r["mae"], "mae_intra": r["mae_intra"],
                          "cobertura": r["cobertura"],
                          "augrc": augrc(curva_riesgo(va, pred))})

    res = pd.DataFrame(filas)
    res.to_csv(d / "decision_ab_cv.csv", index=False)
    print("\n" + res.groupby("baseline")[["mae", "mae_intra", "cobertura", "augrc"]]
                    .agg(["mean", "std"]).round(4).to_string())

    # Diferencia PAREADA por pliegue: los dos baselines ven exactamente las mismas empresas.
    pv = res.pivot(index="pliegue", columns="baseline", values="mae")
    dif = (pv["A"] - pv["B"]).to_numpy(float)
    print(f"\nMAE(A) - MAE(B) por pliegue: {np.round(dif, 4)}")
    print(f"media = {dif.mean():+.4f}   (negativo => la composicion APORTA)")
    print("\nLECTURA: si B iguala o supera a A, media arquitectura del spec de clustering "
          "(ILR, gate, residualizacion, IPW) se retira CON EVIDENCIA. Con 5 pliegues no "
          "hay potencia para un contraste formal: es una senal de direccion, y asi debe "
          "reportarse.")


if __name__ == "__main__":
    main()
```

- [ ] **Paso 3: Escribir el README del experimento**

```markdown
# E0 — Estreno del banco con dos baselines

## Qué contesta

1. ¿El banco funciona sobre datos reales? (ya validado con data sintética en
   `tests/test_evaluacion_banco.py`)
2. **¿La composición aporta?** — enmienda de D-003. Si B iguala a A, media arquitectura del
   spec de clustering se puede retirar con evidencia.

## Cómo se corre

```bash
# 1. construir las dos particiones (no mira ningun resultado)
python research/experimentos/e0_banco/construir_baselines.py

# 2. decidir A vs B DENTRO DEL TRAIN
python research/experimentos/e0_banco/decidir_ab.py

# 3. y solo entonces, una vez, con el ganador ya elegido:
benchmarking evaluar --particion research/experimentos/e0_banco/baseline_<ganador>.parquet \
                     --salida research/experimentos/e0_banco/final
```

## Cómo se lee

- **Paso 2** es la decisión de arquitectura, y se toma sobre CV agrupada por empresa dentro
  del train, con A y B intersecados. Con 5 pliegues no hay potencia para un contraste
  formal: es una señal de dirección.
- **Paso 3** es la única vez que el test se toca. Se lee sobre la **curva de riesgo
  generalizado** (denominador `N` para todos) y la **diferencia pareada** contra `CARGO`.

Recordatorio del pre-registro: **k se eligió por estabilidad, no por resultado salarial**, y
los bloques se normalizaron con MFA, sin pesos afinados.
```

- [ ] **Paso 4: Commit**

```bash
git add research/experimentos/e0_banco
git commit -m "feat(research): E0 con la decision A/B dentro del train"
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
  Esperado: los 78 actuales más ~70 nuevos.

- [ ] **Paso 2: La prueba de aceptación, explícita** —
  `.venv\Scripts\python.exe -m pytest tests/test_evaluacion_banco.py -v` → 9 passed.
  Es la que autoriza a fiarse de las mediciones.

- [ ] **Paso 3: Sin data real en el repositorio** —
  `git log --stat -25 | grep -iE "\.parquet|\.csv|\.xlsx" || echo "sin data real"`

- [ ] **Paso 4: El pre-registro no tiene huecos** — `grep -n "<[A-Z]" docs/preregistro.md`
  debe salir vacío. Un `<X>` sin rellenar significa que se congeló un criterio incompleto.

- [ ] **Paso 5: El hash del split coincide** con el del pre-registro. Si no coincide, el test-set
  cambió después de congelar y **todos los resultados quedan invalidados**.

- [ ] **Paso 6: Ninguna decisión se tomó mirando el test** — repasar contra
  `preregistro.md §Qué se decide dentro del train`: A vs B, `k`, el umbral `X` y la representación.
  Es la corrección 3 de D-009, que ya reapareció una vez en la Tarea 15 del plan v2.

- [ ] **Paso 7: Commit final**

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
- Cuantificar el sesgo de movilidad limitada sobre el η²_empresa. **Sube de prioridad**: fija la cota
  teórica del rango dinámico. Con 0,388 el techo posible es 0,623 del MAE aleatorio; si el sesgo lo
  infla hacia el ~20% de Card et al. (2018), el rango disponible pasa del 37,7% al 55,3%.

## Pendientes de D-011 que este plan NO cubre

- **Verificar la cita de OEWS contra el PDF primario.** `bls.gov` bloquea el acceso automatizado
  (403). Hay que abrirlo a mano y cerrar el punto. Mientras tanto la cita está retirada, no refutada.
- **Verificar las 17 fuentes marcadas ▫** en D-011 §Fuentes antes de usarlas en el texto de la tesis.
- **Variante anclada a la empresa** — `ŷ_fi = μ̂_c` + mediana del residuo de los *otros* empleados de
  su empresa. No es circular y **es lo que el producto hace**: el cliente entrega su nómina. Hoy sólo
  se mide una tarea que nadie ejecuta. Coste ~1 día; va al sub-proyecto 2.
- **Curva de aprendizaje** — MAE con 10/25/50/100% de empresas de train. El ranking entre clases de
  modelo se cruza con `n` (Perlich, Provost & Simonoff 2003), y la debilidad de `CARGO` son
  precisamente las celdas escasas.
- **Test-retest sobre la entrega, no sobre la etiqueta** — `|y_ref(2024) − y_ref(2025)|` frente al
  MAE. Si la referencia se mueve tanto como el error, el producto no sirve aunque el MAE sea bueno.
- **Retirar `cargo_plantilla`** del pipeline (D-010): es idéntica a `cargo`, confirmado por el equipo.

## La regla que sale de D-011

**Toda corrección aceptada se reaudita como si fuera una decisión nueva** — porque lo es.
D-009 corrección 1 arregló la ponderación y desemparejó el estimador de la métrica. D-009 corrección 3
prohibió seleccionar sobre el test, y dos secciones más abajo la Tarea 15 lo volvía a hacer. Ninguna
de las dos se detectó al revisar el plan: se detectaron auditando el plan **contra sus propias
correcciones**.
