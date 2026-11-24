PYTHON ?= python
NPM ?= npm
DOMAIN_BRANCH ?= 90
GRAPH_BRANCH ?= 80
PYTEST_DIRS := $(wildcard apps/api/tests/unit apps/api/tests/graph apps/api/tests/integration apps/api/tests/golden)

.PHONY: install test backend frontend typecheck browser e2e golden coverage sync-contracts check-contracts

install:
	$(PYTHON) -m pip install -e "./apps/api[test]"
	$(NPM) --prefix apps/web ci

test: browser backend frontend typecheck e2e

backend:
	$(PYTHON) -m pytest -W error $(PYTEST_DIRS)

golden:
	$(PYTHON) -m pytest -W error apps/api/tests/golden

frontend:
	$(NPM) --prefix apps/web run test

typecheck:
	$(NPM) --prefix apps/web run typecheck

browser:
	$(PYTHON) scripts/check_branch_coverage.py --prepare-browsers

e2e:
	$(PYTHON) scripts/check_branch_coverage.py --e2e

coverage: browser
	$(PYTHON) -m coverage run --branch --source=apps/api/src/bookgen -m pytest -W error $(PYTEST_DIRS)
	$(PYTHON) -m coverage json -o coverage.json
	$(PYTHON) scripts/check_branch_coverage.py --report coverage.json --domain $(DOMAIN_BRANCH) --graph $(GRAPH_BRANCH)
	$(NPM) --prefix apps/web run test:coverage

sync-contracts:
	bash scripts/sync_contracts.sh

check-contracts:
	bash scripts/sync_contracts.sh --check
