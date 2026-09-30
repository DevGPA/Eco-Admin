// Plan Mtto (plan anual de mantenimiento): se montan los componentes REALES de
// index.html con la agenda que devolvería el servidor y se recorre el flujo del
// técnico (semana → abrir → faltante → iniciar → foto → completar), la petición de
// reprogramar, el correctivo con vista previa del reinicio, el tablero, la asignación
// y los catálogos del administrador. También la pestaña y el editor de administradores.
const {M,React,TR,llamadas,mundo,descargas,localStorage,windowStub}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
// Texto visible del árbol: los textos vecinos de un mismo elemento se pegan sin separador
// («Esta semana (» + 2 + «)» → «Esta semana (2)»); entre elementos va un espacio.
const plano=r=>{const walk=n=>n==null?"":(typeof n==="string"||typeof n==="number")?String(n):Array.isArray(n)?n.map(walk).join(""):(n.children?" "+n.children.map(walk).join("")+" ":"");return walk(r.toJSON());};
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const bts=(r,t)=>r.root.findAllByType("button").filter(b=>JSON.stringify(b.props.children||"").includes(t));
const espera=ms=>act(async()=>{await new Promise(x=>setTimeout(x,ms));});
const montar=(comp,props)=>TR.create(h(comp,props));
// Texto plano de una instancia (sin JSON.stringify de props: los elementos React son circulares)
const textoDe=inst=>inst.findAll(()=>true).map(x=>{const c=x.props&&x.props.children;const pl=v=>(typeof v==="string"||typeof v==="number")?String(v):"";return Array.isArray(c)?c.map(pl).join(""):pl(c);}).join(" ");
// La tarjeta de un vencimiento en la agenda: div.card con onClick cuyo texto trae el código y la semana
const tarjetaDe=(r,codigo,semana)=>r.root.findAll(n=>n.props&&n.props.className==="card"&&n.props.onClick).find(n=>{const t=textoDe(n);return t.includes(codigo)&&(semana==null||t.includes("Sem "+semana));});

const TEC="tec1@gpa.com.mx",TEC2="tec2@gpa.com.mx",JEFE="mantenimiento@gpa.com.mx";
const ACTS=[
  {codigo:"AIR-GDL-01",tipo:"AIR",descripcion:"GERENCIA VENTAS",sucursal:"Cedis",sucCodigo:"GDL",area:"Mini splits",periodicidad:"6 MESES",semPeriodo:26,responsabilidad:"INTERNO",titular:null,activo:true},
  {codigo:"AIR-GDL-02",tipo:"AIR",descripcion:"CONTABILIDAD",sucursal:"Cedis",sucCodigo:"GDL",area:"Mini splits",periodicidad:"6 MESES",semPeriodo:26,responsabilidad:"INTERNO",titular:TEC2,activo:true},
  {codigo:"MON-GDL-01",tipo:"MON",descripcion:"DOOSAN",sucursal:"Cedis",sucCodigo:"GDL",area:"Equipo de carga pesado",periodicidad:"2 MESES",semPeriodo:8,responsabilidad:"EXTERNO",titular:null,activo:true},
  {codigo:"JAR-GDL-01",tipo:"JAR",descripcion:"JARDÍN",sucursal:"Cedis",sucCodigo:"GDL",area:"Servicios generales",periodicidad:"3 MESES",semPeriodo:13,responsabilidad:"INTERNO",titular:null,activo:true},
];
const TIPOS=[
  {pref:"AIR",nombre:"Mini split",procedimiento:"Limpieza y mantenimiento del equipo.",puntos:["Filtros lavados","Serpentín limpio"],materiales:["Filtro de repuesto · 1 pza"],herramienta:["Hidrolavadora","Termómetro"],esPropuesta:false},
  {pref:"MON",nombre:"Montacargas",procedimiento:"Aplicar el protocolo de supervisión.",puntos:["Horómetro leído"],materiales:[],herramienta:[],supervision:"Lee el horómetro antes.",esPropuesta:true},
  {pref:"JAR",nombre:"Jardinería",procedimiento:"",puntos:[],materiales:[],herramienta:[],esPropuesta:false},
];
const mp=(codigo,semana,extra)=>({id:codigo+"#2026#"+semana,codigo,anio:2026,semana,sucursal:"Cedis",area:(ACTS.find(a=>a.codigo===codigo)||{}).area,estatus:"programada",
  estatusEfectivo:semana<39?"vencida":"programada",lista:semana===39?"semana":semana<39?"atrasadas":"proximas",asignado:(ACTS.find(a=>a.codigo===codigo)||{}).titular||null,mia:false,puedeEjecutar:!(ACTS.find(a=>a.codigo===codigo)||{}).titular,fechaLimite:"2026-09-26",publicado:true,hist:[],...(extra||{})});
const ITEMS=[mp("AIR-GDL-01",8,{lista:"atrasadas"}),mp("AIR-GDL-01",39),mp("AIR-GDL-01",46),mp("AIR-GDL-02",39,{asignado:TEC2,mia:false,puedeEjecutar:false}),
  mp("MON-GDL-01",39),mp("MON-GDL-01",46),mp("JAR-GDL-01",41),
  mp("AIR-GDL-02",8,{estatus:"completada",estatusEfectivo:"completada",lista:"cerradas",tecnico:"Técnico Dos",fin:"2026-02-20T10:00:00-06:00",desc:"Lavado",fotos:["https://s3/MP/a.jpg"],hist:[{a:"Completada",q:"Técnico Dos",c:"2026-02-20T10:00:00-06:00"}]})];
const agenda=(nivel,extra)=>({nivel,items:JSON.parse(JSON.stringify(ITEMS)),activos:ACTS,tipos:TIPOS,correctivos:[],semanaActual:39,anioActual:2026,anio:2026,hoy:"2026-09-25",
  rangoSemana:["2026-09-21","2026-09-26"],sucursales:{GDL:"Cedis",CZD:"Guadalajara"},resumen:{},periodicidades:{"POR MES":4,"6 MESES":26,"VARIABLE":0},...(extra||{})});
const sesion=email=>({email,nombre:email.split("@")[0],rol:"operador"});
const cat={sucursales:["Cedis","Cancun"],modulos:[{clave:"mantenimiento",nombre:"Plan Mtto",activo:true,administradores:[JEFE]}],plantillas:[],users:[],vehicles:[],responsables:[],config:{}};

(async()=>{
console.log("══ PLAN MTTO (plan anual de mantenimiento) ══\n");
console.log("── Semanas con la fórmula del Excel (espejo del servidor) ──");
ok(M.mtInicioSemana(2026,1).toDateString()==="Mon Dec 29 2025","la semana 1 de 2026 empieza el 29-dic-2025");
ok(M.mtVence(2026,38)==="19 sep","la semana 38 vence el sábado 19 sep");
let r=M.mtReinicio([8,46],26,39);ok(r.quitar.join()==="46"&&r.conservar.join()==="8"&&r.nuevas.length===0,"6 meses en la 39: retira la 46 y conserva la 8");
r=M.mtReinicio([7,19,33,46],8,20);ok(r.quitar.join()==="33,46"&&r.nuevas.join()==="28,36,44,52","2 meses en la 20: retira 33 y 46, agrega 28, 36, 44, 52");
ok(M.mtReinicio([12,24],0,20).quitar.length===0,"Variable no recalcula");

console.log("\n── El técnico: agenda ──");
mundo.mtto=agenda("ejecuta");llamadas.length=0;
let a;await act(async()=>{a=montar(M.ModPlanMtto,{cat,rol:"operador",session:sesion(TEC),showToast:()=>{}});});await espera(40);
let t=plano(a);
ok(t.includes("Semana")&&t.includes("39"),"muestra la semana actual (39)");
ok(t.includes("Esta semana (2)")&&t.includes("Atrasadas (1)")&&t.includes("Próximas (3)"),"con «solo mías y sin asignar»: esta semana 2 (AIR-01 y MON; AIR-02 es de otro), atrasadas 1, próximas 3");
ok(!t.includes("CONTABILIDAD"),"con «solo mías» no ve lo asignado a otro técnico");
ok(t.includes("SIN ASIGNAR"),"marca lo que está sin asignar");
ok(t.includes("EXTERNO"),"marca lo EXTERNO");
ok(!bt(a,"Tablero")&&!bt(a,"Asignación")&&!bt(a,"Catálogos"),"el técnico no ve tablero, asignación ni catálogos");
ok(!!bt(a,"Falla"),"pero sí puede reportar una falla");
const chk=a.root.findAllByType("input").find(i=>i.props.type==="checkbox");
await act(async()=>{chk.props.onChange({target:{checked:false}});});
ok(plano(a).includes("CONTABILIDAD")&&plano(a).includes("Esta semana (3)")&&plano(a).includes("Cerradas (1)"),"al quitar «solo mías» ve toda la sucursal (3 esta semana, 1 cerrada)");
await act(async()=>{bt(a,"Atrasadas").props.onClick();});
ok(plano(a).includes("Vencida")&&plano(a).includes("GERENCIA VENTAS"),"atrasadas: la semana 8 sale como Vencida");

console.log("\n── Abrir, marcar faltante, iniciar, foto, completar ──");
await act(async()=>{bt(a,"Esta semana").props.onClick();});
const tarjeta=tarjetaDe(a,"AIR-GDL-01",39);
await act(async()=>{tarjeta.props.onClick();});
t=plano(a);
ok(t.includes("Procedimiento")&&t.includes("Limpieza y mantenimiento"),"detalle: muestra el procedimiento del tipo");
ok(t.includes("Antes de empezar")&&t.includes("Hidrolavadora"),"kit: material y herramienta");
ok(t.includes("Filtros lavados"),"puntos de revisión como casillas");
ok(bt(a,"Completar").props.disabled===true,"no completa sin describir lo hecho");
await act(async()=>{bt(a,"Termómetro").props.onClick();});
ok(plano(a).includes("✗ Termómetro"),"marca el faltante");
llamadas.length=0;
await act(async()=>{bt(a,"Iniciar").props.onClick();});await espera(30);
let e=llamadas.find(l=>l.metodo==="mttoEstado");
ok(!!e&&e.datos.estatus==="proceso"&&e.rid==="AIR-GDL-01#2026#39"&&e.datos.faltantes.join()==="Termómetro","«Iniciar» manda proceso con el faltante");
// tras iniciar la agenda se recarga y el detalle se cierra; se vuelve a abrir
await espera(40);
mundo.mtto.items.find(i=>i.id==="AIR-GDL-01#2026#39").estatus="proceso";
const tarjeta2=tarjetaDe(a,"AIR-GDL-01",39);
await act(async()=>{tarjeta2.props.onClick();});
const fotos=a.root.findAllByType(M.FotoCampo);
ok(fotos.length===2&&fotos[0].props.label==="Foto antes"&&fotos[1].props.label==="Foto después","dos campos de foto: antes y después");
await act(async()=>{fotos[0].props.set("data:image/jpeg;base64,ANTES");});
await act(async()=>{fotos[1].props.set("data:image/jpeg;base64,DESPUES");});
const ta=a.root.findAllByType("textarea")[0];
await act(async()=>{ta.props.onChange({target:{value:"Filtros lavados y serpentín limpio"}});});
const cb=a.root.findAllByType("input").filter(i=>i.props.type==="checkbox"&&!i.props.disabled);
await act(async()=>{cb[0].props.onChange();});
await act(async()=>{bt(a,"Falta refacción").props.onClick();});
ok(bt(a,"Completar").props.disabled!==true,"con descripción se habilita Completar");
llamadas.length=0;
await act(async()=>{bt(a,"Completar").props.onClick();});await espera(40);
e=llamadas.find(l=>l.metodo==="mttoEstado");
ok(!!e&&e.datos.estatus==="completada","Completar manda estatus completada");
ok(e.datos.desc.startsWith("Filtros")&&e.datos.checks.join()==="Filtros lavados"&&e.datos.incidencias.join()==="Falta refacción","con descripción, puntos marcados e incidencia");
ok(e.datos.fotos.length===2&&e.datos.fotos[0].startsWith("data:image"),"con las dos fotos (aquí el stub de S3 es identidad)");
ok(localStorage.getItem("mtto_AIR-GDL-01#2026#39")===null,"y borra el borrador local");

console.log("\n── Lo asignado a otro y la petición de reprogramar ──");
await espera(30);
const chk2=a.root.findAllByType("input").find(i=>i.props.type==="checkbox");
if(chk2&&chk2.props.checked)await act(async()=>{chk2.props.onChange({target:{checked:false}});});
const otra=tarjetaDe(a,"AIR-GDL-02",39);
await act(async()=>{otra.props.onClick();});
t=plano(a);
ok(t.includes("asignada a otra persona"),"avisa que está asignada a otra persona");
ok(!bt(a,"Completar"),"y no ofrece Completar");
await act(async()=>{bt(a,"← Agenda").props.onClick();});
const mon=tarjetaDe(a,"MON-GDL-01",39);
await act(async()=>{mon.props.onClick();});
t=plano(a);
ok(!!bt(a,"Registrar supervisión")&&!bt(a,"Completar"),"en lo EXTERNO el botón dice «Registrar supervisión»");
ok(t.includes("Propuesta: por validar")&&t.includes("Qué supervisar"),"muestra que el procedimiento es propuesta y qué supervisar");
ok(!!bt(a,"Pedir reprogramar")&&!bts(a,"Reprogramar").some(b=>JSON.stringify(b.props.children)==='"Reprogramar"'),"el técnico PIDE reprogramar; no reprograma");
await act(async()=>{bt(a,"Pedir reprogramar").props.onClick();});
ok(bt(a,"Enviar solicitud").props.disabled===true,"no envía la solicitud sin motivo");
const taM=a.root.findAllByType("textarea").find(x=>String(x.props.rows)==="2");
await act(async()=>{taM.props.onChange({target:{value:"Proveedor viene la 41"}});});
const numSem=a.root.findAllByType("input").find(i=>i.props.type==="number");
await act(async()=>{numSem.props.onChange({target:{value:"41"}});});
llamadas.length=0;
await act(async()=>{bt(a,"Enviar solicitud").props.onClick();});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoEstado");
ok(!!e&&e.datos.solicitar==="reprogramar"&&e.datos.semana===41&&e.datos.motivo.startsWith("Proveedor"),"manda la solicitud con semana y motivo (el plazo lo mueve el administrador)");
await act(async()=>{a.unmount();});

console.log("\n── Correctivo con vista previa del reinicio ──");
mundo.mtto=agenda("ejecuta");
let c;await act(async()=>{c=montar(M.MttoCorrectivo,{datos:mundo.mtto,actPor:Object.fromEntries(ACTS.map(x=>[x.codigo,x])),tipoPor:{},codigoPre:"AIR-GDL-01",session:sesion(TEC),showToast:()=>{},niv:"ejecuta",onBack:()=>{},onListo:async()=>{}});});
t=plano(c);
ok(t.includes("3 vencimiento(s) este año: semanas 8, 39, 46"),"al elegir el equipo dice sus vencimientos del año");
ok(bt(c,"Guardar correctivo").props.disabled===true,"no guarda sin falla ni descripción");
const tas=c.root.findAllByType("textarea");
await act(async()=>{tas[0].props.onChange({target:{value:"No enfría"}});});
await act(async()=>{tas[1].props.onChange({target:{value:"Cambio de capacitor y servicio"}});});
ok(!plano(c).includes("SE REINICIA"),"sin la casilla del preventivo no muestra reinicio");
const chkP=c.root.findAllByType("input").find(i=>i.props.type==="checkbox");
await act(async()=>{chkP.props.onChange({target:{checked:true}});});
t=plano(c);
ok(t.includes("SE REINICIA DESDE LA SEMANA 39"),"con la casilla muestra desde qué semana");
ok(t.includes("sem 46")&&t.includes("sem 8"),"dice que se retira la 46 y se conserva la 8");
llamadas.length=0;
await act(async()=>{bt(c,"Guardar correctivo").props.onClick();});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoCorrectivo");
ok(!!e&&e.datos.codigo==="AIR-GDL-01"&&e.datos.conPreventivo===true&&e.datos.falla==="No enfría","guarda el correctivo con el equipo y «con preventivo»");
await act(async()=>{c.unmount();});

console.log("\n── El administrador: tablero, asignación, catálogos ──");
mundo.mtto=agenda("administra",{administradores:[JEFE],actas:[{fecha:"2026-09-29T10:00:00-06:00",archivo:"plan.xlsx",activos:291,vencimientos:720,hallazgos:[{codigo:"MON-MEX-01",sucursal:"MEX",semana:12,hallazgo:"Celda con el tono de GDL",dato:"FF92D050"}],avisos:["La sucursal «Tisa» no existe en la app"]}],hayPropuesta:false});
mundo.mtto.correctivos=[{id:"MPC1",codigo:"AIR-GDL-01",descripcionActivo:"GERENCIA VENTAS",sucursal:"Cedis",semana:39,falla:"No enfría",desc:"Capacitor",resp:"INTERNO",conPreventivo:true,semanasRetiradas:[46],tecnico:"tec1",fin:"2026-09-25T12:00:00-06:00",fotos:[]}];
mundo.asignables=[{id:TEC,nombre:"Técnico Uno",sucursales:["Cedis"]},{id:TEC2,nombre:"Técnico Dos",sucursales:["Cedis"]}];
let j;await act(async()=>{j=montar(M.ModPlanMtto,{cat,rol:"supervisor",session:{email:JEFE,nombre:"Jefe",rol:"supervisor"},showToast:()=>{}});});await espera(60);
t=plano(j);
ok(t.includes("Administra"),"se identifica como administrador del módulo");
ok(!!bt(j,"Tablero")&&!!bt(j,"Asignación")&&!!bt(j,"Catálogos"),"ve tablero, asignación y catálogos");
ok(t.includes("Esta semana (3)")&&t.includes("Cerradas (1)"),"el administrador arranca viendo toda la sucursal");
await act(async()=>{bt(j,"Tablero").props.onClick();});
t=plano(j);
ok(t.includes("Cumplimiento")&&t.includes("exigibles"),"tablero: cumplimiento sobre lo exigible");
// exigibles = semanas ≤ 39: AIR-01 s8, AIR-01 s39, AIR-02 s39, MON s39, AIR-02 s8(completada) → 5; hechas 1 → 20%
ok(t.includes("20%")&&t.includes("1 de 5 exigibles"),"20% = 1 completada de 5 exigibles");
ok(t.includes("Las 52 semanas del plan"),"calendario de 52 semanas");
ok(t.includes("Cumplimiento por sucursal")&&t.includes("Cumplimiento por área")&&t.includes("Cumplimiento por técnico"),"barras por sucursal, área y técnico");
ok(t.includes("Técnico Dos"),"el técnico se muestra por nombre, no por correo");
descargas.length=0;
await act(async()=>{bt(j,"Descargar plan en CSV").props.onClick();});
const csv=Buffer.from(await descargas[0].blob.arrayBuffer()).subarray(3).toString("utf8");
const filas=csv.split("\r\n");
ok(filas[0].startsWith('"Código","Equipo","Sucursal"')&&filas.length===ITEMS.length+1,"CSV: encabezado entre comillas y una fila por vencimiento ("+(filas.length-1)+")");
ok(csv.includes('"Vencida"')&&csv.includes('"Completada"'),"con el estatus derivado en texto");
await act(async()=>{bt(j,"Correctivos (1)").props.onClick();});
ok(plano(j).includes("No enfría")&&plano(j).includes("retiró sem 46"),"correctivos: falla y semanas retiradas");
await act(async()=>{bt(j,"Acta").props.onClick();});
ok(plano(j).includes("291 activos")&&plano(j).includes("Tisa")&&plano(j).includes("tono de GDL"),"acta: cifras, avisos y hallazgos");
await act(async()=>{bt(j,"Evidencias").props.onClick();});
ok(plano(j).includes("Lavado")&&plano(j).includes("Técnico Dos"),"evidencias: lo capturado con quién y qué");

await act(async()=>{bt(j,"Asignación").props.onClick();});await espera(20);
t=plano(j);
ok(t.includes("Quién puede ejecutar en Cedis")&&t.includes("Técnico Uno")&&t.includes("Técnico Dos"),"asignación: lista las cuentas asignables de la sucursal");
ok(t.includes("Asignar un área completa")&&t.includes("Titular por activo")&&t.includes("Excepción de una semana"),"con área completa, titular por activo y excepción por semana");
const sels=j.root.findAllByType("select");
const selArea=sels.find(s=>s.findAllByType("option").some(o=>String(o.props.children).includes("Mini splits")));
await act(async()=>{selArea.props.onChange({target:{value:"Mini splits"}});});
const selTec=sels.find(s=>s.findAllByType("option").some(o=>String(o.props.children)==="Técnico Uno")&&s!==selArea);
await act(async()=>{selTec.props.onChange({target:{value:TEC}});});
llamadas.length=0;
await act(async()=>{bt(j,"Asignar área").props.onClick();});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoAdminTitular");
ok(!!e&&e.d.area==="Mini splits"&&e.d.sucursal==="Cedis"&&e.d.titular===TEC,"área completa → titular");
llamadas.length=0;
const selExc=j.root.findAllByType("select").filter(s=>s.findAllByType("option").some(o=>String(o.props.children)==="Técnico Dos"));
await act(async()=>{selExc[selExc.length-1].props.onChange({target:{value:TEC2}});});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoAsignar");
ok(!!e&&e.rid.endsWith("#2026#39")&&e.cuenta===TEC2,"excepción de la semana 39 → mttoAsignar con el id del vencimiento");

await act(async()=>{bt(j,"Catálogos").props.onClick();});await espera(20);
t=plano(j);
ok(t.includes("Activos (4)")&&t.includes("Tipos (3)")&&t.includes("Año 2027"),"catálogos: activos, tipos y año siguiente");
await act(async()=>{bt(j,"+ Nuevo activo").props.onClick();});
ok(plano(j).includes("El código se propone solo"),"alta de activo: el código se propone solo");
const inDesc=j.root.findAllByType("input").find(i=>String(i.props.placeholder||"").includes("GERENCIA VENTAS"));
await act(async()=>{inDesc.props.onChange({target:{value:"COMEDOR"}});});
llamadas.length=0;
await act(async()=>{bt(j,"Guardar").props.onClick();});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoAdminActivo");
ok(!!e&&e.a.descripcion==="COMEDOR"&&e.a.tipo==="JAR"&&e.a.sucCodigo==="GDL"&&!e.a.codigo,"guarda el activo sin código (lo propone el servidor); el tipo por omisión es el primero por nombre (JAR)");
await act(async()=>{bt(j,"Tipos (3)").props.onClick();});
ok(plano(j).includes("Sin procedimiento"),"un tipo sin procedimiento lo dice");
const liJAR=j.root.findAll(n=>n.props&&n.props.className==="li").find(n=>textoDe(n).includes("JAR"));
await act(async()=>{liJAR.findAllByType("button")[0].props.onClick();});
const tProc=j.root.findAllByType("textarea")[0];
await act(async()=>{tProc.props.onChange({target:{value:"Podar y retirar residuo."}});});
const tPuntos=j.root.findAllByType("textarea")[1];
await act(async()=>{tPuntos.props.onChange({target:{value:"Pasto podado\nResiduo retirado\n"}});});
llamadas.length=0;
await act(async()=>{bt(j,"Guardar tipo").props.onClick();});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoAdminTipo");
ok(!!e&&e.t.pref==="JAR"&&e.t.procedimiento.startsWith("Podar")&&e.t.puntos.join("|")==="Pasto podado|Residuo retirado","edita el procedimiento y los puntos (uno por línea)");
await act(async()=>{bt(j,"Año 2027").props.onClick();});
llamadas.length=0;
await act(async()=>{bt(j,"Simular").props.onClick();});await espera(30);
e=llamadas.find(l=>l.metodo==="mttoAdminGenerar");
ok(!!e&&e.anio===2027&&e.aplicar===false,"simula el año siguiente sin escribir");
ok(plano(j).includes("MON-MEX-01"),"lista los de periodicidad Variable aparte");
windowStub.confirm=()=>true;
ok(plano(j).includes("Crear propuesta (7)"),"ofrece crear la propuesta con el total simulado (7)");
await act(async()=>{bt(j,"Crear propuesta").props.onClick();});await espera(30);
e=llamadas.filter(l=>l.metodo==="mttoAdminGenerar").pop();
ok(!!e&&e.aplicar===true,"«Crear propuesta» aplica");
await act(async()=>{bt(j,"Publicar el plan").props.onClick();});await espera(30);
ok(llamadas.some(l=>l.metodo==="mttoAdminPublicar"&&l.anio===2027),"y «Publicar» publica el 2027");
await act(async()=>{bt(j,"Administradores").props.onClick();});
ok(plano(j).includes(JEFE),"administradores: lista los correos (se editan en Admin → Módulos)");
await act(async()=>{j.unmount();});

console.log("\n── Consulta (analista) ──");
mundo.mtto=agenda("consulta");
let q;await act(async()=>{q=montar(M.ModPlanMtto,{cat,rol:"analista",session:{email:"ana@gpa.com.mx",nombre:"Ana",rol:"analista"},showToast:()=>{}});});await espera(40);
ok(!!bt(q,"Tablero")&&!bt(q,"Falla")&&!bt(q,"Asignación"),"el analista ve el tablero, no reporta fallas ni asigna");
await act(async()=>{q.unmount();});

console.log("\n── Editor de administradores (Admin → Módulos) ──");
let ed;let guardado=null;await act(async()=>{ed=montar(M.MttoAdminsEditor,{mo:{clave:"mantenimiento",administradores:[JEFE]},busy:false,onSave:l=>{guardado=l;}});});
ok(ed.root.findAllByType("input")[0].props.value===JEFE,"precarga los administradores actuales");
await act(async()=>{ed.root.findAllByType("input")[0].props.onChange({target:{value:JEFE+", Nuevo@GPA.com.mx ; otro@gpa.com.mx"}});});
await act(async()=>{bt(ed,"Guardar administradores").props.onClick();});
ok(guardado&&guardado.join("|")===JEFE+"|nuevo@gpa.com.mx|otro@gpa.com.mx","separa por coma o punto y coma y normaliza a minúsculas");
await act(async()=>{ed.unmount();});

console.log("\n── La pestaña en el menú ──");
const src=fs.readFileSync(path.resolve(__dirname,"../../frontend/index.html"),"utf8");
ok(src.includes('{id:"mantenimiento",label:"Plan Mtto"')&&src.includes('mttoOn'),"la pestaña «Plan Mtto» existe y depende de que el módulo esté activo");
ok(src.includes('["mantenimiento","Plan Mtto"]'),"Admin → Cuentas ofrece la ficha «Plan Mtto»");
ok(src.includes('mod==="mantenimiento"&&mttoOn&&<ModPlanMtto'),"y la app la pinta con el módulo real");
console.log("\n══ fin ══");
})().catch(e=>{console.error("✗ EXCEPCIÓN",e);process.exitCode=1;});
