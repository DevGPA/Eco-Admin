// Monta los componentes REALES de frontend/index.html (compilados con el mismo
// Babel que usa la app) y simula lo que hace el usuario.
const fs=require("fs");
const path=require("path");
// Babel: el paquete npm si está, o la copia local que se usa para validar el HTML.
const Babel=(()=>{try{return require("@babel/standalone");}catch(e){}
  for(const r of ["../../../../_babel.js","../../../_babel.js","../../_babel.js"]){
    try{return require(path.resolve(__dirname,r));}catch(e){}}
  throw new Error("Falta Babel: corre  npm install @babel/standalone  en tests/frontend");})();
const React=require("react");
const TR=require("react-test-renderer");

const HTML=path.resolve(__dirname,"../../frontend/index.html");
const src=fs.readFileSync(HTML,"utf8");
let code=src.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1];
// Quitar solo el arranque (necesita DOM real)
code=code.replace(/ReactDOM\.createRoot\(document\.getElementById\("root"\)\)\.render\(<App\/>\);/,"")
         .replace(/if\("serviceWorker" in navigator\)[^\n]*\n/,"");
const js=Babel.transform(code,{presets:["react"],filename:"app.jsx"}).code;

// ── Entorno mínimo ────────────────────────────────────────────────────────
let QUOTA=5*1024*1024;const _s=new Map();
const localStorage={
  getItem:k=>_s.has(k)?_s.get(k):null,
  setItem:(k,v)=>{const otros=[..._s].filter(([kk])=>kk!==k).reduce((n,[kk,vv])=>n+kk.length+vv.length,0);
    if(otros+k.length+v.length>QUOTA){const e=new Error("QuotaExceededError");e.name="QuotaExceededError";throw e;}
    _s.set(k,v);},
  removeItem:k=>{_s.delete(k);},
};
const noop=()=>{};
const elem=()=>({getContext:()=>({}),toDataURL:()=>"data:image/png;base64,FIRMA",style:{},
  addEventListener:noop,removeEventListener:noop,appendChild:noop,removeChild:noop,
  getBoundingClientRect:()=>({left:0,top:0,width:340,height:120}),classList:{add:noop,remove:noop}});
const documentStub={createElement:elem,getElementById:()=>elem(),body:{appendChild:noop,removeChild:noop,style:{}},
  addEventListener:noop,removeEventListener:noop,querySelector:()=>null};
const windowStub={GPA_CONFIG:{dominio:"gpa.com.mx"},addEventListener:noop,removeEventListener:noop,
  location:{origin:"https://operaciones-gpa.amplifyapp.com"},matchMedia:()=>({matches:false,addListener:noop}),
  setTimeout,clearTimeout,localStorage};
class GpaApiStub{constructor(){return new Proxy(this,{get:()=>async()=>[]});}}

const fabrica=new Function("React","ReactDOM","GpaApi","window","document","navigator","localStorage","alert","console",
  js+"\n;return {CLForm,MCForm,FormDinamico,SolForm,RepForm};");
const M=fabrica(React,{createRoot:()=>({render:noop,unmount:noop})},GpaApiStub,windowStub,documentStub,
  {serviceWorker:undefined},localStorage,noop,console);

module.exports={M,React,TR,localStorage,setQuota:q=>{QUOTA=q;},bytes:()=>[..._s].reduce((n,[k,v])=>n+k.length+v.length,0)};
