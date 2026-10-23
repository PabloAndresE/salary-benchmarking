"""El informe de una nomina: la nomina entra, el informe sale, en la MISMA peticion.

POR QUE POR LOTES Y NO UNA CONSULTA POR TITULO. El ancla de empresa —lo que habilita la
lectura de equidad interna, la parte mas valiosa del producto— necesita TODAS las filas a
la vez: es la mediana de (lo que paga - lo que dice el mercado) sobre la nomina entera.

SINCRONO. El informe tarda 20-35 s y cabe de sobra en los 300 s por peticion de Cloud
Run. Asi no hay trabajos en memoria que se pierdan cuando la instancia bajo demanda se
apaga, ni un segundo viaje para pedir el Excel: va en la misma respuesta si se pide.

DATOS PERSONALES. La nomina lleva nombres y sueldos: es dato personal bajo LOPDP. NO se
escribe a disco: se procesa en memoria. Lo unico que se guarda es cargo y sueldo de cada
fila, en BigQuery (`registro_nomina_service`), con la base legal del contrato.
"""

import base64
import datetime as _dt
import io
import logging
import time

import numpy as np
import pandas as pd

from src.domain.antiguedad import antiguedad_anios, tramo
from src.domain.base_referencia import SEGMENTOS
from src.domain.ciiu import nombre_ciiu
from src.domain.columnas_nomina import _buscar_sueldo
from src.domain.comparacion import comparar, texto_resumen
from src.domain.formato import CANONICAS, OBLIGATORIAS, FormatoInvalido
from src.domain.formato import validar as validar_formato
from src.domain.nomina import columna, leer_mapeo, leer_nomina_bytes
from src.domain.presentacion import SALIDA_MODELO, UNIDADES, anidar_sector, estado_de_fila
from src.infrastructure.motor import Motor
from src.services import registro_nomina_service
from src.shared.constants import ESQUEMA
from src.shared.contracts.responses import BaseResponseModel, error, exito
from src.shared.utils.conversion import a_python, claves_a_camel, opcional

logger = logging.getLogger(__name__)

# Los dicts cuyas claves son VALORES (estados, niveles de confianza), no nombres de campo
CLAVES_DATO = frozenset({"reparto_estado", "reparto_confianza"})


def crear_informe(
    *,
    motor: Motor,
    contenido: bytes,
    nombre_archivo: str,
    anio: int | None,
    mapeo: str | None,
    ruc: str | None,
    segmento: str | None,
    rubro: str | None,
    formato_libre: bool,
    columna_cargo: str | None,
    columna_sueldo: str | None,
    columnas_originales: bool,
    columnas_extra: str | None,
    incluir_excel: bool,
) -> BaseResponseModel:
    """Valida la peticion, arma el informe, guarda la nomina y devuelve el sobre.

    Se valida ANTES de procesar todo lo que se puede validar barato —el SBU del ano, el
    segmento, el rubro y que el archivo se deje leer—: un 400 inmediato con el motivo es
    mucho mas util que un fallo treinta segundos despues.
    """
    t0 = time.perf_counter()
    logger.info("crear_informe: inicio (%d bytes)", len(contenido))
    # EL ANO POR DEFECTO ES EL ACTUAL. Estaba fijado a 2025 y eso envejece solo: en
    # enero se seguirian emitiendo dolares del ano anterior sin que nadie lo note.
    anio = int(anio) if anio else _dt.date.today().year
    segmento, rubro = opcional(segmento), opcional(rubro)
    ruc = opcional(ruc)
    columna_cargo, columna_sueldo = opcional(columna_cargo), opcional(columna_sueldo)

    # LA INDUSTRIA SE DERIVA DEL RUC. Un area de RR.HH. sabe su RUC y no sabe que es
    # "seccion C". Si ademas pasan `rubro` a mano, manda el explicito y se avisa si no
    # coinciden, en vez de elegir uno en silencio.
    ficha = None
    ciiu_cliente = None
    if ruc:
        g6, tam_emp, seg_ruc = motor.base.meta_ruc.get(ruc.strip(), ("", -1, ""))
        # `en_la_base` sale de `pad_ruc` y NO de `meta_ruc`: el segundo solo se puebla
        # cuando el marco trae las columnas de SCVS, asi que con una base construida sin
        # ellas se le decia a una empresa que no esta cuando si esta.
        ficha = {
            "ruc": ruc.strip(),
            "en_la_base": ruc.strip() in motor.base.pad_ruc,
            # COMPLETO. `ciiu_grupo` se queda por compatibilidad, pero lo que el
            # cliente reconoce como suyo es `ciiu` entero: `G4761.03`, no `G476`.
            "ciiu": g6 or None,
            "ciiu_grupo": (g6[:4] if g6 else None),
            "ciiu_seccion": (g6[:1] if g6 else None),
            "n_empleados": tam_emp if tam_emp > 0 else None,
        }
        # EL CIIU COMPLETO VIAJA AL MODELO, no solo su primera letra. De el sale el
        # nivel al que se compara cada cargo: sin esto la cascada queda muerta.
        ciiu_cliente = g6 or None
        if g6 and not rubro:
            # UN DERIVADO NO PUEDE DAR 400: si no hay respaldo, no se deriva y el informe
            # sale global, igual que si no hubiera mandado el RUC; la ficha lo dice.
            if g6[:1] in motor.base.rubros:
                rubro = g6[:1]
                ficha["rubro_derivado"] = rubro
            else:
                ficha["rubro_sin_respaldo"] = g6[:1]
        elif g6 and rubro and rubro.upper() != g6[:1]:
            ficha["aviso"] = f"pediste rubro {rubro.upper()} y el RUC dice {g6[:1]}; manda el que pediste"
        # EL SEGMENTO TAMBIEN SALE DEL RUC, con la misma regla: el explicito manda y se
        # avisa si no coinciden. Este SI mejora la precision (D-018). Va en
        # `aviso_segmento` para no pisar el del rubro.
        if seg_ruc:
            ficha["segmento_del_ruc"] = seg_ruc
        if seg_ruc and not segmento and seg_ruc in SEGMENTOS:
            segmento = seg_ruc
            ficha["segmento_derivado"] = segmento
        elif seg_ruc and segmento and segmento.upper() != seg_ruc:
            ficha["aviso_segmento"] = (
                f"pediste segmento {segmento.upper()} y el RUC dice {seg_ruc}; manda el que pediste"
            )

    extra_pedidas = [t.strip() for t in (opcional(columnas_extra) or "").split(",") if t.strip()]
    try:
        motor.settings.get_sbu(int(anio), estricto=True)
    except ValueError as e:
        return error(400, str(e))
    if segmento and segmento.upper() not in SEGMENTOS:
        return error(400, f"segmento invalido: {segmento}. Validos: {list(SEGMENTOS)}")
    # El rubro se valida igual que el segmento. Antes solo avisaba por `warnings` y caia
    # al global: el cliente recibia un informe entero creyendo que era sectorial.
    if rubro and rubro.upper() not in motor.base.rubros:
        return error(400, f"rubro sin datos suficientes: {rubro}. Con respaldo en esta base: {list(motor.base.rubros)}")
    if not contenido:
        return error(400, "el archivo llego vacio")
    try:
        df, col = leer_nomina_bytes(contenido, nombre_archivo or "n.xlsx", columna_cargo if formato_libre else None)
    except ValueError as e:
        return error(400, str(e))
    # FORMATO ESTRICTO por defecto: nombres canonicos, sin cedulas, y todos los
    # problemas de una vez. `formato_libre` existe para el archivo que llega como llega.
    informe_formato = None
    if not formato_libre:
        try:
            df, informe_formato = validar_formato(df)
        except FormatoInvalido as e:
            return error(
                400,
                "la nomina no cumple el formato",
                claves_a_camel(
                    {
                        "formato": "estricto",
                        "problemas": e.problemas,
                        "obligatorias": list(OBLIGATORIAS),
                        "aceptadas": list(CANONICAS),
                    }
                ),
            )
        col = "cargo"
        columna_sueldo = "sueldo" if "sueldo" in df.columns else None
    # Si el cliente NOMBRA la columna de sueldo, tiene que existir. Ignorarla en silencio
    # le devuelve un informe sin comparacion y sin explicacion.
    if columna_sueldo and formato_libre:
        real = columna(df, columna_sueldo)
        if real is None:
            return error(
                400, f"la columna de sueldo '{columna_sueldo}' no esta en el archivo. Columnas: {list(df.columns)}"
            )
        columna_sueldo = real
    extra, no_estan = [], []
    for c in extra_pedidas:
        real = columna(df, c)
        (extra if real else no_estan).append(real or c)
    if no_estan:
        return error(400, f"columnas_extra que no estan en el archivo: {no_estan}. Columnas: {list(df.columns)}")
    try:
        correcciones = leer_mapeo(opcional(mapeo), len(df))
    except ValueError as e:
        return error(400, str(e))

    seg_final = segmento.upper() if segmento else None
    rubro_final = rubro.upper() if rubro else None
    cuerpo, excel, ref = _procesar(
        motor,
        df,
        col,
        int(anio),
        seg_final,
        rubro_final,
        columna_sueldo,
        extra,
        columnas_originales,
        informe_formato,
        ruc,
        ciiu_cliente,
        correcciones,
    )
    id_carga = registro_nomina_service.nuevo_id()
    registro_nomina_service.guardar_carga(
        df=df,
        col_cargo=col,
        col_sueldo=_buscar_sueldo(df, columna_sueldo),
        detalle=cuerpo["detalle"],
        homologacion=ref,
        id_carga=id_carga,
        contenido=contenido,
        anio=int(anio),
        ruc=ruc,
        ciiu=ciiu_cliente,
        segmento=seg_final,
        rubro=rubro_final,
        correcciones=correcciones,
        ruta_base=motor.ruta_base,
    )
    contenido_respuesta = {
        "id_carga": id_carga,
        "filas": len(df),
        "columna_cargo": col,
        "empresa": ficha,
        **cuerpo,
        "excel_base64": base64.b64encode(excel).decode() if incluir_excel else None,
    }
    logger.info("crear_informe: fin, %d filas en %.1fms", len(df), (time.perf_counter() - t0) * 1000)
    return exito(
        claves_a_camel(contenido_respuesta, conservar=frozenset(map(str, df.columns)), claves_dato=CLAVES_DATO)
    )


def _procesar(
    motor: Motor,
    df,
    col_cargo: str,
    anio: int,
    segmento: str | None,
    rubro: str | None,
    col_sueldo: str | None,
    columnas_extra: list[str] | None = None,
    columnas_originales: bool = True,
    informe_formato: dict | None = None,
    ruc: str | None = None,
    ciiu: str | None = None,
    mapeo: dict[int, str] | None = None,
) -> tuple[dict, bytes, pd.DataFrame]:
    """El informe completo. Es la misma cadena que el CLI, sin tocar el disco.

    Devuelve tambien la homologacion cruda (`ref`), fila por fila: el registro de
    nominas necesita `cargo_base` y `p_juez`, que el JSON no siempre lleva."""
    # LAS CORRECCIONES DEL USUARIO, ANTES DE NORMALIZAR. De aqui en adelante el flujo es
    # identico: el titulo corregido se embebe y se busca como cualquier otro.
    if mapeo:
        df = df.copy()
        j = df.columns.get_loc(col_cargo)
        for i, txt in mapeo.items():
            df.iat[i, j] = txt
    titulos = df[col_cargo].fillna("").astype(str).str.strip().str.upper()
    nuevos = motor.asegurar(titulos.tolist())

    ref = motor.base.referenciar(
        titulos.tolist(), motor.emb, anio=anio, segmento=segmento, rubro=rubro, ruc=ruc, ciiu=ciiu
    )
    salida = pd.concat([df.reset_index(drop=True), ref.drop(columns=["cargo"]).reset_index(drop=True)], axis=1)

    cs = _buscar_sueldo(df, col_sueldo)
    por_puesto = resumen = None
    if cs:
        salida, por_puesto, resumen = comparar(salida, cs, col_cargo, ref, motor.settings.get_sbu, anio)
    salida["estado"] = [estado_de_fila(f) for _, f in salida.iterrows()]
    # ANTIGUEDAD, para el filtro del front y para explicar por que alguien cobra lo que
    # cobra. Se calcula descontando los periodos fuera: ver `producto/antiguedad.py`.
    salida["antiguedad_anios"] = antiguedad_anios(df, anio).to_numpy()
    salida["antiguedad_tramo"] = tramo(salida["antiguedad_anios"]).to_numpy()
    # La hoja del cliente no lleva escala logaritmica ni la banda de empresas: esa va en
    # `por_puesto`, que es donde la unidad coincide. Mismo criterio que el CLI.
    salida = salida.drop(
        columns=[c for c in salida.columns if c.endswith("_log") or c.endswith("_emp") or c == "sd"], errors="ignore"
    )

    # EL EXCEL LLEVA TODO —es el entregable humano— y el JSON solo lo del modelo.
    xls = io.BytesIO()
    with pd.ExcelWriter(xls) as w:
        salida.to_excel(w, sheet_name="detalle", index=False)
        if por_puesto is not None:
            por_puesto.to_excel(w, sheet_name="por_puesto", index=False)

    def limpio(d):
        return [{str(k): a_python(v) for k, v in fila.items()} for fila in d.to_dict("records")]

    json_det = salida.copy()
    json_det.insert(0, "fila", range(len(json_det)))
    json_det["cargo"] = df[col_cargo].fillna("").astype(str).str.strip().to_numpy()
    quedan = [c for c in SALIDA_MODELO if c in json_det.columns]
    if columnas_originales:
        quedan += [c for c in json_det.columns if c not in quedan]
    else:
        quedan += [c for c in (columnas_extra or []) if c in json_det.columns and c not in quedan]
    json_det = json_det[quedan]

    # ---- TARJETAS DE CABECERA -------------------------------------------------
    # Todo EXACTO, sin cotas. `trabajadores` porque las celdas son disjuntas —cada
    # persona esta en una sola— y `empresas` porque el padron guarda QUE empresas
    # respaldan cada celda, no solo cuantas: la union se calcula de verdad en vez de
    # sumar conteos, que contaria varias veces a la que respalda varios cargos.
    # SE CUENTA LO QUE DE VERDAD SE USO, celda por celda. Con `--rubro`, las celdas
    # que tenian respaldo sectorial se comparan contra empresas de ESE rubro y las que
    # no, contra el mercado entero — el fallback es por cargo. Contar el padron entero
    # daria 4.405 empresas cuando la comparacion de dos tercios de las filas se hizo
    # contra un subconjunto: la tarjeta describiria algo que no paso.
    usa_rubro = {}
    if "rubro" in ref.columns:
        usa_rubro = {t: str(r or "") for t, r in zip(ref["cargo"], ref["rubro"])}
    idx = [(t, motor.base.idx[t]) for t in set(titulos) if t in motor.base.idx]
    vistos, trabajadores, empresas = set(), 0, set()
    n_sectoriales = 0
    for t, i in idx:
        g = int(motor.base.grupo[i])
        if g in vistos:
            continue
        vistos.add(g)
        trabajadores += int(motor.base.personas[i])
        del_celda = motor.base.empresas_de(i)
        r = usa_rubro.get(t, "")
        if r:
            n_sectoriales += 1
            del_celda = [
                e
                for e in del_celda.tolist()
                if e < len(motor.base.pad_ciiu) and str(motor.base.pad_ciiu[e] or "").startswith(r)
            ]
        empresas.update(int(e) for e in del_celda)
    con_padron = len(motor.base.pad_idx) > 0

    tam = motor.base.pad_tam
    tallas = [int(tam[e]) for e in empresas if e < len(tam) and tam[e] > 0]
    mercado = {
        "cargos_del_cliente": int(pd.Series(titulos).nunique()),
        "cargos_con_datos_en_la_base": len(vistos),
        "cargos_comparados_contra_su_rubro": n_sectoriales,
        "trabajadores_analizados": trabajadores,
        "empresas_analizadas": len(empresas) if con_padron else None,
        "tamano_de_las_empresas": (
            {
                "minimo": min(tallas),
                "maximo": max(tallas),
                "mediana": int(np.median(tallas)),
                "con_dato": len(tallas),
                "sin_dato": len(empresas) - len(tallas),
            }
            if tallas
            else None
        ),
    }
    if rubro and n_sectoriales < len(vistos):
        mercado["nota_rubro"] = (
            f"{n_sectoriales} de {len(vistos)} cargos se comparan contra empresas de "
            f"{rubro}; el resto no llega al suelo de respaldo en ese sector y se compara "
            f"contra el mercado entero. El fallback es por cargo."
        )
    # .CUANTO SE ESTA MIRANDO EL CLIENTE AL ESPEJO? Si su empresa participo en los
    # estudios, su propio sueldo entra en la mediana que le sirve de referencia. NO se le
    # quita —de una mediana ponderada no se resta un voto sin guardar los votos, que
    # seria guardar lo que paga cada empresa por cada cargo; ver D-027—, pero se dice.
    #
    # El umbral son 10 empresas y esta medido, no elegido: por encima, quitar una mueve
    # el centro un 0,39% y corregirlo seria corregir ruido; por debajo lo mueve un 5,4%
    # y el cliente pesa entre un 15% y un 33% del mercado.
    if "tu_empresa" in ref.columns and ruc:
        propio = ref[["cargo", "tu_empresa", "tu_influencia", "empresas"]].drop_duplicates("cargo")
        dentro = propio[propio["tu_empresa"].astype(bool)]
        finos = dentro[pd.to_numeric(dentro["empresas"], errors="coerce") < 10]
        mercado["cargos_donde_tu_empresa_esta_en_el_mercado"] = int(len(dentro))
        mercado["cargos_donde_eso_pesa"] = int(len(finos))
        if len(finos):
            peor = finos.sort_values("tu_influencia", ascending=False).iloc[0]
            mercado["nota_espejo"] = (
                f"Tu empresa respalda {len(dentro)} de los cargos que comparas, y en "
                f"{len(finos)} el mercado es tan estrecho que tu propio sueldo pesa lo "
                f"suyo dentro de la referencia — en {peor['cargo']}, un "
                f"{100 * float(peor['tu_influencia']):.0f}%. Esas lecturas no son "
                f"independientes: mira `tu_influencia` en `por_puesto`."
            )
        elif len(dentro):
            mercado["nota_espejo"] = (
                f"Tu empresa respalda {len(dentro)} de los cargos que comparas, todos "
                f"con 10 o mas empresas detras. Medido, quitarte moveria la referencia "
                f"un 0,4%: la comparacion se sostiene."
            )
    if not con_padron:
        mercado["nota"] = (
            "Esta base se construyo sin padron de empresas: " "`empresas_analizadas` no es calculable. Reconstruyela."
        )
    elif tallas and len(tallas) < len(empresas):
        mercado["nota_tamano"] = (
            f"{len(empresas) - len(tallas)} de {len(empresas)} "
            f"empresas no tienen tamano registrado y quedan fuera "
            f"del rango."
        )

    industria = None
    if rubro:
        grupos_ciiu = {}
        for e in empresas:
            if e < len(motor.base.pad_ciiu):
                g6 = str(motor.base.pad_ciiu[e] or "")
                if g6.startswith(rubro):
                    grupos_ciiu[g6] = grupos_ciiu.get(g6, 0) + 1
        top = sorted(grupos_ciiu.items(), key=lambda kv: -kv[1])[:5]
        # CONTRA QUE SE COMPARO, que con la cascada ya no es una sola cosa: unos cargos
        # bajan a la division del cliente y otros se quedan en su seccion.
        #
        # `nombre` es el nivel MAS FINO al que se llego, no el que cubre mas cargos. Es
        # decision de producto: la etiqueta contesta "hasta donde supimos afinar contigo",
        # y una libreria prefiere leer "comercio al por menor" antes que "comercio al por
        # mayor y al por menor; reparacion de vehiculos".
        #
        # EL PRECIO, para que quede escrito: el nivel mas fino puede cubrir UN solo cargo
        # de veinte, y la etiqueta describira igual el informe entero. Por eso viajan
        # `cargos_en_ese_nivel` —cuantos cubre de verdad— y `niveles` con el reparto
        # completo. Si esa cifra es 1 de 20, la etiqueta es cierta y engañosa a la vez, y
        # quien pinte la pantalla tiene con que matizarlo.
        usados = {}
        if "rubro" in ref.columns and "rubro_nivel" in ref.columns:
            vistos = set()
            for t, cod, niv in zip(ref["cargo"], ref["rubro"], ref["rubro_nivel"]):
                if t in vistos or not str(cod):
                    continue
                vistos.add(t)
                k = (str(cod), str(niv))
                usados[k] = usados.get(k, 0) + 1
        # el mas fino primero: codigo mas largo. Empate -> el que cubra mas cargos.
        orden = sorted(usados.items(), key=lambda kv: (-len(kv[0][0]), -kv[1]))
        (cod_pre, niv_pre), n_pre = orden[0] if orden else ((rubro, "seccion"), 0)
        industria = {
            # lo que el front rotula como "el mercado". Es el nivel predominante.
            "codigo": cod_pre,
            "nivel": niv_pre,
            "nombre": nombre_ciiu(cod_pre),
            "cargos_en_ese_nivel": n_pre,
            "niveles": [{"codigo": c, "nivel": n, "cargos": v, "nombre": nombre_ciiu(c)} for (c, n), v in orden],
            # LA SECCION, y solo la seccion. Lo que el front rotula como "el mercado"
            # es `nombre` —el nivel mas fino al que llego la cascada—; esto se queda
            # aparte y con su nombre honesto, para que dentro de seis meses nadie lea
            # "nombre_seccion" y reciba una division.
            "ciiu_seccion": rubro,
            "nombre_seccion": nombre_ciiu(rubro),
            "grupos_ciiu": [{"codigo": c, "empresas": n, "nombre": nombre_ciiu(c)} for c, n in top],
        }

    cuerpo = {
        "esquema": ESQUEMA,
        # ARRIBA, no dentro de `meta`. Estaba en `meta` aqui y en la raiz en
        # `/referencia`: el mismo contrato en dos sitios segun el endpoint, asi que un
        # front que leia `respuesta.unidades` recibia nada de este y lo daba por vacio.
        # Es justo el fallo que `UNIDADES` existe para evitar —formatear un ratio como
        # dolares da un numero creible y falso—, solo que en la capa de arriba.
        "unidades": UNIDADES,
        "mercado": mercado,
        "industria": industria,
        "meta": {
            "anio": anio,
            "sbu": motor.settings.get_sbu(anio),
            "segmento": segmento,
            "rubro": rubro,
            # ACUSE DE RECIBO. Sin esto el front no puede distinguir "se aplico" de "se
            # ignoro": FastAPI descarta EN SILENCIO un campo de formulario que no esta
            # declarado, asi que mandar `mapeo` a una version que no lo entiende devuelve
            # 202 y un informe identico.
            "mapeo_aplicado": len(mapeo or {}),
            "titulos_nuevos_embebidos": nuevos,
            "puestos_en_la_base": len(motor.base.celdas),
            "tau": round(float(np.sqrt(motor.base.tau2)), 4),
            "sigma": round(float(np.sqrt(motor.base.sigma2)), 4),
            "columnas_omitidas": (
                []
                if columnas_originales
                else [c for c in salida.columns if c not in SALIDA_MODELO and c not in (columnas_extra or [])]
            ),
            "nota_detalle": (
                "Cada fila trae lo del modelo primero y despues tus propias "
                "columnas. `fila` es el indice 0-based del archivo que "
                "subiste."
                if columnas_originales
                else "Solo viajan las columnas del modelo: usa `fila` para casar " "con tu copia del archivo."
            ),
            "aviso": "La brecha_grafia compara dos GRAFIAS de titulo escritas por "
            "empresas distintas, sin control por empresa, sector ni "
            "antiguedad. NO es una brecha salarial medida.",
        },
        "formato": informe_formato,
        "reparto_estado": {str(k): int(v) for k, v in salida["estado"].value_counts().items()},
        "reparto_confianza": (
            {str(k): int(v) for k, v in ref["confianza"].value_counts().items()} if "confianza" in ref else {}
        ),
        "detalle": limpio(json_det),
        "por_puesto": (anidar_sector(limpio(por_puesto)) if por_puesto is not None else []),
        "resumen": {k: a_python(v) for k, v in (resumen or {}).items()},
        "texto": texto_resumen(resumen, por_puesto) if resumen is not None else "",
    }
    return cuerpo, xls.getvalue(), ref
