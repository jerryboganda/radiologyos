import { decodeJwt } from 'jose';
import { expect, test } from '@playwright/test';

const webBaseUrl = process.env.RADBRAIN_STAGING_WEB_URL;
const apiBaseUrl = process.env.RADBRAIN_STAGING_API_URL;
const username = process.env.RADBRAIN_STAGING_TEST_USERNAME;
const password = process.env.RADBRAIN_STAGING_TEST_PASSWORD;
const expectedTenantId = process.env.RADBRAIN_STAGING_EXPECTED_TENANT_ID;
const expectedRole = process.env.RADBRAIN_STAGING_EXPECTED_ROLE;
const expectedSubject = process.env.RADBRAIN_STAGING_EXPECTED_SUBJECT;
const expectedUserLabel = process.env.RADBRAIN_STAGING_EXPECTED_USER_LABEL;
const apiAudience = process.env.RADBRAIN_STAGING_API_AUDIENCE;
const unauthorizedTenantId = process.env.RADBRAIN_STAGING_UNAUTHORIZED_TENANT_ID;
const studentToken = process.env.RADBRAIN_STAGING_STUDENT_TOKEN;
const adminToken = process.env.RADBRAIN_STAGING_ADMIN_TOKEN;
const expiredToken = process.env.RADBRAIN_STAGING_EXPIRED_TOKEN;
const wrongAudienceToken = process.env.RADBRAIN_STAGING_WRONG_AUDIENCE_TOKEN;

function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing required staging variable: ${name}`);
  return value;
}

function audienceValues(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

test.describe('M0 staging acceptance', () => {
  test.beforeEach(() => {
    required('RADBRAIN_STAGING_WEB_URL', webBaseUrl);
    required('RADBRAIN_STAGING_API_URL', apiBaseUrl);
    required('RADBRAIN_STAGING_TEST_USERNAME', username);
    required('RADBRAIN_STAGING_TEST_PASSWORD', password);
    required('RADBRAIN_STAGING_EXPECTED_TENANT_ID', expectedTenantId);
    required('RADBRAIN_STAGING_EXPECTED_ROLE', expectedRole);
    required('RADBRAIN_STAGING_EXPECTED_SUBJECT', expectedSubject);
    required('RADBRAIN_STAGING_EXPECTED_USER_LABEL', expectedUserLabel);
    required('RADBRAIN_STAGING_API_AUDIENCE', apiAudience);
    required('RADBRAIN_STAGING_UNAUTHORIZED_TENANT_ID', unauthorizedTenantId);
    required('RADBRAIN_STAGING_STUDENT_TOKEN', studentToken);
    required('RADBRAIN_STAGING_ADMIN_TOKEN', adminToken);
    required('RADBRAIN_STAGING_EXPIRED_TOKEN', expiredToken);
    required('RADBRAIN_STAGING_WRONG_AUDIENCE_TOKEN', wrongAudienceToken);

  });

  test('OIDC membership, negative authorization, and logout', async ({ page, request }) => {
    const webUrl = required('RADBRAIN_STAGING_WEB_URL', webBaseUrl).replace(/\/+$/, '');
    const apiUrl = required('RADBRAIN_STAGING_API_URL', apiBaseUrl).replace(/\/+$/, '');
    const tenantId = required('RADBRAIN_STAGING_EXPECTED_TENANT_ID', expectedTenantId);
    const role = required('RADBRAIN_STAGING_EXPECTED_ROLE', expectedRole);
    const subject = required('RADBRAIN_STAGING_EXPECTED_SUBJECT', expectedSubject);
    const userLabel = required('RADBRAIN_STAGING_EXPECTED_USER_LABEL', expectedUserLabel);
    const audience = required('RADBRAIN_STAGING_API_AUDIENCE', apiAudience);
    const otherTenantId = required('RADBRAIN_STAGING_UNAUTHORIZED_TENANT_ID', unauthorizedTenantId);
    expect(new URL(webUrl).protocol).toBe('https:');
    expect(new URL(apiUrl).protocol).toBe('https:');
    const user = required('RADBRAIN_STAGING_TEST_USERNAME', username);
    const pass = required('RADBRAIN_STAGING_TEST_PASSWORD', password);

    const callbackUrls: URL[] = [];
    page.on('request', (browserRequest) => {
      const requestUrl = new URL(browserRequest.url());
      if (requestUrl.pathname === '/auth/callback') callbackUrls.push(requestUrl);
    });

    const apiHealth = await request.get(`${apiUrl}/health/live`);
    expect(apiHealth.status()).toBe(200);
    const apiReady = await request.get(`${apiUrl}/health/ready`);
    expect(apiReady.status()).toBe(200);

    await page.goto(`${webUrl}/auth/login`, { waitUntil: 'domcontentloaded' });
    await page.getByLabel(/username|email/i).fill(user);
    await page.getByLabel(/password/i).fill(pass);
    await page.getByRole('button', { name: /sign in|log in/i }).click();
    await page.waitForURL(`${webUrl}/`, { timeout: 60_000 });
    expect(callbackUrls.length).toBeGreaterThan(0);
    for (const callbackUrl of callbackUrls) {
      expect(callbackUrl.searchParams.get('code')).toBeTruthy();
      expect(callbackUrl.searchParams.has('access_token')).toBe(false);
      expect(callbackUrl.searchParams.has('id_token')).toBe(false);
      expect(callbackUrl.searchParams.has('client_secret')).toBe(false);
    }
    const finalUrl = new URL(page.url());
    if (['code', 'access_token', 'id_token'].some((key) => finalUrl.searchParams.has(key))) {
      throw new Error('OIDC callback URL contained credential material');
    }
    const student = required('RADBRAIN_STAGING_STUDENT_TOKEN', studentToken);
    const studentClaims = decodeJwt(student);
    expect(studentClaims.sub).toBe(subject);
    expect(Number(studentClaims.exp)).toBeGreaterThan(Math.floor(Date.now() / 1000));
    expect(audienceValues(studentClaims.aud)).toContain(audience);
    const membership = await request.get(`${apiUrl}/v1/me`, {
      headers: { authorization: `Bearer ${student}` }
    });
    expect(membership.status()).toBe(200);
    const membershipBody = (await membership.json()) as { id?: string; role?: string };
    expect(membershipBody.id).toBe(tenantId);
    expect(membershipBody.role).toBe(role);
    await expect(page.locator('.account-card')).toHaveAttribute('data-user-subject', subject);
    await expect(page.locator('body')).toContainText(userLabel);
    await expect(page.locator('body')).toContainText(role);

    const switchResponse = await request.post(
      `${apiUrl}/v1/tenants/switch?tenant_id=${otherTenantId}`,
      { headers: { authorization: `Bearer ${student}` } }
    );
    expect(switchResponse.status()).toBe(403);
    const membershipAfterSwitch = await request.get(`${apiUrl}/v1/me`, {
      headers: { authorization: `Bearer ${student}` }
    });
    expect(membershipAfterSwitch.status()).toBe(200);
    const afterSwitchBody = (await membershipAfterSwitch.json()) as { id?: string };
    expect(afterSwitchBody.id).toBe(tenantId);

    const studentAdmin = await request.get(`${apiUrl}/v1/admin/ping`, {
      headers: { authorization: `Bearer ${student}` }
    });
    expect(studentAdmin.status()).toBe(403);

    const adminAllowed = await request.get(`${apiUrl}/v1/admin/ping`, {
      headers: { authorization: `Bearer ${required('RADBRAIN_STAGING_ADMIN_TOKEN', adminToken)}` }
    });
    expect(adminAllowed.status()).toBe(200);

    const invalid = await request.get(`${apiUrl}/v1/me`, {
      headers: { authorization: 'Bearer not-a-valid-token' }
    });
    expect(invalid.status()).toBe(401);

    const expired = required('RADBRAIN_STAGING_EXPIRED_TOKEN', expiredToken);
    const expiredClaims = decodeJwt(expired);
    expect(expiredClaims.sub).toBe(subject);
    expect(Number(expiredClaims.exp)).toBeLessThan(Math.floor(Date.now() / 1000));
    const expiredResponse = await request.get(`${apiUrl}/v1/me`, {
      headers: { authorization: `Bearer ${expired}` }
    });
    expect(expiredResponse.status()).toBe(401);

    const wrongToken = required('RADBRAIN_STAGING_WRONG_AUDIENCE_TOKEN', wrongAudienceToken);
    const wrongClaims = decodeJwt(wrongToken);
    expect(wrongClaims.sub).toBe(subject);
    expect(Number(wrongClaims.exp)).toBeGreaterThan(Math.floor(Date.now() / 1000));
    expect(audienceValues(wrongClaims.aud)).not.toContain(audience);
    const wrongAudience = await request.get(`${apiUrl}/v1/me`, {
      headers: { authorization: `Bearer ${wrongToken}` }
    });
    expect(wrongAudience.status()).toBe(401);

    await page.getByRole('button', { name: /sign out/i }).click();
    await page.waitForURL(`${webUrl}/`, { timeout: 30_000 });
    await expect(page.locator('body')).toContainText('Sign in with Keycloak');
  });
});
