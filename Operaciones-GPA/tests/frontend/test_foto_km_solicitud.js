// Candado de la foto del kilometraje en la SOLICITUD de combustible (SolForm),
// montando el componente real de frontend/index.html.
const {M,React,TR,localStorage,llamadas}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
cat.config=cat.config||{};
const session={email:"operador@gpa.com.mx",nombre:"Operador",rol:"operador"};
const props={cat,items:[],session,rol:"operador",sucursalesUser:null,
  refrescar:async()=>{},showToast:()=>{},onDone:()=>{}};
const DK="gpa_sol_draft_operador@gpa.com.mx";
const FOTO_KM="data:image/jpeg;base64,ODOMETRO";
const FOTO_TANQUE="data:image/jpeg;base64,TANQUE";
const FIRMA="data:image/png;base64,FIRMA";
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const dormir=ms=>new Promise(r=>setTimeout(r,ms));
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const inputs=r=>r.root.findAllByType("input").filter(n=>n.props.onChange&&!n.props.disabled);

(async()=>{
console.log("══ SOLICITUD DE COMBUSTIBLE — foto del kilometraje ══\n");
localStorage.removeItem(DK);
let r;await act(async()=>{r=TR.create(h(M.SolForm,props));});

console.log("── Con vehículo y km capturados, pero SIN foto ──");
const km=inputs(r).find(n=>n.props.type==="number");
await act(async()=>{km.props.onChange({target:{value:"91127"}});});
const sig1=bt(r,"Siguiente");
ok(sig1.props.disabled===true,"«Siguiente» queda BLOQUEADO sin la foto del odómetro");
ok(JSON.stringify(r.toJSON()).includes("Sin la foto del odómetro no se puede continuar"),
   "y se explica por qué en pantalla");
ok(JSON.stringify(r.toJSON()).includes("Foto del kilometraje"),"existe el campo «Foto del kilometraje»");
await act(async()=>{r.unmount();});

console.log("\n── Con la foto del km sí deja avanzar ──");
// La foto se siembra por el mismo camino que usa la app al retomar un borrador.
localStorage.setItem(DK,JSON.stringify({veh:"16",km:"91127",tank:0.25,obs:"",fotoKm:FOTO_KM,fotos:[],sig:null,step:1}));
let r2;await act(async()=>{r2=TR.create(h(M.SolForm,props));});
ok(bt(r2,"Siguiente").props.disabled!==true,"«Siguiente» se DESBLOQUEA con la foto");
await act(async()=>{bt(r2,"Siguiente").props.onClick();});
ok(JSON.stringify(r2.toJSON()).includes("Fotos de Evidencia"),"pasa al paso de evidencia");
ok(bt(r2,"Siguiente").props.disabled!==true,"las fotos extra (tanque) NO son obligatorias");
await act(async()=>{r2.unmount();});

console.log("\n── Lo que se envía: la foto del km va primero y es la principal ──");
llamadas.length=0;
localStorage.setItem(DK,JSON.stringify({veh:"16",km:"91127",tank:0.25,obs:"carga de ruta",
  fotoKm:FOTO_KM,fotos:[FOTO_TANQUE],sig:FIRMA,step:3}));
let r3;await act(async()=>{r3=TR.create(h(M.SolForm,props));});
const enviar=bt(r3,"Enviar");
ok(!!enviar,"se llegó al paso de envío");
await act(async()=>{enviar.props.onClick();});
await dormir(300);
const env=llamadas.find(l=>l.metodo==="crear");
ok(!!env,"se envió la solicitud");
ok(env.datos.photo===FOTO_KM,"la foto PRINCIPAL es la del kilometraje");
ok(env.datos.fotos[0]===FOTO_KM,"y encabeza la lista de evidencia");
ok(env.datos.fotos[1]===FOTO_TANQUE,"la del tanque queda después");
ok(env.datos.fotos.length===2,"no se duplica: van 2 fotos, no 3");
ok(localStorage.getItem(DK)===null,"el borrador se borró al enviar");

console.log("\n── Borrador VIEJO (antes de este cambio) se migra solo ──");
localStorage.setItem(DK,JSON.stringify({veh:"16",km:"88888",tank:0.5,obs:"",
  fotos:[FOTO_KM,FOTO_TANQUE],sig:null,step:1}));
let r4;await act(async()=>{r4=TR.create(h(M.SolForm,props));});
ok(bt(r4,"Siguiente").props.disabled!==true,"su primera foto pasa a ser la del km y no lo traba");
await act(async()=>{bt(r4,"Siguiente").props.onClick();});
const txt=JSON.stringify(r4.toJSON());
ok(txt.includes("TANQUE"),"y la segunda queda como evidencia extra");
ok((txt.match(/ODOMETRO/g)||[]).length<=1,"sin duplicar la del odómetro en la lista");

console.log("\n== REPORTE DE CARGA - sigue exigiendo la foto de km y medidor ==\n");
await act(async()=>{r4.unmount();});
const DR="gpa_rep_draft_operador@gpa.com.mx";
localStorage.setItem(DR,JSON.stringify({veh:"16",km:"91200",step:1}));
let p1;await act(async()=>{p1=TR.create(h(M.RepForm,props));});
ok(bt(p1,"Siguiente").props.disabled===true,"sin foto ANTES: Siguiente bloqueado");
await act(async()=>{p1.unmount();});
localStorage.setItem(DR,JSON.stringify({veh:"16",km:"91200",fotoAntes:FOTO_KM,step:1}));
let p2;await act(async()=>{p2=TR.create(h(M.RepForm,props));});
ok(bt(p2,"Siguiente").props.disabled===true,"con la de ANTES pero sin la de FINALIZAR: sigue bloqueado");
await act(async()=>{p2.unmount();});
localStorage.setItem(DR,JSON.stringify({veh:"16",km:"91200",fotoAntes:FOTO_KM,fotoDespues:FOTO_TANQUE,step:1}));
let p3;await act(async()=>{p3=TR.create(h(M.RepForm,props));});
ok(bt(p3,"Siguiente").props.disabled!==true,"con ambas fotos si avanza");
localStorage.removeItem(DR);
console.log("\n══ fin ══");
})();
