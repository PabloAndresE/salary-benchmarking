import argparse
import sys
from google.cloud import bigquery
from .config.settings import cargar_settings
from .orquestador import construir_base, construir_universo
from .adquisicion.plantilla_client import descargar_plantilla
from .escritura.bigquery_sink import escribir, tabla_existe, procesos_existentes


def _con_cache(s):
    """`descargar_plantilla` con el caché de GCS enganchado, si hay bucket configurado.

    Sin bucket la corrida funciona igual; lo único que se pierde es que cada reproceso
    vuelve a golpear la API (~10 h para los estudios con plantilla).
    """
    if not s.gcs_bucket_plantillas:
        print("[cache] sin bucket configurado: las plantillas no se cachean")
        return descargar_plantilla
    from functools import partial
    from .adquisicion.cache_plantillas import CacheGCS
    print(f"[cache] plantillas en gs://{s.gcs_bucket_plantillas}/plantillas")
    return partial(descargar_plantilla, cache=CacheGCS(s.gcs_bucket_plantillas))


def main():
    ap = argparse.ArgumentParser(prog="benchmarking")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cb = sub.add_parser("construir-base")
    cb.add_argument("--muestra", type=int, default=None, help="limitar a N estudios (desarrollo)")
    cb.add_argument("--dry-run", action="store_true", help="no escribir a BigQuery")
    cb.add_argument("--concurrencia", type=int, default=None,
                    help="descargas de plantilla en paralelo (default: settings.descargas_concurrentes)")

    cu = sub.add_parser("construir-universo")
    cu.add_argument("--batch-size", type=int, default=500, help="estudios por lote")
    cu.add_argument("--concurrencia", type=int, default=None, help="descargas en paralelo por lote")
    cu.add_argument("--reset", action="store_true", help="borrar y recrear la tabla destino")
    cu.add_argument("--anios", default=None,
                    help="acotar a estos anios, p.ej. 2024,2025 (default: todos)")

    rf = sub.add_parser("referenciar", help="nomina de un cliente -> Excel con referencias")
    rf.add_argument("--nomina", required=True, help="Excel o CSV del cliente")
    rf.add_argument("--salida", default="referencias.xlsx")
    rf.add_argument("--columna", default=None, help="columna de cargo (se autodetecta)")
    rf.add_argument("--columna-sueldo", default=None, help="columna de sueldo (se autodetecta)")
    rf.add_argument("--anio", type=int, default=2025, help="anio del SBU para los dolares")
    rf.add_argument("--segmento", default=None,
                    choices=["MICROEMPRESA", "PEQUENA", "MEDIANA", "GRANDE"],
                    help="tamano de la empresa del cliente. Corrige el sesgo de los "
                         "cargos altos: sin el, a una empresa pequena se le dice que su "
                         "gerente general cobra un 56%% por debajo del mercado")
    rf.add_argument("--rubro", default=None,
                    help="CIIU de primer nivel del cliente (una letra, p.ej. C para "
                         "manufactura). Donde el cargo tenga respaldo en ese rubro, la "
                         "referencia y las bandas salen SOLO de ese sector; donde no, "
                         "ese cargo cae al mercado entero. NO mejora la precision "
                         "—esta medido que no— y estrecha el respaldo: es una lente de "
                         "comparabilidad, y el coste se ve en la columna de confianza")
    rf.add_argument("--cache-embeddings", default=None)
    rf.add_argument("--base", default="base_referencia.npz", help="base serializada")
    rf.add_argument("--rehacer-base", action="store_true")

    args = ap.parse_args()
    s = cargar_settings()
    client = bigquery.Client()
    descargar = _con_cache(s)

    if args.cmd == "construir-base":
        df = construir_base(client, s.actuafast_base_url, s, limite=args.muestra,
                            descargar=descargar, max_workers=args.concurrencia)
        print(f"nomina_features: {len(df)} filas")
        if not args.dry_run and len(df):
            tid = escribir(df, client, s.bq_project, s.bq_dataset)
            print(f"escrito en {tid}")

    elif args.cmd == "construir-universo":
        table_id = f"{s.bq_project}.{s.bq_dataset}.nomina_features"
        if args.reset and tabla_existe(client, table_id):
            client.delete_table(table_id)
        hechos = procesos_existentes(client, table_id)
        estado = {"creada": tabla_existe(client, table_id)}
        def escribir_lote(df):
            disp = "WRITE_APPEND" if estado["creada"] else "WRITE_TRUNCATE"
            escribir(df, client, s.bq_project, s.bq_dataset, write_disposition=disp)
            estado["creada"] = True
        total = construir_universo(client, s.actuafast_base_url, s,
                                   escribir_lote=escribir_lote, batch_size=args.batch_size,
                                   max_workers=args.concurrencia, descargar=descargar,
                                   hechos=hechos,
                                   anios=(tuple(int(a) for a in args.anios.split(","))
                                          if args.anios else None))
        print(f"universo: {total} filas escritas (reanudó saltando {len(hechos)} estudios)")

    elif args.cmd == "referenciar":
        from .producto.referenciar_nomina import referenciar_archivo
        referenciar_archivo(args.nomina, args.salida, client, s,
                            col_cargo=args.columna, col_sueldo=args.columna_sueldo,
                            anio=args.anio, segmento=args.segmento, rubro=args.rubro,
                            cache_emb=args.cache_embeddings, ruta_base=args.base,
                            rehacer=args.rehacer_base)


if __name__ == "__main__":
    main()
