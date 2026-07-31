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
