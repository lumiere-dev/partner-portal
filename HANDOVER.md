# Partner Portal — Handover Document

Last updated: 2026-08-03 (patch)

## What this is

A Streamlit web app that lets Lumiere Education's external partners (sponsors of
students) log in and track the onboarding and program progress of *their*
sponsored students, plus (for some partners) a referral/commission tracker —
without giving them direct Airtable access.

It's modelled on two sibling apps: `student-portal` and `mentor-portal`. All
three share the same magic-link auth + 30-day session cookie pattern. If you're
handed one of the sibling repos, expect very similar structure.

## Stack

- **Streamlit** (single-file app, `app.py`, ~2,450 lines)
- **pyairtable** — reads/writes to Airtable (the system of record; this app is
  read-mostly)
- **resend** — sends magic-link emails
- **itsdangerous** — signs magic-link and session tokens
- **extra-streamlit-components** — cookie manager (`stx.CookieManager`) for the
  30-day "remember me" session cookie. Replaced `streamlit-cookies-controller`
  in commit `8f4f158` because of login/cookie flow bugs — don't switch back
  without checking that history.

Run locally:
```
python -m streamlit run app.py --server.port 8503
```

Deployed on **Railway** (see `Procfile`: `streamlit run app.py --server.port
$PORT ...`). Railway free/sleep tier can cold-start slowly — commit `70da7ee`
fixed an Airtable lookup timeout caused by this, so if partners report slow
first-loads after idle periods, that's expected Railway sleep behavior, not a
regression.

**If lookups hang indefinitely instead of timing out** (e.g. partner preview
stuck on "loading" forever, not just slow): `pyairtable`'s `Api(timeout=...)`
is silently ignored by the installed version, so a stalled connection could
hang forever even though a `ThreadPoolExecutor` timeout guard wrapped the
call — because exiting the `with` block called `shutdown(wait=True)`, which
itself blocks until the hung thread finishes. Fixed in `f8cad94`
(2026-07-09) by mounting a real socket-level timeout via a custom
`requests.adapters.HTTPAdapter` (`_TimeoutHTTPAdapter`, ~L70) on
`get_airtable_api()`'s session, and switching the executor cleanup to
`shutdown(wait=False)`. If you add new Airtable calls wrapped in an
executor, follow this same pattern rather than the old blocking one.

## Auth flow

1. Partner enters their email on the login page.
2. `_partner_exists(email)` checks the email is a known `Partner Email ID
   (For Partner Portal Login)` value in Airtable.
3. If found, a magic link (signed token via `itsdangerous`, 1-hour expiry) is
   emailed via Resend.
4. Clicking the link calls `check_magic_link_token()`, which authenticates and
   sets a 30-day session cookie (`partner_session`) for persistent login.
5. `check_session_cookie()` runs on every page load to restore auth from the
   cookie.

**Admin/team preview mode:** a "Team Access" expander on the login page takes
an `ADMIN_KEY` (env var/secret). Once unlocked, staff can enter any partner's
email and view the portal as that partner (`is_preview = True`, shown with a
banner). This is for Lumiere team members debugging or demoing a partner's
view — not partner-facing.

## Airtable structure

Base: `appK9HemdsQBzVefU`

| Table | ID | Purpose |
|---|---|---|
| Student/Onboarding | `tbl0UJnmMwlGyCFGK` | Main student records — onboarding + program status |
| Deadlines | `tblsGJOAHS4sIxfVr` | Per-student deadlines |
| Progress/Meeting notes | `tblcLCcczpe2G8i1X` | Mentor meeting notes, keyed by `Mentor Student Meeting Key` |
| Partner | `tbl2xFN6arJ8XhW7h` | Partner directory — name lookup, commission rate |
| Referral | `tbldyQSNWYdTGjZGm` | Referral/commission tracker records |
| Cohort | `tblOUDtK8E5VIrQCb` | Cohort names |
| Program Type | `tblJ5CHN2rN4gR27d` | Program type names |

A second base, `appL9DZMKT2AaOuLI` (table `tblTf5LD6gQNdDlXn`), holds the
**BD POC lookup** (Business Development point-of-contact — the "Partnerships
Manager" card shown on the dashboard).

### Field quirks worth knowing before you touch anything

- **Partner auth match, on the Student table**: `partner_id` /
  `get_students_for_partner()` match against `Partner Email ID (For Partner
  Portal Login)` (a lookup array field, via `ARRAYJOIN`). This field was
  renamed from `Stacker ID (Partner)` — fixed in `155a32c` (2026-07-10). If
  logins/student-lists silently return empty again, check whether Airtable
  renamed it a second time.
- **Partner auth match, on the Partner table** (separate field!): every
  Partner-table lookup (`_partner_exists`, `get_partner_name`,
  `get_partner_info`, `get_bd_poc_details`, `get_partner_record_id`,
  `partner_has_commission`, `get_partner_application_link`) filters on
  `Partner Portal Log-In Email`. This was renamed from `Stacker log-in
  Email` — fixed in `30bc0f6` (2026-07-10), same day as the Student-table
  rename above but a genuinely different field on a different table. Both
  had to be fixed separately; a rename of one does not imply the other.
  When login breaks with "Could not reach the database," check both fields
  before assuming it's a timeout issue.
- **Onboarding vs Program split**: `Student Confirmed & Launched` empty =
  still onboarding; `"Yes"` = shows in Program Tracker instead.
- **Partner name lookup**: `Partner Portal Log-In Email` (see above) →
  `Partner Name`. Easy to typo.
- **Meeting notes**: match on `Mentor Student Meeting Key` (must equal the
  *full* tracker value, not a substring) AND `Type of Record = 'Mentor
  Update'`. Date field is `Date of Meeting` (capital M — inconsistent with
  other date fields).
- **`Cohort of Program`** is a linked-record field that returns record IDs,
  not names. Where that lookup isn't reliable, the code falls back to
  parsing cohort/program out of the combined `Student Cohort Application
  Tracker` field, which is formatted as `Name | Cohort | Program`.
- **`Areas of Interest`** is a multi-select; always pass it through the
  `clean_field()` helper (handles lists/linked records → display string).
- **Referral Tracker fields** are referenced by **field ID**, not name (see
  `REFERRAL_FIELD_IDS` dict in `app.py`), because commit `4b9f01b` found
  name-based lookups fragile. If Airtable fields get renamed again (this has
  happened before — see "Fix interview field names after Airtable rename"
  and "Fix Referral Tracker..." commits), field IDs are more stable but a
  field can still be *deleted/recreated* with a new ID, so re-verify IDs via
  Airtable's API/UI if referral data looks wrong.
- Referral Tracker tab only appears if `partner_has_commission(email)` is
  true (commission rate lookup) — don't assume all partners have it.
- **Personalised application link banner** (`6c6b729`, 2026-07-15): shown at
  the top of the Onboarding and Program Tracker tabs via
  `render_application_link_banner()`. Looks up the partner's `Record ID
  (from source base)` on the Partner table, then cross-references it into
  the second base (`appL9DZMKT2AaOuLI` / BD POC table) to pull `Referral
  Source Prefilled Application Link (Lumiere)`. Deliberately hidden (returns
  `""`) when that same lookup's `White Label Partner` field is `"Yes"` —
  white-label partners shouldn't be pointed at Lumiere's own application
  form. Cached 1hr via `@st.cache_data(ttl=3600)`.
- **Discontinued-student flagging** (`b86bde3`, 2026-07-21):
  `_discontinued_label()` (~L2131) centralizes "is this student no longer
  progressing" logic — checks `final_decision` (`Final Application Decision
  - Lumiere Side [OB]`) for `"rejected"`, `participation_decision` for
  `"no"`, and `status_in_program` for `Suspended`/`Withdrawn`. Renders a red
  banner on the student detail Applicant Onboarding tab. On the Onboarding
  Tracker list row (`render_student_list`, ~L2172) it renders as a rounded
  pill badge (light red background/border, `#B91C1C` text, `font-size:
  0.85rem`) rather than plain colored text — restyled twice more in
  `32f0bed`/`2201ba7` (2026-07-24) after the initial plain-text version and
  then a size bump. This replaced an earlier version that only checked
  `status_in_program` — if you need to add another "stalled" reason, extend
  this function rather than re-checking status fields ad hoc elsewhere.

**General rule**: any Airtable field that might come back as a list or linked
record should go through `clean_field()` / `unwrap()` before being rendered.

## Config / secrets

Secrets are read via `get_secret()` (checks `os.environ` first, then
`st.secrets`), so the same code works with Railway env vars in production and
`.streamlit/secrets.toml` locally (gitignored — never commit it).

Required secrets:
- `AIRTABLE_API_KEY`
- `MAGIC_LINK_SECRET` — signing key for magic links/session tokens
- `RESEND_API_KEY`
- `FROM_EMAIL`
- `APP_URL` — must match the deployed URL (used to build magic link URLs),
  **must include the `https://` scheme**. On 2026-08-03 a partner's magic
  link button was invisible in Chrome/Gmail and unclickable in Safari
  because `APP_URL` was set to a bare domain (no scheme) — mail clients
  strip/mis-resolve schemeless hrefs. Fixed the secret value, and
  `send_magic_link` (`6a99760`) now also defensively prepends `https://` if
  a future `APP_URL` value is missing a scheme, plus the button markup was
  changed from a CSS-gradient/`inline-block` anchor to a table-based button
  with solid-color fallback and a plain-text link backup (more resilient
  across mail clients generally).
- `ADMIN_KEY` — team preview unlock passphrase

`.streamlit/secrets.toml` locally has a comment "Copy from student-portal and
update APP_URL" — the sibling portals share the same Airtable API key and
Resend setup, just different `APP_URL`/`MAGIC_LINK_SECRET`.

## Analytics (Umami)

Website ID `4e48a4fa-cc54-4835-ada3-c242f4fec0ec`. Unlike the Mentor Portal
(which tracks all visits, even pre-auth), **the Partner Portal tracks nothing
until after login** — the Umami script (`_inject_umami()`) is only injected
once `authenticated = True`, and `data-auto-track="false"` is set so no
automatic pageview fires before the explicit post-login track. Admin preview
sessions are currently included in tracking (for testing) — worth revisiting
if preview traffic starts polluting partner analytics.

If you change anything about login timing/flow, check that a login event
still fires exactly once per session (`login_tracked` session-state flag
guards against double-firing) — this broke once already (`d2dfad2`, `691fa5a`).

## Code map (`app.py`, single file, ~2,450 lines — line numbers approximate,
drift each time someone edits; re-grep `^def ` if precision matters)

- **L1–68**: imports, `get_secret`, page config, Airtable base/table/field ID
  constants (incl. `BD_LOOKUP_BASE_ID`/`BD_LOOKUP_TABLE_ID`, L42–43).
- **L70–370**: Airtable accessors — `_TimeoutHTTPAdapter` (L70, see cold-start
  section above), `get_airtable_api`, partner lookup (`_partner_exists`,
  `get_partner_name`, `get_partner_info`), BD POC lookup
  (`get_bd_poc_details`), `get_partner_application_link` (L277, powers the
  application-link banner), table getters, referral/commission lookups,
  magic-link/session token generation.
- **L372–588**: `send_magic_link`, `STUDENT_FIELDS` dict (L437), Umami
  injection/tracking helpers.
- **L590–967**: field-cleaning helpers (`unwrap`, `clean_field`,
  `format_date`, etc.), data-fetching for students/deadlines/meetings, and
  `render_application_link_banner` (L945).
- **L968–1016**: referral data building/fetching.
- **L1017–1215**: `check_session_cookie`, `check_magic_link_token`,
  `show_login_page` (incl. admin preview unlock).
- **L1216–1714**: student profile tabs — Applicant Onboarding (incl. the
  rejected/withdrawn banner, see below), Progress Tracker, Meeting Summary.
- **L1715–1993**: Referral Tracker page.
- **L1994–2145**: student profile shell, onboarding-stage HTML,
  `_discontinued_label` (L2131, see below), student list rendering.
- **L2146–2445**: dashboard shell (sidebar nav, logout, BD POC card),
  Onboarding/Program tracker views with search/filter, entry point routing
  between login page and dashboard.

There's no router/framework — page state lives in `st.session_state`
(`selected_student`, radio nav value, etc.) and the file just branches at the
bottom.

## Known rough edges / things to watch

- Single-file architecture (2,450+ lines) — no tests. Changes should be
  smoke-tested manually (`streamlit run`) since there's no CI/test suite to
  catch regressions.
- Airtable field renames have broken this app multiple times (interview
  fields, referral fields, and — twice in the same week, 2026-07-10 — both
  the Student-table and Partner-table login-email fields). When Airtable
  owners rename/restructure fields, expect a fix-up commit here, and check
  *all* tables referencing the old name, not just the first one you find.
- Railway cold-start latency is a recurring source of "portal is slow/broken"
  reports that are actually just sleep/wake behavior, not bugs.
- `ADMIN_KEY` is a shared static passphrase, not per-user — anyone with it can
  preview as *any* partner. Treat it like a shared secret, not a login.

## Where to look next

- Sibling apps for shared patterns: `C:\Users\Thoma\student-portal`,
  `C:\Users\Thoma\mentor-portal`.
- `git log --oneline` for the fuller history of Airtable field churn and past
  bugfixes — many commit messages are self-explanatory postmortems.
