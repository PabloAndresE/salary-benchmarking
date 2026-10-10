"""D-075: clasificador «¿es un cargo?» sobre el embedding de Vertex.

Pasos:
    qwen       Qwen3.5-122B local genera textos que NO son cargos (~40 categorias x 3 semillas) + sin sentido por
               programa. Se quitan titulos de la base y la tercera lista de D-074.
    embeber    Vertex sobre los negativos.
    entrenar   positivos = titulos de empresas de entrenamiento; negativos 80/20; regresion logistica; umbral u =
               el menor que rechaza <= 2 % de los votos reales apartados por analogia (tam_A).
    confirmar  UNA vez, la tercera lista de D-074 (+ listas vistas y controles, para reportar).

    CUDA_VISIBLE_DEVICES=1,3 ../../../.venv-llm/bin/python 82_es_cargo.py qwen
    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 82_es_cargo.py embeber|entrenar|confirmar

SALIDAS: salidas/82_negativos.parquet, 82_emb_negativos.npz, 82_clasificador.npz, 82_es_cargo.txt
"""
import json
import os
import pathlib
import re
import sys

import numpy as np
import pandas as pd

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))

CATEGORIAS = """animales domesticos; animales salvajes; aves e insectos; frutas y verduras; platos de comida y bebidas;
postres y golosinas; muebles y objetos del hogar; electrodomesticos y aparatos; ropa y accesorios; partes del cuerpo;
colores y formas; paises, ciudades y lugares geograficos; fenomenos naturales y clima; planetas y astronomia;
personajes de fantasia, mitologia y cuentos; superheroes y personajes de peliculas; saludos y frases de cortesia;
frases cotidianas sin sentido laboral; respuestas vacias de formulario (no aplica, ninguno, sin dato, etc.);
nombres y apellidos de personas; marcas comerciales y productos; deportes y juegos; instrumentos musicales;
peliculas, canciones y libros; emociones y estados de animo; verbos sueltos; adjetivos sueltos; frases en ingles
cotidianas; palabras en ingles que no son cargos; vehiculos y medios de transporte; plantas y flores; materiales y
sustancias; festividades y celebraciones; partes de una casa o edificio; utiles escolares y de oficina;
juguetes; enfermedades y sintomas; numeros escritos con letras y codigos; insultos suaves o bromas inofensivas;
textos de prueba que escribe un programador (test, prueba, foo, bar)""".replace("\n", " ").split(";")
CATEGORIAS = [c.strip() for c in CATEGORIAS if c.strip()]
TERCERA = ["ZXCVBN", "POIUYT", "ABCDEF", "999", "XYZ 123", "OTRA COSA", "NO SE", "NI IDEA", "LO QUE SEA", "NADA",
           "PERSONA", "ALGUIEN", "JIRAFA", "LEON MARINO", "PINGUINO", "MARIPOSA", "PAPAYA", "ARROZ CON POLLO",
           "EMPANADA", "HELADO DE FRESA", "CAMA", "ESPEJO", "TELEVISOR", "BICICLETA", "OCEANO", "VOLCAN", "ARCOIRIS",
           "FANTASMA", "BRUJA", "ROBOT ASESINO", "ALIEN", "CABALLERO JEDI", "THE CAT IS ON THE TABLE",
           "MY NAME IS JOHN", "GOOD MORNING", "LOREM DOLOR", "MMMM", "QQQQ", "CARGO 1", "TITULO DEL PUESTO"]
VIEJA = ["ASDFGH QWERTY", "XXXXX", "AAAA BBBB", "123456", "LOREM IPSUM", "TEST", "PRUEBA PRUEBA", "NINGUNO", "N/A",
         "HOLA MUNDO", "ASTRONAUTA", "DOMADOR DE LEONES", "MAGO", "UNICORNIO", "PIRATA", "VAMPIRO", "SUPERHEROE",
         "DRAGON", "ZZZZ", "QWERTYUIOP", "MESA", "SILLA", "PERRO", "GATO", "PIZZA", "FUTBOL", "BANANA", "CIELO AZUL",
         "JKLÑ", "????"]
NUEVA = ["QWERASDF", "JJJJJ", "ABC123", "0000", "PALABRA", "COSA", "NADA QUE VER", "HOLA COMO ESTAS", "BUENOS DIAS",
         "SIN CARGO", "NO APLICA", "XXX YYY", "ELEFANTE", "CABALLO", "TORTUGA", "MANZANA", "HAMBURGUESA",
         "CAFE CON LECHE", "SOFA", "VENTANA", "LAPIZ", "MONTANA", "PLAYA", "LUNA", "ESTRELLA FUGAZ", "ZOMBIE",
         "HADA MADRINA", "MAGO DE OZ", "DINOSAURIO", "NAVE ESPACIAL", "THE QUICK BROWN FOX", "I LOVE PIZZA",
         "HELLO WORLD", "BLAH BLAH", "ASDASD", "KJHKJH", "LALALA", "PRUEBA 123", "CARGO X", "NOMBRE APELLIDO"]
CONTROL = ["CONTADOR GENERAL", "PRODUCT DESIGNER UX/UI", "AI DEVELOPER", "HEAD OF AI", "CX SPECIALIST",
           "ADIESTRADOR CANINO", "SOMMELIER", "PILOTO DE DRON", "CIENTIFICO DE DATOS", "CELADOR", "SALVAVIDAS",
           "SIFONERO", "SELLER", "FUNCIONARIO 1"]

INSTRUCCION = """Generas datos de prueba para un sistema de nominas de Ecuador. El campo 'cargo' deberia tener un
titulo de puesto de trabajo, pero a veces la gente escribe cualquier otra cosa. Te dan una categoria: escribe 60
ejemplos DISTINTOS de esa categoria, como alguien los teclearia por error en el campo 'cargo': en MAYUSCULAS, sin
tildes, de 1 a 5 palabras, en espanol (salvo que la categoria diga ingles). NUNCA escribas un puesto de trabajo, una
ocupacion, un oficio ni una profesion. Responde solo con el JSON pedido."""
ESQUEMA = {"type": "object", "properties": {"ejemplos": {"type": "array", "items": {"type": "string", "maxLength": 60},
                                                         "minItems": 30, "maxItems": 60}}, "required": ["ejemplos"]}


def norm(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", t).strip()


def qwen():
    os.environ.setdefault("VLLM_USE_DEEP_GEMM", "0")
    os.environ.setdefault("VLLM_ALLREDUCE_USE_FLASHINFER", "0")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
    os.environ["PATH"] = str(pathlib.Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    from vllm import LLM, SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    llm = LLM(model=str(RAIZ / "modelos" / "qwen35-122b-a10b-fp8"), tensor_parallel_size=2, max_model_len=4096,
              gpu_memory_utilization=0.85, seed=20261010,
              compilation_config={"pass_config": {"fuse_allreduce_rms": False}}, gdn_prefill_backend="triton")
    msgs, cats = [], []
    for semilla in range(3):
        for c in CATEGORIAS:
            msgs.append([{"role": "system", "content": INSTRUCCION},
                         {"role": "user", "content": "Categoria: {} (variante {})".format(c, semilla + 1)}])
            cats.append(c)
    sps = [SamplingParams(temperature=1.0, top_p=0.95, max_tokens=1200, seed=20261010 + i,
                          structured_outputs=StructuredOutputsParams(json=ESQUEMA)) for i in range(len(msgs))]
    sal = llm.chat(msgs, sps, chat_template_kwargs={"enable_thinking": False})
    filas = []
    for c, s in zip(cats, sal):
        try:
            filas += [(c, norm(x)) for x in json.loads(s.outputs[0].text)["ejemplos"]]
        except ValueError:
            pass
    rng = np.random.default_rng(20261010)
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for _ in range(600):              # sin sentido por programa: teclazos, numeros, letras repetidas, mezclas
        k = rng.integers(4)
        if k == 0:
            x = "".join(rng.choice(list(letras), rng.integers(3, 12)))
        elif k == 1:
            x = "".join(rng.choice(list("0123456789"), rng.integers(1, 8)))
        elif k == 2:
            x = rng.choice(list(letras)) * int(rng.integers(3, 7))
        else:
            x = " ".join("".join(rng.choice(list(letras), rng.integers(2, 7))) for _ in range(rng.integers(2, 4)))
        filas.append(("sin sentido (programa)", x))
    d = pd.DataFrame(filas, columns=["categoria", "texto"]).drop_duplicates("texto")
    d.to_parquet(SAL / "82_negativos.parquet", index=False)
    print("{} negativos ({} categorias)".format(len(d), d["categoria"].nunique()))


def embeber():
    from benchmarking.config.settings import cargar_settings
    from benchmarking.evaluacion import embeddings
    d = pd.read_parquet(SAL / "82_negativos.parquet")
    b = np.load(RAIZ / "demo" / "base_v27.npz", allow_pickle=True)
    base = set(str(c) for c in b["celdas"])
    fuera = base | set(TERCERA)
    d = d[~d["texto"].isin(fuera) & (d["texto"].str.len() > 0)].reset_index(drop=True)
    s = cargar_settings()
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    X = np.asarray(embeddings.embeber(list(d["texto"]), cli, s.vertex_embedding_model), dtype=np.float32)
    np.savez_compressed(SAL / "82_emb_negativos.npz", textos=np.array(d["texto"], dtype=object),
                        categorias=np.array(d["categoria"], dtype=object), X=X)
    print("{} negativos embebidos (quitados los que estan en la base o en la tercera lista)".format(len(d)))


def _train_titles():
    import importlib.util
    from benchmarking.evaluacion import splits
    spec = importlib.util.spec_from_file_location("e54", AQUI / "54_pinball.py")
    e54 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e54)
    mk = e54.cargar("e41", "41_base_v16.py").cargar_marco()
    train, _ = splits.partir(mk, splits.empresas_test(mk))
    rng = np.random.default_rng(e54.SEM)
    emp0 = np.array(sorted(train["empresa_ruc"].unique()))
    val = set(rng.choice(emp0, len(emp0) // 4, replace=False))
    return set(train.loc[~train["empresa_ruc"].isin(val), "cargo_norm"].astype(str))


def entrenar():
    from sklearn.linear_model import LogisticRegression
    b = np.load(RAIZ / "demo" / "base_v27.npz", allow_pickle=True)
    Z = {str(c): z for c, z in zip(b["celdas"], b["Z"])}
    tr = _train_titles()
    P = np.vstack([Z[t] for t in tr if t in Z]).astype(float)
    e = np.load(SAL / "82_emb_negativos.npz", allow_pickle=True)
    N = e["X"].astype(float)
    rng = np.random.default_rng(75)
    idx = rng.permutation(len(N))
    n_tr = int(0.8 * len(N))
    Ntr, Nte = N[idx[:n_tr]], N[idx[n_tr:]]
    X = np.vstack([P, Ntr])
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    y = np.r_[np.zeros(len(P)), np.ones(len(Ntr))]
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X, y)
    W, c0 = clf.coef_[0], clf.intercept_[0]

    def p_no(M):
        M = np.asarray(M, float)
        M = M / np.linalg.norm(M, axis=1, keepdims=True)
        return 1 / (1 + np.exp(-(M @ W + c0)))
    d = pd.read_parquet(SAL / "54_tam_A_50_clusters_confiable_cargos_venv.parquet")
    an = d[d["base"] == "por analogia"]
    pr = p_no(np.vstack([Z[t] for t in an["cargo"]]))
    u = float(np.quantile(pr, 0.98))                  # rechaza <= 2 % de los votos reales por analogia
    pte = p_no(Nte)
    np.savez(SAL / "82_clasificador.npz", W=W, b=c0, u=u)
    out = ["82 · CLASIFICADOR ES-CARGO (D-075)",
           "positivos (titulos de entrenamiento) {:,}; negativos {:,} (entrenar {:,}, apartar {:,})".format(
               len(P), len(N), len(Ntr), len(Nte)),
           "umbral u = {:.4f} (percentil 98 de P(no cargo) en votos reales por analogia)".format(u),
           "votos reales por analogia rechazados: {:.2%}; de todos los votos: {:.2%}".format(
               (pr >= u).mean(), (pr >= u).sum() / len(d)),
           "negativos apartados (20 %) rechazados: {:.1%}".format((pte >= u).mean()),
           "reales rechazados (ejemplos): {}".format(list(an["cargo"][pr >= u].unique()[:25]))]
    (SAL / "82_es_cargo.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


def confirmar():
    from benchmarking.config.settings import cargar_settings
    from benchmarking.evaluacion import embeddings
    c = np.load(SAL / "82_clasificador.npz")
    s = cargar_settings()
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    out = ["", "CONFIRMACION (una sola vez), umbral u = {:.4f}".format(float(c["u"]))]
    res = {}
    for nom, lista in (("TERCERA LISTA (confirmacion)", TERCERA), ("lista vieja (vista)", VIEJA),
                       ("lista nueva de D-073 (vista)", NUEVA), ("controles reales", CONTROL)):
        M = np.asarray(embeddings.embeber([norm(t) for t in lista], cli, s.vertex_embedding_model), float)
        M /= np.linalg.norm(M, axis=1, keepdims=True)
        p = 1 / (1 + np.exp(-(M @ c["W"] + float(c["b"]))))
        rech = p >= float(c["u"])
        res[nom] = rech.mean()
        out.append("{}: rechazados {} de {} ({:.0%})".format(nom, int(rech.sum()), len(lista), rech.mean()))
        out += ["   {:<26} P(no cargo) {:.3f} {}".format(t, x, "RECHAZADO" if r else "") for t, x, r in zip(lista, p, rech)]
    out.append("CRITERIO (>= 80 % de la tercera lista): {}".format(
        "CUMPLE" if res["TERCERA LISTA (confirmacion)"] >= 0.8 else "NO CUMPLE"))
    with open(SAL / "82_es_cargo.txt", "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"qwen": qwen, "embeber": embeber, "entrenar": entrenar, "confirmar": confirmar}[sys.argv[1]]()
