# Makefile — Motor de Fletes GPA v2.4 (AWS SAM)
# ─────────────────────────────────────────────────────────────────
# Flujo ÚNICO de infraestructura: AWS SAM (template.yaml + samconfig.toml).
# SAM empaqueta el código y el layer (layer/requirements.txt) automáticamente.
#
# Uso:
#   make build
#   make deploy ENV=dev               # dev | staging | prod
#   make deploy-guided ENV=prod       # primera vez en un ambiente nuevo
#   make update ENV=prod              # build + deploy rápido
#   make logs ENV=prod
#   make outputs ENV=prod
#   make crear-usuario ENV=prod EMAIL=usuario@gpa.com.mx
#   make test
#
# Requisitos: AWS SAM CLI, AWS CLI configurado, Python 3.12, Docker (para
# 'sam build' con contenedor y 'sam local invoke').
# ─────────────────────────────────────────────────────────────────

ENV    ?= dev
REGION ?= us-east-1
EMAIL  ?=
STACK   = gpa-fletes-$(ENV)
FN      = MotorFletesFn

.PHONY: build deploy deploy-guided update logs outputs test test-handler crear-usuario clean destroy

# ── Build — SAM empaqueta código + layer ─────────────────────────
build:
	sam build

# ── Deploy por ambiente (usa samconfig.toml) ─────────────────────
deploy: build
	sam deploy --config-env $(ENV)

# ── Deploy interactivo (primera vez en un ambiente nuevo) ────────
deploy-guided: build
	sam deploy --guided --config-env $(ENV)

# ── Actualizar (build + deploy sin confirmar changeset) ──────────
update: build
	sam deploy --config-env $(ENV) --no-confirm-changeset

# ── Logs en tiempo real ──────────────────────────────────────────
logs:
	sam logs --stack-name $(STACK) --name $(FN) --tail --region $(REGION)

# ── Outputs del stack (URLs, ARNs, IDs) ──────────────────────────
outputs:
	aws cloudformation describe-stacks \
	  --stack-name $(STACK) --region $(REGION) \
	  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' --output table

# ── Tests unitarios (pytest) ─────────────────────────────────────
test:
	python -m pytest tests/ -v --tb=short

# ── Invocación local de la Lambda (requiere Docker) ──────────────
test-handler: build
	sam local invoke $(FN) \
	  --event tests/events/evaluar_ok.json \
	  --env-vars tests/env.json

# ── Crear usuario en Cognito (lee el UserPoolId de los outputs) ──
crear-usuario:
	@test -n "$(EMAIL)" || { echo "Uso: make crear-usuario ENV=$(ENV) EMAIL=usuario@gpa.com.mx"; exit 1; }
	POOL_ID=$$(aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text); \
	aws cognito-idp admin-create-user \
	  --user-pool-id $$POOL_ID \
	  --username "$(EMAIL)" \
	  --user-attributes Name=email,Value="$(EMAIL)" Name=email_verified,Value=true \
	  --region $(REGION)

# ── Destruir el stack ────────────────────────────────────────────
destroy:
	sam delete --stack-name $(STACK) --region $(REGION)

# ── Limpiar artefactos locales ───────────────────────────────────
clean:
	rm -rf .aws-sam/ dist/ .pytest_cache/
