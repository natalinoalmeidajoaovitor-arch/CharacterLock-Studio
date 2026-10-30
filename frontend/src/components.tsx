import type { ButtonHTMLAttributes, ReactNode } from 'react';
import type { Asset, Job } from './api';
import { assetUrl, statuses } from './api';
import { jobProgressPercent } from './JobProgress';
export type IconName='lab'|'video'|'motion'|'workflow'|'history'|'plus'|'arrow'|'upload'|'image'|'audio'|'check'|'close'|'edit'|'folder'|'settings'|'refresh'|'link'|'shield'|'chevron'|'download'|'warning'|'grid'|'spark'|'play'|'lock'|'search';
const paths:Record<IconName,ReactNode>={
  lab:<><path d="M9 3h6M10 3v6L4.5 18a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M8 14h8"/></>,
  video:<><rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 9 5-3v12l-5-3"/></>,
  motion:<><path d="M4 7h14l-3-3m5 13H6l3 3M18 7l-3 3M6 17l3-3"/><circle cx="4" cy="7" r="1"/><circle cx="20" cy="17" r="1"/></>,
  workflow:<><rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="15" y="15" width="6" height="6" rx="1.5"/><path d="M9 6h7a2 2 0 0 1 2 2v7M6 9v7a2 2 0 0 0 2 2h7"/></>,
  history:<><path d="M3 11a9 9 0 1 1 2.6 7M3 4v7h7M12 7v5l3 2"/></>,
  plus:<path d="M12 5v14M5 12h14"/>, arrow:<path d="M5 12h14m-5-5 5 5-5 5"/>,
  upload:<><path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></>,
  image:<><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/></>,
  audio:<><path d="M5 9v6M9 5v14M13 3v18M17 7v10M21 10v4"/></>,
  check:<path d="m5 12 4 4L19 6"/>,close:<path d="m6 6 12 12M6 18 18 6"/>,
  edit:<><path d="m15 4 5 5M4 20l4-1L20 7a2.1 2.1 0 0 0-3-3L5 16l-1 4Z"/></>,
  folder:<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>,
  settings:<><path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/></>,
  refresh:<><path d="M20 7a9 9 0 0 0-15-2L3 7m0-5v5h5M4 17a9 9 0 0 0 15 2l2-2m0 5v-5h-5"/></>,
  link:<><path d="m10 13 4-4m-6 6-2 2a3 3 0 0 1-4-4l4-4a3 3 0 0 1 4 0m4 0 2-2a3 3 0 0 1 4 4l-4 4a3 3 0 0 1-4 0"/></>,
  shield:<><path d="m12 3 8 4v6c0 5-8 8-8 8s-8-3-8-8V7l8-4Z"/><path d="m8 12 3 3 5-6"/></>,
  chevron:<path d="m9 5 7 7-7 7"/>,download:<><path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/></>,
  warning:<><path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.1"/></>,
  grid:<><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  spark:<><path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Z"/></>,
  play:<path d="m8 4 12 8-12 8V4Z"/>,lock:<><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/></>,
  search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>
};
export function Icon({name,size=20,className=''}:{name:IconName;size?:number;className?:string}){return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>}
export function Button({children,icon,variant='primary',className='',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{icon?:IconName;variant?:'primary'|'secondary'|'ghost'|'danger'}){return <button className={`button ${variant} ${className}`} {...props}>{icon&&<Icon name={icon} size={16}/>}<span>{children}</span></button>}
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:'neutral'|'good'|'warn'|'bad'}){return <span className={`badge ${tone}`}><i/>{children}</span>}
export function Modal({title,subtitle,onClose,children,className=''}:{title:string;subtitle?:string;onClose:()=>void;children:ReactNode;className?:string}){return <div className="modal-backdrop" onClick={onClose}><section className={`modal ${className}`} role="dialog" aria-modal="true" aria-labelledby="modal-title" onClick={e=>e.stopPropagation()}><header><div><h2 id="modal-title">{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button className="icon-button" aria-label="Fechar" onClick={onClose}><Icon name="close"/></button></header>{children}</section></div>}
export function Media({asset,controls=true}:{asset:Asset;controls?:boolean}){const url=assetUrl(asset);return asset.media_type.startsWith('image/')?<img src={url} alt={asset.filename} loading="lazy"/>:asset.media_type.startsWith('video/')?<video src={url} controls={controls} preload="metadata"/>:asset.media_type.startsWith('audio/')?<div className="audio-preview"><Icon name="audio" size={42}/><audio src={url} controls preload="metadata"/></div>:<div className="file-preview"><Icon name="folder" size={38}/><span>{asset.filename}</span></div>}
export function Empty({icon='folder',title,description,action}:{icon?:IconName;title:string;description:string;action?:ReactNode}){return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={24}/></span><h3>{title}</h3><p>{description}</p>{action}</div>}
export function Consent({checked,onChange,label='Confirmo que tenho autorização para usar esta identidade e os arquivos associados.'}:{checked:boolean;onChange:(value:boolean)=>void;label?:string}){return <label className="consent"><input type="checkbox" checked={checked} onChange={e=>onChange(e.target.checked)}/><span>{label}</span></label>}
const phaseLabels:Record<string,string>={waiting_for_engine:'Aguardando fila do ComfyUI ficar livre…',pipeline_transition:'Alternando pipeline de modelos…',unloading_models:'Descarregando modelos anteriores da VRAM…',release_acknowledged:'Aguardando confirmação de liberação da GPU…',memory_ready:'VRAM pronta para o próximo modelo.',reusing_models:'Reutilizando modelos já carregados na VRAM.',queued:'Aguardando na fila do ComfyUI…',reconnecting:'Reconectando ao ComfyUI…',saving_outputs:'Importando arquivos gerados para a biblioteca…'};
export function JobProgress({job}:{job:Job}){
  if(['succeeded','failed','cancelled','needs_attention'].includes(job.status))return <div className="job-progress"><div><span>{statuses[job.status]||job.status}</span></div></div>;
  const progress=job.progress;const percent=jobProgressPercent(progress);
  const node=progress?.current_node??progress?.node??progress?.node_id;
  const message=typeof progress?.message==='string'&&progress.message?progress.message:typeof progress?.phase==='string'?phaseLabels[progress.phase]||'':'';
  const sampling=typeof progress?.step==='number'&&typeof progress?.steps==='number'&&progress.steps>0?`${progress.step}/${progress.steps}`:typeof progress?.value==='number'&&typeof progress?.max==='number'&&progress.max>0?`${progress.value}/${progress.max}`:'';
  const nodes=typeof progress?.nodes_done==='number'&&progress.nodes_done>0?`${progress.nodes_done} ${progress.nodes_done===1?'nó processado':'nós processados'}`:'';
  return <div className="job-progress"><div><span>{statuses[job.status]||job.status}</span>{percent!==null?<span>Amostragem {sampling} · {percent}%</span>:node?<span>Nó {String(node)}</span>:null}</div>{percent!==null&&<div className="progress-track" role="progressbar" aria-label="Progresso da amostragem" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><i style={{width:`${percent}%`}}/></div>}{message&&<p className="job-progress-message">{message}</p>}{nodes&&<small className="job-progress-nodes">{nodes}{node?` · nó ${String(node)}`:''}</small>}</div>;
}
