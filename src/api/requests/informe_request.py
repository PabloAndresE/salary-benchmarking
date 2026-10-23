from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field


class CrearInformeRequestModel(BaseModel):
    """El formulario de `POST /informes`. Los campos van en camelCase (alias)."""

    model_config = ConfigDict(extra="forbid")

    archivo: UploadFile = Field(description="Excel o CSV. Primera hoja, encabezados en la fila 1.")
    anio: int | None = Field(
        None,
        description="Ano del SBU con el que se dolariza. Por defecto EL ACTUAL; solo se pasa para rehacer un "
        "informe viejo.",
    )
    mapeo: str | None = Field(
        None,
        description='JSON {"<fila>": "<cargo>"} con las correcciones del usuario, SOLO las filas corregidas. La '
        "clave es el indice 0-based de la fila del archivo —el mismo `fila` del detalle—, no el texto del cargo.",
    )
    ruc: str | None = Field(
        None, description="RUC de la empresa del cliente: resuelve su industria (CIIU) y su tamano."
    )
    segmento: str | None = Field(
        None, description="Tamano de la empresa: MICROEMPRESA, PEQUENA, MEDIANA o GRANDE (D-018)."
    )
    rubro: str | None = Field(
        None, description="CIIU de primer nivel (una letra). Estrecha el respaldo; no mejora la precision (D-023)."
    )
    formato_libre: bool = Field(
        False,
        alias="formatoLibre",
        description="Por defecto se exige el FORMATO del producto (columna `cargo` y opcionales `sueldo`, "
        "`id_empleado`, `nombre`, `sexo`, `fecha_ingreso`, `centro_costo`; sin cedulas). En true se acepta "
        "cualquier archivo indicando las columnas a mano.",
    )
    columna_cargo: str | None = Field(None, alias="columnaCargo", description="Solo con formatoLibre=true.")
    columna_sueldo: str | None = Field(
        None, alias="columnaSueldo", description="Solo si la columna de sueldo no se autodetecta."
    )
    columnas_originales: bool = Field(
        True,
        alias="columnasOriginales",
        description="Por defecto el detalle trae TUS columnas junto a los resultados. En false, solo los numeros.",
    )
    columnas_extra: str | None = Field(
        None,
        alias="columnasExtra",
        description="Con columnasOriginales=false: que columnas tuyas rescatar igualmente, separadas por coma.",
    )
    incluir_excel: bool = Field(
        False,
        alias="incluirExcel",
        description="Ademas del JSON, el Excel del informe en base64 (`excelBase64`), sin procesar dos veces.",
    )
