"""Acervo CMSP — backend que monta o ZIP.

Faz uma coisa só: recebe a lista de PDFs já descoberta pelo navegador e devolve
um .zip em streaming. Não conhece RA, senha nem token de sessão — nada disso
passa por aqui. Os arquivos vêm do CDN público do CMSP, que não exige login.

A validação de host não é paranoia: a URL vem do cliente, e sem ela este
endpoint seria um proxy para o servidor fazer requisição em nome de quem
chamar. Só o domínio do acervo é aceito.
"""

import json
import os
import re
import time
import urllib.request

from flask import Flask, Response, jsonify, request, stream_with_context
from zipstream import ZIP_STORED, ZipStream

app = Flask(__name__)

HOST_PERMITIDO = "acervocmsp.educacao.sp.gov.br"
MAX_ARQUIVOS = 800          # trava de uso: um bimestre inteiro tem ~240 PDFs
TIMEOUT = 90                # segundos por arquivo
TIMEOUT_TOTAL = 25 * 60     # teto do streaming inteiro
INVALIDOS = re.compile(r'[<>:"|?*\x00-\x1f]')


def pedacos(url: str, bloco: int = 256 * 1024):
    """Itera o PDF em blocos. O zipstream consome iterador, nao objeto com read()."""
    with buscar(url) as r:
        while True:
            dados = r.read(bloco)
            if not dados:
                break
            yield dados


def _parte(texto: str, maxlen: int) -> str:
    limpo = INVALIDOS.sub("", texto).strip(" .")
    return limpo[:maxlen]


def nome_seguro(nome: str) -> str:
    """Sanitiza o nome dentro do ZIP.

    Mantém no máximo um nível de pasta — é assim que os arquivos ficam
    organizados por componente. Descarta qualquer coisa que tente escapar:
    '..', caminho absoluto, mais de dois níveis ou barra invertida.
    """
    partes = []
    for p in nome.replace("\\", "/").split("/"):
        if not p or p in (".", "..") or p.startswith(".."):
            continue                      # qualquer tentativa de subir de nivel
        if re.fullmatch(r"[A-Za-z]:", p):
            continue                      # letra de drive do Windows ("C:")
        partes.append(p)
    if not partes:
        return "arquivo.pdf"
    arquivo = _parte(partes[-1], 180) or "arquivo.pdf"
    pasta = _parte(partes[0], 90) if len(partes) >= 2 else ""
    return f"{pasta}/{arquivo}" if pasta else arquivo


def buscar(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "acervo-cmsp/1.0"})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


@app.get("/api/health")
def health():
    return jsonify(ok=True, max_arquivos=MAX_ARQUIVOS)


@app.post("/api/zip")
def zipper():
    # aceita JSON e form-urlencoded: o segundo é o que o browser usa para baixar
    # direto pra disco. Com blob na memoria, um zip de 400 MB estoura a aba.
    if request.is_json:
        corpo = request.get_json(silent=True) or {}
    else:
        bruto = request.form.get("arquivos") or "[]"
        try:
            corpo = {"nome": request.form.get("nome"), "arquivos": json.loads(bruto)}
        except json.JSONDecodeError:
            return jsonify(erro="payload invalido"), 400

    arquivos = corpo.get("arquivos") or []

    if not arquivos:
        return jsonify(erro="nenhum arquivo enviado"), 400
    if len(arquivos) > MAX_ARQUIVOS:
        return jsonify(erro=f"limite de {MAX_ARQUIVOS} arquivos por zip"), 400

    # valida tudo ANTES de começar a streamar: erro tem que ser HTTP, não um zip
    # truncado que o professor só descobre quando tenta abrir
    preparados = []
    usados = set()
    for item in arquivos:
        item = item or {}
        url = item.get("url") or ""
        nome = nome_seguro(item.get("nome") or "")
        if not nome.lower().endswith(".pdf"):
            nome += ".pdf"

        m = re.match(r"https?://([^/:]+)(?::\d+)?(?:/|$)", url)
        if not m or m.group(1).lower() != HOST_PERMITIDO:
            return jsonify(erro=f"origem nao permitida: {url[:80]}"), 400

        if nome in usados:                       # duas aulas com o mesmo titulo
            n = 2
            while f"{nome[:-4]} ({n}).pdf" in usados:
                n += 1
            nome = f"{nome[:-4]} ({n}).pdf"
        usados.add(nome)
        preparados.append((nome, url))

    def gerar():
        inicio = time.monotonic()
        # sized=False: nao sabemos o tamanho de cada PDF antes de abrir a URL, entao
        # o zip sai em chunked. E ZIP_STORED, nao deflate: PDF ja vem comprimido,
        # recomprimir so gasta CPU do servidor sem ganhar byte nenhum na rede.
        z = ZipStream(sized=False, compress_type=ZIP_STORED)
        for nome, url in preparados:
            if time.monotonic() - inicio > TIMEOUT_TOTAL:
                break                            # corta em vez de travar o download
            try:
                z.add(pedacos(url), nome)          # a conexao so abre na hora de ler
            except Exception as e:                 # url quebrada nao derruba o zip
                z.add(f"ERRO ao baixar: {e}".encode(), f"{nome[:-4]}.nao-baixou.txt")
        yield from z

    nome_zip = re.sub(r"[^A-Za-z0-9 _.-]", "", corpo.get("nome") or "materiais")[:60].strip() or "materiais"
    resp = Response(stream_with_context(gerar()), mimetype="application/zip")
    resp.headers["Content-Disposition"] = f'attachment; filename="{nome_zip}.zip"'
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def selftest() -> int:
    """O nome dentro do ZIP nao pode escapar da pasta de download: nem subindo
    nivel, nem com caminho absoluto, nem com letra de drive. Testa as
    propriedades, nao a string exata."""
    entradas = [
        "../../etc/passwd",
        "MAT/../../../etc/passwd",
        "C:\\Windows\\evil.pdf",
        "/absoluto/x.pdf",
        "..\\..\\x.pdf",
        "MATEMATICA/1 - Aula.pdf",
        "MAT/a/b/c.pdf",
        "",
    ]
    ok = True
    for entrada in entradas:
        got = nome_seguro(entrada)
        problemas = []
        if ".." in got:
            problemas.append("sobe nivel")
        if got.startswith("/"):
            problemas.append("caminho absoluto")
        if got.count("/") > 1:
            problemas.append("mais de 2 niveis")
        if re.search(r"(^|/)[A-Za-z]:", got):
            problemas.append("letra de drive")
        if problemas:
            ok = False
            print(f"  [FALHOU] {entrada!r} -> {got!r}  ({', '.join(problemas)})")
        else:
            print(f"  [ok] {entrada!r} -> {got!r}")
    print("selftest ok" if ok else "selftest FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in os.sys.argv:
        raise SystemExit(selftest())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))