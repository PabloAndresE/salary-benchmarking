""".Esta SESGADA la referencia contra las empresas pequenas?

`07` y `08` midieron si segmentar por tamano estrecha la BANDA. No lo hace, y se descarto.
Pero esa no es la razon de fondo para usar el tamano. La razon es esta:

    GERENTE GENERAL en empresa PEQUENA
      banda de su segmento:  $1.011 - $2.330
      referencia que damos:  $3.032          <- fuera de su banda ENTERA

Si eso es sistematico, a una empresa pequena le estamos diciendo que paga muy por debajo
del mercado cuando entre sus pares esta bien. No es un problema de anchura: es que el
NUMERO DEL MEDIO esta en el sitio equivocado para una parte de los clientes.

POR QUE EL AGREGADO NO LO VE. El 56% de las filas son empresas GRANDES y el 26% no tiene
segmento. La referencia acierta donde esta la masa, y el promedio se lo traga.

QUE SE MIDE, sobre votos de empresas APARTADAS:

  A. SESGO por segmento: el error medio CON SIGNO, `voto - referencia`. Si la referencia es
     justa para todos, deberia ser ~0 en cada segmento. Si sale negativo en PEQUENA, les
     estamos diciendo que pagan poco cuando no es verdad.

  B. Lo mismo cruzado con el ESCALON lexico, porque la teoria dice que el tamano manda
     cuanto mas alto el puesto: un chofer maneja igual en una empresa grande.

  C. .Lo arregla segmentar? Mismo calculo con la referencia `cargo x segmento`
     (jerarquica: cae al cargo cuando la celda fina no aguanta).

Ojo con la lectura: aqui se mira SESGO y MAE del centro, no pinball de la banda. Son
preguntas distintas y `08` ya contesto la otra.

TODO SOBRE TRAIN. El 20% de test no se toca.
"""
import pathlib
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from google.cloud import bigquery

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
_s = import_module("07_segmentar_por_tamano")

from benchmarking.config.settings import cargar_settings
from benchmarking.evaluacion import datos, splits
from benchmarking.producto.nivel import nivel_lexico

SEM = 20260805
MIN_EMPRESAS = 3
ORDEN = ["MICROEMPRESA", "PEQUEÑA", "MEDIANA", "GRANDE", "NA"]
CASOS = ["GERENTE GENERAL", "CONTADOR", "JEFE DE BODEGA", "ASISTENTE CONTABLE",
         "VENDEDOR", "CHOFER", "AUXILIAR DE LIMPIEZA"]


def main():
    s = cargar_settings()
    cl = bigquery.Client(project=s.bq_project)
    mk = datos.marco_evaluable(datos.agregar_objetivo(
        datos.cargar_marco(cl, s.bq_project, s.bq_dataset, anios=(2024, 2025)), s))
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    train = train.copy()
    train["cargo_norm"] = train.cargo_norm.astype(str)
    train["_seg"] = train["segmento"].astype(str).fillna("NA")

    rng = np.random.default_rng(SEM)
    emp0 = np.array(sorted(train.empresa_ruc.unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    tr = train[~train.empresa_ruc.isin(val)].copy()
    ts = train[train.empresa_ruc.isin(val)].copy()
    print(f"construir {tr.empresa_ruc.nunique():,} empresas   "
          f"evaluar {ts.empresa_ruc.nunique():,}")

    tr["_c"] = tr.cargo_norm
    mod_cargo = _s.construir(tr, "_c")
    tr["_c"] = tr.cargo_norm + " | " + tr._seg
    mod_fino = _s.construir(tr, "_c")

    v = (ts.dropna(subset=["y"])
           .groupby(["cargo_norm", "empresa_ruc", "_seg"], sort=False)["y"]
           .median().reset_index(name="voto"))
    _, m_c, F_c, _ = _s.banda_de(mod_cargo, v.cargo_norm.to_numpy())
    _, m_f, F_f, _ = _s.banda_de(mod_fino, (v.cargo_norm + " | " + v._seg).to_numpy())
    ref_seg = np.where(F_f >= MIN_EMPRESAS, m_f, m_c)

    v["ref_hoy"] = m_c
    v["ref_seg"] = ref_seg
    v["nivel"] = v.cargo_norm.map(lambda c: nivel_lexico(c) or np.nan)
    v = v[np.isfinite(v.ref_hoy) & np.isfinite(v.ref_seg) & (F_c >= MIN_EMPRESAS)]
    v["e_hoy"] = v.voto - v.ref_hoy
    v["e_seg"] = v.voto - v.ref_seg
    print(f"{len(v):,} votos de empresa evaluables")

    pct = lambda x: np.exp(x) - 1.0
    print("\n" + "=" * 88)
    print("A. SESGO POR TAMANO DE EMPRESA. Si la referencia es justa, deberia ser ~0")
    print("=" * 88)
    print(f"  {'segmento':<14} {'votos':>7} {'sesgo HOY':>12} {'sesgo SEGMENT.':>16} "
          f"{'MAE hoy':>9} {'MAE segm.':>10}")
    for g in ORDEN:
        d = v[v._seg == g]
        if len(d) < 30:
            continue
        print(f"  {g:<14} {len(d):>7,} {pct(d.e_hoy.mean()):>+11.1%} "
              f"{pct(d.e_seg.mean()):>+15.1%} {d.e_hoy.abs().mean():>9.4f} "
              f"{d.e_seg.abs().mean():>10.4f}")
    print(f"  {'TODOS':<14} {len(v):>7,} {pct(v.e_hoy.mean()):>+11.1%} "
          f"{pct(v.e_seg.mean()):>+15.1%} {v.e_hoy.abs().mean():>9.4f} "
          f"{v.e_seg.abs().mean():>10.4f}")

    print("\n" + "=" * 88)
    print("B. CRUZADO CON EL ESCALON: .manda el tamano mas cuanto mas alto el puesto?")
    print("=" * 88)
    for col, et in (("e_hoy", "HOY (solo cargo)"), ("e_seg", "SEGMENTADA")):
        print()
        print(f"  referencia {et}")
        print(f"    {'nivel':<8} " + "  ".join(f"{g[:9]:>11}" for g in ORDEN[:4])
              + f"{'recorrido':>12}")
        for k in (1, 2, 3, 4, 5):
            d = v[v.nivel == k]
            if len(d) < 50:
                continue
            fila, vals = [], []
            for g in ORDEN[:4]:
                dd = d[d._seg == g]
                if len(dd) >= 20:
                    fila.append(f"{pct(dd[col].mean()):>+11.1%}")
                    vals.append(pct(dd[col].mean()))
                else:
                    fila.append(f"{'-':>11}")
            rec = f"{max(vals)-min(vals):>11.1%}" if len(vals) > 1 else f"{'-':>11}"
            print(f"    {k:<8} " + "  ".join(fila) + " " + rec)
    print("\n  (sesgo de la referencia de HOY. Negativo = les decimos que pagan menos de")
    print("   lo que paga su mercado real; positivo = les decimos que pagan de mas)")

    print("\n" + "=" * 88)
    print("C. CARGOS CONCRETOS: sesgo de hoy por segmento")
    print("=" * 88)
    print(f"  {'cargo':<24} " + "  ".join(f"{g[:9]:>11}" for g in ORDEN[:4]))
    for cg in CASOS:
        d = v[v.cargo_norm == cg]
        if len(d) < 20:
            continue
        for col, et in (("e_hoy", "hoy"), ("e_seg", "segm")):
            fila = []
            for g in ORDEN[:4]:
                dd = d[d._seg == g]
                fila.append(f"{pct(dd[col].mean()):>+11.1%}" if len(dd) >= 5 else f"{'-':>11}")
            print(f"  {cg[:19]+' ('+et+')':<24} " + "  ".join(fila))

    print("\n" + "=" * 88)
    print("D. .A CUANTA GENTE LE AFECTA? (empresas apartadas por segmento)")
    print("=" * 88)
    emp = ts.groupby("_seg")["empresa_ruc"].nunique()
    for g in ORDEN:
        if g in emp.index:
            print(f"  {g:<14} {int(emp[g]):>6} empresas  ({emp[g]/emp.sum():>5.1%})")


if __name__ == "__main__":
    main()
