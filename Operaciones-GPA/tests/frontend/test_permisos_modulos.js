// Permisos por módulo: lo que Admin → Cuentas puede otorgar debe coincidir con lo
// que la app muestra en el menú. Monta la App REAL con distintas cuentas.
const {M,React,TR,mundo}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const base=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
const src=fs.readFileSync(path.resolve(__dirname,"../../frontend/index.html"),"utf8");
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};

// Pestañas visibles en el menú de la App montada
const pestanas=r=>{
  const buscarNav=n=>{if(!n||typeof n!=="object")return null;if(n.props&&n.props.className==="nav")return n;
    for(const x of (n.children||[])){const y=buscarNav(x);if(y)return y;}return null;};
  const nav=buscarNav(r.toJSON());
  return ((nav&&nav.children)||[]).map(b=>(b.children||[]).find(x=>typeof x==="string")).filter(Boolean);
};
const montar=async(rol,modulos)=>{
  const cat=JSON.parse(JSON.stringify(base));cat.config={};cat.modulos=[{clave:"responsivas",nombre:"Responsivas",activo:true}];cat.plantillas=[];cat.responsables=[];cat.eppArticulos=[];
  mundo.catalogos=cat;mundo.sesion={email:"u@gpa.com.mx",nombre:"Usuario",rol,sucursales:null,modulos};
  let r;await act(async()=>{r=TR.create(h(M.App));});
  await act(async()=>{await new Promise(x=>setTimeout(x,40));});
  return r;
};

(async()=>{
console.log("══ PERMISOS POR MÓDULO ══\n");
console.log("── Lo que Admin → Cuentas puede otorgar ──");
const m=/Módulos con acceso[\s\S]{0,400}?\[\[(.*?)\]\]\.map/.exec(src.replace(/\n/g," "));
const chips=src.match(/\[\["combustible","Combustible"\],\["mtto","Mtto"\],\["seguridad","Seguridad Industrial"\],\["epp","EPP"\]/);
ok(!!chips,"la pantalla de Cuentas ofrece EPP como módulo con acceso");

console.log("\n── Cuenta SIN módulos marcados = ve todos ──");
let r=await montar("operador",null);
let t=pestanas(r);
ok(t.includes("Combustible")&&t.includes("Mtto")&&t.includes("Seguridad")&&t.includes("EPP")&&t.includes("Responsivas"),"ve Combustible, Mtto, Seguridad, EPP y Responsivas: "+t.join(" · "));
ok(!t.includes("Admin")&&!t.includes("Seguimiento"),"un operador no ve Admin ni Seguimiento");
await act(async()=>{r.unmount();});

console.log("\n── Cuenta limitada a EPP ──");
r=await montar("operador",["epp"]);
t=pestanas(r);
ok(t.length===1&&t[0]==="EPP","solo ve EPP: "+t.join(" · "));
await act(async()=>{r.unmount();});

console.log("\n── Cuenta limitada a Combustible y Mtto ──");
r=await montar("supervisor",["combustible","mtto"]);
t=pestanas(r);
ok(t.includes("Combustible")&&t.includes("Mtto")&&!t.includes("EPP")&&!t.includes("Seguridad"),"ve Combustible y Mtto, no EPP ni Seguridad: "+t.join(" · "));
ok(t.includes("Seguimiento"),"como supervisor sí ve Seguimiento");
await act(async()=>{r.unmount();});

console.log("\n── Módulos heredados de antes (checklist / montacargas) siguen abriendo Mtto ──");
r=await montar("operador",["montacargas"]);
t=pestanas(r);
ok(t.includes("Mtto"),"una cuenta vieja con «montacargas» ve Mtto: "+t.join(" · "));
await act(async()=>{r.unmount();});

console.log("\n── Administrador ──");
r=await montar("admin",null);
t=pestanas(r);
ok(t.includes("Admin")&&t.includes("Seguimiento")&&t.includes("EPP"),"ve Admin, Seguimiento y EPP: "+t.join(" · "));
console.log("\n══ fin ══");
})();
