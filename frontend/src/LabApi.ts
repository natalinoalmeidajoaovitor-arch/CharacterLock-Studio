import { api } from './api';
import type { Job } from './api';

export type LabStage = 'character_sheet' | 'dataset' | 'outfits' | 'references';
export type LabApproval = 'pending' | 'approved' | 'rejected';
export type SheetAnchor = 'face' | 'upper_body' | 'full_body';
export type LabReferenceRole = 'sheet' | 'sheet_face' | 'sheet_upper_bundle' | 'sheet_full_bundle' | 'dataset' | 'outfit' | 'optional_reference' | 'garment';
export interface LabAsset {
  asset_id: string;
  stage: LabStage;
  category: string;
  approval: LabApproval;
  priority: boolean;
  revision_id: string | null;
  legacy: boolean;
  outfit_name?: string;
  job_id?: string;
}
export interface LabWorkflowBinding {
  workflow_id: string;
  stage: LabStage;
  prompt_parameter: string | null;
  steps_parameter: string | null;
  reference_parameters: Record<string, LabReferenceRole>;
  output_categories: Record<string, string>;
  prompt_template?: string;
}
export interface LabState {
  character_id: string;
  active_revision_id: string | null;
  principal_asset_id: string | null;
  sheet_anchors: Record<SheetAnchor, string | null>;
  default_outfit_asset_id: string | null;
  revisions: { id: string; sheet_asset_id: string; created_at: string }[];
  stages: { key: LabStage; locked: boolean; reason: string | null; complete: boolean; workflow_ids: string[] }[];
  assets: LabAsset[];
  workflow_bindings: LabWorkflowBinding[];
  jobs: { job_id: string; stage: LabStage; revision_id: string | null }[];
}
export interface LabGenerateRequest {
  stage: LabStage;
  workflow_id: string;
  steps?: number;
  prompt_text?: string;
  outfit_name?: string;
  reference_asset_id?: string;
  garment_asset_id?: string;
  outfit_asset_id?: string;
  parameters?: Record<string, string | number | boolean>;
  consent_confirmed: true;
}
export type LabAssetPatch = Partial<Pick<LabAsset, 'approval' | 'priority' | 'stage' | 'category' | 'outfit_name'>>;
const base = (characterId: string) => `/characters/${encodeURIComponent(characterId)}/lab`;

export const labApi = {
  get: (characterId: string, signal?: AbortSignal) => api<LabState>(base(characterId), { signal }),
  approveSheet: (characterId: string, assetId: string) => api<LabState>(`${base(characterId)}/approve-sheet`, { method: 'POST', body: JSON.stringify({ asset_id: assetId }) }),
  patchAsset: (characterId: string, assetId: string, patch: LabAssetPatch) => api<LabState>(`${base(characterId)}/assets/${encodeURIComponent(assetId)}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  defaultOutfit: (characterId: string, assetId: string) => api<LabState>(`${base(characterId)}/default-outfit`, { method: 'POST', body: JSON.stringify({ asset_id: assetId }) }),
  generate: (characterId: string, request: LabGenerateRequest) => api<Job>(`${base(characterId)}/generate`, { method: 'POST', body: JSON.stringify(request) }),
};
