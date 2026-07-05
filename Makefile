.PHONY: help setup dev quickstart backend frontend open stop up build down reset logs db sync prod-up prod-down prod-build ci tests cleanup clean

# Default: most convenient local development experience
.DEFAULT_GOAL := all

# ==========================================
# Auto-detect Docker Compose (v1 or v2)
# ==========================================
DOCKER_COMPOSE_BIN := $(shell command -v docker-compose 2> /dev/null)

ifeq ($(DOCKER_COMPOSE_BIN),)
	DOCKER_COMPOSE := docker compose
else
	DOCKER_COMPOSE := docker-compose
endif

# ==========================================
# Colors
# ==========================================
GREEN=\033[0;32m
CYAN=\033[0;36m
YELLOW=\033[1;33m
RESET=\033[0m

# ==========================================
# Help
# ==========================================
help:
	@echo ""
	@echo "$(CYAN)ChatVector — local development$(RESET)"
	@echo ""
	@echo "$(YELLOW)Quick start$(RESET)"
	@echo "  $(GREEN)make quickstart$(RESET)  Create env, pause for credentials, then start everything"
	@echo "  $(GREEN)make$(RESET)             Start backend + frontend, open browser tabs (default)"
	@echo "  $(GREEN)make setup$(RESET)       Create env files, install dependencies, and build Docker images"
	@echo "  $(GREEN)make dev$(RESET)         Start backend + frontend without opening tabs"
	@echo ""
	@echo "$(YELLOW)Individual services$(RESET)"
	@echo "  $(GREEN)make backend$(RESET)     Start only the backend Docker stack (attached logs)"
	@echo "  $(GREEN)make frontend$(RESET)    Start only the frontend demo (non-containerized)"
	@echo "  $(GREEN)make open$(RESET)          Open frontend and API docs in your browser"
	@echo "  $(GREEN)make stop$(RESET)          Stop this repo's frontend process and Docker services"
	@echo ""
	@echo "$(YELLOW)Docker shortcuts$(RESET)"
	@echo "  $(GREEN)make up$(RESET)            Start containers (detached)"
	@echo "  $(GREEN)make build$(RESET)         Rebuild and start containers (detached)"
	@echo "  $(GREEN)make down$(RESET)          Stop containers"
	@echo "  $(GREEN)make reset$(RESET)         Stop containers and remove volumes"
	@echo "  $(GREEN)make logs$(RESET)          Follow API logs"
	@echo "  $(GREEN)make db$(RESET)            Open Postgres shell"
	@echo "  $(GREEN)make tests$(RESET)         Run backend tests via Docker"
	@echo "  $(GREEN)make clean$(RESET)         Remove containers, volumes, and orphans"
	@echo ""
	@echo "$(YELLOW)Other$(RESET)"
	@echo "  $(GREEN)make prod-up$(RESET)       Start production stack"
	@echo "  $(GREEN)make prod-down$(RESET)     Stop production stack"
	@echo "  $(GREEN)make prod-build$(RESET)    Rebuild production stack"
	@echo "  $(GREEN)make sync$(RESET)          Sync with upstream main"
	@echo "  $(GREEN)make cleanup$(RESET)       Delete local branches except main"
	@echo ""
	@echo "Using: $(CYAN)$(DOCKER_COMPOSE)$(RESET)"
	@echo ""

# ==========================================
# Local development workflow
# ==========================================
setup:
	@./scripts/setup.sh

dev:
	@OPEN_BROWSER=0 ./scripts/dev.sh

all:
	@OPEN_BROWSER=1 ./scripts/dev.sh

quickstart:
	@QUICKSTART=1 ./scripts/setup.sh
	@OPEN_BROWSER=1 ./scripts/dev.sh

backend:
	@./scripts/backend.sh

frontend:
	@./scripts/frontend.sh

open:
	@./scripts/open-dev.sh

stop:
	@./scripts/stop.sh

# ==========================================
# Docker Commands
# ==========================================
up:
	$(DOCKER_COMPOSE) up -d
	@echo "$(GREEN)ChatVector services started$(RESET)"

build:
	$(DOCKER_COMPOSE) up --build -d
	@echo "$(GREEN)Containers rebuilt and started$(RESET)"

down:
	$(DOCKER_COMPOSE) down
	@echo "$(YELLOW)Services stopped$(RESET)"

reset:
	$(DOCKER_COMPOSE) down -v
	@echo "$(YELLOW)Containers and volumes removed$(RESET)"

prod-up:
	$(DOCKER_COMPOSE) -f docker-compose.prod.yml up -d
	@echo "$(GREEN)ChatVector production stack started$(RESET)"

prod-down:
	$(DOCKER_COMPOSE) -f docker-compose.prod.yml down
	@echo "$(YELLOW)Production stack stopped$(RESET)"

prod-build:
	$(DOCKER_COMPOSE) -f docker-compose.prod.yml up --build -d
	@echo "$(GREEN)Production containers rebuilt and started$(RESET)"

tests:
	$(DOCKER_COMPOSE) run --rm tests
	@echo "$(GREEN)Tests complete$(RESET)"

clean:
	$(DOCKER_COMPOSE) down -v --remove-orphans
	@echo "$(YELLOW)Containers, volumes, and orphans removed$(RESET)"

logs:
	$(DOCKER_COMPOSE) logs -f api

db:
	$(DOCKER_COMPOSE) exec db psql -U postgres

# ==========================================
# Git Commands
# ==========================================
sync:
	git fetch upstream
	git rebase upstream/main
	git push --force-with-lease origin HEAD
	@echo "$(GREEN)Synced with upstream/main$(RESET)"

cleanup:
	@echo "$(YELLOW)Deleting all local branches except main...$(RESET)"
	@git branch | grep -v "^* main$$" | grep -v "^  main$$" | xargs -r git branch -D
	@echo "$(GREEN)Local branches cleaned up$(RESET)"
