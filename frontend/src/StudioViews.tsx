import { useState } from 'react';
import type { ReactNode } from 'react';
import type { Asset, Character, Job, Module } from './api';
import { assetUrl, date, friendly } from './api';
import { Badge, Button, Icon, JobProgress } from './components';

export interface StudioViewProps {
  character?: Character;
  characters: Character[];
  selectedId: string;
  onSelectCharacter: (id: string) => void;
  assets: Asset[];
  jobs: Job[];
  onUpload: (category?: string) => void;
  onPreview: (asset: Asset) => void;
  generator: ReactNode;
  onManageWorkflows: () => void;
  onViewHistory?: () => void;
  speechText?: string;
  onSpeechTextChange?: (text: string) => void;
  directionText?: string;
  onDirectionTextChange?: (text: string) => void;
}

function scopedAssets({ assets, jobs, selectedId }: StudioViewProps) {
  const found = new Map<string, Asset>();
  for (const asset of assets) if (asset.character_id === selectedId) found.set(asset.id, asset);
  for (const job of jobs) {
    if (job.character_id !== selectedId) continue;
    for (const asset of job.output_assets || []) if (asset.character_id === selectedId) found.set(asset.id, asset);
  }
  return [...found.values()];
}

function outputsFor(assets: Asset[], jobs: Job[], characterId: string, module: Module) {
  const moduleJobs = jobs.filter(job => job.character_id === characterId && job.module === module);
  const jobIds = new Set(moduleJobs.map(job => job.id));
  const outputIds = new Set(moduleJobs.flatMap(job => (job.output_assets || []).map(asset => asset.id)));
  return assets.filter(asset => outputIds.has(asset.id) || (typeof asset.metadata?.job_id === 'string' && jobIds.has(asset.metadata.job_id)));
}

function importedAssets(assets: Asset[], jobs: Job[]) {
  const outputIds = new Set(jobs.flatMap(job => (job.output_assets || []).map(asset => asset.id)));
  return assets.filter(asset => !asset.metadata?.job_id && !outputIds.has(asset.id));
}

function sizeLabel(size: number) {
  return size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;
}

function IdentitySelector({ characters, selectedId, onSelectCharacter, character }: Pick<StudioViewProps, 'characters' | 'selectedId' | 'onSelectCharacter' | 'character'>) {
  return <label className="identity-selector"><span>Personagem</span><span className="identity-select-control"><Icon name="lock" size={16}/><select aria-label="Personagem vinculado ao estúdio" value={selectedId} onChange={event => onSelectCharacter(event.target.value)} disabled={characters.length === 0}>
    {!character && <option value="">{characters.length ? 'Selecionar personagem' : 'Crie um personagem no Character Lab'}</option>}
    {characters.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
  </select></span></label>;
}

function Download({ asset }: { asset: Asset }) {
  return <a className="button secondary" href={assetUrl(asset)} download={asset.filename} aria-label={`Baixar ${asset.filename}`}><Icon name="download" size={15}/><span>Baixar</span></a>;
}

function ReferenceStrip({ images, onPreview, onUpload, disabled = false }: { images: Asset[]; onPreview: (asset: Asset) => void; onUpload: () => void; disabled?: boolean }) {
  return <section className="panel module-assets reference-assets"><div className="module-section-title"><h3>Referências visuais</h3><span className="module-counter">{images.length}</span></div>
    <div className="reference-strip">{images.slice(0, 8).map(asset => <button className="reference-tile" key={asset.id} onClick={() => onPreview(asset)} title={asset.filename}><img src={assetUrl(asset)} alt={asset.filename}/><span>{asset.filename}</span></button>)}<button className="asset-upload-tile" onClick={onUpload} disabled={disabled}><Icon name="plus" size={22}/><span>Adicionar</span></button></div>
    <p className="studio-helper">Escolha a imagem que será usada na geração no campo de referência do workflow.</p>
  </section>;
}

function VideoEmpty({ comparison = false, title, description }: { comparison?: boolean; title: string; description: string }) {
  return <div className={`video-empty ${comparison ? 'comparison-empty' : ''}`}><Icon name="video" size={35}/><h3>{title}</h3><p>{description}</p></div>;
}

function WorkflowLink({ onClick }: { onClick: () => void }) {
  return <button className="module-workflow-link text-button" onClick={onClick}><Icon name="workflow" size={13}/>Gerenciar workflows</button>;
}

function VideoJobStatus({ jobs, characterId, onViewHistory }: { jobs: Job[]; characterId: string; onViewHistory?: () => void }) {
  const activeStatuses = ['queued', 'preparing', 'submitting', 'running'];
  const videoJobs = jobs.filter(job => job.character_id === characterId && job.module === 'video_studio').sort((left, right) => right.created_at.localeCompare(left.created_at));
  const job = videoJobs.find(item => activeStatuses.includes(item.status)) || videoJobs[0];
  if (!job) return null;
  const active = activeStatuses.includes(job.status);
  const failed = job.status === 'failed' || job.status === 'needs_attention';
  const fallback = job.status === 'queued' ? 'A cena aguarda sua vez na fila local.' : job.status === 'preparing' ? 'Preparando a referência e os parâmetros da cena.' : job.status === 'submitting' ? 'Enviando a cena para o ComfyUI.' : job.status === 'running' ? 'O ComfyUI está processando a cena. O progresso aparece conforme o motor envia atualizações.' : job.status === 'succeeded' ? 'Geração concluída. O vídeo fica salvo na biblioteca abaixo.' : job.status === 'cancelled' ? 'Esta tarefa foi cancelada.' : 'A geração precisa de atenção. Consulte o erro abaixo.';
  return <section className={`panel studio-job-status ${failed ? 'failed' : ''}`} aria-label="Acompanhamento da geração de vídeo">
    <div className="module-section-title"><h3><Icon name={active ? 'refresh' : failed ? 'warning' : 'video'} size={17}/>{active ? 'Gerando sua cena' : 'Última geração'}</h3>{onViewHistory && <button className="text-button" type="button" onClick={onViewHistory}>Ver histórico</button>}</div>
    <div role="status" aria-live="polite"><JobProgress job={job}/></div>
    <p>{job.result_message || fallback}</p>
    {job.error && <div className="form-error" role="alert">{friendly(job.error)}</div>}
    <small>Atualizada em {date(job.updated_at)}</small>
  </section>;
}

export function VideoStudioView(props: StudioViewProps) {
  const { character, jobs, selectedId, onUpload, onPreview, generator, onManageWorkflows } = props;
  const [previewId, setPreviewId] = useState('');
  const assets = scopedAssets(props);
  const results = outputsFor(assets, jobs, selectedId, 'video_studio').filter(asset => asset.media_type.startsWith('video/'));
  const sources = importedAssets(assets, jobs).filter(asset => asset.media_type.startsWith('video/'));
  const videos = [...results, ...sources];
  const selected = videos.find(asset => asset.id === previewId) || videos[0];
  const isOutput = !!selected && results.some(asset => asset.id === selected.id);
  return <section className="studio-page video-page"><div className="module-layout video-layout comfy-studio-layout">
    <aside className="studio-controls"><section className="panel studio-composer"><div className="composer-heading"><h2>Nova cena</h2><span><Icon name="video" size={17}/>Vídeo</span></div><div className="studio-input-fields"><IdentitySelector {...props}/><label className="form-field">Direção da cena<textarea value={props.directionText || ''} onChange={event => props.onDirectionTextChange?.(event.target.value)} rows={5} disabled={!character} placeholder="Descreva a ação, o enquadramento e o ambiente…"/><small>A direção acompanha a identidade no prompt do workflow.</small></label></div><div className="module-parameters">{generator}</div><WorkflowLink onClick={onManageWorkflows}/></section></aside>
    <div className="module-main"><VideoJobStatus jobs={jobs} characterId={selectedId} onViewHistory={props.onViewHistory}/><section className="panel video-preview"><div className="module-heading-inline"><span>Resultado</span><Badge>{selected ? (isOutput ? 'Vídeo gerado' : 'Vídeo importado') : 'Vídeo'}</Badge></div><div className="video-stage">{selected ? <video key={selected.id} src={assetUrl(selected)} controls preload="metadata" aria-label={`Prévia de ${selected.filename}`}/> : <VideoEmpty title="Sua primeira cena aparece aqui" description="Defina a cena e as referências. Depois, gere seu vídeo."/>}</div><div className="media-toolbar"><div className="preview-file-meta"><Icon name="video" size={16}/><span>{selected?.filename || 'Nenhum vídeo selecionado'}<small>{selected ? `${sizeLabel(selected.size_bytes)} · ${date(selected.created_at)}` : 'O resultado fica salvo na biblioteca do personagem.'}</small></span></div>{selected && <Download asset={selected}/>}</div></section>
      <section className="panel module-assets video-outputs"><div className="module-section-title"><h3>Cenas & arquivos <span className="module-counter">{videos.length}</span></h3><Button variant="ghost" icon="upload" onClick={() => onUpload('videos')} disabled={!character}>Importar</Button></div>{videos.length ? <div className="frame-filmstrip">{videos.map((asset, index) => <article className={`frame-cell ${selected?.id === asset.id ? 'selected' : ''}`} key={asset.id}><button className="frame-select" aria-pressed={selected?.id === asset.id} onClick={() => setPreviewId(asset.id)}><div className="frame-thumbnail"><video src={assetUrl(asset)} preload="metadata" muted aria-hidden="true"/><span className="frame-number">{String(index + 1).padStart(2, '0')}</span><Icon name="play" size={23}/></div><strong>{asset.filename}</strong><small>{results.some(item => item.id === asset.id) ? 'Produção gerada' : 'Vídeo importado'} · {sizeLabel(asset.size_bytes)}</small></button><div className="module-asset-actions"><button className="text-button" onClick={() => onPreview(asset)}>Ampliar</button><a href={assetUrl(asset)} download={asset.filename} aria-label={`Baixar ${asset.filename}`}><Icon name="download" size={15}/></a></div></article>)}</div> : <div className="module-empty"><Icon name="video" size={22}/><p>Seus vídeos gerados e importados ficam aqui.</p></div>}</section>
    </div>
  </div></section>;
}

function recordedSpeechText(asset: Asset | undefined, jobs: Job[]) {
  if (!asset) return '';
  const metadataText = [asset.metadata?.transcript, asset.metadata?.text].find(value => typeof value === 'string');
  if (typeof metadataText === 'string') return metadataText;
  const job = jobs.find(item => item.id === asset.metadata?.job_id || item.output_assets?.some(output => output.id === asset.id));
  const text = Object.entries(job?.parameters || {}).find(([key, value]) => /text|script|narration|transcript|speech|texto|fala/i.test(key) && typeof value === 'string');
  return text ? String(text[1]) : '';
}

export function VoiceStudioView(props: StudioViewProps) {
  const { character, jobs, selectedId, onUpload, onPreview, generator, onManageWorkflows } = props;
  const [trackId, setTrackId] = useState('');
  const assets = scopedAssets(props);
  const results = outputsFor(assets, jobs, selectedId, 'voice').filter(asset => asset.media_type.startsWith('audio/'));
  const references = importedAssets(assets, jobs).filter(asset => asset.media_type.startsWith('audio/'));
  const tracks = [...results, ...references];
  const selected = tracks.find(asset => asset.id === trackId) || tracks[0];
  const text = recordedSpeechText(selected, jobs);
  const waveform = Array.from({ length: 56 }, (_, index) => 12 + Math.abs(Math.sin(index * 0.79) * Math.cos(index * 0.23)) * 70);
  return <section className="studio-page voice-page"><div className="module-layout voice-layout comfy-studio-layout">
    <aside className="studio-controls"><section className="panel studio-composer"><div className="composer-heading"><h2>Nova fala</h2><span><Icon name="audio" size={17}/>Voz</span></div><div className="studio-input-fields"><IdentitySelector {...props}/><label className="form-field">Texto da narração<textarea className="voice-script-input" value={props.speechText || ''} onChange={event => props.onSpeechTextChange?.(event.target.value)} rows={6} disabled={!character} placeholder="Escreva o que seu personagem vai falar…"/><small>{(props.speechText || '').length} caracteres · texto enviado ao workflow de voz.</small></label></div><div className="module-parameters voice-parameters">{generator}</div><WorkflowLink onClick={onManageWorkflows}/></section><section className="panel voice-reference-upload"><div className="module-section-title"><h3>Referências de voz</h3><Icon name="audio" size={17}/></div><button className="studio-upload-area" onClick={() => onUpload('audio')} disabled={!character}><Icon name="upload" size={25}/><strong>Adicionar áudio</strong><span>Organize as referências deste personagem</span></button></section></aside>
    <div className="module-main"><section className="panel voice-console"><div className="module-heading-inline"><span>Resultado de voz</span><Badge>{selected ? 'Áudio disponível' : 'Áudio'}</Badge></div><div className={`voice-stage ${selected ? 'has-audio' : ''}`}><div className="voice-waveform" aria-hidden="true">{waveform.map((height, index) => <i className="voice-wave-bar" key={index} style={{ height: `${height}%` }}/>)}</div>{selected ? <div className="voice-file-player"><strong>{selected.filename}</strong><audio key={selected.id} src={assetUrl(selected)} controls preload="metadata" aria-label={`Ouvir ${selected.filename}`}/><small>Visual decorativo · ouça o arquivo nos controles acima.</small></div> : <div className="voice-empty"><h3>Sua próxima voz começa aqui</h3><p>Escreva a narração, ajuste a geração e ouça o resultado.</p></div>}</div><div className="media-toolbar"><span className="media-stat"><Icon name="audio" size={15}/>{tracks.length} {tracks.length === 1 ? 'arquivo de áudio' : 'arquivos de áudio'}</span>{selected && <Download asset={selected}/>}</div>{text && <details className="voice-recorded-text"><summary>Texto do áudio selecionado</summary><p className="voice-transcript">{text}</p></details>}</section>
      <section className="panel voice-library"><div className="module-section-title"><h3>Vozes & gravações</h3><span className="module-counter">{tracks.length}</span></div>{tracks.length ? tracks.map((asset, index) => <article key={asset.id} className={`voice-track ${selected?.id === asset.id ? 'selected' : ''}`}><button className="voice-track-select" aria-label={`Selecionar áudio ${asset.filename}`} aria-pressed={selected?.id === asset.id} onClick={() => setTrackId(asset.id)}><span className="track-index">{String(index + 1).padStart(2, '0')}</span><span className="voice-track-play"><Icon name="audio" size={19}/></span><span className="voice-track-info"><strong>{asset.filename}</strong><small>{results.some(item => item.id === asset.id) ? 'Fala gerada' : 'Referência importada'} · {sizeLabel(asset.size_bytes)} · {date(asset.created_at)}</small></span></button><div className="voice-track-actions"><button className="icon-button" aria-label={`Abrir player de ${asset.filename}`} onClick={() => onPreview(asset)}><Icon name="play" size={16}/></button><a className="icon-button" href={assetUrl(asset)} download={asset.filename} aria-label={`Baixar ${asset.filename}`}><Icon name="download" size={16}/></a></div></article>) : <div className="module-empty"><Icon name="audio" size={24}/><p>Falas geradas e referências importadas aparecerão aqui.</p></div>}</section>
    </div>
  </div></section>;
}

export function MotionSwapView(props: StudioViewProps) {
  const { character, jobs, selectedId, onUpload, onPreview, generator, onManageWorkflows } = props;
  const [sourceId, setSourceId] = useState('');
  const [resultId, setResultId] = useState('');
  const assets = scopedAssets(props);
  const sources = importedAssets(assets, jobs).filter(asset => asset.media_type.startsWith('video/'));
  const results = outputsFor(assets, jobs, selectedId, 'motion_swap').filter(asset => asset.media_type.startsWith('video/'));
  const source = sources.find(asset => asset.id === sourceId) || sources[0];
  const result = results.find(asset => asset.id === resultId) || results[0];
  const images = assets.filter(asset => asset.media_type.startsWith('image/'));
  return <section className="studio-page motion-page"><div className="module-layout motion-layout comfy-studio-layout">
    <aside className="studio-controls"><section className="panel studio-composer"><div className="composer-heading"><h2>Transferir movimento</h2><Icon name="motion" size={19}/></div><div className="studio-input-fields"><IdentitySelector {...props}/><button className="studio-upload-area" onClick={() => onUpload('videos')} disabled={!character}><Icon name="upload" size={27}/><strong>Adicionar vídeo de origem</strong><span>A performance que você deseja transferir</span></button></div><div className="module-parameters motion-parameters">{generator}</div><WorkflowLink onClick={onManageWorkflows}/></section><ReferenceStrip images={images} onPreview={onPreview} onUpload={() => onUpload('identity')} disabled={!character}/></aside>
    <div className="module-main"><section className="panel motion-comparison"><div className="module-heading-inline"><span>Origem & resultado</span><Icon name="motion" size={18}/></div><div className="comparison-grid"><section className="comparison-panel source-panel"><div className="comparison-label"><span>Vídeo original</span><Badge>{source ? 'Importado' : 'Sem origem'}</Badge></div><div className="comparison-stage">{source ? <video key={source.id} src={assetUrl(source)} controls preload="metadata" aria-label={`Movimento original: ${source.filename}`}/> : <VideoEmpty comparison title="Sua performance de origem" description="Importe o vídeo com o movimento que deseja transferir."/>}</div><div className="comparison-footer"><label>Prévia da origem<select aria-label="Selecionar vídeo de origem para revisão" value={source?.id || ''} onChange={event => setSourceId(event.target.value)} disabled={!sources.length}><option value="">Selecionar performance</option>{sources.map(asset => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select></label>{source && <button className="icon-button" onClick={() => onPreview(source)} aria-label="Ampliar vídeo de origem"><Icon name="video" size={18}/></button>}</div></section><section className="comparison-panel result-panel"><div className="comparison-label"><span>Identidade aplicada</span><Badge tone={result ? 'good' : 'neutral'}>{result ? 'Gerado' : 'Sem resultado'}</Badge></div><div className="comparison-stage">{result ? <video key={result.id} src={assetUrl(result)} controls preload="metadata" aria-label={`Resultado Motion Swap: ${result.filename}`}/> : <VideoEmpty comparison title="Sua identidade em movimento" description="O resultado da transferência aparece aqui."/>}</div><div className="comparison-footer"><label>Resultado<select aria-label="Selecionar resultado Motion Swap" value={result?.id || ''} onChange={event => setResultId(event.target.value)} disabled={!results.length}><option value="">Nenhum resultado selecionado</option>{results.map(asset => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select></label>{result && <a className="icon-button" href={assetUrl(result)} download={result.filename} aria-label="Baixar resultado Motion Swap"><Icon name="download" size={18}/></a>}</div></section></div><p className="studio-helper">Os seletores do comparador servem para revisão. Defina as entradas do workflow no painel à esquerda.</p></section>
      {results.length > 0 && <section className="panel module-assets motion-outputs"><div className="module-section-title"><h3>Transferências concluídas</h3><span className="module-counter">{results.length}</span></div><div className="module-output-list">{results.map(asset => <article key={asset.id}><button className={`motion-output-select ${result?.id === asset.id ? 'selected' : ''}`} onClick={() => setResultId(asset.id)} aria-pressed={result?.id === asset.id}><Icon name="video" size={19}/><span><strong>{asset.filename}</strong><small>{date(asset.created_at)} · {sizeLabel(asset.size_bytes)}</small></span></button><a className="icon-button" href={assetUrl(asset)} download={asset.filename} aria-label={`Baixar ${asset.filename}`}><Icon name="download" size={16}/></a></article>)}</div></section>}
    </div>
  </div></section>;
}
