#!/bin/sh
# Seed the store's databases on first start (or when RESET=1), then serve.
# Databases live in /data (mounted from ../lab-data), never in the image or repo.
set -e
DB_DIR="/data/stores/${STORE_NAME:?set STORE_NAME}"
mkdir -p "$DB_DIR"

if [ "$RESET" = "1" ] || [ ! -f "$DB_DIR/products.db" ]; then
  rm -f "$DB_DIR"/*.db*
  echo "Seeding $STORE_NAME from /seed/$STORE_NAME"
  uv run --no-sync import_csv.py \
    --products_db_path="$DB_DIR/products.db" \
    --transactions_db_path="$DB_DIR/transactions.db" \
    --data_dir="/seed/$STORE_NAME"
fi

exec uv run --no-sync server.py \
  --products_db_path="$DB_DIR/products.db" \
  --transactions_db_path="$DB_DIR/transactions.db" \
  --port=8182 \
  --simulation_secret="${SIMULATION_SECRET:?set SIMULATION_SECRET}"
