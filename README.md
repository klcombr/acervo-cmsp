# Acervo CMSP

**Todos os PDFs do bimestre do Centro de Mídias SP, sem planilha.**

Uma interface para os materiais que a Secretaria da Educação do Estado de São Paulo
já publica em [repositorio.educacao.sp.gov.br/midia](https://repositorio.educacao.sp.gov.br/midia).
Escolha ano, etapa, série, bimestre e disciplina — o site lista **todas as aulas**,
não só a primeira, e cada PDF abre direto do servidor público.

🔗 **Site no ar:** <https://klcombr.github.io/acervo-cmsp/>

---

## Como funciona

Site estático, **sem backend**. A API do CMSP responde com
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

### Por que sua senha é segura aqui

A busca de materiais **exige** autenticação (sem o parâmetro `key` a API devolve
`materiais: null`). Mas o login acontece no seu navegador:

```
seu navegador  ──POST /auth (RA + senha)──▶  sedintegracoes.educacao.sp.gov.br
```

Não existe servidor intermediário. A senha **não passa por este site**, não é
gravada, não vai para log, e o projeto não tem backend onde ela poderia ficar. É a mesma
requisição que o site oficial faz — só que sem o React no meio.

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
app.js          Cascata de selects, login, busca e render
```

## Limitações conhecidas

- **"Abrir todos"** abre cada PDF numa aba. Navegadores bloqueiam downloads
  múltiplos sem gesto do usuário — o Chrome pergunta uma vez e você autoriza.
  O botão "Copiar links" é o plano B para quem não quiser abrir 20 abas.
- **Sem ZIP.** O servidor de arquivos não envia `Access-Control-Allow-Origin`,
  então o navegador não consegue ler os bytes para montar um .zip no cliente.
  Para juntar tudo em pastas, use o [script em Python](SCRIPT.md).
- O acervo às vezes traz material de série errada (o `Script da tarde` cadastrado
  no noturno, por exemplo). É um problema do dado de origem, não da interface.

## Licença

Código sob MIT (ver [LICENSE](LICENSE)). Os materiais do CMSP **não** estão sob
esta licença — continuam sendo públicos da Secretaria da Educação do Estado de
São Paulo, e cada professor pode usá-los conforme as regras do Centro de Mídias.