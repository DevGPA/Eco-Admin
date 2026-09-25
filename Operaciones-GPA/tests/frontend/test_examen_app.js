// Examen médico en la app (dentro de Responsivas): solo con marca «Expediente
// médico»; pendientes/concluidos/campañas; el médico concluye con diagnóstico,
// clasificación y firma; el formato completo para PDF. Componentes reales.
const {M,React,TR,llamadas,mundo,descargas,localStorage}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
cat.config={};cat.plantillas=[];cat.modulos=[{clave:"responsivas",nombre:"Responsivas",activo:true}];
cat.expedienteMedico=["medico@gpa.com.mx","RH@gpa.com.mx"];
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const plano=r=>r.toJSON()?JSON.stringify(r.toJSON()):"";
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const espera=ms=>act(async()=>{await new Promise(x=>setTimeout(x,ms));});
const lienzo={getContext:()=>({beginPath(){},moveTo(){},lineTo(){},stroke(){},clearRect(){}}),toDataURL:()=>"data:image/png;base64,FIRMAMED",getBoundingClientRect:()=>({left:0,top:0,width:340,height:120}),width:340,height:120};
const montar=(comp,props)=>TR.create(h(comp,props),{createNodeMock:el=>el.type==="canvas"?lienzo:null});
const firmar=async r=>{const c=r.root.findAllByType("canvas")[0];await act(async()=>{c.props.onMouseDown({clientX:5,clientY:5,preventDefault(){}});});await act(async()=>{c.props.onMouseUp();});};

const PEND={id:"e1",tipo_reg:"EXM",status:"Pendiente médico",fecha:new Date().toISOString(),campana:"examen-2026",campanaNombre:"Examen 2026",
  numEmpleado:"1042",nombre:"Edgar Eduardo Grajales Gamboa",sucursal:"Cancun",puesto:"Almacenista",edad:36,sexo:"M",fechaNacimiento:"1990-05-12",
  heredo:{madre:"DM2",padre:"Negados"},noPatologicos:{tabaquismo:{si:false,obs:""}},patologicos:{diabetes:{si:true,cual:"Tipo 2, 3 años"},fracturas:{si:false,cual:""}},
  neurologico:{q1:false,q2:false,q3:false,q4:false,q5:false},laborales:[{empresa:"GPA",antiguedad:"4 años",puesto:"Almacenista",horario:"8-17",exposicion:"Carga",riesgos:"Montacargas"}],
  aparatos:{respiratorio:"",digestivo:"Gastritis"},firma:"https://s3/firma1.png",consentimiento:{aceptado:true,en:new Date().toISOString(),version:"2026-09"}};
const CONC={...PEND,id:"e2",numEmpleado:"7",nombre:"Ana López",sexo:"F",gineco:{fum:"2026-09-01"},status:"Concluido",medico:{signos:{peso:62,estatura:1.6},imc:24.2,diagnostico:"Sana",clasificacion:"Apto",antidoping:{THC:"Negativo"}},firmaMedico:"https://s3/fm.png",nombreMedico:"Dr. Abraham Alvarado Figueroa",concluidoPor:"medico@gpa.com.mx",concluidoEn:new Date().toISOString()};

(async()=>{
console.log("══ EXAMEN MÉDICO EN LA APP ══\n");
console.log("── La tarjeta en Responsivas solo con la marca ──");
const propsMod=email=>({cat,modulo:"responsivas",modLabel:"Responsivas",plantillas:[],rol:"admin",sucursalesUser:null,session:{email,nombre:"X"},showToast:()=>{}});
let m1;await act(async()=>{m1=montar(M.ModDinamico,propsMod("admin@gpa.com.mx"));});
ok(!plano(m1).includes("Examen médico periódico"),"un administrador SIN la marca no ve la tarjeta");
await act(async()=>{m1.unmount();});
ok(M.esExpMed(cat,{email:"rh@gpa.com.mx"})===true,"la marca no distingue mayúsculas del correo");
mundo.examenes=[PEND,CONC];mundo.campanas=[{clave:"examen-2026",nombre:"Examen 2026",activa:true,token:"tok123"}];
let m2;await act(async()=>{m2=montar(M.ModDinamico,propsMod("medico@gpa.com.mx"));});
ok(plano(m2).includes("Examen médico periódico"),"el médico (con marca) sí la ve");
// La tarjeta es el div.card con onClick cuyo texto es «🩺 Examen médico periódico»
const tarjeta=m2.root.findAll(n=>n.props&&n.props.className==="card"&&n.props.onClick)
  .filter(n=>n.findAllByType("div").some(d=>String(d.props.children)==="🩺 Examen médico periódico"));
ok(tarjeta.length===1,"la tarjeta se puede abrir");
await act(async()=>{tarjeta[0].props.onClick();});
await espera(40);
let t=plano(m2);
ok(t.includes("Pendientes de médico (1)")&&t.includes("Concluidos (1)"),"al abrir: pendientes (1) y concluidos (1)");
ok(t.includes("sensibles"),"recuerda que son datos sensibles");
ok(t.includes("1042")&&t.includes("Edgar"),"lista al pendiente");

console.log("\n── Campañas y liga ──");
await act(async()=>{bt(m2,"Campañas y liga").props.onClick();});await espera(20);
t=plano(m2);
ok(t.includes("examen.html?c=examen-2026&t=tok123"),"la liga se arma con la campaña y su token");
ok(t.includes("Activa"),"y muestra que está activa");
llamadas.length=0;
// prompt() no existe en Node: se simula
globalThis.prompt=()=>"Examen 2027";
await act(async()=>{bt(m2,"Nueva campaña").props.onClick();});await espera(40);
const nc=llamadas.find(l=>l.metodo==="adminExamenCampana");
ok(!!nc&&nc.c.clave==="examen-2027"&&nc.c.activa===true,"crea la campaña con clave limpia: "+(nc&&nc.c.clave));
await act(async()=>{m2.unmount();});

console.log("\n── El médico concluye ──");
llamadas.length=0;let listo=false;
let c;await act(async()=>{c=montar(M.ExamenConcluir,{reg:PEND,session:{email:"medico@gpa.com.mx",nombre:"Dr."},showToast:()=>{},onBack:()=>{},onListo:async()=>{listo=true;}});});
t=plano(c);
ok(t.includes("Normocéfalo"),"la exploración trae los hallazgos normales precargados");
ok(t.includes("Ver lo que declaró el colaborador")&&t.includes("Tipo 2, 3 años"),"muestra lo que declaró el colaborador (diabetes con detalle)");
ok(bt(c,"Concluir examen").props.disabled===true,"no concluye sin diagnóstico, clasificación y firma");
const nums=c.root.findAllByType("input").filter(i=>i.props.type==="number");
await act(async()=>{nums[0].props.onChange({target:{value:"80"}});});
await act(async()=>{nums[1].props.onChange({target:{value:"1.75"}});});
ok(plano(c).includes("26.1")&&plano(c).includes("Sobrepeso"),"calcula el IMC (26.1 · Sobrepeso)");
const areas=c.root.findAllByType("textarea");
await act(async()=>{areas[areas.length-1].props.onChange({target:{value:"Sobrepeso leve, sin otras alteraciones"}});});
const selClas=c.root.findAllByType("select").find(s=>s.findAllByType("option").some(o=>String(o.props.children)==="Apto"));
await act(async()=>{selClas.props.onChange({target:{value:"Apto con restricciones"}});});
ok(bt(c,"Concluir examen").props.disabled===true,"con diagnóstico y clasificación pero sin firma sigue bloqueado");
await firmar(c);
ok(bt(c,"Concluir examen").props.disabled!==true,"con firma se habilita");
await act(async()=>{bt(c,"Concluir examen").props.onClick();});await espera(60);
const env=llamadas.find(l=>l.metodo==="examenConcluir");
ok(!!env&&env.id==="e1","llama a concluir con el id del examen");
ok(env.datos.medico.diagnostico.startsWith("Sobrepeso")&&env.datos.medico.clasificacion==="Apto con restricciones","con diagnóstico y clasificación");
ok(env.datos.medico.imc===26.1&&env.datos.medico.signos.peso==="80","con signos e IMC");
ok(!!env.datos.firmaMedico&&env.datos.nombreMedico.startsWith("Dr."),"con la firma y el nombre del médico");
ok(listo,"y regresa a la lista");
await act(async()=>{c.unmount();});

console.log("\n── Formato completo (lo que sale en el PDF) ──");
let d;await act(async()=>{d=montar(M.ExamenDetalle,{reg:CONC,onBack:()=>{}});});
t=plano(d);
for(const sec of ["Ficha de identificación","heredofamiliares","no patológicos","neurológica","gineco-obstétricos","Antecedentes laborales","aparatos","Signos vitales","Antidoping","Diagnóstico y clasificación","Firmas"])
  ok(t.includes(sec),"sección: "+sec);
ok(t.includes("Ana López")&&t.includes("Apto")&&t.includes("Dr. Abraham"),"con datos, clasificación y médico");
ok(d.root.findAll(n=>n.props&&n.props["data-pdfsucursal"]==="Cancun").length===1,"le pasa la sucursal al PDF");
ok(d.root.findAllByType("img").length===2,"pinta las dos firmas");
await act(async()=>{d.unmount();});
let d2;await act(async()=>{d2=montar(M.ExamenDetalle,{reg:PEND,onBack:()=>{}});});
ok(!plano(d2).includes("gineco"),"a un hombre no se le imprime lo gineco-obstétrico");
ok(plano(d2).includes("Pendiente de exploración"),"un pendiente lo dice en las firmas");
await act(async()=>{d2.unmount();});

console.log("\n── Lista de seguimiento (CSV sin datos clínicos) ──");
descargas.length=0;
let l;await act(async()=>{l=montar(M.ExamenLista,{items:[PEND,CONC],vacio:"",onSelect:()=>{},accion:"Ver",zip:true});});
await act(async()=>{bt(l,"Lista de seguimiento").props.onClick();});
const bytes=Buffer.from(await descargas[0].blob.arrayBuffer());const txt=bytes.subarray(3).toString("utf8");
const head=txt.split("\r\n")[0];
ok(head.includes("No. empleado")&&head.includes("Estado")&&head.includes("Clasificación"),"trae identificación, estado y clasificación");
ok(!head.includes("Diagnóstico")&&!txt.includes("DM2")&&!txt.includes("Gastritis")&&!txt.includes("Negativo"),"y NINGÚN dato clínico (antecedentes, diagnóstico, antidoping)");
ok(!!bt(l,"Todos en PDF (ZIP)"),"ofrece el ZIP de todos los PDF (se genera en el navegador)");
console.log("\n══ fin ══");
})();
