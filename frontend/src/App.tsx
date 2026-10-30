import { useCallback, useEffect, useRef, useState } from 'react';
import CharacterConfigurator from './CharacterConfigurator';
import CharacterLab from './CharacterLab';
import CodeBackdrop from './CodeBackdrop';
import { EngineBanner, EngineCard } from './EngineStatus';
import { Generator } from './GenerationPanel';
import { History, UploadForm, WorkflowManager } from './WorkspaceTools';
import { MotionSwapView, VideoStudioView, VoiceStudioView } from './StudioViews';
import type { StudioViewProps } from './StudioViews';
import { api, assetUrl, categories, labels } from './api';
import type { Asset, Character, CharacterCatalog, EngineLifecycle, Job, Module, System, Workflow } from './api';
import { Button, Icon, Media, Modal } from './components';
import type { IconName } from './components';

type Page = Module | 'workflows' | 'history';
const navigation: { id: Module; label: string; subtitle: string; icon: IconName; code: string }[] = [
  { id: 'character_lab', label: 'Character Lab', subtitle: 'Identidade e aparência', icon: 'lab', code: '01' },
  { id: 'video_studio', label: 'Video Studio', subtitle: 'Cenas e produção visual', icon: 'video', code: '02' },
  { id: 'voice', label: 'Voice Studio', subtitle: 'Voz, narração e áudio', icon: 'audio', code: '03' },
  { id: 'motion_swap', label: 'Motion Swap', subtitle: 'Personagem e performance', icon: 'motion', code: '04' },
];
const pageTitles: Record<Page, { eyebrow: string; title: string; description: string }> = {
  character_lab: { eyebrow: 'IDENTITY ENGINE', title: 'Character Lab', description: 'Crie o Character Sheet, aprove a identidade e produza seu dataset.' },
  video_studio: { eyebrow: 'CINEMATIC STUDIO', title: 'Video Studio', description: 'Escolha a referência, dirija a cena e gere seu vídeo.' },
  voice: { eyebrow: 'VOICE SYNTHESIS', title: 'Voice Studio', description: 'Crie vozes e narrações com seus textos e referências de áudio.' },
  motion_swap: { eyebrow: 'PERFORMANCE TRANSFER', title: 'Motion Swap', description: 'Use uma performance de origem para animar sua personagem.' },
  workflows: { eyebrow: 'PIPELINE CONTROL', title: 'Conecte seus workflows.', description: 'Mapeie os fluxos reais da sua instalação local.' },
  history: { eyebrow: 'EXECUTION ARCHIVE', title: 'Sua produção, registrada.', description: 'Tarefas, parâmetros e arquivos de cada execução.' },
};
const activeStatuses = ['queued', 'preparing', 'submitting', 'running'];
const pages = [...navigation.map(item => item.id), 'workflows', 'history'];
function savedValue(key: string, fallback = '') { try { return localStorage.getItem(key) || fallback; } catch { return fallback; } }
function remember(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* Storage is optional. */ } }
function initialPage(): Page { const hash = typeof window === 'undefined' ? '' : window.location.hash.slice(1); return pages.includes(hash) ? hash as Page : 'character_lab'; }

export default function App() {
  const [page, setPage] = useState<Page>(initialPage);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [selectedId, setSelectedId] = useState(() => savedValue('characterlock.selected-character'));
  const [assets, setAssets] = useState<Asset[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [catalog, setCatalog] = useState<CharacterCatalog | null>(null);
  const [system, setSystem] = useState<System | null>(null);
  const [engine, setEngine] = useState<EngineLifecycle | null>(null);
  const [engineBusy, setEngineBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [characterModal, setCharacterModal] = useState<'create' | 'edit' | null>(null);
  const [uploadCategory, setUploadCategory] = useState<string | null>(null);
  const [preview, setPreview] = useState<Asset | null>(null);
  const [codeMotion, setCodeMotion] = useState(() => savedValue('characterlock.code-motion', 'on') !== 'off');
  const [speechText, setSpeechText] = useState('');
  const [directionText, setDirectionText] = useState('');
  const selected = characters.find(character => character.id === selectedId);
  const characterAssets = assets.filter(asset => asset.character_id === selectedId);
  const selectedIdRef = useRef(selectedId); selectedIdRef.current = selectedId;
  const outputRevision = jobs.filter(job => job.character_id === selectedId).reduce((count, job) => count + (job.output_assets?.length || 0), 0);
  const activeJobs = jobs.filter(job => activeStatuses.includes(job.status));
  const message = useCallback((value: string) => setToast(value), []);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([api<Character[]>('/characters'), api<Workflow[]>('/workflows'), api<Job[]>('/jobs'), api<System>('/system')]);
    if (results[0].status === 'fulfilled') {
      const loaded = results[0].value;
      setCharacters(loaded);
      setSelectedId(id => loaded.some(character => character.id === id) ? id : loaded[0]?.id || '');
    }
    if (results[1].status === 'fulfilled') setWorkflows(results[1].value);
    if (results[2].status === 'fulfilled') setJobs(results[2].value);
    if (results[3].status === 'fulfilled') setSystem(results[3].value);
    const failure = results.find(result => result.status === 'rejected');
    setError(failure?.status === 'rejected' ? 'Não foi possível acessar o serviço local. ' + (failure.reason instanceof Error ? failure.reason.message : '') : '');
    setLoading(false);
  }, []);
  const refreshAssets = useCallback(async (id: string) => {
    if (!id) { setAssets([]); return; }
    try { const next = await api<Asset[]>('/characters/' + id + '/assets'); if (selectedIdRef.current === id) setAssets(next); }
    catch (failure) { message((failure as Error).message); }
  }, [message]);
  const effectiveEngine = engine || system?.comfy.lifecycle;
  const engineConnected = !!system?.comfy.connected;
  const retryEngine = async () => {
    setEngineBusy(true);
    try { const next = await api<EngineLifecycle>('/engine/start', { method: 'POST' }); setEngine(next); if (next.state === 'ready') void refresh(); }
    catch (failure) { message((failure as Error).message); }
    finally { setEngineBusy(false); }
  };

  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 20000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => { void api<CharacterCatalog>('/character-options').then(setCatalog).catch(() => undefined); }, []);
  useEffect(() => {
    let active = true; let previousState: string | undefined;
    const poll = async () => {
      try { const next = await api<EngineLifecycle>('/engine/status'); if (!active) return; setEngine(next); if (next.state === 'ready' && previousState && previousState !== 'ready') void refresh(); previousState = next.state; }
      catch { /* Retain observed state during restarts. */ }
    };
    void poll(); const timer = window.setInterval(() => void poll(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    setAssets([]); setPreview(null); remember('characterlock.selected-character', selectedId);
    setSpeechText(savedValue('characterlock.speech.' + selectedId, 'Olá! Eu sou uma influenciadora virtual criada no CharacterLock Studio, com voz e performance geradas localmente.'));
    setDirectionText(savedValue('characterlock.scene.' + selectedId));
    void refreshAssets(selectedId);
  }, [selectedId, refreshAssets]);
  useEffect(() => { if (outputRevision > 0) void refreshAssets(selectedId); }, [outputRevision, selectedId, refreshAssets]);
  useEffect(() => { if (!toast) return; const timer = window.setTimeout(() => setToast(''), 6500); return () => window.clearTimeout(timer); }, [toast]);
  useEffect(() => { const handler = () => setPage(initialPage()); window.addEventListener('hashchange', handler); return () => window.removeEventListener('hashchange', handler); }, []);
  useEffect(() => {
    let socket: WebSocket | undefined; let retry: number | undefined; let stopped = false;
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket((location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host + '/api/ws/jobs');
      socket.onmessage = event => {
        try { const data = JSON.parse(event.data); if (data.type === 'snapshot' && Array.isArray(data.jobs)) setJobs(data.jobs); if (data.type === 'job' && data.job) setJobs(current => [data.job, ...current.filter(job => job.id !== data.job.id)]); }
        catch { /* Ignore unrelated engine events. */ }
      };
      socket.onclose = () => { if (!stopped) retry = window.setTimeout(connect, 5000); };
      socket.onerror = () => socket?.close();
    };
    connect(); const timer = window.setInterval(() => { if (socket?.readyState !== WebSocket.OPEN) void api<Job[]>('/jobs').then(setJobs).catch(() => undefined); }, 5000);
    return () => { stopped = true; window.clearTimeout(retry); window.clearInterval(timer); socket?.close(); };
  }, []);

  const navigate = (next: Page) => { setPage(next); window.location.hash = next; window.scrollTo({ top: 0, behavior: 'auto' }); };
  const upload = (category = 'identity') => { if (selected) setUploadCategory(category); else setCharacterModal('create'); };
  const onCharacterSaved = async (character: Character) => { await refresh(); setSelectedId(character.id); setCharacterModal(null); message('Identidade salva na biblioteca.'); };
  const onUploaded = async () => { setUploadCategory(null); await Promise.all([refreshAssets(selectedId), refresh()]); message('Arquivo adicionado à biblioteca.'); };
  const changeSpeech = (value: string) => { setSpeechText(value); remember('characterlock.speech.' + selectedId, value); };
  const changeDirection = (value: string) => { setDirectionText(value); remember('characterlock.scene.' + selectedId, value); };
  const module: Module = page === 'video_studio' || page === 'voice' || page === 'motion_swap' ? page : 'character_lab';
  const generator = <Generator key={module} module={module} character={selected} assets={characterAssets} workflows={workflows} capability={system?.capabilities[module]} connected={engineConnected} engine={effectiveEngine} onManage={() => navigate('workflows')} onUpload={() => upload(module === 'voice' ? 'audio' : module === 'motion_swap' ? 'videos' : 'identity')} speechText={module === 'voice' ? speechText : undefined} directionText={module === 'video_studio' ? directionText : undefined} onPreview={setPreview} onCreated={async job => { setJobs(current => [job, ...current.filter(item => item.id !== job.id)]); await refresh(); message('Tarefa adicionada à fila local.'); }}/>;
  const studioProps: StudioViewProps = { character: selected, characters, selectedId, onSelectCharacter: setSelectedId, assets: characterAssets, jobs, onUpload: upload, onPreview: setPreview, generator, onManageWorkflows: () => navigate('workflows'), onViewHistory: () => navigate('history'), speechText, onSpeechTextChange: changeSpeech, directionText, onDirectionTextChange: changeDirection };
  const info = pageTitles[page];
  const pageName = page === 'history' ? 'Histórico' : page === 'workflows' ? 'Workflows' : labels[page];

  return <div className={'app-shell cyber-shell module-' + page + (codeMotion ? '' : ' code-paused')}>
    <CodeBackdrop/>
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate('character_lab')} aria-label="CharacterLock Studio início"><span className="brand-symbol"><Icon name="lock" size={22}/></span><span>character<span className="brand-light">lock</span><small>STUDIO / LOCAL ENGINE</small></span></button>
      <div className="workspace-tag"><span className="workspace-icon">CL</span><div>Creative workspace<small>Personagens · produção · performance</small></div></div>
      <span className="nav-caption">ESTÚDIOS</span>
      <nav aria-label="Estúdios de produção">{navigation.map(item => <button key={item.id} className={'nav-item ' + (page === item.id ? 'selected ' : '') + (item.id === 'voice' ? 'voice-emphasis' : '')} aria-current={page === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><Icon name={item.icon} size={21}/><span>{item.label}<small>{item.subtitle}</small></span><span className="nav-code">{item.code}</span></button>)}</nav>
      <span className="nav-caption workspace-caption">CONTROLE</span>
      <nav aria-label="Biblioteca e execuções"><button className={'nav-item compact ' + (page === 'workflows' ? 'selected' : '')} onClick={() => navigate('workflows')}><Icon name="workflow"/><span>Workflows</span><span className="nav-count">{workflows.length}</span></button><button className={'nav-item compact ' + (page === 'history' ? 'selected' : '')} onClick={() => navigate('history')}><Icon name="history"/><span>Histórico</span>{activeJobs.length > 0 && <span className="nav-count">{activeJobs.length}</span>}</button></nav>
      <div className="sidebar-bottom"><EngineCard lifecycle={effectiveEngine} connected={engineConnected} url={system?.comfy.url} memory={system?.memory} busy={engineBusy} onRetry={() => void retryEngine()} onRefresh={() => void refresh()}/><div className="sidebar-foot"><Icon name="shield" size={16}/><span>LOCAL FIRST / OPEN SOURCE</span></div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><Icon name="chevron" size={13}/><strong>{pageName}</strong></div><div className="topbar-right"><button className="code-toggle" aria-pressed={codeMotion} onClick={() => { setCodeMotion(!codeMotion); remember('characterlock.code-motion', codeMotion ? 'off' : 'on'); }} title="Ativar ou pausar códigos animados"><span aria-hidden="true">&lt;/&gt;</span> Código {codeMotion ? 'ON' : 'OFF'}</button><button className="queue-button" onClick={() => navigate('history')}><Icon name="history" size={17}/><span>{activeJobs.length} tarefas ativas</span></button><span className="avatar">CL</span></div></header>
      <main>
        {error && <div className="error-banner" role="alert"><Icon name="warning" size={18}/><span>{error}</span><button onClick={() => void refresh()}>Tentar novamente</button></div>}
        <EngineBanner lifecycle={effectiveEngine} connected={engineConnected} busy={engineBusy} onRetry={() => void retryEngine()}/>
        <section className="page-heading"><div><span className="eyebrow"><i/>{info.eyebrow}</span><h1>{info.title}</h1><p>{info.description}</p></div><div className="page-actions">{page === 'character_lab' ? <Button icon="plus" onClick={() => setCharacterModal('create')}>Novo personagem</Button> : page === 'voice' ? <Button variant="secondary" icon="upload" onClick={() => upload('audio')}>Importar áudio</Button> : page === 'video_studio' || page === 'motion_swap' ? <Button variant="secondary" icon="upload" onClick={() => upload('videos')}>Importar vídeo</Button> : <Button variant="secondary" icon="refresh" onClick={() => void refresh()}>Atualizar</Button>}</div></section>

        {page === 'character_lab' && <CharacterLab
          characters={characters} character={selected} selectedId={selectedId} onSelectCharacter={setSelectedId}
          assets={characterAssets} jobs={jobs} workflows={workflows} connected={engineConnected} catalog={catalog} loading={loading}
          onCreate={() => setCharacterModal('create')} onEdit={() => setCharacterModal('edit')} onUpload={upload} onPreview={setPreview}
          onManageWorkflows={() => navigate('workflows')} onRefresh={async () => { await Promise.all([refresh(), refreshAssets(selectedId)]); }}
        />}
        {page === 'video_studio' && <VideoStudioView {...studioProps}/>}
        {page === 'voice' && <VoiceStudioView {...studioProps}/>}
        {page === 'motion_swap' && <MotionSwapView {...studioProps}/>}
        {page === 'workflows' && <WorkflowManager workflows={workflows} refresh={refresh} message={message} connected={engineConnected} engine={effectiveEngine}/>}
        {page === 'history' && <History jobs={jobs} characters={characters} workflows={workflows} refresh={refresh} message={message} onPreview={setPreview}/>}
        <footer className="main-footer"><span>CHARACTERLOCK / STUDIO</span><span><i/>{engineConnected ? 'ENGINE CONNECTED' : 'ENGINE CONNECTING'} · BIBLIOTECA LOCAL</span></footer>
      </main>
    </div>

    {toast && <div className="toast" role="status"><Icon name="check" size={18}/><span>{toast}</span><button className="icon-button" aria-label="Fechar mensagem" onClick={() => setToast('')}><Icon name="close" size={16}/></button></div>}
    {characterModal && <CharacterConfigurator character={characterModal === 'edit' ? selected : undefined} onClose={() => setCharacterModal(null)} onSave={onCharacterSaved}/>}
    {uploadCategory && selected && <UploadForm character={selected} initialCategory={uploadCategory} onClose={() => setUploadCategory(null)} onSave={onUploaded}/>}
    {preview && <Modal title={preview.filename} subtitle={categories[preview.category] || preview.category} onClose={() => setPreview(null)}><div className="modal-media"><Media asset={preview}/></div><div className="modal-actions"><a className="button primary" href={assetUrl(preview)} download={preview.filename}><Icon name="download" size={17}/>Baixar arquivo</a><Button variant="secondary" onClick={() => setPreview(null)}>Fechar preview</Button></div></Modal>}
  </div>;
}
