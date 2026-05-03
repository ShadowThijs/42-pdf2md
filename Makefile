.PHONY: install run lint clean build

install:
	pip install -e .

run:
	python -m src.cli

lint:
	flake8 src/
	mypy src/ --ignore-missing-imports --check-untyped-defs

clean:
	rm -rf build/ dist/ *.egg-info __pycache__ .mypy_cache
	find . -name '__pycache__' -type d -exec rm -rf {} +

build:
	pip install --upgrade build
	python -m build
