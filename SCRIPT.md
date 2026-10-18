# Script: baixar o bimestre inteiro em pastas

Para quem quer **todos** os componentes de uma vez, organizados em pasta por
matéria — em vez de discipline por discipline no site.

`baixar_materiais.py` faz isso com Python 3 puro, sem nenhuma biblioteca para
instalar. Ele conversa com a mesma API pública do CMSP que o site usa.

## Instalação

Nada. Só Python 3.8 ou mais novo.

```bash
git clone https://github.com/klcombr/acervo-cmsp.git
cd acervo-cmsp
```

## Uso

```bash
# primeira vez: informa RA e senha quando perguntar
python3 baixar_materiais.py

# ou sem digitar, com variáveis de ambiente
CMSP_USUARIO='0000000000sp' CMSP_SENHA='sua-senha' python3 baixar_materiais.py
```

Por padrão ele baixa **3º ano do Ensino Médio, 2º semestre, 4º bimestre** e cria:

```
Materiais_4_Bimestre/
  MATEMÁTICA/
    Aula 1 - Grandezas determinadas pela razão.pdf
    Aula 2 - Resolução de problemas.pdf
  FÍSICA/
    ...
```

Matéria sem PDF publicado não ganha pasta.

## Opções

| Flag | O que faz |
|---|---|
| `--saida DIR` | pasta de destino (padrão `./Materiais_4_Bimestre`) |
| `--progresso ARQ` | arquivo de progresso (padrão `./progresso.json`) |
| `--reiniciar` | apaga o progresso e rebaixa tudo |
| `--limite N` | só as N primeiras matérias (para testar) |
| `--componente NOME` | filtra por nome, pode repetir |
| `--ano` `--serie` `--bimestre` | outros filtros do acervo |
| `--selftest` | verificações locais, sem rede |

Exemplos:

```bash
python3 baixar_materiais.py --limite 3              # teste rápido
python3 baixar_materiais.py --componente "MATEMÁTICA" --componente "FÍSICA"
python3 baixar_materiais.py --ano 2025 --bimestre 3  # 3º bimestre de 2025
python3 baixar_materiais.py --saida ~/Downloads/b4
```

## Se a internet cair

Pode interromper com `Ctrl+C` e rodar de novo: o script lê `progresso.json` e
pula o que já está no disco. Ele só marca um arquivo como concluído **depois**
de gravar e validar que é mesmo um PDF (assinatura `%PDF`, > 1 KB) — página de
erro do servidor nunca vira `.pdf`.

## O que ele ignora de propósito

O acervo também tem arquivos de áudio (`.wav`) e vídeo. A extensão é conferida
**antes** da requisição, então o script não baixa dezenas de MB de áudio só para
descartar. O relatório final diz quantos foram pulados.

## Relatório

Cada execução escreve `relatorio.json`:

```json
{
  "materias_verificadas": 77,
  "materias_com_pdf": 19,
  "materias_ignoradas": 58,
  "pdfs_baixados": 239,
  "arquivos_nao_pdf": 52,
  "duplicatas_evertas": 12,
  "erros": 0,
  "erros_detalhe": []
}
```

O código de saída é `0` se não houve erro, `1` se houve, `2` se o login falhou —
útil para rodar em rotina.

## Sobre a senha

O script pede RA e senha e manda direto para `sedintegracoes.educacao.sp.gov.br`.
A senha não é gravada em lugar nenhum. O token de sessão é guardado em
`.token.json` (permissão `600`) só para você não precisar entrar toda vez; apague
o arquivo se preferir entrar sempre.