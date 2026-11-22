# Thin wrappers around docker compose; README lists the plain commands.
COMPOSE ?= docker compose

.PHONY: up down ps logs smoke

up:
	$(COMPOSE) up --build --wait

# Never removes volumes.
down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs --follow --tail=200

# One explicit request per mapped model through the gateway; billable for a hosted provider.
smoke:
	$(COMPOSE) exec -T api python -m jobs.smoke_llm
