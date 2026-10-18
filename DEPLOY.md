# Backend no Render (ZIP)

O site em si é estático e já está no ar no GitHub Pages. Esta parte é só o
servidor que monta o `.zip` — o único motivo de existir backend.

## O que o backend faz (e o que ele NÃO faz)

Faz **uma** coisa: recebe a lista de PDFs que o navegador já descobriu e
devolve um `.zip` em streaming, com uma pasta por disciplina.

Ele **não** recebe RA, senha nem token de sessão. A busca de materiais acontece
na aba do professor; o backend só empacota as URLs que ela mandou, e baixa cada
PDF do CDN público do CMSP (que não exige login). Nenhuma credencial passa
por aqui — nem para armazenamento, nem para log.

A URL vem do cliente, então o endpoint valida que só aceita o domínio
`acervocmsp.educacao.sp.gov.br`. Sem isso, o serviço seria um proxy para o
servidor fazer requisição em nome de quem chamasse (SSRF).

## Deploy no Render

1. Crie conta em <https://render.com> (GitHub login).
2. **New → Blueprint**, aponte para `https://github.com/klcombr/acervo-cmsp`.
   O Render lê o [`render.yaml`](render.yaml) e monta tudo sozinho.
3. Confirme o plano **Free**. O deploy leva 2–3 minutos.
4. Ao terminar, o Render mostra uma URL tipo
   `https://acervo-cmsp-zip.onrender.com`.

**Não precisa configurar nada à mão** — build command, start command e health
check já estão no `render.yaml`.

## Ligar no site

Abra [`app.js`](app.js) e troque a constante:

```js
const ZIP_BACKEND = "";   // ← cole aqui a URL do Render
```

para:

```js
const ZIP_BACKEND = "https://acervo-cmsp-zip.onrender.com";
```

Depois é só dar push. O GitHub Pages republica em um minuto.

## Rodar local (para desenvolver)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py --selftest   # checa travessia de caminho e afins
python app.py              # http://localhost:8000
```

## Testar o endpoint na mão

```bash
curl -X POST http://localhost:8000/api/zip \
  -H 'Content-Type: application/json' \
  -d '{"nome":"teste","arquivos":[{"nome":"MAT/1 - Aula.pdf","url":"https://acervocmsp.educacao.sp.gov.br/154639/1672266.pdf"}]}' \
  -o teste.zip

unzip -l teste.zip          # deve ter MAT/1 - Aula.pdf
unzip -p teste.zip 'MAT/1 - Aula.pdf' | head -c 5   # %PDF-
```

Uma origem fora do acervo deve ser recusada:

```bash
curl -X POST http://localhost:8000/api/zip -H 'Content-Type: application/json' \
  -d '{"arquivos":[{"nome":"x.pdf","url":"http://169.254.169.254/latest/meta-data/"}]}'
# {"erro":"origem nao permitida: ..."}
```

## O que foi medido de verdade

| Teste | Resultado |
|---|---|
| ZIP de uma disciplina (ROBÓTICA) | 7 arquivos, 25 MB, `unzip -t` sem erro |
| ZIP do bimestre inteiro (77 componentes) | 251 arquivos, 407 MB, 109s, íntegro |
| Pastas dentro do zip | 19, uma por disciplina |
| PDFs dentro do zip | 251/251 com assinatura `%PDF-` |
| SSRF (`169.254.169.254`) | recusado com 400 |
| `javascript:` URL | recusado com 400 |
| `../../etc/passwd` como nome | vira `etc/passwd`, não escapa |

## Limitações do plano gratuito do Render

- **Dorme.** Sem tráfego por ~15 minutos o serviço hiberna; o primeiro request
  seguinte demora até ~50 segundos. Por isso a primeira vez pode parecer travada.
- Zips muito grandes podem esbarrar no limite de tempo do plano. O timeout do
  gunicorn está em 900s e o stream tem teto de 25 minutos, então o bimestre
  inteiro (≈100s) cabe com folga.
- Se sair do plano gratuito, o site continua funcionando — só o botão de ZIP
  para. É degradação boa.

## Por que streaming e não "gerar e guardar"

Guardar 400 MB em disco no servidor seria upload e download de 800 MB por
usuário. O `zipstream-ng` monta
o arquivo sob demanda conforme ele é enviado: memória constante, sem temp.
E no navegador, o download é um `form POST` cross-origin, não um blob em JS —
`Blob` de 400 MB trava a aba. Assim o browser escreve direto no disco com a
barra de progresso nativa.