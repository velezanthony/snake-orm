/**
 * Who the demo's people are: the person, the roles they hold, and what the engine counted for them.

`User` and `Role` live here and not next to the pages that read them, mirroring `shared/models/accounts_models.py` — the same file the Python side keeps them in.
 */

export interface User {
  id: number;
  username: string;
  email: string;
}

export interface Role {
  id: number;
  name: string;
}

export interface UserStats {
  id: number;
  username: string;
  post_count: number;
}
