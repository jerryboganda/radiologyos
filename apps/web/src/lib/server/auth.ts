import { env } from '$env/dynamic/private';
import { env as publicEnv } from '$env/dynamic/public';
import { createRemoteJWKSet, jwtVerify, SignJWT } from 'jose';
import { createAuthorizationUrl, createPkcePair } from './oidc-url';

const SESSION_COOKIE = 'radbrain_session';
const STATE_COOKIE = 'radbrain_oidc_state';
const VERIFIER_COOKIE = 'radbrain_oidc_verifier';
const NONCE_COOKIE = 'radbrain_oidc_nonce';

export interface SessionUser {
  subject: string;
  name: string;
  email?: string;
  roles: string[];
  tenantId: string;
  tenantRole: string;
}

function config() {
  const issuer = env.OIDC_ISSUER ?? 'http://localhost:8080/realms/radbrain';
  const clientId = env.OIDC_CLIENT_ID;
  const clientSecret = env.OIDC_CLIENT_SECRET;
  const sessionSecret = env.AUTH_SESSION_SECRET;
  if (!clientId || !clientSecret || !sessionSecret || sessionSecret.length < 32) return null;
  return {
    issuer,
    internalIssuer: env.OIDC_INTERNAL_ISSUER ?? issuer,
    clientId,
    clientSecret,
    key: new TextEncoder().encode(sessionSecret)
  };
}

export function authEnabled(): boolean {
  return config() !== null;
}

function cookieOptions(secure: boolean) {
  return { httpOnly: true, sameSite: 'lax' as const, secure, path: '/' };
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
  if (!code || !state || !expectedState || !verifier || !expectedNonce || state !== expectedState) {
    throw new Error('The OIDC login response could not be verified');
  }

  const origin = publicEnv.PUBLIC_ORIGIN ?? url.origin;
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: `${origin}/auth/callback`,
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

  const jwks = createRemoteJWKSet(new URL(`${oidc.internalIssuer}/protocol/openid-connect/certs`));
  const { payload } = await jwtVerify(tokens.id_token, jwks, {
    issuer: oidc.issuer,
    audience: oidc.clientId,
    clockTolerance: 5
  });
  if (!payload.sub || payload.nonce !== expectedNonce) {
    throw new Error('The OIDC identity token did not match this login request');
  }
  const realmRoles = payload.realm_access;
  const roles = typeof realmRoles === 'object' && realmRoles !== null && 'roles' in realmRoles ? realmRoles.roles : [];
  const name = typeof payload.name === 'string'
    ? payload.name
    : typeof payload.preferred_username === 'string'
      ? payload.preferred_username
      : payload.sub;
  const user: Omit<SessionUser, 'tenantId' | 'tenantRole'> = {
    subject: payload.sub,
    name,
    ...(typeof payload.email === 'string' ? { email: payload.email } : {}),
    roles: Array.isArray(roles) ? roles.filter((role): role is string => typeof role === 'string') : []
  };
  const membershipResponse = await fetch(`${env.API_INTERNAL_URL ?? 'http://localhost:8000'}/v1/me`, {
    headers: { authorization: `Bearer ${tokens.access_token}` }
  });
  if (!membershipResponse.ok) {
    throw new Error('The authenticated subject has no current authorized membership');
  }
  const membership = (await membershipResponse.json()) as { id?: string; role?: string };
  if (!membership.id || !membership.role) {
    throw new Error('The API returned an invalid membership');
  }

  const session = await new SignJWT({
    name: user.name,
    email: user.email,
    roles: user.roles,
    tenantId: membership.id,
    tenantRole: membership.role
  })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setIssuer('radbrain-web')
    .setAudience('radbrain-web-session')
    .setSubject(user.subject)
    .setIssuedAt()
    .setExpirationTime('8h')
    .sign(oidc.key);
  cookies.set(SESSION_COOKIE, session, { ...options, maxAge: 8 * 60 * 60 });
  return {
    ...user,
    tenantId: membership.id,
    tenantRole: membership.role
  };
}

export async function readSession(cookies: import('@sveltejs/kit').Cookies): Promise<SessionUser | null> {
  const oidc = config();
  const token = cookies.get(SESSION_COOKIE);
  if (!oidc || !token) return null;
  try {
    const { payload } = await jwtVerify(token, oidc.key, {
      issuer: 'radbrain-web',
      audience: 'radbrain-web-session'
    });
    if (!payload.sub || typeof payload.name !== 'string') return null;
    if (typeof payload.tenantId !== 'string' || typeof payload.tenantRole !== 'string') return null;
    return {
      subject: payload.sub,
      name: payload.name,
      ...(typeof payload.email === 'string' ? { email: payload.email } : {}),
      roles: Array.isArray(payload.roles) ? payload.roles.filter((role): role is string => typeof role === 'string') : [],
      tenantId: payload.tenantId,
      tenantRole: payload.tenantRole
    };
  } catch {
    cookies.delete(SESSION_COOKIE, { path: '/' });
    return null;
  }
}

export function clearSession(cookies: import('@sveltejs/kit').Cookies, secure: boolean): void {
  cookies.delete(SESSION_COOKIE, cookieOptions(secure));
}
