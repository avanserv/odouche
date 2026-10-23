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
| `machine_next_commit` | bool | |
| `domains` | list of str | Custom domains; one on the staging branch |
| `domain_build_production` | str | `odoo.com` |
| `domain_to_point_to` | str | The build's host on `dev`, the production host otherwise |
| `production_environment` | bool | `true` on all three stages |
| `upgrade_branch`, `upgrade_info`, `upgrade_step` | list, object, `false` | The Upgrade tab's state |

- `machine` values and their end of support are in `mappings.machine` of `get_info`: Ubuntu 18.04
  to 26.04, each with a `label`, `python_version` and `end_date`.
- The `branch_info` of a `builds` answer also carries `ai_agent`, `demo_data`, `is_ai`,
  `machine`, `odoo_branch`, `odoo_revision_id`, `test_mode`, `upgrade_step` and
  `last_build_odoo_branch`, and each build a `machine` and an `odoo_branch`, beyond the fields of
  [Builds of a branch](upstream.md#builds-of-a-branch).
- Seen once on each stage.

`POST /app/branch/<id>/set_settings`, read from the script. Its params are one section of the
tab, as form values, and its `result` is the branch's settings, which the page merges into what
it holds. The page never sends the whole tab:

| Section | Params | Stages | Sent |
| --- | --- | --- | --- |
| Behavior upon new commits | `push_behavior` | `dev`, `staging` | On change |
| New build options | `apply_default_settings`, `modules_auto`, `modules`, `test_mode`, `test_tags`, `demo_data`, `ai_agent` | `dev` | On change |
| Odoo version | `odoo_branch`, `odoo_revision_id` | All; `odoo_branch` only on `dev` | On save |
| Custom domains | `add_domain` or `delete_domain` | All | On click |
| Operating system | `machine`, `machine_next_commit` | All | On save |

- Values are strings from the form: a checkbox is `"on"` or `"off"`, a revision is its id or
  `"latest"`.
- A disabled field is left out. With `apply_default_settings` on, the other fields of its section
  are disabled, so it is sent alone.
- The page's "unmute" sends `push_behavior` alone. That a field left out keeps its value is
  inferred from it, not seen.
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

## Panels

| Panel | URL | Authentication |
| --- | --- | --- |
| Shell | The page `/project/<project_name>/branches/<branch>/shell` frames `<build url>/odoo-sh/webshell` | The build host's own, below |
| Editor | `<build url>/odoo-sh/editor`, in a new tab | The build host's own |
| Monitor | `/project/<project_name>/branches/<branch>/monitoring?theme=<theme>` on `www.odoo.sh` | The session |

- Shell and editor URLs are derived from a build's `url`, with no request, and carry no token.
  The build host hands access over from the session through `/paas/build/<id>/token`: see
  [Hosts](upstream.md#hosts). They were not opened in this capture.
- The AI tab of a `dev` branch frames `<build url>/odoo-sh/webshell?ai=<ai_agent>`.

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

- Any write on this page, and the answer to each.
- Shell and editor requests, a mail, and a pinned revision.
- What a user below a stage's access level gets from these requests.
