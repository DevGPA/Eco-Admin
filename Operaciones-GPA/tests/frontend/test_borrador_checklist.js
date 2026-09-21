// Prueba del flujo REAL: se monta CLForm de frontend/index.html, se llena, el
// usuario SALE del módulo (unmount) y VUELVE (mount nuevo). Debe reaparecer.
const {M,React,TR,localStorage}=require("./montar.js");
const fs=require("fs");
const act=TR.act;
const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(require("path").resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
cat.config=cat.config||{};
const session={email:"giovanni@gpa.com.mx",nombre:"Giovanni R.",rol:"operador"};
const props={tipo:"semanal",cat,items:[],session,rol:"operador",sucursalesUser:null,
  refrescar:async()=>{},showToast:()=>{},onDone:()=>{}};

const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const dormir=ms=>new Promise(r=>setTimeout(r,ms));
const buscar=(r,t)=>r.root.findAllByType(t);
const inputs=r=>buscar(r,"input").filter(n=>n.props.onChange&&!n.props.disabled);
const selects=r=>buscar(r,"select").filter(n=>n.props.onChange);
const botones=r=>buscar(r,"button");
const porTexto=(r,txt)=>botones(r).find(b=>JSON.stringify(b.props.children||"").includes(txt));
const textoPlano=r=>JSON.stringify(r.toJSON());

(async()=>{
console.log("══ CHECKLIST SEMANAL DE REPARTO — llenar, salir y volver ══\n");
let r;
await act(async()=>{r=TR.create(h(M.CLForm,props));});

console.log("── Paso 1: el operador captura los datos generales ──");
const km=inputs(r).find(n=>n.props.type==="number");
await act(async()=>{km.props.onChange({target:{value:"97710"}});});
const foto=buscar(r,"input").find(n=>n.props.type==="file");
await act(async()=>{foto.props.onChange({target:{files:[]},__fake:true});});   // no dispara (sin File real)
ok(inputs(r).find(n=>n.props.type==="number").props.value==="97710","capturó km = 97710");

console.log("\n── Avanza a la primera sección y responde ──");
await act(async()=>{porTexto(r,"Siguiente").props.onClick();});
let sels=selects(r);
ok(sels.length>0,"la sección trae "+sels.length+" pregunta(s) de selección");
const respuestas={};
await act(async()=>{sels.forEach((s,i)=>{const op=(s.props.children||[]).flat().filter(Boolean);
  const vals=op.map(o=>o&&o.props&&(o.props.value!==undefined?o.props.value:o.props.children)).filter(v=>typeof v==="string"&&v);
  const v=vals[1]||vals[0];if(v){respuestas[i]=v;s.props.onChange({target:{value:v}});}});});
const antes=selects(r).map(s=>s.props.value);
ok(antes.filter(Boolean).length>0,"quedaron respondidas "+antes.filter(Boolean).length+" pregunta(s): "+antes.slice(0,4).join(", "));

console.log("\n── Caso A: «← Atrás» dentro del checklist ──");
await act(async()=>{porTexto(r,"Atrás").props.onClick();});
ok(inputs(r).find(n=>n.props.type==="number").props.value==="97710","al volver al paso 1 sigue el km");
await act(async()=>{porTexto(r,"Siguiente").props.onClick();});
ok(JSON.stringify(selects(r).map(s=>s.props.value))===JSON.stringify(antes),"y las respuestas siguen ahí");

console.log("\n── Caso B: SALE del módulo y VUELVE (lo que reportó el usuario) ──");
await dormir(600);                                   // el borrador se guarda a los 400 ms
const guardado=localStorage.getItem("gpa_cl_draft_semanal_giovanni@gpa.com.mx");
ok(!!guardado,"se guardó el borrador ("+Math.round((guardado||"").length/1024)+" KB)");
await act(async()=>{r.unmount();});                  // ← salir del módulo desmonta el formulario
let r2;
await act(async()=>{r2=TR.create(h(M.CLForm,props));});   // ← volver a entrar
// Regresa en el MISMO paso en el que se quedó, no al principio
const despues=selects(r2).map(s=>s.props.value);
ok(JSON.stringify(despues)===JSON.stringify(antes),"AL VOLVER reaparecen las mismas respuestas: "+despues.join(", "));
await act(async()=>{porTexto(r2,"Atrás").props.onClick();});
ok(inputs(r2).find(n=>n.props.type==="number").props.value==="97710","AL VOLVER sigue el km = 97710");
await act(async()=>{porTexto(r2,"Siguiente").props.onClick();});
ok(textoPlano(r2).includes("Retomaste un checklist sin enviar"),"se ve el aviso «Retomaste un checklist sin enviar»");
ok(!!porTexto(r2,"Descartar"),"y el botón «Descartar» para empezar de cero");

console.log("\n── Caso C: «Descartar» limpia todo ──");
await act(async()=>{porTexto(r2,"Descartar").props.onClick();});
await dormir(600);
const kmTrasDescartar=inputs(r2).find(n=>n.props.type==="number");
ok(!!kmTrasDescartar&&kmTrasDescartar.props.value==="","regresó al paso 1 con el km vacío");
let r3;await act(async()=>{r3=TR.create(h(M.CLForm,props));});
ok(!textoPlano(r3).includes("Retomaste"),"y al volver a entrar ya no hay borrador");

console.log("\n── Caso D: el checklist MENSUAL no se mezcla con el semanal ──");
await act(async()=>{r2.unmount();r3.unmount();});
let rs,rm;
await act(async()=>{rs=TR.create(h(M.CLForm,props));});
await act(async()=>{inputs(rs).find(n=>n.props.type==="number").props.onChange({target:{value:"11111"}});});
await dormir(600);
await act(async()=>{rm=TR.create(h(M.CLForm,{...props,tipo:"mensual"}));});
ok(inputs(rm).find(n=>n.props.type==="number").props.value==="","el mensual arranca limpio");
await act(async()=>{inputs(rm).find(n=>n.props.type==="number").props.onChange({target:{value:"22222"}});});
await dormir(600);
await act(async()=>{rs.unmount();});
let rs2;await act(async()=>{rs2=TR.create(h(M.CLForm,props));});
ok(inputs(rs2).find(n=>n.props.type==="number").props.value==="11111","el semanal conserva SU km (11111)");
ok(inputs(rm).find(n=>n.props.type==="number").props.value==="22222","el mensual conserva EL SUYO (22222)");
console.log("\n══ fin ══");
})();
