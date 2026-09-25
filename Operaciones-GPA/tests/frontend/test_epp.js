// Módulo EPP: entrada por factura, entrega a empleado y tabla de existencias.
// Monta los componentes REALES de frontend/index.html.
const {M,React,TR,llamadas,mundo,localStorage}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));
cat.config={};
cat.eppArticulos=[
  {id:"playera",nombre:"Playera",grupo:"Uniforme",conTalla:true,orden:1,activo:true},
  {id:"casco",nombre:"Casco",grupo:"Equipo de Protección",conTalla:false,orden:2,activo:true},
  {id:"calzado_casquillo",nombre:"Calzado con casquillo",grupo:"Equipo de Protección",conTalla:true,orden:3,activo:true},
  {id:"faja_vieja",nombre:"Faja (descontinuada)",grupo:"Equipo de Protección",conTalla:true,orden:9,activo:false},
];
const session={email:"almacen@gpa.com.mx",nombre:"Jefe de Almacén"};
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const plano=r=>r.toJSON()?JSON.stringify(r.toJSON()):"";
const inputs=r=>r.root.findAllByType("input").filter(x=>x.props.onChange&&!x.props.disabled&&x.props.type!=="file"&&x.props.type!=="checkbox");
const selects=r=>r.root.findAllByType("select").filter(x=>x.props.onChange);
const lienzo={getContext:()=>({beginPath(){},moveTo(){},lineTo(){},stroke(){},clearRect(){}}),
  toDataURL:()=>"data:image/png;base64,FIRMA",
  getBoundingClientRect:()=>({left:0,top:0,width:340,height:120}),width:340,height:120};
const montar=(comp,props)=>TR.create(h(comp,props),{createNodeMock:el=>el.type==="canvas"?lienzo:null});
const escribir=async(r,etiqueta,valor)=>{
  // Busca el input que sigue a una etiqueta concreta, por su placeholder
  const n=inputs(r).find(x=>String(x.props.placeholder||"").includes(etiqueta));
  ok(!!n,"existe el campo con placeholder «"+etiqueta+"»");
  if(n)await act(async()=>{n.props.onChange({target:{value:valor}});});
};
const props=mov=>({movimiento:mov,cat,session,rol:"admin",sucursalesUser:null,
  refrescar:async()=>{},showToast:()=>{},onDone:()=>{}});

(async()=>{
console.log("══ MÓDULO EPP ══\n");

console.log("── ENTRADA: exige factura y su foto ──");
localStorage.removeItem("gpa_epp_draft_entrada_almacen@gpa.com.mx");
llamadas.length=0;
let r;await act(async()=>{r=montar(M.EppForm,props("entrada"));});
ok(plano(r).includes("Entrada por factura"),"se abre la captura de entrada");
ok(!plano(r).includes("Número de empleado"),"no pide datos de empleado");
ok(bt(r,"Registrar entrada").props.disabled===true,"no deja registrar en blanco");
await escribir(r,"A-10245","A-10245");
const selArt=selects(r)[1];                       // 0 = sucursal, 1 = artículo
await act(async()=>{selArt.props.onChange({target:{value:"casco"}});});
await escribir(r,"0","12");                        // cantidad
ok(bt(r,"Registrar entrada").props.disabled===true,"sigue bloqueado sin la foto de la factura");
ok(!plano(r).includes("Talla"),"la entrada no pregunta talla (el inventario es por artículo)");
await act(async()=>{r.unmount();});

console.log("\n── ENTRADA completa (la foto se siembra por el borrador) ──");
localStorage.setItem("gpa_epp_draft_entrada_almacen@gpa.com.mx",JSON.stringify(
  {suc:"Cedis",factura:"A-10245",proveedor:"Uniformes SA",fotoFactura:"data:image/jpeg;base64,FACTURA",
   reng:[{articuloId:"casco",cantidad:"12",talla:""},{articuloId:"playera",cantidad:"30",talla:""}],obs:"Pedido de septiembre"}));
let r2;await act(async()=>{r2=montar(M.EppForm,props("entrada"));});
ok(plano(r2).includes("Retomaste una entrada sin registrar"),"retoma el borrador");
ok(bt(r2,"Registrar entrada").props.disabled!==true,"con factura, foto y artículos sí deja registrar");
await act(async()=>{bt(r2,"Registrar entrada").props.onClick();});
await new Promise(x=>setTimeout(x,250));
const env=llamadas.find(l=>l.metodo==="crear");
ok(!!env&&env.tipo==="epp","se envió como movimiento de EPP");
ok(env&&env.datos.movimiento==="entrada","movimiento = entrada");
ok(env&&env.datos.factura==="A-10245","lleva el número de factura");
ok(env&&env.datos.renglones.length===2,"lleva los 2 renglones");
ok(env&&env.datos.renglones[0].cantidad===12,"la cantidad va como número: "+(env&&env.datos.renglones[0].cantidad));
ok(localStorage.getItem("gpa_epp_draft_entrada_almacen@gpa.com.mx")===null,"el borrador se borró al registrar");
await act(async()=>{r2.unmount();});

console.log("\n── ENTREGA: número de empleado ANTES del nombre ──");
localStorage.removeItem("gpa_epp_draft_salida_almacen@gpa.com.mx");
llamadas.length=0;
let r3;await act(async()=>{r3=montar(M.EppForm,props("salida"));});
const et=plano(r3);
ok(et.includes("Número de empleado"),"pide el número de empleado");
ok(et.indexOf("Número de empleado")<et.indexOf("Nombre del empleado"),"y va ANTES del nombre");
ok(et.includes("Acepto y me comprometo"),"muestra la carta responsiva del vale");
ok(!et.includes("Número de factura"),"no pide factura");
ok(bt(r3,"Registrar entrega").props.disabled===true,"no deja registrar en blanco");

console.log("\n── La talla solo se pregunta donde aplica ──");
const sel3=selects(r3)[selects(r3).length-1];
await act(async()=>{sel3.props.onChange({target:{value:"casco"}});});
ok(!plano(r3).includes("Ej. G, 29"),"el casco NO pide talla");
await act(async()=>{selects(r3)[selects(r3).length-1].props.onChange({target:{value:"calzado_casquillo"}});});
ok(plano(r3).includes("Ej. G, 29"),"el calzado SÍ pide talla");
await act(async()=>{r3.unmount();});

console.log("\n── ENTREGA completa, con firma ──");
localStorage.setItem("gpa_epp_draft_salida_almacen@gpa.com.mx",JSON.stringify(
  {suc:"Cancun",numEmpleado:"1042",empleado:"Edgar Eduardo Grajales Gamboa",
   reng:[{articuloId:"calzado_casquillo",cantidad:"1",talla:"29"},{articuloId:"playera",cantidad:"5",talla:"G"}],obs:""}));
llamadas.length=0;
let r4;await act(async()=>{r4=montar(M.EppForm,props("salida"));});
ok(bt(r4,"Registrar entrega").props.disabled===true,"sin firma no deja registrar");
const c=r4.root.findAllByType("canvas")[0];
await act(async()=>{c.props.onMouseDown({clientX:5,clientY:5,preventDefault(){}});});
await act(async()=>{c.props.onMouseUp();});
ok(bt(r4,"Registrar entrega").props.disabled!==true,"al firmar se habilita");
ok(plano(r4).includes("#1042"),"el vale muestra «#1042 · nombre» junto a la firma");
await act(async()=>{bt(r4,"Registrar entrega").props.onClick();});
await new Promise(x=>setTimeout(x,250));
const sal=llamadas.find(l=>l.metodo==="crear");
ok(!!sal&&sal.datos.movimiento==="salida","se envió la salida");
ok(sal&&sal.datos.numEmpleado==="1042","con el número de empleado");
ok(sal&&sal.datos.empleado.startsWith("Edgar"),"y el nombre");
ok(sal&&sal.datos.renglones[0].talla==="29","la talla viaja en el renglón");
ok(sal&&!!sal.datos.firma,"con la firma");
ok(sal&&String(sal.datos.aviso||"").includes("Acepto"),"y la carta responsiva queda guardada en el registro");
await act(async()=>{r4.unmount();});

console.log("\n── EXISTENCIAS ──");
mundo.saldos={Cedis:{casco:{entradas:12,salidas:4,saldo:8},playera:{entradas:30,salidas:31,saldo:-1}}};
let r5;await act(async()=>{r5=montar(M.EppSaldos,{cat,sucursalesUser:["Cedis"],showToast:()=>{}});});
await act(async()=>{await new Promise(x=>setTimeout(x,40));});
const ts=plano(r5);
ok(ts.includes("Casco"),"lista los artículos activos");
ok(!ts.includes("descontinuada"),"y NO los desactivados");
ok(ts.includes("existencia en negativo"),"avisa de las existencias en negativo");
ok(/"children":\[?"?8/.test(ts)||ts.includes(">8<")||ts.includes('"8"'),"muestra el saldo 8 del casco");
await act(async()=>{r5.unmount();});

console.log("\n── HISTORIAL ──");
const movs=[
  {id:"1",tipo_reg:"EPP",movimiento:"entrada",fecha:new Date().toISOString(),sucursal:"Cedis",factura:"A-1",proveedor:"Uniformes SA",renglones:[{articuloId:"casco",cantidad:12}]},
  {id:"2",tipo_reg:"EPP",movimiento:"salida",fecha:new Date().toISOString(),sucursal:"Cancun",numEmpleado:"1042",empleado:"Edgar G.",renglones:[{articuloId:"playera",cantidad:5,talla:"G"}]},
];
let r6;await act(async()=>{r6=montar(M.EppHistory,{items:movs,cat,onSelect:()=>{}});});
const th=plano(r6);
ok(th.includes("Factura A-1"),"la entrada se identifica por su factura");
ok(th.includes("#1042"),"la entrega por el número de empleado");
await act(async()=>{bt(r6,"Entradas").props.onClick();});
ok(plano(r6).includes("Factura A-1")&&!plano(r6).includes("#1042"),"el filtro «Entradas» deja solo entradas");
await act(async()=>{r6.unmount();});

console.log("\n── DETALLE / VALE PARA PDF ──");
let r7;await act(async()=>{r7=montar(M.EppDetail,{reg:{...movs[1],firma:"data:image/png;base64,F",aviso:"Acepto y me comprometo…"},cat,onBack:()=>{}});});
const td=plano(r7);
ok(td.includes("Vale de entrega de EPP"),"el PDF sale titulado como vale de entrega");
ok(td.includes("data-pdfsucursal")||JSON.stringify(r7.root.findAll(n=>n.props&&n.props["data-pdfsucursal"]).map(n=>n.props["data-pdfsucursal"])).includes("Cancun"),
   "le pasa la sucursal al PDF (para el domicilio del encabezado)");
ok(td.includes("Playera"),"lista el artículo con su nombre, no su clave");
ok(td.includes("Acepto y me comprometo"),"y reproduce la carta responsiva firmada");

console.log("\n── FACTURA: archivo o foto de galería, SOLO en este campo ──");
const S3PDF="https://gpa-ops-evidencias-prod.s3.amazonaws.com/EPP/abc123.pdf?AWSAccessKeyId=X&Expires=1&Signature=Y";
const S3JPG="https://gpa-ops-evidencias-prod.s3.amazonaws.com/EPP/abc123.jpg?AWSAccessKeyId=X";
ok(M.esPDF("data:application/pdf;base64,JVBERi0=")===true,"reconoce un PDF recién elegido");
ok(M.esPDF(S3PDF)===true,"reconoce un PDF ya guardado en S3 (ruta .pdf con firma)");
ok(M.esPDF(S3JPG)===false,"una foto .jpg no es PDF");
ok(M.esPDF("data:image/jpeg;base64,/9j/")===false,"una foto recién tomada no es PDF");
ok(M.esPDF(null)===false&&M.esPDF("")===false,"vacío no es PDF");
// El campo de factura: acepta PDF y NO fuerza la cámara
localStorage.removeItem("gpa_epp_draft_entrada_almacen@gpa.com.mx");
let r8;await act(async()=>{r8=montar(M.EppForm,props("entrada"));});
const fileFactura=r8.root.findAllByType("input").find(x=>x.props.type==="file");
ok(!!fileFactura,"la entrada tiene un campo de archivo");
ok(String(fileFactura.props.accept).includes("application/pdf"),"acepta PDF: "+fileFactura.props.accept);
ok(fileFactura.props.capture===undefined,"NO trae capture → el celular ofrece cámara, galería o archivos");
ok(plano(r8).includes("archivo o foto"),"el texto invita a elegir archivo o foto");
await act(async()=>{r8.unmount();});
// Los demás campos de foto NO cambian: el reporte de carga sigue abriendo la cámara
localStorage.removeItem("gpa_rep_draft_almacen@gpa.com.mx");
let r9;await act(async()=>{r9=montar(M.RepForm,{cat,items:[],session,rol:"operador",sucursalesUser:null,refrescar:async()=>{},showToast:()=>{},onDone:()=>{}});});
const filesRep=r9.root.findAllByType("input").filter(x=>x.props.type==="file");
ok(filesRep.length>0&&filesRep.every(x=>x.props.capture!==undefined),"los "+filesRep.length+" campos de foto del reporte de carga siguen con cámara directa");
ok(filesRep.every(x=>!String(x.props.accept).includes("pdf")),"y ninguno acepta PDF");
await act(async()=>{r9.unmount();});
// Vista previa: un PDF no se pinta como <img>
let r10;await act(async()=>{r10=montar(M.FotoCampo,{val:"data:application/pdf;base64,JVBERi0=",set:()=>{},label:"Factura",archivo:true});});
ok(plano(r10).includes("Archivo PDF cargado")&&r10.root.findAllByType("img").length===0,"un PDF elegido se muestra como archivo, no como imagen rota");
await act(async()=>{r10.unmount();});
let r11;await act(async()=>{r11=montar(M.FotoCampo,{val:"data:image/jpeg;base64,/9j/",set:()=>{},label:"Factura",archivo:true});});
ok(r11.root.findAllByType("img").length===1,"una foto sí se previsualiza como imagen");
await act(async()=>{r11.unmount();});
// Detalle: PDF → enlace para abrirlo; foto → imagen
const entPDF={id:"9",tipo_reg:"EPP",movimiento:"entrada",fecha:new Date().toISOString(),sucursal:"Cedis",factura:"A-9",fotoFactura:S3PDF,renglones:[{articuloId:"casco",cantidad:1}]};
let r12;await act(async()=>{r12=montar(M.EppDetail,{reg:entPDF,cat,onBack:()=>{}});});
const a=r12.root.findAllByType("a").find(x=>x.props.href===S3PDF);
ok(!!a&&a.props.target==="_blank","el detalle ofrece «Abrir factura (PDF)» en pestaña nueva");
ok(r12.root.findAllByType("img").length===0,"y no intenta pintar el PDF como imagen");
ok(plano(r12).includes("Factura adjunta como archivo PDF"),"el PDF impreso deja constancia de la factura adjunta");
await act(async()=>{r12.unmount();});
let r13;await act(async()=>{r13=montar(M.EppDetail,{reg:{...entPDF,fotoFactura:S3JPG},cat,onBack:()=>{}});});
ok(r13.root.findAllByType("img").some(i=>i.props.src===S3JPG),"una factura en foto sí se muestra como imagen");
await act(async()=>{r13.unmount();});
console.log("\n══ fin ══");
})();
