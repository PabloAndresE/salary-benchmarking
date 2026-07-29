import argparse
from google.cloud import bigquery
from .config.settings import cargar_settings
from .orquestador import construir_base
from .escritura.bigquery_sink import escribir

def main():
    ap = argparse.ArgumentParser(prog="benchmarking")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cb = sub.add_parser("construir-base")
    cb.add_argument("--muestra", type=int, default=None, help="limitar a N estudios (desarrollo)")
    cb.add_argument("--dry-run", action="store_true", help="no escribir a BigQuery")
    args = ap.parse_args()
    s = cargar_settings()
    client = bigquery.Client()
    df = construir_base(client, s.actuafast_base_url, s, limite=args.muestra)
    print(f"nomina_features: {len(df)} filas")
    if not args.dry_run and len(df):
        tid = escribir(df, client, s.bq_project, s.bq_dataset)
        print(f"escrito en {tid}")

if __name__ == "__main__":
    main()
