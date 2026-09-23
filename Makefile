# Makefile — GPA Alta de Clientes (AWS SAM)
# ─────────────────────────────────────────────────────────────────
# Uso desde AWS CloudShell:
#   make build
#   make deploy-guided ENV=dev    # primera vez (pregunta y guarda respuestas)
#   make deploy ENV=dev           # siguientes despliegues
#   make outputs ENV=dev          # URLs e IDs para configurar Amplify
#   make admin ENV=dev CORREO=... # crear el primer Administrador
#   make pruebas                  # reglas de negocio (no necesita AWS)
#   make logs ENV=dev
#   make destroy ENV=dev
#
# Requisitos: AWS SAM CLI y AWS CLI (ya vienen en CloudShell), Python 3.12.
# En Windows (PowerShell): $env:PYTHONUTF8=1
# ─────────────────────────────────────────────────────────────────

ENV      ?= dev
REGION   ?= us-east-1
STACK     = gpa-alta-clientes-$(ENV)
CORREO   ?= administracion@gpa.com.mx
NOMBRE   ?= Administrador GPA
PASSWORD ?= GpaAlta2026

.PHONY: build deploy deploy-guided outputs admin amplify-vars pruebas logs destroy

build:
	sam build

deploy: build
	sam deploy --config-env $(ENV) --no-confirm-changeset

deploy-guided: build
	sam deploy --guided --config-env $(ENV)

outputs:
	@aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[].{Dato:OutputKey,Valor:OutputValue}" --output table

# Crea la primera cuenta de Administrador. Las demás se dan de alta desde el panel.
admin:
	@POOL=$$(aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text); \
	echo "User Pool: $$POOL"; \
	aws cognito-idp admin-create-user --user-pool-id $$POOL --username $(CORREO) \
	  --user-attributes Name=email,Value=$(CORREO) Name=email_verified,Value=true \
	    Name=custom:nombre,Value="$(NOMBRE)" Name=custom:n1,Value=1 Name=custom:n2,Value=1 \
	  --temporary-password '$(PASSWORD)' --message-action SUPPRESS --region $(REGION) >/dev/null; \
	aws cognito-idp admin-add-user-to-group --user-pool-id $$POOL --username $(CORREO) \
	  --group-name admin --region $(REGION); \
	echo ""; \
	echo "Cuenta creada."; \
	echo "  Correo:              $(CORREO)"; \
	echo "  Contraseña temporal: $(PASSWORD)"; \
	echo "  Al entrar la primera vez, el sistema le pedirá elegir su propia contraseña."

amplify-vars:
	@echo "Pegue esto en Amplify → App settings → Environment variables:"
	@aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text | sed 's/^/API_URL    = /'
	@aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text | sed 's/^/POOL_ID    = /'
	@aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text | sed 's/^/CLIENT_ID  = /'
	@echo "APP_ENV    = $(ENV)"

pruebas:
	PYTHONUTF8=1 python tests/prueba_reglas.py
	PYTHONUTF8=1 python tests/prueba_usuarios.py
	PYTHONUTF8=1 python tests/rutas.py
	node tests/prueba_pantalla.js

logs:
	sam logs --stack-name $(STACK) --region $(REGION) --tail

destroy:
	sam delete --stack-name $(STACK) --region $(REGION)
