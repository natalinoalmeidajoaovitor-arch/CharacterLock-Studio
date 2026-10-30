import assert from 'node:assert/strict';
import test from 'node:test';
import { generationAssetInputs, generationBlockers, generationParameters } from '../src/GenerationPayload.ts';

const parameters = {
  identity_image: { node_id: '51', input: 'image', type: 'string', kind: 'image', required: true, label: 'Referência da personagem' },
  scene_prompt: { node_id: '263', input: 'text', type: 'string', kind: 'prompt', required: true, label: 'Direção da cena' },
  steps: { node_id: '332', input: 'steps', type: 'integer', default: 8 },
};
const assets = [
  { id: 'approved-face', character_id: 'sofia', media_type: 'image/png', metadata: { lab: { approval: 'pending' } } },
  { id: 'manual-reference', character_id: 'sofia', media_type: 'image/jpeg' },
  { id: 'other-face', character_id: 'other-character', media_type: 'image/png' },
  { id: 'unsupported-image', character_id: 'sofia', media_type: 'image/gif' },
  { id: 'narration', character_id: 'sofia', media_type: 'audio/flac' },
  { id: 'driver-mp4', character_id: 'sofia', media_type: 'video/mp4' },
  { id: 'driver-webm', character_id: 'sofia', media_type: 'video/webm' },
];
const assetRequest = { module: 'video_studio', characterId: 'sofia', parameters, assets, selected: {} };
const readiness = {
  busy: false, checking: false, hasWorkflow: true, validationValid: true,
  connected: true, hasCharacter: true, consent: true, parameters,
  scalarParameters: { scene_prompt: 'Sofia smiles at the camera.', steps: 8 },
  assetInputs: {}, unboundDraft: false,
};

test('a validated video becomes ready only when its approved face is available', () => {
  const withoutFace = generationAssetInputs(assetRequest);
  assert.deepEqual(generationBlockers({ ...readiness, assetInputs: withoutFace }), ['Preencha Referência da personagem.']);
  const withFace = generationAssetInputs({ ...assetRequest, preferredReferenceId: 'approved-face' });
  assert.deepEqual(withFace, { identity_image: 'approved-face' });
  assert.deepEqual(generationBlockers({ ...readiness, assetInputs: withFace }), []);
  // The API's current approved anchor is authoritative; creation metadata can be stale.
  assert.equal(assets[0].metadata.lab.approval, 'pending');
});

test('manual reference and explicit clearing take precedence over the approved face', () => {
  assert.deepEqual(generationAssetInputs({ ...assetRequest, preferredReferenceId: 'approved-face', selected: { identity_image: 'manual-reference' } }), { identity_image: 'manual-reference' });
  const cleared = generationAssetInputs({ ...assetRequest, preferredReferenceId: 'approved-face', selected: { identity_image: '' } });
  assert.deepEqual(cleared, {});
  assert.deepEqual(generationBlockers({ ...readiness, assetInputs: cleared }), ['Preencha Referência da personagem.']);
});

test('a stale or unsupported reference never falls back to an arbitrary library image', () => {
  for (const preferredReferenceId of ['other-face', 'unsupported-image', 'missing-image']) {
    assert.deepEqual(generationAssetInputs({ ...assetRequest, preferredReferenceId }), {});
    assert.deepEqual(generationAssetInputs({ ...assetRequest, preferredReferenceId: 'approved-face', selected: { identity_image: preferredReferenceId } }), {});
  }
  assert.deepEqual(generationAssetInputs({ ...assetRequest, characterId: 'other-character', preferredReferenceId: 'approved-face' }), {});
  assert.deepEqual(generationAssetInputs({ ...assetRequest, characterId: undefined, preferredReferenceId: 'approved-face' }), {});
});

test('automatic references are limited to the named video identity input', () => {
  for (const module of ['character_lab', 'voice', 'motion_swap']) {
    assert.deepEqual(generationAssetInputs({ ...assetRequest, module, preferredReferenceId: 'approved-face' }), {});
  }
  assert.deepEqual(generationAssetInputs({ ...assetRequest, parameters: { garment: parameters.identity_image }, preferredReferenceId: 'approved-face' }), {});
  assert.deepEqual(generationAssetInputs({ ...assetRequest, parameters: { identity_image: { ...parameters.identity_image, kind: 'audio' } }, preferredReferenceId: 'approved-face' }), {});
});

test('other modules retain valid manually selected media without leaking unknown inputs', () => {
  const voiceParameters = { voice_reference: { type: 'string', kind: 'audio' } };
  assert.deepEqual(generationAssetInputs({ ...assetRequest, module: 'voice', parameters: voiceParameters, selected: { voice_reference: 'narration', unknown: 'manual-reference' } }), { voice_reference: 'narration' });
  assert.deepEqual(generationAssetInputs({ ...assetRequest, selected: { identity_image: 'manual-reference', unknown: 'approved-face' } }), { identity_image: 'manual-reference' });
});

test('validated VHS_LoadVideo MP4 inputs are accepted while unsupported video or audio inputs remain blocked', () => {
  const swapParams = { source_video: { node_id: '10', input: 'video', type: 'string', kind: 'video', required: true, label: 'Vídeo de origem' } };
  assert.deepEqual(generationAssetInputs({ ...assetRequest, module: 'motion_swap', parameters: swapParams, selected: { source_video: 'driver-webm' } }), {});
  assert.deepEqual(generationAssetInputs({ ...assetRequest, module: 'motion_swap', parameters: swapParams, selected: { source_video: 'driver-mp4' } }), { source_video: 'driver-mp4' });
  assert.deepEqual(generationBlockers({ ...readiness, parameters: swapParams, scalarParameters: {}, assetInputs: { source_video: 'driver-mp4' } }), ['O upload de áudio/vídeo para este workflow ainda está indisponível.']);
  assert.deepEqual(generationBlockers({ ...readiness, parameters: swapParams, scalarParameters: {}, assetInputs: {}, supportedVideoInputs: ['source_video'] }), ['Preencha Vídeo de origem.']);
  assert.deepEqual(generationBlockers({ ...readiness, parameters: swapParams, scalarParameters: {}, assetInputs: { source_video: 'driver-mp4' }, supportedVideoInputs: ['source_video'] }), []);
});

test('a valid reference does not bypass consent or other execution requirements', () => {
  const ready = { ...readiness, assetInputs: { identity_image: 'approved-face' } };
  assert.deepEqual(generationBlockers({ ...ready, consent: false }), ['Confirme a autorização para gerar.']);
  for (const patch of [
    { busy: true }, { checking: true }, { hasWorkflow: false }, { validationValid: false },
    { connected: false }, { hasCharacter: false }, { unboundDraft: true },
    { scalarParameters: { scene_prompt: '', steps: 8 } },
  ]) assert.ok(generationBlockers({ ...ready, ...patch }).length > 0, JSON.stringify(patch));
  assert.deepEqual(generationBlockers({ ...ready, parameters: { optional_audio: { kind: 'audio' } } }), ['O upload de áudio/vídeo para este workflow ainda está indisponível.']);
});

test('zero and false are valid required scalar values', () => {
  assert.deepEqual(generationBlockers({
    ...readiness, parameters: { amount: { required: true }, enabled: { required: true } },
    scalarParameters: { amount: 0, enabled: false },
  }), []);
});

test('whitespace cannot silently satisfy the required scene prompt', () => {
  assert.deepEqual(generationBlockers({ ...readiness, assetInputs: { identity_image: 'approved-face' }, scalarParameters: { scene_prompt: '  \n  ', steps: 8 } }), ['Preencha Direção da cena.']);
});

test('the generation payload keeps image IDs out of scalar parameters', () => {
  const scalarParameters = generationParameters({
    module: 'video_studio', parameters,
    values: { identity_image: 'approved-face', scene_prompt: 'Original direction', steps: 8, unknown: 'discard me' },
    identityPrompt: 'Sofia identity', useIdentity: true, directionText: 'Turn toward the camera.',
  });
  assert.deepEqual(scalarParameters, { scene_prompt: 'Sofia identity\n\nTurn toward the camera.', steps: 8 });
  assert.equal('identity_image' in scalarParameters, false);
});
