# Roll-rate predictor (PS-03)

Roll-rate forecasting with agentic root-cause investigation.

Data (parquet, ~600 MB) is not stored in git. Place files under `data/{public,hidden,reference}/` and run:

    python -m venv .venv && .venv/bin/pip install duckdb pandas pyarrow
    .venv/bin/python src/load_duckdb.py

See `docs/DATA_DICTIONARY.md` and `docs/schema.png`. `src/generate_dataset.py` regenerates the data.
