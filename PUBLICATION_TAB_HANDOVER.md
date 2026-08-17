# Handover: Replicating the Publication Program tab on another portal

Source of truth: `partner-portal/app.py` — `show_publication_program()` (~L1776)
and `get_student_publication_record()` (~L342). Reference commits: `455951b`,
`289ca51`, `23b9bcf`.

## What it shows

A trimmed-down publication status view for the student, with only:
1. **Publication Specialist card** — name + email of the student's assigned PSA.
2. **Publication Target** card — the journal/outlet they're targeting.
3. **Latest Publication Outcome** card — a friendly status message mapped from
   the raw Airtable outcome value (accepted, rejected, submitted, etc.).

Deliberately excludes workshop links, target resources, and quiz checkpoints —
those exist in the fuller `student-portal` version of this tab, but partners
(and whoever else this is being ported for) shouldn't see them.

## Data source

A **separate Airtable base** from the main student table — not the base the
rest of the portal usually reads from:

- Base ID: `appOhh4711y4cXSfj`
- Table: `Lumiere Students`
- Uses the **same `AIRTABLE_API_KEY`** as everything else (just a different base).

Fields to fetch (exact Airtable field names):
- `Student Cohort Application Tracker` — join key, format `Name | Cohort | Program`
- `Publication Specialist (Text)` — PSA name
- `Publication Specialist Email` — PSA email
- `Publication Target (text)` — target journal/outlet
- `PS: Latest Publication Outcome - (latest)` — raw outcome status

Lookup logic: take the student's own tracker string (same field name on the
main student table), split on `|`, take the first segment (the name), strip
it, and match with `FIND('{name}', {Student Cohort Application Tracker})`
against the Publication base. Take the first matching record.

Gate the tab on whichever of these is true on the main student record:
`Publication Marker == "Yes"` or `Publication Foundation Student Y/N` starts
with `"Yes"` (field names may need adjusting per portal).

## Code pattern to copy

```python
@st.cache_resource(show_spinner=False)
def get_application_table():
    return get_airtable_api().base(get_secret("PUBLICATION_BASE_ID")).table(get_secret("PUBLICATION_TABLE"))

@st.cache_data(ttl=3600, show_spinner=False)
def get_student_publication_record(tracker_value):
    if not tracker_value:
        return None
    table = get_application_table()
    name = str(tracker_value).split("|")[0].strip().replace("'", "\\'")
    records = table.all(
        formula=f"FIND('{name}', {{Student Cohort Application Tracker}})",
        fields=[
            "Student Cohort Application Tracker",
            "Publication Specialist (Text)",
            "Publication Specialist Email",
            "Publication Target (text)",
            "PS: Latest Publication Outcome - (latest)",
        ],
    )
    return records[0] if records else None
```

**Do not wrap that lookup in a bare `except Exception: return None`.** We did
that originally and it silently turned a missing/misconfigured secret into
what looked exactly like "this student has no publication record yet" —
cost real debugging time. Instead, let it raise and catch at the call site:

```python
try:
    app_record = get_student_publication_record(student.get("name", ""))
except Exception as e:
    st.error(f"Couldn't load publication data — check the PUBLICATION_BASE_ID / PUBLICATION_TABLE configuration. ({e})")
    app_record = None
app_fields = app_record["fields"] if app_record else {}
```

Then render the three cards (specialist / target / outcome) — see
`show_publication_program()` in `partner-portal/app.py` for the full HTML/CSS,
including the `OUTCOME_MESSAGES` dict that maps raw outcome strings to
friendly copy + color.

## ⚠️ Railway config — do this or it will silently fail

Secrets are read via `get_secret()`, which checks `os.environ` first, then
`.streamlit/secrets.toml`. **That file is gitignored and never deploys** —
it only exists on local dev machines. Whoever builds this locally will test
successfully against their own `secrets.toml` and then see it fail (or worse,
silently show blank data) once deployed, unless the same two variables are
*also* added directly in Railway:

1. Go to the target portal's Railway project → the service → **Variables**.
2. Add:
   - `PUBLICATION_BASE_ID` = `appOhh4711y4cXSfj`
   - `PUBLICATION_TABLE` = `Lumiere Students`
3. Confirm `AIRTABLE_API_KEY` is already set there (it should be, for the rest
   of the portal to work) — the Publication base uses the same key.
4. Railway auto-redeploys on push, which is a full container restart, so no
   extra "reboot" step is needed once the variables are saved — just make
   sure they're saved *before* or shortly after the code with this feature
   lands on `main`.

If the tab shows placeholder text ("Not yet assigned" / "No target selected
yet") after deploying, check these two variables first, before assuming it's
a data or caching issue.
