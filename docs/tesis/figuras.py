"""Las figuras de la tesis y de la presentacion, en PDF vectorial.

    python docs/tesis/figuras.py

CADA CIFRA TIENE PROCEDENCIA. Las de la escalera y la descomposicion del error estan
escritas aqui con su fuente al lado —salen de `docs/mediciones.md`, que a su vez
referencia el script que las midio— y la del espesor del catalogo se calcula en vivo
desde la base de referencia. Ninguna se inventa: si una cambia, cambia en `mediciones.md`
primero y aqui despues.

DECISIONES DE FORMA, por si alguien las revisa:

  - La ESCALERA se expresa como multiplo salarial respecto al nivel 1, no como el efecto
    centrado. El efecto cruza cero solo porque es un residuo tras quitar empresa y area, y
    pintar eso con colores divergentes destacaria una frontera que no significa nada. Como
    multiplo, el 2,11x que cita la tesis se lee directo del eje.

  - La DESCOMPOSICION va en barra apilada y no en dos barras sueltas: la pregunta es que
    FRACCION del error es reducible, y una parte-de-un-todo se lee apilada. El suelo
    irreducible va en gris —es contexto— y lo reducible en color, que es el sujeto.

  - El ESPESOR lleva dos series porque la tension es justo esa: casi todos los titulos son
    delgados y casi toda la gente esta en los gruesos. Una sola serie no la muestra.

Paleta: la de referencia del metodo de visualizacion, validada (CVD dE 24,7 entre las dos
series, umbral 8). Todas las barras llevan su valor impreso, asi que la identidad nunca
depende solo del color — importa porque una tesis se imprime en blanco y negro.
"""
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter


def es(x, dec=2):
    """Numero con coma decimal y punto de millar.

    El documento esta en espanol y el formateador por defecto de matplotlib escribe
    `0.5`, que en una tesis en castellano se lee como otra cosa.
    """
    t = "{:,.{}f}".format(x, dec)
    return t.replace(",", "\x01").replace(".", ",").replace("\x01", ".")

SALIDA = pathlib.Path(__file__).parent / "figuras"
BASE = "demo/base_v15.npz"

# --- paleta de referencia, valores claros (impresion sobre blanco) -------------
TINTA = "#0b0b0b"          # texto primario
TINTA_2 = "#52514e"        # texto secundario
AZUL = "#2a78d6"           # categorica 1
NARANJA = "#eb6834"        # categorica 2
GRIS = "#d6d5d1"           # neutro: lo que NO es el sujeto
REJILLA = "#e8e7e4"

plt.rcParams.update({
    "font.family": "serif",          # para que case con el cuerpo del documento
    "font.size": 9,
    "axes.edgecolor": TINTA_2,
    "axes.labelcolor": TINTA,
    "text.color": TINTA,
    "xtick.color": TINTA_2,
    "ytick.color": TINTA_2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})


def _limpia(ax, eje_x=True):
    """Rejilla recesiva y sin adornos. El dato manda, no el marco."""
    ax.grid(axis="x" if eje_x else "y", color=REJILLA, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for s in ("left", "bottom"):
        ax.spines[s].set_linewidth(0.6)


# =============================================================================
def fig_escalera():
    """El eje que si paga: recorrido de 2,11x entre el escalon 1 y el 5.

    Fuente: `docs/mediciones.md` 15.4, escalera monotona dentro de empresa y area.
    """
    niveles = [
        ("1 · ayudante, auxiliar,\noperario, asistente", -0.1202, 131_314),
        ("2 · técnico, analista", -0.0860, 27_715),
        ("3 · supervisor, coordinador,\nespecialista", 0.0542, 29_336),
        ("4 · jefe, subgerente", 0.3109, 26_611),
        ("5 · gerente, director", 0.6270, 13_236),
    ]
    # `n` va en la etiqueta del eje y no al lado de la barra: alli chocaba con el
    # valor y la ultima fila se salia del margen derecho.
    etiquetas = [n[0] + "\n(n = " + es(n[2], 0) + ")" for n in niveles]
    efecto = np.array([n[1] for n in niveles])
    n_pers = [n[2] for n in niveles]
    # multiplo salarial respecto al nivel 1: exp(efecto - efecto_1)
    mult = np.exp(efecto - efecto[0])

    fig, ax = plt.subplots(figsize=(5.6, 3.1))
    y = np.arange(len(niveles))
    ax.barh(y, mult, height=0.62, color=AZUL, zorder=3)
    ax.set_yticks(y, etiquetas, fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 2.42)
    ax.set_xlabel("Salario relativo al escalón más bajo", color=TINTA_2, fontsize=8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: es(v, 1) + "×"))
    _limpia(ax)

    for i, m in enumerate(mult):
        ax.text(m + 0.05, i, es(m) + "×", va="center", ha="left",
                fontsize=9, color=TINTA, fontweight="bold")
    # NO se anota el recorrido con una flecha: las barras ya dicen 1,00x y 2,11x, y la
    # flecha chocaba con la etiqueta de la ultima fila.
    fig.savefig(SALIDA / "escalera_niveles.pdf")
    plt.close(fig)
    return f"escalera: {mult[0]:.2f}x -> {mult[-1]:.2f}x"


# =============================================================================
def fig_descomposicion():
    """Cuanto del error es reducible agrupando mejor. El resto lo pone el empleador.

    Fuente: `docs/mediciones.md` 15.3.
    """
    filas = [
        ("Todo el conjunto\nde ajuste", 0.3700, 0.3253),
        ("Lejos del piso\ndel SBU  (y > 0,05)", 0.4322, 0.3750),
    ]
    fig, ax = plt.subplots(figsize=(5.6, 2.0))
    y = np.arange(len(filas))
    for i, (_, real, suelo) in enumerate(filas):
        reducible = real - suelo
        # apilada: suelo (contexto) + lo reducible (sujeto), con 2px de aire entre medias
        ax.barh(i, suelo, height=0.5, color=GRIS, zorder=3)
        ax.barh(i, reducible, left=suelo + 0.004, height=0.5, color=AZUL, zorder=3)
        ax.text(suelo / 2, i, "irreducible", va="center", ha="center",
                fontsize=7.5, color=TINTA_2)
        ax.text(real + 0.012, i, es(100 * reducible / real, 1) + "%",
                va="center", ha="left", fontsize=9, color=TINTA, fontweight="bold")

    ax.set_yticks(y, [f[0] for f in filas], fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 0.50)
    ax.set_xlabel("Desviación estándar del error, en log(sueldo / SBU)",
                  color=TINTA_2, fontsize=8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: es(v, 1)))
    _limpia(ax)
    # La explicacion va al \caption de LaTeX y no dentro de la imagen: ahi dentro no se
    # puede corregir sin regenerar el PDF, y compite con el pie de figura del documento.
    fig.savefig(SALIDA / "descomposicion_error.pdf")
    plt.close(fig)
    return "descomposicion: 12,1% y 13,2%"


# =============================================================================
def fig_espesor():
    """Casi todos los titulos son delgados; casi toda la gente esta en los gruesos."""
    sys.path.insert(0, "src")
    from benchmarking.config.settings import cargar_settings
    from benchmarking.producto.base_referencia import BaseReferencia

    s = cargar_settings()
    b = BaseReferencia.cargar(BASE, s.get_sbu)
    # una fila por PUESTO, no por grafia: las grafias comparten respaldo y contarlas
    # por separado inflaria la cola delgada, que es justo lo que la figura mide
    vistos, emp, per = set(), [], []
    for i in range(len(b.celdas)):
        g = int(b.grupo[i])
        if g in vistos:
            continue
        vistos.add(g)
        emp.append(int(b.emp[i]))
        per.append(int(b.personas[i]))
    emp, per = np.array(emp), np.array(per)

    cortes = [(1, 1, "1"), (2, 2, "2"), (3, 4, "3–4"), (5, 9, "5–9"),
              (10, 29, "10–29"), (30, 10**9, "30+")]
    etiquetas, pct_tit, pct_per = [], [], []
    for lo, hi, et in cortes:
        m = (emp >= lo) & (emp <= hi)
        etiquetas.append(et)
        pct_tit.append(100 * m.sum() / len(emp))
        pct_per.append(100 * per[m].sum() / per.sum())

    fig, ax = plt.subplots(figsize=(5.6, 2.9))
    x = np.arange(len(cortes))
    w = 0.38
    ax.bar(x - w / 2 - 0.01, pct_tit, w, color=AZUL, zorder=3, label="Puestos")
    ax.bar(x + w / 2 + 0.01, pct_per, w, color=NARANJA, zorder=3, label="Personas")
    for xi, (a, c) in enumerate(zip(pct_tit, pct_per)):
        ax.text(xi - w / 2 - 0.01, a + 1.2, f"{a:.0f}%", ha="center",
                fontsize=7.5, color=TINTA)
        ax.text(xi + w / 2 + 0.01, c + 1.2, f"{c:.0f}%", ha="center",
                fontsize=7.5, color=TINTA)

    ax.set_xticks(x, etiquetas)
    ax.set_xlabel("Empresas que respaldan el puesto", color=TINTA_2, fontsize=8)
    ax.set_ylabel("% del total", color=TINTA_2, fontsize=8)
    ax.set_ylim(0, max(max(pct_tit), max(pct_per)) * 1.18)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    _limpia(ax, eje_x=False)
    ax.legend(frameon=False, fontsize=8, loc="upper right",
              labelcolor=TINTA_2, handlelength=1.1)
    fig.savefig(SALIDA / "espesor_catalogo.pdf")
    plt.close(fig)
    return (f"espesor: {len(emp):,} puestos; "
            f"{pct_tit[0]:.0f}% con 1 empresa cubren {pct_per[0]:.0f}% de la gente")



# =============================================================================
def fig_sesgo_tamano():
    """Sin corregir por tamano, a una empresa pequena se le dice que su gerente cobra un
    56% por debajo del mercado — y entre sus pares esta bien.

    Es la figura mas vendible del expediente porque el error es enorme, concreto y de
    los que un cliente puede comprobar por su cuenta.

    Fuente: `docs/mediciones.md` 17.6 y D-018.
    """
    tam = ["Pequeña", "Mediana", "Grande"]
    sin = [-56.0, -15.8, +81.9]
    con = [-12.1, +6.9, +17.9]

    fig, ax = plt.subplots(figsize=(5.6, 2.7))
    x = np.arange(len(tam))
    w = 0.38
    ax.bar(x - w / 2 - 0.01, sin, w, color=GRIS, zorder=3, label="Sin corregir")
    ax.bar(x + w / 2 + 0.01, con, w, color=AZUL, zorder=3, label="Corregido por tamaño")
    ax.axhline(0, color=TINTA_2, linewidth=0.9, zorder=4)

    for xi, (a, c) in enumerate(zip(sin, con)):
        ax.text(xi - w / 2 - 0.01, a + (4 if a > 0 else -9), es(a, 1) + "%",
                ha="center", fontsize=8, color=TINTA)
        ax.text(xi + w / 2 + 0.01, c + (4 if c > 0 else -9), es(c, 1) + "%",
                ha="center", fontsize=8, color=TINTA, fontweight="bold")

    ax.set_xticks(x, tam)
    ax.set_xlabel("Tamaño de la empresa", color=TINTA_2, fontsize=8)
    ax.set_ylabel("Error del diagnóstico", color=TINTA_2, fontsize=8)
    ax.set_ylim(-72, 98)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: es(v, 0) + "%"))
    _limpia(ax, eje_x=False)
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              labelcolor=TINTA_2, handlelength=1.1)
    fig.savefig(SALIDA / "sesgo_tamano.pdf")
    plt.close(fig)
    return ("sesgo por tamano: de %s/%s a %s/%s"
            % (es(sin[0], 1), es(sin[2], 1), es(con[0], 1), es(con[2], 1)))


if __name__ == "__main__":
    SALIDA.mkdir(parents=True, exist_ok=True)
    for f in (fig_escalera, fig_descomposicion, fig_espesor,
              fig_sesgo_tamano):
        print(" ", f(), flush=True)
    print("\nPDFs en", SALIDA)
