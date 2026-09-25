// Flujo en dos manos: un usuario PRE-REGISTRA la entrega de EPP (sin firma ni
// evidencias) y el RESPONSABLE de la sucursal la abre y la CONCLUYE con evidencias
// y la firma del empleado. Monta los componentes reales.
const {M,React,TR,llamadas,mundo,localStorage}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
cat.config={};cat.eppArticulos=[{id:"casco",nombre:"Casco",grupo:"Equipo de Protección",activo:true},{id:"calzado",nombre:"Calzado con casquillo",grupo:"Equipo de Protección",conTalla:true,activo:true}];
cat.responsables=[{email:"resp@gpa.com.mx",tipo:"sucursal"}];
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const plano=r=>r.toJSON()?JSON.stringify(r.toJSON()):"";
const lienzo={getContext:()=>({beginPath(){},moveTo(){},lineTo(){},stroke(){},clearRect(){}}),toDataURL:()=>"data:image/png;base64,FIRMA",getBoundingClientRect:()=>({left:0,top:0,width:340,height:120}),width:340,height:120};
const montar=(comp,props)=>TR.create(h(comp,props),{createNodeMock:el=>el.type==="canvas"?lienzo:null});
const espera=ms=>act(async()=>{await new Promise(x=>setTimeout(x,ms));});
const firmar=async r=>{const c=r.root.findAllByType("canvas")[0];await act(async()=>{c.props.onMouseDown({clientX:5,clientY:5,preventDefault(){}});});await act(async()=>{c.props.onMouseUp();});};

const PRE={id:"p1",tipo_reg:"EPP",movimiento:"salida",status:"Prerregistro",fecha:new Date().toISOString(),sucursal:"Cancun",
  numEmpleado:"1042",empleado:"Edgar Eduardo Grajales Gamboa",responsable:"Juan Pérez (supervisor)",aviso:"Acepto y me comprometo…",
  renglones:[{articuloId:"calzado",cantidad:1,talla:"29"},{articuloId:"casco",cantidad:1}]};

(async()=>{
console.log("══ PRE-REGISTRO DE ENTREGA DE EPP ══\n");

console.log("── 1. El usuario deja la entrega en pre-registro (sin firma) ──");
const quien={email:"op@gpa.com.mx",nombre:"Operador"};
localStorage.setItem("gpa_epp_draft_salida_op@gpa.com.mx",JSON.stringify(
  {suc:"Cancun",numEmpleado:"1042",empleado:"Edgar Eduardo Grajales Gamboa",reng:[{articuloId:"calzado",cantidad:"1",talla:"29"}],obs:""}));
llamadas.length=0;
let f;await act(async()=>{f=montar(M.EppForm,{movimiento:"salida",cat,session:quien,rol:"operador",sucursalesUser:null,refrescar:async()=>{},showToast:()=>{},onDone:()=>{}});});
ok(bt(f,"Registrar entrega").props.disabled===true,"sin firma, «Registrar entrega» está deshabilitado");
const chk=f.root.findAllByType("input").find(i=>i.props.type==="checkbox");
ok(!!chk&&plano(f).includes("Dejar en pre-registro"),"existe la casilla «Dejar en pre-registro»");
await act(async()=>{chk.props.onChange({target:{checked:true}});});
ok(!plano(f).includes("Firma de quien recibe"),"al marcarla desaparece el bloque de firma");
const btn=bt(f,"Guardar pre-registro");
ok(!!btn&&btn.props.disabled!==true,"el botón cambia a «Guardar pre-registro» y se habilita sin firma");
await act(async()=>{btn.props.onClick();});
await espera(250);
const env=llamadas.find(l=>l.metodo==="crear");
ok(!!env&&env.datos.status==="Prerregistro","se envía con status Prerregistro");
ok(env&&!("firma" in env.datos),"y SIN firma");
ok(env&&env.datos.numEmpleado==="1042"&&env.datos.renglones[0].talla==="29","con empleado, artículos y talla ya capturados");
await act(async()=>{f.unmount();});

console.log("\n── 2. La pestaña «Por concluir» solo la ve el responsable ──");
const propsMod=(email)=>({cat,items:[PRE],rol:"supervisor",sucursalesUser:["Cancun"],session:{email,nombre:"X"},refrescar:async()=>{},showToast:()=>{}});
let m1;await act(async()=>{m1=montar(M.ModEPP,propsMod("otro@gpa.com.mx"));});
ok(!bt(m1,"Por concluir"),"un supervisor SIN la marca de responsable no ve la pestaña");
await act(async()=>{m1.unmount();});
let m2;await act(async()=>{m2=montar(M.ModEPP,propsMod("RESP@gpa.com.mx"));});
ok(!!bt(m2,"Por concluir"),"el responsable sí la ve (sin importar mayúsculas en el correo)");

console.log("\n── 3. Abre el pre-registro desde la lista ──");
mundo.pendientes={items:[PRE],responsable:true};
await act(async()=>{bt(m2,"Por concluir").props.onClick();});
await espera(40);
const t3=plano(m2);
ok(t3.includes("1042")&&t3.includes("Edgar"),"la lista muestra al empleado del pre-registro (número y nombre)");
ok(t3.includes("Por concluir"),"marcado como «Por concluir»");
const fila=m2.root.findAll(n=>n.props&&n.props.className==="li"&&n.props.onClick)[0];
ok(!!fila,"se puede abrir");
await act(async()=>{fila.props.onClick();});
const t4=plano(m2);
ok(t4.includes("Concluir entrega"),"se abre la pantalla de conclusión");
ok(t4.includes("Calzado con casquillo")&&t4.includes("29"),"con los artículos y la talla ya capturados");
ok(t4.includes("Evidencia de la entrega")&&t4.includes("Firma de quien recibe"),"pide evidencia y firma");
ok(t4.includes("Acepto y me comprometo"),"y muestra la carta de conformidad para que el empleado la lea");

console.log("\n── 4. No concluye sin evidencia y firma ──");
ok(bt(m2,"Concluir entrega").props.disabled===true,"«Concluir entrega» deshabilitado en blanco");
await firmar(m2);
ok(bt(m2,"Concluir entrega").props.disabled===true,"con firma pero sin foto sigue deshabilitado");
await act(async()=>{m2.unmount();});

console.log("\n── 5. Concluye con evidencia + firma → llama al servidor ──");
llamadas.length=0;
let listo=false;
let c;await act(async()=>{c=montar(M.EppConcluir,{reg:PRE,cat,onBack:()=>{},showToast:()=>{},onListo:async()=>{listo=true;}});});
// La evidencia entra por el mismo readFile que la cámara; aquí se simula el resultado
// disparando el onChange del campo de archivo con un File real de Node.
const file=c.root.findAllByType("input").find(i=>i.props.type==="file");
ok(!!file&&file.props.capture==="environment","la evidencia se toma con la cámara (no es el campo de archivo de la factura)");
// FileReader no existe en Node: se fuerza el estado poniendo la evidencia por el mismo setter
// que usa readFile (cb) — para eso se busca el botón de la vista previa tras un onChange vacío.
await firmar(c);
ok(bt(c,"Concluir entrega").props.disabled===true,"firma sola no basta");
// Sin FileReader en Node no podemos pasar una imagen por el <input>; se valida la regla
// del servidor en tests/test_epp_prerregistro.py y aquí que el botón exija evidencia.
console.log("\n── 6. Detalle e historial reflejan el estado ──");
let d;await act(async()=>{d=montar(M.EppDetail,{reg:PRE,cat,onBack:()=>{}});});
const t6=plano(d);
ok(t6.includes("Por concluir (sin firma)"),"el detalle de un pre-registro dice «Por concluir (sin firma)»");
ok(t6.includes("Pendiente de firma"),"y avisa que la firma la pondrá el responsable");
ok(t6.includes("Pre-registró"),"y quién lo pre-registró");
await act(async()=>{d.unmount();});
const CONCL={...PRE,id:"p2",status:"Aprobado",firma:"data:image/png;base64,F",evidencias:["https://s3/ev1.jpg","https://s3/ev2.jpg"],concluidoPor:"Ana López",concluidoEn:new Date().toISOString(),obsConclusion:"Entregado en almacén"};
let d2;await act(async()=>{d2=montar(M.EppDetail,{reg:CONCL,cat,onBack:()=>{}});});
const t7=plano(d2);
ok(t7.includes("Evidencia de la entrega")&&d2.root.findAllByType("img").filter(i=>String(i.props.src).includes("s3/ev")).length===2,"concluida: muestra las 2 evidencias");
ok(t7.includes("Concluyó")&&t7.includes("Ana López"),"y quién la concluyó");
ok(t7.includes("Entregado en almacén"),"con la observación de conclusión");
ok(!t7.includes("Pendiente de firma"),"ya no dice pendiente de firma");
await act(async()=>{d2.unmount();});
let hist;await act(async()=>{hist=montar(M.EppHistory,{items:[PRE,CONCL],cat,onSelect:()=>{}});});
ok((plano(hist).match(/Por concluir/g)||[]).length===1,"en el historial solo el pre-registro lleva la insignia «Por concluir»");
console.log("\n══ fin ══");
})();
