.PHONY: test lint serve docker
test:
	pytest -q
lint:
	python -m compileall -q harness
serve:
	python -m harness serve
docker:
	docker build -t coding-harness .