const {M,React,TR,localStorage}=require("./montar.js");
const fs=require("fs");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(require("path").resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
cat.config=cat.config||{};
const session={email:"operador@gpa.com.mx",nombre:"Operador",rol:"operador"};
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const dormir=ms=>new Promise(r=>setTimeout(r,ms));
const tipos=(r,t)=>r.root.findAllByType(t);
const inputs=r=>tipos(r,"input").filter(n=>n.props.onChange&&!n.props.disabled);
const selects=r=>tipos(r,"select").filter(n=>n.props.onChange);
const bt=(r,txt)=>tipos(r,"button").find(b=>JSON.stringify(b.props.children||"").includes(txt));
const plano=r=>JSON.stringify(r.toJSON());

(async()=>{
console.log("══ MONTACARGAS — llenar, salir y volver ══\n");
const mc=cat.vehicles.filter(v=>String(v.combustible)==="Gas LP");
const pMC={tipo:"gas",cat,mc,registros:[],session,rol:"operador",sucursalesUser:null,
  refrescar:async()=>{},showToast:()=>{},onDone:()=>{}};
let r;await act(async()=>{r=TR.create(h(M.MCForm,pMC));});
const horas=inputs(r).find(n=>n.props.type==="number");
await act(async()=>{horas.props.onChange({target:{value:"1250"}});});
await act(async()=>{bt(r,"Siguiente").props.onClick();});
const resp=tipos(r,"button").filter(b=>b.props.className&&String(b.props.className).startsWith("rb"));
ok(resp.length>0,"la pantalla trae "+resp.length+" botones de respuesta O/P/N-A");
await act(async()=>{resp.slice(0,6).forEach(b=>b.props.onClick());});
await dormir(600);
const g=localStorage.getItem("gpa_mc_draft_gas_operador@gpa.com.mx");
ok(!!g,"se guardó el borrador del montacargas");
await act(async()=>{r.unmount();});
let r2;await act(async()=>{r2=TR.create(h(M.MCForm,pMC));});
ok(plano(r2).includes("Retomaste un checklist sin enviar"),"AL VOLVER aparece el aviso");
await act(async()=>{bt(r2,"Atrás").props.onClick();});
ok(inputs(r2).find(n=>n.props.type==="number").props.value==="1250","AL VOLVER siguen las horas = 1250");
const sel=JSON.parse(g).resps;
ok(Object.keys(sel).length>0,"y las "+Object.keys(sel).length+" respuestas del chequeo: "+JSON.stringify(sel));
await act(async()=>{r2.unmount();});

console.log("\n══ FORMULARIO DINÁMICO — llenar, salir, volver y ENVIAR ══\n");
const plantilla={clave:"prueba_bot",modulo:"seguridad",nombre:"Revisión de prueba",
  requiereFirma:false,requiereAutorizacion:false,periodicidad:"mensual",
  secciones:[{id:"s1",title:"Existencias",items:[
    {id:"gasas",label:"Gasas",type:"escala",opts:[{t:"Completo",sev:"ok"},{t:"Faltante",sev:"bad"}]},
    {id:"nota",label:"Nota",type:"text",opcional:true}]}]};
let enviado=false;
const pFD={plantilla,cat,rol:"operador",sucursalesUser:null,session,
  showToast:()=>{},onDone:()=>{enviado=true;}};
let f;await act(async()=>{f=TR.create(h(M.FormDinamico,pFD));});
await act(async()=>{bt(f,"Siguiente").props.onClick();});
// La escala se pinta como opciones clicables (.es-opt), no como <select>
const esOpt=r=>r.root.findAll(n=>n.props&&String(n.props.className||"").startsWith("es-opt")&&n.props.onClick);
const s1=esOpt(f);
ok(s1.length>0,"la sección trae las "+s1.length+" opciones de la escala");
await act(async()=>{s1[0].props.onClick();});
const t1=inputs(f).find(n=>n.props.type==="text"&&!n.props.disabled);
if(t1)await act(async()=>{t1.props.onChange({target:{value:"todo en orden"}});});
await dormir(600);
const KF="gpa_frm_draft_prueba_bot_operador@gpa.com.mx";
ok(!!localStorage.getItem(KF),"se guardó el borrador del formulario");
await act(async()=>{f.unmount();});
let f2;await act(async()=>{f2=TR.create(h(M.FormDinamico,pFD));});
ok(plano(f2).includes("Retomaste un formulario sin enviar"),"AL VOLVER aparece el aviso");
const guardadoF=JSON.parse(localStorage.getItem(KF)||"{}");
ok(guardadoF.ans&&guardadoF.ans.gasas===0,"AL VOLVER regresa la escala marcada (gasas="+JSON.stringify(guardadoF.ans&&guardadoF.ans.gasas)+")");
ok(plano(f2).includes("sel-ok")||plano(f2).includes("todo en orden"),"y se ve marcada en pantalla");

console.log("\n── Al ENVIAR, el borrador debe desaparecer ──");
// Avanzar hasta el último paso (el botón Enviar solo existe ahí)
for(let i=0;i<5&&!bt(f2,"Enviar");i++){const sg=bt(f2,"Siguiente");if(!sg)break;await act(async()=>{sg.props.onClick();});}
const btEnviar=bt(f2,"Enviar");
ok(!!btEnviar,"se llegó al último paso con el botón Enviar");
await act(async()=>{btEnviar.props.onClick();});
await dormir(400);
ok(enviado===true,"el formulario se envió (onDone)");
ok(localStorage.getItem(KF)===null,"el borrador quedó BORRADO tras enviar");
let f3;await act(async()=>{f3=TR.create(h(M.FormDinamico,pFD));});
ok(!plano(f3).includes("Retomaste"),"y al entrar de nuevo arranca en blanco");

console.log("\n── La vista previa de Admin NO debe dejar borrador ──");
let f4;await act(async()=>{f4=TR.create(h(M.FormDinamico,{...pFD,sinBorrador:true,
  session:{email:"preview",nombre:"Vista previa",sucursal:cat.sucursales[0]}}));});
await act(async()=>{bt(f4,"Siguiente").props.onClick();});
const sp=f4.root.findAll(n=>n.props&&String(n.props.className||"").startsWith("es-opt")&&n.props.onClick);
if(sp.length)await act(async()=>{sp[0].props.onClick();});
await dormir(600);
const llaves=[];for(const k of ["gpa_frm_draft_prueba_bot_preview"])if(localStorage.getItem(k))llaves.push(k);
ok(llaves.length===0,"la vista previa no escribió ningún borrador");
console.log("\n══ fin ══");
})();
