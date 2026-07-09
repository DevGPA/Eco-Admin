/* viaticos-app.jsx — Recorrido de DISEÑO (10 pasos POL-TE01).
   Cargado por index.html vía Babel standalone. Es la "maqueta maestra"
   del flujo; el módulo operativo (login, bandeja, alta y aprobación contra
   AWS) vive en index.html. Aquí se expone window.ViaticosDemo. */
const { useState, useEffect, useRef } = React;

/* ═══════════════════════════════════════════════════════════════════════════
   GPA ViaticOS — Demo Integral Unificada
   10 pasos con cotizador de vuelos y autobús integrado
   Identidad corporativa GPA · POL-TE01 completa
   ═══════════════════════════════════════════════════════════════════════════ */

/* ─── PALETA GPA ──────────────────────────────────────────────────────────── */
const C = {
  navy:"#1B3A5C", navyMid:"#2A4F7A", blue:"#2E6DA4", blueSoft:"#EBF4FB",
  teal:"#5BB8C4", tealDark:"#3D9BAA", tealLight:"#A8D8DC", tealXL:"#E6F6F8",
  bgPage:"#F2F5F7", bgCard:"#FFFFFF", bgSurf:"#F8FAFB",
  border:"#D4DCE4", borderMid:"#B8C5D0",
  ink:"#1A2533", inkMid:"#3D4A5C", inkLight:"#6B7D8E", inkFaint:"#A0ADB8",
  green:"#1A7A4A", greenBg:"#E8F5EE", greenBdr:"#A8D5BC",
  amber:"#B45309", amberBg:"#FEF3C7", amberBdr:"#F6D860",
  red:"#C0392B", redBg:"#FEE8E6", redBdr:"#F4A09A",
  gold:"#C9A84C",
  /* Aerolíneas */
  am:"#E31837", volaris:"#7B2D8B", viva:"#FF5F00",
  /* Autobuses */
  etn:"#003082", pp:"#CC1B2A", eb:"#1A7A4A", tap:"#E87722",
};
const F = { display:"'Georgia',serif", body:"'Helvetica Neue',Helvetica,sans-serif", mono:"'Courier New',monospace" };
const fmt = n => `$${Number(n).toLocaleString("es-MX",{minimumFractionDigits:0})}`;
const fmtD = n => `$${Number(n).toLocaleString("es-MX",{minimumFractionDigits:2})}`;
const fmtMin = m => { const h=Math.floor(m/60),min=m%60; return h>0?`${h}h${min>0?" "+min+"m":""}`:min+"m"; };
const MAX_TRASLADO = 240;

/* ─── POLÍTICA POL-TE01 ──────────────────────────────────────────────────── */
const POL = {
  vuelos:{ "GDL-MEX":{r:3500,s:1750}, "GDL-MTY":{r:3100,s:1550}, "GDL-CUN":{r:5100,s:2550},
           "GDL-SJD":{r:3700,s:1850}, "GDL-PVR":{r:1400,s:700} },
  autobus:{ "GDL-PVR":{r:1400,s:700}, "GDL-AGS":{r:480,s:240}, "GDL-COL":{r:380,s:190},
            "GDL-MOR":{r:520,s:260}, "GDL-SLP":{r:700,s:350}, "GDL-QRO":{r:860,s:430},
            "GDL-TEP":{r:380,s:190}, "GDL-ZMO":{r:560,s:280} },
  hospedaje:{ cancun:1270, mexico:1300, guadalajara:994, cabos:1300, monterrey:1249, vallarta:1597 },
  alimentos:{ nacional_1p:300, largo:200, grupo:175, sin_cfdi:100, extj_usd:30 },
  representacion:{ max_p:1250, max_total:5000 },
  comprobacion:{ dias:6, pen:[{s:1,p:25},{s:2,p:50},{s:3,p:75},{s:4,p:100}] },
  anticip_dias:{ avion_nac:15, avion_ext:60, bus_nac:7 },
  aprobacion_dg: 10000,
};

/* ─── ACTORES ─────────────────────────────────────────────────────────────── */
const EMP = { name:"Carlos Mendoza", area:"Ventas", rol:"Ejecutivo Sr.", av:"CM" };
const SUP = { name:"Patricia Ruiz", rol:"Dir. Comercial", av:"PR" };
const FIN = { name:"Ana Torres, CPC", rol:"Gte. Finanzas", av:"AT" };

const VIAJE = { folio:"VIA-2025-0341", destino:"Monterrey, N.L.", destCode:"MTY", motivo:"Cierre contrato Q2 · Grupo Alfa",
  ida:"Lun 5 Mayo 2025", ret:"Mié 7 Mayo 2025", dias:3, tipo:"Nacional", anticipo:8500, presupuesto:9200 };

/* ─── VUELOS DB ──────────────────────────────────────────────────────────── */
const AIRLINES = {
  AM:{ name:"Aeroméxico", color:C.am, bg:"#FEE8EA" },
  Y4:{ name:"Volaris",    color:C.volaris, bg:"#F3E8F8" },
  VB:{ name:"VivaAerobus",color:C.viva, bg:"#FFF0E8" },
};
const FLIGHTS = [
  { id:"AM502",al:"AM",sal:"07:00",lleg:"08:25",dur:85,total:170,precio_s:1280,precio_r:2560,esc:false,asientos:18 },
  { id:"Y4612",al:"Y4",sal:"08:20",lleg:"09:50",dur:90,total:175,precio_s:780,precio_r:1560,esc:false,asientos:12 },
  { id:"VB420",al:"VB",sal:"06:45",lleg:"08:15",dur:90,total:175,precio_s:720,precio_r:1440,esc:false,asientos:28 },
  { id:"AM714",al:"AM",sal:"15:30",lleg:"17:00",dur:90,total:175,precio_s:1540,precio_r:3080,esc:false,asientos:5 },
  { id:"Y4820",al:"Y4",sal:"19:15",lleg:"20:45",dur:90,total:175,precio_s:950,precio_r:1900,esc:false,asientos:7 },
];

/* ─── AUTOBUSES DB (para PVR como ejemplo de ruta corta) ─────────────────── */
const BUSLINES = {
  ETN:{ name:"ETN Turistar",  color:C.etn, bg:"#E8EEFA" },
  PP: { name:"Primera Plus",  color:C.pp,  bg:"#FCE8EA" },
  EB: { name:"Estrella Blanca",color:C.eb, bg:"#E8F5EE" },
  TAP:{ name:"TAP",           color:C.tap, bg:"#FEF0E6" },
};
const BUSES = [
  { id:"PP-1201",ln:"PP",dest:"PVR",sal:"06:00",lleg:"09:30",dur:210,total:270,precio_s:385,precio_r:770,dir:true,clase:"Primera Plus",asientos:28 },
  { id:"ETN-804",ln:"ETN",dest:"PVR",sal:"07:30",lleg:"11:15",dur:225,total:285,precio_s:520,precio_r:1040,dir:true,clase:"Ejecutivo",asientos:24 },
  { id:"TAP-305",ln:"TAP",dest:"PVR",sal:"08:00",lleg:"11:30",dur:210,total:270,precio_s:310,precio_r:620,dir:true,clase:"Primera",asientos:36 },
  { id:"EB-620",ln:"EB",dest:"PVR",sal:"05:00",lleg:"09:30",dur:270,total:330,precio_s:280,precio_r:560,dir:false,clase:"Primera",asientos:44,parada:"Compostela" },
];

/* ─── TICKETS COMPROBACIÓN ───────────────────────────────────────────────── */
const TICKETS = [
  { id:1,com:"Aeroméxico GDL→MTY→GDL",tipo:"Transporte Aéreo",monto:3240,iva:0,fecha:"05/05",cfdi:true,st:"ok",riesgo:2,ocr:98,pol:"✓ Dentro del límite vuelo GDL-MTY ($3,100 redondo)",ev:"Factura + itinerario" },
  { id:2,com:"Hotel Quality Inn MTY",tipo:"Hospedaje",monto:2498,iva:399.68,fecha:"05–06/05",cfdi:true,st:"ok",riesgo:4,ocr:97,pol:`✓ 2 noches × $1,249. Límite MTY: $${POL.hospedaje.monterrey}/noche`,ev:"Factura fiscal GPA" },
  { id:3,com:"Rest. La Catedral MTY",tipo:"Representación",monto:1850,iva:240.50,fecha:"05/05",cfdi:true,st:"revision",riesgo:58,ocr:93,pol:`⚠ $462/persona. Excede límite viaje ($300). Aplica representación art 4.38 ($${POL.representacion.max_p}/p). Requiere lista asistentes.`,nota:"Cena cierre con 3 reps Grupo Alfa.",ev:"Factura + lista asistentes" },
  { id:4,com:"Uber Business MTY",tipo:"Transporte Local",monto:380,iva:60.80,fecha:"05–07/05",cfdi:true,st:"ok",riesgo:6,ocr:99,pol:"✓ Trayectos autorizados art 4.29. < $350 por traslado.",ev:"Recibos Uber app" },
  { id:5,com:"Starbucks Centro MTY",tipo:"Alimentos",monto:185,iva:29.60,fecha:"07/05",cfdi:false,st:"rechazado",riesgo:82,ocr:71,pol:`✗ Sin CFDI (art 4.21). Máx sin factura: $${POL.alimentos.sin_cfdi} solo en casos extraordinarios.`,ev:"Ticket caja — insuficiente" },
];
const totalAprobado = TICKETS.filter(t=>t.st!=="rechazado").reduce((s,t)=>s+t.monto,0);

/* ═══════════════════════════════════════════════════════════════════════════
   COMPONENTES BASE
   ═══════════════════════════════════════════════════════════════════════════ */
function Avatar({i,s=32,c=C.teal}){return<div style={{width:s,height:s,borderRadius:"50%",background:`${c}20`,border:`1.5px solid ${c}50`,display:"flex",alignItems:"center",justifyContent:"center",color:c,fontSize:s*.34,fontFamily:F.body,fontWeight:700,flexShrink:0}}>{i}</div>}
function Chip({l,c,bg,bd}){return<span style={{display:"inline-flex",padding:"2px 8px",borderRadius:3,fontSize:10,fontFamily:F.body,fontWeight:700,letterSpacing:".05em",textTransform:"uppercase",color:c,background:bg||`${c}14`,border:`1px solid ${bd||c+"40"}`}}>{l}</span>}
function Cd({children,style={}}){return<div style={{background:C.bgCard,border:`1px solid ${C.border}`,borderRadius:8,padding:"18px 20px",...style}}>{children}</div>}
function Info({children,c=C.teal,style={}}){return<div style={{background:`${c}0D`,border:`1px solid ${c}30`,borderRadius:8,padding:"14px 16px",...style}}>{children}</div>}
function Bar({v,m,c=C.teal}){const p=Math.min(100,v/m*100);return<div style={{background:C.bgSurf,borderRadius:4,height:5,overflow:"hidden",border:`1px solid ${C.border}`}}><div style={{width:`${p}%`,height:"100%",background:c,borderRadius:4,transition:"width .8s"}}/></div>}
function Head({n,t,title,sub,role,rc=C.teal}){return<div style={{marginBottom:24}}><div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}><div style={{background:C.navy,color:C.tealLight,fontFamily:F.mono,fontSize:10,fontWeight:700,padding:"3px 8px",borderRadius:3,letterSpacing:".1em"}}>PASO {String(n).padStart(2,"0")} / {String(t).padStart(2,"0")}</div><div style={{flex:1,height:".5px",background:C.border}}/><Chip l={role} c={C.navy} bg={`${rc}18`} bd={`${rc}40`}/></div><h2 style={{fontFamily:F.display,fontSize:24,color:C.ink,margin:0,fontWeight:400,letterSpacing:"-.02em"}}>{title}</h2>{sub&&<p style={{fontFamily:F.body,fontSize:12,color:C.inkLight,margin:"4px 0 0"}}>{sub}</p>}</div>}
function Btn({children,onClick,disabled,small}){const[h,setH]=useState(false);return<button onClick={disabled?undefined:onClick} onMouseEnter={()=>setH(true)} onMouseLeave={()=>setH(false)} style={{padding:small?"7px 16px":"11px 24px",background:disabled?C.bgSurf:h?C.navyMid:C.navy,color:disabled?C.inkFaint:C.tealLight,border:`1px solid ${disabled?C.border:C.navy}`,borderRadius:6,fontFamily:F.body,fontSize:small?11:13,fontWeight:700,cursor:disabled?"default":"pointer",transition:"all .15s",letterSpacing:".02em"}}>{children}</button>}
function Ghost({children,onClick,danger}){return<button onClick={onClick} style={{padding:"9px 18px",background:"transparent",color:danger?C.red:C.inkMid,border:`1px solid ${danger?C.redBdr:C.border}`,borderRadius:6,fontFamily:F.body,fontSize:12,fontWeight:700,cursor:"pointer"}}>{children}</button>}
function useTyp(text,spd=12,run=true){const[o,setO]=useState("");useEffect(()=>{if(!run)return;setO("");let i=0;const iv=setInterval(()=>{if(i<text.length)setO(text.slice(0,++i));else clearInterval(iv)},spd);return()=>clearInterval(iv)},[text,run]);return o}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 1 — SOLICITUD
   ═══════════════════════════════════════════════════════════════════════════ */
function P1({onNext}){
  const[st,setSt]=useState("idle");
  const go=()=>{setSt("loading");setTimeout(()=>setSt("done"),1800)};
  return<div>
    <Head n={1} t={10} title="Solicitud de Viaje" sub={`${EMP.name} inicia en la app · POL-TE01 §4.8–4.11`} role="Empleado"/>
    <div style={{display:"grid",gridTemplateColumns:"3fr 2fr",gap:16}}>
      <Cd>
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:18,paddingBottom:16,borderBottom:`1px solid ${C.border}`}}>
          <Avatar i={EMP.av} c={C.blue}/><div><div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.ink}}>{EMP.name}</div><div style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>{EMP.rol} · {EMP.area}</div></div>
        </div>
        {[["Destino",VIAJE.destino],["Propósito",VIAJE.motivo],["Salida",VIAJE.ida],["Retorno",VIAJE.ret],["Duración",VIAJE.dias+" días"],["Presupuesto",fmt(VIAJE.presupuesto)]].map(([k,v])=>
          <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"8px 0",borderBottom:`1px solid ${C.bgSurf}`}}>
            <span style={{fontFamily:F.body,fontSize:11,color:C.inkLight,textTransform:"uppercase",letterSpacing:".06em"}}>{k}</span>
            <span style={{fontFamily:F.body,fontSize:12,color:C.ink,fontWeight:600}}>{v}</span></div>)}
        <div style={{marginTop:20}}>
          {st==="idle"&&<Btn onClick={go}>Enviar Solicitud →</Btn>}
          {st==="loading"&&<div style={{fontFamily:F.mono,fontSize:12,color:C.teal}}>⟳ Enviando...</div>}
          {st==="done"&&<Info c={C.teal}><div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.tealDark}}>✓ Solicitud registrada</div><div style={{fontFamily:F.mono,fontSize:11,color:C.teal,marginTop:3}}>{VIAJE.folio}</div></Info>}
        </div>
      </Cd>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Info c={C.blue}><div style={{fontFamily:F.body,fontSize:10,color:C.blue,fontWeight:700,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>⚙ Validación automática</div>
          {["Presupuesto área disponible","Política nivel 3","Sin anticipos pendientes","Días anticipación OK"].map(x=><div key={x} style={{fontFamily:F.body,fontSize:11,color:C.blue,padding:"4px 0",borderBottom:`1px solid ${C.border}`}}>✓ {x}</div>)}
        </Info>
        <Cd><div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".08em",marginBottom:6}}>Anticipo estimado</div>
          <div style={{fontFamily:F.display,fontSize:32,color:C.navy}}>{fmt(VIAJE.anticipo)}</div>
          <div style={{fontFamily:F.body,fontSize:11,color:C.inkLight,marginBottom:8}}>Tarjeta Empresarial GPA</div>
          <Bar v={VIAJE.anticipo} m={VIAJE.presupuesto}/>
        </Cd>
      </div>
    </div>
    {st==="done"&&<div style={{marginTop:20}}><Btn onClick={onNext}>Continuar → Aprobación</Btn></div>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 2 — APROBACIÓN
   ═══════════════════════════════════════════════════════════════════════════ */
function P2({onNext}){
  const[dec,setDec]=useState(null);
  const[ld,setLd]=useState(false);
  const go=v=>{setLd(true);setTimeout(()=>{setLd(false);setDec(v)},1200)};
  return<div>
    <Head n={2} t={10} title="Aprobación de Solicitud" sub={`${SUP.name} revisa y aprueba · POL-TE01 §4.1`} role="Supervisor" rc={C.blue}/>
    <div style={{display:"grid",gridTemplateColumns:"3fr 2fr",gap:16}}>
      <Cd>
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:16,paddingBottom:14,borderBottom:`1px solid ${C.border}`}}>
          <Avatar i={SUP.av} c={C.navy}/><div><div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.ink}}>{SUP.name}</div><div style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>{SUP.rol}</div></div>
          <div style={{marginLeft:"auto"}}><Chip l="1 pendiente" c={C.amber} bg={C.amberBg} bd={C.amberBdr}/></div>
        </div>
        <div style={{background:C.bgSurf,borderRadius:8,padding:"14px 16px",marginBottom:16,border:`1px solid ${C.border}`}}>
          <div style={{fontFamily:F.mono,fontSize:10,color:C.inkFaint,marginBottom:6}}>{VIAJE.folio}</div>
          <div style={{fontFamily:F.body,fontSize:14,fontWeight:700,color:C.ink}}>{EMP.name}</div>
          <div style={{fontFamily:F.body,fontSize:12,color:C.inkMid}}>{VIAJE.destino} · {VIAJE.ida} – {VIAJE.ret}</div>
          <div style={{fontFamily:F.body,fontSize:11,color:C.inkLight,lineHeight:1.5}}>{VIAJE.motivo}</div>
        </div>
        {[["Comprobación a tiempo","94% — Excelente"],["Gastos fuera de política","0 en 6 meses"],["Viajes Q2","2 de 4"]].map(([k,v])=>
          <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"7px 0",borderBottom:`1px solid ${C.bgSurf}`}}>
            <span style={{fontFamily:F.body,fontSize:11,color:C.inkMid}}>{k}</span>
            <span style={{fontFamily:F.body,fontSize:11,color:C.green,fontWeight:600}}>{v}</span></div>)}
        {!dec&&<div style={{display:"flex",gap:10,marginTop:20}}>
          <Btn onClick={()=>go("ok")} disabled={ld}>{ld?"...":"✓ Aprobar"}</Btn>
          <Ghost onClick={()=>go("no")} danger>✗ Rechazar</Ghost></div>}
        {dec==="ok"&&<Info c={C.teal} style={{marginTop:16}}><div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.tealDark}}>✓ Aprobado por {SUP.name}</div></Info>}
      </Cd>
      <Info c={C.blue}><div style={{fontFamily:F.body,fontSize:10,color:C.blue,fontWeight:700,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>Pre-validado</div>
        {["Presupuesto OK","Política aplicada","Sin anticipos abiertos","Hoteles dentro de lista","Anticipación OK"].map(x=><div key={x} style={{fontFamily:F.body,fontSize:12,color:C.blue,padding:"4px 0",borderBottom:`1px solid ${C.border}`}}>✓ {x}</div>)}
      </Info>
    </div>
    {dec==="ok"&&<div style={{marginTop:20}}><Btn onClick={onNext}>Continuar → Cotizar Transporte</Btn></div>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 3 — COTIZAR TRANSPORTE (VUELOS + AUTOBÚS INTEGRADO)
   ═══════════════════════════════════════════════════════════════════════════ */
function P3Transporte({onNext}){
  const[modo,setModo]=useState("vuelo"); // vuelo | autobus
  const[buscando,setBuscando]=useState(false);
  const[resultados,setResultados]=useState(null);
  const[selected,setSelected]=useState(null);
  const[confirmed,setConfirmed]=useState(false);

  const destVuelo = VIAJE.destCode; // MTY
  const limVuelo = POL.vuelos[`GDL-${destVuelo}`];
  const limBus = POL.autobus[`GDL-PVR`]; // ejemplo PVR para bus

  const buscar=()=>{
    setBuscando(true);setSelected(null);setConfirmed(false);
    setTimeout(()=>{
      if(modo==="vuelo"){
        const analyzed = FLIGHTS.map(f=>{
          const precio=f.precio_r;
          const sup4=f.total>MAX_TRASLADO;
          const supLim=limVuelo?precio>limVuelo.r:null;
          return{...f,precio,sup4,supLim,rec:!sup4&&supLim===false};
        });
        setResultados(analyzed);
      } else {
        const analyzed = BUSES.map(b=>{
          const precio=b.precio_r;
          const sup4=b.total>MAX_TRASLADO;
          const supLim=limBus?precio>limBus.r:null;
          return{...b,precio,sup4,supLim,rec:!sup4&&supLim===false};
        });
        setResultados(analyzed);
      }
      setBuscando(false);
    },1500);
  };

  const validos = resultados ? resultados.filter(r=>!r.sup4) : [];
  const descartados = resultados ? resultados.filter(r=>r.sup4).length : 0;
  const mejor = validos.length ? Math.min(...validos.map(r=>r.precio)) : null;

  return<div>
    <Head n={3} t={10} title="Cotizar Transporte" sub="Comprador de Indirectos selecciona vuelo o autobús · POL-TE01 §4.27–4.34" role="Compras" rc={C.blue}/>

    {/* Toggle vuelo / autobús */}
    <div style={{display:"flex",gap:0,marginBottom:20,background:C.bgCard,borderRadius:8,border:`1px solid ${C.border}`,overflow:"hidden",width:"fit-content"}}>
      {[
        {key:"vuelo",icon:"✈",label:"Vuelos",sub:"Aeroméxico · Volaris · VivaAerobus"},
        {key:"autobus",icon:"🚌",label:"Autobús",sub:"ETN · Primera Plus · Estrella Blanca · TAP"},
      ].map(t=>(
        <button key={t.key} onClick={()=>{setModo(t.key);setResultados(null);setSelected(null);setConfirmed(false)}} style={{
          padding:"14px 24px",background:modo===t.key?C.tealXL:"transparent",
          border:"none",borderBottom:`2.5px solid ${modo===t.key?C.teal:"transparent"}`,
          cursor:"pointer",fontFamily:F.body,textAlign:"left",transition:"all .15s",
        }}>
          <div style={{fontSize:16,marginBottom:2}}>{t.icon}</div>
          <div style={{fontSize:13,fontWeight:modo===t.key?700:400,color:modo===t.key?C.tealDark:C.inkMid}}>{t.label}</div>
          <div style={{fontSize:10,color:C.inkLight}}>{t.sub}</div>
        </button>
      ))}
    </div>

    {/* Barra de búsqueda */}
    <div style={{background:C.navy,borderRadius:10,padding:"20px 24px",marginBottom:20}}>
      <div style={{display:"flex",gap:14,alignItems:"end"}}>
        <div style={{flex:1}}>
          <div style={{fontFamily:F.body,fontSize:10,color:C.tealLight,textTransform:"uppercase",letterSpacing:".07em",marginBottom:5}}>Ruta</div>
          <div style={{fontFamily:F.body,fontSize:16,color:"#fff",fontWeight:700}}>
            GDL → {modo==="vuelo"?VIAJE.destCode:"PVR"} {modo==="vuelo"?"("+VIAJE.destino+")":"(Puerto Vallarta)"}
          </div>
        </div>
        <div>
          <div style={{fontFamily:F.body,fontSize:10,color:C.tealLight,textTransform:"uppercase",letterSpacing:".07em",marginBottom:5}}>Tipo</div>
          <div style={{fontFamily:F.body,fontSize:13,color:"#fff"}}>Redondo</div>
        </div>
        <div>
          <div style={{fontFamily:F.body,fontSize:10,color:C.tealLight,textTransform:"uppercase",letterSpacing:".07em",marginBottom:5}}>Límite POL-TE01</div>
          <div style={{fontFamily:F.body,fontSize:13,color:C.tealLight,fontWeight:700}}>
            {modo==="vuelo" ? (limVuelo ? fmt(limVuelo.r) : "Auth DG") : (limBus ? fmt(limBus.r) : "—")}
          </div>
        </div>
        <button onClick={buscar} disabled={buscando} style={{
          padding:"10px 24px",background:buscando?C.blueSoft:C.teal,color:buscando?C.inkFaint:C.navy,
          border:"none",borderRadius:6,fontFamily:F.body,fontSize:13,fontWeight:700,cursor:buscando?"default":"pointer",
        }}>{buscando?"⟳ Buscando...":"Buscar →"}</button>
      </div>
    </div>

    {/* Regla 4 hrs */}
    <div style={{background:C.amberBg,border:`1px solid ${C.amberBdr}`,borderRadius:8,padding:"10px 14px",marginBottom:16,fontFamily:F.body,fontSize:12,color:C.amber}}>
      <strong>⚠ Regla GPA:</strong> Rutas con traslado total &gt;4 horas son automáticamente descartadas (tiempo de ruta + abordaje + llegada + traslado destino).
    </div>

    {/* Buscando */}
    {buscando && (
      <Cd style={{padding:"32px",textAlign:"center"}}>
        <div style={{fontFamily:F.body,fontSize:14,color:C.inkMid,marginBottom:10}}>Consultando {modo==="vuelo"?"aerolíneas":"líneas de autobús"}...</div>
        <div style={{display:"flex",justifyContent:"center",gap:20}}>
          {(modo==="vuelo"?Object.values(AIRLINES):Object.values(BUSLINES)).map(a=>(
            <div key={a.name} style={{display:"flex",alignItems:"center",gap:6}}>
              <div style={{width:8,height:8,borderRadius:"50%",background:a.color}}/>
              <span style={{fontFamily:F.body,fontSize:12,color:a.color,fontWeight:700}}>{a.name}</span>
            </div>
          ))}
        </div>
      </Cd>
    )}

    {/* Resultados */}
    {resultados && !buscando && !confirmed && (
      <div>
        {/* Métricas */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:16}}>
          {[
            {l:"Encontrados",v:resultados.length,c:C.navy},
            {l:"Válidos <4h",v:validos.length,c:C.tealDark},
            {l:"Descartados >4h",v:descartados,c:C.red},
            {l:"Mejor precio",v:mejor?fmt(mejor):"—",c:C.green},
          ].map(s=><Cd key={s.l} style={{textAlign:"center",padding:"12px 14px"}}>
            <div style={{fontFamily:F.display,fontSize:22,color:s.c}}>{s.v}</div>
            <div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".07em",marginTop:2}}>{s.l}</div>
          </Cd>)}
        </div>

        {/* Lista de resultados */}
        <div style={{display:"grid",gridTemplateColumns:"2fr 1fr",gap:16}}>
          <div style={{display:"flex",flexDirection:"column",gap:10}}>
            {resultados.map(r=>{
              const provider = modo==="vuelo"?AIRLINES[r.al]:BUSLINES[r.ln];
              const isSel = selected?.id===r.id;
              const desc = r.sup4;
              const bc = isSel?C.teal:desc?C.redBdr:r.rec?C.greenBdr:C.border;
              const bg = isSel?C.tealXL:desc?C.redBg:C.bgCard;
              return <div key={r.id} onClick={()=>!desc&&setSelected(r)} style={{
                border:`1.5px solid ${bc}`,borderRadius:8,background:bg,padding:"14px 16px",
                cursor:desc?"not-allowed":"pointer",opacity:desc?.6:1,position:"relative",overflow:"hidden",transition:"all .15s",
              }}>
                <div style={{position:"absolute",top:0,left:0,right:0,height:3,background:provider.color,opacity:.85}}/>
                {desc&&<div style={{position:"absolute",top:8,right:8,background:C.redBg,border:`1px solid ${C.redBdr}`,borderRadius:4,padding:"2px 8px",fontFamily:F.body,fontSize:10,fontWeight:700,color:C.red}}>✗ DESCARTADO &gt;4H</div>}
                {r.rec&&!isSel&&<div style={{position:"absolute",top:8,right:8,background:C.greenBg,border:`1px solid ${C.greenBdr}`,borderRadius:4,padding:"2px 8px",fontFamily:F.body,fontSize:10,fontWeight:700,color:C.green}}>✓ RECOMENDADO</div>}
                {isSel&&<div style={{position:"absolute",top:8,right:8,background:C.tealXL,border:`1px solid ${C.tealLight}`,borderRadius:4,padding:"2px 8px",fontFamily:F.body,fontSize:10,fontWeight:700,color:C.tealDark}}>◉ SELECCIONADO</div>}

                <div style={{display:"flex",alignItems:"center",gap:14,marginTop:6}}>
                  <div style={{width:52,height:44,borderRadius:6,background:provider.bg,border:`1px solid ${provider.color}30`,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",flexShrink:0}}>
                    <span style={{fontSize:8,fontWeight:900,color:provider.color,fontFamily:F.body}}>{provider.name.split(" ")[0]}</span>
                    <span style={{fontSize:11,fontFamily:F.mono,color:provider.color,fontWeight:700}}>{r.id}</span>
                  </div>
                  <div style={{flex:1,display:"flex",alignItems:"center",gap:8}}>
                    <div style={{textAlign:"center"}}><div style={{fontFamily:F.display,fontSize:18,color:C.navy,lineHeight:1}}>{r.sal}</div><div style={{fontFamily:F.mono,fontSize:10,color:C.inkLight}}>GDL</div></div>
                    <div style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:2}}>
                      <div style={{fontFamily:F.body,fontSize:10,color:C.inkLight}}>{fmtMin(r.dur)}</div>
                      <div style={{width:"100%",display:"flex",alignItems:"center",gap:3}}><div style={{height:1,flex:1,background:C.borderMid}}/><span style={{fontSize:10}}>{modo==="vuelo"?"✈":"🚌"}</span><div style={{height:1,flex:1,background:C.borderMid}}/></div>
                      {(r.esc===false&&r.dir!==false)?<div style={{fontFamily:F.body,fontSize:9,color:C.green}}>Directo</div>:<div style={{fontFamily:F.body,fontSize:9,color:C.amber,fontWeight:700}}>{r.parada?`Parada ${r.parada}`:"Con escala"}</div>}
                    </div>
                    <div style={{textAlign:"center"}}><div style={{fontFamily:F.display,fontSize:18,color:C.navy,lineHeight:1}}>{r.lleg}</div><div style={{fontFamily:F.mono,fontSize:10,color:C.inkLight}}>{modo==="vuelo"?VIAJE.destCode:"PVR"}</div></div>
                  </div>
                  <div style={{textAlign:"center",padding:"6px 10px",background:r.sup4?C.redBg:C.tealXL,borderRadius:6,border:`1px solid ${r.sup4?C.redBdr:C.tealLight}`,minWidth:72}}>
                    <div style={{fontFamily:F.mono,fontSize:13,fontWeight:700,color:r.sup4?C.red:r.total>200?C.amber:C.green,lineHeight:1}}>{fmtMin(r.total)}</div>
                    <div style={{fontFamily:F.body,fontSize:8,color:r.sup4?C.red:C.tealDark,marginTop:2}}>traslado total</div>
                  </div>
                  <div style={{textAlign:"right",minWidth:90}}>
                    <div style={{fontFamily:F.display,fontSize:20,color:r.supLim?C.red:C.navy,lineHeight:1}}>{fmt(r.precio)}</div>
                    <div style={{fontFamily:F.body,fontSize:10,color:C.inkLight}}>redondo</div>
                    {r.supLim!==null&&<div style={{fontFamily:F.body,fontSize:10,color:r.supLim?C.red:C.green,fontWeight:700,marginTop:2}}>{r.supLim?"✗ Excede":"✓ Dentro"}</div>}
                  </div>
                  <div style={{textAlign:"center",minWidth:36}}><div style={{fontFamily:F.mono,fontSize:13,color:r.asientos<=5?C.red:C.inkMid,fontWeight:700}}>{r.asientos}</div><div style={{fontFamily:F.body,fontSize:9,color:C.inkFaint}}>disp.</div></div>
                </div>
                <div style={{display:"flex",gap:6,marginTop:8,flexWrap:"wrap"}}>
                  <Chip l={provider.name} c={provider.color} bg={provider.bg}/>
                  {r.clase&&<Chip l={r.clase} c={C.inkMid} bg={C.bgSurf}/>}
                  {r.sup4&&<Chip l="Descartado >4h" c={C.red} bg={C.redBg} bd={C.redBdr}/>}
                </div>
              </div>;
            })}
          </div>

          {/* Panel resumen */}
          <div style={{position:"sticky",top:16,alignSelf:"start",display:"flex",flexDirection:"column",gap:14}}>
            {selected ? (
              <Cd>
                <div style={{fontFamily:F.body,fontSize:10,color:C.tealDark,fontWeight:700,textTransform:"uppercase",letterSpacing:".08em",marginBottom:12}}>Selección</div>
                <div style={{background:C.tealXL,borderRadius:6,padding:"10px 14px",marginBottom:12}}>
                  <div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.navy}}>{(modo==="vuelo"?AIRLINES[selected.al]:BUSLINES[selected.ln]).name} · {selected.id}</div>
                  <div style={{fontFamily:F.body,fontSize:11,color:C.inkMid}}>{selected.sal} → {selected.lleg} · {fmtMin(selected.dur)} · Directo</div>
                </div>
                <div style={{display:"flex",justifyContent:"space-between",marginBottom:6}}>
                  <span style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>Precio redondo</span>
                  <span style={{fontFamily:F.display,fontSize:20,color:C.navy}}>{fmt(selected.precio)}</span>
                </div>
                {selected.supLim!==null&&<div style={{fontFamily:F.body,fontSize:11,color:selected.supLim?C.red:C.green,fontWeight:700}}>
                  {selected.supLim?`✗ Excede límite POL-TE01`:`✓ Dentro del límite POL-TE01`}
                </div>}
                <button onClick={()=>setConfirmed(true)} style={{width:"100%",marginTop:14,padding:"11px",fontFamily:F.body,fontSize:13,fontWeight:700,background:C.navy,color:C.tealLight,border:"none",borderRadius:6,cursor:"pointer"}}>
                  ✓ Confirmar e integrar
                </button>
              </Cd>
            ) : (
              <Cd style={{background:C.bgSurf}}>
                <div style={{textAlign:"center",color:C.inkFaint,fontFamily:F.body,fontSize:13,padding:"20px 0"}}>
                  Selecciona un {modo==="vuelo"?"vuelo":"servicio"} para continuar
                </div>
              </Cd>
            )}

            <Cd style={{padding:"14px 16px"}}>
              <div style={{fontFamily:F.body,fontSize:10,color:C.navy,fontWeight:700,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>Límites POL-TE01</div>
              {Object.entries(modo==="vuelo"?POL.vuelos:POL.autobus).map(([ruta,lim])=>(
                <div key={ruta} style={{display:"flex",justifyContent:"space-between",padding:"4px 0",borderBottom:`1px solid ${C.bgSurf}`}}>
                  <span style={{fontFamily:F.mono,fontSize:11,color:C.inkMid}}>{ruta}</span>
                  <span style={{fontFamily:F.body,fontSize:11,color:C.ink,fontWeight:600}}>{fmt(lim.s)} / {fmt(lim.r)}</span>
                </div>
              ))}
            </Cd>
          </div>
        </div>
      </div>
    )}

    {/* Confirmado */}
    {confirmed&&selected&&(
      <Info c={C.teal} style={{marginTop:16}}>
        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <span style={{fontSize:24}}>✓</span>
          <div>
            <div style={{fontFamily:F.body,fontSize:14,fontWeight:700,color:C.tealDark}}>Transporte confirmado e integrado a la solicitud</div>
            <div style={{fontFamily:F.body,fontSize:12,color:C.tealDark}}>{(modo==="vuelo"?AIRLINES[selected.al]:BUSLINES[selected.ln]).name} · {selected.id} · {fmt(selected.precio)} redondo</div>
          </div>
        </div>
      </Info>
    )}

    {/* Estado inicial */}
    {!resultados&&!buscando&&(
      <Cd style={{padding:"40px",textAlign:"center"}}>
        <div style={{fontSize:32,marginBottom:10}}>{modo==="vuelo"?"✈":"🚌"}</div>
        <div style={{fontFamily:F.display,fontSize:20,color:C.navy,marginBottom:6}}>Haz clic en "Buscar" para consultar {modo==="vuelo"?"vuelos":"autobuses"}</div>
        <div style={{fontFamily:F.body,fontSize:13,color:C.inkLight}}>Filtro automático &gt;4h · Límites POL-TE01 aplicados · Mejor opción recomendada</div>
      </Cd>
    )}

    {confirmed&&<div style={{marginTop:20}}><Btn onClick={onNext}>Continuar → Liberación de Anticipo</Btn></div>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 4 — ANTICIPO
   ═══════════════════════════════════════════════════════════════════════════ */
function P4({onNext}){
  const[d,setD]=useState(false);
  useEffect(()=>{const t=setTimeout(()=>setD(true),2000);return()=>clearTimeout(t)},[]);
  return<div>
    <Head n={4} t={10} title="Asignación de Fondos" sub="Tesorería libera anticipo · Tarjeta Empresarial · POL-TE01 §4.54" role="Tesorería" rc={C.teal}/>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
      <Cd><div style={{textAlign:"center",padding:"24px 0"}}>
        <div style={{fontFamily:F.body,fontSize:11,color:C.inkLight,textTransform:"uppercase",letterSpacing:".1em",marginBottom:6}}>Anticipo</div>
        <div style={{fontFamily:F.display,fontSize:48,color:C.navy}}>{fmt(VIAJE.anticipo)}</div>
        <div style={{fontFamily:F.body,fontSize:12,color:C.inkLight,marginTop:4}}>Tarjeta Empresarial GPA · {EMP.name}</div>
        {!d?<div style={{marginTop:16,fontFamily:F.mono,fontSize:12,color:C.amber}}>⟳ Procesando...</div>
          :<Info c={C.teal} style={{marginTop:16,textAlign:"left"}}><div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.tealDark}}>✓ Fondos asignados</div></Info>}
      </div>
      {d&&[["Centro de costo","VTA-NORTE-2025"],["Cuenta","6320 Viáticos"],["Límite comprobación","12 Mayo 2025"]].map(([k,v])=>
        <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"7px 0",borderBottom:`1px solid ${C.border}`}}>
          <span style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>{k}</span>
          <span style={{fontFamily:F.body,fontSize:11,color:C.ink,fontWeight:600}}>{v}</span></div>)}
      </Cd>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Cd><div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>Registro ERP</div>
          <div style={{fontFamily:F.mono,fontSize:11,color:C.inkMid,lineHeight:2,background:C.bgSurf,borderRadius:6,padding:"12px 14px"}}>
            <span style={{color:C.inkFaint}}>›</span> PÓLIZA-2025-3782<br/><span style={{color:C.inkFaint}}>›</span> 6320 Debe: {fmt(VIAJE.anticipo)}<br/><span style={{color:C.inkFaint}}>›</span> 1110 Haber: {fmt(VIAJE.anticipo)}<br/><span style={{color:C.teal}}>›</span> CONTABILIZADO ✓
          </div>
        </Cd>
        <Cd style={{background:C.amberBg,borderColor:C.amberBdr}}>
          <div style={{fontFamily:F.body,fontSize:10,color:C.amber,fontWeight:700,marginBottom:8}}>⏰ Recordatorios automáticos</div>
          {[["D+3","Push al empleado"],["D+4","WhatsApp: quedan 48h"],["D+5","Email urgente"],["D+6","Alerta supervisor"]].map(([d,m])=>
            <div key={d} style={{display:"flex",gap:10,padding:"4px 0",borderBottom:`1px solid ${C.amberBdr}`}}>
              <span style={{fontFamily:F.mono,fontSize:10,color:C.amber,minWidth:32}}>{d}</span>
              <span style={{fontFamily:F.body,fontSize:11,color:C.amber}}>{m}</span></div>)}
        </Cd>
      </div>
    </div>
    {d&&<div style={{marginTop:20}}><Btn onClick={onNext}>Continuar → Captura de Gastos</Btn></div>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 5 — CAPTURA
   ═══════════════════════════════════════════════════════════════════════════ */
function P5({onNext}){
  const[caps,setCaps]=useState([]);
  const[proc,setProc]=useState(false);
  const idx=caps.length;
  const capturar=()=>{if(idx>=TICKETS.length||proc)return;setProc(true);setTimeout(()=>{setCaps(p=>[...p,TICKETS[p.length]]);setProc(false)},1500)};
  const total=caps.reduce((s,t)=>s+t.monto,0);
  return<div>
    <Head n={5} t={10} title="Captura de Comprobantes" sub={`${EMP.name} regresó — OCR extrae datos automáticamente`} role="Empleado"/>
    <div style={{display:"grid",gridTemplateColumns:"5fr 2fr",gap:16}}>
      <div>
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:14}}>
          <div style={{fontFamily:F.body,fontSize:12,color:C.inkMid}}>{caps.length}/{TICKETS.length}</div>
          <div style={{flex:1}}><Bar v={caps.length} m={TICKETS.length}/></div>
          {idx<TICKETS.length&&<Btn onClick={capturar} disabled={proc} small>{proc?"⟳ OCR...":"📷 Capturar #"+(idx+1)}</Btn>}
        </div>
        {caps.map(t=>{const sc=t.st==="ok"?C.teal:t.st==="revision"?C.amber:C.red;return<Cd key={t.id} style={{marginBottom:10,borderLeft:`3px solid ${sc}`}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
            <div style={{flex:1}}>
              <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:5,flexWrap:"wrap"}}>
                <span style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.ink}}>{t.com}</span>
                <Chip l={t.st==="ok"?"✓ Válido":t.st==="revision"?"⚠ Revisión":"✗ Rechazado"} c={sc} bg={t.st==="ok"?C.greenBg:t.st==="revision"?C.amberBg:C.redBg} bd={t.st==="ok"?C.greenBdr:t.st==="revision"?C.amberBdr:C.redBdr}/>
                {t.cfdi?<Chip l="CFDI ✓" c={C.blue} bg={C.blueSoft}/>:<Chip l="Sin CFDI" c={C.red} bg={C.redBg} bd={C.redBdr}/>}
              </div>
              <div style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>{t.tipo} · {t.fecha}</div>
              <div style={{fontFamily:F.body,fontSize:11,color:sc,lineHeight:1.5,marginTop:4}}>{t.pol}</div>
              {t.nota&&<div style={{marginTop:6,background:C.amberBg,border:`1px solid ${C.amberBdr}`,borderRadius:4,padding:"4px 10px",fontFamily:F.body,fontSize:11,color:C.amber}}>💬 {t.nota}</div>}
            </div>
            <div style={{textAlign:"right",marginLeft:14,flexShrink:0}}>
              <div style={{fontFamily:F.display,fontSize:18,color:C.navy}}>{fmtD(t.monto)}</div>
              <div style={{fontFamily:F.mono,fontSize:9,color:C.inkFaint}}>OCR {t.ocr}%</div>
            </div>
          </div>
        </Cd>})}
        {idx>=TICKETS.length&&<div style={{marginTop:8}}><Btn onClick={onNext}>Continuar → Validación IA</Btn></div>}
      </div>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Cd><div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".08em",marginBottom:6}}>Total</div>
          <div style={{fontFamily:F.display,fontSize:28,color:C.navy}}>{fmtD(total)}</div>
          <div style={{fontFamily:F.body,fontSize:11,color:C.inkLight,marginBottom:6}}>de {fmt(VIAJE.presupuesto)}</div>
          <Bar v={total} m={VIAJE.presupuesto} c={total>VIAJE.presupuesto?C.red:C.teal}/>
        </Cd>
      </div>
    </div>
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 6 — VALIDACIÓN IA
   ═══════════════════════════════════════════════════════════════════════════ */
function P6({onNext}){
  const[rev,setRev]=useState(0);
  const done=rev>=TICKETS.length;
  useEffect(()=>{const ts=TICKETS.map((_,i)=>setTimeout(()=>setRev(r=>r+1),480*(i+1)));return()=>ts.forEach(clearTimeout)},[]);
  const txt=`De ${TICKETS.length} comprobantes contra POL-TE01: ${TICKETS.filter(t=>t.st==="ok").length} aprobados automáticamente (80%). El restaurante aplica política de representación (art 4.38) y requiere lista de asistentes. Starbucks rechazado por ausencia de CFDI (art 4.21).`;
  const tw=useTyp(txt,12,done);
  return<div>
    <Head n={6} t={10} title="Validación IA · Motor de Políticas" sub="Verificación automática contra POL-TE01 · Score antifraude · CFDI SAT" role="Sistema IA" rc={C.tealDark}/>
    <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12,marginBottom:20}}>
      {[{l:"Auto-aprobados",n:TICKETS.filter(t=>t.st==="ok").length,c:C.teal,bg:C.tealXL},{l:"Revisión",n:TICKETS.filter(t=>t.st==="revision").length,c:C.amber,bg:C.amberBg},{l:"Rechazados",n:TICKETS.filter(t=>t.st==="rechazado").length,c:C.red,bg:C.redBg}].map(s=>
        <Cd key={s.l} style={{textAlign:"center",background:s.bg,borderColor:`${s.c}30`}}>
          <div style={{fontFamily:F.display,fontSize:38,color:s.c}}>{s.n}</div>
          <div style={{fontFamily:F.body,fontSize:10,color:s.c,textTransform:"uppercase",letterSpacing:".08em",fontWeight:700}}>{s.l}</div>
        </Cd>)}
    </div>
    {TICKETS.slice(0,rev).map(t=>{const sc=t.st==="ok"?C.teal:t.st==="revision"?C.amber:C.red;return<Cd key={t.id} style={{marginBottom:10,borderLeft:`3px solid ${sc}`}}>
      <div style={{display:"flex",justifyContent:"space-between"}}><span style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.ink}}>{t.com}</span><span style={{fontFamily:F.display,fontSize:16,color:C.navy}}>{fmtD(t.monto)}</span></div>
      <div style={{fontFamily:F.body,fontSize:11,color:sc,marginTop:4,lineHeight:1.5}}>{t.pol}</div>
    </Cd>})}
    {done&&<Info c={C.blue} style={{marginTop:16}}><div style={{fontFamily:F.body,fontSize:11,color:C.blue,fontWeight:700,marginBottom:6}}>🤖 Análisis IA</div>
      <div style={{fontFamily:F.body,fontSize:12,color:C.blue,lineHeight:1.7}}>{tw}{tw.length<txt.length?"|":""}</div>
      <div style={{marginTop:14}}><Btn onClick={onNext}>Continuar → Revisión</Btn></div>
    </Info>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 7 — REVISIÓN
   ═══════════════════════════════════════════════════════════════════════════ */
function P7({onNext}){
  const[decs,setDecs]=useState({});
  const exc=TICKETS.filter(t=>t.st!=="ok");
  const allDone=exc.every(t=>decs[t.id]);
  return<div>
    <Head n={7} t={10} title="Revisión de Excepciones" sub={`Solo ${exc.length} casos — ${TICKETS.filter(t=>t.st==="ok").length} ya aprobados automáticamente`} role="Supervisor" rc={C.blue}/>
    <Info c={C.teal} style={{marginBottom:16}}><div style={{fontFamily:F.body,fontSize:12,color:C.tealDark}}>✓ <strong>{TICKETS.filter(t=>t.st==="ok").length} comprobantes aprobados sin intervención.</strong> Solo {exc.length} excepciones.</div></Info>
    {exc.map(t=>{const sc=t.st==="revision"?C.amber:C.red;return<Cd key={t.id} style={{marginBottom:14,borderLeft:`3px solid ${sc}`}}>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:10}}>
        <div><div style={{fontFamily:F.body,fontSize:14,fontWeight:700,color:C.ink}}>{t.com}</div><div style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>{t.tipo}</div></div>
        <div style={{fontFamily:F.display,fontSize:22,color:C.navy}}>{fmtD(t.monto)}</div>
      </div>
      <div style={{background:C.bgSurf,border:`1px solid ${C.border}`,borderRadius:6,padding:"10px 12px",marginBottom:10}}>
        <div style={{fontFamily:F.body,fontSize:11,color:sc,lineHeight:1.5}}>{t.pol}</div>
        {t.nota&&<div style={{fontFamily:F.body,fontSize:11,color:C.amber,marginTop:6}}>Justificación: {t.nota}</div>}
      </div>
      {!decs[t.id]?<div style={{display:"flex",gap:10}}>
        <Btn small onClick={()=>setDecs(d=>({...d,[t.id]:"ok"}))}>✓ Aprobar</Btn>
        <Ghost danger onClick={()=>setDecs(d=>({...d,[t.id]:"no"}))}>✗ Rechazar</Ghost></div>
       :<Info c={decs[t.id]==="ok"?C.teal:C.red}><div style={{fontFamily:F.body,fontSize:12,fontWeight:700,color:decs[t.id]==="ok"?C.tealDark:C.red}}>{decs[t.id]==="ok"?"✓ Excepción aprobada":"✗ Rechazado"}</div></Info>}
    </Cd>})}
    {allDone&&<Btn onClick={onNext}>Continuar → Cierre</Btn>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 8 — CIERRE
   ═══════════════════════════════════════════════════════════════════════════ */
function P8({onNext}){
  const saldo=VIAJE.anticipo-totalAprobado;
  const[sp,setSp]=useState(false);
  useEffect(()=>{const t=setTimeout(()=>setSp(true),2000);return()=>clearTimeout(t)},[]);
  return<div>
    <Head n={8} t={10} title="Cierre de Comprobación" sub="Liquidación automática · PDF firmado · Registro ERP · POL-TE01 §4.55–4.61" role="Finanzas" rc={C.teal}/>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
      <Cd>
        {[["Anticipo entregado",fmt(VIAJE.anticipo),C.navy],["Gasto aprobado",fmtD(totalAprobado),C.ink],["Rechazado",`– ${fmtD(TICKETS.find(t=>t.st==="rechazado").monto)}`,C.red]].map(([k,v,c])=>
          <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"10px 0",borderBottom:`1px solid ${C.border}`}}>
            <span style={{fontFamily:F.body,fontSize:12,color:C.inkMid}}>{k}</span>
            <span style={{fontFamily:F.display,fontSize:16,color:c}}>{v}</span></div>)}
        <div style={{display:"flex",justifyContent:"space-between",padding:"14px 12px",background:saldo>0?C.amberBg:C.tealXL,borderRadius:8,border:`1px solid ${saldo>0?C.amberBdr:C.tealLight}`,marginTop:10}}>
          <span style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:saldo>0?C.amber:C.tealDark}}>{saldo>0?"Saldo a cargo del empleado":"Reembolso"}</span>
          <span style={{fontFamily:F.display,fontSize:22,color:saldo>0?C.amber:C.tealDark}}>{fmtD(Math.abs(saldo))}</span>
        </div>
        {!sp?<div style={{marginTop:14,fontFamily:F.mono,fontSize:12,color:C.amber}}>⟳ Liquidando...</div>
          :<Info c={C.teal} style={{marginTop:14}}><div style={{fontFamily:F.body,fontSize:13,fontWeight:700,color:C.tealDark}}>✓ Liquidación procesada</div></Info>}
      </Cd>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Info c={C.teal}><div style={{fontFamily:F.body,fontSize:10,color:C.tealDark,fontWeight:700,marginBottom:8}}>📄 Documentos generados</div>
          {["Formato Solicitud y Comprobación","Relación de Facturas firmada","CFDIs adjuntos PDF","Desglose movimientos tarjeta","Póliza contable ERP","Log auditoría SHA-256"].map(d=>
            <div key={d} style={{fontFamily:F.body,fontSize:11,color:C.tealDark,padding:"3px 0",borderBottom:`1px solid ${C.tealLight}`}}>✓ {d}</div>)}
        </Info>
        <Cd><div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>KPIs del viaje</div>
          {[["Tiempo comprobación","47 min"],["vs. manual","3–7 días"],["Auto-aprobados","4/5 (80%)"],["Intervención supv.","6 min"],["Score compliance","94/100 ⭐"]].map(([k,v])=>
            <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"6px 0",borderBottom:`1px solid ${C.bgSurf}`}}>
              <span style={{fontFamily:F.body,fontSize:11,color:C.inkLight}}>{k}</span>
              <span style={{fontFamily:F.body,fontSize:11,color:C.tealDark,fontWeight:700}}>{v}</span></div>)}
        </Cd>
      </div>
    </div>
    {sp&&<div style={{marginTop:20}}><Btn onClick={onNext}>Continuar → Reembolso</Btn></div>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 9 — REEMBOLSO
   ═══════════════════════════════════════════════════════════════════════════ */
function P9({onNext}){
  const saldo=VIAJE.anticipo-totalAprobado;
  const[d,setD]=useState(false);
  useEffect(()=>{const t=setTimeout(()=>setD(true),2000);return()=>clearTimeout(t)},[]);
  return<div>
    <Head n={9} t={10} title={saldo>0?"Devolución del Empleado":"Reembolso al Empleado"} sub="Proceso automático SPEI · POL-TE01 §4.60–4.61" role="Finanzas" rc={C.teal}/>
    <Cd style={{maxWidth:500,margin:"0 auto",textAlign:"center",padding:"32px"}}>
      {!d?<div><div style={{fontFamily:F.display,fontSize:40,color:C.ink}}>⏳</div><div style={{fontFamily:F.body,fontSize:14,color:C.inkMid,marginTop:12}}>Procesando SPEI...</div></div>
        :<div><div style={{fontSize:48}}>✓</div><div style={{fontFamily:F.display,fontSize:36,color:saldo>0?C.amber:C.green,marginTop:8}}>{fmtD(Math.abs(saldo))}</div>
          <div style={{fontFamily:F.body,fontSize:13,color:saldo>0?C.amber:C.green,marginTop:4}}>{saldo>0?"Cargo programado al empleado":"Reembolso depositado a "+EMP.name}</div>
          <div style={{fontFamily:F.mono,fontSize:11,color:C.inkLight,marginTop:4}}>Ref: {VIAJE.folio}-LIQ · 23 min post-cierre</div>
        </div>}
    </Cd>
    {d&&<div style={{marginTop:20,textAlign:"center"}}><Btn onClick={onNext}>Ver Dashboard Ejecutivo →</Btn></div>}
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   PASO 10 — DASHBOARD
   ═══════════════════════════════════════════════════════════════════════════ */
function P10(){
  const cats=[{c:"Transporte Aéreo",m:3240,p:POL.vuelos["GDL-MTY"].r,cl:C.blue},{c:"Hospedaje MTY",m:2498,p:POL.hospedaje.monterrey*2,cl:C.teal},{c:"Representación",m:1850,p:POL.representacion.max_p*4,cl:C.amber},{c:"Transporte Local",m:380,p:700,cl:C.navy}];
  return<div>
    <Head n={10} t={10} title="Dashboard Ejecutivo" sub="Dirección & Finanzas · Tiempo real · Cierre VIA-2025-0341" role="Dirección" rc={C.gold}/>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12,marginBottom:20}}>
      {[{l:"Gasto total",v:fmtD(totalAprobado),s:`vs ${fmt(VIAJE.presupuesto)}`,c:C.navy},{l:"Ahorro",v:fmtD(VIAJE.presupuesto-totalAprobado),s:"bajo presupuesto",c:C.tealDark},{l:"Tiempo",v:"47 min",s:"Meta <4h ✓",c:C.blue},{l:"Score",v:"94/100",s:EMP.name+" ⭐",c:C.gold}].map(s=>
        <Cd key={s.l} style={{textAlign:"center"}}><div style={{fontFamily:F.display,fontSize:24,color:s.c}}>{s.v}</div>
          <div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".07em",margin:"3px 0 2px"}}>{s.l}</div>
          <div style={{fontFamily:F.body,fontSize:10,color:s.c}}>{s.s}</div>
        </Cd>)}
    </div>
    <div style={{display:"grid",gridTemplateColumns:"3fr 2fr",gap:16}}>
      <Cd><div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".08em",marginBottom:14}}>Gasto vs. Límite POL-TE01</div>
        {cats.map(i=>{const pct=i.m/i.p*100;const ov=pct>100;return<div key={i.c} style={{marginBottom:14}}>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
            <span style={{fontFamily:F.body,fontSize:12,color:C.ink}}>{i.c}</span>
            <span style={{fontFamily:F.body,fontSize:12,color:ov?C.red:C.inkMid}}>{fmtD(i.m)}<span style={{marginLeft:6,color:ov?C.red:C.tealDark,fontWeight:700}}>{ov?`+${Math.round(pct-100)}%`:`${Math.round(pct)}%`}</span></span>
          </div><Bar v={i.m} m={i.p} c={ov?C.red:i.cl}/></div>})}
      </Cd>
      <div style={{display:"flex",flexDirection:"column",gap:12}}>
        <Info c={C.blue}><div style={{fontFamily:F.body,fontSize:10,color:C.blue,fontWeight:700,marginBottom:8}}>💡 Insight IA</div>
          <div style={{fontFamily:F.body,fontSize:12,color:C.blue,lineHeight:1.7}}>Recomendación: crear categoría "Representación Comercial" con tope de {fmt(POL.representacion.max_p)}/persona y flujo express para clientes Premium/Clave.</div>
        </Info>
        <Cd><div style={{fontFamily:F.body,fontSize:10,color:C.inkLight,textTransform:"uppercase",letterSpacing:".08em",marginBottom:10}}>Manual vs. ViaticOS</div>
          {[["Tiempo","3–7 días → 47 min"],["Correos","12–18 → 0"],["Trabajo manual","4–6 hrs → 6 min"],["Trazabilidad","Baja → 100%"]].map(([k,v])=>
            <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"6px 0",borderBottom:`1px solid ${C.border}`}}>
              <span style={{fontFamily:F.body,fontSize:10,color:C.inkLight}}>{k}</span>
              <span style={{fontFamily:F.body,fontSize:10,color:C.tealDark,fontWeight:700}}>{v}</span></div>)}
        </Cd>
      </div>
    </div>
    <div style={{marginTop:16,background:C.navy,borderRadius:10,padding:"20px 24px",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
      <div><div style={{fontFamily:F.display,fontSize:20,color:"#fff"}}>Viaje cerrado · {VIAJE.folio}</div><div style={{fontFamily:F.body,fontSize:12,color:C.tealLight}}>{VIAJE.destino} · {EMP.name} · Documentado, trazable y en ERP</div></div>
      <div style={{textAlign:"right"}}><div style={{fontFamily:F.display,fontSize:28,color:C.tealLight}}>{fmtD(VIAJE.presupuesto-totalAprobado)}</div><div style={{fontFamily:F.body,fontSize:11,color:C.tealLight,opacity:.8}}>ahorro vs presupuesto</div></div>
    </div>
  </div>;
}

/* ═══════════════════════════════════════════════════════════════════════════
   APP PRINCIPAL — 10 PASOS
   ═══════════════════════════════════════════════════════════════════════════ */
const ALL_STEPS=[P1,P2,P3Transporte,P4,P5,P6,P7,P8,P9,P10];
const LABELS=["Solicitud","Aprobación","Transporte","Anticipo","Captura","Validación IA","Revisión","Cierre","Reembolso","Dashboard"];
const ACTORS=["Empleado","Supervisor","Compras","Tesorería","Empleado","Sistema","Supervisor","Finanzas","Finanzas","Dirección"];

function ViaticosDemo(){
  const[paso,setPaso]=useState(0);
  const bodyRef=useRef(null);
  const ir=n=>{setPaso(n);bodyRef.current?.scrollTo(0,0)};
  const sig=()=>ir(Math.min(paso+1,ALL_STEPS.length-1));
  const Paso=ALL_STEPS[paso];

  return<div style={{background:C.bgPage,minHeight:"100vh",color:C.ink,fontFamily:F.body,display:"flex",flexDirection:"column"}}>

    {/* NAVBAR */}
    <nav style={{background:C.navy,padding:"0 24px",display:"flex",alignItems:"center",height:56,gap:16,flexShrink:0}}>
      <div style={{display:"flex",alignItems:"center",gap:10}}>
        <div style={{width:34,height:34,borderRadius:"50%",background:`${C.teal}30`,border:`2px solid ${C.teal}60`,display:"flex",alignItems:"center",justifyContent:"center"}}>
          <span style={{color:C.tealLight,fontSize:12,fontWeight:900}}>GPA</span>
        </div>
        <div><div style={{fontFamily:F.display,fontSize:15,color:"#fff",letterSpacing:"-.02em",lineHeight:1}}>General de Productos para el Agua</div>
          <div style={{fontFamily:F.body,fontSize:9,color:C.tealLight,letterSpacing:".12em",textTransform:"uppercase"}}>ViaticOS · Sistema Integral de Viáticos</div>
        </div>
      </div>
      <div style={{flex:1}}/>
      <span style={{fontFamily:F.mono,fontSize:10,color:C.tealLight,opacity:.7}}>{VIAJE.folio}</span>
      <div style={{background:`${C.teal}20`,border:`1px solid ${C.teal}50`,borderRadius:20,padding:"3px 10px",fontFamily:F.body,fontSize:10,fontWeight:700,color:C.tealLight,letterSpacing:".06em"}}>DEMO INTEGRAL</div>
    </nav>

    {/* STEPPER */}
    <div style={{background:C.bgCard,borderBottom:`1px solid ${C.border}`,padding:"0 16px",overflowX:"auto",flexShrink:0}}>
      <div style={{display:"flex",gap:0,minWidth:"max-content"}}>
        {LABELS.map((lbl,i)=>{const a=i===paso,d=i<paso;return<div key={lbl} style={{display:"flex",alignItems:"center"}}>
          <button onClick={()=>ir(i)} style={{display:"flex",alignItems:"center",gap:5,padding:"12px 10px",background:"transparent",border:"none",borderBottom:`2.5px solid ${a?C.teal:"transparent"}`,color:a?C.tealDark:d?C.teal:C.inkFaint,cursor:"pointer",fontFamily:F.body,fontSize:11,fontWeight:a?700:400,transition:"all .15s"}}>
            <span style={{fontFamily:F.mono,fontSize:9,opacity:.8}}>{d?"✓":String(i+1).padStart(2,"0")}</span>{lbl}
          </button>
          {i<LABELS.length-1&&<div style={{width:8,height:".5px",background:d?`${C.teal}60`:C.border}}/>}
        </div>})}
      </div>
    </div>

    {/* BANNER */}
    <div style={{background:C.tealXL,borderBottom:`1px solid ${C.tealLight}`,padding:"10px 24px",display:"flex",gap:20,alignItems:"center",flexShrink:0}}>
      <div><div style={{fontFamily:F.mono,fontSize:9,color:C.teal,textTransform:"uppercase",letterSpacing:".1em"}}>Caso · POL-TE01</div>
        <div style={{fontFamily:F.body,fontSize:12,color:C.navy,fontWeight:700}}>{EMP.name} · {VIAJE.destino} · {VIAJE.ida} – {VIAJE.ret}</div>
      </div>
      <div style={{height:28,width:".5px",background:C.tealLight}}/>
      <div style={{fontFamily:F.body,fontSize:11,color:C.inkMid,flex:1}}>{VIAJE.motivo}</div>
      <div style={{display:"flex",gap:6}}>
        {[{i:EMP.av,c:C.blue},{i:SUP.av,c:C.navy},{i:FIN.av,c:C.teal}].map(a=><Avatar key={a.i} i={a.i} s={26} c={a.c}/>)}
      </div>
      <Chip l={`Paso: ${ACTORS[paso]}`} c={C.tealDark} bg={C.tealXL} bd={C.tealLight}/>
    </div>

    {/* CONTENIDO */}
    <div ref={bodyRef} style={{flex:1,overflowY:"auto",padding:"28px 24px",maxWidth:1060,width:"100%",margin:"0 auto",boxSizing:"border-box"}}>
      <Paso onNext={sig}/>
    </div>

    {/* PIE */}
    <div style={{background:C.navy,padding:"8px 24px",display:"flex",justifyContent:"space-between",alignItems:"center",flexShrink:0}}>
      <span style={{fontFamily:F.body,fontSize:10,color:C.tealLight,opacity:.7}}>General de Productos para el Agua S.A. de C.V. · Calzada del Águila #985-A, Guadalajara, Jalisco</span>
      <span style={{fontFamily:F.mono,fontSize:10,color:C.tealLight,opacity:.5}}>POL-TE01 v.01 · 15-Oct-25 — 15-Oct-28</span>
    </div>
  </div>;
}

/* ── Exposición global para index.html ─────────────────────────────────────── */
window.ViaticosDemo = ViaticosDemo;
window.VIATICOS_THEME = { C, F, POL };
window.ViaticosUI = { Avatar, Chip, Cd, Info, Bar, Head, Btn, Ghost };
