"""Base de referencia salarial: construir una vez, consultar muchas.

EL PRODUCTO. Un cliente entrega su nomina y recibe, por cada persona, la referencia de
mercado de su puesto con su intervalo y una marca de confianza.

Responde SIEMPRE (decision de ActuaLab). Un cliente sin referencia no se queda quieto:
inventa un numero. Se compite contra eso, no contra el silencio. Pero como se responde
siempre, la marca de confianza deja de ser decorativa y es lo unico que separa "esto lo se"
de "esto lo estoy suponiendo".

COMO FUNCIONA

  titulo conocido   -> la referencia de su propia celda
  titulo NUEVO      -> se embebe y se coloca entre los puestos que se le parecen

Lo segundo es lo que hace que la cobertura pase del 66,6% a casi todo: el 35,9% de la
gente de una nomina nueva tiene un titulo que no esta en la base.

EL PESO DE CADA VECINO, y por que no es `similitud x precision`

La version ingenua pesa cada vecino por su similitud multiplicada por su precision. Medido
sobre un caso real, eso rompe:

    OPERADOR DE PARQUEADERO
      OPERADOR DE PARQUEADEROS   sim 0,989   peso   8%
      OPERADOR DE EXCAVADORA     sim 0,825   peso  46%   <- gana por tener mas datos

Tenia la respuesta exacta delante y le hizo caso a una excavadora. Aqui cada vecino se
trata como una observacion ruidosa del puesto objetivo, con varianza

    var_j = 1/W_j  +  lambda * (1 - sim_j)

y se pesa por 1/var_j. El primer termino es su error de medicion; el segundo, lo que se
paga por no ser exactamente el mismo puesto. Un vecino lejano se descuenta aunque este
perfectamente medido. **`lambda` se estima de los datos**, no se elige: es cuanto difieren
de verdad dos celdas por unidad de distancia semantica.

CUANDO NO HAY VECINDARIO DE VERDAD

    LOTERO -> LINIERO, BOTERO, LAMPERO, TESORERO (sim 0,748-0,784)

El embedding no encuentra nada parecido y se agarra a la terminacion "-ERO". TESORERO
paga 2,5 veces mas. Con la varianza de arriba eso sale solo: si todos los vecinos estan
lejos, `lambda*(1-sim)` domina, el intervalo se dispara y la confianza cae a BAJA.

LIMITE QUE HAY QUE DECLARARLE AL CLIENTE. El empleador explica el 81% de lo que no se
puede predecir (tau = 0,29). Esto da el MERCADO, no la politica salarial de una empresa
concreta. Dos personas identicas en empresas distintas cobran muy diferente y ningun
metodo basado en el puesto arregla eso.
"""
import numpy as np
import pandas as pd

from ..evaluacion.referencia import (_cuantil_por_grupo, componentes_varianza,
                                     sigma2_por_celda, tabla_votos)
from .nivel import efecto_nivel, nivel_lexico

VECINOS = 25
MIN_EMPRESAS = 3        # suelo de identificabilidad y confidencialidad (precedente QCEW)

# La confianza sale del ANCHO DEL INTERVALO, no del numero de empresas. Contar empresas
# engana: `SCRUM MASTER` con 14 salia igual de "ALTA" que `CONTADOR` con 823. Lo que le
# importa a quien lee el informe es cuanto se puede mover el numero.
#
# Y el corte no es un porcentaje fijo, sino cuanto te alejas del SUELO IRREDUCIBLE. Con
# tau y sigma se sabe cual es el intervalo mas estrecho fisicamente posible —ni con
# infinitos datos se baja de ahi—, asi que la pregunta util es "cuantas veces mas ancho
# que el mejor caso". Un umbral absoluto no se traslada entre mercados; este si.
VECES_ALTA = 1.25
VECES_MEDIA = 2.0


def _confianza(sd, sd_suelo, directo):
    """ALTA / MEDIA / BAJA segun cuanto se aleja el intervalo del suelo irreducible."""
    ancho = float(np.exp(0.6745 * sd) - 1.0)
    suelo = float(np.exp(0.6745 * sd_suelo) - 1.0)
    veces = ancho / suelo if suelo > 0 else np.inf
    if directo and veces <= VECES_ALTA:
        return "ALTA", ancho
    if veces <= VECES_MEDIA:
        return "MEDIA", ancho
    return "BAJA", ancho


def _lambda_semantica(m, W, vec, sim, m_todos=None, W_todos=None):
    """Cuanto difieren dos celdas por unidad de distancia semantica. Por momentos.

    Para cada par (celda, vecino) la diferencia observada al cuadrado tiene dos partes:
    el ruido de medicion de ambas, y la diferencia real entre los puestos. La primera se
    conoce (1/W_i + 1/W_j); lo que sobra se atribuye a la distancia y se ajusta por
    minimos cuadrados por el origen.
    """
    mt = m if m_todos is None else m_todos
    Wt = W if W_todos is None else W_todos
    i = np.repeat(np.arange(len(m)), vec.shape[1])
    j = vec.ravel()
    s = sim.ravel()
    ok = (np.isfinite(m[i]) & np.isfinite(mt[j]) & (W[i] > 0) & (Wt[j] > 0)
          & (s < 0.9999))                      # descarta la celda consigo misma
    if ok.sum() < 100:
        return 1.0
    d2 = (m[i][ok] - mt[j][ok]) ** 2 - (1.0 / W[i][ok] + 1.0 / Wt[j][ok])
    x = 1.0 - s[ok]
    den = float((x * x).sum())
    return float(max(np.finfo(float).tiny, (x * d2).sum() / den)) if den > 0 else 1.0


class BaseReferencia:
    """Construida una vez sobre el universo; se consulta por titulo."""

    def __init__(self, celdas, m, W, emp, Z, tau2, sigma2, lam, sbu,
                 nivel=None, efecto=None):
        self.celdas = list(celdas)
        self.idx = {c: i for i, c in enumerate(self.celdas)}
        self.m, self.W, self.emp = m, W, emp
        # `Z` son los embeddings del titulo ENMASCARADO: el area sin contaminacion de
        # rango. `AUXILIAR DE CAJA` y `SUPERVISOR DE CAJA` caen en el mismo punto, y
        # es `nivel` quien los separa despues.
        self.Z = Z
        self.tau2, self.sigma2, self.lam, self.sbu = tau2, sigma2, lam, sbu
        self.nivel = (np.full(len(self.celdas), np.nan) if nivel is None
                      else np.asarray(nivel, dtype=float))
        self.efecto = dict(efecto or {})
        # dispersion del efecto entre escalones: es la incertidumbre que queda cuando
        # NO se sabe el nivel del puesto que se pregunta
        v = list(self.efecto.values())
        self.var_nivel = float(np.var(v)) if len(v) > 1 else 0.0

    # -- construccion ----------------------------------------------------------

    @classmethod
    def construir(cls, marco, X_por_etiqueta, sbu, col="cargo_norm"):
        """`marco` es el universo evaluable; `X_por_etiqueta` un dict etiqueta -> vector."""
        tau2, sigma2 = componentes_varianza(marco, col)
        s2c, _ = sigma2_por_celda(marco, col, sigma2_global=sigma2)
        votos = tabla_votos(marco, col, tau2=tau2, sigma2=sigma2, sigma2_celda=s2c)

        # Vectorizado. Un bucle por celda son 65.081 iteraciones de pandas y minutos
        # de espera; `_cuantil_por_grupo` lo hace de una pasada. Es el mismo error
        # que ya se corrigio dos veces en el paquete, asi que aqui se reutiliza.
        v = votos.sort_values([col, "voto"], kind="mergesort")
        cod, celdas = pd.factorize(v[col], sort=True)
        o = np.argsort(cod, kind="stable")
        cod = cod[o]
        vv = v["voto"].to_numpy(float)[o]
        ww = v["w"].to_numpy(float)[o]
        n = len(celdas)
        m = _cuantil_por_grupo(cod, vv, ww, n)
        W = np.bincount(cod, weights=ww, minlength=n)
        emp = np.bincount(cod, minlength=n).astype(int)
        celdas = list(celdas)

        Z = np.vstack([X_por_etiqueta[c] for c in celdas]).astype(float)
        Z /= np.linalg.norm(Z, axis=1, keepdims=True)
        m, W, emp = np.array(m), np.array(W), np.array(emp, dtype=int)

        # `lambda` sale de una MUESTRA de celdas. Todas contra todas son 65.081^2 x 768
        # dimensiones —unos 3 billones de operaciones— para estimar un solo escalar. Con
        # 3.000 celdas la estimacion ya es estable y tarda segundos.
        rng = np.random.default_rng(20260805)
        muestra = (rng.choice(n, 3000, replace=False) if n > 3000 else np.arange(n))
        vec_s, sim_s = _vecinos(Z[muestra], Z, VECINOS, excluir_propio=False)
        lam = _lambda_semantica(m[muestra], W[muestra], vec_s, sim_s, m_todos=m, W_todos=W)
        niv = np.array([nivel_lexico(c) if nivel_lexico(c) else np.nan
                        for c in celdas], dtype=float)
        ef = efecto_nivel(marco, col=col)
        return cls(celdas, m, W, emp, Z, tau2, sigma2, lam, sbu, niv, ef)

    # -- persistencia ----------------------------------------------------------

    def guardar(self, ruta):
        """Un solo `.npz`. Construir la base tarda minutos —descargar un millon de filas
        y embeber 65.081 titulos—; cargarla debe tardar segundos. Sin esto, cada consulta
        de un cliente rehace todo el trabajo."""
        np.savez_compressed(
            ruta, celdas=np.array(self.celdas, dtype=object), m=self.m, W=self.W,
            emp=self.emp, Z=self.Z.astype(np.float32), nivel=self.nivel,
            ef_k=np.array(sorted(self.efecto), dtype=float),
            ef_v=np.array([self.efecto[k] for k in sorted(self.efecto)], dtype=float),
            escalares=np.array([self.tau2, self.sigma2, self.lam], dtype=float))

    @classmethod
    def cargar(cls, ruta, sbu):
        with np.load(ruta, allow_pickle=True) as z:
            tau2, sigma2, lam = z["escalares"]
            ef = {int(k): float(v) for k, v in zip(z["ef_k"], z["ef_v"])}
            return cls(list(z["celdas"]), z["m"], z["W"], z["emp"],
                       z["Z"].astype(float), float(tau2), float(sigma2), float(lam),
                       sbu, z["nivel"], ef)

    # -- consulta --------------------------------------------------------------

    def referenciar(self, titulos, X_por_etiqueta, anio=None):
        """Una fila por titulo: referencia, intervalo, confianza y en que se basa."""
        titulos = [str(t) for t in titulos]
        unicos = sorted(set(titulos))
        Q = np.vstack([X_por_etiqueta[t] for t in unicos]).astype(float)
        Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        vec, sim = _vecinos(Q, self.Z, VECINOS, excluir_propio=False)

        filas = {}
        for k, t in enumerate(unicos):
            propio = self.idx.get(t)
            directo = propio is not None and self.emp[propio] >= MIN_EMPRESAS
            if directo:
                mu = self.m[propio]
                var = self.tau2 + self.sigma2 + 1.0 / self.W[propio]
                base, n_emp = "datos directos", int(self.emp[propio])
                mejor, directo_ok = 1.0, True
            else:
                j, s = vec[k], sim[k]
                if propio is not None:              # existe pero es demasiado delgada
                    quitar = j != propio
                    j, s = j[quitar], s[quitar]
                dist = self.lam * (1.0 - s)
                var_j = 1.0 / self.W[j] + dist
                peso = 1.0 / var_j
                peso /= peso.sum()

                # AJUSTE POR NIVEL. Los vecinos vienen del area ENMASCARADA, asi que un
                # `JEFE DE BODEGA` es vecino de un `AUXILIAR DE BODEGA` — misma area,
                # distinto escalon, y entre el 1 y el 5 hay 2,37x de pago. No hay que
                # descartarlo: el efecto de cada escalon esta MEDIDO, asi que se le resta
                # al vecino su escalon y se le suma el del puesto que se pregunta.
                #
                # Si no se sabe el nivel del puesto preguntado no se puede ajustar, y esa
                # ignorancia se paga en el intervalo (`var_nivel`), no fingiendo certeza.
                aj = np.zeros(len(j))
                mi = self.nivel[propio] if propio is not None else nivel_lexico(t)
                if mi is not None and np.isfinite(mi) and self.efecto:
                    ei = self.efecto.get(int(mi), 0.0)
                    aj = np.array([ei - self.efecto.get(int(nj), ei)
                                   if np.isfinite(nj) else 0.0 for nj in self.nivel[j]])
                    penal_nivel = 0.0
                else:
                    penal_nivel = self.var_nivel
                mu = float((peso * (self.m[j] + aj)).sum())
                # Las dos partes NO se promedian igual. El error de medicion de cada
                # vecino es independiente y se cancela al promediar (suma de peso^2). La
                # distancia semantica es un SESGO compartido: si los 25 vecinos estan
                # igual de lejos, promediarlos no acerca la respuesta. Tratarla como ruido
                # hacia que `LOTERO` —sin vecindario real— saliera con un intervalo
                # estrecho por el mero hecho de promediar mucha gente equivocada.
                var = (self.tau2 + self.sigma2
                       + float((peso ** 2 / self.W[j]).sum())
                       + float((peso * dist).sum())
                       + penal_nivel)
                base = "por analogia"
                n_emp = int(self.emp[j].sum())
                mejor, directo_ok = float(s.max()), False
            sd = float(np.sqrt(var))
            conf, ancho = _confianza(sd, np.sqrt(self.tau2 + self.sigma2),
                                     directo_ok)
            filas[t] = {"referencia_log": mu, "sd": sd,
                        "p25_log": mu - 0.6745 * sd, "p75_log": mu + 0.6745 * sd,
                        "confianza": conf, "base": base, "ancho_rel": round(ancho, 3),
                        "empresas": n_emp, "similitud": round(mejor, 3)}

        out = pd.DataFrame([filas[t] for t in titulos])
        out.insert(0, "cargo", titulos)
        if anio is not None:
            f = float(self.sbu(int(anio)))
            for col, nueva in (("referencia_log", "referencia"), ("p25_log", "p25"),
                               ("p75_log", "p75")):
                out[nueva] = (np.exp(out[col]) * f).round(2)
        return out


def _vecinos(Q, B, k, excluir_propio):
    """(indices, similitudes) de los k vecinos de cada fila de Q dentro de B."""
    # argpartition exige kth < n, asi que con bases pequenas hay que recortar. Pasa en
    # los tests y en clientes con catalogos cortos, no en produccion.
    k = max(1, min(k, B.shape[0] - 1))
    vec = np.zeros((Q.shape[0], k), dtype=np.int32)
    sim = np.zeros((Q.shape[0], k), dtype=float)
    paso = 512
    for i0 in range(0, Q.shape[0], paso):
        S = Q[i0:i0 + paso] @ B.T
        for r in range(S.shape[0]):
            fila = S[r]
            if excluir_propio:
                fila[i0 + r] = -np.inf
            cand = np.argpartition(-fila, k)[:k]
            cand = cand[np.argsort(-fila[cand])]
            vec[i0 + r] = cand
            sim[i0 + r] = np.clip(fila[cand], 0.0, None)
    return vec, sim
