/* ==========================================================================
   Sharky — interfaz de gestión
   Vanilla JS, sin dependencias. Todo dato dinámico pasa por `esc()` antes
   de entrar en el HTML; el HTML de las notas ya viene saneado del servidor
   (markdown-it sin HTML crudo).
   ========================================================================== */
"use strict";

const TOKEN = document.querySelector('meta[name="sharky-token"]').content;
const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => Array.from(raiz.querySelectorAll(sel));

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

// --------------------------------------------------------------- formato
// "always": en español Intl no agrupa miles hasta 5 cifras (1234,56 €).
const nf = (dec) => new Intl.NumberFormat("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: "always" });
const NF2 = nf(2), NF1 = nf(1), NF0 = nf(0);
const eur = (v) => (v == null ? "—" : `${NF2.format(v)} €`);
const eurSigno = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${NF2.format(v)} €`);
const pct = (v, signo = false, dec = 2) =>
  v == null ? "—" : `${signo && v > 0 ? "+" : ""}${nf(dec).format(v)} %`;
const tono = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const precio = (v) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  return (a >= 1000 ? NF2 : a >= 1 ? NF2 : nf(4)).format(v);
};
const fecha = (iso, opciones = { day: "numeric", month: "short", year: "numeric" }) => {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return isNaN(d) ? iso : d.toLocaleDateString("es-ES", opciones);
};
const fechaHora = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};
const hoyISO = () => new Date().toLocaleDateString("sv-SE");
const legible = (t) => String(t ?? "").replace(/_/g, " ");
const nombreArchivo = (ruta) => String(ruta || "").split(/[\\/]/).pop().replace(/\.md$/i, "");

const ESTADOS = {
  OPTIMO: "Óptimo",
  ALERTA: "Alerta",
  CUIDADOS_INTENSIVOS: "Cuidados intensivos",
  MUERTE: "Muerte",
};

// --------------------------------------------------------------- iconos
const ICONOS = {
  panel: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  informes: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
  operar: '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
  sistema: '<path d="M21 4h-7"/><path d="M10 4H3"/><path d="M21 12h-9"/><path d="M8 12H3"/><path d="M21 20h-5"/><path d="M12 20H3"/><path d="M14 2v4"/><path d="M8 10v4"/><path d="M16 18v4"/>',
  refrescar: '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
  alerta: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  ok: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  objetivo: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  cerrar: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  luna: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  sol: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  auto: '<circle cx="12" cy="12" r="10"/><path d="M12 18a6 6 0 0 0 0-12v12z"/>',
  volver: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  calendario: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
  noticias: '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>',
  estudio: '<path d="M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/>',
  apagar: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>',
};
const ico = (nombre) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONOS[nombre] || ""}</svg>`;

// --------------------------------------------------------------- API
async function api(ruta, { metodo = "GET", cuerpo } = {}) {
  const opciones = { method: metodo, headers: { "X-Sharky-Token": TOKEN } };
  if (cuerpo !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(cuerpo);
  }
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch {
    throw new Error("No hay conexión con la app de Sharky. ¿Se ha cerrado el servidor?");
  }
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(datos.error || `Error ${respuesta.status}`);
  return datos;
}

function aviso(texto, error = false) {
  const el = document.createElement("div");
  el.className = `aviso-toast${error ? " error" : ""}`;
  el.textContent = texto;
  $("#avisos").append(el);
  setTimeout(() => el.remove(), error ? 7000 : 4000);
}

// Anchos y posiciones dinámicos por CSSOM: la CSP bloquea `style=""`.
function aplicarGeometria(raiz) {
  $$("[data-ancho]", raiz).forEach((el) => (el.style.width = `${Math.max(0, Math.min(100, +el.dataset.ancho))}%`));
  $$("[data-izq]", raiz).forEach((el) => (el.style.left = `${Math.max(0, Math.min(100, +el.dataset.izq))}%`));
}

// --------------------------------------------------------------- tema
const TEMAS = ["auto", "oscuro", "claro"];
function temaGuardado() {
  try { return localStorage.getItem("sharky-tema") || "auto"; } catch { return "auto"; }
}
function aplicarTema(tema) {
  if (tema === "auto") delete document.documentElement.dataset.tema;
  else document.documentElement.dataset.tema = tema;
  try { localStorage.setItem("sharky-tema", tema); } catch { /* sin almacenamiento */ }
}
function botonTema() {
  const tema = temaGuardado();
  const icono = tema === "oscuro" ? "luna" : tema === "claro" ? "sol" : "auto";
  const nombre = { auto: "Tema del sistema", oscuro: "Tema oscuro", claro: "Tema claro" }[tema];
  return `<button class="btn-icono" data-accion="tema" title="${nombre}" aria-label="${nombre}">${ico(icono)}</button>`;
}

// --------------------------------------------------------------- estado
const estado = {
  panel: null,
  cargandoPanel: null,
  acciones: [],
  trabajo: null,
  sondeo: null,
  sistema: null,
  ordenPos: { campo: "valor_eur", desc: true },
  informes: { tipo: "diario", notas: [], tipos: {}, filtro: "" },
};

// --------------------------------------------------------------- navegación
const RUTAS = [
  { clave: "panel", titulo: "Panel", icono: "panel" },
  { clave: "informes", titulo: "Informes", icono: "informes" },
  { clave: "operar", titulo: "Operar", icono: "operar" },
  { clave: "sistema", titulo: "Sistema", icono: "sistema" },
];

function pintarNav(activa) {
  const atencion = estado.panel ? itemsAtencion(estado.panel).filter((i) => i.tono === "critico").length : 0;
  $("#nav").innerHTML = RUTAS.map(
    (r) => `<a href="#/${r.clave}" class="${r.clave === activa ? "activo" : ""}" ${r.clave === activa ? 'aria-current="page"' : ""}>
      ${ico(r.icono)}<span>${r.titulo}</span>
      ${r.clave === "panel" && atencion ? `<span class="contador" title="${atencion} aviso(s) crítico(s)">${atencion}</span>` : ""}
    </a>`
  ).join("");
}

function pintarEstadoIA() {
  const s = estado.sistema;
  const t = estado.trabajo;
  const trabajando = t && t.estado === "en_curso";
  $("#estado-ia").innerHTML = `
    ${trabajando ? `<div class="chip-ia"><span class="punto trabajando"></span><span>${esc(t.titulo)}…</span></div>` : ""}
    ${s ? `<div class="chip-ia" title="${esc(s.boveda)}">
      <span class="punto ${s.api_conectada ? "ok" : "mal"}"></span>
      <span>${s.api_conectada ? `Claude · ${esc(s.modelo)}` : "Sin API: modo simulación"}</span>
    </div>` : ""}`;
}

function cabecera(titulo, subtitulo = "", acciones = "") {
  $("#titulo").textContent = titulo;
  $("#subtitulo").textContent = subtitulo;
  $("#cabecera-acciones").innerHTML = acciones + botonTema();
  document.title = `${titulo} · Sharky`;
}

async function navegar() {
  const partes = location.hash.replace(/^#\/?/, "").split("/");
  const ruta = partes[0] || "panel";
  pintarNav(ruta === "nota" ? "informes" : ruta);
  window.scrollTo(0, 0);
  try {
    if (ruta === "panel") await vistaPanel();
    else if (ruta === "informes") await vistaInformes(partes[1] || estado.informes.tipo, partes[2] ? decodeURIComponent(partes.slice(2).join("/")) : null);
    else if (ruta === "nota") await abrirNotaPorNombre(decodeURIComponent(partes.slice(1).join("/")));
    else if (ruta === "operar") await vistaOperar();
    else if (ruta === "sistema") await vistaSistema();
    else location.hash = "#/panel";
  } catch (e) {
    $("#vista").innerHTML = `<div class="tarjeta error-carga"><strong>No se pudo cargar esta vista.</strong><span class="tenue">${esc(e.message)}</span>
      <button class="btn" data-accion="reintentar">${ico("refrescar")}Reintentar</button></div>`;
  }
}

// ======================================================================
// Panel
// ======================================================================
async function cargarPanel(refrescar = false) {
  if (estado.cargandoPanel && !refrescar) return estado.cargandoPanel;
  estado.cargandoPanel = api(`/api/panel${refrescar ? "?refrescar=1" : ""}`)
    .then((p) => (estado.panel = p))
    .finally(() => (estado.cargandoPanel = null));
  return estado.cargandoPanel;
}

async function vistaPanel(refrescar = false) {
  const acciones = `<button class="btn" data-accion="refrescar" id="btn-refrescar">${ico("refrescar")}Actualizar precios</button>`;
  cabecera("Panel", estado.panel ? `Valorado a mercado · ${fechaHora(estado.panel.generado)}` : "Valorando la cartera a mercado…", acciones);
  if (!estado.panel || refrescar) {
    if (!estado.panel) {
      $("#vista").innerHTML = `<div class="hero"><div class="esqueleto alto"></div><div class="esqueleto alto"></div></div>
        <div class="esqueleto medio"></div><div class="esqueleto alto"></div>`;
    }
    const boton = $("#btn-refrescar");
    boton?.classList.add("girando");
    boton && (boton.disabled = true);
    await cargarPanel(refrescar);
  }
  if (!location.hash.startsWith("#/panel") && location.hash !== "" && location.hash !== "#/") return;
  const p = estado.panel;
  cabecera("Panel", `Valorado a mercado · ${fechaHora(p.generado)}`, acciones);
  pintarNav("panel");
  $("#vista").innerHTML = htmlPanel(p);
  aplicarGeometria($("#vista"));
}

function itemsAtencion(p) {
  const items = [];
  for (const n of p.niveles) {
    if (n.tipo === "STOP_LOSS") {
      items.push({ tono: "critico", icono: "alerta", titulo: `Stop-loss alcanzado · ${n.ticker}`, sub: `${n.texto} El mandato exige liquidar la posición.` });
    } else if (n.tipo === "TAKE_PROFIT") {
      items.push({ tono: "info", icono: "objetivo", titulo: `Objetivo alcanzado · ${n.ticker}`, sub: n.texto });
    }
  }
  for (const b of p.incumplimientos) {
    items.push({
      tono: b.severidad === "ALTA" ? "critico" : "aviso",
      icono: "alerta",
      titulo: `${b.regla}${b.sujeto ? ` · ${b.sujeto}` : ""}`,
      sub: `${b.mensaje}${b.accion ? ` → ${b.accion}` : ""}`,
    });
  }
  for (const n of p.niveles.filter((x) => !x.accionable)) {
    items.push({ tono: "aviso", icono: "info", titulo: `Nivel no verificable · ${n.ticker}`, sub: n.texto });
  }
  for (const a of p.cartera.advertencias) {
    items.push({ tono: "aviso", icono: "info", titulo: "Calidad de los datos", sub: a });
  }
  return items;
}

function htmlPanel(p) {
  const s = p.salud, c = p.cartera, l = p.limites;
  const atencion = itemsAtencion(p);
  const conTesis = c.posiciones.filter((x) => x.tesis).length;
  const graves = p.incumplimientos.filter((b) => b.severidad === "ALTA").length;
  const ddRelleno = (s.drawdown_pct / l.dd_muerte_pct) * 100;
  const ddTono = s.drawdown_pct <= l.dd_optimo_pct ? "pos" : s.drawdown_pct <= l.dd_alerta_pct ? "aviso" : "neg";

  return `
  <section class="hero">
    <div class="tarjeta estado-vital">
      <div class="fila">
        <span class="insignia ${esc(s.estado)}">${esc(ESTADOS[s.estado] || s.estado)}</span>
        <span class="tenue">Salud ${pct(s.salud_pct, false, 1)} · Energía ${NF1.format(s.energia)}/100</span>
      </div>
      <div>
        <div class="tenue">Patrimonio (NAV)</div>
        <div class="nav-grande num">${eur(s.nav)}</div>
        <div class="num ${tono(s.pnl_ref_eur)}">${eurSigno(s.pnl_ref_eur)} (${pct(s.pnl_ref_pct, true)}) sobre la referencia</div>
      </div>
      <div class="medidor">
        <div class="etiquetas"><span>Drawdown ${pct(s.drawdown_pct)}</span><span>máx. ${pct(s.drawdown_maximo_pct)} · muerte ${pct(l.dd_muerte_pct, false, 0)}</span></div>
        <div class="pista" title="Óptimo hasta ${pct(l.dd_optimo_pct, false, 0)}, alerta hasta ${pct(l.dd_alerta_pct, false, 0)}">
          <span class="relleno ${ddTono}" data-ancho="${Math.max(ddRelleno, 1.5)}"></span>
          <span class="marca-limite" data-izq="${(l.dd_optimo_pct / l.dd_muerte_pct) * 100}"></span>
          <span class="marca-limite" data-izq="${(l.dd_alerta_pct / l.dd_muerte_pct) * 100}"></span>
        </div>
        <div class="etiquetas"><span>Máximo histórico ${eur(s.nav_maximo)}</span></div>
      </div>
    </div>
    <div class="tarjeta">
      <div class="tarjeta-cab"><h2>Resumen</h2><span class="tenue">Límites: activo ≤ ${pct(l.max_activo_pct, false, 0)} · sector ≤ ${pct(l.max_sector_pct, false, 0)} · caja ≥ ${pct(l.min_caja_pct, false, 0)}</span></div>
      <div class="kpis">
        ${kpi("PnL latente", eurSigno(c.pnl_latente_eur), `${pct(c.pnl_latente_pct, true)} sobre coste`, tono(c.pnl_latente_eur))}
        ${kpi("Liquidez", eur(c.efectivo), `${pct(c.efectivo_pct)} · objetivo ${pct(l.caja_objetivo_pct, false, 0)}`, c.efectivo_pct < l.min_caja_pct ? "neg" : "")}
        ${kpi("Posiciones", String(c.posiciones.length), `${conTesis} con tesis activa`)}
        ${kpi("Incumplimientos", String(p.incumplimientos.length), graves ? `${graves} grave(s)` : "ninguno grave", graves ? "neg" : "")}
        ${kpi("Cobertura de datos", pct(c.cobertura_pct, false, 1), "del NAV con precio fiable", c.cobertura_pct < 100 ? "neg" : "")}
        ${kpi("Último control", s.ultimo_ciclo ? fechaHora(s.ultimo_ciclo) : "Nunca", p.cadencia.diario.hecho_hoy ? "hecho hoy" : "pendiente hoy")}
      </div>
    </div>
  </section>

  <section class="rejilla dos">
    <div class="tarjeta">
      <div class="tarjeta-cab"><h2>Requiere atención</h2><span class="tenue">${atencion.length ? `${atencion.length} aviso(s)` : ""}</span></div>
      ${atencion.length ? `<div class="lista-atencion">${atencion.map((i) => `
        <div class="item-atencion ${i.tono}">${ico(i.icono)}<div><strong>${esc(i.titulo)}</strong><div class="sub">${esc(i.sub)}</div></div></div>`).join("")}</div>`
      : `<div class="todo-bien">${ico("ok")}Todo en orden: sin niveles alcanzados ni incumplimientos.</div>`}
    </div>
    <div class="tarjeta grafico">
      <div class="tarjeta-cab"><h2>Evolución del NAV</h2><span class="tenue">${p.historial.length} control(es) diario(s)</span></div>
      ${graficoNAV(p.historial)}
    </div>
  </section>

  <section class="rejilla tres">
    ${tarjetaDiario(p)}
    ${tarjetaSemanal(p)}
    ${tarjetaMensual(p)}
  </section>

  <section class="tarjeta">
    <div class="tarjeta-cab"><h2>Posiciones</h2><span class="tenue">Variación desde el último control · resaltado a partir de ±${NF0.format(l.umbral_movimiento_pct)} %</span></div>
    <div class="tabla-envoltorio">${tablaPosiciones(p)}</div>
  </section>

  <section class="rejilla dos">
    <div class="tarjeta">
      <div class="tarjeta-cab"><h2>Exposición sectorial</h2><span class="tenue">Límite ${pct(l.max_sector_pct, false, 0)} por sector</span></div>
      ${barrasSectores(c.sectores, l.max_sector_pct)}
    </div>
    ${tarjetaRadar(p)}
  </section>`;
}

// El radar tiene dos mitades y la tarjeta enseña las dos: las alertas vivas
// (lo que el filtro cuantitativo ya confirmó) y el botón para salir a buscar
// ideas nuevas. Sin la segunda, una lista vacía no distingue "hoy no cualifica
// nada" de "nadie ha buscado nunca".
// Qué le ha pasado a la convicción al registrar la operación: una compra
// desde una alerta abre tesis y consume la alerta; una venta que deja la
// posición a cero la archiva. Sin enseñarlo, registrar una venta parecía
// dejar viva una tesis que ya no tiene posición detrás.
function cicloDeVida(r) {
  const filas = [
    r.tesis_abierta && ["🎯", "Tesis abierta", r.tesis_abierta,
      "La posición ya tiene un stop vigilado."],
    r.tesis_cerrada && ["📁", "Tesis archivada", r.tesis_cerrada,
      "Movida a 02_Tesis_Cerradas: el motor ya no la propondrá como compra."],
    r.alerta_actualizada && ["✅", "Alerta ejecutada", r.alerta_actualizada,
      "Sale del radar activo y su ticker vuelve a quedar libre."],
  ].filter(Boolean);
  if (!filas.length) return "";
  return `<div class="ciclo-vida">${filas.map(([ico, titulo, archivo, nota]) => `
    <div class="item-atencion"><span class="emoji">${ico}</span>
      <div><strong>${esc(titulo)}</strong>
        <div class="sub">${esc(nota)}</div>
        <button class="btn pequeno" data-nota="${esc(nombreArchivo(archivo))}">Ver nota</button>
      </div></div>`).join("")}</div>`;
}

function tarjetaRadar(p) {
  const e = p.exploracion;
  const accion = estado.acciones.find((a) => a.clave === "explorar");
  const resumen = e
    ? `Última exploración ${esc(fecha(e.fecha))} · ${e.candidatos} candidato(s), ${e.alertas} alerta(s)`
    : "El mercado nunca se ha explorado desde aquí.";
  return `
    <div class="tarjeta radar">
      <div class="tarjeta-cab"><h2>Oportunidades en radar</h2><span class="tenue">${p.oportunidades.length} activa(s)</span></div>
      ${p.oportunidades.length ? `<div class="oportunidades">${p.oportunidades.map((o) => `
        <div class="oportunidad">
          <button class="enlace-nota" data-nota-ticker="${esc(o.ticker)}"><span class="activo-celda"><span class="ticker">${esc(o.ticker)}</span><span class="nombre">${esc(o.empresa)}</span></span></button>
          <div class="datos num">Convicción ${o.conviccion}/10 · R:R ${NF2.format(o.ratio_rr)}<br><span class="pos">+${NF1.format(o.potencial_pct)} %</span> · stop ${precio(o.stop)} ${esc(o.divisa)}</div>
        </div>`).join("")}</div>`
      : `<div class="vacio">Ningún candidato cualifica ahora mismo.</div>`}
      <div class="pie">
        <span class="coste">${resumen}${accion ? ` · ${esc(accion.coste)}` : ""}</span>
        <span>
          ${e ? `<button class="btn pequeno" data-nota-id="${esc(e.id)}">Ver informe</button>` : ""}
          <button class="btn pequeno primario" data-lanzar="explorar">${ico("objetivo")}Buscar oportunidades</button>
        </span>
      </div>
    </div>`;
}

function kpi(etiqueta, valor, detalle = "", claseValor = "") {
  return `<div class="kpi"><div class="etiqueta">${esc(etiqueta)}</div><div class="valor num ${claseValor}">${esc(valor)}</div><div class="detalle">${esc(detalle)}</div></div>`;
}

function graficoNAV(historial) {
  const puntos = historial.filter((h) => h.nav != null);
  if (puntos.length < 2) return `<div class="vacio">Hace falta al menos dos controles diarios para dibujar la evolución.</div>`;
  const valores = puntos.map((h) => +h.nav);
  let min = Math.min(...valores), max = Math.max(...valores);
  const margen = (max - min) * 0.12 || max * 0.01 || 1;
  min -= margen; max += margen;
  const W = 600, H = 170;
  const x = (i) => (i / (puntos.length - 1)) * W;
  const y = (v) => H - ((v - min) / (max - min)) * H;
  const linea = valores.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${linea} L${W},${H} L0,${H} Z`;
  const guias = [0.25, 0.5, 0.75].map((f) => `<line class="rejilla-linea" x1="0" x2="${W}" y1="${H * f}" y2="${H * f}"/>`).join("");
  const primero = valores[0], ultimo = valores[valores.length - 1];
  const variacion = ((ultimo - primero) / primero) * 100;
  return `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Evolución del NAV">
      ${guias}<path class="area" d="${area}"/><path class="linea" d="${linea}"/>
    </svg>
    <div class="grafico-ejes num">
      <span>${fecha(puntos[0].fecha)}</span>
      <span>mín. ${eur(Math.min(...valores))} · máx. ${eur(Math.max(...valores))} · <span class="${tono(variacion)}">${pct(variacion, true)}</span></span>
      <span>${fecha(puntos[puntos.length - 1].fecha)}</span>
    </div>`;
}

// Markdown mínimo de las conclusiones: **negrita** y [[wikilinks]]
// clicables. Se escapa primero y se formatea después.
function enLinea(texto) {
  return esc(texto)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[\[([^\[\]|#]+?)(?:#[^\[\]|]*)?(?:\\?\|([^\[\]]+?))?\]\]/g,
      (_, destino, alias) => `<a href="#" class="wikilink" data-nota="${destino.trim()}">${(alias || destino).trim()}</a>`);
}

function listaConclusion(texto) {
  const lineas = String(texto || "").split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lineas.length) return "";
  const vinetas = lineas.every((l) => /^[-*•]\s/.test(l));
  return vinetas
    ? `<ul>${lineas.map((l) => `<li>${enLinea(l.replace(/^[-*•]\s+/, ""))}</li>`).join("")}</ul>`
    : lineas.map((l) => `<div>${enLinea(l)}</div>`).join("");
}

function tarjetaCadencia({ icono, titulo, chip, estadoTexto, conclusion, fechaConclusion, clave, boton, nota }) {
  const accion = estado.acciones.find((a) => a.clave === clave);
  return `
  <div class="tarjeta cadencia">
    <div class="cab"><h3>${titulo}</h3>${chip}</div>
    <div class="estado">${estadoTexto}</div>
    <div class="conclusion">${conclusion
      ? `${fechaConclusion ? `<span class="fecha">Conclusión · ${esc(fechaConclusion)}</span>` : ""}${listaConclusion(conclusion)}`
      : `<span class="tenue">Todavía no hay conclusión registrada.</span>`}</div>
    <div class="pie">
      <span class="coste">${accion ? esc(accion.coste) : ""}</span>
      <span>
        ${nota ? `<button class="btn pequeno" data-nota-id="${esc(nota)}">Ver informe</button>` : ""}
        <button class="btn pequeno primario" data-lanzar="${clave}">${ico(icono)}${boton}</button>
      </span>
    </div>
  </div>`;
}

function tarjetaDiario(p) {
  const d = p.cadencia.diario;
  return tarjetaCadencia({
    icono: "play", titulo: "Control diario", clave: "diario", boton: "Ejecutar",
    chip: d.hecho_hoy ? `<span class="chip ok">Hecho hoy</span>` : `<span class="chip aviso">Pendiente</span>`,
    estadoTexto: d.ultimo ? `Último control: ${esc(fechaHora(d.ultimo))}` : "Todavía no se ha ejecutado ningún control.",
    conclusion: d.conclusion, fechaConclusion: d.fecha_conclusion ? fecha(d.fecha_conclusion) : "",
    nota: d.fecha_conclusion ? `05_Diario_Reflexion/${d.fecha_conclusion}_Cierre_Mercado.md` : null,
  });
}

function tarjetaSemanal(p) {
  const s = p.cadencia.semanal;
  return tarjetaCadencia({
    icono: "noticias", titulo: "Noticias semanales", clave: "noticias", boton: "Buscar noticias",
    chip: s.pendiente ? `<span class="chip aviso">Toca hoy</span>` : `<span class="chip">Próximo ${esc(fecha(s.proximo, { day: "numeric", month: "short" }))}</span>`,
    estadoTexto: s.ultimo ? `Último escaneo: ${esc(fecha(s.ultimo))}` : "Todavía no se ha hecho ningún escaneo.",
    conclusion: s.conclusion, fechaConclusion: s.ultimo ? fecha(s.ultimo) : "",
    nota: s.ultimo ? `04_Sentimiento_Y_Flujos/Noticias_Semanales/${s.ultimo}_Noticias_Semanales.md` : null,
  });
}

function tarjetaMensual(p) {
  const m = p.cadencia.mensual;
  const u = m.ultimo || {};
  let chip = `<span class="chip ok">Hecho</span>`;
  if (m.pendiente) chip = `<span class="chip aviso">Pendiente</span>`;
  else if (u.simulado) chip = `<span class="chip aviso">Sin Claude</span>`;
  return tarjetaCadencia({
    icono: "estudio", titulo: "Estudio mensual", clave: "estudio", boton: "Ejecutar estudio",
    chip,
    estadoTexto: u.mes ? `Último estudio: ${esc(u.mes)}${u.fecha ? ` (${esc(fecha(u.fecha))})` : ""}` : `Aún no hay estudio de ${esc(m.mes_actual)}.`,
    conclusion: u.conclusion, fechaConclusion: u.mes || "",
    nota: u.id || null,
  });
}

const COLUMNAS = [
  { campo: "ticker", titulo: "Activo" },
  { campo: "sector", titulo: "Sector" },
  { campo: "precio", titulo: "Cotización", der: true, sinOrden: true },
  { campo: "valor_eur", titulo: "Valor", der: true },
  { campo: "peso_pct", titulo: "Peso", der: true },
  { campo: "pnl_eur", titulo: "PnL €", der: true },
  { campo: "pnl_pct", titulo: "PnL %", der: true },
  { campo: "variacion_pct", titulo: "Var.", der: true },
  { campo: "niveles", titulo: "Stop / Objetivo", der: true, sinOrden: true },
];

function tablaPosiciones(p) {
  const { campo, desc } = estado.ordenPos;
  const l = p.limites;
  const filas = [...p.cartera.posiciones].sort((a, b) => {
    const va = a[campo] ?? -Infinity, vb = b[campo] ?? -Infinity;
    const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return desc ? -r : r;
  });
  const escala = l.max_activo_pct * 1.6;
  return `<table class="tabla">
    <thead><tr>${COLUMNAS.map((c) => `<th class="${c.der ? "der" : ""} ${c.sinOrden ? "" : "ordenable"} ${c.campo === campo ? "orden-activo" : ""}" ${c.sinOrden ? "" : `data-orden="${c.campo}"`}>${c.titulo}${c.campo === campo ? (desc ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
    <tbody>${filas.map((x) => {
      const excede = x.peso_pct > l.max_activo_pct;
      const fuerte = x.variacion_pct != null && Math.abs(x.variacion_pct) >= l.umbral_movimiento_pct;
      return `<tr>
        <td><button class="enlace-nota" ${x.nota ? `data-nota="${esc(x.nota)}"` : `data-nota-ticker="${esc(x.ticker)}"`} title="Abrir la nota del activo">
          <span class="activo-celda"><span class="ticker">${esc(x.ticker)}</span><span class="nombre">${esc(x.nombre)}</span></span></button></td>
        <td class="tenue">${esc(legible(x.sector))}</td>
        <td class="der num">${precio(x.precio)} ${esc(x.divisa)}${x.fiable ? "" : ` <span class="no-fiable" title="Precio no fiable (${esc(x.fuente)})">⚠</span>`}</td>
        <td class="der num">${eur(x.valor_eur)}</td>
        <td class="der"><div class="peso-celda"><span class="num ${excede ? "neg destacado" : ""}">${pct(x.peso_pct)}</span>
          <span class="pista"><span class="relleno ${excede ? "neg" : ""}" data-ancho="${(x.peso_pct / escala) * 100}"></span><span class="marca-limite" data-izq="${(l.max_activo_pct / escala) * 100}"></span></span></div></td>
        <td class="der num ${tono(x.pnl_eur)}">${eurSigno(x.pnl_eur)}</td>
        <td class="der num ${tono(x.pnl_pct)}">${pct(x.pnl_pct, true)}</td>
        <td class="der num ${tono(x.variacion_pct)} ${fuerte ? "destacado" : ""}">${x.variacion_pct == null ? "—" : pct(x.variacion_pct, true)}</td>
        <td class="der num tenue">${x.tesis ? `${precio(x.tesis.stop)} / ${precio(x.tesis.target)} ${esc(x.tesis.divisa)}` : "—"}</td>
      </tr>`;
    }).join("")}</tbody>
    <tfoot class="pie-tabla">
      <tr><td>Efectivo</td><td></td><td></td><td class="der num">${eur(p.cartera.efectivo)}</td><td class="der num">${pct(p.cartera.efectivo_pct)}</td><td colspan="4"></td></tr>
      <tr><td>NAV total</td><td></td><td></td><td class="der num">${eur(p.cartera.nav)}</td><td class="der num">100,00 %</td>
        <td class="der num ${tono(p.cartera.pnl_latente_eur)}">${eurSigno(p.cartera.pnl_latente_eur)}</td><td class="der num ${tono(p.cartera.pnl_latente_pct)}">${pct(p.cartera.pnl_latente_pct, true)}</td><td colspan="2"></td></tr>
    </tfoot>
  </table>`;
}

function barrasSectores(sectores, limite) {
  if (!sectores.length) return `<div class="vacio">Sin posiciones.</div>`;
  const escala = Math.max(limite * 1.6, ...sectores.map((s) => s.peso_pct));
  return `<div class="sectores">${sectores.map((s) => {
    const excede = s.peso_pct > limite;
    return `<div class="sector">
      <div class="cab"><span>${esc(legible(s.sector))}</span><span class="num ${excede ? "neg destacado" : ""}">${pct(s.peso_pct)}</span></div>
      <div class="pista"><span class="relleno ${excede ? "neg" : ""}" data-ancho="${(s.peso_pct / escala) * 100}"></span><span class="marca-limite" data-izq="${(limite / escala) * 100}"></span></div>
    </div>`;
  }).join("")}</div>`;
}

// ======================================================================
// Informes
// ======================================================================
const PREFIJOS_TIPO = [
  ["estudios", /^08_Rebalanceos_Mensuales\/.*_Estudio_Mensual\.md$/],
  ["rebalanceos", /^08_Rebalanceos_Mensuales\//],
  ["noticias", /^04_Sentimiento_Y_Flujos\/Noticias_Semanales\//],
  ["diario", /^05_Diario_Reflexion\//],
  ["operaciones", /^04_Operaciones_Bitacora\//],
  ["tesis", /^01_Tesis_Activas\//],
  // Antes que el prefijo general de la carpeta: una exploracion vive dentro
  // de 09_Alertas_Oportunidades pero tiene pestana propia.
  ["exploraciones", /^09_Alertas_Oportunidades\/Exploraciones\//],
  ["alertas", /^09_Alertas_Oportunidades\//],
];
const tipoDeNota = (id) => (PREFIJOS_TIPO.find(([, re]) => re.test(id)) || [null])[0];

async function abrirNotaPorNombre(nombre) {
  let nota;
  try {
    nota = await api(`/api/nota?nombre=${encodeURIComponent(nombre)}`);
  } catch (e) {
    // Enlace roto en la bóveda: se avisa y se vuelve a donde estabas.
    aviso(e.message, true);
    if (history.length > 1) history.back();
    else location.hash = "#/informes";
    return;
  }
  const tipo = tipoDeNota(nota.id) || estado.informes.tipo;
  history.replaceState(null, "", `#/informes/${tipo}/${encodeURIComponent(nota.id)}`);
  await vistaInformes(tipo, nota.id, nota);
}

async function vistaInformes(tipo, notaId = null, notaPrecargada = null) {
  cabecera("Informes", "Todo lo que Sharky ha escrito en la bóveda");
  pintarNav("informes");
  const cambiaTipo = tipo !== estado.informes.tipo || !estado.informes.notas.length;
  estado.informes.tipo = tipo;

  if (!$("#vista .informes") || cambiaTipo) {
    $("#vista").innerHTML = `
      <div class="pestanas" id="pestanas" role="tablist"></div>
      <div class="informes ${notaId ? "leyendo" : ""}">
        <div class="tarjeta lista-notas">
          <div class="buscar"><input type="search" id="filtro-notas" placeholder="Filtrar por título o fecha…" value="${esc(estado.informes.filtro)}" aria-label="Filtrar informes"></div>
          <ul id="lista-notas"><li class="vacio">Cargando…</li></ul>
        </div>
        <div class="tarjeta lector" id="lector"></div>
      </div>`;
    const datos = await api(`/api/informes?tipo=${encodeURIComponent(tipo)}`);
    estado.informes.notas = datos.notas;
    estado.informes.tipos = datos.tipos;
  }
  $("#vista .informes").classList.toggle("leyendo", !!notaId);
  $("#pestanas").innerHTML = Object.entries(estado.informes.tipos).map(([clave, titulo]) =>
    `<button role="tab" class="${clave === tipo ? "activo" : ""}" aria-selected="${clave === tipo}" data-tipo="${clave}">${esc(titulo)}</button>`).join("");
  pintarListaNotas(notaId);

  const lector = $("#lector");
  if (!notaId) {
    const primera = estado.informes.notas[0];
    lector.innerHTML = primera && window.innerWidth > 820
      ? `<div class="vacio">Elige un informe de la lista.</div>`
      : `<div class="vacio">${primera ? "Elige un informe de la lista." : "Todavía no hay informes de este tipo."}</div>`;
    return;
  }
  lector.innerHTML = `<div class="esqueleto medio"></div>`;
  const nota = notaPrecargada || (await api(`/api/nota?id=${encodeURIComponent(notaId)}`));
  const meta = nota.meta || {};
  const chips = [];
  if (meta.inteligencia_simulada) chips.push(`<span class="chip aviso">Generado sin Claude</span>`);
  if (meta.modelo) chips.push(`<span class="chip acento">${esc(meta.modelo)}</span>`);
  if (meta.disponible === false) chips.push(`<span class="chip aviso">Escaneo no disponible</span>`);
  lector.innerHTML = `
    <div class="lector-cab"><button class="btn pequeno volver" data-accion="volver-lista">${ico("volver")}Volver</button></div>
    ${chips.length ? `<div class="meta-nota">${chips.join("")}</div>` : ""}
    <article class="md">${nota.html}</article>`;
}

function pintarListaNotas(activa) {
  const filtro = estado.informes.filtro.trim().toLowerCase();
  const notas = estado.informes.notas.filter((n) => !filtro || `${n.titulo} ${n.fecha}`.toLowerCase().includes(filtro));
  $("#lista-notas").innerHTML = notas.length
    ? notas.map((n) => `<li><button class="${n.id === activa ? "activo" : ""}" data-nota-id="${esc(n.id)}">
        <span class="titulo-nota">${esc(n.titulo)}</span>
        <span class="chips"><span class="chip">${esc(n.fecha)}</span>${n.etiquetas.map((e) => `<span class="chip ${esc(e.tono)}">${esc(e.texto)}</span>`).join("")}</span>
      </button></li>`).join("")
    : `<li class="vacio">${estado.informes.notas.length ? "Ningún informe coincide con el filtro." : "Todavía no hay informes de este tipo."}</li>`;
}

// ======================================================================
// Operar
// ======================================================================
async function vistaOperar() {
  cabecera("Operar", "Registra una operación que ya has ejecutado en Trade Republic");
  if (!estado.panel) {
    $("#vista").innerHTML = `<div class="esqueleto alto"></div>`;
    await cargarPanel();
  }
  const p = estado.panel;
  $("#vista").innerHTML = `
  <div class="rejilla dos">
    <form class="tarjeta" id="form-operacion" novalidate>
      <div class="tarjeta-cab"><h2>Nueva operación</h2><span class="tenue">Pasa por el RiskGovernor antes de tocar el libro</span></div>
      <div class="formulario">
        <div class="campo ancho">
          <label>Sentido</label>
          <div class="segmentado" role="radiogroup" aria-label="Sentido de la operación">
            <label><input type="radio" name="tipo" value="COMPRA" checked><span class="compra">Compra</span></label>
            <label><input type="radio" name="tipo" value="VENTA"><span class="venta">Venta</span></label>
          </div>
        </div>
        <div class="campo"><label for="op-ticker">Ticker</label>
          <input id="op-ticker" name="ticker" list="lista-tickers" autocomplete="off" required placeholder="p. ej. MSFT">
          <datalist id="lista-tickers">${p.cartera.posiciones.map((x) => `<option value="${esc(x.ticker)}">${esc(x.nombre)}</option>`).join("")}</datalist>
        </div>
        <div class="campo"><label for="op-unidades">Unidades</label><input id="op-unidades" name="unidades" inputmode="decimal" required placeholder="0,5"></div>
        <div class="campo"><label for="op-precio">Precio de ejecución</label><input id="op-precio" name="precio" inputmode="decimal" required><span class="ayuda">En la divisa de cotización.</span></div>
        <div class="campo"><label for="op-divisa">Divisa</label><input id="op-divisa" name="divisa" maxlength="3" placeholder="La de la posición"></div>
        <div class="campo"><label for="op-comision">Comisión (€)</label><input id="op-comision" name="comision" inputmode="decimal" placeholder="1,00"></div>
        <div class="campo"></div>
        <div class="campo"><label for="op-stop">Stop-loss</label><input id="op-stop" name="stop" inputmode="decimal"><span class="ayuda">Obligatorio en compras según el mandato.</span></div>
        <div class="campo"><label for="op-target">Objetivo</label><input id="op-target" name="target" inputmode="decimal"><span class="ayuda">Obligatorio en compras según el mandato.</span></div>
        <div class="campo ancho"><label for="op-motivo">Motivo</label><textarea id="op-motivo" name="motivo" placeholder="Por qué ejecutas esta operación"></textarea></div>
        <details class="extra ancho">
          <summary>Posición nueva o datos adicionales</summary>
          <div class="formulario">
            <div class="campo"><label for="op-nombre">Nombre completo</label><input id="op-nombre" name="nombre"></div>
            <div class="campo"><label for="op-isin">ISIN</label><input id="op-isin" name="isin" maxlength="12"></div>
            <div class="campo"><label for="op-simbolo">Símbolo de cotización</label><input id="op-simbolo" name="simbolo" placeholder="p. ej. RHM.DE"></div>
            <div class="campo"><label for="op-sector">Sector</label><input id="op-sector" name="sector" list="lista-sectores">
              <datalist id="lista-sectores">${p.cartera.sectores.map((s) => `<option value="${esc(s.sector)}">`).join("")}</datalist></div>
            <div class="campo"><label for="op-clase">Clase de activo</label>
              <select id="op-clase" name="clase"><option value="ACCION">Acción</option><option value="ETF">ETF</option><option value="ETC">ETC</option><option value="CRIPTO">Cripto</option></select></div>
            <div class="campo"><label for="op-divisa-niveles">Divisa de stop/objetivo</label><input id="op-divisa-niveles" name="divisa_niveles" maxlength="3" placeholder="Si es distinta"></div>
            <div class="campo ancho"><label for="op-tesis">Tesis de referencia</label><input id="op-tesis" name="tesis" placeholder="Nota de tesis"></div>
          </div>
        </details>
        <label class="casilla ancho"><input type="checkbox" name="forzar">
          <span><strong>Registrar aunque incumpla el mandato</strong><br><span class="tenue">Sólo límites del mandato (topes, liquidez, stop, R:R). Nunca datos imposibles.</span></span></label>
        <div class="acciones-form ancho"><button type="reset" class="btn">Limpiar</button><button type="submit" class="btn primario">Revisar y registrar</button></div>
      </div>
    </form>
    <div class="rejilla">
      <div class="tarjeta" id="op-contexto"></div>
      <div id="op-resultado"></div>
    </div>
  </div>`;
  pintarContextoOperacion();
}

function pintarContextoOperacion() {
  const p = estado.panel;
  const ticker = ($("#op-ticker")?.value || "").trim().toUpperCase();
  const x = p.cartera.posiciones.find((pos) => pos.ticker === ticker);
  const l = p.limites;
  $("#op-contexto").innerHTML = `
    <div class="tarjeta-cab"><h2>${x ? esc(`${x.ticker} · ${x.nombre}`) : "Contexto"}</h2></div>
    ${x ? `<dl class="lista-datos">
        <dt>Unidades</dt><dd class="num">${nf(6).format(x.unidades)}</dd>
        <dt>Cotización</dt><dd class="num">${precio(x.precio)} ${esc(x.divisa)}</dd>
        <dt>Valor</dt><dd class="num">${eur(x.valor_eur)} (${pct(x.peso_pct)} del NAV)</dd>
        <dt>PnL</dt><dd class="num ${tono(x.pnl_eur)}">${eurSigno(x.pnl_eur)} (${pct(x.pnl_pct, true)})</dd>
        <dt>Tesis</dt><dd class="num">${x.tesis ? `stop ${precio(x.tesis.stop)} · objetivo ${precio(x.tesis.target)} ${esc(x.tesis.divisa)}` : "Sin tesis activa"}</dd>
      </dl>`
    : `<p class="tenue">${ticker ? "Posición nueva: completa nombre, símbolo y sector en «Posición nueva»." : "Escribe un ticker para ver su posición actual."}</p>`}
    <hr class="separador">
    <dl class="lista-datos">
      <dt>Liquidez</dt><dd class="num">${eur(p.cartera.efectivo)} (${pct(p.cartera.efectivo_pct)})</dd>
      <dt>Máx. por activo</dt><dd class="num">${pct(l.max_activo_pct, false, 1)}</dd>
      <dt>Máx. por sector</dt><dd class="num">${pct(l.max_sector_pct, false, 1)}</dd>
      <dt>Caja mínima</dt><dd class="num">${pct(l.min_caja_pct, false, 1)}</dd>
    </dl>`;
}

async function enviarOperacion(form) {
  const datos = Object.fromEntries(new FormData(form).entries());
  datos.forzar = !!form.elements.forzar.checked;
  datos.ticker = (datos.ticker || "").trim().toUpperCase();
  const num = (v) => parseFloat(String(v || "").replace(",", "."));
  if (!datos.ticker || !(num(datos.unidades) > 0) || !(num(datos.precio) > 0)) {
    aviso("Faltan ticker, unidades o precio (deben ser mayores que cero).", true);
    return;
  }
  const total = num(datos.unidades) * num(datos.precio);
  const venta = datos.tipo === "VENTA";
  const ok = await confirmar({
    titulo: `Registrar ${venta ? "venta" : "compra"} de ${datos.ticker}`,
    cuerpo: `${nf(6).format(num(datos.unidades))} × ${precio(num(datos.precio))} ${datos.divisa || ""} ≈ ${NF2.format(total)} ${datos.divisa || "(divisa de la posición)"}. Se escribirá en Cartera_Real.md y en la bitácora de operaciones.`,
    extra: datos.forzar ? "Has marcado registrar aunque incumpla el mandato." : "",
    aceptar: venta ? "Registrar venta" : "Registrar compra",
  });
  if (!ok) return;
  const boton = $("button[type=submit]", form);
  boton.disabled = true;
  try {
    const r = await api("/api/operaciones", { metodo: "POST", cuerpo: datos });
    $("#op-resultado").innerHTML = r.aprobada
      ? `<div class="tarjeta"><div class="resultado ok"><h3>Operación registrada</h3><p>${esc(r.motivo)}</p>
          <dl class="lista-datos"><dt>NAV posterior</dt><dd class="num">${eur(r.nav_posterior)}</dd><dt>Efectivo posterior</dt><dd class="num">${eur(r.efectivo_posterior)}</dd>
          ${r.pnl_realizado != null ? `<dt>PnL realizado</dt><dd class="num ${tono(r.pnl_realizado)}">${eurSigno(r.pnl_realizado)}</dd>` : ""}</dl>
          ${cicloDeVida(r)}
          ${r.nota ? `<p><button class="btn pequeno" data-nota="${esc(nombreArchivo(r.nota))}">Ver nota de la operación</button></p>` : ""}</div></div>`
      : `<div class="tarjeta"><div class="resultado mal"><h3>Rechazada por el RiskGovernor</h3><p>${esc(r.motivo)}</p><p class="tenue">El libro de posiciones no se ha modificado.</p></div></div>`;
    if (r.aprobada) {
      form.reset();
      estado.panel = null;
      await cargarPanel();
      pintarContextoOperacion();
    }
  } catch (e) {
    aviso(e.message, true);
  } finally {
    boton.disabled = false;
  }
}

// ======================================================================
// Sistema
// ======================================================================
async function vistaSistema() {
  cabecera("Sistema", "Configuración de la IA, acciones y estado de la app");
  const [sistema, trabajos] = await Promise.all([api("/api/sistema"), api("/api/trabajos")]);
  estado.sistema = sistema;
  estado.acciones = trabajos.acciones;
  pintarEstadoIA();
  $("#vista").innerHTML = `
  <div class="rejilla dos">
    <div class="tarjeta">
      <div class="tarjeta-cab"><h2>Inteligencia artificial</h2>${sistema.api_conectada ? `<span class="chip ok">API conectada</span>` : `<span class="chip negativo">Sin API</span>`}</div>
      <dl class="lista-datos"><dt>Modelo</dt><dd>${esc(sistema.modelo)}</dd><dt>Modelo de noticias</dt><dd>${esc(sistema.modelo_noticias)}</dd><dt>Modelo del explorador</dt><dd>${esc(sistema.modelo_explorador)}</dd><dt>Modelo de revisión</dt><dd>${esc(sistema.modelo_revision)}</dd></dl>
      <div class="tabla-envoltorio">
        <table class="tabla"><thead><tr><th>Nivel</th><th>Qué razona</th><th>Effort</th><th class="der">Máx. tokens</th></tr></thead>
        <tbody>${sistema.perfiles.map((f) => `<tr><td><strong>${esc(f.nivel)}</strong></td><td class="tenue">${esc(f.que)}</td><td>${esc(f.effort)}</td><td class="der num">${NF0.format(f.max_tokens)}</td></tr>`).join("")}</tbody></table>
      </div>
    </div>
    <div class="tarjeta">
      <div class="tarjeta-cab"><h2>Acciones</h2><span class="tenue">De una en una, en segundo plano</span></div>
      <div class="lista-atencion">${trabajos.acciones.map((a) => `
        <div class="item-atencion">${ico(a.usa_claude ? "estudio" : "play")}
          <div class="cadencia"><div class="cab"><strong>${esc(a.titulo)}</strong><button class="btn pequeno" data-lanzar="${esc(a.clave)}">Ejecutar</button></div>
          <div class="sub">${esc(a.descripcion)} <span class="coste">· ${esc(a.coste)}</span></div></div>
        </div>`).join("")}</div>
    </div>
  </div>
  <div class="tarjeta">
    <div class="tarjeta-cab"><h2>Historial de acciones</h2><span class="tenue">Desde que se abrió la app</span></div>
    ${trabajos.historial.length ? `<div class="tabla-envoltorio"><table class="tabla"><thead><tr><th>Acción</th><th>Inicio</th><th>Fin</th><th>Estado</th><th>Detalle</th></tr></thead><tbody>
      ${trabajos.historial.map((t) => `<tr><td>${esc(t.titulo)}</td><td class="num">${esc(fechaHora(t.inicio))}</td><td class="num">${t.fin ? esc(fechaHora(t.fin)) : "—"}</td>
        <td>${t.estado === "ok" ? `<span class="chip ok">Correcto</span>` : t.estado === "error" ? `<span class="chip negativo">Error</span>` : `<span class="chip acento">En curso</span>`}</td>
        <td class="tenue">${esc(t.error || "")}</td></tr>`).join("")}
    </tbody></table></div>` : `<div class="vacio">Todavía no se ha ejecutado ninguna acción.</div>`}
  </div>
  <div class="tarjeta">
    <div class="tarjeta-cab"><h2>App</h2></div>
    <dl class="lista-datos"><dt>Bóveda</dt><dd>${esc(sistema.boveda)}</dd><dt>En marcha desde</dt><dd>${esc(fechaHora(sistema.iniciado))}</dd></dl>
    <p class="tenue">Cerrar la ventana no detiene el servidor local. Apágalo aquí cuando termines.</p>
    <button class="btn peligro" data-accion="apagar">${ico("apagar")}Apagar la app</button>
  </div>`;
}

// ======================================================================
// Trabajos en segundo plano
// ======================================================================
async function cargarAcciones() {
  const t = await api("/api/trabajos");
  estado.acciones = t.acciones;
  if (t.actual) {
    estado.trabajo = t.actual;
    if (t.actual.estado === "en_curso") {
      pintarTrabajo();
      sondear();
    }
  }
  pintarEstadoIA();
}

async function lanzar(clave) {
  let accion = estado.acciones.find((a) => a.clave === clave);
  if (!accion) {
    try {
      await cargarAcciones();
    } catch (e) {
      aviso(e.message, true);
      return;
    }
    accion = estado.acciones.find((a) => a.clave === clave);
  }
  if (!accion) {
    // La página se sirve del disco en cada petición, pero las acciones viven
    // en la memoria del servidor: uno arrancado antes de añadir una acción no
    // la conoce. Mejor decirlo que no hacer nada.
    aviso("El servidor en marcha es anterior a esta versión y no conoce esta acción. Reinicia la app: Sistema › Apagar la app y vuelve a abrirla.", true);
    return;
  }
  if (estado.trabajo?.estado === "en_curso") {
    aviso(`Espera a que termine «${estado.trabajo.titulo}».`, true);
    return;
  }
  const c = estado.panel?.cadencia;
  let extra = "";
  if (clave === "diario" && c?.diario.hecho_hoy) extra = "El control de hoy ya se hizo: repetirlo reescribe el diario de hoy y vuelve a llamar a Claude.";
  if (clave === "estudio" && c && !c.mensual.pendiente) extra = "Este mes ya tiene estudio: se volverá a generar y lo sustituirá.";
  if (clave === "noticias" && c && !c.semanal.pendiente) extra = "Esta semana no toca escaneo todavía; puedes lanzarlo igualmente.";
  if (clave === "explorar") {
    const e = estado.panel?.exploracion;
    extra = "Busca en la web con el modelo más capaz de Claude: puede tardar varios minutos.";
    if (e) extra += ` La última exploración fue el ${fecha(e.fecha)}.`;
  }
  const ok = await confirmar({
    titulo: accion.titulo,
    cuerpo: accion.descripcion,
    coste: accion.usa_claude ? `Usa la API de Claude · ${accion.coste}` : "",
    extra,
    aceptar: "Ejecutar",
  });
  if (!ok) return;
  try {
    estado.trabajo = await api("/api/trabajos", { metodo: "POST", cuerpo: { accion: clave } });
    pintarTrabajo();
    pintarEstadoIA();
    sondear();
  } catch (e) {
    aviso(e.message, true);
  }
}

function sondear() {
  clearTimeout(estado.sondeo);
  estado.sondeo = setTimeout(async () => {
    try {
      const t = await api("/api/trabajos");
      estado.trabajo = t.actual;
      pintarTrabajo();
      pintarEstadoIA();
      if (t.actual?.estado === "en_curso") return sondear();
      alTerminar(t.actual);
    } catch (e) {
      aviso(e.message, true);
      sondear();
    }
  }, 1500);
}

async function alTerminar(t) {
  if (!t) return;
  aviso(t.estado === "ok" ? `${t.titulo}: terminado.` : `${t.titulo}: ha fallado.`, t.estado !== "ok");
  estado.panel = null;
  estado.informes.notas = [];
  const ruta = location.hash.replace(/^#\/?/, "").split("/")[0] || "panel";
  if (ruta === "panel") await vistaPanel();
  else if (ruta === "sistema") await vistaSistema();
  else cargarPanel().then(() => pintarNav(ruta)).catch(() => {});
}

function resumenTrabajo(t) {
  const r = t.resultado || {};
  const lineas = [];
  let nota = null, veredicto = null;
  switch (t.accion) {
    case "niveles":
      lineas.push(r.resumen || "Niveles revisados.", ...(r.avisos_niveles || []));
      break;
    case "diario":
      lineas.push(`${ESTADOS[r.estado_vital] || r.estado_vital} · NAV ${eur(r.nav_eur)} · drawdown ${pct(r.drawdown_actual_pct)}`);
      if (r.inteligencia_simulada) lineas.push("⚠ Control generado sin Claude: revisa el registro.");
      if (r.posiciones_a_vigilar?.length) lineas.push(`A vigilar: ${r.posiciones_a_vigilar.join(", ")}`);
      nota = nombreArchivo(r.diario_guardado);
      break;
    case "noticias":
      lineas.push(r.disponible ? `${r.busquedas_realizadas} búsquedas · ${r.num_fuentes} fuentes · ${r.dias_de_contexto} días de contexto` : `No disponible: ${r.error || "sin detalle"}`);
      nota = nombreArchivo(r.nota_guardada);
      break;
    case "estudio":
      lineas.push(r.estudio_simulado ? `⚠ Sin Claude: ${r.estudio_error || "revisa el registro"}` : `Estudio de ${r.mes} por ${r.modelo}`);
      lineas.push(`${r.num_propuestas} propuesta(s) en el plan de rebalanceo`);
      nota = nombreArchivo(r.estudio_guardado);
      break;
    case "rebalanceo":
      lineas.push(`${r.num_propuestas} propuesta(s) · caja objetivo ${pct(r.cash_objetivo_pct)}`);
      nota = nombreArchivo(r.archivo_informe);
      break;
    case "comite":
      lineas.push(r.veredicto_simulado ? "⚠ Resolución generada sin Claude." : `Resolución del CIO por ${r.modelo}`);
      veredicto = r.veredicto_cio;
      break;
  }
  return { lineas, nota, veredicto };
}

function pintarTrabajo() {
  const t = estado.trabajo;
  const panel = $("#trabajo");
  if (!t || t.oculto) { panel.hidden = true; return; }
  panel.hidden = false;
  const inicio = new Date(t.inicio);
  const fin = t.fin ? new Date(t.fin) : new Date();
  const seg = Math.max(0, Math.round((fin - inicio) / 1000));
  const duracion = `${Math.floor(seg / 60)}:${String(seg % 60).padStart(2, "0")}`;
  const log = (t.log || "").trim();

  if (t.estado === "en_curso") {
    panel.innerHTML = `<div class="cab"><span class="spinner"></span><strong>${esc(t.titulo)}</strong><span class="tenue num">${duracion}</span></div>
      <div class="tenue">En marcha. Puedes seguir usando la app mientras termina.</div>
      ${log ? `<pre class="log">${esc(log.slice(-4000))}</pre>` : ""}`;
    return;
  }
  const ok = t.estado === "ok";
  const { lineas, nota, veredicto } = ok ? resumenTrabajo(t) : { lineas: [t.error || "Error desconocido."], nota: null, veredicto: null };
  panel.innerHTML = `<div class="cab"><span class="${ok ? "pos" : "neg"}">${ico(ok ? "ok" : "alerta")}</span><strong>${esc(t.titulo)}: ${ok ? "terminado" : "error"}</strong><span class="tenue num">${duracion}</span></div>
    <div>${lineas.map((l) => `<div>${esc(l)}</div>`).join("")}</div>
    ${veredicto ? `<div class="veredicto">${esc(veredicto)}</div>` : ""}
    ${log && (!ok || /error|⚠/i.test(log)) ? `<details><summary class="tenue">Registro</summary><pre class="log">${esc(log.slice(-6000))}</pre></details>` : ""}
    <div class="botones">${nota ? `<button class="btn pequeno" data-nota="${esc(nota)}">Abrir informe</button>` : ""}<button class="btn pequeno" data-accion="cerrar-trabajo">Cerrar</button></div>`;
  $$("svg", $(".cab", panel)).forEach((s) => s.setAttribute("width", "18"));
}

// ======================================================================
// Diálogo de confirmación
// ======================================================================
function confirmar({ titulo, cuerpo, coste = "", extra = "", aceptar = "Aceptar", peligro = false }) {
  const dialogo = $("#dialogo");
  dialogo.innerHTML = `<div class="contenido">
    <h2>${esc(titulo)}</h2>
    <p>${esc(cuerpo)}</p>
    ${coste ? `<div class="nota-coste">${ico("info")}<span>${esc(coste)}</span></div>` : ""}
    ${extra ? `<p class="tenue">${esc(extra)}</p>` : ""}
    <div class="botones"><button class="btn" data-respuesta="no">Cancelar</button>
      <button class="btn ${peligro ? "peligro lleno" : "primario"}" data-respuesta="si">${esc(aceptar)}</button></div>
  </div>`;
  $$(".nota-coste svg", dialogo).forEach((s) => s.setAttribute("width", "16"));
  return new Promise((resolver) => {
    // Se resuelve desde el propio botón además de desde `close`: hay builds de
    // Chromium en los que `close` no llega y la promesa quedaría colgada.
    let hecho = false;
    const resolverUnaVez = (valor) => {
      if (hecho) return;
      hecho = true;
      resolver(valor);
    };
    dialogo.addEventListener("close", () => resolverUnaVez(dialogo.returnValue === "si"), { once: true });
    $$("[data-respuesta]", dialogo).forEach((b) =>
      b.addEventListener("click", () => resolverUnaVez(b.dataset.respuesta === "si"), { once: true }));
    dialogo.returnValue = "";
    dialogo.showModal();
    $('[data-respuesta="si"]', dialogo).focus();
  });
}

// ======================================================================
// Eventos (delegados)
// ======================================================================
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-respuesta],[data-accion],[data-lanzar],[data-nota],[data-nota-id],[data-nota-ticker],[data-orden],[data-tipo],a.wikilink");
  if (!el) return;

  if (el.dataset.respuesta) { $("#dialogo").close(el.dataset.respuesta); return; }
  if (el.matches("a.wikilink")) { ev.preventDefault(); location.hash = `#/nota/${encodeURIComponent(el.dataset.nota)}`; return; }
  if (el.dataset.lanzar) { lanzar(el.dataset.lanzar); return; }
  if (el.dataset.nota) { location.hash = `#/nota/${encodeURIComponent(el.dataset.nota)}`; return; }
  if (el.dataset.notaTicker) { location.hash = `#/nota/${encodeURIComponent(el.dataset.notaTicker)}`; return; }
  if (el.dataset.notaId) {
    const id = el.dataset.notaId;
    location.hash = `#/informes/${tipoDeNota(id) || estado.informes.tipo}/${encodeURIComponent(id)}`;
    return;
  }
  if (el.dataset.tipo) { estado.informes.notas = []; location.hash = `#/informes/${el.dataset.tipo}`; return; }
  if (el.dataset.orden) {
    const campo = el.dataset.orden;
    estado.ordenPos = { campo, desc: estado.ordenPos.campo === campo ? !estado.ordenPos.desc : !["ticker", "sector"].includes(campo) };
    const contenedor = el.closest(".tabla-envoltorio");
    contenedor.innerHTML = tablaPosiciones(estado.panel);
    aplicarGeometria(contenedor);
    return;
  }
  switch (el.dataset.accion) {
    case "tema": {
      const siguiente = TEMAS[(TEMAS.indexOf(temaGuardado()) + 1) % TEMAS.length];
      aplicarTema(siguiente);
      el.outerHTML = botonTema();
      break;
    }
    case "refrescar":
      try { await vistaPanel(true); aviso("Precios actualizados."); } catch (e) { aviso(e.message, true); vistaPanel(); }
      break;
    case "reintentar":
      navegar();
      break;
    case "volver-lista":
      location.hash = `#/informes/${estado.informes.tipo}`;
      break;
    case "cerrar-trabajo":
      if (estado.trabajo) estado.trabajo.oculto = true;
      pintarTrabajo();
      break;
    case "apagar":
      if (await confirmar({ titulo: "Apagar la app", cuerpo: "Se detiene el servidor local. Para volver a abrirla, lanza de nuevo «Sharky».", aceptar: "Apagar", peligro: true })) {
        await api("/api/sistema/apagar", { metodo: "POST", cuerpo: {} }).catch(() => {});
        document.body.innerHTML = `<div class="principal"><div class="tarjeta"><h2>Sharky se ha apagado.</h2><p class="tenue">Ya puedes cerrar esta ventana.</p></div></div>`;
      }
      break;
  }
});

document.addEventListener("input", (ev) => {
  if (ev.target.id === "filtro-notas") {
    estado.informes.filtro = ev.target.value;
    const activa = decodeURIComponent(location.hash.split("/").slice(3).join("/") || "");
    pintarListaNotas(activa);
  } else if (ev.target.id === "op-ticker") {
    pintarContextoOperacion();
  }
});

document.addEventListener("submit", (ev) => {
  if (ev.target.id === "form-operacion") {
    ev.preventDefault();
    enviarOperacion(ev.target);
  }
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "r" && (ev.ctrlKey || ev.metaKey) && ev.shiftKey) return;
  if (ev.altKey && /^[1-4]$/.test(ev.key)) {
    location.hash = `#/${RUTAS[+ev.key - 1].clave}`;
  }
});

setInterval(() => { if (estado.trabajo?.estado === "en_curso") pintarTrabajo(); }, 1000);
window.addEventListener("hashchange", navegar);

// --------------------------------------------------------------- arranque
(async function iniciar() {
  aplicarTema(temaGuardado());
  pintarNav("panel");
  api("/api/sistema").then((s) => { estado.sistema = s; pintarEstadoIA(); }).catch(() => {});
  await cargarAcciones().catch(() => {});
  navegar();
})();
