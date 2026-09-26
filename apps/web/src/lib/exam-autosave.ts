// Exam autosave with revision compare-and-set. Framework-free so node --test
// can drive it with a fake transport; the exam screen mirrors its snapshot.
import { pendingChanges, rebase, saveOutcome, type Changes } from './exam-session.ts';
import type { Answers, AutosaveOut, ExamView, TextAnswers } from './types/assessment.ts';

export interface HttpReply {
  status: number;
  body: unknown;
}

export interface AutosaveTransport {
  save(revision: number, answers: Changes, textAnswers: Changes<string>): Promise<HttpReply>;
  load(): Promise<HttpReply>;
}

export type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'retrying' | 'closed' | 'error';

export interface AutosaveSnapshot {
  answers: Answers;
  textAnswers: TextAnswers;
  revision: number;
  state: SaveState;
  message: string;
}

const MAX_ROUNDS = 5;

function detailOf(body: unknown): string | null {
  const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null;
  return typeof detail === 'string' ? detail : null;
}

export class ExamAutosave {
  private saved: Answers;
  private local: Answers;
  private savedText: TextAnswers;
  private localText: TextAnswers;
  private revision: number;
  private state: SaveState = 'idle';
  private message = '';
  private chain: Promise<boolean> = Promise.resolve(true);
  private readonly transport: AutosaveTransport;
  private readonly onChange: (snapshot: AutosaveSnapshot) => void;

  // No parameter properties: node --experimental-strip-types only erases types.
  constructor(
    initial: { answers: Answers; revision: number; textAnswers?: TextAnswers },
    transport: AutosaveTransport,
    onChange: (snapshot: AutosaveSnapshot) => void = () => {}
  ) {
    this.transport = transport;
    this.onChange = onChange;
    this.saved = { ...initial.answers };
    this.local = { ...initial.answers };
    this.savedText = { ...(initial.textAnswers ?? {}) };
    this.localText = { ...(initial.textAnswers ?? {}) };
    this.revision = initial.revision;
  }

  snapshot(): AutosaveSnapshot {
    return {
      answers: { ...this.local },
      textAnswers: { ...this.localText },
      revision: this.revision,
      state: this.state,
      message: this.message
    };
  }

  /** Record a choice locally (null clears it); the caller schedules `flush`. */
  set(questionId: string, option: number | null): void {
    if (this.state === 'closed') return;
    if (option === null) delete this.local[questionId];
    else this.local[questionId] = option;
    this.update('dirty', '');
  }

  /** Record a written answer locally (blank or null clears it); the caller schedules `flush`. */
  setText(questionId: string, text: string | null): void {
    if (this.state === 'closed') return;
    if (text === null || text.trim() === '') delete this.localText[questionId];
    else this.localText[questionId] = text;
    this.update('dirty', '');
  }

  hasPending(): boolean {
    return this.count(pendingChanges(this.saved, this.local)) + this.count(pendingChanges(this.savedText, this.localText)) > 0;
  }

  private count(changes: Record<string, unknown>): number {
    return Object.keys(changes).length;
  }

  /** Save everything pending. Calls are serialised; resolves true when fully saved. */
  flush(): Promise<boolean> {
    this.chain = this.chain.then(() => this.run()).catch(() => this.fail('retrying', 'Connection lost; retrying.'));
    return this.chain;
  }

  private async run(): Promise<boolean> {
    for (let round = 0; round < MAX_ROUNDS; round += 1) {
      if (this.state === 'closed') return false;
      const changes = pendingChanges(this.saved, this.local);
      const textChanges = pendingChanges(this.savedText, this.localText);
      if (this.count(changes) + this.count(textChanges) === 0) {
        this.update('saved', 'All answers saved.');
        return true;
      }
      this.update('saving', 'Saving…');
      const reply = await this.transport.save(this.revision, changes, textChanges);
      const outcome = saveOutcome(reply.status, detailOf(reply.body));
      if (outcome === 'saved') this.accept(reply.body as AutosaveOut);
      else if (outcome === 'stale') {
        if (!(await this.reload())) return false;
      } else if (outcome === 'closed') return this.fail('closed', 'This exam is closed; showing results.');
      else if (outcome === 'retry') return this.fail('retrying', 'Connection problem; your answers will be retried.');
      else return this.fail('error', detailOf(reply.body) ?? 'Your answers could not be saved.');
    }
    return !this.hasPending();
  }

  private accept(out: AutosaveOut): void {
    this.saved = { ...out.answers };
    this.savedText = { ...(out.text_answers ?? this.savedText) };
    this.revision = out.revision;
  }

  /** 409 stale revision: reload the server copy and re-apply this tab's unsaved edits. */
  private async reload(): Promise<boolean> {
    const reply = await this.transport.load();
    if (reply.status < 200 || reply.status >= 300) {
      return this.fail(saveOutcome(reply.status, null) === 'retry' ? 'retrying' : 'error', 'Could not reload the exam.');
    }
    const exam = reply.body as ExamView;
    if (exam.status !== 'active') return this.fail('closed', 'This exam is closed; showing results.');
    this.local = rebase(exam.answers, this.saved, this.local);
    this.saved = { ...exam.answers };
    const serverText = exam.text_answers ?? {};
    this.localText = rebase(serverText, this.savedText, this.localText);
    this.savedText = { ...serverText };
    this.revision = exam.revision;
    return true;
  }

  private fail(state: SaveState, message: string): false {
    this.update(state, message);
    return false;
  }

  private update(state: SaveState, message: string): void {
    this.state = state;
    this.message = message;
    this.onChange(this.snapshot());
  }
}
