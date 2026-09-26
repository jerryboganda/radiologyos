// Pure authentication helpers. No `$env/*` or `@sveltejs/kit` runtime imports, so
// `node --test` can exercise them directly; auth.ts wires them to the request.
import { jwtVerify, SignJWT, type JWTPayload } from 'jose';

export const SESSION_ISSUER = 'radbrain-web';
export const SESSION_AUDIENCE = 'radbrain-web-session';
export const SESSION_TTL_SECONDS = 8 * 60 * 60;
export const MIN_SESSION_SECRET_LENGTH = 32;
const DEFAULT_ISSUER = 'http://localhost:8080/realms/radbrain';

export interface SessionUser {
  subject: string;
  name: string;
  email?: string;
  roles: string[];
  tenantId: string;
  tenantRole: string;
}

export type OidcIdentity = Omit<SessionUser, 'tenantId' | 'tenantRole'>;

export interface AuthConfig {
  issuer: string;
  internalIssuer: string;
  clientId: string;
  clientSecret: string;
  key: Uint8Array;
}

export interface Membership {
  id: string;
  role: string;
}

export type EnvRecord = Record<string, string | undefined>;

/** The OIDC + session configuration, or null when sign-in must stay disabled. */
export function parseAuthConfig(env: EnvRecord): AuthConfig | null {
  const issuer = env.OIDC_ISSUER ?? DEFAULT_ISSUER;
  const clientId = env.OIDC_CLIENT_ID;
  const clientSecret = env.OIDC_CLIENT_SECRET;
  const sessionSecret = env.AUTH_SESSION_SECRET;
  if (!clientId || !clientSecret || !sessionSecret) return null;
  if (sessionSecret.length < MIN_SESSION_SECRET_LENGTH) return null;
  return {
    issuer,
    internalIssuer: env.OIDC_INTERNAL_ISSUER ?? issuer,
    clientId,
    clientSecret,
    key: new TextEncoder().encode(sessionSecret)
  };
}

export function cookieOptions(secure: boolean) {
  return { httpOnly: true, sameSite: 'lax' as const, secure, path: '/' };
}

export interface VerifiedCallback {
  code: string;
  verifier: string;
  nonce: string;
}

/** The callback values, or null unless every one is present and the state matches. */
export function checkCallback(input: {
  code: string | null;
  state: string | null;
  expectedState: string | undefined;
  verifier: string | undefined;
  expectedNonce: string | undefined;
}): VerifiedCallback | null {
  const { code, state, expectedState, verifier, expectedNonce } = input;
  if (!code || !state || !expectedState || !verifier || !expectedNonce) return null;
  if (state !== expectedState) return null;
  return { code, verifier, nonce: expectedNonce };
}

/** String entries of a role list; anything else yields no roles. */
export function stringRoles(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((role): role is string => typeof role === 'string') : [];
}

/** Keycloak's `realm_access.roles`, tolerating a missing or malformed claim. */
export function realmRoles(realmAccess: unknown): string[] {
  if (typeof realmAccess !== 'object' || realmAccess === null || !('roles' in realmAccess)) return [];
  return stringRoles(realmAccess.roles);
}

/** `name`, then `preferred_username`, then the subject. */
export function displayName(payload: JWTPayload, subject: string): string {
  if (typeof payload.name === 'string') return payload.name;
  if (typeof payload.preferred_username === 'string') return payload.preferred_username;
  return subject;
}

/** Map verified ID-token claims to an identity; throws on a missing subject or nonce mismatch. */
export function identityFromIdToken(payload: JWTPayload, expectedNonce: string): OidcIdentity {
  if (!payload.sub || payload.nonce !== expectedNonce) {
    throw new Error('The OIDC identity token did not match this login request');
  }
  return {
    subject: payload.sub,
    name: displayName(payload, payload.sub),
    ...(typeof payload.email === 'string' ? { email: payload.email } : {}),
    roles: realmRoles(payload.realm_access)
  };
}

/** Validate the API's `/v1/me` body; tenant and role must both be present. */
export function parseMembership(body: unknown): Membership {
  const value = (typeof body === 'object' && body !== null ? body : {}) as { id?: unknown; role?: unknown };
  if (typeof value.id !== 'string' || !value.id || typeof value.role !== 'string' || !value.role) {
    throw new Error('The API returned an invalid membership');
  }
  return { id: value.id, role: value.role };
}

export function signSession(user: SessionUser, key: Uint8Array): Promise<string> {
  return new SignJWT({
    name: user.name,
    email: user.email,
    roles: user.roles,
    tenantId: user.tenantId,
    tenantRole: user.tenantRole
  })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setIssuer(SESSION_ISSUER)
    .setAudience(SESSION_AUDIENCE)
    .setSubject(user.subject)
    .setIssuedAt()
    .setExpirationTime(`${SESSION_TTL_SECONDS}s`)
    .sign(key);
}

/** Verify signature, issuer, audience, and expiry; throws when any fails. */
export async function verifySessionToken(token: string, key: Uint8Array): Promise<JWTPayload> {
  const { payload } = await jwtVerify(token, key, {
    issuer: SESSION_ISSUER,
    audience: SESSION_AUDIENCE,
    algorithms: ['HS256']
  });
  return payload;
}

/** A verified session payload as a SessionUser, or null when a claim is missing. */
export function sessionFromClaims(payload: JWTPayload): SessionUser | null {
  if (!payload.sub || typeof payload.name !== 'string') return null;
  if (typeof payload.tenantId !== 'string' || typeof payload.tenantRole !== 'string') return null;
  return {
    subject: payload.sub,
    name: payload.name,
    ...(typeof payload.email === 'string' ? { email: payload.email } : {}),
    roles: stringRoles(payload.roles),
    tenantId: payload.tenantId,
    tenantRole: payload.tenantRole
  };
}
