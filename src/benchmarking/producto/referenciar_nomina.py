"""De la nomina de un cliente a un Excel con referencias. El caso de uso completo.

    benchmarking referenciar --nomina cliente.xlsx --salida referencias.xlsx

Lee un Excel o CSV con una columna de cargo, construye la base contra el universo (o la
reutiliza si ya esta cacheada), y devuelve un Excel con la referencia de mercado de cada
puesto, su rango y una marca de confianza.

Se responde SIEMPRE. La columna `confianza` es lo que separa una referencia con datos
detras de una analogia — y no se puede quitar del entregable.
"""
import pathlib

import numpy as np
import pandas as pd

from ..evaluacion import datos, embeddings
from .base_referencia import BaseReferencia
from .comparacion import comparar, texto_resumen
from .nivel import enmascarar

_POSIBLES = ("cargo", "cargo_norm", "puesto", "denominacion", "descripcion_cargo",
             "nombre_cargo", "titulo")
_POSIBLES_SUELDO = ("sueldo", "salario", "remuneracion", "sueldo_base",
                    "salario_base", "sueldo_mensual", "basico")


def leer_nomina(ruta, col_cargo=None):
    """Lee la nomina del cliente y localiza la columna de cargo.

    Excel o CSV, porque es lo que un area de RR.HH. tiene a mano. Si no se indica la
    columna se busca por nombre entre los habituales: pedirle al cliente que renombre
    columnas es una friccion que no hace falta.
    """
    ruta = pathlib.Path(ruta)
    df = (pd.read_csv(ruta, dtype=str) if ruta.suffix.lower() == ".csv"
          else pd.read_excel(ruta, dtype=str))
    if col_cargo:
        if col_cargo not in df.columns:
            raise SystemExit(f"la columna '{col_cargo}' no esta en {ruta.name}: "
                             f"{list(df.columns)}")
        return df, col_cargo
    normal = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _POSIBLES:
        if cand in normal:
            return df, normal[cand]
    raise SystemExit(f"no encuentro la columna de cargo en {ruta.name}. "
                     f"Columnas: {list(df.columns)}. Use --columna.")


def construir_base(cliente_bq, settings, anios=(2024, 2025), cache_emb=None,
                   ruta_base=None, rehacer=False):
    """Base de referencia sobre el universo completo, con persistencia.

    Sin partir en train/test: esto es produccion, no evaluacion. El split existe para
    medir si el metodo funciona, y esa pregunta se responde en `research/`.

    Construirla tarda minutos —un millon de filas y 65.081 titulos que embeber—, asi
    que se guarda. Una consulta de cliente no puede pagar ese coste: la base se
    reconstruye por lotes, cuando cambian los datos, y se sirve ya hecha.
    """
    cache = embeddings.CacheArchivo(cache_emb or settings.gcs_cache_embeddings
                                    or "emb_base.npz")
    cli = embeddings.cliente_vertex(settings.vertex_embedding_model,
                                    settings.bq_project, settings.vertex_location)

    if ruta_base and pathlib.Path(ruta_base).exists() and not rehacer:
        base = BaseReferencia.cargar(ruta_base, settings.get_sbu)
        print(f"base cargada de {ruta_base}: {len(base.celdas):,} puestos")
        emb = {c: base.Z[i] for i, c in enumerate(base.celdas)}
        return base, emb, cache, cli

    marco = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cliente_bq, settings.bq_project, settings.bq_dataset,
                           anios=anios), settings))
    etiquetas = sorted(set(marco["cargo_norm"].astype(str)))
    # Se embebe el titulo ENMASCARADO, no el crudo: el area sin contaminacion de rango.
    # `AUXILIAR DE CAJA` y `SUPERVISOR DE CAJA` caen en el mismo punto y es el lexico
    # quien los separa despues, con el efecto de escalon ya medido. Con el titulo crudo
    # el embedding los daba a 0,944 de similitud y los promediaba (D-012).
    areas = [enmascarar(e) for e in etiquetas]
    print(f"construyendo la base: {len(marco):,} filas, {len(etiquetas):,} titulos "
          f"({len(set(areas)):,} areas tras enmascarar el rango)")
    X = embeddings.embeber(areas, cli, settings.vertex_embedding_model, cache=cache)
    cache.volcar()
    emb = dict(zip(etiquetas, X))
    base = BaseReferencia.construir(marco, emb, settings.get_sbu)
    if ruta_base:
        base.guardar(ruta_base)
        print(f"base guardada en {ruta_base}")
    return base, emb, cache, cli


def _buscar_sueldo(df, col_sueldo):
    if col_sueldo:
        return col_sueldo if col_sueldo in df.columns else None
    normal = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _POSIBLES_SUELDO:
        if cand in normal:
            return normal[cand]
    return None


def referenciar_archivo(ruta_nomina, ruta_salida, cliente_bq, settings,
                        col_cargo=None, col_sueldo=None, anio=2025,
                        anios_base=(2024, 2025), cache_emb=None,
                        ruta_base=None, rehacer=False):
    df, col = leer_nomina(ruta_nomina, col_cargo)
    print(f"nomina: {len(df):,} filas, columna de cargo '{col}'")

    base, emb, cache, cli = construir_base(cliente_bq, settings, anios_base,
                                          cache_emb, ruta_base, rehacer)
    print(f"base: {len(base.celdas):,} puestos con datos   "
          f"tau={np.sqrt(base.tau2):.3f} sigma={np.sqrt(base.sigma2):.3f} "
          f"lambda={base.lam:.3f}")

    titulos = df[col].fillna("").astype(str).str.strip().str.upper()
    nuevos = sorted(set(titulos) - set(base.celdas))
    print(f"puestos distintos en la nomina: {titulos.nunique():,}   "
          f"sin datos directos: {len(nuevos):,}")
    if nuevos:
        X = embeddings.embeber([enmascarar(n) for n in nuevos], cli,
                               settings.vertex_embedding_model, cache=cache)
        cache.volcar()
        emb.update(dict(zip(nuevos, X)))

    ref = base.referenciar(titulos.tolist(), emb, anio=anio)
    salida = pd.concat([df.reset_index(drop=True),
                        ref.drop(columns=["cargo"]).reset_index(drop=True)], axis=1)

    # Si la nomina trae sueldos, se puede comparar contra el mercado. Es la lectura que
    # el cliente quiere primero, y solo es posible porque el nos entrega su nomina: el
    # efecto empleador es irreducible frente a una empresa nueva, pero aqui nos lo dicen.
    cs = _buscar_sueldo(df, col_sueldo)
    resumen = por_puesto = None
    if cs:
        print(f"columna de sueldo '{cs}': se compara contra el mercado")
        det, por_puesto, resumen = comparar(salida, cs, col, ref["referencia_log"],
                                            ref["confianza"], settings.get_sbu, anio)
        salida = det
    else:
        print("sin columna de sueldo: solo se emiten referencias")

    salida = salida.drop(columns=[c for c in salida.columns if c.endswith("_log")])
    pathlib.Path(ruta_salida).parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(ruta_salida) as xl:
        salida.to_excel(xl, sheet_name="detalle", index=False)
        if por_puesto is not None:
            por_puesto.to_excel(xl, sheet_name="por_puesto", index=False)

    reparto = ref["confianza"].value_counts(normalize=True)
    print("\nreparto de confianza:")
    for nivel in ("ALTA", "MEDIA", "BAJA"):
        print(f"  {nivel:<6} {reparto.get(nivel, 0.0):>6.1%}")
    if resumen is not None:
        print()
        print(texto_resumen(resumen, por_puesto))
        print()
    print(f"\nescrito en {ruta_salida}")
    return salida
