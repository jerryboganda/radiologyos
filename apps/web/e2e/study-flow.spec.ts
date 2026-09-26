// Synthetic end-to-end study flow against the CI Compose stack (.github/workflows/e2e.yml).
// Skipped unless RADBRAIN_E2E_WEB_URL is set. No model credentials exist in that
// stack, so nothing here submits an AI action; pages must render without AI output
// and show the degraded (keyword-only, vision-pending) states instead.
import { randomBytes } from 'node:crypto';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

const webUrl = process.env.RADBRAIN_E2E_WEB_URL?.replace(/\/+$/, '');
const username = process.env.RADBRAIN_E2E_USERNAME;
const password = process.env.RADBRAIN_E2E_PASSWORD;
const expectedSubject = process.env.RADBRAIN_E2E_EXPECTED_SUBJECT;

const INGEST_TIMEOUT = 240_000;

function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing required E2E variable: ${name}`);
  return value;
}

/** A lowercase token that exists nowhere else, so search can only find our upload. */
function uniqueWord(): string {
  const letters = Array.from(randomBytes(10), (byte) => String.fromCharCode(97 + (byte % 26))).join('');
  return `zq${letters}x`;
}

/** A hand-written one-page PDF (Helvetica, native text) with a correct xref table. */
function syntheticPdf(word: string): Buffer {
  const content = [
    'BT /F1 20 Tf 72 720 Td (Synthetic radbrain fixture) Tj ET',
    `BT /F1 12 Tf 72 660 Td (This synthetic page mentions the marker ${word} for search.) Tj ET`
  ].join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`
  ];
  let pdf = '%PDF-1.4\n';
  const offsets: number[] = [];
  objects.forEach((body, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf, 'latin1');
}

/** `ready`, `failed`, or `processing` from a library row's visible text. */
function rowState(text: string): string {
  if (/\bfailed\b/i.test(text)) return 'failed';
  if (/\bready\b/i.test(text)) return 'ready';
  return 'processing';
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/');
  await page.getByRole('link', { name: /sign in with keycloak/i }).click();
  // Keycloak's stable form ids (the v2 theme also labels a "show password" button).
  await page.locator('#username').fill(required('RADBRAIN_E2E_USERNAME', username));
  await page.locator('#password').fill(required('RADBRAIN_E2E_PASSWORD', password));
  await page.locator('#kc-login').click();
  await page.waitForURL((url) => url.origin === webUrl && url.pathname === '/', { timeout: 60_000 });
}

test.describe('synthetic study flow', () => {
  test.skip(!webUrl, 'RADBRAIN_E2E_WEB_URL is not set');
  test.describe.configure({ mode: 'serial' });

  const word = uniqueWord();
  const fileName = `e2e-${word}.pdf`;
  let context: BrowserContext;
  let page: Page;

  test.beforeAll(async ({ browser }: { browser: Browser }) => {
    context = await browser.newContext({ baseURL: webUrl });
    page = await context.newPage();
  });

  test.afterAll(async () => {
    await context?.close();
  });

  test('guards refuse anonymous access', async ({ request }) => {
    const upload = await request.post(`${webUrl}/library/upload`, { maxRedirects: 0 });
    expect(upload.status()).toBe(401);
    await page.goto('/library');
    await expect(page).toHaveURL(`${webUrl}/`);
    await expect(page.getByRole('link', { name: /sign in with keycloak/i })).toBeVisible();
  });

  test('signs in through Keycloak with a tenant membership', async () => {
    const callbacks: URL[] = [];
    page.on('request', (req) => {
      const url = new URL(req.url());
      if (url.pathname === '/auth/callback') callbacks.push(url);
    });
    await signIn(page);
    expect(callbacks.length).toBeGreaterThan(0);
    for (const url of callbacks) {
      expect(url.searchParams.get('code')).toBeTruthy();
      expect(url.searchParams.has('access_token')).toBe(false);
      expect(url.searchParams.has('id_token')).toBe(false);
    }
    const account = page.locator('.account-card').first();
    await expect(account).toContainText('student');
    if (expectedSubject) await expect(account).toHaveAttribute('data-user-subject', expectedSubject);
    const cookies = await context.cookies();
    const session = cookies.find((cookie) => cookie.name === 'radbrain_session');
    expect(session?.httpOnly).toBe(true);
    expect(session?.sameSite).toBe('Lax');
  });

  test('uploads a synthetic PDF that becomes keyword-searchable', async () => {
    test.setTimeout(INGEST_TIMEOUT + 60_000);
    await page.goto('/library');
    await expect(page.getByRole('heading', { level: 1, name: 'Your sources' })).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles({
      name: fileName,
      mimeType: 'application/pdf',
      buffer: syntheticPdf(word)
    });
    await expect(page.getByText('Uploaded — processing started.')).toBeVisible({ timeout: 60_000 });

    const row = page.locator('li.panel').filter({ hasText: word });
    const state = async () => {
      await page.reload();
      return (await row.count()) ? rowState(await row.first().innerText()) : 'missing';
    };
    await expect.poll(state, { timeout: INGEST_TIMEOUT, intervals: [2_000, 5_000, 10_000] }).toMatch(/^(ready|failed)$/);
    expect(await state()).toBe('ready');
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(/1 pages/i);
  });

  test('opens the page in the reader with native text and no AI figures', async () => {
    await page.goto('/library');
    const row = page.locator('li.panel').filter({ hasText: word });
    await row.getByRole('link', { name: 'Read' }).click();
    await expect(page).toHaveURL(/\/library\/[0-9a-f-]{36}/);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(word);

    const image = page.getByAltText(/^Page 1 of /);
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(page.getByText('text: native')).toBeVisible();
    await expect(page.getByRole('tabpanel')).toContainText(word);

    // No model transport: the vision pass is skipped, so no figures are described.
    await page.getByRole('tab', { name: /Figures/ }).click();
    await expect(page.getByRole('tabpanel')).toContainText('Figures appear here once the vision pass has parsed this page.');
    await expect(page.getByText('AI description')).toHaveCount(0);
  });

  test('search finds the unique word as a cited, keyword-only passage', async () => {
    await page.goto('/search');
    await page.getByRole('searchbox', { name: 'Search your library' }).fill(word);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`[?&]q=${word}`));
    const passages = page.getByRole('region', { name: 'Passages' });
    await expect(passages).toContainText(word);
    await expect(passages.locator('ol > li')).toHaveCount(1);
    // No embedder and no Voyage key in this stack: the page says so rather than failing.
    await expect(page.getByText('keyword only (embeddings off)')).toBeVisible();
  });

  test('today renders onboarding for a new learner', async () => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /E2E/ })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'When is your exam?' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Shortcuts' })).toContainText('1 sources');
    await expect(page.getByText('Your study planner is unreachable')).toHaveCount(0);
  });

  test('questions page renders an empty bank', async () => {
    await page.goto('/questions');
    await expect(page.getByRole('heading', { level: 1, name: 'Practice questions' })).toBeVisible();
    await expect(page.getByText('No questions match.')).toBeVisible();
    await expect(page.getByText('The question bank is unreachable')).toHaveCount(0);
    // The ready upload is offered as a generation source (the form is not submitted).
    await expect(page.locator('select[name="source_ids"] option', { hasText: word })).toHaveCount(1);
  });

  test('exams page renders with no papers yet', async () => {
    await page.goto('/exams');
    await expect(page.getByRole('heading', { level: 1, name: 'Timed mock exams' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Start a paper' })).toBeVisible();
    await expect(page.getByText('No exams yet.', { exact: false })).toBeVisible();
  });

  test('settings accepts a data export request', async () => {
    await page.goto('/settings');
    const section = page.getByRole('region', { name: 'Export my data' });
    await expect(section).toBeVisible();
    await section.getByRole('button', { name: 'Export my data' }).click();
    await expect(section.getByText('Export queued.', { exact: false })).toBeVisible({ timeout: 30_000 });
    await expect(section.getByRole('list', { name: 'Your exports' }).getByRole('listitem')).toHaveCount(1);
  });

  test('signing out ends the session', async () => {
    await page.locator('.account-card').first().getByRole('button', { name: 'Sign out' }).click();
    await page.waitForURL(`${webUrl}/`);
    await expect(page.getByRole('link', { name: /sign in with keycloak/i })).toBeVisible();
    const upload = await page.request.post('/library/upload', { maxRedirects: 0 });
    expect(upload.status()).toBe(401);
  });
});
