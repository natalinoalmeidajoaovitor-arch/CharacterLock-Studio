import type { Asset, Module, Parameter, Workflow } from './api';

type Scalar = string | number | boolean;
export interface GenerationValues {
  module: Module;
  parameters: Record<string, Parameter>;
  values: Record<string, Scalar>;
  identityPrompt?: string;
  useIdentity: boolean;
  speechText?: string;
  directionText?: string;
}

export interface GenerationAssets {
  module: Module;
  characterId?: string;
  parameters: Record<string, Parameter>;
  assets: Asset[];
  selected: Record<string, string>;
  preferredReferenceId?: string | null;
}

export interface GenerationReadiness {
  busy: boolean;
  checking: boolean;
  hasWorkflow: boolean;
  validationValid?: boolean;
  connected: boolean;
  hasCharacter: boolean;
  consent: boolean;
  parameters: Record<string, Parameter>;
  scalarParameters: Record<string, Scalar>;
  assetInputs: Record<string, string>;
  unboundDraft: boolean;
  supportedVideoInputs?: string[];
}

const imageTypes = ['image/png', 'image/jpeg', 'image/webp'];
const mediaKinds = ['image', 'audio', 'video'];

/** Resolve a reviewed face without replacing a manual choice or explicit clearing. */
export function generationAssetInputs(input: GenerationAssets): Record<string, string> {
  const result: Record<string, string> = {};
  if (!input.characterId) return result;
  const isValidAsset = (assetId: string, kind: string) => input.assets.some(asset =>
    asset.id === assetId && asset.character_id === input.characterId &&
    (kind === 'image' ? imageTypes.includes(asset.media_type.toLowerCase()) :
     kind === 'video' ? asset.media_type.toLowerCase() === 'video/mp4' :
     asset.media_type.startsWith(`${kind}/`)),
  );
  for (const [name, assetId] of Object.entries(input.selected)) {
    const kind = input.parameters[name]?.kind;
    if (assetId && kind && mediaKinds.includes(kind) && isValidAsset(assetId, kind)) result[name] = assetId;
  }
  if (input.module === 'video_studio' && input.parameters.identity_image?.kind === 'image' &&
      !Object.hasOwn(input.selected, 'identity_image') && input.preferredReferenceId &&
      isValidAsset(input.preferredReferenceId, 'image')) {
    result.identity_image = input.preferredReferenceId;
  }
  return result;
}

/** The same reasons shown beside Generate determine whether it can be submitted. */
export function generationBlockers(input: GenerationReadiness): string[] {
  const reasons: string[] = [];
  if (input.busy) reasons.push('Adicionando a tarefa à fila.');
  if (input.checking) reasons.push('Validando o workflow.');
  if (!input.hasWorkflow) reasons.push('Selecione um workflow.');
  if (input.hasWorkflow && !input.checking && !input.validationValid) reasons.push('O workflow precisa estar validado.');
  if (!input.connected) reasons.push('Aguardando conexão com o ComfyUI.');
  if (!input.hasCharacter) reasons.push('Selecione um personagem.');
  if (!input.consent) reasons.push('Confirme a autorização para gerar.');
  for (const [name, parameter] of Object.entries(input.parameters)) {
    if (!parameter.required) continue;
    const value = mediaKinds.includes(parameter.kind || '') ? input.assetInputs[name] : input.scalarParameters[name];
    if (value === undefined || (typeof value === 'string' && !value.trim())) reasons.push(`Preencha ${parameter.label || name}.`);
  }
  const supportedVideos = new Set(input.supportedVideoInputs || []);
  if (Object.entries(input.parameters).some(([name, parameter]) => parameter.kind === 'audio' || (parameter.kind === 'video' && !supportedVideos.has(name)))) {
    reasons.push('O upload de áudio/vídeo para este workflow ainda está indisponível.');
  }
  if (input.unboundDraft) reasons.push('Vincule o texto da cena ou narração a uma entrada de prompt.');
  return reasons;
}

/** Prefer the locally registered realism preset without tying selection to its ID. */
export function preferredGenerationWorkflow(options: Workflow[], module: Module): Workflow | undefined {
  if (module === 'video_studio') {
    const preset = options.find(workflow => {
      const parameters = workflow.mapping.parameters;
      return parameters.realism_strength?.default === 1 && parameters.turbo_strength?.default === 1;
    });
    if (preset) return preset;
  }
  if (module === 'motion_swap') {
    const preset = options.find(workflow => workflow.format === 'api' && workflow.executable && workflow.mapping.parameters.target_person !== undefined)
      || options.find(workflow => workflow.format === 'api' && workflow.executable);
    if (preset) return preset;
  }
  return options[0];
}

/** Only explicitly mapped scalar inputs may cross the generation API boundary. */
export function generationParameters(input: GenerationValues): Record<string, Scalar> {
  const result: Record<string, Scalar> = {};
  for (const [name, parameter] of Object.entries(input.parameters)) {
    if (['image', 'audio', 'video'].includes(parameter.kind || '')) continue;
    let value: Scalar | undefined = input.values[name];
    if (parameter.kind === 'prompt') {
      if (input.module === 'voice' && input.speechText !== undefined && input.speechText.trim() !== '') {
        value = input.speechText;
      } else if (input.module !== 'voice') {
        if (input.module === 'motion_swap') {
          if (input.useIdentity && input.identityPrompt) {
            value = [String(value ?? '').trim(), input.identityPrompt.trim()].filter(Boolean).join('\n\n');
          }
        } else if (input.useIdentity && input.identityPrompt) {
          value = input.identityPrompt;
        }
        if (input.module === 'video_studio' && input.directionText?.trim()) {
          value = [String(value ?? '').trim(), input.directionText.trim()].filter(Boolean).join('\n\n');
        }
      }
    }
    if (value !== undefined) result[name] = value;
  }
  return result;
}
