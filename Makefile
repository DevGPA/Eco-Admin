# Makefile — Deploy Motor de Fletes GPA v2.4
# ─────────────────────────────────────────────────────────────────
# Uso:
#   make package ENV=dev
#   make deploy  ENV=prod EMAIL=oscar@gpa.com.mx
#   make logs    ENV=dev
#   make test
# ─────────────────────────────────────────────────────────────────

ENV    ?= dev
REGION ?= us-east-1
EMAIL  ?=
ACCOUNT = $(shell aws sts get-caller-identity --query Account --output text)
DEPLOY_BUCKET = gpa-deploy-$(ENV)-$(ACCOUNT)
STACK  = gpa-fletes-$(ENV)
FN     = gpa-motor-fletes-$(ENV)
DIST   = dist

.PHONY: all package layer deploy update-fn logs test clean

all: package deploy

# ── Crear bucket de deploy si no existe ──────────────────────────
bucket:
	aws s3 mb s3://$(DEPLOY_BUCKET) --region $(REGION) 2>/dev/null || true
	aws s3api put-bucket-versioning \
	  --bucket $(DEPLOY_BUCKET) \
	  --versioning-configuration Status=Enabled

# ── Empaquetar código Lambda ──────────────────────────────────────
package: bucket
	@echo "📦 Empaquetando Lambda..."
	rm -rf $(DIST)/lambda
	mkdir -p $(DIST)/lambda
	# Copiar código fuente
	cp handler.py $(DIST)/lambda/
	cp -r motor/  $(DIST)/lambda/motor/
	cp -r db/     $(DIST)/lambda/db/
	cp -r s3/     $(DIST)/lambda/s3/
	# Crear __init__.py donde falte
	touch $(DIST)/lambda/db/__init__.py
	touch $(DIST)/lambda/s3/__init__.py
	# Comprimir
	cd $(DIST)/lambda && zip -r ../gpa-motor-fletes.zip . -x "*.pyc" -x "__pycache__/*"
	aws s3 cp $(DIST)/gpa-motor-fletes.zip \
	  s3://$(DEPLOY_BUCKET)/lambda/gpa-motor-fletes.zip
	@echo "✅ Lambda empaquetada → s3://$(DEPLOY_BUCKET)/lambda/gpa-motor-fletes.zip"

# ── Empaquetar Layer de dependencias ─────────────────────────────
layer: bucket
	@echo "📦 Empaquetando Layer de dependencias..."
	rm -rf $(DIST)/layer
	mkdir -p $(DIST)/layer/python
	pip install boto3 pydantic -t $(DIST)/layer/python/ -q
	cd $(DIST)/layer && zip -r ../gpa-dependencias.zip python/ -x "*.pyc"
	aws s3 cp $(DIST)/gpa-dependencias.zip \
	  s3://$(DEPLOY_BUCKET)/layers/gpa-dependencias.zip
	@echo "✅ Layer empaquetado"

# ── Deploy completo CloudFormation ───────────────────────────────
deploy: package layer
	@echo "🚀 Desplegando stack $(STACK)..."
	aws cloudformation deploy \
	  --template-file infrastructure/stack-gpa-fletes.yaml \
	  --stack-name $(STACK) \
	  --region $(REGION) \
	  --parameter-overrides \
	    Env=$(ENV) \
	    NotificacionesEmail=$(EMAIL) \
	  --capabilities CAPABILITY_NAMED_IAM \
	  --no-fail-on-empty-changeset
	@echo "✅ Stack desplegado:"
	@aws cloudformation describe-stacks \
	  --stack-name $(STACK) \
	  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
	  --output table

# ── Actualizar solo el código (sin recrear infra) ─────────────────
update-fn: package
	@echo "🔄 Actualizando código Lambda..."
	aws lambda update-function-code \
	  --function-name $(FN) \
	  --s3-bucket $(DEPLOY_BUCKET) \
	  --s3-key lambda/gpa-motor-fletes.zip \
	  --region $(REGION)
	@echo "✅ Función actualizada"

# ── Ver logs en tiempo real ───────────────────────────────────────
logs:
	aws logs tail /aws/lambda/$(FN) --follow --region $(REGION)

# ── Tests locales ─────────────────────────────────────────────────
test:
	@echo "🧪 Ejecutando tests..."
	python -m pytest tests/ -v --tb=short

test-handler:
	@echo "🧪 Test handler completo..."
	python -c "
import json, os
os.environ['DYNAMO_TABLE'] = 'gpa_fletes_dev'
os.environ['S3_BUCKET']    = 'gpa-documentos-dev'
from handler import lambda_handler
event = {
  'httpMethod': 'POST',
  'path': '/evaluar',
  'body': json.dumps({
    'folioCP':       '116873635',
    'foliosFV':      ['FA10315862'],
    'origenSucursal': 'GDL',
    'codigoSAP':     'GS0230',
    'destinoEstado': 'Sonora',
    'destinoCiudad': 'Navojoa',
    'fletaRFC':      'ACT68080665A',
    'campoEntregaFV':'ENTREGA_DOMICILIO',
    'partidas': [
      {'sku':'39111611','descripcion':'Reflector LED','cantidad':1,
       'precioUnitarioUSD':1074.53,'pesoKg':5.0}
    ],
    'fleteBaseMXN': 18500.0,
    'ferryMXN': 0.0,
    'tipoCambioRef': 17.35,
    'fechaEmision': '2026-04-22'
  })
}
resp = lambda_handler(event, {})
print('Status:', resp['statusCode'])
print('Body:',   json.dumps(json.loads(resp['body']), indent=2, ensure_ascii=False))
"

# ── Destruir stack ────────────────────────────────────────────────
destroy:
	@read -p "⚠️  ¿Destruir stack $(STACK)? [y/N] " ans; \
	if [ "$$ans" = "y" ]; then \
	  aws cloudformation delete-stack --stack-name $(STACK) --region $(REGION); \
	  echo "Stack en proceso de eliminación..."; \
	fi

# ── Limpiar artefactos locales ────────────────────────────────────
clean:
	rm -rf $(DIST)/ __pycache__/ .pytest_cache/ *.pyc
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
