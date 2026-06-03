# Makefile — GPA Operaciones (AWS SAM)
# ─────────────────────────────────────────────────────────────────
# Uso:
#   make build
#   make deploy-guided ENV=dev      # primera vez (pide confirmaciones)
#   make deploy ENV=dev             # siguientes despliegues
#   make outputs ENV=dev            # ver URLs/IDs del stack
#   make seed ENV=dev               # cargar catálogos + cuentas
#   make deploy-web ENV=dev         # subir el frontend a S3 + invalidar CDN
#   make logs ENV=dev
#   make destroy ENV=dev
#
# Requisitos: AWS SAM CLI, AWS CLI configurado, Python 3.12.
# En Windows (PowerShell): export PYTHONUTF8=1  ->  $env:PYTHONUTF8=1
# ─────────────────────────────────────────────────────────────────

ENV    ?= dev
REGION ?= us-east-1
STACK   = gpa-operaciones-$(ENV)
PASSWORD ?= Gpa2026!

.PHONY: build deploy deploy-guided update outputs seed seed-operadores deploy-web logs destroy

build:
	sam build

deploy: build
	sam deploy --config-env $(ENV) --no-confirm-changeset

deploy-guided: build
	sam deploy --guided --config-env $(ENV)

update: build
	sam deploy --config-env $(ENV) --no-confirm-changeset

# Outputs del stack (URLs, IDs de Cognito, buckets)
outputs:
	aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' --output table

# Carga catálogos a DynamoDB y crea las cuentas especiales de cuentas.json
seed:
	$(eval TABLE := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue" --output text))
	$(eval POOL  := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text))
	python seed/seed.py --tabla $(TABLE) --pool-id $(POOL) --region $(REGION) --password "$(PASSWORD)"

# Igual que seed pero además crea un login operador por cada responsable
seed-operadores:
	$(eval TABLE := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue" --output text))
	$(eval POOL  := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text))
	python seed/seed.py --tabla $(TABLE) --pool-id $(POOL) --region $(REGION) --password "$(PASSWORD)" --operadores

# Genera frontend/config.js con los datos del stack, sube el frontend y purga la CDN
deploy-web:
	$(eval WEB   := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='WebBucketName'].OutputValue" --output text))
	$(eval API   := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text))
	$(eval POOL  := $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text))
	$(eval CLIENT:= $(shell aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text))
	$(eval DIST  := $(shell aws cloudfront list-distributions --query "DistributionList.Items[?Comment=='GPA Operaciones PWA ($(ENV))'].Id" --output text))
	@echo "window.GPA_CONFIG={apiUrl:'$(API)',region:'$(REGION)',poolId:'$(POOL)',clientId:'$(CLIENT)',env:'$(ENV)'};" > frontend/config.js
	aws s3 sync frontend/ s3://$(WEB)/ --delete --region $(REGION)
	@[ -n "$(DIST)" ] && aws cloudfront create-invalidation --distribution-id $(DIST) --paths "/*" || echo "(sin distribución que invalidar)"

logs:
	sam logs --stack-name $(STACK) --name OperacionesFn --tail --region $(REGION)

destroy:
	sam delete --stack-name $(STACK) --region $(REGION)
