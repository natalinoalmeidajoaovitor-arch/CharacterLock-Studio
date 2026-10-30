# Contratos da API — fundação 0.1.0

Base local: `http://127.0.0.1:8000/api`. Interface e API compartilham `/api`
pelo proxy Vite. Não há autenticação pública nesta fase; o servidor exige Host
e Origin de loopback permitidos. `/openapi.json` e `/docs` são gerados pelo código.
Datas são ISO 8601 em UTC; a interface as apresenta no fuso do navegador.

IDs de personagens, assets, presets, workflows e jobs são identificadores
opacos gerados pelo backend. O cliente não fornece caminhos de arquivos.
Corpos JSON recusam campos adicionais nos contratos tipados de requisição.

## Saúde e disponibilidade

- `GET /api/health` → `{status, version, worker}`. Saúde da API não implica ComfyUI disponível.
- `GET /api/system` → `{comfy, capabilities, modules, storage, queue, limitations}`.
  `comfy` contém `connected`, `url`, `error`, `system_stats` e `node_count`.
  Também contém `sdk:{transport,connected,proxy_url}`. Na execução normal,
  `transport="comfy-sdk"`. `comfy.connected` exige motor e proxy conectados.
  Para cada módulo, `available`, `reason`, `workflow_count` e `validated_count`
  reportam a validação atual contra os nós instalados.

Módulos aceitos: `character_lab`, `video_studio`, `motion_swap`, `voice`.
`available` indica a existência de workflow estruturalmente compatível com a
instância atual; não é uma certificação de qualidade ou uso de memória na GPU.

O objeto `comfy.lifecycle` informa `{state,message,autostart_enabled,can_retry,
owned_process,pid,log_file}`. Estados: `detecting`, `starting`, `waiting`,
`ready`, `failed` e `disabled`. O backend inicia o Portable configurado em
segundo plano e confirma prontidão pela API, sem porcentagens artificiais.
Na execução com SDK, `lifecycle.comfyui` e `lifecycle.sdk` trazem os estados
independentes dos dois serviços; o estado principal resume a disponibilidade.
O proxy usa `COMFY_BASE_URL` e `CHARACTERLOCK_SDK_AUTOSTART` como configuração
local. Seu probe valida também se está ligado ao `COMFYUI_URL` configurado.

- `GET /api/engine/status` retorna esse estado em cache sem consultar schemas pesados.
- `POST /api/engine/start` solicita detecção/inicialização e retorna `202`.
  Não aceita caminhos nem comandos no corpo. Chamadas simultâneas compartilham
  a mesma supervisão. A instância reconhecida é reutilizada.

Configuração de execução é local: `CHARACTERLOCK_COMFYUI_DIR`,
`CHARACTERLOCK_COMFYUI_AUTOSTART` e `CHARACTERLOCK_COMFYUI_STARTUP_TIMEOUT`.
O monitor faz recuperação limitada após perda de conexão; falhas ficam visíveis
na interface com opção de repetir. Não há instalação automática de componentes.

## Biblioteca de personagens

`GET /api/character-options` fornece os campos, seções, opções, sugestões de
nome e valores padrão do criador. Cada campo tem `key`, `label`, `default`
e `options:[{value,label}]`. Todos os valores selecionados são IDs string,
incluindo idade e código do país. O catálogo é a autoridade dos valores aceitos.
Não representa suporte de vozes ou modelos de IA.

| Método e rota | Entrada | Saída |
| --- | --- | --- |
| `GET /characters` | — | array de Character |
| `POST /characters` | `{attributes?, name?, description?, prompt?, consent_confirmed:true}` | `201` Character |
| `GET /characters/{id}` | — | Character |
| `PATCH /characters/{id}` | `{attributes?, name?, description?, prompt?}` | Character atualizado |

Character: `{id,name,description,prompt,attributes,consent_confirmed,created_at,updated_at,
asset_count,preview_asset_id}`. Nome de 1–120 caracteres; descrição até 8.000;
prompt até 16.000. Nome em branco após trim é recusado.

Com `attributes`, o backend valida as seleções contra o catálogo e produz
automaticamente nome sugerido, descrição em português e prompt visual em inglês.
Um nome personalizado é opcional. No PATCH, a recomposição acontece apenas
quando `attributes` é enviado; editar apenas o nome preserva prompts anteriores.
O banco recebe migração aditiva, mantendo dados e prompts de perfis legados.

A referência principal automática prioriza a imagem de identidade mais recente.
Seleção manual persistente de referência principal é uma evolução do MVP.

## Assets

| Método e rota | Entrada | Saída |
| --- | --- | --- |
| `GET /characters/{id}/assets` | `?category=` opcional | array de Asset |
| `POST /characters/{id}/assets` | multipart `file`, `category`, `consent_confirmed=true` | `201` Asset |
| `GET /assets/{id}/file` | ID do asset | mídia validada; suporte de Range do FileResponse |

Asset: `{id,character_id,category,filename,media_type,size_bytes,sha256,url,
metadata,created_at}`. `url` é uma rota relativa da API. Não retorna caminho
absoluto interno. Outputs incluem `job_id`, `prompt_id` e nó de origem nos metadados.

Categorias: `identity`, `character_sheets`, `dataset`, `outfits`, `expressions`,
`poses`, `loras`, `audio`, `videos`.

- Imagens: PNG, JPEG, WebP, GIF e BMP, verificadas pelo Pillow, com limite de pixels.
- Áudio: WAV, MP3, FLAC, OGG e M4A; verificação de assinatura do container.
- Vídeo: MP4, MOV e WebM; verificação de assinatura do container.
- LoRA: safetensors, com verificação estrutural do cabeçalho; formatos pickle são recusados.
- Validação de container não equivale a uma análise completa de codec/duração.
- Limite padrão de arquivo: 512 MiB, configurável. Há também limite de corpo
  da requisição antes da leitura pela rota; JSON até 16 MiB.

Importar uma LoRA para a biblioteca não a instala no ComfyUI. Para uso por
um loader, ela deve já estar disponível nas opções reais da instância.

## Presets

- `GET /characters/{id}/presets` → array `{id,character_id,name,parameters,created_at}`.
- `POST /characters/{id}/presets` com `{name,parameters:{...}}` → `201` preset.

Presets são metadados persistidos. Ao reutilizá-los, seus valores ainda passam
pela validação do workflow. Não há treinamento ou aplicação de LoRA implícitos.

## Workflows e mapeamento

- `GET /workflows?module=` → array de resumos Workflow.
- `POST /workflows` com `{name,module,workflow:{...},mapping:{...}}` → `201` Workflow.
- `GET /workflows/{id}` → Workflow incluindo o JSON original registrado.
- `POST /workflows/{id}/validate` com corpo opcional `{parameters:{...}}`
  → `{valid,errors,warnings,...,validated_at}`.

Workflow inclui `{id,name,module,sha256,created_at,format,executable,inspection,
mapping,validation}`. `format` distingue `ui`, `api` e estruturas inválidas.
`executable` verifica o formato/mapeamento; a validação contra a instância ainda
é necessária. Um export UI é armazenado para inspeção, mas não é convertido.

O mapeamento é um objeto com:

| Campo | Contrato |
| --- | --- |
| `parameters` | dicionário de nomes públicos → especificação de parâmetro |
| `output_nodes` | array de IDs reais, como strings, dos nós de saída do export API |
| `node_id` | ID real do nó do parâmetro, obrigatoriamente como string |
| `input` | nome exato do campo presente no `inputs` desse nó |
| `type` | `string`, `integer`, `number`, `boolean` ou `enum` |
| `required` | booleano opcional |
| `default` | escalar opcional, validado pelo tipo e pelo nó |
| `label`, `description` | textos opcionais de apresentação |
| `kind` | `prompt`, `negative_prompt`, `model`, `lora`, `image`, `audio`, `video`, `width`, `height`, `seed`, `duration` ou `other` |
| `choices` | array não vazio; obrigatório para enum, ou restrição adicional |
| `min`, `max` | limites numéricos opcionais, sujeitos aos limites reais do nó |

`node_id`, `input` e `type` ficam dentro da especificação de cada parâmetro.
Não se fornecem IDs fictícios neste documento. Use a inspeção do seu export
API para preenchê-los. Inputs conectados a outros nós não podem ser tratados
como escalares editáveis. Outputs precisam existir e ser nós de saída reais.

Os originais são versionados pelo ID de registro. Para mudar o mapeamento,
registre uma nova versão; jobs anteriores continuam ligados ao registro original.
Modelos e LoRAs precisam coincidir com as opções de `/object_info`.

## Character Lab sequencial

Os endpoints abaixo complementam a biblioteca e a fila existentes:

| Rota | Operação |
| --- | --- |
| `GET /characters/{id}/lab` | Estado das quatro etapas, revisão ativa, referência principal, figurino padrão, assets lógicos, bindings e jobs de origem. |
| `POST /characters/{id}/lab/approve-sheet` | `{asset_id}`; aprova explicitamente um Sheet e define a revisão principal. |
| `PATCH /characters/{id}/lab/assets/{asset_id}` | Aprovação `pending/approved/rejected`, prioridade, categoria, etapa e nome de figurino, sujeitos às dependências e à proveniência. |
| `POST /characters/{id}/lab/default-outfit` | `{asset_id}`; seleciona um figurino aprovado da revisão atual. |
| `POST /lab/workflows` | Associa um workflow API validado a uma etapa, com prompt, steps, papéis de referência e categorias de saída explícitos. |
| `POST /characters/{id}/lab/generate` | Enfileira um Job existente com snapshot de etapa e referências resolvidas automaticamente. |

`stage` aceita `character_sheet`, `dataset`, `outfits` ou `references`.
Geração recebe `stage`, `workflow_id`, `consent_confirmed:true` e, quando
suportados, `steps`, `prompt_text`, `outfit_name`, `reference_asset_id`,
`garment_asset_id`, `outfit_asset_id` e `parameters` avançados. Prompt, steps
e referências automáticas não podem ser sobrescritos em `parameters`.

Sem Sheet aprovado, as demais etapas retornam bloqueio `409`. Figurinos e
Referências também precisam de Dataset aprovado da revisão atual. Sem
workflow explicitamente associado à etapa, gerar retorna `422`. Um arquivo
importado ou gerado não avança a identidade automaticamente. Descarte é
lógico e preserva mídia e histórico. Veja [CHARACTER_LAB.md](CHARACTER_LAB.md).

## Jobs dos quatro estúdios

`POST /jobs` retorna `202` e recebe:

```json
{
  "module": "character_lab",
  "character_id": "ID_OPACO_DO_PERSONAGEM",
  "workflow_id": "ID_OPACO_DO_WORKFLOW_REGISTRADO",
  "parameters": {},
  "asset_inputs": {},
  "consent_confirmed": true
}
```

Os IDs acima são placeholders de contrato. `parameters` usa os nomes públicos
do mapeamento. `asset_inputs` usa esses mesmos nomes → IDs de assets do
personagem selecionado. Um input não pode aparecer nos dois objetos.

Na fundação, staging para o ComfyUI aceita PNG/JPEG/WebP pelo `/upload/image`.
Inputs de áudio/vídeo são recusados explicitamente até existir transporte real
validado. A biblioteca aceita essas mídias para organização e preview.

Job: `{id,module,character_id,workflow_id,status,parameters,asset_inputs,
prompt_id,progress,error,result_message,output_assets,created_at,updated_at}`.
`output_assets` é um array de Assets. `progress` pode ser `null`; sem eventos
de progresso reais não se inventa porcentagem. `error` pode ser `null` ou um
objeto com `code`, `message` e `details`.

- `GET /jobs?character_id=&limit=100` → array de jobs; limite de 1–500.
- `GET /jobs/{id}` → Job e `events:[{status,detail,created_at}]` persistidos.
- `POST /jobs/{id}/cancel` → Job; `409` se já saiu da fila local.
- `POST /jobs/{id}/retry` → `202` com **novo** Job, apenas para estado terminal
  confirmado. IDs de prompt anteriores são conferidos no histórico. Jobs
  `needs_attention` nunca são repetidos por esse endpoint.

Estados: `queued`, `preparing`, `submitting`, `running`, `succeeded`, `failed`,
`cancelled`, `needs_attention`. O worker processa um por vez e observa jobs
que já possuem `prompt_id` após reinício. Um envio ambíguo exige inspeção no
ComfyUI e não é reenviado automaticamente.

Falhas de memória/GPU retornadas pelo motor são preservadas no erro do job.
O Studio não tenta corrigir o workflow, alterar flags ou repetir uma geração
pesada silenciosamente.

## WebSocket

`ws://127.0.0.1:8000/api/ws/jobs` envia:

```json
{"type":"snapshot","jobs":[]}
```

Em seguida, cada mudança observada envia `{type:"job",job:{...}}`.
`{type:"heartbeat"}` mantém a conexão ativa sem alterar progresso.
Na interface, a conexão usa a origem do Vite e fallback de consulta REST.

## Erros e limites

Erros HTTP usam `{detail:...}`. O conteúdo pode ser string, objeto com código
e detalhes, ou array de erros de validação Pydantic.

| Status | Significado |
| --- | --- |
| `400` | corpo/caminho inválido |
| `403` | Host ou Origin não confiável |
| `404` | personagem, asset, workflow ou job ausente |
| `409` | transição ou repetição insegura |
| `413` | arquivo/corpo acima do limite |
| `422` | contrato, formato, mapeamento, mídia ou compatibilidade inválidos |
| `503` | conexão/serviço ComfyUI indisponível |

Alguns custom nodes executam código e acessam arquivos do próprio ComfyUI.
A validação não isola esse código: somente workflows confiáveis devem ser registrados.
