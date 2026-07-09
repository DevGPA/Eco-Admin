// config.example.js — plantilla de configuración del frontend.
// El archivo real `config.js` lo genera AWS Amplify durante el build
// (ver amplify.yml) a partir de variables de entorno. Para probar en local,
// copia este archivo a config.js y rellena los datos de los Outputs de SAM.
window.GPA_CONFIG = {
  apiUrl:   "https://XXXXXXXX.execute-api.us-east-1.amazonaws.com/dev",
  region:   "us-east-1",
  poolId:   "us-east-1_XXXXXXXXX",
  clientId: "XXXXXXXXXXXXXXXXXXXXXXXXXX",
  env:      "dev",
};
