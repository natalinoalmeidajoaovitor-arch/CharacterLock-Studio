# Workflows necessários

## Character Lab atual: integração por etapa

A reorganização atual usa **Character Sheet → Dataset → Figurinos → Referências**.
O usuário forneceu o MATRIX Normal V4 para Dataset e autorizou uma adaptação
local de Character Sheet. `scripts/register_matrix_lab.py` prepara dois
exports de Sheet e quatro de Dataset, confere a origem por hash e valida
classes/opções contra o ComfyUI ativo. `--register` registra os workflows e
vínculos; o comando não gera mídia nem aprova uma identidade. Evidências de
execução permanecem separadas do preflight em [VALIDATION.md](VALIDATION.md).
Com `--with-smoke5`, o preparador acrescenta um sétimo export para um único
teste de cinco fotos. As sete definições atuais passaram no preflight; IDs
de registro e hashes são conferidos no manifest privado, sem aprovação
automática de personagem.

O retrato **Qwen 2.1 — Imagem-base** já executado é preservado, mas não comprova
Sheet, Dataset ou consistência entre vistas.

| Etapa | Definição disponível e validação necessária |
| --- | --- |
| Character Sheet | Variantes por descrição e com referência: padrão fixo 3 × 3 com três closes do rosto e seis vistas/poses de corpo. Tronco salvo separadamente como âncora. Dez imagens-base e uma prancha por job; exige inspeção e aprovação explícita. |
| Dataset | Produção: quatro grupos MATRIX de oito imagens. Teste solicitado: um único job de cinco fotos e 10 steps. Ambos resolvem as âncoras aprovadas de rosto, tronco e corpo conforme a vista; execução e consistência precisam de avaliação própria. |
| Figurinos | Workflow ainda necessário, recebendo identidade aprovada e descrição/referência de roupa; verificar preservação de identidade. |
| Referências | Workflow ainda necessário, recebendo identidade, Dataset e figurino quando suportado; validar cenas e reutilização nos outros módulos. |

Os arquivos derivados ficam em `workflows/local/matrix-lab/`, fora do Git.
O manifest registra as diferenças: encoder local w4a8 já validado em vez do
int8 ausente do original, edições com `resolution=0` e latent do encoder, e
novos nós instalados de composição/salvamento/normalização para o Sheet.
O padrão atual acrescenta cadeias reais de A-pose e mãos na cintura.
Não são exports byte a byte do original nem uma instalação do pacote MATRIX.
O original permanece intacto; nenhum peso ou custom node é baixado.

O teste anterior com prancha 2 × 2 e cinco imagens-base é histórico e não foi
aprovado como identidade principal. Ele não substitui o padrão atual com
closes e poses.

A associação específica da etapa, os papéis de imagem e as revisões são
documentados em [CHARACTER_LAB.md](CHARACTER_LAB.md). A lista histórica abaixo
descreve o inventário inicial; a nova sequência não exige uma geração separada
de imagem-base antes do Sheet.

## Video Studio atual: realismo e Turbo local

O workflow escolhido é `Best Minimax H3 skin realism workflow.json`, fornecido
em `<USER_HOME>\Documents\WORK`. `scripts/register_video_realism.py` resolve
os links reais do gráfico UI e exporta apenas o caminho ativo de vídeo/áudio.
A segunda passagem desativada no original continua desativada.

A variante **MiniMax H3 · Realismo + Turbo 8 (local)** usa a LoRA de realismo
original em força **1** e a Turbo de oito steps instalada em força **1**.
O usuário autorizou essa escolha após a identificação da Turbo V4 ausente.
O UNET e o encoder também são adaptações locais explícitas, registradas na
proveniência. Somente uma LoRA Turbo é carregada; as alternativas desativadas
do original não são empilhadas.

O preset local passou no preflight e está registrado no Video Studio. O export
com os nomes exatos do original é preservado para revisão, mas não é registrado
enquanto seus três arquivos ausentes não forem reconhecidos pela instância.
O preflight não comprova compatibilidade dos pesos ou qualidade na GPU;
execuções reais e seus parâmetros estão em [VALIDATION.md](VALIDATION.md).
[Configuração e comandos do preparador](VIDEO_STUDIO.md).

Os nomes abaixo são **nomes propostos para os arquivos a fornecer**, não nomes
de modelos, nós ou workflows que foram inventados. Cada arquivo deve ser
exportado de um pipeline existente que funcione no seu ComfyUI. O Studio não
baixa modelos nem converte posições de widgets por tentativa.

## Lista histórica de exports solicitados no MVP

| Arquivo solicitado em formato API | Módulo / operação | Referência local encontrada |
| --- | --- | --- |
| `character_lab_qwen21_base.api.json` | Imagem-base por prompt; salvar imagem final | Qwen local para retrato, já executado; o MATRIX fornecido é um workflow de edição com referências |
| `character_lab_qwen21_sheet_dataset.api.json` | Sheet, views e dataset; descrever operações realmente suportadas | O MATRIX fornecido contém Dataset de 32 imagens, sem prancha de Sheet. A adaptação atual separa dois exports de Sheet e quatro de Dataset |
| `video_studio_minimax_h3.api.json` | Geração de vídeo, referência de identidade e saída MP4 | `Best Minimax H3 skin realism workflow.json` |
| `voice_omnivoice_tts.api.json` | Texto para áudio, voz/idioma suportados e arquivo de saída | `Omini_voice.json` usa voice_cloning com áudio de referência; não comprova TTS sem referência. O modo desejado precisa de export e validação próprios. |
| `motion_swap_minimax_h3.api.json` | Vídeo-fonte, identidade, LoRA fornecida e saída de vídeo | `MinimaxH3_Char_Swap-20261015.json` |

Se um único export real suportar imagem-base e dataset por um seletor explícito,
ele pode ser registrado em mais de uma operação sem duplicar pesos. Não é
necessário criar um pipeline artificial para atender aos nomes desta tabela.

## Arquivos condicionais, após o primeiro MVP

| Arquivo | Quando é necessário |
| --- | --- |
| `video_lipsync.api.json` | Para habilitar lip-sync com entrada de áudio validada. Não foi identificado um export API comprovado para essa operação. |
| `video_upscale.api.json` | Para expor upscale como operação; `Latent_Up_video_salvo.json` e `NVIDIA UP.JSON` são referências locais a inspecionar, não requisitos da geração inicial. |
| `voice_reference.api.json` | Caso clonagem/referência de voz exija um grafo diferente do TTS; somente com autorização sobre a voz e suporte real do modelo. |

## O que acompanhar cada export

Para **cada** `.api.json`, fornecer:

1. O JSON original da interface (`.ui.json`) para manutenção visual.
2. Um `<nome>.mapping.json` apontando somente para IDs e inputs presentes no
   export API. A estrutura suportada está em [API.md](API.md).
3. Um `<nome>.notes.md` com versão/commit dos custom nodes, nomes e localização
   dos modelos/LoRAs já instalados, operação suportada e saída esperada.
4. Parâmetros de uma execução que já funcionou: resolução, frames/duração,
   steps, seed, formato, uso de offload/quantização e memória observada.
5. Para entradas de áudio/vídeo: classe do nó, campo, tipo esperado e transporte
   real (arquivo no input, upload específico ou outro mecanismo documentado).
6. Para preservação de identidade: referência utilizada, LoRA aplicável,
   força validada e exemplos autorizados de entrada/saída para avaliação.

Não é necessário reenviar pesos. Uma referência aos arquivos existentes basta.
Não publicar prompts, imagens, vozes ou paths privados sem revisão.

## Como obter o formato correto

No ComfyUI, abra o workflow existente, habilite as opções de desenvolvedor se
necessário e use a exportação **API**, não apenas o salvamento do gráfico visual.
O nome do comando pode variar conforme a versão do frontend.

Um export API contém um objeto cujas chaves são IDs de nós e cujos valores
possuem `class_type` e `inputs`. Um arquivo com `nodes`, `links` e
`widgets_values` é um grafo da interface, não o prompt enviado a `/prompt`.

IDs e slots são lidos dos arquivos fornecidos. Na adaptação atual do Sheet,
os IDs 421, 422, 423, 430–434 e 440–444 são novas instâncias explícitas de classes instaladas,
documentadas no manifest; não são nós alegadamente presentes no MATRIX
original. `object_info` do ComfyUI ativo confirma classes, tipos, valores de
modelos e nós de saída antes de registrar.

## Inventário inicial privado

Os cinco JSONs de `<USER_HOME>\Documents\WORK` foram encontrados como
gráficos da interface. Os workflows MATRIX Qwen ficam na instalação Portable,
em `MATRIX-Qwen21-Dataset-Workflow\workflows\normal` e `\turbo`.
As cópias locais preservadas ficam em `workflows/originals/`, fora do Git.
`workflow-inventory.json` contém hashes, formato e nós inspecionados, sem prompts,
valores de widgets ou títulos. Todos os sete arquivos são gráficos UI.
O relatório final da inspeção prevalece sobre nomes de arquivos.

## Critérios para liberar uma operação

- JSON API e mapeamento estruturalmente válidos.
- Todos os custom nodes necessários disponíveis na instância ativa.
- Loaders e LoRAs reconhecidos pelos valores reais de `/object_info`.
- Inputs e saídas coerentes; nenhum caminho arbitrário vindo do navegador.
- Transporte de referências validado para o tipo de mídia.
- Execução real curta concluída, outputs copiados e parâmetros persistidos.
- Qualidade e uso de memória observados e documentados; nenhuma garantia de
  consistência perfeita ou de caber em 16 GB sem essa execução.

A validação automática cobre estrutura, nós e opções. Somente uma execução
real com outputs preservados e inspecionados comprova a operação específica.
O resultado de outro workflow de retrato, vídeo ou voz não valida por
substituição os novos exports de Sheet e Dataset.
