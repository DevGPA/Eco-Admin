// Botón «Anclar en mi teléfono»: solo debe aparecer cuando la app se abre desde
// el NAVEGADOR, y comportarse distinto en Android (instalación nativa) y en
// iPhone (instrucciones). Monta el componente real de frontend/index.html.
const {M,React,TR,windowStub,navegador}=require("./montar.js");
const act=TR.act;const h=React.createElement;
const ok=(c,m)=>{console.log((c?"  ✓":"  ✗ FALLA")+"  "+m);if(!c)process.exitCode=1;};
const plano=r=>r.toJSON()?JSON.stringify(r.toJSON()):"";
const bts=r=>r.root.findAllByType("button");
const bt=(r,t)=>bts(r).find(b=>JSON.stringify(b.props.children||"").includes(t));

const ANDROID="Mozilla/5.0 (Linux; Android 13) Chrome/120";
const IPHONE ="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari";
const IPAD   ="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari";
const ESCRITORIO="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/121";

const escenario=({ua,tactil=0,standalone=false})=>{
  navegador.userAgent=ua;navegador.maxTouchPoints=tactil;navegador.standalone=standalone;
  windowStub._standalone=standalone;
};
// El aviso que manda Chrome antes de ofrecer la instalación
const avisoChrome=(decision="accepted")=>{let llamado=false;
  return {llamado:()=>llamado,preventDefault(){},prompt(){llamado=true;},
          userChoice:Promise.resolve({outcome:decision})};};

(async()=>{
console.log("══ BOTÓN PARA ANCLAR LA APP ══\n");

console.log("── Ya está anclada (se abrió desde el ícono) ──");
escenario({ua:IPHONE,standalone:true});
let r;await act(async()=>{r=TR.create(h(M.BotonInstalar,{}));});
ok(r.toJSON()===null,"no se muestra nada: ya está instalada");
await act(async()=>{r.unmount();});

console.log("\n── Navegador de escritorio que no ofrece instalarla ──");
escenario({ua:ESCRITORIO});
let r0;await act(async()=>{r0=TR.create(h(M.BotonInstalar,{}));});
ok(r0.toJSON()===null,"no se muestra un botón que no haría nada");
await act(async()=>{r0.unmount();});

console.log("\n── Android / Chrome desde el navegador ──");
escenario({ua:ANDROID});
let r1;await act(async()=>{r1=TR.create(h(M.BotonInstalar,{}));});
ok(r1.toJSON()===null,"aún no aparece: el navegador no ha ofrecido instalarla");
const av=avisoChrome("accepted");
await act(async()=>{windowStub.dispatch("beforeinstallprompt",av);});
ok(!!bt(r1,"Anclar"),"al ofrecerla el navegador, SÍ aparece el botón");
ok(plano(r1).includes("Anclar en mi teléfono"),"con el texto completo por omisión");
await act(async()=>{bt(r1,"Anclar").props.onClick();});
await act(async()=>{await Promise.resolve();});
ok(av.llamado(),"al pulsarlo se dispara la instalación REAL del navegador");
ok(r1.toJSON()===null,"y aceptada, el botón desaparece");
await act(async()=>{r1.unmount();});

console.log("\n── Android, pero el usuario la rechaza ──");
escenario({ua:ANDROID});
let r2;await act(async()=>{r2=TR.create(h(M.BotonInstalar,{}));});
await act(async()=>{windowStub.dispatch("beforeinstallprompt",avisoChrome("dismissed"));});
ok(!!bt(r2,"Anclar"),"aparece el botón");
await act(async()=>{bt(r2,"Anclar").props.onClick();});
await act(async()=>{await Promise.resolve();});
ok(!!bt(r2,"Anclar"),"el botón NO desaparece: Chrome ya no reabre su aviso hasta recargar");
await act(async()=>{bt(r2,"Anclar").props.onClick();});
const t2=plano(r2);
ok(t2.includes("Instalar aplicación"),"ahora explica cómo hacerlo desde el menú del navegador");
ok(!t2.includes("Compartir"),"con las instrucciones de Android, no las de iPhone");
await act(async()=>{r2.unmount();});

console.log("\n── iPhone (Safari no ofrece instalación) ──");
escenario({ua:IPHONE});
let r3;await act(async()=>{r3=TR.create(h(M.BotonInstalar,{}));});
ok(!!bt(r3,"Anclar"),"el botón aparece sin esperar aviso del navegador");
await act(async()=>{bt(r3,"Anclar").props.onClick();});
const t3=plano(r3);
ok(t3.includes("Compartir"),"abre las instrucciones de iPhone (Compartir)");
ok(t3.includes("Agregar a inicio"),"y dice exactamente qué opción elegir");
ok(!t3.includes("Instalar aplicación"),"no mezcla las instrucciones de Android");
await act(async()=>{bt(r3,"Entendido").props.onClick();});
ok(!plano(r3).includes("Compartir"),"se cierran con «Entendido»");
await act(async()=>{r3.unmount();});

console.log("\n── iPad con iPadOS (se anuncia como Mac) ──");
escenario({ua:IPAD,tactil:5});
let r4;await act(async()=>{r4=TR.create(h(M.BotonInstalar,{}));});
ok(!!bt(r4,"Anclar"),"se detecta por el táctil y muestra el botón");
await act(async()=>{r4.unmount();});
escenario({ua:IPAD,tactil:0});          // Mac de verdad
let r5;await act(async()=>{r5=TR.create(h(M.BotonInstalar,{}));});
ok(r5.toJSON()===null,"una Mac de verdad no lo muestra");
await act(async()=>{r5.unmount();});

console.log("\n── Versión compacta (la del encabezado) ──");
escenario({ua:IPHONE});
let r6;await act(async()=>{r6=TR.create(h(M.BotonInstalar,{compacto:true}));});
ok(plano(r6).includes("⤓ Anclar")&&!plano(r6).includes("mi teléfono"),"texto corto para el encabezado");
await act(async()=>{r6.unmount();});

console.log("\n── Si la instalan desde el menú del navegador ──");
escenario({ua:ANDROID});
let r7;await act(async()=>{r7=TR.create(h(M.BotonInstalar,{}));});
await act(async()=>{windowStub.dispatch("beforeinstallprompt",avisoChrome());});
ok(!!bt(r7,"Anclar"),"el botón está");
await act(async()=>{windowStub.dispatch("appinstalled",{});});
ok(r7.toJSON()===null,"al instalarla por fuera, el botón se quita solo");
await act(async()=>{r7.unmount();});

console.log("\n── En la pantalla de inicio de sesión ──");
escenario({ua:IPHONE});
let r8;await act(async()=>{r8=TR.create(h(M.Login,{onLogin:async()=>{},onSetNewPassword:async()=>{}}));});
ok(!!bt(r8,"Anclar"),"quien aún no entra también puede anclarla");
escenario({ua:IPHONE,standalone:true});
await act(async()=>{r8.unmount();});
let r9;await act(async()=>{r9=TR.create(h(M.Login,{onLogin:async()=>{},onSetNewPassword:async()=>{}}));});
ok(!bt(r9,"Anclar"),"y estando ya anclada no estorba en el login");
console.log("\n══ fin ══");
})();
