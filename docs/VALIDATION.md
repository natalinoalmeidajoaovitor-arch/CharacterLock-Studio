# Validação da primeira entrega

Verificado em 15 de outubro de 2026, neste computador Windows.

## Resultado

- **55 testes do backend passaram** usando `unittest` no Python isolado,
  incluindo inicialização oculta, detecção de instância, exclusão de partidas
  simultâneas, timeout e recuperação limitada do motor.
- **3 testes de backup passaram**, incluindo snapshot SQLite, exclusão de
  temporários, rejeição de backup com backend ativo e destino fora de `data`.
- **Build de produção passou**: TypeScript e Vite 6.4.4, 38 módulos compilados.
- **4 verificações do payload passaram**: mídia excluída dos escalares,
  narração sem prompt visual, identidade com direção de cena e prompt manual
  com direção. Nenhuma geração foi executada para esses testes.
- `/api/health` retornou `200` no serviço local iniciado pelo script documentado.
- `/api/character-options` retornou **22 campos, 52 países e 24 nomes**, com
  seções de identidade, aparência e estilo. Nenhum texto é obrigatório no
  fluxo principal de criação.
- Sete workflows reais encontrados no computador foram preservados com hashes
  conferidos e registrados na biblioteca para inspeção. Nenhum foi executado.
- `openapi.json` e `schema.sql` foram gerados do backend implementado.
- Interfaces independentes dos quatro estúdios com tema cyberpunk, códigos
  decorativos animados, opção de pausar e suporte a movimento reduzido.
- Inicialização oculta usa UTF-8 no processo filho para evitar falhas de logs
  de custom nodes. Respostas saudáveis da API reconciliam falhas antigas do
  lifecycle. A verificação real final confirmou `connected: true` e `ready`.
- `pip check` não encontrou dependências incompatíveis no ambiente isolado.

## O que os testes cobrem

Biblioteca e autorização, persistência, criação por seleções, composição
determinística do prompt, catálogo e validação de opções, independência entre
país/aparência/idioma, edição parcial, preservação de nomes personalizados e
prompts legados, migração de banco v1→v2 sem perder perfis, assets, presets e jobs.

Uploads verificados, limite de corpo com e sem Content-Length, referências do
próprio personagem, bloqueio de traversal, Host/Origin/CORS, WebSocket e
exclusão mútua de processos que compartilham a mesma biblioteca.

Workflows imutáveis, mapeamento de inputs reais, opções de modelos/nós,
parâmetros rejeitados, staging de imagens, resultados e snapshots, falhas
reportadas pelo motor, retomada por prompt_id e não repetição de envios ambíguos.

Os testes de transporte e execução usam fixtures explícitas e respostas
controladas em diretórios temporários. Os logs desses testes podem mostrar
URLs do protocolo ComfyUI, mas não representam gerações na instalação real.
Não há fixtures, personagens de teste ou resultados artificiais inseridos na
biblioteca de produção.

## Limites de verificação

- O navegador recusou permissão para automação no endereço local. A conferência
  visual automatizada não foi realizada; não foi tentado outro caminho para
  contornar esse bloqueio. O usuário abriu a aplicação no próprio navegador.
- Na inspeção inicial o ComfyUI estava desligado. Na validação final da
  inicialização automática, havia uma instância real disponível e ela foi
  reutilizada: `/system_stats` respondeu com ComfyUI `0.39.0` e RTX 5060 Ti.
  O lifecycle do Studio confirmou `ready`, sem duplicar ou encerrar essa
  instância externa. A criação de processo a partir de uma instalação desligada
  foi verificada por testes controlados, sem interromper o motor ativo.
- Todos os sete JSONs encontrados são gráficos da interface, sem export API.
  Geração de imagem, vídeo, voz e swap na GPU **ainda não foi validada**.
- Referências de áudio/vídeo podem ser armazenadas e pré-visualizadas. Seu
  transporte para custom nodes ainda requer adaptação comprovada.
- VRAM/RAM máxima, duração, resolução, qualidade de identidade, lip-sync e
  consistência temporal não foram medidos por geração real nesta entrega.
- Áudio/vídeo recebem verificação de assinatura do container, não análise
  completa de codec ou duração. Os limites estão descritos em `API.md`.
- Starlette emitiu aviso de depreciação de `httpx` no cliente de testes. Os
  testes passaram; uma futura migração desse cliente deve ser feita e validada
  quando necessária, sem reinstalar dependências do ComfyUI.

## Operação local

Dados persistentes: `CharacterLockStudio/data`. O backend e a interface ficaram
ativos em loopback para o usuário continuar usando o configurador. Os scripts
em `scripts/` permitem reiniciar os serviços. Dados temporários de conferência
ficam separados em `.local/`; nenhuma biblioteca do usuário foi apagada.

O próximo passo de integração é fornecer os exports API listados em
[WORKFLOWS_REQUIRED.md](WORKFLOWS_REQUIRED.md). A abertura manual
do motor não é mais necessária: o backend o detecta ou inicia automaticamente.

## Abertura com dois cliques

`Abrir CharacterLock Studio.bat` chama `scripts/open-studio.ps1`. O lançador
reaproveita serviços ativos, inicia backend e frontend ocultos quando necessário,
aguarda suas respostas HTTP e abre somente a página do Studio. Há proteção
contra dois cliques simultâneos e logs de partida separados em `logs/`.
O modo de verificação `-NoBrowser` passou, incluindo partida real do backend
em segundo plano e reutilização da interface e do motor existentes.

## Integração com o SDK oficial

- `comfy-sdk 0.5.0` e `comfy-api-proxy 0.1.6` instalados na `.venv` do Studio;
  `pip check` passou. Nenhum pacote da instalação Portable foi alterado.
- **66 testes Python passaram**, incluindo 11 novos testes do SDK/proxy.
  O SDK e o proxy oficiais são reais nos testes; apenas o upstream das gerações
  de integração é uma fixture explícita em porta temporária.
- Foram verificados submissão com chave estável, ausência de credenciais
  herdadas da nuvem, timeout sem reenvio, rejeição definitiva versus chave já
  utilizada, bloqueio de UI graphs, limite de download mesmo com tamanho
  desconhecido, salvamento na biblioteca e retomada sem outra submissão.
- Reiniciar o proxy de teste preservou idempotência e identificadores das saídas.
  Partida oculta, reutilização e preservação do processo no encerramento foram
  verificadas; configurações de nuvem e portas sobrepostas são recusadas.
- Build TypeScript/Vite passou, com 38 módulos.
- O backend real foi reiniciado sem jobs do Studio ativos. O ComfyUI externo
  permaneceu com sua tarefa em execução. O proxy oficial iniciou em segundo
  plano e o SDK observou essa tarefa como `running` sem submetê-la novamente.
- `/api/system` confirmou `comfy.connected=true`, transporte `comfy-sdk`, proxy
  `http://127.0.0.1:8189` conectado e lifecycle `ready`.
- O SDK oficial também leu 1.024 bytes de uma saída MP4 real já concluída,
  usando Range pelo proxy. O arquivo não foi importado para a biblioteca nem
  gerado novamente. Isso verifica o transporte local de saída, não a qualidade
  ou a execução de um pipeline do Studio.
- Não houve nova inferência de modelo na GPU nesta etapa. Os sete workflows
  registrados continuam exigindo exports API e validação dos pipelines reais.

## Execuções reais posteriores — 16/10/2026

As limitações acima registram a fase inicial. Posteriormente, foram preparadas
cópias API de ramos reais dos workflows privados, sem baixar modelos ou
modificar os originais. Duas execuções do Studio passaram pela fila, SDK e
proxy oficiais, inferência local e recuperação completa dos resultados:

| Operação | Job | Resultado persistido |
| --- | --- | --- |
| Qwen 2.1 — Imagem-base, 512×640, 25 steps | `91ab55db0f0e481b9202c3819e903ca0` | PNG `9dbefde315434478b1d7e19c1eb3a390`, 579.000 bytes. |
| OmniVoice — narração local em português, auto voice | `28f3fb6f01cf4150bb47760dad0d0a3b` | FLAC `01c6efae590a4e4eadac58c2fe299468`, 105.645 bytes. |

O primeiro teste é um retrato único, não um Character Sheet. Não valida
preservação de identidade entre vistas, Dataset, figurinos ou referências.
O teste de voz não é clonagem. A preparação de um export de vídeo não
constitui teste de inferência de vídeo. Motion Swap permanece pendente.

## Reorganização do Character Lab

O novo fluxo é Character Sheet → Dataset → Figurinos → Referências.
Não há associações automáticas dos workflows antigos às quatro etapas.
O workflow real de Character Sheet ainda será fornecido pelo usuário.
A integração e a avaliação visual completas dessa sequência permanecem
pendentes, incluindo sua consistência e reinício durante geração real.

Antes da migração aditiva v3, foi criado um snapshot SQLite consistente em
`.local/lab-before.sqlite3` e uma cópia dos quatro assets existentes. O banco
passou em `integrity_check`. A validação posterior compara IDs, registros,
caminhos e hashes com esse snapshot, sem aprovar ou reclassificar arquivos
de produção para fins de teste.

- **87 testes Python passaram**, incluindo orquestração em fixtures isoladas,
  aprovação, ownership, bloqueios, troca de revisão, reutilização automática,
  retry com contexto original, steps padrão e rollback de saída.
- Backend real reiniciado com fila vazia; ComfyUI e proxy foram reutilizados.
  `/api/system` confirmou conexão pronta após o reinício.
- Banco de produção v3: `integrity_check=ok`, nenhuma violação de chave
  estrangeira, 1 personagem, 4 assets e 4 jobs preservados. Registros antigos
  de personagens, assets, jobs, eventos e presets ficaram idênticos ao backup.
  Conteúdo e mapeamentos dos 10 workflows foram preservados; somente o
  timestamp da validação de um workflow foi atualizado por uma consulta da UI.
- Os hashes dos quatro arquivos continuam iguais. O estado real do Lab retorna
  exatamente as quatro etapas, nenhum Sheet aprovado e nenhum vínculo de
  workflow inventado. As etapas dependentes informam o Sheet pendente.
- Evidência local: `.local/lab-after.json`. Conferência visual automatizada
  permanece indisponível pela permissão de navegador registrada acima.
- Cinco verificações isoladas com ReactDOMServer passaram para os controles
  de aprovação: imports sem revisão podem ser aprovados após cumprir a
  dependência; versões antigas e etapas bloqueadas não podem. Isso verifica
  o markup e os guards do componente, sem substituir a conferência visual.
- Build TypeScript/Vite da nova interface passou, com 40 módulos. A interface,
  o módulo transpilado do Lab e seu CSS responderam `200` no Vite ativo.

## Teste real de áreas com 10 steps — 16/10/2026

Imagem-base Qwen, voz OmniVoice e vídeo MiniMax H3 concluíram sequencialmente
pelo SDK local, com **10 steps confirmados no prompt efetivamente submetido**:

| Área | Job concluído | Saída recuperada |
| --- | --- | --- |
| Imagem-base | `611ff0dc90a747178144275be80020ce` | PNG 512×640, 509.884 bytes. |
| Voz | `0acf611772bf4536857be72adba7f359` | FLAC 24 kHz mono, 4,88 s, 136.193 bytes. |
| Vídeo | `3d889702253c44649d18c3ea1fc8365d` | MP4 H.264 608×352, 22 quadros a 24 fps (0,92 s), 87.542 bytes. |

Os três arquivos foram recuperados pelo SDK, registrados na biblioteca e
servidos pela API com tamanho/hash conferidos. Áudio e MP4 passaram pela
decodificação completa no FFmpeg; imagem e primeiro frame foram inspecionados.
O vídeo levou 295,73 s no motor, incluindo a primeira carga do modelo. Esse
teste curto não equivale a uma avaliação completa de identidade ou qualidade.

O teste encontrou uma falha real de staging: o `LoadImage` instalado enumera
somente arquivos da raiz de input, enquanto o adaptador enviava à subpasta
`characterlock`. A correção usa a raiz com nomes UUID e `overwrite=false`,
mantendo validação estrita. Dois testes de regressão comprovam falha antiga
e sucesso corrigido; **89 testes backend passaram**. A tentativa inicial
`7f8588855af645989839d1b540d5ecef` permanece no histórico; o retry acima passou.

Os mapeamentos de imagem e vídeo foram copiados para permitir 10 steps
suportados pelos nós reais, sem alterar grafos, modelos ou workflows antigos.
Não houve download, alteração manual de arquivos do ComfyUI ou aprovação de
identidade durante os testes.

As cinco tentativas de áreas indisponíveis retornaram os bloqueios esperados,
sem criar jobs: Sheet `422` (workflow sem associação), Dataset/Figurinos/
Referências `409` (Sheet não aprovado), Motion Swap `422` (somente export UI).
Essas áreas **não tiveram geração real validada**. Continuam exigindo os
workflows reais e, para Motion Swap, transporte de vídeo compatível.

Os quatro assets anteriores mantiveram seus hashes. Motor e SDK conectados,
fila vazia ao final. Evidências locais em `.local/smoke-10steps/report.json`,
`blocked-areas.json` e `summary.md`; reprodução em `scripts/smoke_10_steps.py`.

## Sheet Qwen e integração MATRIX — 16/10/2026

Estado posterior ao teste acima: seis exports API foram validados contra os
2.699 nós do ComfyUI instalado e registrados no Lab. São dois Sheets (por
descrição/com referência) e quatro grupos Dataset de oito imagens. O MATRIX
original permanece intacto; diferenças da adaptação estão documentadas em
`CHARACTER_LAB.md` e no manifesto local.

O Sheet com referência concluiu pelo SDK no job
`9b713df1092f4e4e8dc3c38d2abd07be`, prompt
`7cae64c9-ab85-448b-aebe-19d824a916ce`, em 146,66 s no motor. O snapshot
submetido confirma cinco samplers com **10 steps cada**. Foram recuperados:

- Prancha real composta em 2×2: `fd6566bbb4d54dfe8a7360560b129455`, PNG
  1024×1536, 1.919.921 bytes; rosto, frente, lateral e costas.
- Cinco imagens-base 512×768, com categorias distintas: rosto, tronco,
  corpo inteiro, lateral e costas.

As seis imagens passaram pela decodificação PIL e conferência SHA-256 entre
arquivo, registro e download pela API. A prancha e a imagem de tronco foram
inspecionadas visualmente. Este smoke test de 10 steps não certifica qualidade
final ou consistência anatômica completa. Os quatro assets anteriores mantêm
seus hashes. Reprodução: `scripts/smoke_sheet.py check` e `verify`;
evidências privadas em `.local/sheet-live-test.json`.

Nesta primeira etapa, o Sheet e suas auxiliares ficaram pendentes de aprovação humana. O Dataset
tem contrato e preflight validados, mas a execução GPU dos quatro grupos ainda
depende dessa aprovação. Figurinos, Referências e Motion continuam com as
limitações descritas anteriormente.

**94 testes backend passaram**, incluindo transporte H3 de referências,
propriedade de assets, snapshots/retries, aprovação da prancha e vínculo das
auxiliares à mesma revisão. TypeScript e build Vite passaram com 41 módulos.
Os módulos atualizados do Lab, estúdios e CSS responderam HTTP 200 no Vite.
O tema inspirado nos apps Comfy mantém marca CharacterLock, controles à
esquerda, resultados à direita, Voice separado e códigos Matrix discretos.
Não houve QA visual em navegador: a restrição anterior de automação continua
respeitada. OpenAPI/schema foram regenerados do backend com dados isolados.

## Padrão de nove vistas e teste único de cinco fotos — 16/10/2026

Após a revisão do usuário, o padrão do Sheet passou a ser uma prancha fixa
3×3: closes frontal, três quartos e perfil; corpo frontal, lateral, costas,
três quartos, A-pose e mãos na cintura. A imagem de tronco fica separada como
âncora do Dataset. O seletor de novas gerações oferece essas variantes padrão,
preservando as anteriores no histórico.

O job `e1565ca13bb24025870c3795de300569` concluiu pelo SDK em **91,28 s** no
motor, com **10 samplers de 10 steps**. A prancha
`c29471b9567242c496e26e848fa1e604` é PNG 1536×2304, 4.414.870 bytes.
As dez imagens-base 512×768 e a prancha foram recuperadas e conferidas por
decodificação PIL, SHA-256 e download pela API. Prancha e tronco passaram por
inspeção visual. O usuário aprovou a nova prancha no chat; ela define a revisão
`af30bf1a86754f9ea4eecbd036d950f8`, com suas auxiliares vinculadas à mesma versão.
O Sheet anterior 2×2 continua preservado e não aprovado.

Foi executado **somente um teste do Dataset**, conforme pedido, com cinco
saídas e 10 steps em cada sampler. Job:
`675d22f0bcde4373b2698d673f89a889`; workflow:
`1d8360ffd1dc405eb173eead8b48cfeb`. Concluiu em **41,38 s** no motor e produziu
cinco PNGs 512×768: rosto, expressão, perfil, tronco e corpo inteiro.
As cinco imagens passaram por inspeção visual, decodificação, hash e download.

O snapshot confirma cinco `KSampler` e cinco `SaveImage`. Os quatro loaders
H3 receberam listas de 1, 1, 2 e 3 referências, deduplicadas em **três uploads
reais**: rosto, tronco e corpo inteiro aprovados. O contexto e as saídas
conservam a revisão do Sheet. As cinco fotos de Dataset ficam pendentes de
revisão; não foi simulada aprovação nem executado o Dataset completo de 32
imagens. O teste cobre o transporte e a geração, sem certificar a qualidade
final de um dataset para treino.

Reprodução e evidências locais: `scripts/smoke_sheet.py` com
`--report sheet-expanded-live-test.json`, `scripts/smoke_dataset_five.py`,
`.local/sheet-expanded-live-test.json` e `.local/dataset-five-live-test.json`.
O comando de submissão do teste de cinco fotos recusa uma segunda tentativa
automática. Os quatro assets anteriores mantêm seus hashes.

Validação final: **95 testes backend passaram**; TypeScript/Vite passou com
41 módulos. Não houve novos downloads ou alterações de modelos. As
limitações de Figurinos, Referências e Motion não mudaram. O teste não incluiu
QA visual do aplicativo em navegador, respeitando a restrição anterior.

## Video Studio com Realismo + Turbo 8 — 16/10/2026

O usuário selecionou `Best Minimax H3 skin realism workflow.json` e autorizou
usar as LoRAs Turbo presentes na instalação. O original permaneceu intacto,
SHA-256 `c53ae78c351d0dc82b3a056eeb5b0e4cb5af43dd09e0115b3d28b4a4ceb513a2`.
O export do caminho ativo resolve os nós virtuais e mantém a segunda passagem
desativada. O preset local foi registrado como
`be7b270dbede4bbcb784a7a88d0fc2c5`, com preflight válido e 21 nós.

Foram usados os arquivos instalados Singularity Pruned, encoder GGUF Q2_K,
Realism People e Turbo 8 rank24, conforme [VIDEO_STUDIO.md](VIDEO_STUDIO.md).
As duas LoRAs ficam em ordem Realismo → Turbo, ambas com força 1. Os loaders
nativos validam os nomes reais, sem ignorar silenciosamente pesos ausentes.
O gatilho `r34l1sm` é prefixado por um nó próprio e continua presente quando
o app substitui o texto pela identidade/cena. Os headers das duas LoRAs
têm 104/208 módulos-alvo respectivamente, todos presentes no checkpoint e
com dimensões compatíveis. Isso é uma verificação estrutural, sem comprovar
por si só a qualidade da combinação de pesos.

O teste curto concluiu pelo SDK no job
`27175a0ea6e14b198b128d69d3d21f3d`, em **355,16 s** no motor incluindo a carga
inicial, com **8 steps** e as duas forças em 1 confirmadas no snapshot efetivo.
Saída: `f1536912113f4d4188a412b2633a380e`, MP4 H.264 608×352,
**22 quadros a 24 fps (0,92 s)**, AAC 32 kHz estéreo, 70.719 bytes.
O arquivo, registro e download pela API têm o mesmo SHA-256
`e31bb2f70cbc9f0f81cda9f41a4fa9a4a8ea82d89ba03f7c1914c5262123988d`.
Vídeo e áudio passaram pela decodificação completa no FFmpeg; o primeiro
frame foi inspecionado. Os avisos VHS sobre pix_fmt/CRF/metadata/trim referem-se
a defaults conferidos no schema e iguais aos valores do original.

O teste usou 0,4 s solicitados e 0,2 MP. Os defaults do preset **não foram
reduzidos**: continuam 8 steps, 5 s solicitados (124 quadros), 1 MP, 16:9 e
24 fps. O múltiplo de resolução 32, os pesos locais e o encoder são adaptações
explícitas; a variante com os três nomes exatos ausentes continua separada e
não registrada. O clipe curto não valida a execução integral em 5 s/1 MP nem
a qualidade perceptual de toda a sequência.

Reprodução: `scripts/register_video_realism.py --local-installed --register`
prepara/valida/registra sem executar; `scripts/smoke_video_realism.py check`
e `verify` conferem o job já criado. Evidências privadas:
`.local/video-realism-live-test.json`, `.local/video-realism-decode.log` e
`.local/video-realism-frame.png`. Não houve download ou alteração de pesos.
TypeScript e build Vite passaram com 41 módulos. O Video Studio prefere o
preset local, permite escolha manual de outro workflow e mostra as forças e
steps atuais. Não foi realizada automação de navegador.
