CXX ?= c++
CXXFLAGS := -std=c++20 -pthread -Wall -Wextra -Wpedantic -Iengine/include
ENGINE_SOURCES := engine/src/order_book.cpp engine/src/matching_engine.cpp engine/src/protocol.cpp

.PHONY: build test test-cpp test-python test-process integration-test run demo stop reset demo-reset benchmark lint clean
build:
	docker compose build

build/engine-tests: $(ENGINE_SOURCES) engine/tests/test_engine.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $^ -o $@

build/apex-simulator: simulator/src/main.cpp
	mkdir -p build
	$(CXX) -std=c++20 -pthread -Wall -Wextra -Wpedantic $< -o $@

test-cpp: build/engine-tests
	./build/engine-tests

test-process: build/apex-simulator
	sh simulator/tests/test_process.sh ./build/apex-simulator

test-python:
	PYTHONPATH=. .venv/bin/pytest -m 'not integration'

test: test-cpp test-process test-python
	cd frontend && npm run build

integration-test:
	DATABASE_URL=postgresql://apex:apex_local_only@localhost:55432/apex PYTHONPATH=. .venv/bin/pytest -m integration

run:
	docker compose up -d --build

demo:
	docker compose --profile simulation up -d --build

stop:
	docker compose down

reset:
	docker compose down -v

demo-reset:
	@echo "DESTRUCTIVE: removing the local APEX Compose database volume and all demo data"
	docker compose --profile simulation down -v --remove-orphans

benchmark:
	.venv/bin/python benchmarks/load_test.py

lint:
	$(CXX) $(CXXFLAGS) -fsyntax-only $(ENGINE_SOURCES) engine/src/main.cpp
	.venv/bin/python -m compileall -q api risk benchmarks tests database
	cd frontend && npm run lint

clean:
	rm -rf build frontend/dist benchmark-results .pytest_cache
