# Character Lab: fluxo por identidade

O módulo existente passa a organizar a produção em quatro etapas:
**Character Sheet → Dataset → Figurinos → Referências**. A biblioteca, a
sidebar, o tema e os estúdios de vídeo, voz e motion continuam compartilhando
os serviços atuais. Expressões e poses são categorias internas do Dataset.

## Estado desta entrega

O usuário forneceu `MATRIX-Qwen21-Dataset-V4.json` e autorizou adaptar o Qwen
local para gerar o Character Sheet. O original MATRIX produz um Dataset de
32 imagens; não contém uma prancha de Character Sheet. O preparador
`scripts/register_matrix_lab.py` cria seis exports API derivados: duas variantes
de Sheet e quatro grupos de Dataset. Com `--with-smoke5`, também prepara um
sétimo export para o teste único de cinco fotos. O JSON original permanece
intocado. O preflight das sete definições atuais passou contra a instância
ativa; os IDs de registro, quando presentes, ficam no manifest privado.

O pipeline **Qwen 2.1 — Imagem-base**, já testado, continua sendo um retrato,
sem aprovação automática como Sheet. A execução e a consistência visual dos
novos exports precisam de evidência própria, registrada em [VALIDATION.md](VALIDATION.md).
Figurinos e Referências ainda precisam de workflows reais associados.

## Sheet adaptado e imagens-base

As variantes **por descrição** e **com referência** usam sempre o mesmo
padrão de nove painéis, montado pelo nó instalado `ImageGridComposite3x3`:

| Linha da prancha | Painéis, da esquerda para a direita |
| --- | --- |
| Rosto em close | Frente, três quartos e perfil |
| Corpo inteiro | Frente, perfil e costas |
| Vistas e poses | Três quartos, A-pose e mãos na cintura |

Os closes e as poses fazem parte do padrão do Sheet, sem exigir uma seleção
extra em cada geração. O grafo gera ainda uma imagem separada de tronco para
servir como âncora do Dataset. São dez samplers e dez imagens-base reais,
além da prancha de nove painéis. A saída principal é a prancha; todos os
arquivos individuais permanecem na biblioteca e associados ao mesmo job.
As referências seguem a cadeia rosto → tronco → corpo frontal, que alimenta
as demais vistas e poses.

A primeira adaptação, com cinco imagens-base e uma prancha 2 × 2, permanece
como teste histórico. Ela não foi aprovada como identidade principal e não
define o novo padrão com closes e mais poses.

A variante por descrição não contém loader de referência. A variante com
referência exige uma imagem válida da biblioteca, normalizada para 512 × 768
antes da edição. A descrição física vem do perfil salvo; não depende de um
texto adicional digitado no formulário. Os steps são compartilhados pelos
dez samplers e começam em 10 para a execução curta solicitada pelo usuário.
Esse valor não representa uma validação de qualidade final nem uma conversão
para o modelo Turbo.

A adaptação reutiliza o encoder local `qwen3vl_8b_w4a8.safetensors`, que já
foi executado neste computador. O encoder int8 citado no workflow original
não está instalado. Essa diferença é explícita: não foram baixados pesos nem
alterados os modelos ou o arquivo original. Os demais loaders são conferidos
contra as opções da instância ativa.

Nas edições, `resolution=0` preserva o tamanho das referências e o sampler
usa a saída latent do próprio `TextEncodeQwenImage21`, para corresponder à
primeira imagem. Essa escolha segue a orientação oficial para evitar
deslocamentos na edição; os exports locais não prometem a resolução 2K do
workflow original. [Orientação do Comfy](https://comfy.org/qwen-image-2.1/).

## Aprovação e revisões

Gerar ou importar uma imagem não aprova a identidade automaticamente.
**Aprovar Character Sheet** define explicitamente a referência principal e
cria uma revisão. Somente a prancha principal pode definir essa identidade;
closes, tronco, corpo, vistas e poses são saídas auxiliares. A aprovação da
prancha também aprova essas imagens-base do mesmo job concluído, vinculando-as
à mesma revisão. Dataset exige essa aprovação. Figurinos e Referências
exigem também pelo menos uma imagem aprovada do Dataset da revisão atual.

Trocar o Character Sheet cria outra revisão e limpa a seleção de figurino
padrão. Os arquivos anteriores continuam disponíveis, associados à revisão
anterior; não são substituídos nas gerações concluídas. Aprovar, descartar e
priorizar são operações sobre metadados. Descartar não apaga o arquivo físico
nem remove o resultado do histórico.

Cada imagem do Dataset pode ser classificada em rosto, corpo, ângulos,
expressões, poses ou referências de identidade. As referências prioritárias
aprovadas têm preferência quando o workflow possui inputs de Dataset. Criar
um Dataset não inicia treinamento de LoRA.

O estado da personagem expõe `sheet_anchors.face`, `sheet_anchors.upper_body`
e `sheet_anchors.full_body`. São IDs de imagens aprovadas da revisão e do job
da prancha principal. Um Sheet importado sem essas imagens-base ainda pode
ser aprovado como prancha, mas não satisfaz automaticamente os grupos MATRIX
que exigem as âncoras ausentes. A geração informa essa pendência; não repete
uma única imagem nos três papéis.

## Dataset MATRIX em quatro grupos

| Workflow derivado | Saídas por job | Referências resolvidas automaticamente |
| --- | --- | --- |
| Expressões e rosto | 8 | Rosto aprovado do Sheet |
| Rosto em 360° | 8 | Rosto aprovado do Sheet |
| Tronco em 360° | 8 | Rosto e tronco aprovados, nessa ordem |
| Corpo inteiro em 360° | 8 | Rosto, tronco e corpo inteiro aprovados, nessa ordem |

Os quatro grupos mantêm as instruções por vista, offsets de seed e parâmetros
de sampling do MATRIX, com a adaptação local de encoder e latent descrita
acima. A identidade do perfil é acrescentada ao primeiro prompt de cada
grupo; as imagens-base são referências em todas as vistas. O mapeamento de
steps tem valor inicial 10, aplicado ao controle inteiro compartilhado do
grupo. São quatro gerações separadas de oito imagens, não uma opção fictícia
de quantidade de imagens.

### Teste único de cinco fotos

O export adicional **MATRIX Qwen 2.1 · Teste de 5 fotos** executa exatamente
cinco edições do MATRIX em um único job: rosto, expressão, perfil do rosto,
tronco e corpo inteiro. Os cinco samplers usam o mesmo controle de 10 steps.
Os quatro loaders recebem as âncoras aprovadas de rosto, tronco e corpo
conforme a vista, e uploads repetidos do mesmo asset são deduplicados.

Essa variante é preparada com `--with-smoke5`. Ela não executa os quatro
grupos completos nem dispara quatro jobs. O padrão de produção continua
sendo quatro grupos separados de oito imagens, totalizando 32. O teste
depende do novo Sheet aprovado e não é executado pelo simples registro.

O autor do MATRIX documenta a estrutura de 32 imagens com referências de
rosto, tronco e corpo. O Qwen documenta geração e edição com preservação de
identidade; isso fundamenta a adaptação, sem garantir consistência perfeita.
[MATRIX](https://github.com/JsonMatrixLab/MATRIX-Qwen21-Dataset-Workflow),
[Qwen-Image-2.1](https://github.com/QwenLM/Qwen-Image-2.1).

## Registro de um workflow real

Primeiro, importar o export API e seu mapeamento pelo gerenciador existente.
Depois, registrar sua associação a uma etapa em `POST /api/lab/workflows`.
A associação declara, usando os nomes públicos do mapeamento:

- `workflow_id` e `stage`: workflow existente e uma das quatro etapas.
- `prompt_parameter`: input de texto que receberá a descrição da personagem.
- `steps_parameter`: input inteiro real de steps, quando suportado.
- `reference_parameters`: inputs de imagem e sua função: `sheet`, `dataset`,
  `outfit`, `optional_reference`, `garment`, `sheet_face`,
  `sheet_upper_bundle` ou `sheet_full_bundle`.
- `output_categories`: categoria lógica de cada nó de saída selecionado.
- `prompt_template`: opcional, com `{identity}` e `{prompt}` para preservar
  a organização exigida pelo workflow. Sem template, preserva-se o texto
  original e acrescentam-se identidade e pedido da etapa.

O backend confere formato API, módulo, mapeamento e nós/opções da instalação
local. Dataset precisa de uma das funções `sheet`, `sheet_face`,
`sheet_upper_bundle` ou `sheet_full_bundle`. Figurinos e Referências precisam
de referência aprovada de identidade. Um input de imagem presente no grafo
deve receber um asset válido: marcá-lo como opcional no mapeamento não remove
o nó nem permite reutilizar silenciosamente o nome de um arquivo de exemplo.
Um caminho sem referência deve existir no próprio workflow real.

Não se inventam nós, nomes de modelos, slots ou recursos de quantidade/tipos
de imagens. A adaptação autorizada acrescenta instâncias de classes realmente
instaladas: nós 421 (grid 3 × 3), 422 (salvamento da prancha), 423 (normalização
da referência, somente na variante com imagem), 430–434 (A-pose) e 440–444
(mãos na cintura). As duas novas cadeias de pose usam as classes reais de
encoder Qwen, sampler, decode, salvamento e expressão de seed. Esses IDs novos não são
apresentados como parte do original MATRIX. Controles adicionais aparecem
somente quando expostos no mapeamento. A integração de cada JSON inclui inspeção e teste local antes de
declarar a operação validada.

O loader `MiniMaxH3MediaLoader.media_state` usa um parâmetro de imagem:string
explicitamente obrigatório, sem default e com `serializer: "h3_media_state"`.
Somente esse adaptador aceita listas de 1 a 9 IDs de imagens da personagem.
O worker faz upload, reutiliza o mesmo upload quando o ID se repete e monta
o JSON exigido pelo loader com nomes relativos retornados pelo motor. Um
input de imagem comum continua aceitando uma única referência.

Para preparar os arquivos e conferir o schema da instância ativa:

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\register_matrix_lab.py'
```

Os exports, mapeamentos, vínculos e resultados de preflight ficam na pasta
privada `workflows/local/matrix-lab/`, junto com o manifest de origem e
adaptações. Acrescentar `--register` importa as seis definições padrão e seus
vínculos no backend local; combinar `--with-smoke5 --register` inclui também
o único workflow de teste de cinco fotos. O registro não gera imagens nem
aprova uma identidade. A fonte é
conferida por hash antes da conversão e as classes e opções são verificadas
por `object_info`. Um preflight bem-sucedido ainda exige teste real na GPU.

## Origem e atribuição

**Built with Qwen.** O modelo Qwen-Image-2.1 conserva a
[Qwen Research License Agreement](https://github.com/QwenLM/Qwen-Image-2.1/blob/main/LICENSE).
Os JSONs e a documentação originais MATRIX conservam a
[licença Apache 2.0](https://github.com/JsonMatrixLab/MATRIX-Qwen21-Dataset-Workflow/blob/main/LICENSE).
As adaptações locais são identificadas no manifest; não há redistribuição
de pesos neste projeto. A licença MIT do código do Studio não substitui
as licenças de modelos, workflows e custom nodes.

## Execução e armazenamento

`POST /api/characters/{id}/lab/generate` resolve os assets a partir da
personagem e registra um snapshot de etapa, revisão, descrição, parâmetros,
workflow e referências antes de liberar a fila. O worker sequencial existente
usa o Comfy SDK oficial e o staging de imagens já implementado. As saídas
retornam à biblioteca com classificação e origem da geração.

A migração SQLite v3 é aditiva: tabelas `lab_*` armazenam vínculos, revisões,
aprovações e snapshots sem alterar os registros ou caminhos legados.
`profile.json` inclui os ponteiros do Lab. As pastas físicas existentes são
preservadas; categorias internas do Dataset são metadados, sem mover imagens
de expressões ou poses antigas. Novas referências usam a categoria
`references` e continuam acessíveis aos demais módulos por ID de asset.

Os endpoints de estado e aprovação estão documentados em [API.md](API.md).
Os critérios de execução ainda pendentes estão em
[WORKFLOWS_REQUIRED.md](WORKFLOWS_REQUIRED.md).
