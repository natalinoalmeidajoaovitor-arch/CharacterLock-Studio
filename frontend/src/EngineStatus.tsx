import type { EngineLifecycle, MemoryStatus } from './api';
import { Button, Icon } from './components';

export function engineLabel(lifecycle:EngineLifecycle|null|undefined,connected:boolean):string {
  if(connected)return lifecycle?.sdk?'Conectado via Comfy SDK':'Conectado ao motor local';
  if(!lifecycle)return 'Verificando motor local…';
  if(lifecycle.state==='failed')return lifecycle.sdk?.state==='failed'?'Falha na conexão do SDK':'Falha ao iniciar ComfyUI';
  if(lifecycle.state==='disabled')return 'Inicialização automática desativada';
  if(lifecycle.state==='ready')return 'Confirmando conexão com o motor…';
  return lifecycle.comfyui?.state==='ready'?'Preparando conexão do SDK…':'Iniciando ComfyUI…';
}
export function engineStarting(lifecycle?:EngineLifecycle|null):boolean{return !!lifecycle&&['detecting','starting','waiting'].includes(lifecycle.state);}
export function memorySummary(memory?:MemoryStatus|null):string{
  if(!memory?.enabled)return 'Executando em segundo plano';
  if(memory.phase==='unloading_models'||memory.phase==='release_acknowledged')return 'Liberando VRAM entre modelos…';
  if(memory.phase==='running'||memory.active_job_id)return 'VRAM monitorada · tarefa ativa';
  if(memory.current_pipeline?.fingerprint)return 'VRAM gerenciada · modelo em cache';
  return 'VRAM gerenciada · transição segura';
}

export function EngineCard({lifecycle,connected,url,memory,busy,onRetry,onRefresh}:{lifecycle?:EngineLifecycle|null;connected:boolean;url?:string;memory?:MemoryStatus|null;busy:boolean;onRetry:()=>void;onRefresh:()=>void}){
  const starting=engineStarting(lifecycle);
  return <div className={`engine-card ${starting?'engine-starting':''} ${lifecycle?.state==='failed'?'engine-failed':''}`}>
    <div><span className={`status-dot ${connected?'online':starting?'starting':''}`}/><strong>ComfyUI local</strong><button className="icon-button" title="Atualizar conexão" aria-label="Atualizar conexão" onClick={onRefresh}><Icon name="refresh" size={14}/></button></div>
    <p>{engineLabel(lifecycle,connected)}</p>
    {!connected&&lifecycle?.message&&<p className="engine-detail">{lifecycle.message}</p>}
    {connected?<span>{memorySummary(memory)}</span>:starting?<span>Inicialização automática · janela oculta</span>:<span>{url||'Motor local'}</span>}
    {!connected&&lifecycle?.can_retry&&<button className="engine-retry" disabled={busy} onClick={onRetry}><Icon name="refresh" size={13}/>{busy?'Tentando novamente…':'Repetir inicialização'}</button>}
  </div>;
}
export function EngineBanner({lifecycle,connected,busy,onRetry}:{lifecycle?:EngineLifecycle|null;connected:boolean;busy:boolean;onRetry:()=>void}){
  if(!lifecycle||connected)return null;
  const failed=lifecycle.state==='failed';const starting=engineStarting(lifecycle);
  return <div className={`engine-banner ${failed?'failed':''}`} role={failed?'alert':'status'}>
    <span className={`engine-banner-symbol ${starting?'starting':''}`}><Icon name={failed?'warning':starting?'refresh':'settings'} size={18}/></span>
    <div><strong>{starting?'Preparando motor local em segundo plano':engineLabel(lifecycle,false)}</strong><p>{lifecycle.message||'A conexão com o motor local está sendo verificada.'}</p>{starting&&<span>Você pode organizar seus personagens enquanto o motor inicia.</span>}</div>
    {lifecycle.can_retry&&<Button variant="secondary" icon="refresh" disabled={busy} onClick={onRetry}>{busy?'Tentando novamente…':'Repetir inicialização'}</Button>}
  </div>;
}
