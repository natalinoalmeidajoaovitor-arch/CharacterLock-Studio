import { useId } from 'react';
import type { Asset } from './api';
import { assetUrl } from './api';
import { Icon } from './components';

export interface VideoReferencePickerProps {
  parameterName: string;
  label: string;
  assets: Asset[];
  characterId?: string;
  selectedId: string;
  automatic: boolean;
  loading: boolean;
  onSelect: (id: string) => void;
  onUpload: () => void;
  onPreview?: (asset: Asset) => void;
}

const supportedImageTypes = new Set(['image/png', 'image/jpeg', 'image/webp']);

export function VideoReferencePicker({
  parameterName, label, assets, characterId, selectedId, automatic, loading,
  onSelect, onUpload, onPreview,
}: VideoReferencePickerProps) {
  const headingId = useId();
  const helpId = useId();
  const images = assets.filter(asset => asset.character_id === characterId && supportedImageTypes.has(asset.media_type.toLowerCase()));
  const selected = images.find(asset => asset.id === selectedId);
  const disabled = !characterId || loading;
  const selectionLabel = automatic ? 'Rosto aprovado · seleção automática' : 'Imagem selecionada';

  return <section className="video-reference-picker" aria-labelledby={headingId} aria-describedby={helpId} aria-busy={loading} data-parameter={parameterName}>
    <div className="video-reference-picker-heading">
      <h3 id={headingId}><Icon name="image" size={16}/>{label}</h3>
      <button type="button" className="video-reference-picker-import" onClick={onUpload} disabled={disabled}>
        <Icon name="upload" size={14}/>Importar imagem
      </button>
    </div>
    <p className="video-reference-picker-help" id={helpId}>A imagem selecionada abaixo será usada para criar o vídeo.</p>

    {selected ? <div className="video-reference-picker-selected">
      {onPreview ? <button type="button" className="video-reference-picker-preview" onClick={() => onPreview(selected)} aria-label={`Ampliar referência ${selected.filename}`}>
        <img src={assetUrl(selected)} alt={`Referência selecionada: ${selected.filename}`}/>
        <span><Icon name="search" size={12}/>Ampliar</span>
      </button> : <div className="video-reference-picker-preview"><img src={assetUrl(selected)} alt={`Referência selecionada: ${selected.filename}`}/></div>}
      <div className="video-reference-picker-selected-info">
        <span className="video-reference-picker-selection-badge"><Icon name="check" size={12}/>{selectionLabel}</span>
        <strong title={selected.filename}>{selected.filename}</strong>
        <p>Para trocar, escolha outra imagem na biblioteca abaixo.</p>
        <button type="button" className="video-reference-picker-clear" onClick={() => onSelect('')} disabled={disabled}><Icon name="close" size={13}/>Remover referência</button>
      </div>
    </div> : <div className="video-reference-picker-empty">
      <Icon name={loading ? 'refresh' : 'image'} size={25}/>
      <strong>{loading ? 'Carregando suas referências…' : !characterId ? 'Selecione um personagem' : 'Escolha a imagem para seu vídeo'}</strong>
      <p>{loading ? 'As imagens da biblioteca aparecem aqui.' : !characterId ? 'As referências pertencem à biblioteca do personagem.' : images.length ? 'Clique em uma das imagens abaixo ou importe uma nova.' : 'Importe um retrato ou uma imagem de referência para começar.'}</p>
      {!loading && characterId && !images.length && <button type="button" className="video-reference-picker-import" onClick={onUpload}><Icon name="upload" size={14}/>Adicionar primeira imagem</button>}
    </div>}

    {images.length > 0 && <details className="video-reference-picker-library" open>
      <summary>Escolher outra imagem <span>{images.length}</span><Icon name="chevron" size={13}/></summary>
      <div className="video-reference-picker-grid" aria-label="Imagens disponíveis para o vídeo">
        {images.map(asset => <button type="button" key={asset.id} className={`video-reference-picker-thumbnail ${asset.id === selectedId ? 'selected' : ''}`} onClick={() => onSelect(asset.id)} aria-pressed={asset.id === selectedId} aria-label={`Usar ${asset.filename} como referência`} title={asset.filename} disabled={disabled}>
          <img src={assetUrl(asset)} alt={asset.filename} loading="lazy"/>
          {asset.id === selectedId && <span className="video-reference-picker-check" aria-hidden="true"><Icon name="check" size={12}/></span>}
          <span className="video-reference-picker-filename">{asset.filename}</span>
        </button>)}
        <button type="button" className="video-reference-picker-upload-tile" onClick={onUpload} disabled={disabled} aria-label="Importar outra imagem de referência"><Icon name="plus" size={21}/><span>Importar</span></button>
      </div>
    </details>}
    <div className="video-reference-picker-status" role="status" aria-live="polite" aria-atomic="true">
      {loading ? 'Atualizando biblioteca…' : selected ? `${selectionLabel}: ${selected.filename}` : characterId ? 'Nenhuma referência selecionada.' : 'Selecione um personagem para acessar as referências.'}
    </div>
    <small className="video-reference-picker-formats">PNG, JPEG ou WebP · imagens da biblioteca deste personagem</small>
  </section>;
}
