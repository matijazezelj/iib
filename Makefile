.PHONY: up down restart logs build clean generate-secrets sync-now

up: generate-secrets
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

generate-secrets:
	@if [ ! -f .env ]; then \
		echo "Creating .env from .env.example..."; \
		cp .env.example .env; \
	fi
	@if grep -qE "^[A-Z_]+=GENERATE_ME$$" .env; then \
		echo "Generating secrets..."; \
		tmp=$$(mktemp); \
		sed -e "s|AUTHENTIK_SECRET_KEY=GENERATE_ME|AUTHENTIK_SECRET_KEY=$$(openssl rand -base64 50 | tr -d '\n')|" \
		    -e "s|AUTHENTIK_BOOTSTRAP_TOKEN=GENERATE_ME|AUTHENTIK_BOOTSTRAP_TOKEN=$$(openssl rand -hex 32)|" \
		    -e "s|POSTGRES_PASSWORD=GENERATE_ME|POSTGRES_PASSWORD=$$(openssl rand -hex 24)|" \
		    .env > "$$tmp" && cat "$$tmp" > .env; \
		rm -f "$$tmp"; \
		if grep -qE "^[A-Z_]+=GENERATE_ME$$" .env; then \
			echo "ERROR: secret generation failed, .env still has GENERATE_ME" >&2; \
			exit 1; \
		fi; \
		echo "Secrets generated."; \
	fi

sync-now:
	docker exec iib-monitor python /app/monitor.py --once

clean:
	docker compose down -v
	docker rmi iib-monitor 2>/dev/null || true
