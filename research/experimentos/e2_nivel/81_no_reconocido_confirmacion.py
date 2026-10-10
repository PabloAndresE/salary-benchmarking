"""D-073: confirmacion (una sola vez) del filtro de «no reconocido» con la lista NUEVA de basura, fijada en el
registro antes de disenar. Base v27 y configuracion de la API (juez, nivel por grupo, traductor, tipeo).

    GRPC_DNS_RESOLVER=native ../../../.venv/bin/python 81_no_reconocido_confirmacion.py

SALIDA: salidas/81_no_reconocido_confirmacion.txt
"""
import pathlib
import sys

import numpy as np

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
SAL = AQUI / "salidas"
sys.path.insert(0, str(RAIZ / "src"))
from benchmarking.config.settings import cargar_settings  # noqa: E402
from benchmarking.evaluacion import embeddings  # noqa: E402
from benchmarking.producto import idioma  # noqa: E402
from benchmarking.producto.base_referencia import BaseReferencia  # noqa: E402
from benchmarking.producto.juez import cargar as cargar_juez  # noqa: E402

NUEVA = ["QWERASDF", "JJJJJ", "ABC123", "0000", "PALABRA", "COSA", "NADA QUE VER", "HOLA COMO ESTAS", "BUENOS DIAS",
         "SIN CARGO", "NO APLICA", "XXX YYY", "ELEFANTE", "CABALLO", "TORTUGA", "MANZANA", "HAMBURGUESA",
         "CAFE CON LECHE", "SOFA", "VENTANA", "LAPIZ", "MONTANA", "PLAYA", "LUNA", "ESTRELLA FUGAZ", "ZOMBIE",
         "HADA MADRINA", "MAGO DE OZ", "DINOSAURIO", "NAVE ESPACIAL", "THE QUICK BROWN FOX", "I LOVE PIZZA",
         "HELLO WORLD", "BLAH BLAH", "ASDASD", "KJHKJH", "LALALA", "PRUEBA 123", "CARGO X", "NOMBRE APELLIDO"]
VIEJA = ["ASDFGH QWERTY", "XXXXX", "AAAA BBBB", "123456", "LOREM IPSUM", "TEST", "PRUEBA PRUEBA", "NINGUNO", "N/A",
         "HOLA MUNDO", "ASTRONAUTA", "DOMADOR DE LEONES", "MAGO", "UNICORNIO", "PIRATA", "VAMPIRO", "SUPERHEROE",
         "DRAGON", "ZZZZ", "QWERTYUIOP", "MESA", "SILLA", "PERRO", "GATO", "PIZZA", "FUTBOL", "BANANA", "CIELO AZUL",
         "JKLÑ", "????"]
CONTROL = ["CONTADOR GENERAL", "Product Designer UX/UI", "AI Developer", "Head of AI", "CX Specialist",
           "ADIESTRADOR CANINO", "SOMMELIER", "PILOTO DE DRON", "CIENTIFICO DE DATOS", "contdor generl"]


def main():
    s = cargar_settings()
    b = BaseReferencia.cargar(RAIZ / "demo" / "base_v27.npz", s.get_sbu)
    b.juez = cargar_juez(RAIZ / "modelos" / "juez_v3")
    b.juez_vecinos = True
    b.nivel_por_grupo()
    b.candado_nivel = True
    b.traductor = idioma.cargar(RAIZ / "modelos" / "opus-mt-en-es")
    b.idioma_sueldo, b.candado_glosario, b.tipeo, b.confianza_ancho, b.filtro_cargo = True, True, True, True, True
    cli = embeddings.cliente_vertex(s.vertex_embedding_model, s.bq_project, s.vertex_location)
    todos = [t.upper() for t in NUEVA + VIEJA + CONTROL]
    emb = {c: b.Z[i] for i, c in enumerate(b.celdas)}
    nuevos = [t for t in todos if t not in emb]
    nuevos += [x for x in b.traducciones_a_embeber(todos) if x not in emb]
    emb.update(dict(zip(nuevos, embeddings.embeber(nuevos, cli, s.vertex_embedding_model))))
    r = b.referenciar(todos, emb).set_index("cargo")
    out = ["81 · CONFIRMACION DE D-073 (una sola vez)"]
    for nom, lista in (("LISTA NUEVA (confirmacion)", NUEVA), ("lista vieja (diseno)", VIEJA), ("controles reales", CONTROL)):
        rech = [t for t in lista if r.loc[t.upper(), "base"] == "no reconocido"]
        out.append("{}: rechazados {} de {} ({:.0%})".format(nom, len(rech), len(lista), len(rech) / len(lista)))
        for t in lista:
            x = r.loc[t.upper()]
            out.append("   {:<24} {:<16} similitud {:.3f}".format(t, x["base"], x["similitud"]))
    n = [t for t in NUEVA if r.loc[t.upper(), "base"] == "no reconocido"]
    out.append("CRITERIO (>= 80 % de la lista nueva): {}".format("CUMPLE" if len(n) / len(NUEVA) >= 0.8 else "NO CUMPLE"))
    (SAL / "81_no_reconocido_confirmacion.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
