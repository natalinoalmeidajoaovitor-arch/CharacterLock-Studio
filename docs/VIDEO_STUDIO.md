# Video Studio: MiniMax H3 com realismo

O preset **MiniMax H3 · Realismo + Turbo 8 (local)** deriva de
`<USER_HOME>\Documents\WORK\Best Minimax H3 skin realism workflow.json`.
Ele é a opção preferencial do Video Studio; uma seleção manual de outro
workflow continua sendo respeitada. A imagem de referência vem da biblioteca
da personagem e é enviada ao ComfyUI como `<Picture 1>`. A direção de cena e
a identidade selecionada alimentam o prompt mapeado.

## Pesos e LoRAs do preset local

| Componente | Arquivo local / configuração |
| --- | --- |
| UNET | `Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors` |
| Encoder | `qwen3vl-32B-MiniMax-H3-Q2_K.gguf`, carregado por `CLIPLoaderGGUF` |
| Primeira LoRA | `h3-realism-people-t2v-i2v-r2v.safetensors`, força **1** |
| Segunda LoRA | `minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors`, força **1** |
| Amostragem | **8 steps**, com sampler e scheduler do caminho ativo original |
| Vídeo | **16:9**, **1 megapixel**, **24 fps**, MP4 H.264 com áudio |
| Duração solicitada | **5 s**; a regra de comprimento do workflow gera 124 quadros, cerca de **5,17 s** |

As forças de realismo e Turbo são controles independentes do estúdio.
O valor zero desativa a contribuição correspondente; os valores iniciais são
1 para ambas. Só a Turbo indicada na tabela é carregada após a LoRA de realismo.
As LoRAs alternativas desativadas no original permanecem fora da execução.

O grafo acrescenta automaticamente o gatilho `r34l1sm` ao prompt composto,
conforme a [orientação do autor da LoRA de realismo](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA).
O gatilho fica em um nó próprio, de modo que editar a cena ou aplicar a
identidade pelo Studio preserva sua inclusão.

## Diferenças em relação ao arquivo enviado

O JSON original é lido e conferido por SHA-256, sem alterações. A exportação
resolve os nós virtuais `SetNode`, `GetNode` e `Reroute`, conservando as
conexões do caminho ativo até a saída de vídeo. A segunda passagem que estava
desativada não é habilitada pelo preparador.

O preset local troca explicitamente o UNET, o encoder e a Turbo V4 ausentes
pelos arquivos instalados da tabela. Também ajusta o múltiplo da resolução
de 24 para **32**, alinhando as dimensões aos latentes H3. Essas substituições
ficam registradas na proveniência; o preset local não reproduz a configuração
exata de pesos do original.

O loader de LoRAs `rgthree` é convertido em dois `LoraLoaderModelOnly`, na
mesma ordem e com as mesmas forças ativas. O CLIP desse loader não estava
conectado no original. Os loaders nativos exigem que os nomes estejam nas
opções reais da instância, impedindo a execução silenciosa sem a LoRA esperada.
O caminho privado da imagem e o texto de cena do arquivo enviado são
substituídos por entradas mapeadas do Studio.

## Preparar e registrar

```powershell
Set-Location '<USER_HOME>\Documents\CharacterLockStudio'
& '.\.venv\Scripts\python.exe' '.\scripts\register_video_realism.py' --local-installed --register
```

O comando consulta os nós da instância ativa e só registra um workflow que
passe no preflight. Reutiliza um registro com o mesmo grafo e mapeamento;
não gera mídia, instala custom nodes ou baixa pesos. Sem `--register`, apenas
prepara e valida os arquivos para revisão.

Os arquivos privados ficam em `workflows/local/video-realism/`:

- `local-installed.api.json`: grafo executável da adaptação local.
- `local-installed.mapping.json`: controles e imagem de referência.
- `local-installed.provenance.json`: origem, hash, LoRAs e substituições.
- `local-installed.validation.json`: resultado do preflight.

A execução sem `--local-installed` prepara a variante `source-exact`, mantendo
os nomes de pesos solicitados pelo original. Essa variante falha no preflight
atual porque o UNET, o encoder e a Turbo V4 exatos não estão disponíveis.
Ela não é registrada como opção executável. As transformações de exportação,
entrada de referência e gatilho também estão documentadas em sua proveniência.

## Validação e uso

O preflight confirma classes, inputs e opções instaladas. Ele não demonstra
que a combinação de pesos carregou, que cabe na GPU ou que a identidade e
o realismo foram preservados. Os parâmetros e resultados das execuções reais
ficam em [VALIDATION.md](VALIDATION.md); um teste curto não valida por extensão
o preset completo de 5 segundos e 1 megapixel.

No estúdio, selecione uma referência de imagem da personagem, confira a cena,
as forças das LoRAs e os parâmetros, confirme a autorização e gere o vídeo.
Os resultados e parâmetros persistem no histórico. Vídeo e áudio de entrada
continuam exigindo adaptadores específicos; esse preset usa uma imagem de
referência e gera vídeo com áudio pelo caminho original.
