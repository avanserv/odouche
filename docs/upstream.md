# Upstream reference

What Odoo.sh was observed to do, from a browser capture and from plain requests. Odoo.sh is
undocumented and can change without notice, so every section is dated. Values are scrubbed:
`session_id=REDACTED` stands for a session, and project names and logins are invented.

## Login and session

Captured on 2026-10-01.

### Login flow

Signing in with a GitHub account that has already authorised Odoo.sh:

| Hop | Request | Answer |
| --- | --- | --- |
| 1 | `GET www.odoo.sh/web/login` | 302 to `/oauth/signin` |
| 2 | `GET www.odoo.sh/oauth/signin` | 302 to `github.com/login/oauth/authorize`, with `client_id` and `scope=read:user user:email` |
| 3 | `GET github.com/login/oauth/authorize` | 302 to `www.odoo.sh/oauth/callback`, with `code` and `iss` |
| 4 | `GET www.odoo.sh/oauth/callback` | 303 to `/project`, and sets the authenticated `session_id` |
| 5 | `GET www.odoo.sh/project` | 200, the project list page |

- The authorisation request carries no `state` parameter.
- Hop 3 shows no page when GitHub is already signed in. A sign-in on GitHub itself was not
  captured.
- Odoo.sh has no login form of its own: `/web/login` only redirects.

### Session cookie

The session is the `session_id` cookie on `www.odoo.sh`. Sent alone, it authenticates a request:
no other cookie or header is needed.

| Attribute | Value |
| --- | --- |
| `Domain` | not set, so the cookie is bound to `www.odoo.sh` only |
| `Path` | `/` |
| `HttpOnly` | yes: page script cannot read it |
| `Secure` | not set |
| `SameSite` | not set |
| `Max-Age` | `691200` (8 days) |
| `Expires` | one year ahead, which `Max-Age` overrides |

- The value is 84 characters from the URL-safe alphabet.
- An anonymous `session_id` exists before login: `/web/login` and `/oauth/signin` set one on a
  request that has none. The presence of the cookie says nothing about being signed in.
- Hop 4 replaces the anonymous value with a new one.
- Page responses send the cookie again with the same value and a fresh `Max-Age`.

Other cookies on `www.odoo.sh` are `frontend_lang`, `tz` and two analytics cookies. None of them
takes part in authentication.

### Without a valid session

The answers are the same with no cookie and with a made-up `session_id`.

| Request | Status | Answer |
| --- | --- | --- |
| Page: `GET /project` | 303 | `Location: /web/login?redirect=%2Fproject%3F` |
| JSON: `POST /app/projects` | 200 | A JSON-RPC error, below |

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": 0,
    "message": "Odoo Server Error",
    "data": {
      "name": "odoo.http.SessionExpiredException",
      "message": "Session expired"
    }
  }
}
```

A JSON request never answers 401 or 403 for a missing session. The status is 200 and the only
signal is `error.data.name`.

### What else the session is tied to

- JSON requests are `POST` with `Content-Type: application/json` and a JSON-RPC body
  (`{"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1}`). The read requests captured
  send no CSRF token, and are accepted without `Origin` or `Referer`.
- The `/project` page embeds a `csrf_token`. No state-changing request was captured, so whether
  one requires it is unknown.
- `POST /app/project/<project>/get_info` returns an `access_token` of 32 characters, distinct
  from the session. No captured request sends it.

### Logout

`GET www.odoo.sh/web/session/logout?redirect=...` answers 303 to `/` and sets a new anonymous
`session_id`. It takes no CSRF token. The previous value is invalidated on the server: replayed
afterwards, it gets the `SessionExpiredException` answer above.

### Hosts

Contacted during login and on the project pages:

| Host | Role | Authentication |
| --- | --- | --- |
| `www.odoo.sh` | Pages and every `/app/...` JSON request | `session_id` |
| `github.com` | Hop 3 of the login | GitHub's own session |
| `avatars.githubusercontent.com` | User avatars | None |

The pages also load fonts, analytics and an embedded video from third parties. A client needs
none of them.

Each build has a host of its own, `<project>-<branch>-<build id>.dev.odoo.com`, which serves
its database, its shell (`/odoo-sh/webshell/ws`) and its editor (`/odoo-sh/editor/lab`). The
`www.odoo.sh` session is not sent there, since the cookie is bound to `www.odoo.sh`. Without
authentication of its own, the build host answers 302 to
`www.odoo.sh/paas/build/<build id>/token?redirect=...&otp=0`, so access is handed over from the
`www.odoo.sh` session. The hops after that were not captured.

Named in the project payloads but not contacted:

| Host | Role |
| --- | --- |
| `<project>.odoo.com` | The production database |
| `eupd00.odoo.com` and other numbered hosts | Unknown |
| `upgrade.odoo.com` | Odoo's upgrade service |

### Unknown

- How long a session lasts on the server, and whether use extends it. The cookie declares 8 days
  and is renewed by page responses.
- Which host serves build logs. No log request was captured.
- What the `/paas/build/<build id>/token` handover gives the build host, and how long it lasts.
- What `access_token` is for.
- Whether state-changing requests need the `csrf_token`.
