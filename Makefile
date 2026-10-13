setup-db:
	docker compose up -d db
	python -m alembic upgrade head
	python -m app.db.checkpoints

run-api:
	uvicorn app.main:app --reload

test:
	pytest -q
