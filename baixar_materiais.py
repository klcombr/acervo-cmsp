#!/usr/bin/env python3
"""Baixa todos os PDFs do 3o ano do Ensino Medio (2o semestre / 4o bimestre) do
Centro de Midias SP (repositorio.educacao.sp.gov.br/midia).

O site e uma SPA React. Esta automacao fala diretamente com a mesma API JSON que
o navegador usa (mesmos endpoints, mesma chave de assinatura que esta embutida no
bundle publico do site), portanto nao precisa de navegador, Playwright nem de
perfil do Brave. Logins da GUI nao sao reaproveitados: a autenticacao e feita
pela rota de aluno da propria API.

Uso:
    python3 baixar_materiais.py                    # coleta completa
    python3 baixar_materiais.py --limite 3         # teste nas 3 primeiras materias
    python3 baixar_materiais.py --componente "APROFUNDAMENTO EM QUIMICA"
    python3 baixar_materiais.py --reiniciar       # ignora o progresso salvo
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://sedintegracoes.educacao.sp.gov.br/apirepocmsp/api"
SUBSCRIPTION_KEY = "9a1c18f57885465ebc2ea0557afc6dbe"  # publica, embutida no bundle do site

# Padroes de filtro do pedido
ANO_PADRAO = 2026
TIPO_ENSINO = 3      # ENSINO MEDIO
SERIE_PADRAO = 12    # 3a SERIE do Ensino Medio
BIMESTRE_PADRAO = 4  # 4o Bimestre (2o semestre)

DELAY = 0.35   # intervalo entre requisicoes, para nao martelar o servidor
TENTATIVAS = 4
INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class Falha(Exception):
    """Erro de negocio (HTTP 4xx, JSON invalido) que nao adianta repetir."""


# --------------------------------------------------------------------------- IO


def _req(url: str, *, dados=None, headers=None, tentativas=TENTATIVAS) -> tuple[bytes, str, int]:
    """Requisicao HTTP com retentativas apenas em erro transitorio (5xx/timeout)."""
    h = {
        "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
        "Accept-Encoding": "identity",
        "User-Agent": "cmsp-materiais-downloader/1.0",
    }
    if headers:
        h.update(headers)
    corpo = json.dumps(dados).encode() if dados is not None else None
    if corpo is not None:
        h["Content-Type"] = "application/json"

    ultimo = None
    for tentativa in range(tentativas):
        try:
            r = urllib.request.Request(url, data=corpo, headers=h, method="POST" if corpo else "GET")
            with urllib.request.urlopen(r, timeout=120) as resp:
                return resp.read(), resp.headers.get("Content-Type", ""), resp.status
        except urllib.error.HTTPError as e:
            corpo_erro = e.read()[:300].decode("utf-8", "replace")
            ultimo = Falha(f"HTTP {e.code}: {corpo_erro}")
            if e.code < 500:  # 4xx nao melhora com repeticao
                raise ultimo
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            ultimo = Falha(f"rede: {e}")
        if tentativa < tentativas - 1:
            time.sleep(1.5 * (tentativa + 1))  # backoff linear, sem sleep fixo
    raise ultimo


def _json(url: str, *, dados=None) -> dict:
    bruto, _, _ = _req(url, dados=dados)
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        raise Falha(f"resposta nao-JSON ({e}): {bruto[:120]!r}") from e


def _api_get(caminho: str, params: dict) -> dict:
    url = f"{API}/{caminho}?{urllib.parse.urlencode(params)}"
    res = _json(url)
    if not res.get("success"):
        raise Falha(f"API recusou {caminho}: {res.get('messages')}")
    return res.get("data")


# ------------------------------------------------------------------ autenticacao


def obter_token(cache: Path) -> str:
    """Token de sessao. Ordem: cache valido -> variaveis de ambiente -> prompt."""
    if cache.exists():
        try:
            tok = json.loads(cache.read_text())["token"]
            # valida o cache antes de confiar nele
            if _dados_usuario(tok):
                return tok
        except (json.JSONDecodeError, KeyError, Falha):
            pass  # cache expirado -> refaz o login

    usuario = os.environ.get("CMSP_USUARIO") or input("RA: ").strip()
    if not usuario.lower().endswith("sp") and "rg" in usuario.lower():
        raise Falha("o perfil.gov.br nao tem materiais; use o login de aluno (RA)")
    senha = os.environ.get("CMSP_SENHA") or getpass.getpass("Senha: ")

    res = _json(f"{API}/cronograma-aula/auth", dados={"usuario": usuario, "senha": senha})
    if not res.get("success"):
        raise Falha(f"login falhou: {res.get('messages') or 'usuario/senha invalidos'}")
    token = res["data"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"token": token}))
    cache.chmod(0o600)
    return token


def _dados_usuario(token: str) -> bool:
    try:
        return bool(_json(f"{API}/cronograma-aula/dados-usuario?{urllib.parse.urlencode({'token': token})}").get("success"))
    except Falha:
        return False


# ------------------------------------------------------------------------ nomes


def saneiar(nome: str, maxlen: int = 120) -> str:
    """Nome seguro para arquivo/pasta em Linux."""
    nome = unicodedata.normalize("NFC", nome)
    nome = INVALIDOS.sub("", nome)
    nome = re.sub(r"\s+", " ", nome).strip(" .")
    return nome[:maxlen].rstrip(" .") or "sem-titulo"


# ------------------------------------------------------------------- progresso


class Progresso:
    """Marca de downloads concluidos. Chave: componente:idArquivo."""

    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        self.baixados: dict[str, dict] = {}
        self.hashes: set[str] = set()
        self.erros: list[dict] = []
        if arquivo.exists():
            try:
                d = json.loads(arquivo.read_text())
                self.baixados = d.get("baixados", {})
                self.hashes = set(d.get("hashes", []))
                self.erros = d.get("erros", [])
            except json.JSONDecodeError:
                pass  # arquivo corrompido por interrupcao: comeca do zero
        self.podar()

    def podar(self):
        """Esquece registros cujo arquivo sumiu (apagado na mao, disco cheio).
        Sem isso o sha256 orfao faria o re-download ser tratado como duplicata."""
        vivas = {k: v for k, v in self.baixados.items()
                 if Path(v["caminho"]).exists() and Path(v["caminho"]).stat().st_size > 0}
        if len(vivas) != len(self.baixados):
            self.baixados = vivas
            self.hashes = {v["sha256"] for v in vivas.values()}

    def salvar(self):
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"baixados": self.baixados, "hashes": sorted(self.hashes), "erros": self.erros},
            ensure_ascii=False, indent=1))
        tmp.replace(self.arquivo)  # atomico: interrupcao nunca deixa JSON pela metade

    def feito(self, chave: str) -> bool:
        reg = self.baixados.get(chave)
        return bool(reg) and Path(reg["caminho"]).exists() and Path(reg["caminho"]).stat().st_size > 0


# -------------------------------------------------------------------- download


def baixar_pdf(url: str, destino: Path) -> bytes:
    """Baixa e valida que o resultado e mesmo um PDF."""
    bruto, tipo, _ = _req(url)
    if "pdf" not in tipo.lower() and not bruto.startswith(b"%PDF"):
        raise Falha(f"conteudo '{tipo}' em vez de PDF ({len(bruto)} bytes)")
    if b"%PDF" not in bruto[:1024]:
        raise Falha(f"assinatura %PDF ausente (pagina de erro de {len(bruto)} bytes)")
    if len(bruto) < 1024:
        raise Falha(f"PDF suspeito de estar truncado: {len(bruto)} bytes")
    destino.write_bytes(bruto)
    return bruto


def unico(destino: Path) -> Path:
    """Evita sobrescrever: 'a.pdf', 'a (2).pdf', ..."""
    n, base = 2, destino
    while destino.exists():
        destino = base.with_name(f"{base.stem} ({n}){base.suffix}")
        n += 1
    return destino


# ------------------------------------------------------------------------ main


def componentes(ano: int, serie: int) -> list[dict]:
    dados = _api_get("materiais-digitais/componente",
                     {"anoLetivo": ano, "serie": serie, "tipoEnsino": TIPO_ENSINO}) or []
    return sorted(dados, key=lambda c: c["nome"])


def coletar(ano: int, serie: int, bimestre: int, saida: Path, prog: Progresso,
            componentes_alvo: list[dict]) -> dict:
    rel = {"materias_verificadas": 0, "materias_com_pdf": 0, "materias_ignoradas": 0,
           "pdfs_baixados": 0, "duplicatas_evertas": 0, "retomados": 0, "erros": 0, "bytes": 0,
           "arquivos_nao_pdf": 0}
    total = len(componentes_alvo)

    for i, comp in enumerate(componentes_alvo, 1):
        nome = comp["nome"]
        print(f"\n[{i}/{total}] {nome}")
        rel["materias_verificadas"] += 1
        pasta = saida / saneiar(nome)
        baixou_na_materia = 0
        ja_tem_na_materia = False  # PDFs baixados em execucao anterior

        try:
            materiais = _api_get("materiais-digitais/materiaisdigitais", {
                "key": prog.token, "Ano": ano, "TipoEnsino": TIPO_ENSINO,
                "Serie": serie, "Bimestre": bimestre, "Componente": comp["codigo"],
            }) or {}
            aulas = materiais.get("materiais") or []
        except Falha as e:
            print(f"  ERRO na pesquisa: {e}")
            rel["erros"] += 1
            prog.erros.append({"componente": nome, "aula": None, "arquivo": None, "erro": str(e)})
            prog.salvar()
            continue

        if not aulas:
            print("  Nenhum material disponível. Ignorando matéria.")
            rel["materias_ignoradas"] += 1
            time.sleep(DELAY)
            continue

        for aula in aulas:
            titulo = aula.get("titulo") or "sem titulo"
            todos = [a for a in (aula.get("arquivos") or []) if a.get("ativo") and a.get("linkDownload")]
            # filtrar pela extensao ANTES de pedir: o acervo tambem tem .wav/.mp4/.docx,
            # e audio de 12 MB nao e "erro", e so perda de banda
            arquivos = [a for a in todos if ".pdf" in a["linkDownload"].lower().split("?")[0]]
            rel["arquivos_nao_pdf"] += len(todos) - len(arquivos)
            rotulo = f"Aula {aula.get('ordenacao', '?')} - {titulo}"

            if not arquivos:
                extra = f" ({len(todos)} arquivo(s) nao-PDF ignorado(s))" if todos else ""
                print(f"  Nenhum PDF disponível: {rotulo}{extra}")
                continue

            print(f"  {rotulo}")
            for arq in arquivos:
                chave = f"{comp['codigo']}:{arq['idArquivo']}"
                if prog.feito(chave):
                    print(f"    ja baixado: {Path(prog.baixados[chave]['caminho']).name}")
                    rel["retomados"] += 1
                    ja_tem_na_materia = True
                    continue
                pasta.mkdir(parents=True, exist_ok=True)  # so depois de confirmar que ha PDF
                destino = unico(pasta / f"{saneiar(rotulo)}.pdf")
                try:
                    bruto = baixar_pdf(arq["linkDownload"], destino)
                except Falha as e:
                    destino.unlink(missing_ok=True)  # nunca deixa PDF parcial no disco
                    print(f"    FALHOU: {e}")
                    rel["erros"] += 1
                    prog.erros.append({"componente": nome, "aula": titulo,
                                       "arquivo": arq.get("nomeArquivo"), "erro": str(e)})
                    continue
                h = hashlib.sha256(bruto).hexdigest()
                if h in prog.hashes:  # mesmo conteudo ja baixado em outro lugar
                    destino.unlink()
                    print(f"    duplicata ignorada: {destino.name}")
                    rel["duplicatas_evertas"] += 1
                    continue
                prog.hashes.add(h)
                prog.baixados[chave] = {"caminho": str(destino), "sha256": h, "bytes": len(bruto)}
                prog.salvar()  # so marca como concluido depois de gravar em disco
                print(f"    PDF baixado: {destino.name} ({len(bruto)//1024} KB)")
                rel["pdfs_baixados"] += 1
                rel["bytes"] += len(bruto)
                baixou_na_materia += 1
                time.sleep(DELAY)

        if baixou_na_materia or ja_tem_na_materia:
            rel["materias_com_pdf"] += 1
            if not baixou_na_materia:
                print("  Todos os PDFs desta matéria já estavam baixados.")
        else:
            if pasta.exists() and not any(pasta.iterdir()):
                pasta.rmdir()  # materia sem PDF nao ganha pasta
            print("  Nenhum PDF baixado.")
            rel["materias_ignoradas"] += 1
            prog.salvar()
        time.sleep(DELAY)

    return rel


def selftest() -> int:
    """Verificacoes das partes que nao dao para ver no terminal."""
    import tempfile

    ok = 0
    def check(desc, cond):
        nonlocal ok
        print(f"  [{'ok' if cond else 'FALHOU'}] {desc}")
        ok += bool(cond)

    check("saneiar remove separadores", saneiar('a/b:c*?"<>|') == "abc")
    check("saneiar normaliza espacos", saneiar("  Chem?  Lesson \n ") == "Chem Lesson")
    check("saneiar nunca fica vazio", saneiar("///") == "sem-titulo")

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        a = unico(d / "x.pdf"); a.write_bytes(b"%PDF-1.7 aaa")
        check("unico nao sobrescreve", unico(d / "x.pdf").name == "x (2).pdf")

        # pagina de erro HTML nao pode virar .pdf
        global _req
        original = _req
        _req = lambda *a, **k: (b"<!DOCTYPE html><html>erro 404 nao encontrado</html>" * 5, "text/html", 404)
        try:
            baixar_pdf("https://exemplo.invalido/x.pdf", d / "y.pdf")
            check("rejeita HTML como PDF", False)
        except Falha:
            check("rejeita HTML como PDF", not (d / "y.pdf").exists())
        finally:
            _req = original

        prog = Progresso(d / "p.json")
        prog.baixados = {"1:1": {"caminho": str(d / "sumiu.pdf"), "sha256": "x", "bytes": 1}}
        prog.hashes = {"x"}
        prog.podar()
        check("podar limpa registro sem arquivo", prog.baixados == {} and prog.hashes == set())

    print("selftest ok" if ok == 6 else "selftest FALHOU")
    return 0 if ok == 6 else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--saida", type=Path, default=Path(__file__).parent / "Materiais_4_Bimestre")
    p.add_argument("--ano", type=int, default=ANO_PADRAO)
    p.add_argument("--serie", type=int, default=SERIE_PADRAO)
    p.add_argument("--bimestre", type=int, default=BIMESTRE_PADRAO)
    p.add_argument("--limite", type=int, default=0, help="processa so as N primeiras materias (teste)")
    p.add_argument("--componente", action="append", default=[], help="filtra componentes por nome (repetivel)")
    p.add_argument("--reiniciar", action="store_true", help="ignora e apaga o progresso salvo")
    p.add_argument("--progresso", type=Path, default=Path(__file__).parent / "progresso.json",
                   help="caminho do arquivo de progresso (use um separado em testes)")
    p.add_argument("--selftest", action="store_true", help="roda as verificacoes locais e sai")
    args = p.parse_args()

    if args.selftest:
        return selftest()

    base = Path(__file__).parent
    prog_path = args.progresso.resolve()
    if args.reiniciar:
        prog_path.unlink(missing_ok=True)
    prog = Progresso(prog_path)
    prog.token = obter_token(base / ".token.json")

    componentes_alvo = componentes(args.ano, args.serie)
    if args.componente:
        alvo_up = [a.upper() for a in args.componente]
        componentes_alvo = [c for c in componentes_alvo if any(a in c["nome"].upper() for a in alvo_up)]
        if not componentes_alvo:
            raise Falha(f"nenhum componente casa com {args.componente}")
    if args.limite:
        componentes_alvo = componentes_alvo[: args.limite]

    args.saida = args.saida.resolve()   # caminho absoluto: o progresso nao depende do cwd
    args.saida.mkdir(parents=True, exist_ok=True)
    print(f"Ensino Medio / {args.serie} serie / {args.bimestre}bimestre / ano {args.ano}")
    print(f"{len(componentes_alvo)} componente(s) a verificar -> {args.saida}")
    if prog.baixados:
        print(f"Retomando: {len(prog.baixados)} PDF(s) ja concluidos no progresso anterior.\n")

    rel = coletar(args.ano, args.serie, args.bimestre, args.saida, prog, componentes_alvo)

    relatorio = args.progresso.parent / "relatorio.json"
    relatorio.write_text(json.dumps({**rel, "erros_detalhe": prog.erros}, ensure_ascii=False, indent=2))
    print("\n" + "=" * 60)
    print(f"Materias verificadas....... {rel['materias_verificadas']}")
    print(f"  com PDF baixado......... {rel['materias_com_pdf']}")
    print(f"  ignoradas (sem PDF)..... {rel['materias_ignoradas']}")
    print(f"PDFs baixados............. {rel['pdfs_baixados']} ({rel['bytes'] // (1024*1024)} MB)")
    print(f"Arquivos nao-PDF pulados.. {rel['arquivos_nao_pdf']} (.wav/.mp4/etc do acervo)")
    print(f"Duplicatas evitadas....... {rel['duplicatas_evertas']}")
    print(f"Ja baixados (retomada).... {rel['retomados']}")
    print(f"Erros..................... {rel['erros']}")
    print(f"Relatorio................. {relatorio}")
    return 0 if rel["erros"] == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Falha as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nInterrompido. O progresso foi salvo; rode de novo para retomar.")
        sys.exit(130)