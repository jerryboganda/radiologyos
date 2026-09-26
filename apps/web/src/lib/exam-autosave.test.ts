import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ExamAutosave, type AutosaveTransport, type HttpReply } from './exam-autosave.ts';
import type { Answers } from './types/assessment.ts';

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';

/** A fake API holding the authoritative exam with compare-and-set semantics. */
function fakeServer(initial: { answers: Answers; revision: number; status?: string }) {
  const exam = { ...initial, status: initial.status ?? 'active' };
  const calls: { revision: number; answers: Record<string, number | null> }[] = [];
  const transport: AutosaveTransport = {
    async save(revision, answers): Promise<HttpReply> {
      calls.push({ revision, answers });
      if (exam.status !== 'active') return { status: 409, body: { detail: 'exam_time_expired' } };
      if (revision !== exam.revision) return { status: 409, body: { detail: 'stale_revision' } };
      for (const [id, option] of Object.entries(answers)) {
        if (option === null) delete exam.answers[id];
        else exam.answers[id] = option;
      }
      exam.revision += 1;
      return { status: 200, body: { exam_id: 'e', revision: exam.revision, deadline_at: null, answers: { ...exam.answers } } };
    },
    async load(): Promise<HttpReply> {
      return { status: 200, body: { status: exam.status, revision: exam.revision, answers: { ...exam.answers } } };
    }
  };
  return { exam, calls, transport };
}

test('saves pending changes with the current revision and advances it', async () => {
  const server = fakeServer({ answers: {}, revision: 0 });
  const autosave = new ExamAutosave({ answers: {}, revision: 0 }, server.transport);
  autosave.set(A, 2);
  assert.equal(await autosave.flush(), true);
  assert.deepEqual(server.calls, [{ revision: 0, answers: { [A]: 2 } }]);
  assert.equal(autosave.snapshot().revision, 1);
  assert.equal(autosave.snapshot().state, 'saved');
  assert.equal(await autosave.flush(), true);
  assert.equal(server.calls.length, 1, 'nothing pending: no request');
});

test('409 stale_revision reloads the exam and retries with the rebased answers', async () => {
  const server = fakeServer({ answers: { [A]: 0 }, revision: 3 });
  // This tab loaded revision 2; another tab has since answered B and saved (revision 3).
  server.exam.answers[B] = 4;
  const autosave = new ExamAutosave({ answers: { [A]: 0 }, revision: 2 }, server.transport);
  autosave.set(A, 1);
  assert.equal(await autosave.flush(), true);
  assert.equal(server.calls[0]?.revision, 2);
  assert.deepEqual(server.calls[1], { revision: 3, answers: { [A]: 1 } });
  assert.deepEqual(server.exam.answers, { [A]: 1, [B]: 4 });
  assert.deepEqual(autosave.snapshot().answers, { [A]: 1, [B]: 4 });
});

test('a closed exam stops autosave', async () => {
  const server = fakeServer({ answers: {}, revision: 0, status: 'expired' });
  const autosave = new ExamAutosave({ answers: {}, revision: 0 }, server.transport);
  autosave.set(A, 1);
  assert.equal(await autosave.flush(), false);
  assert.equal(autosave.snapshot().state, 'closed');
  autosave.set(B, 1);
  assert.equal(autosave.snapshot().answers[B], undefined, 'no edits after close');
});

test('network failures are reported as retrying and keep the edit pending', async () => {
  const autosave = new ExamAutosave(
    { answers: {}, revision: 0 },
    { save: async () => ({ status: 0, body: null }), load: async () => ({ status: 0, body: null }) }
  );
  autosave.set(A, 3);
  assert.equal(await autosave.flush(), false);
  assert.equal(autosave.snapshot().state, 'retrying');
  assert.equal(autosave.hasPending(), true);
});

test('concurrent flushes are serialised', async () => {
  const server = fakeServer({ answers: {}, revision: 0 });
  const autosave = new ExamAutosave({ answers: {}, revision: 0 }, server.transport);
  autosave.set(A, 1);
  const first = autosave.flush();
  autosave.set(B, 2);
  const second = autosave.flush();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.ok(server.calls.every((call, i) => call.revision === i), 'each save used the latest revision');
  assert.deepEqual(server.exam.answers, { [A]: 1, [B]: 2 });
});

test('written answers autosave with the same revision and clear when blanked', async () => {
  const sent: { revision: number; answers: Record<string, number | null>; text: Record<string, string | null> }[] = [];
  let text: Record<string, string> = {};
  let revision = 0;
  const transport: AutosaveTransport = {
    async save(rev, answers, textAnswers): Promise<HttpReply> {
      sent.push({ revision: rev, answers, text: textAnswers });
      for (const [id, value] of Object.entries(textAnswers)) {
        if (value === null) {
          const { [id]: _removed, ...rest } = text;
          text = rest;
        } else text = { ...text, [id]: value };
      }
      revision += 1;
      return { status: 200, body: { exam_id: 'e', revision, deadline_at: null, answers: {}, text_answers: { ...text } } };
    },
    async load(): Promise<HttpReply> {
      return { status: 200, body: { status: 'active', revision, answers: {}, text_answers: { ...text } } };
    }
  };
  const autosave = new ExamAutosave({ answers: {}, revision: 0 }, transport);
  autosave.setText(A, 'Crazy paving');
  assert.equal(await autosave.flush(), true);
  assert.deepEqual(sent[0], { revision: 0, answers: {}, text: { [A]: 'Crazy paving' } });
  autosave.setText(A, '   ');
  assert.equal(await autosave.flush(), true);
  assert.deepEqual(sent[1].text, { [A]: null });
  assert.deepEqual(autosave.snapshot().textAnswers, {});
  assert.equal(autosave.snapshot().revision, 2);
});
