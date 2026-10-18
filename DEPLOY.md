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

Conferido no deploy real: `POST /api/zip` com `169.254.169.254` devolve 400, e
um zip de teste saiu íntegro com a pasta `MATEMATICA/` preservada.

A URL vem do cliente, então o endpoint valida que só aceita o domínio
`acervocmsp.educacao.sp.gov.br`. Sem isso, o serviço seria um proxy para o
servidor fazer requisição em nome de quem chamasse (SSRF).

## Deploy no Render — já feito

O backend está no ar em:

**https://acervo-cmsp-zip.onrender.com**

E já está ligado no site (`ZIP_BACKEND` em [`app.js`](app.js)). Esta seção
explica como foi feito, caso você queira refazer.

1. Crie conta em <https://render.com> (GitHub login).
2. **New → Blueprint**, aponte para `https://github.com/klcombr/acervo-cmsp`.
   O Render lê o [`render.yaml`](render.yaml) e monta tudo sozinho.
3. Confirme o plano **Free**. O deploy leva 2–3 minutos.

**Não precisa configurar nada à mão** — build command, start command e health
check já estão no `render.yaml`.

### Ligar no site (ou trocar a URL)

Abra [`app.js`](app.js) e troque a constante:

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
  É o comportamento do plano gratuito, não do código.
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
## O ZIP do bimestre inteiro: causa raiz e o que mudou

O ZIP único de 407 MB **não chega íntegro**. Medi três vezes até achar a causa:

| Caminho | Esperado | Chegou | Tempo |
|---|---|---|---|
| Browser (form POST) | 407.616.699 B | 316.981.662 B | — |
| curl, 1ª tentativa | 407.616.699 B | 200.888.320 B | — |
| curl, 2ª tentativa | 407.616.699 B | 293.128.134 B | **900,79 s** |

O número que explica tudo é o tempo: **900,79 s**, praticamente o `--timeout 900`
do gunicorn. A primeira hipótese era o proxy do plano Free, e estava errada — foi
o **gunicorn matando o worker no meio da stream**.

Por que 900 s não bastam: o Render entrega os PDFs em série a ~325 KB/s
(293 MB ÷ 900 s). Os 407 MB exigiriam ~21 min.

Duas correções:

1. `--timeout 1800` no `render.yaml`, para o teto artificial não matar a stream.
2. **Um ZIP por disciplina em vez de um de tudo.** Dezoito downloads de ~20 MB
   são rápidos e não dependem de uma resposta de 20 minutos. O site faz isso
   sozinho agora.

Se o script Python continuar sendo o caminho para "baixar tudo de uma vez": ele
faz 407 MB direto da sua máquina, em ~100 s, com pastas e retomada — e não depende
de serviço gratuito nenhum.
