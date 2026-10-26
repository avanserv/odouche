# Upstream branch tools

What a branch's settings, revision, mails, panels and stage moves use, captured on 2026-10-23 on
one project with a production, a staging and a development branch. The requests follow the
[common shape](upstream.md#common-shape) and the [identifiers](upstream.md#identifiers) of the
upstream reference. Values are scrubbed as there.

Every write on this page was read from the page's script (`paas_master.paas_app_assets`), not
captured: saving settings, clearing mails and moving a stage. Reads were captured unless a section
says otherwise.

## Access

The page shows a branch's tabs, other than History, only when the user's level reaches the one
the branch's stage needs: `access_level_map[user.access] >= access_by_stage[stage]`, both from
the `config` of `get_info` (`project_info.json`). With the values seen, a `developer` reaches
`dev` branches, a `tester` also `staging`, and an `admin` every stage.

| Tab | Stages | Build needed |
| --- | --- | --- |
| Settings | All | No |
| Shell, Editor | All | The last build `done` |
| Monitor | `production`, `staging` | The last build `done` |
| Mails | `dev`, `staging` | The last build `done` |

That gate is the page's. What upstream answers a user below it was not seen.

## Branch and build settings

`POST /app/branch/<id>/get_settings`, no params. Fixture: `branch_settings.json`.

| Field | Type | Observed |
| --- | --- | --- |
| `push_behavior` | str | `new` on `dev`, `update` on `staging` and `production` |
| `apply_default_settings` | bool | `true`: the project's development defaults apply |
| `modules_auto` | str | `repo`; the page offers `repo`, `all`, `none` |
| `modules` | str or `false` | Comma-separated, when `modules_auto` is `none` |
| `test_mode` | str | `custom`; the page offers `off`, `custom`, `all` |
| `test_tags` | str or `false` | Odoo test tags, when `test_mode` is `all` |
| `demo_data` | bool | |
| `ai_agent` | str | `claude`; the page offers `claude`, `opencode` |
| `odoo_branch` | str or `false` | `false`: the project's version |
| `odoo_revision_id` | int or `false` | `false`: the latest weekly [revision](#revision) |
| `is_eol` | bool | |
| `machine`, `recommended_machine` | str | `ubuntu-24.04` |
| `machine_next_commit` | str or `false` | Only `false` seen; by the page's script, a machine's name when set |
| `domains` | list of str | Custom domains; one on the staging branch |
| `domain_build_production` | str | `odoo.com` |
| `domain_to_point_to` | str | The build's host on `dev`, the production host otherwise |
| `production_environment` | bool | `true` on all three stages |
| `upgrade_branch`, `upgrade_info`, `upgrade_step` | list, object, `false` | The Upgrade tab's state |

- The library reads `push_behavior`, `modules_auto`, `test_mode` and `ai_agent` as strict
  [enumerations](upstream.md#enumerations): a value outside them raises the changed shape error.
- `machine` values and their end of support are in `mappings.machine` of `get_info`: Ubuntu 18.04
  to 26.04, each with a `label`, `python_version` and `end_date`.
- The `branch_info` of a `builds` answer also carries `ai_agent`, `demo_data`, `is_ai`,
  `machine`, `odoo_branch`, `odoo_revision_id`, `test_mode`, `upgrade_step` and
  `last_build_odoo_branch`, and each build a `machine` and an `odoo_branch`, beyond the fields of
  [Builds of a branch](upstream.md#builds-of-a-branch).
- Seen once on each stage.

### Change a branch's settings

`POST /app/branch/<id>/set_settings`, read from the script (`Branch.updateSettings`). Its params
are one section of the tab, as form values, and its `result` is the branch's settings, which the
page merges into what it holds. The page never sends the whole tab:

| Section | Params | Stages | Sent |
| --- | --- | --- | --- |
| Behavior upon new commits | `push_behavior` | `dev`, `staging` | On change |
| New build options | `apply_default_settings`, `modules_auto`, `modules`, `test_mode`, `test_tags`, `demo_data`, `ai_agent` | `dev` | On change |
| Odoo version | `odoo_branch`, `odoo_revision_id` | All; `odoo_branch` only on `dev` | On save |
| Custom domains | `add_domain` or `delete_domain` | All | On click |
| Operating system | `machine`, `machine_next_commit` | All | On save |

- A section is one `<form>`, sent as `Object.fromEntries(new FormData(form))`, so values are
  strings. A checkbox is a hidden input of value `"off"` followed by the box, of value `"on"`, and
  the last wins: it is sent as `"on"` or `"off"`. A revision is its id or `"latest"`.
- A disabled field is left out. With `apply_default_settings` on, the other fields of its section
  are disabled, so it is sent alone. A field the page does not render is left out too: `modules`
  while the stored `modules_auto` is not `none`, `test_mode` while it is `all`, `test_tags` while
  `test_mode` is not `all`, and `demo_data` before Odoo 19.0. Behavior upon new commits is hidden
  while `upgrade_step` is set.
- The page's "unmute" sends `push_behavior` alone.
- That a field left out keeps its value is inferred, not seen: every save of the page leaves most
  fields out, and the hidden `"off"` inputs are needed only by a server that keeps a missing box.
- The library sends, in one request, the fields it is given that differ from `get_settings`,
  encoded as the form does. It reads the stage from `builds` and the settings before, and the
  settings after: it checks those rather than reading `result`, whose shape was not seen.
  `set_settings.json` stands for that answer, as the `get_settings` one.
- The library refuses what the page does not offer: `push_behavior` on `production`, a new build
  option on another stage than `dev`, one while `apply_default_settings` stays on, and one the page
  would not render given the values after the change. It does not check `upgrade_step` or the
  Odoo version for `demo_data`.
- The page warns that saving the Odoo version restarts the server with the new revision.

## Revision

The revision of a branch is that of Odoo's own repositories, not of the project's submodules.

`POST /app/odoo/<odoo_branch>/revisions`, no params, lists the weekly revisions of a version.
Fixture: `odoo_revisions.json`. Each has an `id`, a `name` (`19.0.20261019`), a `date` and
`has_security_issue`. Thirteen came back, one per week, newest first.

`POST /app/branch/<id>/revision`, params `{"odoo_branch": "19.0"}`, is the latest revision.
Fixture: `branch_revision.json`.

| Field | Type | Observed |
| --- | --- | --- |
| `id` | int | The latest of `revisions` |
| `date_expiration` | str | Ninety days after its `date` |
| `branch` | str | `19.0` |
| `refs` | list | `repository` (`odoo`, `enterprise`, `themes`), `ref` (a commit) and `url` |
| `issues` | list | Empty |

- The page asks `POST /app/revision/<revision id>`, no params, for a pinned revision instead. Read
  from the script.
- The three branches got the same answer. No request ties a build to the revision it ran: a build
  gives only `odoo_branch` and its `head_commit_*`, which are the project repository's.
- The project's own submodules are in the project's [`get_settings`](upstream-project.md#project-settings)
  (`submodules`, empty here), with their deploy keys and no commit. No request seen gives the
  commit of a submodule.
- The library sends `/app/revision/<odoo_revision_id>` when the branch pins one, and otherwise
  `/app/branch/<id>/revision` with the branch's `odoo_branch` or, when that is `false`, the
  project's, from the `projects` answer, as the page does.
- Fixture `odoo_revision.json` stands for the answer to `/app/revision/<id>`. That answer was not
  seen, and is read in the shape of the latest's.
- What a version past its end of life answers is not known: the page asks neither request for it.

## Mails

Mails are on the build's `worker_url`, authenticated by the project's `access_token` as
[logs](upstream.md#logs) are, and never by the session. They are the outgoing mails the build
caught.

`POST <worker_url>/paas/<build id>/mail/json/fetch`, params `{"token": "<access_token>"}`. The
`result` was an empty list, on the staging build, so the fields below are the script's:

- An item has `id`, `date`, `from`, `to` and `subject`. There is no paging: the page says it shows
  the latest 1000, and that older ones need `/home/odoo/MailDir` cleaned.
- `POST .../mail/json/message`, params `{"message_id": <id>, "token": ...}`, gives one mail:
  `headers` (`date`, `from`, `to`, `subject`), `attachments` (pairs of part and file name),
  `plain` (the text), `source` (the raw message) and `body_url`, a worker path whose HTML the page
  shows in a sandboxed frame. Its size was not seen.
- `POST .../mail/json/clear`, params `{"token": ...}`, deletes every mail of the build.
- `GET .../mail/message?message_id=<id>&token=<access_token>`, with `&message_format=eml` for the
  file, is the pop-out. The URL carries the token, so it must not be printed.
- A bus event `paas.repository/mailviewer` makes the page fetch again.

What the library reads, until a mail is seen (manual test R41 settles it). Fixtures `mails.json`
and `mail_message.json` stand for answers that were not seen, written in the script's shape.

- `id` as an integer or a string that is not empty, kept as a string and sent back in `message` as
  `fetch` typed it. Only an `id` that `fetch` listed is sent.
- `date`, `from`, `to` and `subject` as strings, `false` or `null` for a missing header. `date` is
  read as a mail date, then as `%Y-%m-%d %H:%M:%S`, and kept as text when it is neither. The list
  is sorted by it, newest first: the order of `fetch` is not known.
- Of `message`, only `source`, parsed for its text, its `Cc` and its attachments' names and sizes.
  An answer of `fetch` or `message` over 16 MiB is not read further. `headers`, `attachments`, `plain` and `body_url` are
  not read.
- `body_url`, the pop-out and `clear` are never asked. Nor is a production branch's build: the
  library refuses it before any request, as the page hides the tab.

## Panels

The URLs are read from the script. None needs a request: each is built from the build, the
branch and the project.

| Panel | URL | Authentication |
| --- | --- | --- |
| Shell | The tab `/project/<project_name>/branches/<branch>/shell` frames `<build url>/odoo-sh/webshell`. A build's menu links to the latter, in a new tab | The build host's own, below |
| Editor | `<build url>/odoo-sh/editor`, from the tab and a build's menu, in a new tab | The build host's own |
| Monitor | The tab `/project/<project_name>/branches/<branch>/monitor` frames `.../monitoring?theme=<theme>` on `www.odoo.sh`, `<theme>` being the `grafana_theme` cookie or `dark` | The session |

- `<branch>` is the branch's name encoded with `encodeURIComponent`. The project's name is not
  encoded.
- The three tabs are enabled when the branch's latest build is `done`, and a build's menu offers
  Web Shell and Editor for any listed build that is `done`. The Monitor tab exists for
  `production` and `staging` branches only.
- Shell and editor URLs are derived from a build's `url` and carry no token. The build host hands
  access over from the session through `/paas/build/<id>/token`: see [Hosts](upstream.md#hosts).
  They were not opened in this capture.
- The AI tab of a `dev` branch frames `<build url>/odoo-sh/webshell?ai=<ai_agent>`.
- The library builds the tab's `/monitor` URL and never asks for `.../monitoring` or follows its
  redirect, whose target names a dashboard.

The monitor page answers 302 to `/monitoring/public-dashboards/<dashboard>?project=<project_name>&branch=<branch>`,
a Grafana dashboard served by `www.odoo.sh`. Its data comes from requests whose body is a bare
`{"params": {...}}`, with no `jsonrpc` key, answered in the JSON-RPC shape with `"id": null`:

| Request | Params | `result` |
| --- | --- | --- |
| `POST /_grafana/search` | `project` (`project_name`), `branch`, `build` (`null`) | A list of one build id |
| `POST /_grafana/query/pad` | `build_id`, `start_ts`, `end_ts` (epoch milliseconds) | `data`: per period, request durations, memory, CPU, I/O, HTTP and mail counts |
| `POST /_grafana/query/pa` | Same | `data`: `size_database_avg`, `size_container_avg`, `size_toast_avg` |
| `POST /_grafana/query/global` | Same | `{"error": "no-production"}` on the staging build |
| `POST /_grafana/annotations` | Same | `annotations`, and `dashboard` with `build`, `repository`, `workers`, `stage` |

Seen once, for a two-day range, on a staging branch named `staging`: whether `branch` is the branch's
name or its stage is not known.

## Stage moves

`POST /app/branch/<id>/set_stage`, params `{"stage": "<stage>"}`, read from the script. Its
`result` is the branch, in the fields of [Branches](upstream.md#branches), which the page takes
in place of the one it holds.

- The page sends it when a branch is dragged onto a stage. It lets any branch be dragged and
  checks no access level.
- To `production`, the page refuses when the project already has a production branch: "You can
  only have one production branch per project". Whether upstream refuses too is unknown, since
  the page never asks.
- From `staging` or `production`, the page asks to confirm first: moving the production branch
  "will drop your production database and staging builds", and a staging branch's builds "are not
  backed up and will be lost forever". From `dev` it asks nothing.
- The page's "unmute" restores `push_behavior` to `new` on `dev` and `update` elsewhere, the
  values seen per stage. Whether a stage move changes it is unknown.

## Not seen

- Any write on this page, and the answer to each. The library sends payloads the page does not:
  fields of two sections in one request, a new build option without `apply_default_settings`,
  `modules` with a change of `modules_auto`, and `test_tags` with a change of `test_mode`.
- Shell and editor requests, a mail, and a pinned revision.
- The revision requests for a version past its end of life.
- The answer for a pinned revision past its `date_expiration`.
- What a user below a stage's access level gets from these requests.
