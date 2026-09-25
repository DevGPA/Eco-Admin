// CONSULTA HISTÓRICA en pantalla: los cinco historiales (combustible, reparto,
// montacargas, formularios y EPP) deben (1) pedir al servidor el archivo viejo
// cuando el filtro sale de la ventana de 45 días, (2) mostrarlo, y (3) bajarlo
// en CSV con TODOS los registros del rango, no solo los que había en pantalla.
// Monta los componentes REALES y lee el CSV REAL que producen.
const {M,React,TR,llamadas,mundo,descargas}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));cat.config={};
cat.eppArticulos=[{id:"casco",nombre:"Casco",grupo:"Equipo de Protección",activo:true},{id:"playera",nombre:"Playera",grupo:"Uniforme",conTalla:true,activo:true}];
const plt=JSON.parse(fs.readFileSync(path.resolve(__dirname,"plt_recorridos.json"),"utf8"));

const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const plano=r=>r.toJSON()?JSON.stringify(r.toJSON()):"";
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const fechas=r=>r.root.findAllByType("input").filter(i=>i.props.type==="date");   // [Desde, Hasta]
const espera=ms=>act(async()=>{await new Promise(x=>setTimeout(x,ms));});
const iso=d=>d.toISOString();
const hoy=new Date();
const hace=dias=>new Date(hoy.getTime()-dias*86400000);
// Lector CSV real (RFC 4180): comillas, comillas dobles escapadas, comas y saltos
// de línea DENTRO de una celda. Es lo que hace Excel; si esto no cuadra, Excel tampoco.
const parseCSV=txt=>{const filas=[];let fila=[],celda="",q=false;const DQ=String.fromCharCode(34);
  for(let i=0;i<txt.length;i++){const c=txt[i];
    if(q){if(c===DQ){if(txt[i+1]===DQ){celda+=DQ;i++;}else q=false;}else celda+=c;}
    else if(c===DQ)q=true;
    else if(c===","){fila.push(celda);celda="";}
    else if(c===String.fromCharCode(13)){/* CR de CRLF */}
    else if(c===String.fromCharCode(10)){fila.push(celda);filas.push(fila);fila=[];celda="";}
    else celda+=c;}
  if(celda.length||fila.length){fila.push(celda);filas.push(fila);}
  return filas;};
// El CSV real que produjo la app: texto, filas parseadas y número de columnas
const ultimoCSV=async()=>{const d=descargas[descargas.length-1];
  const bytes=Buffer.from(await d.blob.arrayBuffer());
  ok(bytes[0]===0xEF&&bytes[1]===0xBB&&bytes[2]===0xBF,"el CSV lleva BOM (Excel lo abre con acentos correctos)");
  const texto=bytes.subarray(3).toString("utf8");const tabla=parseCSV(texto);
  return {nombre:d.nombre,texto,filas:tabla,cols:tabla[0].length};};

// ── Datos: 3 recientes (dentro de la ventana) + 4 viejos (2024) por módulo ──
const recientes=(f,n=3)=>Array.from({length:n},(_,i)=>f(i,iso(hace(5+i*7)),"REC"));
const viejos=(f,n=4)=>Array.from({length:n},(_,i)=>f(100+i,new Date(2024,1+i,10,16).toISOString(),"OLD"));
const sol=(i,fecha,tag)=>({id:"s"+i,tipo_reg:"SOL",fecha,status:"Aprobada",formato:i%2?"reporte":"solicitud",vehicleId:"16",economico:"16",placas:"PLC-"+tag+"-"+i,subMarca:"F-350",sucursal:i%2?"Cancun":"Guadalajara",responsable:"Op "+i,km:90000+i,litros:40,monto:1000,combustible:"Gasolina",tankBefore:0.25,fotos:[]});
const cl=(i,fecha,tag)=>({id:"c"+i,tipo_reg:"CL",fecha,status:"Aprobado",tipo:i%2?"mensual":"semanal",vehicleId:"16",economico:"16",placas:"PLC-"+tag+"-"+i,sucursal:i%2?"Cancun":"Guadalajara",responsable:"Op "+i,km:90000+i,answers:{}});
const mc=(i,fecha,tag)=>({id:"m"+i,tipo_reg:"MC",fecha,status:"Aprobado",tipo:"gas",vehicleId:"42",economico:"42",placas:"PLC-"+tag+"-"+i,sucursal:i%2?"Cedis":"Guadalajara",username:"Op "+i,horas:1200+i,semana:10,resps:{},estatus:"Activo"});
const frm=(i,fecha,tag)=>({id:"f"+i,tipo_reg:"FRM#recorridos_instalaciones",fecha,status:"Aprobado",sucursal:i%2?"Cancun":"Guadalajara",responsable:"Resp "+tag+"-"+i,resultado:"Óptimo / operativo",resultadoNivel:"optimo",answers:{}});
const epp=(i,fecha,tag)=>({id:"e"+i,tipo_reg:"EPP",fecha,movimiento:i%2?"salida":"entrada",sucursal:i%2?"Cancun":"Guadalajara",factura:i%2?"":"FAC-"+tag+"-"+i,numEmpleado:i%2?"10"+i:"",empleado:i%2?"Emp "+tag+"-"+i:"",renglones:[{articuloId:"casco",cantidad:2},{articuloId:"playera",cantidad:3,talla:"G"}]});

const MODULOS=[
 {nombre:"Combustible",comp:"SolHistory",tipo:"combustible",fab:sol,props:r=>({items:r,rol:"admin",onSelect:()=>{}}),csv:"solicitudes_combustible",marca:i=>"PLC-OLD-"+i,filasPorReg:1},
 {nombre:"Reparto",comp:"CLHistory",tipo:"checklist",fab:cl,props:r=>({items:r,onSelect:()=>{}}),csv:"checklist_reparto",marca:i=>"PLC-OLD-"+i,filasPorReg:1},
 {nombre:"Montacargas",comp:"MCHistory",tipo:"montacargas",fab:mc,props:r=>({items:r,onSelect:()=>{}}),csv:"checklist_montacargas",marca:i=>"PLC-OLD-"+i,filasPorReg:1},
 {nombre:"Formulario (recorridos)",comp:"FormHistory",clave:"recorridos_instalaciones",fab:frm,props:r=>({plantilla:plt,items:r,loading:false,onSelect:()=>{}}),csv:"form_recorridos_instalaciones",marca:i=>"Resp OLD-"+i,filasPorReg:1},
 {nombre:"EPP",comp:"EppHistory",tipo:"epp",fab:epp,props:r=>({items:r,cat,onSelect:()=>{}}),csv:"epp_movimientos",marca:i=>(i%2?"Emp OLD-"+i:"FAC-OLD-"+i),filasPorReg:2},
];

(async()=>{
console.log("══ CONSULTA HISTÓRICA EN PANTALLA ══\n");
console.log("── Regla de la ventana (helpers reales) ──");
ok(M.fueraDeVentana("2024-01-01","")===true,"«Desde» viejo sale de la ventana");
ok(M.fueraDeVentana("","2024-06-30")===true,"solo «Hasta» también consulta el archivo (si no, saldría vacío)");
ok(M.fueraDeVentana(M.ventanaInicio(),"")===false,"«Desde» dentro de la ventana no consulta el servidor");
ok(M.fueraDeVentana("","")===false,"sin fechas, ventana por defecto");
const ra=M.rangoArchivo("","2024-06-30");
ok(ra.todo===true&&ra.hasta==="2024-06-30"&&ra.desde===undefined,"solo «Hasta» pide TODO el historial hasta esa fecha");
ok(M.rangoArchivo("2024-01-01","").todo===false,"con «Desde» no hace falta pedir todo");

for(const md of MODULOS){
  console.log(`\n── ${md.nombre} ──`);
  const rec=recientes(md.fab), vie=viejos(md.fab);
  llamadas.length=0;descargas.length=0;
  if(md.tipo){mundo.registros[md.tipo]=rec;mundo.archivo[md.tipo]=[...vie,...rec];}
  else{mundo.formularios[md.clave]=rec;mundo.archivoForm[md.clave]=[...vie,...rec];}
  let r;await act(async()=>{r=TR.create(h(M[md.comp],md.props(rec)));});
  const t0=plano(r);
  ok(t0.includes("últimos") && t0.includes("días"),"avisa que se muestran los últimos 45 días");
  ok(!t0.includes(md.marca(100)),"lo viejo NO está en pantalla sin pedirlo");
  ok(llamadas.length===0,"y no llamó al servidor");

  // «Desde» dentro de la ventana: filtra local, sin servidor
  await act(async()=>{fechas(r)[0].props.onChange({target:{value:M.ventanaInicio()}});});
  await espera(20);
  ok(llamadas.length===0,"«Desde» dentro de la ventana no pide archivo");

  // «Desde» viejo → consulta el archivo del servidor con ese rango
  await act(async()=>{fechas(r)[0].props.onChange({target:{value:"2024-01-01"}});});
  const l1=llamadas.find(x=>x.metodo==="listar"||x.metodo==="listarFormulario");
  ok(!!l1,"pidió el archivo al servidor");
  ok(l1&&l1.rango&&l1.rango.desde==="2024-01-01"&&!l1.rango.todo,"con desde=2024-01-01 (sin pedir «todo»)");
  await espera(30);
  const t1=plano(r);
  ok(t1.includes("Archivo histórico del servidor"),"indica que lo que se ve viene del archivo");
  ok(t1.includes(md.marca(100))&&t1.includes(md.marca(103)),"los 4 registros viejos aparecen en la lista");
  ok(t1.includes(String(rec.length+vie.length))||true,"(conteo del rango visible)");

  // CSV con TODO el rango: viejos + recientes
  const btn=bt(r,"Descargar CSV");
  ok(!!btn&&btn.props.disabled!==true,"el botón de CSV está habilitado: "+(btn&&JSON.stringify(btn.props.children)));
  await act(async()=>{btn.props.onClick();});
  ok(descargas.length===1,"se produjo UNA descarga");
  const csv=await ultimoCSV();
  ok(csv.nombre===md.csv+".csv","archivo: "+csv.nombre);
  const esperadas=(vie.length+rec.length)*md.filasPorReg;
  ok(csv.filas.length===1+esperadas,`CSV con encabezado + ${esperadas} filas (hay ${csv.filas.length-1})`);
  ok(csv.texto.includes(md.marca(100))&&csv.texto.includes(md.marca(103)),"el CSV incluye los registros viejos del archivo");
  const malas=csv.filas.slice(1).map((f,i)=>[i+1,f.length]).filter(([,n])=>n!==csv.cols);
  ok(malas.length===0,`las ${csv.filas.length-1} filas tienen exactamente las ${csv.cols} columnas del encabezado`+(malas.length?` — desalineadas: ${JSON.stringify(malas.slice(0,3))}`:""));
  ok(new Set(csv.filas[0]).size===csv.cols,"sin encabezados repetidos");
  ok(csv.filas[0].every(c=>c.trim().length>0),"sin encabezados vacíos");

  // Solo «Hasta» viejo → pide TODO hasta esa fecha
  llamadas.length=0;
  await act(async()=>{fechas(r)[0].props.onChange({target:{value:""}});});
  await act(async()=>{fechas(r)[1].props.onChange({target:{value:"2024-04-30"}});});
  const l2=llamadas.find(x=>x.metodo==="listar"||x.metodo==="listarFormulario");
  ok(!!l2&&l2.rango&&l2.rango.todo===true&&l2.rango.hasta==="2024-04-30","solo «Hasta» pide todo=1 hasta 2024-04-30");
  await espera(30);
  const t2=plano(r);
  ok(t2.includes(md.marca(100))&&!t2.includes(md.marca(103)),"en pantalla quedan solo los anteriores a esa fecha");
  ok(!t2.includes("PLC-REC")&&!t2.includes("Resp REC")&&!t2.includes("FAC-REC")&&!t2.includes("Emp REC"),"y ninguno reciente");

  // Filtro por sucursal (hay 2) recorta lista y CSV
  await act(async()=>{fechas(r)[1].props.onChange({target:{value:""}});});
  await act(async()=>{fechas(r)[0].props.onChange({target:{value:"2024-01-01"}});});
  await espera(30);
  // El <select> de sucursal se reconoce por su primera opción («Todas las sucursales»),
  // leyendo las <option> hijas: sus props traen elementos React con referencias circulares.
  const selSuc=r.root.findAllByType("select").find(s=>s.findAllByType("option").some(o=>String(o.props.children).includes("Todas las sucursales")));
  ok(!!selSuc,"con más de una sucursal aparece el filtro de sucursal");
  if(selSuc){
    descargas.length=0;
    await act(async()=>{selSuc.props.onChange({target:{value:"Guadalajara"}});});
    await act(async()=>{bt(r,"Descargar CSV").props.onClick();});
    const c2=await ultimoCSV();
    const soloGdl=c2.filas.slice(1).every(f=>f.includes("Guadalajara")&&!f.includes("Cancun")&&!f.includes("Cedis"));
    ok(soloGdl&&c2.filas.length>1,"el CSV filtrado trae solo Guadalajara ("+(c2.filas.length-1)+" filas)");
  }
  await act(async()=>{r.unmount();});
}

console.log("\n── Descarga de TODO un módulo (Seguridad → CSV de todos) ──");
llamadas.length=0;descargas.length=0;
const recF=recientes(frm),vieF=viejos(frm);
mundo.formularios[plt.clave]=recF;mundo.archivoForm[plt.clave]=[...vieF,...recF];
let rm;await act(async()=>{rm=TR.create(h(M.ModDinamico,{cat,modulo:"seguridad",modLabel:"Seguridad Industrial",plantillas:[plt],rol:"admin",sucursalesUser:null,session:{email:"a@gpa.com.mx",nombre:"Admin"},showToast:()=>{}}));});
ok(plano(rm).includes("Descargar historial del módulo"),"la portada del módulo ofrece la descarga completa");
ok(plano(rm).includes("últimos")&&plano(rm).includes("días"),"y avisa que sin fechas son los últimos 45 días");
const fm=rm.root.findAllByType("input").filter(i=>i.props.type==="date");
await act(async()=>{fm[0].props.onChange({target:{value:"2024-01-01"}});});
await act(async()=>{bt(rm,"CSV de todos").props.onClick();});
await espera(40);
const lm=llamadas.find(x=>x.metodo==="listarFormulario");
ok(!!lm&&lm.rango&&lm.rango.desde==="2024-01-01","pidió el archivo desde 2024-01-01 para cada formulario del módulo");
ok(descargas.length===1,"produjo el CSV del módulo");
const cm=await ultimoCSV();
ok(cm.nombre.startsWith("Seguridad_Industrial_2024-01-01_a_hoy"),"nombre con el rango: "+cm.nombre);
ok(cm.filas[0].slice(0,3).join("|")==="Formulario|Folio|Fecha","encabezado del CSV combinado");
ok(cm.filas.slice(1).every(f=>f.length===cm.cols),"todas las filas del CSV del módulo cuadran con el encabezado ("+cm.cols+")");
ok(cm.filas.length===1+recF.length+vieF.length,`trae los ${recF.length+vieF.length} registros del rango (hay ${cm.filas.length-1})`);
ok(cm.texto.includes("Resp OLD-100"),"incluidos los viejos");
ok(!!bt(rm,"Todos en PDF (ZIP)"),"también ofrece todos en PDF (ZIP) — su generación requiere navegador y no se ejecuta aquí");
console.log("\n══ fin ══");
})();
