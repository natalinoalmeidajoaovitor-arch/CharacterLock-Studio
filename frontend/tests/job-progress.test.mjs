import assert from 'node:assert/strict';
import test from 'node:test';
import { jobProgressPercent } from '../src/JobProgress.ts';

test('real SDK sampling and legacy counters produce a sampling percentage', () => {
  assert.equal(jobProgressPercent({ value: 3, max: 8 }), 38);
  assert.equal(jobProgressPercent({ step: 3, steps: 8 }), 38);
  assert.equal(jobProgressPercent({ value: 1, step: 3, steps: 8, nodes_done: 4, nodes_total: 4 }), 38);
  assert.equal(jobProgressPercent({ step: 0, steps: 8 }), 0);
  assert.equal(jobProgressPercent({ step: 8, steps: 8 }), 100);
});

test('empty, reconnecting and placeholder events never imply progress', () => {
  for (const progress of [null, {}, { phase: 'reconnecting' }, { value: 0, max: 0 }, { value: 8 }, { value: NaN }, { value: Infinity }, { step: 0, steps: 0 }]) {
    assert.equal(jobProgressPercent(progress), null);
  }
});

test('SDK node discovery never implies that loading or the whole video is complete', () => {
  for (const value of [0, 0.375, 1]) {
    assert.equal(jobProgressPercent({ value, nodes_done: 4, nodes_total: 4, current_node: '13', message: 'Carregando encoder' }), null);
  }
});

test('sampling percentage stays within the progress bar bounds', () => {
  assert.equal(jobProgressPercent({ value: 12, max: 8 }), 100);
  assert.equal(jobProgressPercent({ value: -1, max: 8 }), 0);
});
