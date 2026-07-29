import io
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

_ESQUEMA = yaml.safe_load(
    (Path(__file__).parent.parent / "config" / "esquema_plantilla.yaml").read_text(
        encoding="utf-8"
    )
)


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
    df[["comisiones", "extras", "otros"]] = df[["comisiones", "extras", "otros"]].fillna(0)
    return df[df["identificacion"].notna() & df["sueldo"].notna()].reset_index(
        drop=True
    )


def calcular_composicion(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["total"] = (
        out["sueldo"] + out["comisiones"] + out["extras"] + out["otros"]
    )
    out = out[out["total"] > 0].copy()
    for rubro, pct in [
        ("sueldo", "pct_fijo"),
        ("comisiones", "pct_comisiones"),
        ("extras", "pct_extras"),
        ("otros", "pct_otros"),
    ]:
        out[pct] = out[rubro] / out["total"]
    return out.reset_index(drop=True)
