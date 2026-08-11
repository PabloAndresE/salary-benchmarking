"""Data sintética con la respuesta conocida.

Si el banco no ordena correctamente la partición verdadera frente a una aleatoria,
está mal el BANCO. Descubrirlo aquí cuesta segundos; descubrirlo tras nueve semanas
midiendo con una regla torcida, no.

Los roles se separan por COMPOSICIÓN del pago y antigüedad, con los sueldos solapándose
por el ruido individual y el efecto empresa, para que una partición por bandas de sueldo
NO apruebe el examen. Si se separaran por nivel salarial, el techo supervisado —que agrupa
mirando el sueldo— pasaría la prueba de aceptación sin demostrar nada.
"""
import numpy as np
import pandas as pd

# (nombre, pct_comisiones medio, pct_extras medio, antigüedad media, multiplicador salarial)
_ROLES = [("comercial", 0.45, 0.02, 6.0, 1.8),
          ("operativo", 0.01, 0.28, 9.0, 1.0),
          ("administrativo", 0.02, 0.03, 11.0, 1.3),
          ("tecnico", 0.05, 0.15, 7.0, 1.5)]

# Etiquetas sucias a propósito: la misma vale para varios roles, como TRABAJADOR EN
# GENERAL en los datos reales.
_CARGOS = {"comercial": ["VENDEDOR", "ASESOR COMERCIAL", "TRABAJADOR EN GENERAL"],
           "operativo": ["OPERARIO", "TRABAJADOR EN GENERAL", "OBRERO"],
           "administrativo": ["ASISTENTE", "TRABAJADOR EN GENERAL", "AUXILIAR"],
           "tecnico": ["TECNICO", "ASISTENTE", "OPERARIO"]}


def generar(n_empresas=40, personas_por_empresa=25, n_roles=3, semilla=20260805,
            anio=2025, sbu=470, desiguales=False):
    """DataFrame con la misma forma que `nomina_features`, más `rol_verdadero`.

    `desiguales=True` hace que las empresas tengan tamaños muy distintos, necesario para
    poder testear la ponderación por empresa: si todas aportan lo mismo, ponderar por
    persona y por empresa dan el mismo resultado y el test no probaría nada.
    """
    rng = np.random.default_rng(semilla)
    roles = _ROLES[:n_roles]
    filas = []
    for e in range(n_empresas):
        ruc = f"179{e:07d}001"
        # Efecto empresa. La desviacion esta calibrada para reproducir el valor MEDIDO
        # sobre 2025: eta2_empresa del log-salario = 0,388 (485.084 personas, 5.269
        # empresas). Con 0,35 salia ~0,57 — mas facil que la realidad justo en el eje que
        # el leave-company-out neutraliza, que es la parte que hay que poner dificil.
        nivel_empresa = rng.normal(0.0, 0.24)
        n = personas_por_empresa * (1 + 4 * (e % 5)) // 3 if desiguales else personas_por_empresa
        for p in range(n):
            # el índice recorre los roles dentro de cada empresa: todas tienen de todo,
            # así la variación de rol es intra-empresa y no infla el efecto empleador
            nombre, m_com, m_ext, m_ant, mult = roles[(e * n + p) % len(roles)]
            base = sbu * mult * np.exp(nivel_empresa + rng.normal(0.0, 0.18))
            pc = float(np.clip(rng.normal(m_com, 0.08), 0.0, 0.85))
            pe = float(np.clip(rng.normal(m_ext, 0.05), 0.0, 0.60))
            po = float(np.clip(rng.normal(0.02, 0.02), 0.0, 0.30))
            pf = max(1.0 - pc - pe - po, 0.05)
            filas.append({
                "id_hash": f"h{e:04d}{p:04d}", "empresa_ruc": ruc,
                "numero_proceso": f"P{e:05d}", "anio_valoracion": anio,
                "rol_verdadero": nombre,
                "cargo": _CARGOS[nombre][p % len(_CARGOS[nombre])],
                "sueldo": round(base, 2),
                "pct_fijo": pf, "pct_comisiones": pc, "pct_extras": pe, "pct_otros": po,
                "antiguedad_total": int(max(0, rng.normal(m_ant, 3.0))),
                "segmento": ["MICRO", "PEQUENA", "MEDIANA", "GRANDE"][e % 4],
                "ciiu_n1": chr(ord("A") + (e % 8)),
                "provincia": f"{(e % 24) + 1:02d}",
                "en_clean": True, "tiene_composicion": True})
    df = pd.DataFrame(filas)
    df["cargo_norm"] = df["cargo"]
    return df
