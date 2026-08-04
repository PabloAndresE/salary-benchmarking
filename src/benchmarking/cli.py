import argparse
import sys
from google.cloud import bigquery
from .config.settings import cargar_settings
from .orquestador import construir_base, construir_universo
from .escritura.bigquery_sink import escribir, tabla_existe, procesos_existentes

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

    args = ap.parse_args()
    s = cargar_settings()
    client = bigquery.Client()

    if args.cmd == "construir-base":
        df = construir_base(client, s.actuafast_base_url, s,
                            limite=args.muestra, max_workers=args.concurrencia)
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
                                   max_workers=args.concurrencia, hechos=hechos)
        print(f"universo: {total} filas escritas (reanudó saltando {len(hechos)} estudios)")

if __name__ == "__main__":
    main()
