.PHONY: install web serve dev test test-llm lint typecheck check demo clean-data

install:
	uv sync --all-extras
	cd web && npm install --no-audit --no-fund

web:
	cd web && npm run build

serve:
	uv run pitwall serve

# hot-reload dashboard against a running `make serve`
dev:
	cd web && npm run dev

test:
	uv run pytest -q

test-llm:
	uv run pytest -m llm -q -s

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

typecheck:
	uv run mypy
	cd web && npm run check

check: lint typecheck test

# generate a synthetic session and replay it into the database (no game needed). The capture goes to and is
# replayed from the data folder pitwall itself resolves (PITWALL_DATA_DIR from the environment or .env, else data/).
demo:
	@capture="$$(uv run python -c 'from pitwall.config import get_settings; print(get_settings().capture_dir / "synthetic-coaching-demo-2025.pwcap")')" && \
	uv run pitwall simulate --out "$$capture" && \
	uv run pitwall replay "$$capture" && \
	uv run pitwall report

# ---- React + HeroUI (Pro) dashboard (web-react/), served at / (and /next/ as an alias). Pro needs HEROUI_AUTH_TOKEN.
.PHONY: web-react web-react-dev web-react-check web-react-test

web-react:
	cd web-react && npm ci --no-audit --no-fund && npm run build:root

# hot-reload React dashboard on http://127.0.0.1:5174/next/ against a running `make serve` (proxies /api and /ws)
web-react-dev:
	cd web-react && ([ -d node_modules ] || npm ci --no-audit --no-fund) && npm run dev

# tsc (strict) + vitest unit tests (router, auth token, live store, driver store)
web-react-check:
	cd web-react && ([ -d node_modules ] || npm ci --no-audit --no-fund) && npm run check

web-react-test:
	cd web-react && ([ -d node_modules ] || npm ci --no-audit --no-fund) && npm test
