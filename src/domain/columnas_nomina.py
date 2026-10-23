"""Que columna de la nomina del cliente es el cargo y cual el sueldo.

Los nombres que se aceptan sin que el cliente tenga que decirlos. La construccion de la
base desde BigQuery y el flujo del CLI (`referenciar`) no son del servicio: siguen en la
rama `main`.
"""
_POSIBLES = ("cargo", "cargo_norm", "puesto", "denominacion", "descripcion_cargo",
             "nombre_cargo", "titulo")
_POSIBLES_SUELDO = ("sueldo", "salario", "remuneracion", "sueldo_base",
                    "salario_base", "sueldo_mensual", "basico")


def _buscar_sueldo(df, col_sueldo):
    if col_sueldo:
        return col_sueldo if col_sueldo in df.columns else None
    normal = {c.strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _POSIBLES_SUELDO:
        if cand in normal:
            return normal[cand]
    return None
