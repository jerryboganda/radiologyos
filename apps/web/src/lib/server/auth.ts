import { env } from '$env/dynamic/private';
import { env as publicEnv } from '$env/dynamic/public';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import {
  checkCallback,
  cookieOptions,
  identityFromIdToken,
  parseAuthConfig,
  parseMembership,
  sessionFromClaims,
  SESSION_TTL_SECONDS,
  signSession,
  verifySessionToken,
  type AuthConfig,
  type SessionUser
} from './auth-core';
import { createAuthorizationUrl, createPkcePair } from './oidc-url';

export type { SessionUser };

const SESSION_COOKIE = 'radbrain_session';
const STATE_COOKIE = 'radbrain_oidc_state';
const VERIFIER_COOKIE = 'radbrain_oidc_verifier';
const NONCE_COOKIE = 'radbrain_oidc_nonce';

function config() {
  return parseAuthConfig(env);
}

export function authEnabled(): boolean {
  return config() !== null;
}

function randomValue(): string {
  return Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64url');
}

export async function beginLogin(url: URL, cookies: import('@sveltejs/kit').Cookies) {
  const oidc = config();
  if (!oidc) throw new Error('Authentication is not configured');
  const pair = await createPkcePair();
  const state = randomValue();
  const nonce = randomValue();
  const options = { ...cookieOptions(url.protocol === 'https:'), maxAge: 600 };
  cookies.set(STATE_COOKIE, state, options);
  cookies.set(VERIFIER_COOKIE, pair.verifier, options);
  cookies.set(NONCE_COOKIE, nonce, options);
  const origin = publicEnv.PUBLIC_ORIGIN ?? url.origin;
  return createAuthorizationUrl({
    authorizationEndpoint: `${oidc.issuer}/protocol/openid-connect/auth`,
    clientId: oidc.clientId,
    redirectUri: `${origin}/auth/callback`,
    state,
    nonce,
    codeChallenge: pair.challenge
  });
}

async function exchangeCode(oidc: AuthConfig, code: string, verifier: string, redirectUri: string) {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri,
    client_id: oidc.clientId,
    code_verifier: verifier
  });
  const response = await fetch(`${oidc.internalIssuer}/protocol/openid-connect/token`, {
    method: 'POST',
    headers: {
      authorization: `Basic ${Buffer.from(`${oidc.clientId}:${oidc.clientSecret}`).toString('base64')}`,
      'content-type': 'application/x-www-form-urlencoded'
    },
    body
  });
  if (!response.ok) throw new Error('The OIDC token exchange was rejected');
  const tokens = (await response.json()) as { id_token?: string; access_token?: string };
  if (!tokens.id_token || !tokens.access_token) {
    throw new Error('The OIDC provider did not return the required tokens');
  }
  return { idToken: tokens.id_token, accessToken: tokens.access_token };
}

async function fetchMembership(accessToken: string) {
  const response = await fetch(`${env.API_INTERNAL_URL ?? 'http://localhost:8000'}/v1/me`, {
    headers: { authorization: `Bearer ${accessToken}` }
  });
  if (!response.ok) {
    throw new Error('The authenticated subject has no current authorized membership');
  }
  return parseMembership(await response.json());
}

export async function completeLogin(
  url: URL,
  cookies: import('@sveltejs/kit').Cookies
): Promise<SessionUser> {
  const oidc = config();
  if (!oidc) throw new Error('Authentication is not configured');
  const code = url.searchParams.get('code');
  const state = url.searchParams.get('state');
  const expectedState = cookies.get(STATE_COOKIE);
  const verifier = cookies.get(VERIFIER_COOKIE);
  const expectedNonce = cookies.get(NONCE_COOKIE);
  const options = cookieOptions(url.protocol === 'https:');
  for (const name of [STATE_COOKIE, VERIFIER_COOKIE, NONCE_COOKIE]) cookies.delete(name, options);
  const callback = checkCallback({ code, state, expectedState, verifier, expectedNonce });
  if (!callback) throw new Error('The OIDC login response could not be verified');

  const origin = publicEnv.PUBLIC_ORIGIN ?? url.origin;
  const tokens = await exchangeCode(oidc, callback.code, callback.verifier, `${origin}/auth/callback`);
  const jwks = createRemoteJWKSet(new URL(`${oidc.internalIssuer}/protocol/openid-connect/certs`));
  const { payload } = await jwtVerify(tokens.idToken, jwks, {
    issuer: oidc.issuer,
    audience: oidc.clientId,
    clockTolerance: 5
  });
  const identity = identityFromIdToken(payload, callback.nonce);
  const membership = await fetchMembership(tokens.accessToken);
  const user: SessionUser = { ...identity, tenantId: membership.id, tenantRole: membership.role };
  const session = await signSession(user, oidc.key);
  cookies.set(SESSION_COOKIE, session, { ...options, maxAge: SESSION_TTL_SECONDS });
  return user;
}

export async function readSession(cookies: import('@sveltejs/kit').Cookies): Promise<SessionUser | null> {
  const oidc = config();
  const token = cookies.get(SESSION_COOKIE);
  if (!oidc || !token) return null;
  let payload;
  try {
    payload = await verifySessionToken(token, oidc.key);
  } catch {
    cookies.delete(SESSION_COOKIE, { path: '/' });
    return null;
  }
  return sessionFromClaims(payload);
}

export function clearSession(cookies: import('@sveltejs/kit').Cookies, secure: boolean): void {
  cookies.delete(SESSION_COOKIE, cookieOptions(secure));
}
