"""La escalera de referencias: los rivales, el techo y el oraculo.

  aleatoria         -> aporta algo la informacion?
  cargo_crudo       -> supero lo que se usa hoy, entero y sin podar?
  solo_texto        -> la composicion aporta algo mas alla del nombre del puesto?
  techo_alcanzable  -> cuanto es lo maximo posible con estos datos?   (NO es particion)
  oraculo_salarial  -> BANDERA ROJA: si el arquetipo se le acerca, derivo a bandas

Todos los rivales se puntuan con EL MISMO estimador (`referencia.predecir`). Es el
invariante del banco: lo unico que cambia entre metodos es como se agrupa a la gente. Sin
eso, una diferencia seria atribuible al estimador, al split o al agrupamiento, y no habria
forma de saber a cual.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor

SEMILLA = 20260805


def cargo_crudo(df):
    """CARGO tal cual, con todas sus etiquetas. No se poda (D-005).

    Medido sobre el marco evaluable 2024-2025: 65.081 etiquetas, celda mediana de 2
    personas y 1 empresa, y solo el 9,24% de las celdas alcanza 3 empresas — aunque esas
    cubren el 66,6% de la gente. Podarlo a sus etiquetas grandes no produce un rival:
    produce una celda "otros" con la mayoria de la gente dentro.
    """
    return df["cargo_norm"].astype(str).rename("celda")


def aleatoria(df, k, semilla=SEMILLA):
    """Piso de la escalera: k celdas sin ninguna informacion.

    No es trivial. Es lo que detecta el artefacto de la masa en el SBU: si media plantilla
    tuviera y = 0 por censura, hasta el azar acertaria y el piso subiria hasta tocar al
    arquetipo. Medido en la Tarea 2b: solo el 5,9% esta en cero, asi que el piso es real.
    """
    rng = np.random.default_rng(semilla)
    return pd.Series(rng.integers(0, int(k), len(df)).astype(str),
                     index=df.index, name="celda")


def solo_texto(df, k, embeddings, semilla=SEMILLA):
    """Agrupa por el significado del titulo, en k celdas. El rival dificil.

    Hace dos trabajos: aisla la contribucion de la composicion frente al puro significado
    del titulo, E IGUALA LA CARDINALIDAD — sin el, la primera objecion del tribunal es
    "gana por tener 50 celdas en vez de 65.081" y no hay respuesta.

    Embeddings y no TF-IDF porque la similitud de caracteres invierte la jerarquia
    —medido: AUXILIAR DE SERVICIOS GENERALES -> JEFE DE SERVICIOS GENERALES puntua 0,79—
    y eso fabricaria un rival mas flojo del necesario, que es el patron de D-006.

    Los embeddings se inyectan ya calculados: este modulo no habla con Vertex.
    """
    X = np.asarray(embeddings, dtype=float)
    km = KMeans(n_clusters=int(k), random_state=int(semilla), n_init=10)
    return pd.Series(km.fit_predict(X).astype(str), index=df.index, name="celda")


def oraculo_salarial(train, df, k, semilla=SEMILLA):
    """Agrupa DIRECTAMENTE por el salario: circular por diseno. AJUSTADO SOLO EN TRAIN.

    No es un metodo candidato ni un denominador. Es la alarma: si el arquetipo se le
    acerca, sospechar que derivo a bandas salariales, que es exactamente lo que la tesis
    promete no hacer.

    El ajuste sobre train importa. La version previa corria k-means sobre `y` de todo el
    df, test incluido: definida la celda por la propia y de la persona, la mediana de sus
    donantes era casi su y y el MAE colapsaba al error de cuantizacion de k bins. La
    alarma no podia sonar nunca, y ademas servia de denominador a la frase-resultado.
    """
    ytr = pd.to_numeric(train["y"], errors="coerce").fillna(0.0).to_numpy(float)
    km = KMeans(n_clusters=int(k), random_state=int(semilla),
                n_init=10).fit(ytr.reshape(-1, 1))
    y = pd.to_numeric(df["y"], errors="coerce").fillna(0.0).to_numpy(float)
    return pd.Series(km.predict(y.reshape(-1, 1)).astype(str),
                     index=df.index, name="celda")


def techo_alcanzable(train, test, X_train, X_test, semilla=SEMILLA):
    """Cuanta senal hay en los observables legitimos. Devuelve PREDICCIONES, no celdas.

    No tiene por que ser una particion: su papel es acotar el maximo alcanzable, y un
    modelo flexible acota mejor que cualquier agrupamiento. Entrenado en train y evaluado
    en empresas held-out, la misma frontera que usa el banco.

    Perdida ABSOLUTA, no cuadratica: si el modelo optimizara MSE estaria estimando la
    media condicional mientras la metrica puntua el error absoluto, y el techo saldria mas
    bajo de lo que realmente es. Es el mismo desemparejamiento que D-011 corrigio en el
    estimador; aqui tambien aplica.

    COTA TEORICA que este numero no puede superar: con eta2_empresa = 0,388 y el efecto
    empresa inobservable bajo leave-company-out, Var(error) >= 0,388*Var(y) para cualquier
    metodo. En sd, el mejor posible llega a raiz(0,388) = 0,623 del MAE aleatorio. Si el
    techo sale muy por debajo de eso, se colo informacion del test.
    """
    modelo = HistGradientBoostingRegressor(loss="absolute_error", random_state=int(semilla))
    modelo.fit(np.asarray(X_train, dtype=float),
               pd.to_numeric(train["y"], errors="coerce").to_numpy(float))
    return pd.Series(modelo.predict(np.asarray(X_test, dtype=float)),
                     index=test.index, name="y_techo")
