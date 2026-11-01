# Sincronização do cache do Orbita (ELF)

O cache local do menu fica em XC360/ no pendrive do Xbox 360:

- ROWS.TXT: fileiras e lista de jogos em cache (XCCROWS 2).
- IMGIDX.TXT: bigIds, URLs e bits que indicam quais imagens estão no disco (XCCIMG 1).
- COVERS/ e HERO/: capas e fundos JPEG, cada um com trailer próprio para validar o bigId.

## Ferramenta no PC

tools/orbita-sync/sync_cache.py é um verificador offline. Ele não acessa a conta Microsoft, não usa TOKEN.TXT e não baixa conteúdo. O modo normal só lê os arquivos:

```powershell
py .\tools\orbita-sync\sync_cache.py E:\XC360
```

Para sincronizar o índice com o conteúdo que realmente existe em COVERS/ e HERO/, feche o Orbita e execute:

```powershell
py .\tools\orbita-sync\sync_cache.py E:\XC360 --repair-index
```

O reparo:
1. exige ROWS.TXT válido e recusa sobrescrever um índice com formato/linhas inválidos;
2. verifica o tamanho, SOI/EOI do JPEG, magia XCC1/XCH2, bigId do trailer e nome 8.3 FNV-1a;
3. recompõe os bits disk de IMGIDX.TXT e inclui bigIds presentes nas fileiras ou recuperáveis pelo trailer;
4. cria IMGIDX.BAK uma única vez e troca IMGIDX.TXT usando IMGIDX.NEW.

**Não apaga nem recompacta imagens** e não altera ROWS.TXT, TOKEN.TXT, WIFI.TXT ou configurações. Se um JPEG estiver truncado/corrompido, o bit dele é desligado no índice; quando o Orbita voltar a ficar online, o worker poderá baixá-lo novamente. O reparo não inventa URLs: imagens sem metadados continuam dependendo de uma sincronização online do catálogo.

Execute a ferramenta com o Xbox fora do Orbita e o pendrive montado sem uso pelo console. Se o índice estiver estruturalmente inválido, o script para sem gravar; preserve os arquivos e investigue antes de tentar reconstruí-los manualmente.

## Verificação no desenvolvimento

python3 tools/orbita-sync/sync_cache.py --self-test valida o reparo em uma pasta temporária. Os testes do catálogo também simulam falhas de gravação em ROWS.TXT/IMGIDX.TXT e respostas JPEG truncadas.
