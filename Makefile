.PHONY: help up build down reset logs db

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
	@echo "$(GREEN)make up$(RESET)      🚀 Start containers"
	@echo "$(GREEN)make build$(RESET)   🔧 Rebuild & start containers"
	@echo "$(GREEN)make down$(RESET)    🛑 Stop containers"
	@echo "$(GREEN)make reset$(RESET)   💣 Stop and remove volumes"
	@echo "$(GREEN)make logs$(RESET)    📊 Follow API logs"
	@echo "$(GREEN)make db$(RESET)      🐘 Open Postgres shell"
	@echo ""
	@echo "Using: $(CYAN)$(DOCKER_COMPOSE)$(RESET)"
	@echo ""
	@echo "These are wrappers around docker compose commands."
	@echo "Direct docker compose usage still works."
	@echo ""

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

logs:
	$(DOCKER_COMPOSE) logs -f api

db:
	$(DOCKER_COMPOSE) exec db psql -U postgres
