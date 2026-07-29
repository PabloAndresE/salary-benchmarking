import pandas as pd

def unir_scvs(df_base: pd.DataFrame, df_scvs: pd.DataFrame) -> pd.DataFrame:
    out = df_base.merge(df_scvs, how="left", left_on="empresa_ruc", right_on="ruc")
    out["provincia"] = out["empresa_ruc"].astype(str).str[:2]
    return out.drop(columns=[c for c in ["ruc"] if c in out.columns])
