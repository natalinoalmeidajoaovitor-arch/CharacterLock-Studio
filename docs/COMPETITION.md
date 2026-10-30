# Verificação da Comfy Developer Platform

Consulta realizada em 15 de outubro de 2026, horário do Pacífico.

## Requisito confirmado

A [página oficial da competição](https://comfy.org/open-source-higgsfield)
exige uso da Comfy Developer Platform, indicando **Comfy API, Comfy Router
e/ou Comfy SDK**. O texto permite escolher um desses componentes; não exige
usar os três.

Também exige código e workflows em repositório GitHub público, licença open
source e instruções de execução local. O vídeo demonstrativo deve ter até
dois minutos. Um endereço para experimentar a aplicação é opcional.
O prazo informado é **30 de outubro de 2026, às 9h PT**.

O [formulário oficial](https://form.typeform.com/to/V1dSQrkS) confirma os campos
de repositório, demonstração e publicação com `#OpenSourceHiggsfield`. Oferece
Comfy API, Router, SDK, Cloud Agent, Local Agent e MCP como tecnologias usadas.
Para a decisão técnica, seguimos o requisito mais explícito da página principal.

## Execução local é tecnicamente possível

A [documentação oficial do Comfy SDK](https://docs.comfy.org/development/api-development/sdks)
descreve execução em Comfy Cloud, em um deployment ou no ComfyUI do próprio
usuário. No modo local, o SDK usa `COMFY_BASE_URL` apontando para um proxy
local, sem chave de API por padrão.

O [comfy-api-proxy oficial](https://github.com/Comfy-Org/comfy-api-proxy)
expõe a API v2 em frente ao ComfyUI existente. Os endereços padrão são
`127.0.0.1:8188` para ComfyUI e `127.0.0.1:8189` para o proxy. É um serviço
Python separado, com licença MIT; não substitui os modelos ou os workflows.

**Conclusão técnica:** combinar o SDK oficial com o proxy local é um caminho
compatível com as tecnologias exigidas, mantendo a geração na GPU do usuário.
Essa conclusão resulta da leitura conjunta das regras e da documentação;
não representa uma aprovação individual emitida pelos organizadores.

## Situação do CharacterLock Studio

O backend agora usa **`comfy-sdk==0.5.0`** para submeter workflows, observar jobs
por ID e baixar resultados. O **`comfy-api-proxy==0.1.6`** oficial inicia oculto,
com estado persistente, antes da aplicação declarar o motor pronto. Ambos estão
instalados apenas na `.venv` do Studio e registrados em `requirements.txt`.

A biblioteca, a fila e os mapeamentos permanecem integrados a esse transporte.
As entradas de imagem e a descoberta de nós usam as rotas nativas já validadas;
isso não desvia a submissão de geração do SDK. O identificador durável do job
também serve como chave de idempotência. Envios de resultado incerto não são
repetidos automaticamente.

O fluxo worker → SDK oficial → proxy oficial → upstream → biblioteca passou
em teste isolado com servidor upstream de teste, incluindo download e retomada
sem nova submissão. O proxy real iniciou oculto neste computador, confirmou o
ComfyUI correto e o SDK observou uma tarefa local existente em execução.
A API do Studio reportou `comfy.sdk.transport="comfy-sdk"` e conexão pronta.
Também foi verificada a leitura parcial de um MP4 existente pelo SDK e proxy
reais, sem nova geração e sem alterar a biblioteca.

## Execuções locais posteriores

Em 16/10/2026, duas gerações reais do Studio concluíram pelo SDK oficial:
Qwen 2.1 — Imagem-base (`91ab55db0f0e481b9202c3819e903ca0`, PNG) e
OmniVoice — narração local (`28f3fb6f01cf4150bb47760dad0d0a3b`, FLAC).
Ambas salvaram os resultados na biblioteca existente. O teste Qwen é um
retrato, sem comprovação de Character Sheet ou Dataset. Vídeo e Motion Swap
ainda precisam de validação de geração própria.

A reorganização do Character Lab prepara quatro etapas e aguarda o workflow
real de Character Sheet que o usuário fornecerá; não reutiliza o retrato
como prova de consistência. A revisão de licenças e os outros requisitos da
candidatura continuam pendentes. A integração com o SDK não os certifica.
