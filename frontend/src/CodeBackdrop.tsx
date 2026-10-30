const fragments = [
  'const identity = library.resolve(character.id);',
  'identity.references.map(asset => asset.sha256);',
  'await pipeline.validate(workflow.inputs);',
  'export { character, voice, video, motion };',
  'function composeIdentity(attributes) {',
  '  return Object.freeze({ ...attributes });',
  '}',
  'const frame = sequence.at(index);',
  'reference.bind(identity.signature);',
  'for (const asset of library) { index(asset); }',
  '01001100 01001111 01000011 01001011',
  'character.lock({ consistent: true });',
];

/** Decorative code, intentionally separate from real engine/job status. */
export default function CodeBackdrop() {
  return <div className="code-backdrop" aria-hidden="true"><div className="cyber-grid"/>{Array.from({ length: 12 }, (_, index) => <div className="code-stream" key={index} style={{ left: String(2 + index * 9) + '%', animationDelay: String(-index * 3) + 's', animationDuration: String(32 + index % 4 * 8) + 's' }}><pre>{[...fragments.slice(index % 4), ...fragments, ...fragments.slice(0, index % 4)].join('\n\n')}</pre></div>)}<div className="scanline"/></div>;
}
