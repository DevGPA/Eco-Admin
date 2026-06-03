// config.example.js — plantilla de configuración del frontend.
// El archivo real `config.js` lo genera automáticamente `make deploy-web`
// con los valores del stack. Para probar en local, copia este archivo a
// config.js y rellena los datos de los Outputs de CloudFormation.
window.GPA_CONFIG = {
  apiUrl:   "https://XXXXXXXX.execute-api.us-east-1.amazonaws.com/dev",
  region:   "us-east-1",
  poolId:   "us-east-1_XXXXXXXXX",
  clientId: "XXXXXXXXXXXXXXXXXXXXXXXXXX",
  env:      "dev",
};
