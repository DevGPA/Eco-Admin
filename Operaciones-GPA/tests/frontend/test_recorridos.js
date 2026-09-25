// Formulario «Recorridos en instalaciones»: se monta el FormDinamico REAL con la
// plantilla que genera seed/plantilla_recorridos.py y se llena de principio a fin.
// Es el paso que faltó con el botiquín: que además de verse, se ENVÍE.
const {M,React,TR,llamadas}=require("./montar.js");
const fs=require("fs");const path=require("path");const act=TR.act;const h=React.createElement;
const cat=JSON.parse(fs.readFileSync(path.resolve(__dirname,"../../seed/catalogos.json"),"utf8"));cat.config={};
const plt=JSON.parse(fs.readFileSync(path.resolve(__dirname,"plt_recorridos.json"),"utf8"));
const session={email:"seguridad@gpa.com.mx",nombre:"Coordinador SH",rol:"operador"};
let enviado=false;
const props={plantilla:plt,cat,rol:"operador",sucursalesUser:null,session,sinBorrador:true,
  showToast:()=>{},onDone:()=>{enviado=true;}};
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const bt=(r,t)=>r.root.findAllByType("button").find(b=>JSON.stringify(b.props.children||"").includes(t));
const plano=r=>JSON.stringify(r.toJSON());
const esOpts=r=>r.root.findAll(n=>n.props&&String(n.props.className||"").startsWith("es-opt")&&n.props.onClick);
const semaforo=r=>{const n=r.root.findAll(x=>x.props&&String(x.props.className||"").startsWith("score-bar"))[0];return n?String(n.props.className):null;};
const puntos=plt.secciones.flatMap(s=>s.items).filter(i=>i.type==="escala");
// El <canvas> de la firma necesita un doble: sin él, sigRef.current es null y
// el botón «Enviar» se queda deshabilitado (requiereFirma: true).
const lienzo={getContext:()=>({beginPath(){},moveTo(){},lineTo(){},stroke(){},clearRect(){}}),
  toDataURL:()=>"data:image/png;base64,FIRMA",
  getBoundingClientRect:()=>({left:0,top:0,width:340,height:120}),width:340,height:120};
const montar=()=>TR.create(h(M.FormDinamico,props),{createNodeMock:el=>el.type==="canvas"?lienzo:null});
const firmar=async r=>{const c=r.root.findAllByType("canvas")[0];
  await act(async()=>{c.props.onMouseDown({clientX:10,clientY:10,preventDefault(){}});});
  await act(async()=>{c.props.onMouseUp();});};

const llenarTexto=async r=>{for(const n of r.root.findAllByType("input").filter(x=>x.props.onChange&&!x.props.disabled&&x.props.type!=="file")){
  await act(async()=>{n.props.onChange({target:{value:"CEDIS · Av. Ejemplo 100"}});});}};

// Recorre el asistente sección por sección respondiendo lo que toca.
// elegir(item) devuelve 0=Cumple · 1=No cumple · 2=N/A.
const recorrer=async(r,elegir,alLlegar)=>{
  await llenarTexto(r);                                   // paso 0: sucursal
  await act(async()=>{bt(r,"Siguiente").props.onClick();});
  for(const sec of plt.secciones){
    await llenarTexto(r);                                 // domicilio, si la sección lo trae
    const escalas=sec.items.filter(i=>i.type==="escala");
    let cur=0;
    for(const it of escalas){
      const bloque=esOpts(r).slice(cur,cur+it.opts.length);
      await act(async()=>{bloque[elegir(it)].props.onClick();});
      cur+=it.opts.length;
    }
    if(alLlegar)await alLlegar(sec,r);
    await act(async()=>{bt(r,"Siguiente").props.onClick();});
  }
};

(async()=>{
console.log("══ RECORRIDOS EN INSTALACIONES ══\n");
console.log("── La plantilla ──");
ok(puntos.length===36,"36 puntos de revisión");
ok(plt.modulo==="seguridad","módulo Seguridad");
ok(plt.secciones.length===6,"6 secciones → 8 pasos con el motor");
ok(plt.secciones[0].items[0].id==="domicilio","el domicilio va con la primera sección, sin robar un paso");

let r;await act(async()=>{r=montar();});
ok(plano(r).includes("Sucursal"),"el paso 1 pide la sucursal");
await llenarTexto(r);
await act(async()=>{bt(r,"Siguiente").props.onClick();});

console.log("\n── El criterio de revisión se ve en pantalla ──");
const t1=plano(r);
ok(t1.includes("Domicilio"),"la primera sección pide el domicilio");
ok(t1.includes("es-ayuda"),"cada punto trae su línea de criterio");
ok(t1.includes("Sin obstrucción en ningún momento del día"),"con el texto del Excel (pasillos libres)");
ok(t1.includes("Móviles: En condiciones de uso"),"y conserva el criterio de dos líneas (escaleras)");

console.log("\n── No deja avanzar con puntos sin responder ──");
await act(async()=>{bt(r,"Siguiente").props.onClick();});
ok(plano(r).includes("Faltan"),"avisa cuántas respuestas faltan");
ok(plano(r).includes("Pasillos libres"),"y se queda en la misma sección");
await act(async()=>{r.unmount();});

console.log("\n── Recorrido TODO en orden (Cumple) ──");
enviado=false;llamadas.length=0;
let r1;await act(async()=>{r1=montar();});
await recorrer(r1,()=>0);
ok(!!bt(r1,"Enviar"),"se recorrieron los 8 pasos hasta el envío");
const s1=semaforo(r1);
ok(!!s1&&s1.includes("optimo"),"semáforo VERDE — clase: "+s1);
ok(plano(r1).includes("72/72"),"el puntaje cuenta los 36 puntos (2 c/u = 72/72)");

console.log("\n── ENVIAR (lo que falló con el botiquín) ──");
ok(bt(r1,"Enviar").props.disabled===true,"sin firma, «Enviar» está deshabilitado");
await firmar(r1);
ok(bt(r1,"Enviar").props.disabled!==true,"al firmar se habilita");
await act(async()=>{bt(r1,"Enviar").props.onClick();});
await new Promise(x=>setTimeout(x,300));
const env=llamadas.find(l=>l.metodo==="crearFormulario");
ok(!!env,"se envió el formulario");
ok(env&&env.clave==="recorridos_instalaciones","con la clave correcta");
const resp=env?Object.keys(env.datos.answers).filter(k=>!k.includes("__")):[];
ok(resp.length===37,"llegan los 36 puntos + el domicilio ("+resp.length+"), más sus notas");
ok(env&&env.datos.resultado==="Óptimo / operativo","resultado: "+(env&&env.datos.resultado));
ok(env&&env.datos.sucursal,"con sucursal: "+(env&&env.datos.sucursal));
ok(enviado===true,"y regresa al historial");
await act(async()=>{r1.unmount();});

console.log("\n── Un punto en «No cumple» ──");
let r2;await act(async()=>{r2=montar();});
let vioEvidencia=false;
await recorrer(r2,it=>it.id==="extintores"?1:0,async(sec,rr)=>{
  if(sec.items.some(i=>i.id==="extintores")&&plano(rr).includes("Evidencia del daño"))vioEvidencia=true;});
ok(vioEvidencia,"pide foto y descripción del punto que no cumple");
const s2=semaforo(r2);
ok(!!s2&&s2.includes("fuera"),"semáforo ROJO — clase: "+s2);
const hall=M.hallazgosSecs(plt.secciones,{answers:{extintores:1}});
ok(hall.some(x=>x.label==="Extintores"),"«Extintores» entra en los puntos en mal estado del PDF");
await act(async()=>{r2.unmount();});

console.log("\n── Todo marcado N/A ──");
let r3;await act(async()=>{r3=montar();});
let pidioEvidencia=false;
await recorrer(r3,()=>2,async(sec,rr)=>{if(plano(rr).includes("Evidencia del daño"))pidioEvidencia=true;});
ok(!pidioEvidencia,"N/A nunca pide evidencia");
const s3=semaforo(r3);
ok(!!s3&&s3.includes("optimo"),"y no manda la instalación a fuera de servicio — clase: "+s3);
console.log("\n══ fin ══");
})();
