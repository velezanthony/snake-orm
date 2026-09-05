# SnakeORM — development tasks.
# Meant to be run INSIDE the devcontainer (uv manages the environment).
# `make` or `make help` lists the targets.

UV := uv run
SRC := src

# DB config. The root `.env` is the SINGLE source for the port — the same file `docker-compose.yml`
# publishes from and `shared/config.py` reads. It used to be a `5432` written here, and it went stale
# the day the .env moved to 5434: `make db-ready` answered "no response" against a database that was
# up. The `-include` comes FIRST so the `?=` below are a fallback for when there is no .env at all.
-include .env
DB_HOST ?= localhost
DB_PORT ?= 5432
DB_USER ?= postgres
DB_PASSWORD ?= snakeorm_pass
DB_NAME ?= snakeorm_db

# Demo seeding: framework and scale VALIDATED against their allow-lists.
VALID_FRAMEWORKS := flask django fastapi
VALID_SCALES := minimal normal large massive
FW ?= flask
SCALE ?= normal

.DEFAULT_GOAL := help
.PHONY: help sync lock lint format format-check typecheck typecheck-frameworks react-deps typecheck-react lint-react typecheck-strict pyright pyright-frameworks docs-build test test-v coverage coverage-html audit fix db-ready db-shell clean django-dev flask-dev fastapi-dev frameworks-test frameworks-test-shared frameworks-test-fastapi frameworks-test-flask frameworks-test-django seed examples benchmarks benchmarks-smoke react-dev

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-23s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Dependencies
# With EVERYTHING: the extras (`async`, `mysql`) and every group (`dev`, `docs`, `test-frameworks`).
# A bare `uv sync` leaves out mkdocs and the demo dependencies, so `make audit` and
# `make frameworks-test` failed for want of a package and it looked like a fault in the repo. The
# environment the everyday command installs has to be the one the gates need.
sync: ## Sync the dependencies: every extra and every group
	uv sync --all-extras --all-groups

lock: ## Regenerate uv.lock
	uv lock

##@ Quality
# `.` and not `$(SRC)`, in all three: CI checks the WHOLE repo, and `audit` claims to be what CI
# does. Pinned to `src/`, three unformatted demo files sat green locally with CI already red.
lint: ## Lint with ruff (check only)
	$(UV) ruff check .

format: ## Format the code with ruff
	$(UV) ruff format .

format-check: ## Check the formatting without writing (for CI)
	$(UV) ruff format --check .

# `.` and not `$(SRC)`: the scope is decided by pyproject's `[tool.mypy] exclude`, which already
# leaves the three frameworks/ apps out and keeps `frameworks/shared/` IN, which is real domain. With
# `$(SRC)` the gate stopped at the package boundary and did not see the 74 violations that lived
# there — 33 of them in the ORM's own contract.
typecheck: ## Type-check with mypy (the package)
	$(UV) mypy .

# The demos' shared layer CANNOT be checked from the root: `from shared.models import ...` does not
# resolve there and `ignore_missing_imports` turns it into `Any`, so mypy counted the whole layer and
# checked nothing. From `frameworks/` it does resolve. The long reason is in pyproject.toml's
# `[tool.mypy]`.
typecheck-frameworks: ## Type-check the demos' shared domain (from where `shared` resolves)
	cd frameworks && $(UV) mypy shared

# The FOURTH demo's gates. A linter nobody runs is not a gate: this one found 37 problems the day it
# was wired, two of them `eslint-disable`s aimed at a tool that was not installed.
#
# `npm ci` and not `install`: it lays down EXACTLY the lockfile. And it is its OWN target because it
# DELETES `node_modules` first — with it inline in both gates, `make -j` ran two at once in the same
# directory and each wiped the other's install. A race, so it passed several parallel runs before
# failing one. As a prerequisite make runs it once, serially, and both gates read the same tree.
react-deps: ## Install the React client's lockfile (prerequisite of the two gates below)
	cd frameworks/react_front && npm ci --silent

typecheck-react: react-deps ## Type-check the React client (the fourth demo)
	cd frameworks/react_front && npm run typecheck

lint-react: react-deps ## Lint the React client (ESLint with type-aware rules)
	cd frameworks/react_front && npm run lint

# The three gates that were missing. `audit` claimed to be "what would happen in CI" and left out
# precisely the ones that break most: somebody saw it green and the pipeline knocked it down. An
# incomplete gate that advertises itself as complete is worse than no gate, because it also
# manufactures confidence.
typecheck-strict: ## Strict type-check over the package (the "ZERO Any" gate)
	$(UV) mypy --strict src/snakeorm

# Over the PACKAGE, not over the repo: a bare `pyright` gives 260 errors and always will, because it
# analyses `src/test/typing/cases_negative.py` —whose errors are DELIBERATE, which is why
# `[tool.pyright]` documents that it is not excluded—. The `frameworks/` demos are NO longer left
# out: they have a command of their own right below.
pyright: ## Type-check with pyright over the package (what Pylance sees by default)
	$(UV) pyright src/snakeorm

# THE GATE FOR THE THREE APPS. Until it opened, 297 files were checked by nobody —`mypy` excludes
# `^frameworks/`, `typecheck-frameworks` sees `shared/` only, `pyright` was pinned to the package—
# and inside lived 40 `# type: ignore` suppressing nothing, because nothing was looking.
#
# Pyright and not mypy for resolution, not taste: `frameworks/django/` SHADOWS the real Django in
# `mypy_path`, and mypy cannot say "this root resolves like this". `executionEnvironments` can.
# One command for the three paths, or CI runs two and forgets the third.
pyright-frameworks: ## Type-check with pyright of the THREE demo apps
	$(UV) pyright frameworks/django frameworks/flask frameworks/fastapi

docs-build: ## Build the documentation treating any warning as an error
	$(UV) mkdocs build --strict

# THE ORDER IS THE DECISION, so do not tidy it alphabetically. `examples` and `benchmarks-smoke` sit
# just before `test` because both DEMAND Postgres and take seconds, while `test` takes two minutes
# and without Postgres skips in green: a missing engine fails at second three instead of after two
# minutes of manufactured confidence. `frameworks-test` goes last, being slowest — and it is in the
# gate at all because the demos are the only place the ORM runs with a server in front of it.
#
# A bare `benchmarks` is deliberately absent: measurement, not verification. The why is at the target.
audit: lint format-check typecheck typecheck-frameworks typecheck-react lint-react typecheck-strict pyright pyright-frameworks docs-build examples benchmarks-smoke test frameworks-test ## Full read-only gate (what would happen in CI)

fix: ## Auto-fix: ruff --fix + format
	$(UV) ruff check --fix $(SRC)
	$(UV) ruff format $(SRC)

##@ Tests
test: ## Run the tests
	$(UV) pytest -q

test-v: ## Run the tests in verbose mode
	$(UV) pytest -v

# The gates go here too, because in a coverage report a SKIPPED test and an untested line are
# indistinguishable: engines down, the run still exits 0 and hands back a LOW number that looks like
# a measurement.
#
# BOTH suites, for the same reason. `frameworks/shared/tests/` drives the async layer and is a
# separate pytest run because `shared` only resolves from `frameworks/`. Measuring one called
# `asyncsession.py` 65% where both say 87%, about to send somebody to test what was already tested.
#
# `|| true` because this MEASURES; whether the suite passes is `make test`.
coverage-run: ## (internal) Run both suites and leave one combined data file
	@rm -f .coverage .coverage.*
	@SNAKEORM_REQUIRE_POSTGRES=$(SNAKEORM_REQUIRE_POSTGRES) \
	 SNAKEORM_REQUIRE_MYSQL=$(SNAKEORM_REQUIRE_MYSQL) \
	 COVERAGE_FILE=$(CURDIR)/.coverage.orm \
	 $(UV) pytest --cov=snakeorm --cov-branch --cov-report= -q >/dev/null 2>&1 || true
	@cd frameworks && SNAKEORM_REQUIRE_POSTGRES=$(SNAKEORM_REQUIRE_POSTGRES) \
	 COVERAGE_FILE=$(CURDIR)/.coverage.demos \
	 $(UV) pytest shared/tests --cov=snakeorm --cov-branch --cov-report= -q >/dev/null 2>&1 || true
	@$(UV) coverage combine >/dev/null 2>&1

coverage: coverage-run ## Coverage of BOTH suites, with the lines that never ran
	@$(UV) coverage report --show-missing

coverage-html: coverage-run ## The same, as HTML (htmlcov/)
	@$(UV) coverage html
	@echo "htmlcov/index.html"

# One line per subpackage instead of one per file. `term-missing` answers "which lines did not run",
# which is the question you ask once you know WHERE to look; this answers where. It runs the suite
# itself rather than reading whatever `.coverage` was left behind, because a stale data file reports
# the state of a tree that no longer exists and says nothing about being stale.
coverage-domains: coverage-run ## Coverage rolled up per domain, one line per subpackage
	@printf '%-16s %8s %8s %8s %8s %7s\n' domain stmts miss branch bmiss cover
	@for dir in src/snakeorm/*/; do \
		case "$$dir" in *__pycache__*) continue;; esac; \
		$(UV) coverage report --include="$$dir*" 2>/dev/null | tail -1 \
		| sed "s|^TOTAL|$$(basename $$dir)|" \
		| awk '{printf "%-16s %8s %8s %8s %8s %7s\n", $$1, $$2, $$3, $$4, $$5, $$6}'; \
	done
	@$(UV) coverage report 2>/dev/null | tail -1 \
	| awk '{printf "%-16s %8s %8s %8s %8s %7s\n", "TOTAL", $$2, $$3, $$4, $$5, $$6}'

HISTORY := docs/contributors/coverage-history
SCRIPT := $(HISTORY)/assets/script/history.py
PORT ?= 8020
# Stamped to the second: two runs in one afternoon is the normal case —you measure, you sharpen a
# test, you measure again— and a name carrying only the date eats the first without saying so.
STAMP := $(shell date +%FT%H%M%S)

coverage-snapshot: coverage-run ## Record a coverage snapshot and rebuild what reads it
	@raw=$$(mktemp); \
	 $(UV) coverage json -o $$raw --pretty-print >/dev/null 2>&1; \
	 $(UV) python $(SCRIPT) snapshot $$raw $(STAMP) orm,demos; \
	 rm -f $$raw
	@$(UV) python $(SCRIPT) render
	@$(MAKE) --no-print-directory coverage-css
	@echo "written $(HISTORY)/assets/data/$(STAMP).json"

coverage-chart: ## Rebuild the manifest without measuring again
	@$(UV) python $(SCRIPT) render

# The stylesheet is COPIED next to the pages rather than linked across the repository. An absolute
# `/frameworks/...` only resolves when the server root is the repository, which breaks the moment
# this is served under mkdocs or opened from the folder itself. A relative link works everywhere,
# and the copy is the price.
coverage-css: ## Copy the built stylesheet next to the viewer
	@mkdir -p $(HISTORY)/assets/css
	@cp frameworks/shared/static/app.css $(HISTORY)/assets/css/app.css

# Served because the page FETCHES its snapshots, and a browser refuses that over `file://` — every
# such URL is its own origin. The folder is enough of a root now that the stylesheet lives inside it.
coverage-serve: ## Serve the viewer so it can fetch its snapshots
	@echo "http://127.0.0.1:$(PORT)/coverage/"
	@cd $(HISTORY) && $(UV) python -m http.server $(PORT) --bind 127.0.0.1

##@ Examples and benchmarks
# TWO commands that check different things, and either alone leaves a hole. `python -m examples.tour`
# is LITERALLY what the docs tell the reader to type, so it verifies the `__main__`, the module path
# and the package; the test imports `main` and never goes through any of that. `pytest` then asserts
# the output's VALUES. Running it catches that the example BLOWS UP; the test catches that it LIES,
# which is the expensive failure in executable documentation.
#
# The variable only reaches the second line, and deliberately: `python -m` has no `skip` to convert,
# so it dies with `OperationalError` and exit 1 whatever the switch says. `SNAKEORM_REQUIRE_POSTGRES=false`
# does not manufacture a green without an engine — it turns off the skip-into-failure conversion,
# nothing else.
examples: ## Run the published examples (the tour + its assertions). REQUIRES Postgres
	$(UV) python -m examples.tour
	SNAKEORM_REQUIRE_POSTGRES=$(SNAKEORM_REQUIRE_POSTGRES) $(UV) pytest src/test/examples -q

# `benchmarks` stays OUT of `audit`, and it is a matter of category, not of clock. A benchmark is a
# MEASUREMENT: a gate that swallows one either asserts nothing about the timings, or asserts a
# threshold and turns flaky — and a flaky gate ends up ignored, taking with it what it did protect.
#
# What IS verifiable is that it STILL RUNS: compiles, creates the schema, seeds, measures, cleans up,
# returns 0. That half goes into `audit`, at `SMALL_CONFIG` sizes and without asserting a single ms.
benchmarks: ## Measure performance against Postgres, full sizes. MEASUREMENT, outside the gate
	$(UV) python -m benchmarks.run

# The other half. `src/test/benchmarks/test_smoke.py` already checks the seven sections and that the
# include emits 2 queries and not N+1, with `SMALL_CONFIG`; all it lacked was somebody running it
# DEMANDING the engine, for the same reason as above: it skips itself without a server.
benchmarks-smoke: ## Check that the benchmark harness STILL runs (minimal sizes). REQUIRES Postgres
	SNAKEORM_REQUIRE_POSTGRES=$(SNAKEORM_REQUIRE_POSTGRES) $(UV) pytest src/test/benchmarks -q

##@ Database
db-ready: ## Check that PostgreSQL answers
	pg_isready -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER)

db-shell: ## Open a psql shell against the database
	PGPASSWORD=$(DB_PASSWORD) psql -h $(DB_HOST) -p $(DB_PORT) -U $(DB_USER) -d $(DB_NAME)

##@ Frameworks (demo apps in frameworks/)
# They need the `test-frameworks` dependency group: uv sync --group test-frameworks
#
# Variables so one override clears a collision. They are ALSO in the React client's
# `config/backends.ts`, and `test_the_ports_agree.py` is what keeps the two honest: they had already
# drifted —FastAPI started on 8000, the client proxied to 8001— and nothing said so.
DJANGO_PORT ?= 8080
FASTAPI_PORT ?= 8001
django-dev: ## Start the Django demo (SSR + API) on http://127.0.0.1:8080 (SCALE=... for the volume)
	cd frameworks/django && DEMO_SCALE=$(SCALE) $(UV) python manage.py runserver $(DJANGO_PORT)

flask-dev: ## Start the Flask demo (SSR + API) on http://127.0.0.1:5000 (SCALE=... for the volume)
	cd frameworks/flask && DEMO_SCALE=$(SCALE) $(UV) flask --app app run --debug

fastapi-dev: ## Start the FastAPI demo (API only) on http://127.0.0.1:8001 (SCALE=... for the volume)
	cd frameworks/fastapi && DEMO_SCALE=$(SCALE) $(UV) uvicorn main:app --reload --port $(FASTAPI_PORT)

# Serves nothing by itself: its dev server PROXIES to the three backends, so at least one of the
# three targets above has to be running. The three hold DIFFERENT ports, so they can all be up at
# once — which is what makes the client's backend switcher usable: it changes backend without
# anything being restarted. They used to share 8000 and it was one at a time.
#
# Nobody assumes 8000. It is uvicorn's default and Django's, and it is also the first port any
# other project on the machine takes — which is how this moved: it was already held.
react-dev: ## Start the React client (the fourth demo) on http://127.0.0.1:5173. NEEDS a backend up
	cd frameworks/react_front && npm ci --silent && npm run dev

# ONE switch for the whole "an engine is needed here" policy: it governs `frameworks-test-shared`,
# `examples` and `benchmarks-smoke`.
#
# Only `-shared` of the four demo targets carries it, and that is measured rather than wholesale.
# Its two-connection tests —row locking, savepoints, isolation— arm a strict hook only when this is
# set; without it a wrong port makes the suite pass in full and grows only the skipped counter. The
# other three have no such hook and never call `pytest.skip`: their database missing is an error, so
# handing them the variable would switch nothing on and leave it WRITTEN that there is a net.
#
# `?=` so a machine with no docker can turn it off by hand, and so CI's `env:` wins. The default is
# to DEMAND: a gate that gives up when the server is missing is not a gate.
SNAKEORM_REQUIRE_POSTGRES ?= true

# The second gate. It existed in `src/test/conftest.py` since the engine catalogue became three and
# was nowhere in this file, so `make coverage` measured with MySQL skipped and nobody could tell.
# The comment above says a second variable is one more thing that gets forgotten — this one already
# had been, on the side nobody was watching. Two engines, two switches, both written down.
SNAKEORM_REQUIRE_MYSQL ?= true

# One suite per target, and the aggregate composes them. Split that way for a concrete reason: CI
# runs them IN PARALLEL (one matrix leg per suite) and needs to invoke them one at a time. With the
# four commands stuffed inside a single target, the workflow would have to copy them — and a copy
# goes out of sync at the first change, leaving CI and the programmer's machine checking different
# things, which is the worst possible state.
frameworks-test-shared: ## Tests of the shared layer (the three apps' domain)
	cd frameworks && SNAKEORM_REQUIRE_POSTGRES=$(SNAKEORM_REQUIRE_POSTGRES) $(UV) pytest shared/tests -q

frameworks-test-fastapi: ## Tests of the FastAPI demo
	cd frameworks/fastapi && $(UV) pytest -q

frameworks-test-flask: ## Tests of the Flask demo
	# No `verify.py` as an argument: pinned to ONE FILE, a test file added beside it exists and
	# never runs — the same defect the Django target below names, in its worse form. The discovery
	# lives in `frameworks/flask/pytest.ini`, which also keeps `verify.py` in the pattern.
	cd frameworks/flask && $(UV) pytest -q

frameworks-test-django: ## Tests of the Django demo
	# `apps` and not `apps.blog`: pinned to one app, a suite added to any other one exists and
	# never runs, which is the most expensive kind of test there is.
	cd frameworks/django && $(UV) python manage.py test apps

# `shared/` goes FIRST: it is the domain the three share (models, selectors, services, usecases). If
# something breaks there, it breaks in all three, and seeing that before the three derived failures
# saves diagnosing three symptoms of a single cause. Serially, because locally it is read top to
# bottom; the parallelism is CI's job, which is where the clock matters.
frameworks-test: frameworks-test-shared frameworks-test-fastapi frameworks-test-flask frameworks-test-django  ## Runs the three demo apps and the shared layer

seed: ## Seed one demo at one scale. Usage: make seed FW=flask SCALE=massive
	@case " $(VALID_FRAMEWORKS) " in \
	  *" $(FW) "*) ;; \
	  *) echo "❌ Invalid FW: '$(FW)'. Valid: $(VALID_FRAMEWORKS)"; exit 1 ;; \
	esac
	@case " $(VALID_SCALES) " in \
	  *" $(SCALE) "*) ;; \
	  *) echo "❌ Invalid SCALE: '$(SCALE)'. Valid: $(VALID_SCALES)"; exit 1 ;; \
	esac
	cd frameworks && $(UV) python -m shared.cli $(FW) $(SCALE)

##@ Cleanup
clean: ## Remove tool caches and bytecode
	rm -rf .mypy_cache .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
