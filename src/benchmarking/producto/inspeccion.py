"""Mirar QUE se junto en cada puesto, para poder juzgarlo a ojo.

PARA QUE EXISTE. La consolidacion de grafias decide el denominador de todo el
benchmark, y hasta ahora la unica forma de auditarla era abrir el `.npz` a mano
en un interprete. Eso significa que en la practica no se audita: cuando el front
ofrecia `VEDEDOR` en el desplegable hubo que escribir diez lineas de numpy para
ver de donde salia.

Aqui se le pasa una lista de cargos —o una nomina pequena— y devuelve, por cada
uno, el grupo en el que cayo con TODAS sus grafias. Es lectura pura sobre la base
serializada: no toca BigQuery, no embebe nada y no necesita red.

LO QUE NO HACE, y conviene saberlo: para un titulo que NO esta en la base no
puede ensenar sus vecinos semanticos, porque eso exige embeberlo contra Vertex.
Se dice que no esta y se acabo; los vecinos se ven en `/puestos`, que si tiene
red.

CON `--vecinos` se anade lo contrario y es igual de util: los grupos mas
parecidos que NO se fusionaron, con su similitud. Es donde se ve si el umbral se
quedo corto —`SECRETARIO/A GENERAL` a 0,955 de `SECRETARIO GENERAL`— o si hizo
bien su trabajo —`COORDINADOR` a 0,951 de `JEFE`, que son escalones distintos.
"""
import numpy as np

from .base_referencia import CORTE_ALTA, CORTE_MEDIA, MIN_EMPRESAS, MIN_PERSONAS


def _confianza(var_centro):
    """Misma regla que `base_referencia._confianza`, sobre `1/W` de la celda."""
    pct = float(np.exp(np.sqrt(max(float(var_centro), 0.0))) - 1.0)
    if pct <= CORTE_ALTA:
        return "ALTA", pct
    if pct <= CORTE_MEDIA:
        return "MEDIA", pct
    return "BAJA", pct


def _representante(grafias, frec):
    """La grafia que se le ensena al usuario. Copia de la regla del servicio.

    Se puntua por la palabra MENOS frecuente del titulo, porque una errata es rara
    por definicion y un dedazo en cualquier palabra delata al titulo entero.
    """
    def clave(t):
        raro = min((frec.get(w, 0) for w in t.split()), default=0)
        return (-raro, sum(1 for c in t if not (c.isalnum() or c == " ")), len(t), t)
    return min(grafias, key=clave)


class Inspector:
    """Consultas de solo lectura sobre una base serializada."""

    def __init__(self, ruta):
        d = np.load(ruta, allow_pickle=True)
        self.celdas = [str(c) for c in d["celdas"]]
        self.idx = {c: i for i, c in enumerate(self.celdas)}
        self.grupo = d["grupo"].astype(np.int64)
        self.emp, self.personas = d["emp"], d["personas"]
        self.m, self.W = d["m"], d["W"]
        self.bandas = d["bandas"]
        self.nivel = d["nivel"]
        self._Z = d["Z"]                      # se normaliza solo si hace falta
        self._Zn = None

        self.miembros = {}
        for i, g in enumerate(self.grupo):
            self.miembros.setdefault(int(g), []).append(i)

        # CLAVE DURA: solo letras y digitos. El pipeline normaliza el cargo del
        # cliente con `strip().upper()` y nada mas, asi que `Contador.` no encuentra
        # a `CONTADOR` y se va por analogia. Es correcto —no se puede inventar una
        # coincidencia que la base no tiene— pero al auditar hace falta VER que la
        # respuesta estaba ahi al lado, que es lo que esto permite decir.
        self.dura = {}
        for i, c in enumerate(self.celdas):
            self.dura.setdefault("".join(ch for ch in c if ch.isalnum()), []).append(i)

        # Frecuencia de cada palabra en todo el catalogo, para el representante.
        self.frec = {}
        for c in self.celdas:
            for w in c.split():
                self.frec[w] = self.frec.get(w, 0) + 1

    @property
    def Z(self):
        """Vectores normalizados. Se calculan en la primera consulta de vecinos."""
        if self._Zn is None:
            Z = self._Z.astype(np.float32)
            self._Zn = Z / np.linalg.norm(Z, axis=1, keepdims=True)
        return self._Zn

    def ficha(self, titulo, sbu, k_vecinos=0):
        """Todo lo que se sabe de un cargo. `None` en `grupo` si no esta en la base."""
        t = str(titulo or "").strip().upper()
        i = self.idx.get(t)
        if i is None:
            # No esta con esa grafia exacta. .Esta la misma cadena sin puntuacion?
            k = "".join(ch for ch in t if ch.isalnum())
            casi = sorted({self.celdas[j] for j in self.dura.get(k, [])})
            return {"pedido": titulo, "norm": t, "grupo": None, "casi": casi}

        g = int(self.grupo[i])
        hermanas = sorted(self.celdas[j] for j in self.miembros[g])
        directo = (self.emp[i] >= MIN_EMPRESAS and self.personas[i] >= MIN_PERSONAS)
        conf, pct = _confianza(1.0 / self.W[i]) if self.W[i] > 0 else ("BAJA", 1.0)
        b = np.exp(self.bandas[i]) * sbu

        ficha = {
            "pedido": titulo, "norm": t, "grupo": g,
            "grafias": hermanas,
            "representante": _representante(hermanas, self.frec),
            "empresas": int(self.emp[i]), "personas": int(self.personas[i]),
            "nivel": None if not np.isfinite(self.nivel[i]) else int(self.nivel[i]),
            "directo": bool(directo),
            "centro": float(np.exp(self.m[i]) * sbu),
            "p10": b[0], "p25": b[1], "p75": b[2], "p90": b[3],
            "confianza": conf, "incert": pct,
            "vecinos": [],
        }
        if k_vecinos:
            ficha["vecinos"] = self.vecinos(i, k_vecinos)
        return ficha

    def vecinos(self, i, k):
        """Los `k` grupos mas parecidos que NO son el suyo, con su similitud.

        Es la mitad interesante de la auditoria: no lo que se junto, sino lo que se
        quedo fuera y por cuanto.
        """
        s = self.Z @ self.Z[i]
        s[self.grupo == self.grupo[i]] = -1.0
        vistos, salida = set(), []
        for j in np.argsort(-s):
            g = int(self.grupo[j])
            if g in vistos:
                continue
            vistos.add(g)
            salida.append({"cargo": self.celdas[j], "similitud": float(s[j]),
                           "empresas": int(self.emp[j]),
                           "nivel": (None if not np.isfinite(self.nivel[j])
                                     else int(self.nivel[j]))})
            if len(salida) >= k:
                break
        return salida


def imprimir(f):
    """Una ficha, legible en una terminal."""
    print("=" * 74)
    if f["grupo"] is None:
        print("%s   ->   NO ESTA CON ESA GRAFIA" % f["norm"])
        if f.get("casi"):
            print("   se resolveria POR ANALOGIA, aunque la base tiene la misma")
            print("   cadena sin la puntuacion:  %s" % ", ".join(f["casi"][:4]))
        else:
            print("   se resolveria por analogia; los vecinos se ven en /puestos")
        print()
        return

    cab = "%s   ->   grupo %d" % (f["norm"], f["grupo"])
    if f["norm"] != f["representante"]:
        cab += "   (se muestra como %s)" % f["representante"]
    print(cab)
    print("=" * 74)
    print("  %d grafias | %d empresas | %d personas | escalon %s | %s"
          % (len(f["grafias"]), f["empresas"], f["personas"],
             f["nivel"] if f["nivel"] else "-",
             "datos directos" if f["directo"] else "POR ANALOGIA (no llega al suelo)"))
    print()
    # Las columnas se dimensionan con la grafia mas larga del grupo: con un ancho
    # fijo, `ASISTENTE ADMINISTRATIVO` y sus 26 variantes salian pegadas.
    ancho = max(len(g) for g in f["grafias"]) + 2
    por_fila = max(1, 72 // ancho)
    for k in range(0, len(f["grafias"]), por_fila):
        print("    " + "".join("%-*s" % (ancho, g)
                               for g in f["grafias"][k:k + por_fila]).rstrip())
    print()
    print("  centro $%.0f | mitad central $%.0f - $%.0f | confianza %s (%.1f%%)"
          % (f["centro"], f["p25"], f["p75"], f["confianza"], 100 * f["incert"]))
    if f["vecinos"]:
        print()
        print("  grupos parecidos que NO se fusionaron:")
        for v in f["vecinos"]:
            print("    %.3f  %-38s %4d empresas  escalon %s"
                  % (v["similitud"], v["cargo"][:38], v["empresas"],
                     v["nivel"] if v["nivel"] else "-"))
    print()
