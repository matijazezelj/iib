.PHONY: up down restart logs build clean

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

clean:
	docker compose down -v
	docker rmi iib-manager 2>/dev/null || true
