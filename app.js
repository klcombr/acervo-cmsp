/* Acervo CMSP — talks directly to the public CMSP API from the browser.
   The API sends Access-Control-Allow-Origin: *, so there is no backend here:
   the RA/password go straight from this tab to sedintegracoes.educacao.sp.gov.br. */

const API   = "https://sedintegracoes.educacao.sp.gov.br/apirepocmsp/api/materiais-digitais";
const AUTH  = "https://sedintegracoes.educacao.sp.gov.br/apirepocmsp/api/cronograma-aula/auth";
const CHAVE = "9a1c18f57885465ebc2ea0557afc6dbe"; // publica: esta no bundle do site oficial
const ETAPA_EM = 3;                                 // 3 = ENSINO MÉDIO

const $ = (s) => document.querySelector(s);
const el = (t, cls, txt) => { const n = document.createElement(t); if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };

let token = sessionStorage.getItem("cmsp_token") || "";   // vive só nesta aba
let materiaAtual = null;

/* ------------------------------------------------------------------ rede */

async function api(url, opcoes = {}) {
  const r = await fetch(url, {
    ...opcoes,
    headers: { "Ocp-Apim-Subscription-Key": CHAVE, "Content-Type": "application/json", ...opcoes.headers },
  });
  const texto = await r.text();
  let dados;
  try { dados = JSON.parse(texto); } catch { throw new Error(`resposta inesperada do servidor (${r.status})`); }
  if (!dados.success) throw new Error((dados.messages || []).join(" ") || `falha ${r.status}`);
  return dados.data;
}

const getDados = (rota, params) => api(`${API}/${rota}?${new URLSearchParams(params)}`);

/* ------------------------------------------------------------- utilidades */

function preencher(select, itens, valorPadrao) {
  select.textContent = "";
  for (const it of itens) {
    const o = el("option", null, it.nome);
    o.value = it.codigo;
    select.append(o);
  }
  if (valorPadrao != null && select.querySelector(`option[value="${valorPadrao}"]`)) select.value = String(valorPadrao);
}

const bytes = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;

// "2º SEMESTRE/4º BIMESTRE" -> "4º BIMESTRE · 2º semestre" (cabe no select)
function curto(rotulo) {
  const [sem, bim] = rotulo.split("/");
  return bim && sem ? `${bim.trim()} · ${sem.trim().toLowerCase()}` : rotulo;
}

function erro(alvo, msg) {
  alvo.textContent = msg;
  alvo.hidden = !msg;
}

async function comBotao(botao, fn) {
  const rotulo = botao.textContent;
  botao.disabled = true;
  botao.textContent = "Aguarde…";
  try { return await fn(); }
  catch (e) { erro($("#loginErro"), e.message); }
  finally { botao.disabled = false; botao.textContent = rotulo; }
}

/* ------------------------------------------------------------------ login */

$("#formLogin").addEventListener("submit", async (e) => {
  e.preventDefault();
  erro($("#loginErro"), "");
  await comBotao($("#btnEntrar"), async () => {
    const usuario = $("#usuario").value.trim();
    const senha = $("#senha").value;
    const r = await fetch(AUTH, {
      method: "POST",
      headers: { "Ocp-Apim-Subscription-Key": CHAVE, "Content-Type": "application/json" },
      body: JSON.stringify({ usuario, senha }),
    });
    const d = await r.json();
    if (!d.success) throw new Error((d.messages || []).join(" ") || "RA ou senha incorretos.");
    token = d.data;
    sessionStorage.setItem("cmsp_token", token);
    $("#senha").value = "";                     // não deixa a senha parada no formulário
    await iniciarBusca();
  });
});

$("#btnOlho").addEventListener("click", () => {
  const i = $("#senha");
  i.type = i.type === "password" ? "text" : "password";
  $("#btnOlho").textContent = i.type === "password" ? "ver" : "ocultar";
});

$("#btnSair").addEventListener("click", () => {
  token = "";
  sessionStorage.removeItem("cmsp_token");
  location.reload();
});

/* ------------------------------------------------------- cascata de selects */

$("#fAno").addEventListener("change", async () => {
  await carregarBimestre($("#fAno").value);
  $("#btnBuscar").disabled = false;
});
$("#fEtapa").addEventListener("change", () => carregarSerie());
$("#fSerie").addEventListener("change", () => carregarComponentes());

async function carregarBimestre(ano) {
  const sel = $("#fBimestre");
  sel.textContent = "";
  if (!ano) return;
  sel.disabled = true;
  try {
    const lista = await getDados("bimestre", { ano });
    // o select oficial manda o codigo numerico (1..4), nao o rotulo; os perfis
    // servidor/aluno repetem o mesmo bimestre, entao deduplica por codigo
    const vistos = new Map();
    for (const b of lista) if (!vistos.has(b.codigo)) vistos.set(b.codigo, curto(b.codigoBimestre || b.nome));
    const itens = [...vistos].map(([codigo, nome]) => ({ nome, codigo }));
    preencher(sel, itens, null);
    const alvo = itens.find((i) => /4º BIMESTRE/i.test(i.nome) && /2º semestre/i.test(i.nome))
              || itens.find((i) => /4º BIMESTRE/i.test(i.nome)) || itens[0];
    if (alvo) sel.value = String(alvo.codigo);
  } finally { sel.disabled = false; }
}

async function carregarSerie() {
  const sel = $("#fSerie");
  sel.textContent = "";
  sel.disabled = true;
  try {
    const lista = await getDados("serie", { TipoEnsino: $("#fEtapa").value, AnoLetivo: $("#fAno").value });
    preencher(sel, lista, sel.value || (ETAPA_EM == +$("#fEtapa").value ? 12 : lista[0]?.codigo));
    $("#statSeries").textContent = lista.length;
    await carregarComponentes();
  } finally { sel.disabled = false; }
}

async function carregarComponentes() {
  const sel = $("#fComponente");
  sel.textContent = "";
  sel.disabled = true;
  try {
    const lista = await getDados("componente", {
      anoLetivo: $("#fAno").value, serie: $("#fSerie").value, tipoEnsino: $("#fEtapa").value,
    });
    sel.dataset.todos = lista.length;
    preencher(sel, lista, null);
    $("#statComponentes").textContent = lista.length;
  } finally { sel.disabled = false; }
}

// "quim" precisa achar "QUÍMICA": a busca ignora acento e caixa
const semAcento = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();

// filtro de texto sobre o <select> nativo: esconde as opções que não casam
$("#fFiltroComp").addEventListener("input", (e) => {
  const termo = semAcento(e.target.value.trim());
  const sel = $("#fComponente");
  let visiveis = 0;
  let primeiro = null;
  for (const o of sel.options) {
    const casa = !termo || semAcento(o.textContent).includes(termo);
    o.hidden = !casa;
    if (casa) { visiveis++; primeiro ??= o; }
  }
  if (termo && visiveis === 1) sel.value = primeiro.value;
});

/* ------------------------------------------------------------- a busca */

$("#formBusca").addEventListener("submit", async (e) => {
  e.preventDefault();
  const selComp = $("#fComponente");
  materiaAtual = selComp.options[selComp.selectedIndex].textContent;
  const area = $("#resultados");
  area.textContent = "";
  for (let i = 0; i < 3; i++) area.append(el("div", "esqueleto"));
  $("#resumo").hidden = true;

  try {
    const d = await getDados("materiaisdigitais", {
      key: token,
      Ano: $("#fAno").value,
      TipoEnsino: $("#fEtapa").value,
      Serie: $("#fSerie").value,
      Bimestre: $("#fBimestre").value,
      Componente: selComp.value,
    });
    render(selComp.options[selComp.selectedIndex].textContent, d?.materiais || []);
  } catch (err) {
    if (/sess|token|login|expired/i.test(err.message)) {
      token = ""; sessionStorage.removeItem("cmsp_token");
      erro($("#loginErro"), "Sua sessão expirou. Entre com o RA novamente.");
    }
    area.textContent = "";
    area.append(vazio("Não deu para consultar", err.message));
  }
});

/* --------------------------------------------------------------- desenho */

function vazio(titulo, texto) {
  const c = el("div", "vazio");
  c.append(el("h3", null, titulo), el("p", null, texto));
  return c;
}

const ehPdf = (a) => (a.linkDownload || "").toLowerCase().split("?")[0].endsWith(".pdf");

function render(componente, aulas) {
  const area = $("#resultados");
  area.textContent = "";

  if (!aulas.length) {
    area.append(vazio("Nada publicado aqui",
      `O componente “${componente}” não tem materiais no bimestre selecionado. Tente outro bimestre ou ano.`));
    return;
  }

  // PDFs primeiro; aulas só com áudio ficam de fora da lista, mas são contabilizadas
  const linhas = aulas.map((a) => ({
    aula: a,
    pdfs: (a.arquivos || []).filter((x) => x.ativo && ehPdf(x)),
    outros: (a.arquivos || []).filter((x) => x.ativo && !ehPdf(x)).length,
  })).filter((l) => l.pdfs.length);

  const naoPdf = linhas.reduce((s, l) => s + l.outros, 0);
  const total = linhas.reduce((s, l) => s + l.pdfs.length, 0);

  if (!total) {
    area.append(vazio("Só há áudio nesta disciplina",
      `As ${aulas.length} aulas de “${componente}” têm arquivos de áudio, mas nenhum PDF. Nada para baixar.`));
    return;
  }

  const resumo = $("#resumo");
  resumo.textContent = "";
  resumo.append(el("b", null, `${componente} — `),
    document.createTextNode(`${linhas.length} aula${linhas.length > 1 ? "s" : ""} · ${total} PDF${total > 1 ? "s" : ""}` +
      (naoPdf ? ` · ${naoPdf} arquivo(s) de áudio ignorado(s)` : "")));
  resumo.hidden = false;

  area.append(barra(linhas, total));

  for (const { aula, pdfs } of linhas) {
    const box = el("article", "aula");
    const cab = el("button", "aula-cabeca");
    cab.type = "button";
    cab.append(el("span", "aula-num", aula.ordenacao ?? "?"));
    cab.append(el("span", "aula-titulo", aula.titulo || "sem título"));
    const pdfTag = el("span", "tag", `${pdfs.length} PDF${pdfs.length > 1 ? "s" : ""}`);
    cab.append(pdfTag);
    cab.insertAdjacentHTML("beforeend",
      '<svg class="aula-seta" viewBox="0 0 12 8" aria-hidden="true"><path d="M1 1.5 6 6.5l5-5" stroke="currentColor" stroke-width="1.7" fill="none" stroke-linecap="round"/></svg>');

    const lista = el("div", "arq-lista");
    lista.hidden = true;
    for (const a of pdfs) {
      const li = el("div", "arq");
      li.append(el("span", "arq-icone", "PDF"));
      const nome = el("a", "arq-nome", `Aula ${aula.ordenacao ?? "?"} — ${aula.titulo || "sem título"}`);
      nome.href = a.linkDownload;
      nome.target = "_blank";
      nome.rel = "noopener";
      nome.title = "Abrir / baixar o PDF";
      li.append(nome);
      lista.append(li);
    }

    cab.addEventListener("click", () => {
      const aberto = box.dataset.aberta === "true";
      box.dataset.aberta = String(!aberto);
      lista.hidden = aberto;
      cab.setAttribute("aria-expanded", String(!aberto));
    });
    box.append(cab, lista);
    area.append(box);
  }
}

function barra(linhas, total) {
  const b = el("div", "barra-ferramentas");
  const conta = el("span", "conta");
  conta.append(el("b", null, String(total)), document.createTextNode(" arquivos prontos para baixar"));
  b.append(conta);

  const abrir = el("button", "btn-secundario", "Abrir todos");
  abrir.type = "button";
  abrir.title = "Abre cada PDF em uma aba. Se o navegador bloquear, permita os downloads múltiplos.";
  abrir.addEventListener("click", () => {
    const urls = linhas.flatMap((l) => l.pdfs.map((a) => a.linkDownload));
   _urls(urls);
  });

  const copiar = el("button", "btn-ghost", "Copiar links");
  copiar.type = "button";
  copiar.addEventListener("click", async () => {
    const texto = linhas.flatMap((l) => l.pdfs.map((a) => `Aula ${l.aula.ordenacao ?? "?"} — ${l.aula.titulo || "sem título"}\t${a.linkDownload}`)).join("\n");
    try { await navigator.clipboard.writeText(texto); copiar.textContent = "Copiado!"; }
    catch { copiar.textContent = "Use Ctrl+C"; }
    setTimeout(() => (copiar.textContent = "Copiar links"), 1800);
  });

  b.append(abrir, copiar);
  return b;
}

// o navegador só libera vários downloads a partir de um gesto do usuário;
// abrimos com uma pausa curta entre eles e deixamos o contador na tela.
let _urls = (urls) => {
  urls.reduce((t, url, i) => setTimeout(() => {
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener";
    document.body.append(a); a.click(); a.remove();
  }, i * 450), undefined);
};

/* ------------------------------------------------------------------ boot */

async function iniciarBusca() {
  $("#formLogin").hidden = true;
  $("#btnSair").hidden = false;
  $("#busca").hidden = false;
  document.body.classList.add("logado");   // sem hero, a busca vira a primeira coisa na tela
  $("#busca").scrollIntoView({ block: "start", behavior: "instant" });

  const [anos, etapas] = await Promise.all([
    getDados("anos"),
    getDados("etapa"),
  ]);
  preencher($("#fAno"), anos, anos[0]?.codigo);
  preencher($("#fEtapa"), etapas, ETAPA_EM);
  await carregarBimestre($("#fAno").value);
  await carregarSerie();
}

if (token) {
  $("#formLogin").hidden = true;
  $("#btnSair").hidden = false;
  $("#busca").hidden = false;
  document.body.classList.add("logado");
  iniciarBusca().catch((e) => {
    token = ""; sessionStorage.removeItem("cmsp_token");
    $("#formLogin").hidden = false;
    $("#busca").hidden = true;
    document.body.classList.remove("logado");
    erro($("#loginErro"), "Sua sessão expirou. Entre com o RA novamente.");
  });
}