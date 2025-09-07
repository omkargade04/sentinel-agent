.DEFAULT_GOAL := help

help:
	@echo "Available commands:"
	@echo "  make install      Install dependencies and pre-commit hooks"
	@echo "  make run          Run the application"
	@echo "  make test         Run tests"
	@echo "  make format-code  Format code with pre-commit"

run:
	poetry run python -m src.main

test:
	poetry run python -m pytest

install:
	poetry install
	poetry run pre-commit install

format-code:
	poetry run pre-commit run --all-files