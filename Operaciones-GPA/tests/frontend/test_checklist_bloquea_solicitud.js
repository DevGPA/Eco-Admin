// Candado en pantalla: si la unidad trae el checklist de reparto VENCIDO, la
// solicitud de combustible no deja avanzar y explica por qué.
// Usa el SolForm real de frontend/index.html.
const {M,React,TR,localStorage,llamadas}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const base=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
const session={email:"operador@gpa.com.mx",nombre:"Operador",rol:"operador"};
const DK="gpa_sol_draft_operador@gpa.com.mx";
const FOTO="data:image/jpeg;base64,ODOMETRO";
const FIRMA="data:image/png;base64,FIRMA";
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const dormir=ms=>new Promise(r=>setTimeout(r,ms));
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const plano=r=>JSON.stringify(r.toJSON());

// Catálogo con la unidad #16 en el estado que se quiera probar
const catCon=chk=>{
  const c=JSON.parse(JSON.stringify(base));c.config={};
  c.vehicles=c.vehicles.map(v=>String(v.id)==="16"?{...v,ultimoKm:90000,checklist:chk}:v);
  return c;
};
const props=chk=>({cat:catCon(chk),items:[],session,rol:"operador",sucursalesUser:null,
  refrescar:async()=>{},showToast:()=>{},onDone:()=>{}});
const VENCIDO={semanal:"vencido",mensual:"cumplido",limiteSemanal:"2026-09-21",limiteMensual:"2026-09-07"};
const AL_DIA ={semanal:"cumplido",mensual:"cumplido",limiteSemanal:"2026-09-21",limiteMensual:"2026-09-07"};
const EN_PLAZO={semanal:"pendiente",mensual:"pendiente",limiteSemanal:"2026-09-28",limiteMensual:"2026-10-05"};
// Borrador con la unidad #16 ya elegida, km y foto puestos: así el único
// motivo posible de bloqueo es el checklist.
const sembrar=()=>localStorage.setItem(DK,JSON.stringify(
  {veh:"16",km:"90500",tank:0.25,obs:"",fotoKm:FOTO,fotos:[],sig:null,step:1}));

(async()=>{
console.log("══ SOLICITUD DE COMBUSTIBLE · checklist de reparto vencido ══\n");

console.log("── Con el checklist SEMANAL vencido ──");
sembrar();
let r;await act(async()=>{r=TR.create(h(M.SolForm,props(VENCIDO)));});
const txt=plano(r);
ok(txt.includes("checklist"),"se ve el aviso del checklist");
ok(txt.includes("semanal"),"dice cuál falta (semanal)");
ok(txt.includes("2026-09-21"),"dice la fecha en que vencía");
ok(txt.includes("Mtto"),"dice dónde capturarlo (Mtto → Reparto)");
ok(bt(r,"Siguiente").props.disabled===true,"«Siguiente» BLOQUEADO aunque el km y la foto estén puestos");
await act(async()=>{r.unmount();});

console.log("\n── Con el checklist AL DÍA ──");
sembrar();
let r2;await act(async()=>{r2=TR.create(h(M.SolForm,props(AL_DIA)));});
ok(!plano(r2).includes("tiene pendiente su checklist"),"no aparece el aviso");
ok(bt(r2,"Siguiente").props.disabled!==true,"«Siguiente» habilitado: puede solicitar");
await act(async()=>{r2.unmount();});

console.log("\n── Dentro del plazo (pendiente, todavía no vence) ──");
sembrar();
let r3;await act(async()=>{r3=TR.create(h(M.SolForm,props(EN_PLAZO)));});
ok(!plano(r3).includes("tiene pendiente su checklist"),"no bloquea: aún está en plazo");
ok(bt(r3,"Siguiente").props.disabled!==true,"«Siguiente» habilitado");
await act(async()=>{r3.unmount();});

console.log("\n── Unidad SIN checklist de reparto (montacargas) ──");
// Las unidades que no son de reparto llegan sin el campo: no deben bloquearse.
localStorage.setItem(DK,JSON.stringify({veh:"42",km:"5100",tank:0.25,obs:"",fotoKm:FOTO,fotos:[],sig:null,step:1}));
let r4;await act(async()=>{r4=TR.create(h(M.SolForm,{...props(undefined),cat:(()=>{const c=catCon(undefined);c.vehicles=c.vehicles.map(v=>String(v.id)==="42"?{...v,ultimoKm:5000}:v);return c;})()}));});
ok(!plano(r4).includes("tiene pendiente su checklist"),"no se bloquea una unidad sin checklist");
await act(async()=>{r4.unmount();});

console.log("\n── Ni siquiera enviando desde el último paso ──");
llamadas.length=0;
localStorage.setItem(DK,JSON.stringify(
  {veh:"16",km:"90500",tank:0.25,obs:"",fotoKm:FOTO,fotos:[],sig:FIRMA,step:3}));
let r5;await act(async()=>{r5=TR.create(h(M.SolForm,props(VENCIDO)));});
const enviar=bt(r5,"Enviar");
ok(!!enviar,"se llegó al paso de envío con un borrador viejo");
await act(async()=>{enviar.props.onClick();});
await dormir(300);
ok(!llamadas.some(l=>l.metodo==="crear"),"NO se envió nada: el candado también corta al enviar");
ok(plano(r5).includes("checklist"),"y regresa al paso 1 mostrando el motivo");
console.log("\n══ fin ══");
})();
