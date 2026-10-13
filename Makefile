.PHONY: install run test lint samples docker-build docker-run

install:
	pip install -r requirements-dev.txt

run:
	python wsgi.py

test:
	pytest -q

lint:
	ruff check app tests scripts

samples:
	python scripts/generate_samples.py

docker-build:
	docker build -t ttb-label-verifier .

docker-run:
	docker run --rm -p 8000:8000 ttb-label-verifier
