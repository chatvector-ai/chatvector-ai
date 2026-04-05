.PHONY: help up build down reset logs db sync dev stop prod-up prod-down prod-build ci clean

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
	@echo "$(CYAN)"
	@echo "   ____ _           _   __     __          _            "
	@echo " ██████╗██╗  ██╗ █████╗ ████████╗██╗   ██╗███████╗ ██████╗████████╗ ██████╗ ██████╗        █████╗ ██╗"
	@echo "██╔════╝██║  ██║██╔══██╗╚══██╔══╝██║   ██║██╔════╝██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗      ██╔══██╗██║"
	@echo "██║     ███████║███████║   ██║   ██║   ██║█████╗  ██║        ██║   ██║   ██║██████╔╝█████╗███████║██║"
	@echo "██║     ██╔══██║██╔══██║   ██║   ╚██╗ ██╔╝██╔══╝  ██║        ██║   ██║   ██║██╔══██╗╚════╝██╔══██║██║"
	@echo "╚██████╗██║  ██║██║  ██║   ██║    ╚████╔╝ ███████╗╚██████╗   ██║   ╚██████╔╝██║  ██║      ██║  ██║██║"
	@echo " ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝     ╚═══╝  ╚══════╝ ╚═════╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝      ╚═╝  ╚═╝╚═╝"
	@echo "$(RESET)"
	@echo ""
	@echo "$(YELLOW)Available Commands$(RESET)"
	@echo "-------------------------------------"
	@echo "$(GREEN)make dev$(RESET)     ⚡ Start backend + frontend together"
	@echo "$(GREEN)make up$(RESET)      🚀 Start containers"
	@echo "$(GREEN)make build$(RESET)   🔧 Rebuild & start containers"
	@echo "$(GREEN)make down$(RESET)    🛑 Stop containers"
	@echo "$(GREEN)make reset$(RESET)   💣 Stop and remove volumes"
	@echo "$(GREEN)make logs$(RESET)    📊 Follow API logs"
	@echo "$(GREEN)make db$(RESET)      🐘 Open Postgres shell"
	@echo "$(GREEN)make sync$(RESET)    🔄 Sync with upstream main"
	@echo "$(GREEN)make prod-up$(RESET)   🚀 Start production stack (compose override)"
	@echo "$(GREEN)make prod-down$(RESET) 🛑 Stop production stack"
	@echo "$(GREEN)make prod-build$(RESET) 🔧 Rebuild & start production stack"
	@echo "$(GREEN)make ci$(RESET)      ✅ Run backend tests (CI parity)"
	@echo "$(GREEN)make clean$(RESET)   🧹 Remove containers, volumes, and orphans"
	@echo ""
	@echo "Using: $(CYAN)$(DOCKER_COMPOSE)$(RESET)"
	@echo ""
	@echo "These are wrappers around docker compose commands."
	@echo "Direct docker compose usage still works."
	@echo ""

# ==========================================
# Dev (Backend + Frontend together)
# ==========================================
dev:
	@echo "$(GREEN)⚡ Starting backend (detached) + frontend...$(RESET)"
	@$(DOCKER_COMPOSE) up -d
	@cd frontend-demo && npm run dev
stop:
	@echo "$(YELLOW)🛑 Stopping frontend dev server...$(RESET)"
	@pkill -f "npm run dev" || true
	@$(DOCKER_COMPOSE) down
	@echo "$(YELLOW)🛑 All services stopped$(RESET)"

# ==========================================
# Docker Commands
# ==========================================
up:
	$(DOCKER_COMPOSE) up -d
	@echo "$(GREEN)🚀 ChatVector services started$(RESET)"

build:
	$(DOCKER_COMPOSE) up --build -d
	@echo "$(GREEN)🔧 Containers rebuilt & started$(RESET)"

down:
	$(DOCKER_COMPOSE) down
	@echo "$(YELLOW)🛑 Services stopped$(RESET)"

reset:
	$(DOCKER_COMPOSE) down -v
	@echo "$(YELLOW)💣 Containers and volumes removed$(RESET)"

prod-up:
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml up -d
	@echo "$(GREEN)🚀 ChatVector production stack started$(RESET)"

prod-down:
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml down
	@echo "$(YELLOW)🛑 Production stack stopped$(RESET)"

prod-build:
	$(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml up --build -d
	@echo "$(GREEN)🔧 Production containers rebuilt & started$(RESET)"

ci:
	cd backend && pytest tests/ -v --tb=short
	@echo "$(GREEN)✅ CI tests complete$(RESET)"

clean:
	$(DOCKER_COMPOSE) down -v --remove-orphans
	@echo "$(YELLOW)🧹 Containers, volumes, and orphans removed$(RESET)"

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
	git push --force-with-lease
	@echo "$(GREEN)🔄 Synced with upstream/main$(RESET)"