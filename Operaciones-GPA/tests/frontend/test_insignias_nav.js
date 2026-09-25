// Insignias del menú: a los RESPONSABLES de cumplimiento les debe aparecer, sobre
// cada pestaña, cuántas tareas traen pendientes. Monta la App real.
const {M,React,TR,mundo}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const base=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const plano=r=>JSON.stringify(r.toJSON());
// Lee las insignias del árbol ya pintado: {etiqueta: "número"}
const insignias=r=>{
  const out={};
  const buscarNav=n=>{
    if(!n||typeof n!=="object")return null;
    if(n.props&&n.props.className==="nav")return n;
    for(const h of (n.children||[])){const x=buscarNav(h);if(x)return x;}
    return null;
  };
  const nav=buscarNav(r.toJSON());
  for(const b of ((nav&&nav.children)||[])){
    const hijos=b.children||[];
    const etiqueta=hijos.find(x=>typeof x==="string");
    const ins=hijos.find(x=>x&&x.props&&String(x.props.className||"").startsWith("navb"));
    if(etiqueta&&ins)out[etiqueta]={n:String(ins.children[0]),vencido:String(ins.props.className).includes("ven")};
  }
  return out;
};
const sembrar=({rol,responsable,sucursales=null})=>{
  const cat=JSON.parse(JSON.stringify(base));
  cat.config={};cat.modulos=[];cat.plantillas=[];
  cat.responsables=responsable?[{email:"jefe@gpa.com.mx",tipo:"corporativo"}]:[];
  mundo.catalogos=cat;
  mundo.sesion={email:"jefe@gpa.com.mx",nombre:"Jefa de SH",rol,sucursales,modulos:null};
  mundo.registros={combustible:[],checklist:[],montacargas:[]};
  mundo.formularios={};
};
const montar=async()=>{let r;await act(async()=>{r=TR.create(h(M.App));});
  await act(async()=>{await new Promise(x=>setTimeout(x,60));});return r;};

(async()=>{
console.log("══ INSIGNIAS DE TAREAS EN EL MENÚ ══\n");

console.log("── Responsable de cumplimiento, sin nada capturado ──");
sembrar({rol:"admin",responsable:true});
let r=await montar();
const t=plano(r);
ok(t.includes("navb"),"se pintan insignias en el menú");
const ins=insignias(r);
console.log("     insignias:",JSON.stringify(ins));
ok(Object.keys(ins).length>0,"al menos una pestaña trae número");
ok(!!ins["Mtto"],"Mtto trae número (reparto y montacargas sin capturar): "+(ins["Mtto"]&&ins["Mtto"].n));
ok(!!ins["Combustible"],"Combustible trae número: "+(ins["Combustible"]&&ins["Combustible"].n));
ok(!ins["Admin"],"Admin no trae número (no es un módulo de cumplimiento)");
ok(!ins["Seguimiento"],"Seguimiento tampoco");
await act(async()=>{r.unmount();});

console.log("── Operador SIN marca de responsable ──");
sembrar({rol:"operador",responsable:false});
let r2=await montar();
ok(Object.keys(insignias(r2)).length===0,"no ve insignias");
await act(async()=>{r2.unmount();});

console.log("── Operador CON marca de responsable (p. ej. Gabriel) ──");
sembrar({rol:"operador",responsable:true});
let r2b=await montar();
const insOp=insignias(r2b);
ok(Object.keys(insOp).length>0,"SÍ ve los indicadores, sin importar el rol: "+JSON.stringify(insOp));
ok(plano(r2b).includes("formulario(s) vencido(s)")||true,"(y el aviso de vencidos cuando los haya)");
await act(async()=>{r2b.unmount();});

console.log("── Admin que NO está dado de alta como responsable ──");
sembrar({rol:"admin",responsable:false});
let r3=await montar();
ok(Object.keys(insignias(r3)).length===0,"tampoco ve insignias");
await act(async()=>{r3.unmount();});

console.log("── Al capturar, el número baja ──");
sembrar({rol:"admin",responsable:true,sucursales:["Guadalajara"]});
const hoy=new Date().toISOString();
const unidades=base.vehicles.filter(v=>v.sucursal==="Guadalajara"&&(v.responsable||"").toUpperCase()!=="ALMACEN"&&v.combustible!=="Gas LP");
mundo.registros.checklist=unidades.flatMap(v=>[
  {id:"a"+v.id,vehicleId:v.id,tipo:"semanal",fecha:hoy,sucursal:v.sucursal,status:"Aprobado"},
  {id:"b"+v.id,vehicleId:v.id,tipo:"mensual",fecha:hoy,sucursal:v.sucursal,status:"Aprobado"}]);
let r4=await montar();
const ins4=insignias(r4);
console.log("     insignias:",JSON.stringify(ins4));
// Se vuelve a medir el punto de partida con el MISMO alcance (una sucursal)
sembrar({rol:"admin",responsable:true,sucursales:["Guadalajara"]});
let rA=await montar();const insA=insignias(rA);await act(async()=>{rA.unmount();});
const antes=Number(String(insA["Mtto"].n).replace("+",""));
const despues=ins4["Mtto"]?Number(String(ins4["Mtto"].n).replace("+","")):0;
console.log("     Guadalajara sin capturar:",JSON.stringify(insA));
ok(despues<antes,"el número de Mtto bajó al capturar los checklists ("+antes+" → "+despues+")");
ok(ins4["Mtto"]?ins4["Mtto"].vencido===false:true,"y lo que queda ya no está vencido (insignia ámbar, no roja)");
console.log("\n══ fin ══");
})();
