import { SignJWT } from 'jose';

// Kept free of SvelteKit imports so it can be unit-tested with node --test.
export const ASSERTION_ISSUER = 'radbrain-web';
export const ASSERTION_AUDIENCE = 'radbrain-api-internal';
const LIFETIME_SECONDS = 60;

export class ApiUnavailable extends Error {}

export async function signAssertion(subject: string, secret: string | undefined): Promise<string> {
  if (!secret || secret.length < 32) throw new ApiUnavailable('WEB_API_SECRET is not configured');
  if (!subject.trim()) throw new ApiUnavailable('no subject');
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({})
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuer(ASSERTION_ISSUER)
    .setAudience(ASSERTION_AUDIENCE)
    .setSubject(subject)
    .setIssuedAt(now)
    .setExpirationTime(now + LIFETIME_SECONDS)
    .sign(new TextEncoder().encode(secret));
}
