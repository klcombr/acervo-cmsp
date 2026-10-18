# Acervo CMSP

**Todos os PDFs do bimestre do Centro de Mídias SP, sem planilha.**

Uma interface para os materiais que a Secretaria da Educação do Estado de São Paulo
já publica em [repositorio.educacao.sp.gov.br/midia](https://repositorio.educacao.sp.gov.br/midia).
Escolha ano, etapa, série, bimestre e disciplina — o site lista **todas as aulas**,
não só a primeira, e cada PDF abre direto do servidor público.

🔗 **Site no ar:** <https://klcombr.github.io/acervo-cmsp/>

---

## Como funciona

O site é estático e fala direto com a API do CMSP. Um backend opcional
([`backend/`](backend/), um `app.py` só) monta o `.zip` — é o único motivo de
existir servidor. A API do CMSP responde com
`Access-Control-Allow-Origin: *`, então o navegador fala com ela diretamente:

```
POST .../api/cronograma-aula/auth                    {usuario, senha} → token
GET  .../api/materiais-digitais/anos                  → anos letivos
GET  .../api/materiais-digitais/etapa                 → etapas de ensino
GET  .../api/materiais-digitais/serie                 → séries da etapa
GET  .../api/materiais-digitais/bimestre              → bimestres do ano
GET  .../api/materiais-digitais/componente            → componentes da série
GET  .../api/materiais-digitais/materiaisdigitais     → aulas + arquivos
```

O token de sessão vive no `sessionStorage` da aba e morre com ela.

### ZIP

O botão **Baixar tudo em .zip** e **Baixar o bimestre inteiro em .zip** usam um
backend mínimo ([`backend/app.py`](backend/app.py), Flask) que só empacota as
URLs que o navegador já descobriu e baixa cada PDF do CDN público do CMSP — ele
**não recebe RA, senha nem token**. Está no ar em
`acervo-cmsp-zip.onrender.com`.

Instruções de deploy: **[DEPLOY.md](DEPLOY.md)**.

### Por que sua senha é segura aqui

A busca de materiais **exige** autenticação (sem o parâmetro `key` a API devolve
`materiais: null`). Mas o login acontece no seu navegador:

```
seu navegador  ──POST /auth (RA + senha)──▶  sedintegracoes.educacao.sp.gov.br
```

Não existe servidor intermediário. A senha **não passa por este site**, não é
gravada, não vai para log. Nem este site nem o servidor de ZIP a recebem. É a
mesma requisição que o site oficial faz — só que sem o React no meio.

A chave de assinatura `Ocp-Apim-Subscription-Key` usada no cliente é pública:
está embutida no bundle JS do site oficial. Não é credencial.

### O que não é feito

Nada de CAPTCHA, controle de acesso ou qualquer outra proteção é contornado. O
acesso é o mesmo que qualquer aluno tem. O projeto é independente e não afiliado
à Secretaria da Educação do Estado de São Paulo.

---

## Rodar localmente

Não tem build, não tem dependência. Qualquer servidor estático serve:

```bash
python3 -m http.server 8000
# abra http://localhost:8000
```

`file://` **não** funciona: o navegador bloqueia `fetch` de origem nula.

## Estrutura

```
index.html      página única
style.css       folha de estilo (light + dark, sem build)
app.js          Cascata de selects, login, busca, render e ZIP
backend/app.py  servidor do ZIP (opcional, Flask)
DEPLOY.md       como subir o backend no Render
SCRIPT.md       script de linha de comando para baixar tudo em pastas
```

## Limitações conhecidas

- **Sem ZIP no browser puro.** O servidor de arquivos do CMSP não envia CORS, então
  só com o backend é possível montar o `.zip` — com pasta por disciplina.
- **Sem "abrir todos".** O Chrome só permite um popup por clique do usuário, então
  abrir 250 abas é bloqueado de propósito. O ZIP cobre esse caso melhor.
- O acervo às vezes traz material de série errada (o `Script da tarde` cadastrado
  no noturno, por exemplo). É um problema do dado de origem, não da interface.

## Licença

Código sob MIT (ver [LICENSE](LICENSE)). Os materiais do CMSP **não** estão sob
esta licença — continuam sendo públicos da Secretaria da Educação do Estado de
São Paulo, e cada professor pode usá-los conforme as regras do Centro de Mídias.