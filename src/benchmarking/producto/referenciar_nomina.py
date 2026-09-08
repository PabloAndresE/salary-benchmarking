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
    # Se embebe el titulo COMPLETO. Enmascarar el rango parecia buena idea —dejaba el
    # area limpia y el lexico separaba los escalones— y esta MEDIDO que empeora: +6,0% de
    # error, IC [+0,038, +0,080]. La palabra de rango no dice solo el rango; `OPERARIO DE
    # PRODUCCION` y `ANALISTA DE PRODUCCION` quedan identicos al taparla y son trabajos
    # distintos. `lambda` lo delataba antes de medirlo: 1,90 en crudo contra 2,71
    # enmascarado, o sea peor representacion del area.
    #
    # La jerarquia entra por el AJUSTE, no por la representacion: al vecino de otro
    # escalon se le resta el suyo y se le suma el del puesto preguntado. Medido: -0,0130,
    # IC [-0,0202, -0,0002]. Y corregir gana a filtrar (-0,0102, IC [-0,021, -0,002]):
    # descartar a los de otro escalon tira informacion util.
    print(f"construyendo la base: {len(marco):,} filas, {len(etiquetas):,} titulos")
    X = embeddings.embeber(etiquetas, cli, settings.vertex_embedding_model, cache=cache)
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
                        ruta_base=None, rehacer=False, segmento=None):
    # El SBU convierte el entregable a dolares: si no lo tenemos para ese anio, parar.
    # Usar el del anio anterior desplaza sistematicamente TODAS las cifras del informe.
    try:
        settings.get_sbu(int(anio), estricto=True)
    except ValueError as e:                      # mensaje limpio, como `leer_nomina`
        raise SystemExit(str(e))
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
        X = embeddings.embeber(nuevos, cli,
                               settings.vertex_embedding_model, cache=cache)
        cache.volcar()
        emb.update(dict(zip(nuevos, X)))

    ref = base.referenciar(titulos.tolist(), emb, anio=anio, segmento=segmento)
    if segmento:
        n_aj = int((ref["segmento"] != "").sum() and
                   (base.ajuste_seg[[base.idx[t] for t in titulos if t in base.idx]]
                    != 0).any(axis=1).sum())
        print(f"segmento del cliente: {segmento}   "
              f"cargos con correccion por tamano: {n_aj}")
    salida = pd.concat([df.reset_index(drop=True),
                        ref.drop(columns=["cargo"]).reset_index(drop=True)], axis=1)

    # Si la nomina trae sueldos, se puede comparar contra el mercado. Es la lectura que
    # el cliente quiere primero, y solo es posible porque el nos entrega su nomina: el
    # efecto empleador es irreducible frente a una empresa nueva, pero aqui nos lo dicen.
    cs = _buscar_sueldo(df, col_sueldo)
    resumen = por_puesto = None
    if cs:
        print(f"columna de sueldo '{cs}': se compara contra el mercado")
        det, por_puesto, resumen = comparar(salida, cs, col, ref, settings.get_sbu, anio)
        salida = det
    else:
        print("sin columna de sueldo: solo se emiten referencias")

    # La hoja del cliente no lleva escala logaritmica. `sd = 0.4685` no significa nada
    # para quien abre el archivo, y las columnas `_log` menos aun: todo lo que se entrega
    # va en dolares o en porcentaje. `incert_centro` sustituye a `sd` y si es legible —es
    # cuanto puede moverse la referencia de mercado, en tanto por uno.
    salida = salida.drop(columns=[c for c in salida.columns
                                  if c.endswith("_log") or c == "sd"])
    # La hoja de personas lleva la banda de PERSONAS (`p25`/`p75`); la de empresas se
    # queda fuera del detalle para no poner dos bandas al lado del mismo sueldo. Va en
    # `por_puesto`, que es donde la unidad coincide.
    #
    # Esto ultimo era falso hasta que se arreglo: `comparar` calculaba la banda de
    # empresas, decidia con ella la columna `lectura` y la botaba en la linea siguiente.
    # El cliente recibia el veredicto sin los numeros que lo sustentan, que es justo lo
    # que `_lectura` existe para evitar. Ahora `por_puesto` la lleva en dolares.
    salida = salida.drop(columns=[c for c in salida.columns
                                  if c.endswith("_emp")], errors="ignore")
    orden = ["referencia", "p10", "p25", "p75", "p90", "confianza", "incert_centro",
             "ancho_rel", "base", "empresas", "personas", "similitud"]
    primeras = [c for c in salida.columns if c not in orden]
    salida = salida[primeras + [c for c in orden if c in salida.columns]]
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
