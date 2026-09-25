// Liga PÚBLICA del examen médico (frontend/examen.html): se monta la página real
// con un fetch simulado y se recorre como lo haría un colaborador sin cuenta.
const fs=require("fs");const path=require("path");
const Babel=(()=>{try{return require("@babel/standalone");}catch(e){}
  for(const r of ["../../../../_babel.js","../../../_babel.js"]){try{return require(path.resolve(__dirname,r));}catch(e){}}
  throw new Error("Falta Babel");})();
const React=require("react");const TR=require("react-test-renderer");const act=TR.act;const h=React.createElement;
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};

const src=fs.readFileSync(path.resolve(__dirname,"../../frontend/examen.html"),"utf8");
let code=src.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1]
  .replace(/ReactDOM\.createRoot\(document\.getElementById\("root"\)\)\.render\(<App\/>\);/,"");
const js=Babel.transform(code,{presets:["react"],filename:"examen.jsx"}).code;

// ── Entorno: fetch, location, localStorage, canvas ──
const peticiones=[];let respuestas={};
const fetchFalso=async(url,opts)=>{
  peticiones.push({url,metodo:(opts&&opts.method)||"GET",body:opts&&opts.body?JSON.parse(opts.body):null});
  const r=Object.entries(respuestas).find(([k])=>url.includes(k));
  const [status,body]=r?r[1]:[404,{error:"sin ruta"}];
  return {ok:status>=200&&status<300,status,json:async()=>body};
};
const _s=new Map();
const localStorage={getItem:k=>_s.has(k)?_s.get(k):null,setItem:(k,v)=>_s.set(k,v),removeItem:k=>_s.delete(k)};
const lienzo={getContext:()=>({beginPath(){},moveTo(){},lineTo(){},stroke(){},clearRect(){}}),toDataURL:()=>"data:image/png;base64,FIRMA",getBoundingClientRect:()=>({left:0,top:0,width:340,height:120}),width:340,height:120};
const montarPagina=(search)=>{
  const windowStub={GPA_CONFIG:{apiUrl:"https://api.falsa/prod"}};
  const location={search,reload(){}};
  const fabrica=new Function("React","ReactDOM","window","location","localStorage","fetch","URLSearchParams","document",js+"\n;return {App};");
  const M=fabrica(React,{createRoot:()=>({render(){}})},windowStub,location,localStorage,fetchFalso,URLSearchParams,{getElementById:()=>null});
  return TR.create(h(M.App),{createNodeMock:el=>el.type==="canvas"?lienzo:null});
};
const plano=r=>r.toJSON()?JSON.stringify(r.toJSON()):"";
const espera=ms=>act(async()=>{await new Promise(x=>setTimeout(x,ms));});
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const inputs=r=>r.root.findAllByType("input").filter(i=>i.props.onChange&&!i.props.disabled);
const porPlaceholder=(r,p)=>inputs(r).find(i=>String(i.props.placeholder||"").includes(p));
const sel=r=>r.root.findAllByType("select")[0];
const siNo=(r,indice,valor)=>{const bs=r.root.findAllByType("button").filter(b=>b.props.className&&String(b.props.className).startsWith("rb")&&(b.props.children==="Sí"||b.props.children==="No"));
  const par=bs.slice(indice*2,indice*2+2);return act(async()=>{par[valor?0:1].props.onClick();});};

(async()=>{
console.log("══ LIGA PÚBLICA DEL EXAMEN MÉDICO ══\n");

console.log("── Liga incompleta o inválida ──");
let r0;await act(async()=>{r0=montarPagina("");});await espera(20);
ok(plano(r0).includes("liga está incompleta"),"sin ?c= y ?t= avisa que la liga está incompleta");
respuestas={"/publico/examen/campana":[404,{error:"Esta liga no está activa. Pide una nueva a Recursos Humanos."}]};
let r1;await act(async()=>{r1=montarPagina("?c=vieja&t=x");});await espera(30);
ok(plano(r1).includes("no está activa"),"con campaña inactiva muestra el aviso del servidor");
ok(r1.root.findAllByType("input").length===0,"y no muestra el formulario");

console.log("\n── Liga válida: paso 1 (identificación) ──");
respuestas={"/publico/examen/campana":[200,{nombre:"Examen 2026",clave:"examen-2026"}],"/publico/examen":[200,{ok:true,folio:"EXM-ABC123"}]};
peticiones.length=0;_s.clear();
let r;await act(async()=>{r=montarPagina("?c=examen-2026&t=tok123");});await espera(30);
ok(plano(r).includes("Examen 2026"),"muestra el nombre de la campaña");
ok(peticiones[0].url.includes("c=examen-2026")&&peticiones[0].url.includes("t=tok123"),"validó la liga con campaña y token");
ok(bt(r,"Siguiente").props.disabled===true,"no deja avanzar sin los datos obligatorios");
await act(async()=>{porPlaceholder(r,"1042").props.onChange({target:{value:"1042"}});});
await act(async()=>{porPlaceholder(r,"credencial").props.onChange({target:{value:"Edgar Eduardo Grajales Gamboa"}});});
await act(async()=>{sel(r).props.onChange({target:{value:"Cancun"}});});
await act(async()=>{inputs(r).find(i=>i.props.type==="date").props.onChange({target:{value:"1990-05-12"}});});
ok(bt(r,"Siguiente").props.disabled===true,"todavía falta el sexo");
await act(async()=>{bt(r,"Masculino").props.onClick();});
ok(plano(r).includes('"value":"36"')||plano(r).includes('"value":36'),"calcula la edad (36)");
ok(bt(r,"Siguiente").props.disabled!==true,"con número, nombre, sucursal, fecha y sexo ya deja avanzar");

console.log("\n── Pasos 2 a 5 ──");
await act(async()=>{bt(r,"Siguiente").props.onClick();});
ok(plano(r).includes("heredofamiliares"),"paso 2: antecedentes heredofamiliares");
ok((plano(r).match(/"value":"Negados"/g)||[]).length===10,"los 10 familiares arrancan en «Negados»");
await act(async()=>{bt(r,"Siguiente").props.onClick();});
ok(plano(r).includes("no patológicos")&&plano(r).includes("patológicos"),"paso 3: antecedentes personales");
ok(bt(r,"Siguiente").props.disabled===true,"no avanza sin responder Sí/No en cada uno");
for(let i=0;i<3;i++)await siNo(r,i,false);           // tabaquismo, alcoholismo, toxicomanías: No
for(let i=3;i<15;i++)await siNo(r,i,i===5);          // patológicos: solo diabetes = Sí
ok(plano(r).includes("¿Cuál? ¿Hace cuánto?"),"al marcar Sí pide el detalle");
ok(bt(r,"Siguiente").props.disabled!==true,"con todo respondido deja avanzar");
await act(async()=>{bt(r,"Siguiente").props.onClick();});
ok(plano(r).includes("neurológica"),"paso 4: cuestionario neurológico");
ok(!plano(r).includes("gineco"),"a un hombre NO se le muestra lo gineco-obstétrico");
ok(bt(r,"Siguiente").props.disabled===true,"no avanza sin las 5 respuestas");
for(let i=0;i<5;i++)await siNo(r,i,false);
await act(async()=>{bt(r,"Siguiente").props.onClick();});
ok(plano(r).includes("Antecedentes laborales")&&plano(r).includes("aparatos"),"paso 5: laborales y aparatos");
ok(plano(r).includes('"value":"GPA"'),"la fila laboral de GPA viene precargada");
await act(async()=>{bt(r,"Siguiente").props.onClick();});

console.log("\n── Paso 6: consentimiento y firma ──");
ok(plano(r).includes("Aviso de privacidad")&&plano(r).includes("datos personales sensibles"),"muestra el aviso de privacidad");
const enviar=bt(r,"Enviar examen");
ok(enviar.props.disabled===true,"no deja enviar sin consentimiento ni firma");
const chk=r.root.findAllByType("input").find(i=>i.props.type==="checkbox");
await act(async()=>{chk.props.onChange({target:{checked:true}});});
ok(bt(r,"Enviar examen").props.disabled===true,"con consentimiento pero sin firma sigue bloqueado");
const c=r.root.findAllByType("canvas")[0];
await act(async()=>{c.props.onMouseDown({clientX:5,clientY:5,preventDefault(){}});});
await act(async()=>{c.props.onMouseUp();});
ok(bt(r,"Enviar examen").props.disabled!==true,"con firma se habilita");

console.log("\n── Envío ──");
await act(async()=>{bt(r,"Enviar examen").props.onClick();});await espera(40);
const env=peticiones.find(p=>p.metodo==="POST");
ok(!!env&&env.url.endsWith("/publico/examen"),"manda POST a /publico/examen");
ok(env.body.campana==="examen-2026"&&env.body.token==="tok123","con la campaña y el token de la liga");
const d=env.body.datos;
ok(d.consentimiento===true,"consentimiento = true");
ok(String(d.firma).startsWith("data:image/png"),"firma como PNG");
ok(d.numEmpleado==="1042"&&d.nombre.startsWith("Edgar")&&d.sucursal==="Cancun"&&d.fechaNacimiento==="1990-05-12"&&d.sexo==="M","identificación completa");
ok(d.patologicos.diabetes.si===true&&d.patologicos.fracturas.si===false,"antecedentes con Sí/No como booleanos");
ok(!("gineco" in d),"sin bloque gineco-obstétrico para hombre");
ok(!("_step" in d),"sin datos de navegación en el envío");
ok(d.laborales[0].empresa==="GPA","antecedentes laborales incluidos");
ok(plano(r).includes("EXM-ABC123"),"muestra el folio de recibido");
ok(localStorage.getItem("gpa_examen_examen-2026")===null,"y borra el borrador local");

console.log("\n── Rechazos del servidor se muestran ──");
respuestas["/publico/examen"]=[409,{error:"Ya recibimos tu examen de esta campaña. Si necesitas corregir algo, acude con Recursos Humanos."}];
_s.clear();peticiones.length=0;
let r2;await act(async()=>{r2=montarPagina("?c=examen-2026&t=tok123");});await espera(30);
// Se siembra un borrador ya avanzado al último paso para probar solo el envío
_s.set("gpa_examen_examen-2026",JSON.stringify({numEmpleado:"1042",nombre:"Edgar",sucursal:"Cancun",fechaNacimiento:"1990-05-12",sexo:"M",_step:5}));
let r3;await act(async()=>{r3=montarPagina("?c=examen-2026&t=tok123");});await espera(30);
ok(plano(r3).includes("Retomaste un borrador"),"avisa que retomó un borrador de este teléfono");
const chk3=r3.root.findAllByType("input").find(i=>i.props.type==="checkbox");
await act(async()=>{chk3.props.onChange({target:{checked:true}});});
const c3=r3.root.findAllByType("canvas")[0];
await act(async()=>{c3.props.onMouseDown({clientX:5,clientY:5,preventDefault(){}});});await act(async()=>{c3.props.onMouseUp();});
await act(async()=>{bt(r3,"Enviar examen").props.onClick();});await espera(40);
ok(plano(r3).includes("Ya recibimos tu examen"),"el 409 (duplicado) se muestra tal cual al colaborador");
ok(!plano(r3).includes("EXM-"),"y no dice que se recibió");
console.log("\n══ fin ══");
})();
