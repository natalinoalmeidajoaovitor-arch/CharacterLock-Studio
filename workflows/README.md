# Workflows reais

Os originais locais foram preservados byte a byte em `originals/`, com SHA-256 no inventário. Essa pasta é ignorada pelo Git: os JSONs podem conter prompts, nomes de arquivos e dados pessoais. O inventário público registra somente estrutura e campos observados.

Os arquivos fornecidos e os dois workflows Qwen encontrados são grafos da interface do ComfyUI. Eles podem ser inspecionados na aplicação, mas a execução fica indisponível até importar a exportação **API format** feita pelo próprio ComfyUI. A aplicação não converte posições de widgets em inputs.

Para executar, registre o JSON de API e um mapeamento explícito com esta estrutura:

```json
{
  "parameters": {},
  "output_nodes": []
}
```

Preencha `parameters` com nomes públicos e especificações `{ "node_id": "ID real", "input": "campo real", "type": "string" }`. Os tipos aceitos são `string`, `integer`, `number`, `boolean` e `enum`. Campos opcionais: `required`, `default`, `label`, `description`, `kind`, `choices`, `min` e `max`. `enum` exige `choices`. `kind` pode ser `prompt`, `negative_prompt`, `model`, `lora`, `image`, `audio`, `video`, `width`, `height`, `seed`, `duration` ou `other`.

`output_nodes` deve conter IDs reais de nós de saída confirmados por `/object_info`. Parâmetros só podem alterar inputs literais já existentes; não podem criar IDs, criar campos ou substituir conexões. O prompt original é copiado para cada execução.

A validação consulta os schemas e as escolhas instaladas em `/object_info`, verifica inputs obrigatórios, tipos, conexões e caminhos relativos. O servidor faz a validação final em `/prompt`. Isso não garante compatibilidade entre modelos nem consumo de VRAM.

Referências de imagem podem ser vinculadas a assets da biblioteca e enviadas por `/upload/image`. Áudio e vídeo permanecem na biblioteca local até existir um adaptador de transferência validado para os nós usados; não existe um upload genérico presumido.

São necessários os exports de API correspondentes a:

- Qwen: `MATRIX-Qwen21-Dataset-V4.json` ou `MATRIX-Qwen21-Dataset-V4-Turbo.json`, conforme o pipeline escolhido.
- Vídeo: `Best Minimax H3 skin realism workflow.json`.
- Motion Swap: `MinimaxH3_Char_Swap-20261015.json`.
- Voz: `Omini_voice.json`.
- Pós-processamento opcional: `Latent_Up_video_salvo.json` e `NVIDIA UP.JSON`.

O inventário foi gerado sem carregar modelos e sem executar gerações. Referências técnicas: [rotas oficiais](https://docs.comfy.org/development/comfyui-server/comms_routes) e [servidor do ComfyUI](https://github.com/Comfy-Org/ComfyUI/blob/master/server.py).
