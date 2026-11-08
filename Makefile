.PHONY: setup demo ingest geo app mcp test

setup:
	uv sync --extra dev

demo:
	uv run python scripts/run_ingest.py --mode demo

ingest:
	uv run python scripts/run_ingest.py --mode live --dataset all

geo:
	uv run python scripts/run_geo.py

app:
	uv run streamlit run src/property_hunt/app.py

mcp:
	uv run python -m property_hunt.mcp_server

test:
	uv run pytest -q
