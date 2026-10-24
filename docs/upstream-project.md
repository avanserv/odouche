# Upstream project administration

What a project's overview, audit log, settings and members use, captured on 2026-10-23 on one
project with three members. The requests follow the [common shape](upstream.md#common-shape)
and the [identifiers](upstream.md#identifiers) of the upstream reference. Values are scrubbed as
there.

Changing a member's role was captured. Every other write on this page was read from the page's
script (`paas_master.paas_app_assets`), not captured: saving settings, adding and removing a
member.

## Access

The page shows the project's Audit Logs and Settings to an `admin` only, and its Branches,
Builds and Status to a `developer` and above. Levels are those of `access_level_map` in the
`config` of `get_info` (`project_info.json`). What upstream answers a user below them was not
seen.

## Overview

No request is a project overview. The project's Status page (`POST /app/project/<technical_name>/status`,
read from the script) is the platform's own: each server's roles, whether they are online, and
probe percentages. It says nothing about the project.

The figures of an overview are in the `repository` of the project's [settings](#project-settings).
Sizes are in KiB.

| Figure | Fields | Also in |
| --- | --- | --- |
| Subscription | `subscription_validity` (`valid`), `subscription_code`, `subscription_recurrence` (`1`), `subscription_next_invoice` (a date) | `subscription_validity` and `subscription_code` in `get_info`; `subscription_validity` in `projects` |
| What it pays for | `subscription_workers`, `subscription_stagings`, `subscription_storage`, `subscription_dedicated` | |
| Odoo version | `odoo_branch` (`19.0`) | `projects`, `get_info` |
| Region | `geolocation` (`eu`), `hosting_location` and `hosting_location_dev` (`Europe`) | `projects` gives `geolocation` as `Europe` |
| Storage | `used_storage`, `max_storage` (1048576, one GiB), `max_GB`, `production_build_size`, `size_staging`, `size_others` | |
| Workers | `max_production_workers`, `max_staging_branches`, `pays_dedicated` | `pays_dedicated` in `get_info` |

`production_build` of the same answer splits the production size into `size_container`,
`size_database`, `size_custom_branch` and `size_total`, with its `worker_url` and `branch_id`.

`Client.project_overview` reads what the project page and its Settings page send, read from the
script on 2026-10-24 from the capture of 2026-10-23: the project page asks `get_info` then
`branches`, the Settings page `get_info` then `get_settings`. The region comes from `projects`,
which answers it to every member.

| Request | Read |
| --- | --- |
| `get_info` | `active_repo`: `id`, `owner`, `name`, `project_name`, `technical_name`, `subscription_validity`, `odoo_branch`, `pays_dedicated`, `production_expiration_days_left` (`null` seen), `production_build_id` (`id`, `branch_name`, `url`, or `false`); `user.access`; `config.access_level_map` |
| `projects` | The listed project's `geolocation` (`Europe`) |
| `branches` | Each branch's `stage`, `last_build_id`, `last_build_status` and `last_build_result` |
| `get_settings` | `repository`: `used_storage`, `max_storage`, `max_production_workers`, `max_staging_branches` |

- The page shows Settings when `access_level_map[user.access] >= access_level_map["admin"]`. The
  library applies the same test before asking `get_settings`.
- `subscription_validity`: `valid` was seen. The templates also name `trial` ("Trial"), `custom`
  ("Non-standard") and `invalid` ("Expired"). The project page shows "Invalid Subscription" for
  any other value.
- The page's "Total accounted storage" is `production_build.size_total * 4 + size_staging`, which
  equalled `used_storage` in the one capture. `used_storage` is also the least the storage input
  accepts.
- `production_expiration_days_left` is the days left of a trial given by a partnership code.
- `get_info` holds `access_token`, `subscription_code` and the production build's
  `enterprise_code` (only `false` seen). `projects` holds each project's `subscription_code`.
  `get_settings` holds `ci_token`, the GitHub token for commit statuses (only `false` seen; the
  page tests it for truth only), `subscription_code` and `subscription_code_display`. The library
  drops them before reading.

## Audit log

`POST /app/project/<technical_name>/audit_logs`, no params. Fixture: `audit_logs.json`.

`result` is a list, newest first, with no paging: 47 entries going back 25 days. The page says it
shows the last 30 days.

| Field | Type | Observed |
| --- | --- | --- |
| `date` | str | UTC |
| `action` | str | `Allow IP`, `Connect as user`, `Download database`, `Manage collaborators`, `Open Editor`, `Open Shell`, `Open Webmail`, `Open database logs` |
| `stage` | str | `production`, `staging`, `dev`, or empty for a project action |
| `user` | str | The GitHub login of who did it |
| `message` | str | Free text, often empty; holds IP addresses, logins and SSH client versions |
| `successful` | bool | `true`; the page shows it only when the project `is_staff_restricted` |

- A role change is logged as "Change access rights of user `<login>` from `<old>` to `<new>`".
- The page asks once, in `onWillStart`, and its `SearchTable` pages the rows itself, 25 a screen,
  sorted by `date` descending.
- The CSV export also holds `Change branch stage`, `Add domain name` and `Manage settings`, which
  the 30 days of JSON did not.
- `GET .../audit_logs/download/csv` and `.../download/xls` give up to a year, as attachments named
  `audit_log_<project_name>`. The CSV columns are `Date`, `Github User`, `Repository`
  (`<owner>/<name>`), `Stage`, `Database`, `Action` and `Extra Information`. Its dates were two
  hours ahead of the JSON's, which matches the zone of the `tz` cookie.

Seen once.

`Client.audit_log` asks `get_info`, applies the page's admin test to it, then asks `audit_logs`
once and reads every field above but none of the exports. It sorts the entries by `date` itself,
as the page does.

## Project settings

`POST /app/project/<technical_name>/get_settings`, no params. Fixture: `project_settings.json`,
which leaves out the upsell links and the limits' descriptions.

| Key of `result` | Holds |
| --- | --- |
| `repository` | The settings, and the [overview](#overview) figures |
| `users` | The [members](#members) |
| `production_build` | Its sizes, above |
| `submodules` | Private submodules: `id`, `deploy_key_public`, `deploy_key_public_fingerprint`. Empty here |
| `dedicated_limits` | `limit_real_time` and `limit_real_time_cron`, each with `value` in minutes and bounds in seconds |
| `session_lifetime`, `session_lifetime_map` | `auto`, and the choices from `4-hours` to `8-days` with their `seconds` |
| `domain_build_production`, `title`, `dedicated`, `upsells` | |

The other settings in `repository` are the development defaults (`modules_auto`, `modules`,
`test_mode`, `test_tags`, `demo_data`, `ai_agent`, as on a [branch](upstream-branches.md#branch-and-build-settings)),
`disable_tests`, `private`, `block_odoo_domain`, `deploy_key_writable`, `ip_whitelist`,
`ci_token`, `ci_suspended` and `project_name`.

`POST /app/project/<technical_name>/set_settings`, read from the script. As on a branch, its
params are one section of the page as form values, and its `result` is the new `repository`.

| Section | Params | Touches access |
| --- | --- | --- |
| Project name | `project_name`, `block_odoo_domain` | No |
| Session lifetime | `session_lifetime`, a slider's position in `session_lifetime_map` (`"0"` is `auto`) | Yes: how long any member's session lasts on the project |
| Public access | `public` | Yes: opens the Builds page and the development builds to anyone |
| GitHub commit statuses | `ci_token` or `reset_ci_token` | A GitHub token |
| GitHub key and webhook | `deploy_key_writable`, `redeploy_key`, `redeploy_webhook` | Yes: the deploy key's write access to the repository |
| Production database size | `max_storage` | No; billed |
| Database workers | `max_production_workers`, `pays_dedicated` | No; billed |
| Workers settings | `limit_real_time`, `limit_real_time_cron` | No |
| Staging branches | `max_staging_branches` | No; billed |
| Development branches | The development defaults | No |
| Firewall | `ip_whitelist` | Yes: SSH, and PostgreSQL on a dedicated server, to production and staging |
| Activation | `subscription_code` | No; billed |

- `ip_whitelist` is IPv4 addresses, one per line, at most 10, applied within 5 minutes.
- A `result` with `new_sub_values` is a subscription change waiting for confirmation, which the
  page asks for and then sends again with `code_upsell_confirm`. The page also confirms a raise
  of a billed field before sending.
- Collaborators, submodules (`create_submodule_deploy_key`), and the limits'
  `reset_default_limits` have requests of their own.

## Members

The members are `users` of [`get_settings`](#project-settings). Fixture: `project_settings.json`.

| Field | Type | Observed |
| --- | --- | --- |
| `id` | int | The membership: what a role change and a removal name |
| `username`, `name` | str | The GitHub login, twice |
| `hosting_identifier` | str | The GitHub user id |
| `avatar_url` | str | |
| `access_level` | str | `admin` for all three |
| `user_id` | `[id, name]` or `false` | `false` shows "Pending login" (script) |
| `hosting_user_id` | `[id, name]` | Named as the `hosting_user_id` of [Projects](upstream.md#projects); the two were not compared |

Roles, lowest first, from `access_level_map`: `developer` (100), `tester` (200), `admin` (300).

`POST /app/user_access/<id>/set_access_level`, params `{"access_level": "<role>"}`. Fixture:
`set_access_level.json`. The answer has no `result` key, as a [rebuild](upstream.md#rebuild).
Captured on one member, from `admin` to `tester`, `developer` and back to `admin`, and each change
was in the audit log.

Adding a member, read from the script apart from the search:

1. `POST /app/github/find_users`, params `{"query": "<text>"}`, searches GitHub as the user types.
   `result` is GitHub's own user objects (`login`, `id`, `avatar_url`, `html_url`, `name`, ...).
2. `POST /app/github/get_user_profile`, params `{"github_username": "<login>"}`.
3. `POST /app/project/<technical_name>/add_collaborator`, params `github_username`,
   `access_level` (the page offers `developer`, the default, `tester` and `admin`) and
   `send_invitation`. Its `result` is the new member, which the page adds to `users`.

A new member is named by their GitHub login.

`find_users` needs Odoo.sh's GitHub grant to have the `repo` scope, beyond the
`read:user user:email` of [login](upstream.md#login-flow). Without it the answer is
`InsufficientScopeError` (fixture `insufficient_scope.json`), whose `arguments` hold a GitHub
authorize URL asking for `read:user user:email repo`. Following it ran the login's hops again and
set a new `session_id`.

Removing a member: `POST /app/user/<hosting_user_id>/revokable_count` gives how many of the
user's projects they can be removed from, and `POST /app/user_access/<id>/revoke`, params
`{"all_projects": <bool>}`, removes them. Its `result` is `true` when the user removed themselves.

## Not seen

- A settings save, an added or removed member, and their answers.
- The project Status answer.
- What a member below `admin` gets from these requests.
