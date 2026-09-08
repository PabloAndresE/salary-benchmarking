"""Clasificador de nivel jerarquico desde el texto del cargo.

POR QUE EXISTE. Los embeddings codifican el AREA y no la JERARQUIA — medido en D-012:
pares que solo se diferencian en el rango puntuan 0,857 y pares que solo se diferencian en
el area, 0,764. Un gerente y un auxiliar del mismo area se parecen mas que dos jefes de
areas distintas, y `GERENTE DE AUDITORIA` / `JEFE DE AUDITORIA` dan 0,944.

Eso rompe el vecindario del producto: `SUPERVISOR DE CAJA` se promedia con `AUXILIAR DE
CAJA`, y entre el nivel 1 y el 5 hay **2,11x de diferencia en pago** (D-013). El nivel
tiene que venir de otra senal.

LA SUPERVISION ES DEBIL Y GRATIS. El ~51% de las etiquetas lleva la palabra de rango
escrita —`AUXILIAR DE BODEGA`, `JEFE DE PLANTA`— y eso cubre el 38,6% de las personas. Se
entrena con esas y se predice el resto.

COMO SE VALIDA DE VERDAD. Acertar el rango en una etiqueta que lo lleva escrito es
trivial: el modelo solo tiene que leer la palabra de vuelta. La prueba util es otra:

  1. entrenar SIN VER SALARIOS,
  2. predecir el nivel de los titulos que NO llevan rango,
  3. comprobar si el salario se ordena por ese nivel predicho.

Si aparece la escalera, el clasificador encontro jerarquia real en textos donde nadie la
escribio. Y no es circular: el salario no entra en ninguna etapa del entrenamiento.
"""
import re

import numpy as np
import pandas as pd

# Nivel aproximado de cada palabra de rango. Los sinonimos comparten escalon a proposito:
# `AUXILIAR` y `AYUDANTE` no son jerarquia entre si, y tratarlos como escalones distintos
# fabricaria diferencias donde no las hay.
# QUE NO ENTRA, y por que. `EJECUTIVO` parece nivel 5 y en Ecuador no lo es: `EJECUTIVO DE
# VENTAS` es un vendedor, y meterlo mandaria 17.000 personas al escalon mas alto por una
# falsa amistad del idioma. `ADMINISTRADOR`, `OFICIAL`, `GESTOR`, `AGENTE` e `INSPECTOR`
# son ambiguas —a veces rango, a veces oficio— y no entran sin criterio verificable.
#
# Y lo que NO es un hueco del diccionario: `TRABAJADOR AGRICOLA`, `DOCENTE`, `CHOFER`,
# `GUARDIA`, `MEDICO`... no declaran escalon porque no lo tienen. Son ocupaciones. El 56%
# de las personas seguira sin nivel lexico y es correcto que asi sea; para esas el
# tratamiento es el intervalo, no inventarles un rango.
#
# El nivel de cada palabra se decide por lo que SIGNIFICA, nunca por lo que cobra: usar el
# sueldo para asignar el escalon seria la circularidad que todo el proyecto evita.
RANGOS = {
    "PASANTE": 1, "PRACTICANTE": 1,
    "AYUDANTE": 1, "AUXILIAR": 1, "OPERARIO": 1, "OPERADOR": 1, "OBRERO": 1,
    "ASISTENTE": 1,
    "TECNICO": 2, "ANALISTA": 2,
    "SUPERVISOR": 3, "COORDINADOR": 3, "ESPECIALISTA": 3,
    "JEFE": 4, "SUBGERENTE": 4,
    "GERENTE": 5, "DIRECTOR": 5, "VICEPRESIDENTE": 5, "PRESIDENTE": 5,
}
NIVELES = (1, 2, 3, 4, 5)

# El plural castellano es -S o -ES: AUXILIAR/AUXILIARES, JEFE/JEFES. Las alternativas van
# ordenadas por longitud para que SUBGERENTE no se lea como GERENTE, y los limites de
# palabra impiden que una subcadena cuele.
_ALTERNATIVAS = "|".join(sorted(RANGOS, key=len, reverse=True))
_PATRON = re.compile(r"\b(" + _ALTERNATIVAS + r")(?:ES|S)?\b")


def nivel_lexico(etiqueta):
    """Nivel segun la palabra de rango del titulo, o None si no lleva ninguna.

    Con varias palabras gana la MAS ALTA: `ASISTENTE DE GERENCIA` no es un gerente, pero
    `JEFE TECNICO` si es un jefe. Es una heuristica y falla en el primer caso; se acepta
    porque la alternativa —descartar los titulos con dos rangos— tira senal util y el
    error va en la direccion del ruido, no del sesgo.
    """
    hallados = _PATRON.findall(str(etiqueta).upper())
    return max((RANGOS[h] for h in hallados), default=None)


def enmascarar(etiqueta, marca="PUESTO"):
    """Quita la palabra de rango del titulo: `AUXILIAR DE BODEGA` -> `PUESTO DE BODEGA`.

    ES LA PIEZA QUE HACE FUNCIONAR LA SUPERVISION DEBIL, y sin ella no funciona. Medido:
    entrenando sobre el titulo COMPLETO el clasificador acierta el 98,9% del rango — pero
    porque lee la palabra de vuelta, no porque entienda jerarquia. Al llegarle un titulo
    sin rango (`CONTADOR`) su detector no tiene a que dispararse y vuelca el 58% de la
    gente al nivel mas bajo. La escalera salarial resultante no es monotona (1,48x).

    Tapando el rango el atajo desaparece: el modelo tiene que inferir el nivel del RESTO
    del titulo, y un titulo sin rango deja de ser un caso fuera de distribucion — es
    exactamente lo que vio entrenando.

    La etiqueta queda ruidosa a proposito: `___ DE BODEGA` es unas veces 1 y otras 4. Eso
    es correcto. Lo que se aprende es P(nivel | resto del titulo), que es justo la
    pregunta cuando nadie escribio el rango.
    """
    return _PATRON.sub(marca, str(etiqueta).upper()).strip()


def etiquetar(etiquetas):
    """Serie etiqueta -> nivel lexico (NaN donde no hay palabra de rango)."""
    return pd.Series({e: nivel_lexico(e) for e in etiquetas}, dtype="Float64")


class ClasificadorNivel:
    """Regresion logistica sobre el embedding del titulo.

    Un modelo simple a proposito. El objetivo no es exprimir el ultimo punto de acierto:
    es comprobar si la jerarquia esta recuperable del texto, y con un modelo complicado no
    se sabria si el merito es del metodo o de la capacidad. Si el lineal ya la recupera,
    la respuesta es que la senal esta ahi.
    """

    def __init__(self, modelo=None):
        self.modelo = modelo

    def entrenar(self, X, y, semilla=20260805):
        from sklearn.linear_model import LogisticRegression
        self.modelo = LogisticRegression(max_iter=2000, C=1.0, random_state=semilla,
                                         class_weight="balanced")
        self.modelo.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        return self

    def predecir(self, X):
        return self.modelo.predict(np.asarray(X, dtype=float)).astype(int)

    def probabilidades(self, X):
        return self.modelo.predict_proba(np.asarray(X, dtype=float))

    def nivel_esperado(self, X):
        """Nivel como valor continuo: suma de p_k * k.

        Mas util que la clase ganadora para ordenar puestos y para meterlo en una
        distancia: entre un puesto que el modelo ve claramente de nivel 4 y otro dudoso
        entre 3 y 5 hay una diferencia que la clase discreta borra.
        """
        p = self.probabilidades(X)
        return p @ np.array(self.modelo.classes_, dtype=float)


def escalera_salarial(niveles, y):
    """Mediana de `y` por nivel, el recorrido entre extremos, y si es monotona.

    Es la prueba que importa: si el nivel PREDICHO sobre titulos sin palabra de rango
    ordena el salario de forma monotona, el clasificador encontro jerarquia real en textos
    donde nadie la escribio.
    """
    d = pd.DataFrame({"nivel": np.asarray(niveles), "y": np.asarray(y, dtype=float)})
    d = d.dropna()
    g = d.groupby("nivel")["y"].agg(["median", "size"])
    if len(g) < 2:
        return g, float("nan"), False
    recorrido = float(np.exp(g["median"].iloc[-1] - g["median"].iloc[0]))
    monotona = bool(g["median"].is_monotonic_increasing)
    return g, recorrido, monotona


def efecto_nivel(marco, col="cargo_norm", col_y="y", col_empresa="empresa_ruc",
                 estimador="media"):
    """Cuanto paga cada escalon, en log, DENTRO de la misma area enmascarada.

    Medido asi porque es el unico contraste sin confusion: `PUESTO DE CAJA` existe como
    auxiliar y como supervisor, misma area exacta, solo cambia el rango. Comparar entre
    areas mezclaria "los jefes cobran mas" con "la contabilidad paga mas que la bodega".

    Resultado sobre 2024-2025 (`e2_nivel/03`): monotono, con recorrido 2,37x del nivel 1
    al 5 y omega2 = 0,288 frente a un placebo de 0,000.

    Devuelve un dict nivel -> efecto en log, centrado en cero.
    """
    d = marco[[col, col_y, col_empresa]].dropna(subset=[col_y]).copy()
    d["area"] = d[col].map(lambda e: enmascarar(e))
    d["nivel"] = d[col].map(nivel_lexico)
    # `estimador` existe porque hay un DESAJUSTE en el producto: esto sale de PROMEDIOS y
    # se suma a `m`, que es una MEDIANA ponderada. Una diferencia-de-promedios solo es una
    # diferencia-de-medianas si las dos distribuciones tienen la MISMA FORMA, y aqui no la
    # tienen: los escalones altos arrastran cola derecha mucho mas gorda (`GERENTE GENERAL`
    # va de $500 a $13.712; `AUXILIAR DE LIMPIEZA`, de $475 a $485). Con mas asimetria el
    # promedio se aleja mas de su mediana, asi que E[nivel 5]-E[nivel 1] SOBREESTIMA
    # med[nivel 5]-med[nivel 1] y el ajuste queda sobredimensionado.
    #
    # Por defecto sigue siendo `media`: cambiar el estimador cambia la respuesta del 35,9%
    # de la gente —la que va por analogia— y eso se decide midiendo, no opinando.
    ag = "median" if estimador == "mediana" else "mean"
    # dentro de empresa primero: el empleador es el 81% del ruido y taparia el efecto
    d["r"] = d[col_y] - d.groupby(col_empresa)[col_y].transform(ag)
    d = d[d["nivel"].notna()]
    mixtas = d.groupby("area")["nivel"].nunique()
    d = d[d.area.isin(mixtas[mixtas >= 2].index)]
    if d.empty:
        return {}
    d["r"] = d["r"] - d.groupby("area")["r"].transform(ag)
    g = d.groupby("nivel")["r"].agg(ag)
    centro = g.median() if estimador == "mediana" else g.mean()
    return {int(k): float(v - centro) for k, v in g.items()}
