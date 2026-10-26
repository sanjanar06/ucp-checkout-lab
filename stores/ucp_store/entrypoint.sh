#!/bin/sh
# Lab addition: start the store under the supervisor, which seeds the
# databases into /data (mounted from ../lab-data) and can reset them between
# trials. Set RESET=1 to re-seed from the catalog CSVs.
set -e
: "${STORE_NAME:?set STORE_NAME}" "${SIMULATION_SECRET:?set SIMULATION_SECRET}"
exec /venv/bin/python supervisor.py
