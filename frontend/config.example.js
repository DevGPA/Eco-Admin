// config.example.js — plantilla de configuración del frontend.
// Amplify genera el config.js real en cada despliegue (ver amplify.yml).
// Para probar en local: copie este archivo a config.js y llene los datos
// con los Outputs del stack de SAM (make outputs).
window.GPA_CONFIG = {
  apiUrl:    "https://XXXXXXXX.execute-api.us-east-1.amazonaws.com/dev",
  region:    "us-east-1",
  poolId:    "us-east-1_XXXXXXXXX",
  clientId:  "XXXXXXXXXXXXXXXXXXXXXXXXXX",
  portalUrl: "",   // vacío = la liga se arma con la dirección del navegador
  env:       "dev",
};
