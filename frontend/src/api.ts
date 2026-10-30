export type Module = 'character_lab' | 'video_studio' | 'motion_swap' | 'voice';
export interface Character { id:string; name:string; description:string; prompt:string; attributes?:Record<string,string>; consent_confirmed:boolean; created_at:string; updated_at:string; asset_count:number; preview_asset_id?:string|null }
export interface CharacterOption { value:string; label:string }
export interface CharacterField { key:string; label:string; options:CharacterOption[]; default:string; group:string; description?:string }
export interface CharacterCatalog { names:string[]; fields:CharacterField[]; sections:{id:string;label:string;fields:CharacterField[]}[]; defaults:Record<string,string> }
export interface Asset { id:string; character_id:string; category:string; filename:string; media_type:string; size_bytes:number; url:string; created_at:string; metadata:Record<string,unknown> }
export interface Parameter { node_id:string; input:string; type:'string'|'integer'|'number'|'boolean'|'enum'; required?:boolean; label?:string; description?:string; kind?:string; serializer?:'h3_media_state'; default?:string|number|boolean; choices?:(string|number|boolean)[]; min?:number; max?:number }
export interface Mapping { parameters:Record<string,Parameter>; output_nodes:string[] }
export interface Validation { valid:boolean; errors:unknown[]; warnings:unknown[]; outputs?:unknown[] }
export interface Workflow { id:string; name:string; module:Module; format:string; executable:boolean; mapping:Mapping; video_input_parameters?:string[]; created_at:string; validation?:Validation; inspection:{node_count?:number; candidates?:{node_id:string;input:string;kind:string;linked:boolean}[]; nodes?:{node_id:string;class_type:string}[]; output_nodes?:string[]} }
export interface Job { id:string; module:Module; character_id:string; workflow_id:string; status:string; parameters:Record<string,unknown>; asset_inputs:Record<string,string|string[]>; prompt_id?:string; progress?:Record<string,unknown>|null; error?:string|{code?:string;message?:string;details?:unknown}|null; result_message?:string|null; output_assets:Asset[]; created_at:string; updated_at:string }
export interface Capability { available:boolean; reason:string; workflow_count:number; validated_count:number }
export interface EngineLifecycle { state:'disabled'|'detecting'|'starting'|'waiting'|'ready'|'failed'; message:string; autostart_enabled:boolean; can_retry:boolean; owned_process:boolean; pid:number|null; log_file:string|null; sdk?:EngineLifecycle; comfyui?:EngineLifecycle }
export interface MemoryStatus { enabled:boolean; name:string; phase:string; active_job_id?:string|null; current_pipeline?:{fingerprint?:string;reusable?:boolean;models?:{node_id:string;class_type:string;input:string;value:string}[]}|null; last_measurement?:{at?:string;devices?:{name?:string;type?:string;vram_total?:number;vram_free?:number;torch_vram_total?:number;torch_active_bytes?:number}[];nvidia_smi?:{memory_used_mib?:number;memory_total_mib?:number;memory_free_mib?:number}[]}|null }
export interface System { comfy:{connected:boolean;url:string;error?:string;system_stats?:unknown;lifecycle?:EngineLifecycle}; capabilities:Record<Module,Capability>; queue:{active:number;queued:number}; memory?:MemoryStatus; storage?:Record<string,unknown> }
export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) headers.set('Content-Type','application/json');
  const response = await fetch(`/api${path}`, {...init,headers});
  const value = await response.json().catch(()=>null);
  if (!response.ok) {
    const detail = value?.detail;
    throw new Error(detail ? friendly(detail) : `Falha na requisição (${response.status}).`);
  }
  return value as T;
}
export const labels:Record<Module,string> = { character_lab:'Character Lab', video_studio:'Video Studio', motion_swap:'Motion Swap', voice:'Voice Studio' };
export const statuses:Record<string,string> = {queued:'Na fila',preparing:'Preparando',submitting:'Enviando ao ComfyUI',running:'Em execução',succeeded:'Concluído',failed:'Falhou',cancelled:'Cancelado',needs_attention:'Requer atenção'};
export const categories:Record<string,string> = {identity:'Identidade',character_sheets:'Character sheets',dataset:'Dataset',outfits:'Figurinos',references:'Referências',expressions:'Expressões',poses:'Poses',loras:'LoRAs',audio:'Áudio',videos:'Vídeos'};
export function friendly(value:unknown):string {
  if(typeof value==='string')return value;
  if(Array.isArray(value))return value.map(friendly).join(' · ');
  if(value&&typeof value==='object'){
    const detail=value as Record<string,unknown>;
    const message=typeof detail.message==='string'?detail.message:typeof detail.msg==='string'?detail.msg:'';
    const errors=Array.isArray(detail.errors)&&detail.errors.length?` ${detail.errors.map(friendly).join(' · ')}`:'';
    return message?`${message}${errors}`:JSON.stringify(value);
  }
  return String(value??'');
}
export function date(value:string):string { return new Date(value).toLocaleString('pt-BR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}); }
export function assetUrl(asset:Asset):string { return asset.url || `/api/assets/${asset.id}/file`; }
