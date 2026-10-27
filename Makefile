.PHONY: secrets up down logs dev test lint

# Crée .env avec des secrets aléatoires (n'écrase jamais un .env existant).
secrets:
	@test ! -f .env || (echo ".env existe déjà : rien modifié." && exit 1)
	@cp .env.example .env
	@sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$(openssl rand -hex 24)|" .env
	@sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$$(openssl rand -hex 32)|" .env
	@sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$(openssl rand -hex 32)|" .env
	@sed -i "s|^WEBHOOK_TOKEN=.*|WEBHOOK_TOKEN=$$(openssl rand -hex 24)|" .env
	@echo "✔ .env créé. Ouvrez-le pour renseigner DOMAIN, BASE_URL, ADMIN_EMAIL et ADMIN_PASSWORD."

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

test:
	cd backend && python -m pytest -q

lint:
	cd backend && ruff check . && ruff format --check .
	cd frontend && npm run typecheck
