import numpy as np
import pandas as pd
from sintetico import generar


def test_estructura_basica():
    df = generar(n_empresas=10, personas_por_empresa=20, n_roles=3)
    assert len(df) == 200
    assert df["empresa_ruc"].nunique() == 10
    assert df["rol_verdadero"].nunique() == 3
    assert df["id_hash"].is_unique
    assert "identificacion" not in df.columns          # frontera de privacidad


def test_los_roles_se_separan_por_composicion_no_por_sueldo():
    # Si se separaran por sueldo, una particion por bandas salariales aprobaria el
    # examen del banco y no probariamos nada.
    df = generar(n_empresas=30, personas_por_empresa=20, n_roles=3)
    comp = df.groupby("rol_verdadero")["pct_comisiones"].mean().sort_values()
    assert comp.iloc[-1] - comp.iloc[0] > 0.25


def test_el_efecto_empresa_se_parece_al_real():
    # Medido sobre 2025: eta2_empresa del log-salario = 0,388. La data sintetica debe
    # reproducirlo, no algo mas facil: es el eje que el leave-company-out neutraliza, y
    # si aqui fuera pequeno la prueba de aceptacion del banco seria mas benevola que la
    # realidad.
    df = generar(n_empresas=30, personas_por_empresa=20, n_roles=3)
    y = np.log(df["sueldo"])
    g = df.assign(y=y).groupby("empresa_ruc")["y"].agg(["mean", "size"])
    eta2 = (g["size"] * (g["mean"] - y.mean()) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    assert 0.25 < eta2 < 0.55, f"eta2_empresa={eta2:.3f}, lejos del 0,388 real"


def test_tamanos_de_empresa_desiguales():
    # Necesario para que la ponderacion por empresa sea testeable: si todas las
    # empresas aportan lo mismo, ponderar por persona y por empresa coinciden.
    df = generar(n_empresas=20, personas_por_empresa=25, desiguales=True)
    n = df.groupby("empresa_ruc").size()
    assert n.max() >= 4 * n.min()


def test_determinista():
    pd.testing.assert_frame_equal(generar(n_empresas=5, personas_por_empresa=10, semilla=7),
                                  generar(n_empresas=5, personas_por_empresa=10, semilla=7))
