/**
 * The other half of authentication: a token for a client with no cookie jar, a session for a browser.
 */

export interface ApiToken {
  id: number;
  label: string;
  revoked: boolean;
  user_id: number;
  created_at: string;
  expires_at: string | null;
}

export interface LoginSession {
  id: number;
  user_id: number;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string | null;
}
