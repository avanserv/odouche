# Upstream backups

What the Backups tab of a branch does, captured on 2026-10-14 on one project, from its staging
branch, with a listing over SSH of its production build. The requests follow the
[common shape](upstream.md#common-shape) and the [identifiers](upstream.md#identifiers) of the
upstream reference. Values are scrubbed as there.

Creating a backup and preparing a download both change state on Odoo.sh. Listing does not.

## List

`POST /app/project/<technical_name>/backups`, no params. Fixture: `backups.json`.

The request belongs to the project, not to a branch: opened from the staging branch, it answered
the backups of every stage. `result` is a flat list, newest first, of two shapes told apart by
`type`.

Kept on the production build (see [below](#on-the-production-build)), `manual` and `daily`:

| Field | Type | Observed |
| --- | --- | --- |
| `type` | str | `manual`, `daily` |
| `backup_datetime_utc` | str | The timestamp that names the backup in every later request |
| `name` | str | The name of the build it was taken from |
| `branch`, `stage` | str | The branch and stage it was taken from |
| `revision` | str | The build's commit |
| `odoo_branch`, `machine` | str | `19.0`, `ubuntu-24.04` |
| `installed_modules` | object | `custom` and `standard`, each a comma-separated string |
| `path` | str | A path on Odoo.sh's side, not the build's |
| `comment`, `upgrade` | `null` | |
| `downloadable` | bool | `true` |

Off-site, `remote`:

| Field | Type | Observed |
| --- | --- | --- |
| `type` | str | `remote` |
| `id` | int | Not stable: see below |
| `backup_datetime_utc`, `name`, `branch`, `revision` | str | As above |
| `project` | str | The `technical_name` |
| `size_sql_gz`, `size_container` | float | Bytes: the compressed SQL, and the whole backup |
| `downloadable` | bool | `false` |

- One `daily` backup was listed, the latest. The `remote` list held one a day for ten days, then
  two a week for four weeks.
- The latest `remote` backup has the same `backup_datetime_utc` as the `daily` one: it is the
  same backup, kept off-site.
- **A `remote` id is not an identifier.** Two answers 2 minutes apart gave most backups
  different ids. Name a backup by its `backup_datetime_utc`, as the download does.
- Only a `remote` backup gives a size, and it cannot be downloaded as it is.

Seen twice, from the staging branch.

## Create a manual backup

`POST /app/build/<id>/dump`, params `{"backup_only": true, "comment": ""}`, on the branch's
current build. Fixture: `dump.json`.

- The answer is 200 with no `result`: `{"jsonrpc": "2.0", "id": 73}`.
- The backup was listed with a `backup_datetime_utc` 58 seconds after the request.
- 77 seconds after the request, the project gained a notification (`notif_type` `dump`, name
  `Manual Backup Ready`): "Your backup is ready and will be kept for 3 days. Please note that
  manual backups are stored locally and do not follow the same replication and security policies
  as daily platform backups." Its button links to the branch's Backups tab.
- Notifications are in `get_info` under `notifications.<project id>.items`, with `id`, `seen`,
  `create_date`, `notif_type`, `level`, `name`, `content` (HTML) and `buttons`.
  `POST /app/project/<project id>/mark_notifications_seen`, no params, answers `true`.
- `get_info`'s `active_repo.dump_in_progress` was `false` once the backup was ready.
- The page learnt of the notification without asking for it, so over the
  [bus](upstream.md#build-status-changes). Its frames were not captured.

Seen once, on a staging build.

## Prepare a download

`POST /app/build/<id>/dump`, params `{"test_dump": true, "filestore": true,
"backup_datetime_utc": "<timestamp>"}`, on the build the backup was taken from, which was also
the branch's current build.

- `test_dump` is the dialog's choice between a neutralized database (`true`) and an exact one;
  `filestore` whether the filestore is included.
- The answer is the same empty one as the create's.
- The download was asked for 64 seconds later, after a second notification was marked seen. That
  notification was not captured.

Seen once, with `test_dump` and `filestore` both `true`. The three other combinations were not
captured; that they send `false` is inferred from the shape.

## Download

The page's link is on the worker of the build, with the same three values:

`GET <worker_url>/paas/build/<id>/download/dump?backup_datetime_utc=<timestamp>&test_dump=1&filestore=1`

| Hop | Request | Answer |
| --- | --- | --- |
| 1 | The link, without authentication | 302 to `www.odoo.sh/paas/build/<id>/token?redirect=<path and query of the link>&base_url=<worker_url>`, and sets a `session_id` cookie on the worker |
| 2 | That URL, with the `www.odoo.sh` session | 302 to the link with a `token` parameter first |
| 3 | The link with `token`, and the worker's cookie | 200, the file |

- The link itself grants nothing: without a `www.odoo.sh` session, hop 2 has none to hand over.
  The `token` grants the file. It is 32 letters and digits, appears in no other answer, and is
  not the project's `access_token`.
- Hop 3 sent the cookie set at hop 1. Whether the `token` alone is enough is unknown.
- The file came with `Content-Length` and
  `Content-Disposition: attachment; filename*=UTF-8''<build name>_<YYYY-MM-DD_HHMMSS>_test_fs.zip`,
  as `application/octet-stream`. The zip held `dump.sql` first.
- The worker's cookie lasts 7 days.

Seen once, on a staging build.

## On the production build

Over SSH, the production build's `~/backup.daily` held three entries per `manual` and `daily`
backup: `<name>_<type>.sql.gz`, `<name>_<type>.json` and a directory
`<name>_<type>`. A `manual` entry is prefixed `<YYYY-MM-DD_HHMMSS>-`.

- It held the latest `daily` backup of production and the `manual` backup taken on staging, so
  backups of every stage live on the production build.
- The files were mode `644`, the directories `755`, owned by `odoo`.
- The `.sql.gz` was the size the `remote` entry gives as `size_sql_gz`.

Seen once, on 2026-10-14. The JSON file and the directory were not read.

## Not seen

- A manual backup on production, a second request while one runs, and a refused stage.
- Whether a development branch has the tab.
- The bus frames for both notifications, and the second notification's content.
- How a `remote` backup is made downloadable.
- How long a manual backup's download, or a `token`, lasts.
