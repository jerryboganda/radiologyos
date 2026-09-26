import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BLANK, cardType, clozeAnswer, clozeParts, knowledgeSummary, parseKnowledgeCardsForm } from './cards.ts';
import { ExamAutosave, type AutosaveTransport, type HttpReply, type ReviewExtras } from './exam-autosave.ts';
import {
  ItemClock,
  calibrationText,
  disputeFor,
  formatSeconds,
  mergeSeconds,
  parseDisputeForm,
  parseResolveForm,
  secondsChanges
} from './exam-review.ts';
import { examKey } from './shortcuts.ts';
import type { DisputeOut } from './types/results.ts';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [key, value] of entries) data.append(key, value);
  return data;
}

test('cloze fronts split into text and blanks; the answer is the first paragraph', () => {
  assert.deepEqual(clozeParts(`${BLANK} shows crazy paving; ${BLANK} is rare`), [
    { blank: true },
    { blank: false, text: ' shows crazy paving; ' },
    { blank: true },
    { blank: false, text: ' is rare' }
  ]);
  assert.deepEqual(clozeAnswer('PAP\n\nPAP shows crazy paving.\n\nEvidence: “x”'), {
    answer: 'PAP',
    rest: 'PAP shows crazy paving.\n\nEvidence: “x”'
  });
  assert.equal(cardType({ card_type: 'image' }), 'image');
  assert.equal(cardType({}), 'basic');
});

test('knowledge card form and summary', () => {
  assert.deepEqual(parseKnowledgeCardsForm(form([['kind', 'image'], ['max_cards', '10'], ['topic', 'chest']])), {
    ok: true,
    value: { kind: 'image', max_cards: 10, source_id: null, topic: 'chest' }
  });
  assert.equal(parseKnowledgeCardsForm(form([['kind', 'basic']])).ok, false);
  assert.equal(parseKnowledgeCardsForm(form([['kind', 'cloze'], ['max_cards', '51']])).ok, false);
  assert.equal(parseKnowledgeCardsForm(form([['kind', 'cloze'], ['source_id', 'x']])).ok, false);
  assert.match(knowledgeSummary('cloze', 2, 1), /Created 2 cloze cards .*1 skipped/);
  assert.match(knowledgeSummary('image', 0, 0), /No new image cards/);
});

test('exam keys: letters choose, 1–3 rate, nothing fires while typing', () => {
  assert.deepEqual(examKey({ key: 'c' }, 5, false), { kind: 'choose', option: 2 });
  assert.deepEqual(examKey({ key: '3' }, 5, false), { kind: 'confidence', level: 3 });
  assert.deepEqual(examKey({ key: '2' }, 5, true), { kind: 'confidence', level: 2 });
  assert.equal(examKey({ key: 'a' }, 5, true), null, 'written items take no option keys');
  assert.equal(examKey({ key: '4' }, 5, false), null);
  assert.equal(examKey({ key: '1', target: { tagName: 'TEXTAREA' } }, 5, true), null);
  assert.equal(examKey({ key: '1', ctrlKey: true }, 5, false), null);
});

test('the item clock counts visible time on the item on screen', () => {
  const clock = new ItemClock({ [A]: 10 });
  clock.enter(A, 0);
  clock.enter(B, 5_000);
  clock.pause(8_000);
  clock.enter(B, 20_000);
  assert.deepEqual(clock.seconds(21_500), { [A]: 15, [B]: 4 });
});

test('seconds only grow and only increases are sent', () => {
  assert.deepEqual(mergeSeconds({ [A]: 30 }, { [A]: 10, [B]: 5.7 }), { [A]: 30, [B]: 5 });
  assert.deepEqual(secondsChanges({ [A]: 30 }, { [A]: 30, [B]: 5 }), { [B]: 5 });
  assert.equal(formatSeconds(45), '45s');
  assert.equal(formatSeconds(185), '3m 05s');
  assert.equal(formatSeconds(3720), '1h 02m');
  assert.equal(formatSeconds(null), '—');
});

test('autosave sends confidence and time with the answers', async () => {
  const sent: (ReviewExtras | undefined)[] = [];
  const transport: AutosaveTransport = {
    async save(revision, answers, _text, extras): Promise<HttpReply> {
      sent.push(extras);
      return {
        status: 200,
        body: { exam_id: 'e', revision: revision + 1, deadline_at: null, answers, confidence: { [A]: 2 }, item_seconds: { [A]: 12 } }
      };
    },
    async load(): Promise<HttpReply> {
      return { status: 500, body: null };
    }
  };
  const autosave = new ExamAutosave({ answers: {}, revision: 0 }, transport);
  autosave.setConfidence(A, 2);
  autosave.setSeconds({ [A]: 12 });
  assert.equal(await autosave.flush(), true);
  assert.deepEqual(sent[0], { confidence: { [A]: 2 }, item_seconds: { [A]: 12 } });
  assert.equal(autosave.hasPending(), false);
  assert.deepEqual(autosave.snapshot().confidence, { [A]: 2 });
  autosave.setConfidence(A, null);
  autosave.setSeconds({ [A]: 11 });
  await autosave.flush();
  assert.deepEqual(sent[1], { confidence: { [A]: null }, item_seconds: {} });
});

test('calibration reads as a sentence, never a pass probability', () => {
  const base = { rated: 5, levels: [], confidently_wrong: 0, unsure_right: 0 };
  assert.match(calibrationText({ ...base, bias: 0.25 }), /Overconfident.*25 points/);
  assert.match(calibrationText({ ...base, bias: -0.2 }), /Underconfident/);
  assert.match(calibrationText({ ...base, bias: 0.05 }), /Well calibrated/);
  assert.match(calibrationText(undefined), /Rate your confidence/);
});

test('dispute forms and lookups', () => {
  assert.deepEqual(parseDisputeForm(form([['question_id', A], ['point_index', '1'], ['reason', ' named it ']])), {
    ok: true,
    value: { question_id: A, point_index: 1, reason: 'named it' }
  });
  assert.equal(parseDisputeForm(form([['question_id', A], ['point_index', '1'], ['reason', ' ']])).ok, false);
  assert.equal(parseDisputeForm(form([['question_id', 'x'], ['point_index', '1'], ['reason', 'r']])).ok, false);
  assert.deepEqual(parseResolveForm(form([['dispute_id', B], ['action', 'accept'], ['awarded', '1.5']])), {
    ok: true,
    value: { id: B, action: 'accept', awarded: 1.5, note: '' }
  });
  const rejected = parseResolveForm(form([['dispute_id', B], ['action', 'reject'], ['awarded', '2']]));
  assert.equal(rejected.ok && rejected.value.awarded, null);
  assert.equal(parseResolveForm(form([['dispute_id', B], ['action', 'accept'], ['awarded', '-1']])).ok, false);
  const d = { question_id: A, point_index: 2 } as DisputeOut;
  assert.equal(disputeFor([d], A, 2), d);
  assert.equal(disputeFor([d], A, 1), null);
});
