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
