import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from './api';
import type { Character, CharacterCatalog, CharacterField } from './api';
import { Button, Consent, Icon, Modal } from './components';

const steps=[{id:'identity',label:'Identidade',icon:'shield' as const,description:'Defina quem seu personagem é.'},{id:'appearance',label:'Aparência',icon:'image' as const,description:'Escolha os detalhes que tornam sua identidade única.'},{id:'style',label:'Estilo & personalidade',icon:'spark' as const,description:'Dê personalidade ao seu universo criativo.'}];
const identityKeys=['artistic_name','age','country','presentation'];
const styleKeys=['makeup','wardrobe','accessories','personality','content_niche','content_language','photo_style'];
function fieldStep(field:CharacterField):number{return identityKeys.includes(field.key)?0:styleKeys.includes(field.key)?2:1;}

export default function CharacterConfigurator({character,onClose,onSave}:{character?:Character;onClose:()=>void;onSave:(character:Character)=>Promise<void>}){
  const [catalog,setCatalog]=useState<CharacterCatalog|null>(null);
  const [attributes,setAttributes]=useState<Record<string,string>>({});
  const [step,setStep]=useState(0);
  const [consent,setConsent]=useState(character?.consent_confirmed ?? true);
  const [customName,setCustomName]=useState('');
  const [changed,setChanged]=useState(false);
  const [nameChanged,setNameChanged]=useState(false);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const load=async()=>{setLoading(true);setError('');try{const result=await api<CharacterCatalog>('/character-options');setCatalog(result);setAttributes({...result.defaults,...(character?.attributes||{})});}catch(e){setError((e as Error).message);}finally{setLoading(false);}};
  useEffect(()=>{void load();},[]);
  const update=(key:string,value:string)=>{setAttributes(current=>({...current,[key]:value}));setChanged(true);if(key==='artistic_name')setNameChanged(true);};
  const label=(key:string)=>{const field=catalog?.fields.find(f=>f.key===key);return field?.options.find(o=>o.value===attributes[key])?.label||attributes[key]||'A definir';};
  const displayName=customName.trim()||(!nameChanged&&character?.name?character.name:label('artistic_name'));
  const fields=catalog?.fields.filter(f=>fieldStep(f)===step)||[];
  const legacy=!!character&&!Object.keys(character.attributes||{}).length;
  const submit=async(e:FormEvent)=>{e.preventDefault();if(step<2){setStep(current=>current+1);return;}setBusy(true);setError('');try{const body:Record<string,unknown>={};if(!character){body.attributes=attributes;body.consent_confirmed=consent;if(customName.trim())body.name=customName.trim();}else{if(changed){body.attributes=attributes;if(!nameChanged)body.name=character.name;}if(customName.trim())body.name=customName.trim();}const result=await api<Character>(character?`/characters/${character.id}`:'/characters',{method:character?'PATCH':'POST',body:JSON.stringify(body)});await onSave(result);}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  return <Modal className="character-configurator" title={character?'Personalizar identidade':'Crie seu próximo personagem'} subtitle="Escolha as características. O estúdio organiza sua identidade automaticamente." onClose={onClose}>
    {loading?<div className="config-loading"><Icon name="settings" size={30}/><strong>Preparando suas opções…</strong><span>Carregando o catálogo de características do estúdio.</span></div>:!catalog?<div className="config-loading"><Icon name="warning" size={30}/><strong>Não foi possível carregar as opções</strong><p className="form-error">{error}</p><Button icon="refresh" variant="secondary" onClick={()=>void load()}>Tentar novamente</Button></div>:<form className="config-form" onSubmit={submit}>
      <div className="config-body">
        <aside className="config-summary">
          <span className="config-caption">SUA IDENTIDADE</span>
          <div className="config-identity-mark"><span className="config-orbit"/><span className="config-orbit second"/><div><Icon name="lock" size={30}/></div><i/><b/></div>
          <h3>{displayName}</h3>
          <div className="config-summary-location"><span>{label('age')}</span><i/><span>{label('country')}</span></div>
          <span className="config-summary-presentation">{label('presentation')}</span>
          <div className="config-summary-divider"/>
          <div className="config-summary-row"><Icon name="image" size={15}/><div><span>Aparência</span><strong>{label('skin_tone')} · {label('eye_color')}</strong><p>{label('hair_color')} · {label('hair_texture')}</p></div></div>
          <div className="config-summary-row"><Icon name="spark" size={15}/><div><span>Estilo</span><strong>{label('wardrobe')}</strong><p>{label('personality')}</p></div></div>
          <div className="config-summary-row"><Icon name="video" size={15}/><div><span>Universo criativo</span><strong>{label('content_niche')}</strong><p>{label('photo_style')}</p></div></div>
          <div className="config-local-note"><Icon name="shield" size={15}/><p>Um perfil compartilhado entre todos os módulos do estúdio.</p></div>
        </aside>
        <section className="config-main">
          <nav className="config-steps" aria-label="Etapas de criação">{steps.map((item,index)=><button type="button" key={item.id} aria-current={step===index?'step':undefined} className={`${step===index?'active':''} ${step>index?'complete':''}`} onClick={()=>setStep(index)}><span>{step>index?<Icon name="check" size={12}/>:index+1}</span><strong>{item.label}</strong></button>)}</nav>
          <div className="config-fields-scroll"><div className="config-step-heading"><span>0{step+1} / 03</span><h3>{steps[step].description}</h3><p>{step===0?'Tudo começa com as escolhas básicas. Você pode ajustar cada detalhe depois.':step===1?'Combine características para definir uma referência visual consistente.':'Selecione o visual, o tom e o contexto das suas próximas produções.'}</p></div>
          {legacy&&<div className="config-legacy-note"><Icon name="history" size={15}/><p>Este perfil possui um prompt anterior. As escolhas abaixo substituem essa descrição apenas se você alterar uma opção e salvar.</p></div>}
          <div className="config-field-grid">{fields.map(field=><SelectionField key={field.key} field={field} value={attributes[field.key]||field.default} onChange={value=>update(field.key,value)}/>)}</div>
          {step===0&&<details className="config-advanced"><summary>Prefere um nome personalizado?</summary><label className="form-field">Nome personalizado <span className="optional">opcional</span><input value={customName} maxLength={120} onChange={e=>setCustomName(e.target.value)} placeholder="Use apenas se quiser um nome fora da lista"/></label></details>}
          {step===2&&<div className="config-consent"><Consent checked={consent} onChange={setConsent}/></div>}
          {error&&<div className="form-error" role="alert">{error}</div>}
          </div>
        </section>
      </div>
      <footer className="config-footer"><span><Icon name="lock" size={13}/>Escolhas salvas na sua biblioteca local</span><div><Button type="button" variant="secondary" onClick={()=>step>0?setStep(current=>current-1):onClose()}>{step>0?'Voltar':'Cancelar'}</Button>{step<2?<Button key="next" icon="arrow" type="button" onClick={()=>setStep(current=>current+1)}>Continuar</Button>:<Button key="save" icon="check" type="submit" disabled={busy||!consent}>{busy?'Salvando…':character?'Salvar identidade':'Criar personagem'}</Button>}</div></footer>
    </form>}
  </Modal>;
}

function SelectionField({field,value,onChange}:{field:CharacterField;value:string;onChange:(value:string)=>void}){
  if(field.key==='presentation'&&field.options.length<=6)return <fieldset className="config-presentation"><legend>{field.label}</legend><div>{field.options.map(option=><button key={option.value} type="button" className={value===option.value?'selected':''} aria-pressed={value===option.value} onClick={()=>onChange(option.value)}><span className="presentation-symbol"><Icon name="shield" size={17}/></span><span>{option.label}</span>{value===option.value&&<Icon name="check" size={12}/>}</button>)}</div>{field.description&&<small>{field.description}</small>}</fieldset>;
  return <label className={`form-field config-select ${field.key==='artistic_name'?'name-select':''}`}><span>{field.label}{field.key==='artistic_name'&&<em>uma sugestão do estúdio</em>}</span><select value={value} onChange={e=>onChange(e.target.value)}>{field.options.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select>{field.description&&<small>{field.description}</small>}</label>;
}


