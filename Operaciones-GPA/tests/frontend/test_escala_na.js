// Opción N/A en «Ruedas en buen estado (si aplica)» de la bitácora de extintores:
// debe existir, contar como VERDE, no pedir evidencia y no reinterpretar lo ya
// capturado. Se usa la plantilla REAL de seed/plantillas.json y el FormDinamico real.
const {M,React,TR}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const raiz=path.resolve(__dirname,"../..");
const cat=JSON.parse(fs.readFileSync(path.join(raiz,"seed/catalogos.json"),"utf8"));cat.config={};
const plt=JSON.parse(fs.readFileSync(path.join(raiz,"seed/plantillas.json"),"utf8"))
  .plantillas.find(p=>p.clave==="extintores");
const ITEM="ruedas_en_buen_estado_si_aplica";
const session={email:"seg@gpa.com.mx",nombre:"Seguridad",rol:"operador"};
const props={plantilla:plt,cat,rol:"operador",sucursalesUser:null,session,
  showToast:()=>{},onDone:()=>{},sinBorrador:true};

const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const plano=r=>JSON.stringify(r.toJSON());
const esOpts=r=>r.root.findAll(n=>n.props&&String(n.props.className||"").startsWith("es-opt")&&n.props.onClick);

const item=plt.secciones.flatMap(s=>s.items).find(i=>i.id===ITEM);
const escalas=plt.secciones.flatMap(s=>s.items).filter(i=>i.type==="escala");
const totalOpts=escalas.reduce((n,e)=>n+e.opts.length,0);

// Llena los campos obligatorios que NO son de escala (texto, número, select, fecha):
// sin ellos el formulario no deja pasar a la pantalla del resultado.
const llenarGenerales=async r=>{
  for(const n of r.root.findAllByType("input").filter(x=>x.props.onChange&&!x.props.disabled)){
    if(n.props.type==="file")continue;
    const v=n.props.type==="number"?"6":n.props.type==="date"?"2026-09-01":"Oficina 1";
    await act(async()=>{n.props.onChange({target:{value:v}});});
  }
  for(const sl of r.root.findAllByType("select").filter(x=>x.props.onChange)){
    const vals=(sl.props.children||[]).flat().filter(Boolean)
      .map(o=>o&&o.props&&(o.props.value!==undefined?o.props.value:o.props.children))
      .filter(v=>typeof v==="string"&&v);
    if(vals.length)await act(async()=>{sl.props.onChange({target:{value:vals[vals.length-1]}});});
  }
};
// El semáforo vive en su propio recuadro: se lee su CLASE, no el texto suelto de
// la pantalla (la etiqueta «Fuera de servicio» también sale como insignia de cada
// opción, y eso haría pasar la prueba por el motivo equivocado).
const semaforo=r=>{
  const n=r.root.findAll(x=>x.props&&String(x.props.className||"").startsWith("score-bar"))[0];
  return n?String(n.props.className):null;
};
// Responde TODAS las escalas; `elegir(item)` devuelve la posición a marcar.
const responder=async(r,elegir)=>{
  let cur=0;
  for(const e of escalas){
    const bloque=esOpts(r).slice(cur,cur+e.opts.length);
    await act(async()=>{bloque[elegir(e)].props.onClick();});
    cur+=e.opts.length;
  }
};

(async()=>{
console.log("══ EXTINTORES · «Ruedas en buen estado (si aplica)» ══\n");

console.log("── La plantilla ──");
ok(!!item,"existe la pregunta en la bitácora de extintores");
ok(item.opts.length===3,"tiene 3 opciones: "+item.opts.map(o=>o.t+"["+o.sev+"]").join(" · "));
ok(item.opts[2].t==="N/A"&&item.opts[2].sev==="ok","N/A está y es verde (sev ok)");
ok(item.opts[0].t==="Sí"&&item.opts[1].t==="No",
   "«Sí» sigue en [0] y «No» en [1]: lo ya capturado no se reinterpreta");

console.log("\n── Marcando N/A ──");
let r;await act(async()=>{r=TR.create(h(M.FormDinamico,props));});
await act(async()=>{bt(r,"Siguiente").props.onClick();});
ok(plano(r).includes("N/A"),"la opción N/A se dibuja");
ok(esOpts(r).length===totalOpts,"se dibujan las "+totalOpts+" opciones de la sección");
await responder(r,e=>e.id===ITEM?2:0);          // N/A en Ruedas, «Sí» en el resto
ok(plano(r).includes("sel-ok"),"la opción marcada se pinta en verde (sel-ok)");
ok(!plano(r).includes("Evidencia del daño"),"con N/A NO pide foto ni descripción del daño");

console.log("\n── Resultado del extintor ──");
await llenarGenerales(r);
for(let i=0;i<4&&!bt(r,"Enviar");i++){const sg=bt(r,"Siguiente");if(!sg)break;await act(async()=>{sg.props.onClick();});}
ok(!!bt(r,"Enviar"),"se llegó a la pantalla del resultado");
const s1=semaforo(r);
ok(!!s1,"se pinta el semáforo del extintor");
ok(!!s1&&s1.includes("optimo"),"con N/A el semáforo queda VERDE — clase: "+s1);
ok(!!s1&&!s1.includes("fuera"),"y no queda fuera de servicio");
ok(plano(r).includes("Óptimo / operativo"),"el texto dice «Óptimo / operativo»");

console.log("\n── Contraste: responder «No» sí debe marcar rojo ──");
await act(async()=>{r.unmount();});
let r2;await act(async()=>{r2=TR.create(h(M.FormDinamico,props));});
await act(async()=>{bt(r2,"Siguiente").props.onClick();});
await responder(r2,e=>e.id===ITEM?1:0);         // 1 = «No»
ok(plano(r2).includes("Evidencia del daño"),"con «No» sí pide la evidencia del daño");
await llenarGenerales(r2);
for(let i=0;i<4&&!bt(r2,"Enviar");i++){const sg=bt(r2,"Siguiente");if(!sg)break;await act(async()=>{sg.props.onClick();});}
const s2=semaforo(r2);
ok(!!s2&&s2.includes("fuera"),"con «No» el semáforo queda ROJO — clase: "+s2);

console.log("\n── Registros YA capturados conservan su significado ──");
ok(M.respuestaTexto(item,{answers:{[ITEM]:1}})==="No","una respuesta [1] sigue diciendo «No»");
ok(M.respuestaTexto(item,{answers:{[ITEM]:0}})==="Sí","una [0] sigue diciendo «Sí»");
ok(M.respuestaTexto(item,{answers:{[ITEM]:2}})==="N/A","y las nuevas [2] dicen «N/A»");
const conNA=M.hallazgosSecs(plt.secciones,{answers:{[ITEM]:2}});
ok(!conNA.some(x=>x.label===item.label),"N/A no entra en «Puntos en mal estado» del PDF");
const conNo=M.hallazgosSecs(plt.secciones,{answers:{[ITEM]:1}});
ok(conNo.some(x=>x.label===item.label),"pero «No» sí entra");
console.log("\n══ fin ══");
})();
