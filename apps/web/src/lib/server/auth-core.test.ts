import assert from 'node:assert/strict';
import test from 'node:test';
import { SignJWT } from 'jose';
import {
  checkCallback,
  cookieOptions,
  displayName,
  identityFromIdToken,
  parseAuthConfig,
  parseMembership,
  realmRoles,
  SESSION_AUDIENCE,
  SESSION_ISSUER,
  SESSION_TTL_SECONDS,
  sessionFromClaims,
  signSession,
  verifySessionToken,
  type SessionUser
} from './auth-core.ts';

const secret = 's'.repeat(40);
const key = new TextEncoder().encode(secret);
const baseEnv = { OIDC_CLIENT_ID: 'radbrain-web', OIDC_CLIENT_SECRET: 'client-secret', AUTH_SESSION_SECRET: secret };
const user: SessionUser = {
  subject: 'sub-1',
  name: 'Synthetic Student',
  email: 'student@example.test',
  roles: ['student'],
  tenantId: '11111111-1111-4111-8111-111111111111',
  tenantRole: 'student'
};

test('parses a complete configuration with issuer defaults', () => {
  const config = parseAuthConfig(baseEnv);
  assert.ok(config);
  assert.equal(config.issuer, 'http://localhost:8080/realms/radbrain');
  assert.equal(config.internalIssuer, config.issuer);
  assert.equal(config.clientId, 'radbrain-web');
  assert.deepEqual(config.key, key);
  const split = parseAuthConfig({ ...baseEnv, OIDC_ISSUER: 'https://id.example/r', OIDC_INTERNAL_ISSUER: 'http://kc:8080/r' });
  assert.equal(split?.issuer, 'https://id.example/r');
  assert.equal(split?.internalIssuer, 'http://kc:8080/r');
});

test('disables sign-in when a secret is missing or the session secret is short', () => {
  assert.equal(parseAuthConfig({ ...baseEnv, OIDC_CLIENT_SECRET: undefined }), null);
  assert.equal(parseAuthConfig({ ...baseEnv, OIDC_CLIENT_SECRET: '' }), null);
  assert.equal(parseAuthConfig({ ...baseEnv, OIDC_CLIENT_ID: undefined }), null);
  assert.equal(parseAuthConfig({ ...baseEnv, AUTH_SESSION_SECRET: undefined }), null);
  assert.equal(parseAuthConfig({ ...baseEnv, AUTH_SESSION_SECRET: 'x'.repeat(31) }), null);
  assert.ok(parseAuthConfig({ ...baseEnv, AUTH_SESSION_SECRET: 'x'.repeat(32) }));
});

test('cookies are http-only, lax, and secure only on https', () => {
  assert.deepEqual(cookieOptions(true), { httpOnly: true, sameSite: 'lax', secure: true, path: '/' });
  assert.equal(cookieOptions(false).secure, false);
});

test('accepts a callback only when every value is present and the state matches', () => {
  const ok = { code: 'c', state: 's', expectedState: 's', verifier: 'v', expectedNonce: 'n' };
  assert.deepEqual(checkCallback(ok), { code: 'c', verifier: 'v', nonce: 'n' });
  assert.equal(checkCallback({ ...ok, state: 'other' }), null);
  assert.equal(checkCallback({ ...ok, code: null }), null);
  assert.equal(checkCallback({ ...ok, state: null }), null);
  assert.equal(checkCallback({ ...ok, expectedState: undefined }), null);
  assert.equal(checkCallback({ ...ok, verifier: undefined }), null);
  assert.equal(checkCallback({ ...ok, expectedNonce: undefined }), null);
});

test('extracts only string realm roles', () => {
  assert.deepEqual(realmRoles({ roles: ['student', 7, null, 'editor'] }), ['student', 'editor']);
  assert.deepEqual(realmRoles({ roles: 'student' }), []);
  assert.deepEqual(realmRoles({ roles: { 0: 'student' } }), []);
  assert.deepEqual(realmRoles(null), []);
  assert.deepEqual(realmRoles('student'), []);
  assert.deepEqual(realmRoles(undefined), []);
});

test('chooses name, then preferred username, then subject', () => {
  assert.equal(displayName({ name: 'A', preferred_username: 'b' }, 's'), 'A');
  assert.equal(displayName({ preferred_username: 'b' }, 's'), 'b');
  assert.equal(displayName({ name: 3 }, 's'), 's');
});

test('maps an ID token and rejects a nonce mismatch or missing subject', () => {
  const claims = { sub: 'sub-1', nonce: 'n1', name: 'A B', email: 'a@example.test', realm_access: { roles: ['student'] } };
  assert.deepEqual(identityFromIdToken(claims, 'n1'), {
    subject: 'sub-1',
    name: 'A B',
    email: 'a@example.test',
    roles: ['student']
  });
  assert.equal('email' in identityFromIdToken({ sub: 'x', nonce: 'n' }, 'n'), false);
  assert.throws(() => identityFromIdToken(claims, 'n2'), /did not match/);
  assert.throws(() => identityFromIdToken({ ...claims, nonce: undefined }, 'n1'), /did not match/);
  assert.throws(() => identityFromIdToken({ ...claims, sub: undefined }, 'n1'), /did not match/);
});

test('requires a membership with a tenant id and role', () => {
  assert.deepEqual(parseMembership({ id: 't', role: 'student', name: 'x' }), { id: 't', role: 'student' });
  for (const body of [null, 'x', {}, { id: 't' }, { role: 'student' }, { id: '', role: 'student' }, { id: 1, role: 'student' }]) {
    assert.throws(() => parseMembership(body), /invalid membership/);
  }
});

test('round-trips a signed session', async () => {
  const token = await signSession(user, key);
  const payload = await verifySessionToken(token, key);
  assert.equal(payload.iss, SESSION_ISSUER);
  assert.equal(payload.aud, SESSION_AUDIENCE);
  assert.equal((payload.exp ?? 0) - (payload.iat ?? 0), SESSION_TTL_SECONDS);
  assert.deepEqual(sessionFromClaims(payload), user);
});

test('rejects a session signed with another key', async () => {
  const forged = await signSession(user, new TextEncoder().encode('f'.repeat(40)));
  await assert.rejects(verifySessionToken(forged, key));
});

test('rejects a session with the wrong issuer, audience, or an expired token', async () => {
  const claims = { name: user.name, tenantId: user.tenantId, tenantRole: user.tenantRole };
  const base = () => new SignJWT(claims).setProtectedHeader({ alg: 'HS256' }).setSubject(user.subject).setIssuedAt();
  const wrongIssuer = await base().setIssuer('evil').setAudience(SESSION_AUDIENCE).setExpirationTime('1h').sign(key);
  const wrongAudience = await base().setIssuer(SESSION_ISSUER).setAudience('radbrain-api').setExpirationTime('1h').sign(key);
  const expired = await base().setIssuer(SESSION_ISSUER).setAudience(SESSION_AUDIENCE).setExpirationTime(Math.floor(Date.now() / 1000) - 60).sign(key);
  await assert.rejects(verifySessionToken(wrongIssuer, key));
  await assert.rejects(verifySessionToken(wrongAudience, key));
  await assert.rejects(verifySessionToken(expired, key));
});

test('rejects an unsigned (alg none) or tampered session', async () => {
  const token = await signSession(user, key);
  const [header, body] = token.split('.');
  const none = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
  await assert.rejects(verifySessionToken(`${none}.${body}.`, key));
  const claims = JSON.parse(Buffer.from(body, 'base64url').toString()) as Record<string, unknown>;
  const elevated = Buffer.from(JSON.stringify({ ...claims, tenantRole: 'superadmin' })).toString('base64url');
  await assert.rejects(verifySessionToken(`${header}.${elevated}.${token.split('.')[2]}`, key));
});

test('drops a verified session missing tenant or name claims', () => {
  const full = { sub: 's', name: 'n', tenantId: 't', tenantRole: 'student', roles: ['student', 1] };
  assert.deepEqual(sessionFromClaims(full), { subject: 's', name: 'n', roles: ['student'], tenantId: 't', tenantRole: 'student' });
  assert.equal(sessionFromClaims({ ...full, sub: undefined }), null);
  assert.equal(sessionFromClaims({ ...full, name: undefined }), null);
  assert.equal(sessionFromClaims({ ...full, tenantId: undefined }), null);
  assert.equal(sessionFromClaims({ ...full, tenantRole: 7 }), null);
  assert.deepEqual(sessionFromClaims({ ...full, roles: 'student' })?.roles, []);
});
