import os
import base64
import streamlit as st
from pyairtable import Api
from datetime import datetime, timedelta, timezone
import resend
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from streamlit_cookies_controller import CookieController


def get_secret(key, default=None):
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default


st.set_page_config(
    page_title="Partner Portal - Lumiere Education",
    page_icon="🤝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ──────────────────────────────────────────────
# Airtable
# ──────────────────────────────────────────────

BASE_ID = "appK9HemdsQBzVefU"
STUDENT_TABLE_ID = "tbl0UJnmMwlGyCFGK"
DEADLINES_TABLE_ID = "tblsGJOAHS4sIxfVr"
PROGRESS_TABLE_ID = "tblcLCcczpe2G8i1X"
PARTNER_TABLE_ID = "tbl2xFN6arJ8XhW7h"


@st.cache_resource(show_spinner=False)
def get_airtable_api():
    return Api(get_secret("AIRTABLE_API_KEY"), timeout=(10, 30), retry_strategy=False)


@st.cache_resource(show_spinner=False)
def get_partner_table():
    return get_airtable_api().base(BASE_ID).table(PARTNER_TABLE_ID)


@st.cache_resource(show_spinner=False)
def get_bd_poc_table():
    return get_airtable_api().base(BASE_ID).table("tbl22BErOHo0FLcgJ")


@st.cache_data(ttl=3600, show_spinner=False)
def get_partner_name(email):
    try:
        safe = email.strip().lower().replace("'", "\\'")
        records = get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            fields=["Partner Name"],
            max_records=1,
        )
        if records:
            return records[0]["fields"].get("Partner Name", "")
    except Exception:
        pass
    return ""


@st.cache_data(ttl=3600, show_spinner=False)
def get_partner_info(email):
    try:
        safe = email.strip().lower().replace("'", "\\'")
        records = get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            fields=["BD POC (Linked)", "Headshot (from BD POC (Linked))"],
            max_records=1,
        )
        if records:
            f = records[0]["fields"]
            headshot_url = ""
            raw_headshot = f.get("Headshot (from BD POC (Linked))", [])
            if isinstance(raw_headshot, list) and raw_headshot:
                first = raw_headshot[0]
                if isinstance(first, dict):
                    headshot_url = first.get("url", "")
            poc_name = ""
            poc_email = ""
            linked_ids = f.get("BD POC (Linked)", [])
            if linked_ids:
                poc_record = get_bd_poc_table().get(linked_ids[0])
                poc_name = poc_record["fields"].get("Name", "")
                poc_email_raw = poc_record["fields"].get("BD POC Email", "")
                poc_email = poc_email_raw[0] if isinstance(poc_email_raw, list) and poc_email_raw else (poc_email_raw or "")
            return {"bd_poc_name": poc_name, "bd_poc_email": poc_email, "bd_poc_headshot_url": headshot_url}
    except Exception:
        pass
    return {"bd_poc_name": "", "bd_poc_email": "", "bd_poc_headshot_url": ""}


@st.cache_resource(show_spinner=False)
def get_tables():
    api = get_airtable_api()
    base = api.base(BASE_ID)
    return {
        "students": base.table(STUDENT_TABLE_ID),
        "deadlines": base.table(DEADLINES_TABLE_ID),
        "progress": base.table(PROGRESS_TABLE_ID),
    }


# ──────────────────────────────────────────────
# Magic link auth
# ──────────────────────────────────────────────

def get_serializer():
    return URLSafeTimedSerializer(get_secret("MAGIC_LINK_SECRET"))


def generate_magic_token(email):
    return get_serializer().dumps(email, salt="partner-magic-link")


def verify_magic_token(token, max_age=3600):
    try:
        return get_serializer().loads(token, salt="partner-magic-link", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def generate_session_token(email):
    return get_serializer().dumps(email, salt="partner-session")


def verify_session_token(token):
    try:
        return get_serializer().loads(token, salt="partner-session", max_age=30 * 24 * 3600)
    except (SignatureExpired, BadSignature):
        return None


def send_magic_link(email):
    resend.api_key = get_secret("RESEND_API_KEY")
    token = generate_magic_token(email)
    base_url = get_secret("APP_URL", "http://localhost:8503")
    magic_link = f"{base_url}?token={token}"
    try:
        resend.Emails.send({
            "from": get_secret("FROM_EMAIL", "Partner Portal <onboarding@resend.dev>"),
            "to": [email],
            "subject": "Your Partner Portal Login Link",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #BE1E2D;">Welcome to the Lumiere Partner Portal</h2>
                <p>Click the button below to access your partner dashboard:</p>
                <p style="margin: 30px 0;">
                    <a href="{magic_link}"
                       style="background: linear-gradient(135deg, #BE1E2D 0%, #8B1520 100%);
                              color: white; padding: 12px 30px; text-decoration: none;
                              border-radius: 6px; display: inline-block;">
                        Access Partner Portal
                    </a>
                </p>
                <p style="color: #64748B; font-size: 14px;">
                    This link will expire in 1 hour.<br>
                    If you didn't request this, you can safely ignore this email.
                </p>
            </div>
            """,
        })
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False


# ──────────────────────────────────────────────
# Field mappings
# ──────────────────────────────────────────────

STUDENT_FIELDS = {
    "name":                     "Student Cohort Application Tracker",
    "student_name":             "Student Name",
    "cohort":                   "Cohort of Program",
    "areas_of_interest":        "Areas of Interest",
    "mentor_name":              "Mentor Name_Text",
    "mentor_cv":                "Mentor CV",
    "mentor_confirmation":      "Mentor Confirmation",
    "mentor_university":        "University of PhD/Last Degree (text)",
    "participation_decision":   "Written Confirmation/Participation Decision",
    "interview_invitation_sent":"OB: Interview Invitation Sent",
    "interview_invitation_date":"OB: Date of Interview Invitation Sent",
    "deposit_paid":             "OB: Deposit Paid",
    "full_tuition_paid":        "OB: Full Tuition Paid",
    "financial_aid":            "Financial Aid Allocation",
    "mentor_outreach_date":     "OB: Mentor Outreach date (for automations)",
    "interview_notes":          "Interview Notes For The Mentor",
    "confirmed_launched":       "Student Confirmed & Launched",
    "partner_id":               "Stacker ID (Partner)",
    # Progress tracker + meeting summary
    "expected_meetings":        "Number of Expected Meetings - Student/Mentor",
    "completed_meetings":       "[Current + Archived] No. of Meetings Completed",
    "hours_recorded":           "[Current + Archived] No. of Hours Recorded",
    "student_no_shows":         "[Current + Archived] No. of Student No Shows in Mentor Meetings",
    "most_recent_meeting_mentor":"Most Recent Meeting Mentor",
    "revised_final_paper_due":  "PM: Student's Revised Final Paper - Due date",
    "revised_final_paper_upload": "Revised Final Paper upload (from Mentor-Student Progress Up Date)",
    "submission_portal":        "Student Submission Portal Lookup",
}

DEADLINE_FIELDS = {
    "name":           "Deadline Name",
    "type":           "Deadline Type",
    "due_date":       "Due Date (in use, updated to reflect student's timeline)",
    "status":         "Deadline Status",
    "date_submitted": "Date Submitted",
}

SUBMISSION_FIELDS = [
    "Research Question",
    "Research Proposal",
    "Research Outline",
    "First Draft",
]


# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────

st.markdown("""
<style>
    .info-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
    }
    .status-badge-green {
        background-color: #ECFDF5; color: #065F46;
        padding: 0.2rem 0.65rem; border-radius: 20px;
        font-size: 0.8rem; font-weight: 500; display: inline-block;
    }
    .status-badge-yellow {
        background-color: #FFFBEB; color: #92400E;
        padding: 0.2rem 0.65rem; border-radius: 20px;
        font-size: 0.8rem; font-weight: 500; display: inline-block;
    }
    .status-badge-red {
        background-color: #FEF2F2; color: #991B1B;
        padding: 0.2rem 0.65rem; border-radius: 20px;
        font-size: 0.8rem; font-weight: 500; display: inline-block;
    }
    .status-badge-gray {
        background-color: #F8FAFC; color: #64748B;
        padding: 0.2rem 0.65rem; border-radius: 20px;
        font-size: 0.8rem; font-weight: 500; display: inline-block;
    }
    /* Dark navy sidebar */
    [data-testid="stSidebar"] { background-color: #1A1A2E; color: #FFFFFF; }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label { color: #FFFFFF !important; }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.2); }
    [data-testid="stSidebar"] .stButton button {
        background-color: rgba(255,255,255,0.1);
        color: #FFFFFF !important;
        border: 1px solid rgba(255,255,255,0.3);
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background-color: rgba(255,255,255,0.2);
    }
    [data-testid="stSidebar"] .stRadio > div { gap: 0.25rem !important; }
    [data-testid="stSidebar"] .stRadio > div > label {
        background-color: transparent !important;
        border-radius: 6px !important;
        padding: 0.6rem 1rem !important;
        margin: 0 !important;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    [data-testid="stSidebar"] .stRadio > div > label:hover {
        background-color: rgba(255,255,255,0.1) !important;
    }
    [data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
        background-color: rgba(255,255,255,0.15) !important;
        border-left: 3px solid #DC1E35 !important;
    }
    [data-testid="stSidebar"] .stRadio > div > label > div:first-child {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────

for _key, _default in [
    ("authenticated", False),
    ("partner_email", None),
    ("partner_name", ""),
    ("students", []),
    ("selected_student", None),
    ("is_preview", False),
    ("magic_link_sent", False),
    ("team_unlocked", False),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default

cookies = CookieController()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def unwrap(val, default=""):
    if isinstance(val, list):
        return val[0] if val else default
    return val if val is not None else default


def clean_field(val, default=""):
    """Safely render any Airtable field value as a plain string.

    - Lists of Airtable record IDs (e.g. ['recXXX']) → default (unusable without a lookup)
    - Lists of text values (multi-select, lookup text) → comma-joined string
    - Scalar → string as-is
    """
    if val is None:
        return default
    if isinstance(val, list):
        if not val:
            return default
        # Airtable record IDs start with 'rec' and are 17 chars — discard them
        if all(isinstance(v, str) and v.startswith("rec") and len(v) >= 14 for v in val):
            return default
        return ", ".join(str(v) for v in val if v is not None and str(v).strip())
    return str(val) if val else default


def format_date(date_str):
    if not date_str:
        return "Not set"
    if isinstance(date_str, list):
        date_str = date_str[0] if date_str else ""
    if not date_str:
        return "Not set"
    try:
        date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
        day = date_obj.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{date_obj.strftime('%B')} {day}{suffix}, {date_obj.year}"
    except Exception:
        return str(date_str)


def format_duration(value):
    if not value and value != 0:
        return "N/A"
    if isinstance(value, str):
        return value if value else "N/A"
    try:
        total_seconds = int(value)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}:{minutes:02d}"
    except (ValueError, TypeError):
        return str(value)


def is_overdue(due_date_str, status):
    if status in ("Submitted", "Deadline Waived"):
        return False
    if not due_date_str:
        return False
    try:
        return datetime.strptime(due_date_str, "%Y-%m-%d") < datetime.now()
    except Exception:
        return False


def fb(label, value_html):
    """Render a labelled field block for use inside an info-card grid."""
    return (
        f'<div style="margin-bottom:0.25rem;">'
        f'<div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;'
        f'letter-spacing:0.05em;margin-bottom:0.3rem;">{label}</div>'
        f'<div style="font-size:0.95rem;color:#1A1A2E;font-weight:500;">{value_html or "—"}</div>'
        f'</div>'
    )


# ──────────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────────

def _build_student(record):
    f = record["fields"]
    raw_partner = f.get(STUDENT_FIELDS["partner_id"], [])
    partner_emails = raw_partner if isinstance(raw_partner, list) else ([raw_partner] if raw_partner else [])
    partner_emails = [e.strip().lower() for e in partner_emails if e]

    name = f.get(STUDENT_FIELDS["name"], "")
    name_parts = [p.strip() for p in name.split("|")]

    # Cohort is a linked record field — record IDs are unusable, so fall back to
    # parsing the cohort segment out of the "Name | Cohort | Program" tracker field.
    raw_cohort = clean_field(f.get(STUDENT_FIELDS["cohort"], ""))
    cohort = raw_cohort or (name_parts[1] if len(name_parts) > 1 else "")

    return {
        "id": record["id"],
        "name":                      name,
        "student_name":              clean_field(f.get(STUDENT_FIELDS["student_name"], "")),
        "cohort":                    cohort,
        "areas_of_interest":         clean_field(f.get(STUDENT_FIELDS["areas_of_interest"], "")),
        "mentor_name":               clean_field(f.get(STUDENT_FIELDS["mentor_name"], "")),
        "mentor_cv":                 f.get(STUDENT_FIELDS["mentor_cv"], []),
        "mentor_confirmation":       clean_field(f.get(STUDENT_FIELDS["mentor_confirmation"], "")),
        "mentor_university":         clean_field(f.get(STUDENT_FIELDS["mentor_university"], "")),
        "participation_decision":    clean_field(f.get(STUDENT_FIELDS["participation_decision"], "")),
        "interview_invitation_sent": clean_field(f.get(STUDENT_FIELDS["interview_invitation_sent"], "")),
        "interview_invitation_date": unwrap(f.get(STUDENT_FIELDS["interview_invitation_date"], "")),
        "deposit_paid":              clean_field(f.get(STUDENT_FIELDS["deposit_paid"], "")),
        "full_tuition_paid":         clean_field(f.get(STUDENT_FIELDS["full_tuition_paid"], "")),
        "financial_aid":             clean_field(f.get(STUDENT_FIELDS["financial_aid"], "")),
        "mentor_outreach_date":      unwrap(f.get(STUDENT_FIELDS["mentor_outreach_date"], "")),
        "interview_notes":           clean_field(f.get(STUDENT_FIELDS["interview_notes"], "")),
        "confirmed_launched":        clean_field(f.get(STUDENT_FIELDS["confirmed_launched"], "")),
        "partner_emails":            partner_emails,
        "expected_meetings":         f.get(STUDENT_FIELDS["expected_meetings"], 0),
        "completed_meetings":        f.get(STUDENT_FIELDS["completed_meetings"], 0),
        "hours_recorded":            f.get(STUDENT_FIELDS["hours_recorded"], ""),
        "student_no_shows":          unwrap(f.get(STUDENT_FIELDS["student_no_shows"], 0), default=0),
        "most_recent_meeting_mentor":unwrap(f.get(STUDENT_FIELDS["most_recent_meeting_mentor"], "")),
        "revised_final_paper_due":    unwrap(f.get(STUDENT_FIELDS["revised_final_paper_due"], "")),
        "revised_final_paper_upload": f.get(STUDENT_FIELDS["revised_final_paper_upload"], []),
        "submission_portal":          unwrap(f.get(STUDENT_FIELDS["submission_portal"], "")),
    }


@st.cache_data(ttl=300, show_spinner=False)
def get_students_for_partner(partner_email):
    tables = get_tables()
    try:
        safe = partner_email.lower().replace("'", "\\'")
        formula = f"FIND('{safe}', LOWER(ARRAYJOIN({{Stacker ID (Partner)}}, ',')))"
        records = tables["students"].all(formula=formula)
        return [_build_student(r) for r in records]
    except Exception as e:
        st.error(f"Error fetching students: {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_onboarding_students(partner_email):
    tables = get_tables()
    try:
        safe = partner_email.lower().replace("'", "\\'")
        formula = (
            f"AND("
            f"FIND('{safe}', LOWER(ARRAYJOIN({{Stacker ID (Partner)}}, ','))), "
            f"{{Student Confirmed & Launched}} = ''"
            f")"
        )
        records = tables["students"].all(formula=formula)
        return [_build_student(r) for r in records]
    except Exception as e:
        st.error(f"Error fetching onboarding students: {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_program_students(partner_email):
    tables = get_tables()
    try:
        safe = partner_email.lower().replace("'", "\\'")
        formula = (
            f"AND("
            f"FIND('{safe}', LOWER(ARRAYJOIN({{Stacker ID (Partner)}}, ','))), "
            f"{{Student Confirmed & Launched}} = 'Yes'"
            f")"
        )
        records = tables["students"].all(formula=formula)
        return [_build_student(r) for r in records]
    except Exception as e:
        st.error(f"Error fetching program students: {e}")
        return []


DEADLINE_FETCH_FIELDS = [
    "Deadline Name",
    "Student Application & Cohort Tracker",
    "Deadline Type",
    "Due Date (in use, updated to reflect student's timeline)",
    "Deadline Status",
    "Date Submitted",
] + SUBMISSION_FIELDS


@st.cache_data(ttl=300, show_spinner=False)
def get_deadlines_for_student(student_id, student_name):
    tables = get_tables()
    try:
        name_part = student_name.split("|")[0].strip().replace("'", "\\'")
        formula = f"FIND('{name_part}', {{Deadline Name}})"
        raw = tables["deadlines"].all(formula=formula, fields=DEADLINE_FETCH_FIELDS)
        records = [
            r for r in raw
            if student_id in r["fields"].get("Student Application & Cohort Tracker", [])
        ]
        deadlines = []
        for record in records:
            f = record["fields"]
            submissions = {field: f[field] for field in SUBMISSION_FIELDS if f.get(field)}
            # Date Submitted is a lookup — unwrap array if needed
            date_submitted = f.get(DEADLINE_FIELDS["date_submitted"], "")
            if isinstance(date_submitted, list):
                date_submitted = date_submitted[0] if date_submitted else ""
            deadlines.append({
                "id": record["id"],
                "name": f.get(DEADLINE_FIELDS["name"], ""),
                "type": f.get(DEADLINE_FIELDS["type"], ""),
                "due_date": f.get(DEADLINE_FIELDS["due_date"], ""),
                "status": f.get(DEADLINE_FIELDS["status"], ""),
                "date_submitted": date_submitted,
                "submissions": submissions,
            })
        deadlines.sort(key=lambda x: x["due_date"] or "9999-99-99")
        return deadlines
    except Exception as e:
        st.error(f"Error fetching deadlines: {e}")
        return []


def _fuzzy_get(fields: dict, keyword: str, default=""):
    """Case-insensitive substring match against field names.
    Returns the value of the first field whose name contains `keyword`."""
    kw = keyword.lower()
    for key, val in fields.items():
        if kw in key.lower():
            return val
    return default


@st.cache_data(ttl=300, show_spinner=False)
def get_meeting_notes_for_student(student_name):
    if not student_name:
        return []
    tables = get_tables()
    try:
        name_part = student_name.split("|")[0].strip().replace("'", "\\'")
        formula = (
            f"AND(FIND('{name_part}', {{Mentor Student Meeting Key}}), "
            f"{{Type of Record}} = 'Mentor Update')"
        )
        records = tables["progress"].all(formula=formula)
        notes = [
            {
                "date":  _fuzzy_get(r["fields"], "date of meeting"),
                "notes": _fuzzy_get(r["fields"], "meeting notes between"),
            }
            for r in records
        ]
        notes.sort(key=lambda x: x["date"] or "0000-00-00", reverse=True)
        return notes
    except Exception as e:
        st.error(f"Error fetching meeting notes: {e}")
        return []


# ──────────────────────────────────────────────
# Auth flow
# ──────────────────────────────────────────────

def check_session_cookie():
    if st.session_state.authenticated:
        return
    try:
        token = cookies.get("partner_session")
    except TypeError:
        return
    if token:
        email = verify_session_token(token)
        if email:
            with st.spinner("Loading your portal..."):
                students = get_students_for_partner(email)
            if students:
                st.session_state.authenticated = True
                st.session_state.partner_email = email
                st.session_state.partner_name = get_partner_name(email)
                st.session_state.students = students
                st.session_state.is_preview = False
                st.rerun()
        else:
            cookies.remove("partner_session")


def check_magic_link_token():
    if "token" not in st.query_params or st.session_state.authenticated:
        return
    token = st.query_params["token"]
    email = verify_magic_token(token)
    if email:
        with st.spinner("Loading your portal..."):
            students = get_students_for_partner(email)
        if students:
            st.session_state.authenticated = True
            st.session_state.partner_email = email
            st.session_state.partner_name = get_partner_name(email)
            st.session_state.students = students
            st.session_state.is_preview = False
            st.session_state.pending_session_cookie = email
            st.query_params.clear()
            st.rerun()
        else:
            st.error("No students found for this partner email. Please contact the Lumiere team.")
            st.query_params.clear()
    else:
        st.error("This login link has expired or is invalid. Please request a new one.")
        st.query_params.clear()


# ──────────────────────────────────────────────
# Login page
# ──────────────────────────────────────────────

def show_login_page():
    st.markdown("""
    <style>
        .stApp { background-color: #1A1A2E; }
        #MainMenu, header, footer { visibility: hidden; }
        .block-container { padding-top: 10vh !important; max-width: 100% !important; }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) {
            background: white !important;
            border-radius: 16px !important;
            padding: 2.5rem !important;
            box-shadow: 0 20px 60px rgba(0,0,0,0.4) !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) p,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) label,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) span {
            color: #1A1A2E !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) input {
            border: 1px solid #CBD5E1 !important;
            border-radius: 8px !important;
            color: #1A1A2E !important;
            background: white !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) input::placeholder {
            color: #94A3B8 !important;
        }
        [data-testid="stFormSubmitButton"] > button, .stButton > button {
            background-color: #DC1E35 !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
        }
        [data-testid="stFormSubmitButton"] > button:hover, .stButton > button:hover {
            background-color: #B01829 !important;
        }
        [data-testid="stFormSubmitButton"] > button p, .stButton > button p { color: white !important; }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) hr {
            border-color: #E2E8F0 !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) details {
            background: #F8FAFC !important;
            border: 1px solid #CBD5E1 !important;
            border-radius: 8px !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) details summary,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) details summary * {
            color: #1A1A2E !important;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with open("assets/logo.png", "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<div style="text-align:center;margin-bottom:0.5rem;">'
            f'<img src="data:image/png;base64,{logo_b64}" width="220"></div>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<h2 style="text-align:center;color:#1A1A2E;font-size:1.5rem;font-weight:700;margin:0.5rem 0 0.25rem;">Partner Portal</h2>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<p style="text-align:center;color:#94A3B8;font-size:0.82rem;margin-bottom:1.5rem;line-height:1.5;">'
            'Track your students\' onboarding progress and program status.</p>',
            unsafe_allow_html=True
        )

        if st.session_state.magic_link_sent:
            st.success("Check your email! We've sent you a magic link to access the portal.")
            st.info("The link will expire in 1 hour.")
            if st.button("Send another link"):
                st.session_state.magic_link_sent = False
                st.rerun()
        else:
            st.markdown(
                '<p style="font-size:0.75rem;font-weight:600;letter-spacing:0.08em;color:#64748B;'
                'margin-bottom:0.25rem;text-transform:uppercase;">EMAIL ADDRESS</p>',
                unsafe_allow_html=True
            )
            st.markdown(
                '<p style="font-size:0.8rem;color:#94A3B8;margin-bottom:0.5rem;">'
                'Enter the email address registered with Lumiere Education.</p>',
                unsafe_allow_html=True
            )
            with st.form("login_form"):
                email_input = st.text_input(
                    "Email", label_visibility="collapsed", placeholder="your.email@example.com"
                )
                if st.form_submit_button("Send Magic Link", use_container_width=True):
                    if email_input:
                        clean_email = email_input.strip().lower()
                        with st.spinner("Looking up your account..."):
                            students = get_students_for_partner(clean_email)
                        if students:
                            if send_magic_link(clean_email):
                                st.session_state.magic_link_sent = True
                                st.rerun()
                        else:
                            st.error("No account found for this email. Please contact the Lumiere team.")

        st.markdown("---")
        if st.session_state.team_unlocked:
            st.markdown("#### Admin Preview Mode")
            st.caption("Preview any partner's portal view")
            with st.form("preview_form"):
                preview_email = st.text_input("Partner Email", placeholder="Enter partner email to preview")
                if st.form_submit_button("Preview as Partner", use_container_width=True):
                    if preview_email:
                        with st.spinner("Looking up partner..."):
                            students = get_students_for_partner(preview_email.strip().lower())
                        if students:
                            st.session_state.authenticated = True
                            st.session_state.partner_email = preview_email.strip().lower()
                            st.session_state.partner_name = get_partner_name(preview_email.strip().lower())
                            st.session_state.students = students
                            st.session_state.is_preview = True
                            st.rerun()
                        else:
                            st.error("No students found for this partner email.")
        else:
            with st.expander("Team Access"):
                st.markdown(
                    '<p style="font-size:0.8rem;color:#64748B;margin-bottom:0.75rem;">'
                    'For Lumiere team members only. Enter your admin key to preview the portal as any partner.</p>',
                    unsafe_allow_html=True
                )
                with st.form("team_unlock_form"):
                    admin_key = st.text_input("Admin Key", type="password", placeholder="Enter admin key")
                    if st.form_submit_button("Unlock", use_container_width=True):
                        if admin_key == get_secret("ADMIN_KEY"):
                            st.session_state.team_unlocked = True
                            st.rerun()
                        else:
                            st.error("Invalid admin key.")


# ──────────────────────────────────────────────
# Student profile tabs
# ──────────────────────────────────────────────

def show_applicant_onboarding(student):
    name_parts = [p.strip() for p in student["name"].split("|")]
    display_name = name_parts[0]
    program = name_parts[2] if len(name_parts) > 2 else ""
    cohort = student.get("cohort") or (name_parts[1] if len(name_parts) > 1 else "")

    # Student overview
    st.markdown("#### Student Details")
    st.markdown(
        '<div class="info-card">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.25rem;">'
        + fb("Student Name", display_name)
        + fb("Program", program)
        + fb("Cohort", cohort)
        + fb("Areas of Interest", student.get("areas_of_interest"))
        + '</div></div>',
        unsafe_allow_html=True
    )

    # Payment / participation status
    st.markdown("#### Application Status")
    st.markdown(
        '<div class="info-card">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.25rem;">'
        + fb("Participation Decision", student.get("participation_decision"))
        + fb("Has the student paid the deposit?", student.get("deposit_paid"))
        + fb("Has the student paid full tuition?", student.get("full_tuition_paid"))
        + fb("Financial Aid Allocation", student.get("financial_aid"))
        + fb("Interview Invitation Sent", student.get("interview_invitation_sent"))
        + '</div></div>',
        unsafe_allow_html=True
    )

    # Key dates
    st.markdown(
        '<div class="info-card">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.25rem;">'
        + fb("Date Interview Conducted", format_date(student.get("interview_invitation_date")))
        + fb("Date of Mentor Outreach", format_date(student.get("mentor_outreach_date")))
        + '</div></div>',
        unsafe_allow_html=True
    )

    # Proposed mentor
    cv_raw = student.get("mentor_cv")
    if isinstance(cv_raw, list) and cv_raw:
        cv_html = " ".join(
            f'<a href="{a.get("url","")}" target="_blank" '
            f'style="color:#BE1E2D;text-decoration:none;">{a.get("filename","Download CV")}</a>'
            for a in cv_raw if a.get("url")
        ) or "—"
    else:
        cv_html = "—"

    st.markdown(
        '<div class="info-card">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.25rem;">'
        + fb("Proposed mentor's name", student.get("mentor_name") or "Not yet assigned")
        + fb("Proposed mentor's university", student.get("mentor_university"))
        + fb("Proposed mentor's CV", cv_html)
        + '</div></div>',
        unsafe_allow_html=True
    )

    # Mentor confirmation + interview notes side by side
    confirmation = student.get("mentor_confirmation") or ""
    if confirmation.strip().lower() == "yes":
        conf_html = '<span style="background:#DBEAFE;color:#1D4ED8;padding:0.2rem 0.75rem;border-radius:20px;font-size:0.9rem;font-weight:600;display:inline-block;">Yes</span>'
    elif confirmation.strip():
        conf_html = f'<span style="background:#FEF3C7;color:#92400E;padding:0.2rem 0.75rem;border-radius:20px;font-size:0.9rem;font-weight:600;display:inline-block;">{confirmation}</span>'
    else:
        conf_html = "—"

    notes = student.get("interview_notes") or ""
    notes_clean = notes.strip()
    notes_html = (
        f'<div style="font-size:0.92rem;color:#475569;line-height:1.6;white-space:pre-wrap;">{notes_clean}</div>'
        if notes_clean and notes_clean not in ("-----",) else
        '<span style="color:#94A3B8;">—</span>'
    )

    st.markdown(
        '<div class="info-card">'
        '<div style="display:grid;grid-template-columns:1fr 2fr;gap:1.5rem;">'
        + fb("Has mentor confirmed the match?", conf_html)
        + fb("Summary of notes from student interview", notes_html)
        + '</div></div>',
        unsafe_allow_html=True
    )


def _render_submission_value(value, label=None):
    label_html = (
        f'<span style="font-size:0.78rem;font-weight:600;color:#94A3B8;text-transform:uppercase;'
        f'letter-spacing:0.05em;display:block;margin-bottom:0.4rem;">{label}</span>'
        if label else ""
    )

    def bubble(content_html):
        return (
            f'<div style="display:inline-flex;align-items:center;gap:0.5rem;'
            f'background:#F1F5F9;border:1px solid #E2E8F0;border-radius:999px;'
            f'padding:0.4rem 0.9rem;font-size:0.88rem;color:#1E293B;margin-top:0.25rem;">'
            f'📄 {content_html}</div>'
        )

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                url = item.get("url", "")
                filename = item.get("filename", "Download")
                if url:
                    content = f'<a href="{url}" target="_blank" style="color:#BE1E2D;font-weight:600;text-decoration:none;">{filename}</a>'
                    st.markdown(f'{label_html}{bubble(content)}', unsafe_allow_html=True)
                    label_html = ""
            else:
                st.markdown(f'{label_html}{bubble(str(item))}', unsafe_allow_html=True)
                label_html = ""
    elif isinstance(value, str):
        content = f'<a href="{value}" target="_blank" style="color:#BE1E2D;font-weight:600;text-decoration:none;">View Submission</a>' if value.startswith("http") else value
        st.markdown(f'{label_html}{bubble(content)}', unsafe_allow_html=True)
    elif value is not None:
        st.markdown(f'{label_html}{bubble(str(value))}', unsafe_allow_html=True)


def show_progress_tracker(student):
    EXCLUDED_TYPES = {"Syllabus", "Evaluation & Feedback"}
    all_deadlines = get_deadlines_for_student(student["id"], student["name"])
    deadlines = [d for d in all_deadlines if d.get("type") not in EXCLUDED_TYPES]


    submission_portal = student.get("submission_portal") or ""
    if submission_portal:
        st.markdown(f"""
        <div class="info-card" style="display:flex;align-items:center;justify-content:space-between;
                                      flex-wrap:wrap;gap:0.75rem;margin-bottom:0.5rem;">
            <div>
                <div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;
                            letter-spacing:0.05em;margin-bottom:0.3rem;">Submission Portal</div>
                <div style="font-size:0.9rem;color:#475569;">Student submissions are collected through this form.</div>
            </div>
            <a href="{submission_portal}" target="_blank"
               style="background:#BE1E2D;color:white;text-decoration:none;
                      padding:0.5rem 1.1rem;border-radius:7px;font-size:0.88rem;font-weight:600;white-space:nowrap;">
                Open Portal →
            </a>
        </div>
        """, unsafe_allow_html=True)

    if not deadlines:
        st.info("No deadlines found for this student yet.")
        return

    total = len(deadlines)
    submitted_count = sum(1 for d in deadlines if d["status"] == "Submitted")
    waived_count = sum(1 for d in deadlines if d["status"] == "Deadline Waived")
    overdue_count = sum(1 for d in deadlines if is_overdue(d["due_date"], d["status"]))
    pending_count = total - submitted_count - waived_count - overdue_count

    # Summary dots
    summary_dots = [
        ("#16A34A", f"{submitted_count} Submitted"),
        ("#F59E0B", f"{pending_count} Pending"),
        ("#EF4444", f"{overdue_count} Overdue"),
    ]
    if waived_count:
        summary_dots.append(("#6366F1", f"{waived_count} Waived"))
    dots_html = "".join(
        f'<div style="display:flex;align-items:center;gap:0.4rem;">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:{color};display:inline-block;"></span>'
        f'<span style="font-size:0.9rem;color:#475569;">{label}</span></div>'
        for color, label in summary_dots
    )
    st.markdown(
        f'<div style="display:flex;gap:1.5rem;margin-bottom:1.25rem;flex-wrap:wrap;">{dots_html}</div>',
        unsafe_allow_html=True,
    )

    # Overdue + next deadline banners
    try:
        now = datetime.now()
        actionable = [d for d in deadlines if d["status"] not in ("Submitted", "Deadline Waived") and d["due_date"]]
        overdue_dl = [d for d in actionable if datetime.strptime(d["due_date"], "%Y-%m-%d") < now]
        future_dl = [d for d in actionable if datetime.strptime(d["due_date"], "%Y-%m-%d") >= now]
        if overdue_dl:
            overdue_list = ", ".join(f"{d['type']} ({format_date(d['due_date'])})" for d in overdue_dl)
            st.markdown(
                f'<div style="background:rgba(239,68,68,0.1);border:1px solid #EF4444;'
                f'border-radius:10px;padding:1rem;margin-bottom:0.75rem;">'
                f'<strong>⚠️ Overdue:</strong> {overdue_list}</div>',
                unsafe_allow_html=True,
            )
        if future_dl:
            next_dl = future_dl[0]
            days_left = (datetime.strptime(next_dl["due_date"], "%Y-%m-%d") - now).days
            st.markdown(
                f'<div style="background:rgba(220,30,53,0.1);border:1px solid #DC1E35;'
                f'border-radius:10px;padding:1rem;margin-bottom:1rem;">'
                f'<strong>⏰ Next Deadline:</strong> {next_dl["type"]} — '
                f'due {format_date(next_dl["due_date"])} ({days_left} day{"s" if days_left != 1 else ""} away)'
                f'</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    active_deadlines = [d for d in deadlines if d["status"] not in ("Submitted", "Deadline Waived")]
    waived_deadlines = [d for d in deadlines if d["status"] == "Deadline Waived"]
    submitted_deadlines = [d for d in deadlines if d["status"] == "Submitted"]

    def _render_deadline_row(dl):
        dtype = dl["type"] or "Deadline"
        status = dl["status"]
        overdue = is_overdue(dl["due_date"], status)
        is_waived = status == "Deadline Waived"

        if status == "Submitted":
            icon = "✅"
        elif is_waived:
            icon = "〇"
        elif overdue:
            icon = "⚠️"
        else:
            icon = "📅"

        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.markdown(f"{icon} **{dtype}**")
        with col2:
            st.markdown("**Due:** —" if is_waived else f"**Due:** {format_date(dl['due_date'])}")
        with col3:
            if status == "Submitted":
                submitted_label = f"Submitted {format_date(dl['date_submitted'])}" if dl.get("date_submitted") else "Submitted"
                st.success(submitted_label)
            elif is_waived:
                st.markdown(
                    '<span style="display:inline-block;background:#EEF2FF;color:#4F46E5;'
                    'padding:0.25rem 0.75rem;border-radius:20px;font-size:0.85rem;font-weight:500;">'
                    'Deadline Waived</span>',
                    unsafe_allow_html=True,
                )
            elif overdue:
                st.error("Overdue")
            else:
                st.warning("Not Submitted")

        if dl.get("submissions"):
            for field_name, value in dl["submissions"].items():
                _render_submission_value(value, label="Submission")

    for dl in active_deadlines + waived_deadlines:
        _render_deadline_row(dl)
        st.markdown("---")

    if submitted_deadlines:
        st.markdown(
            '<div style="margin-top:2.5rem;margin-bottom:1.25rem;padding-top:1.5rem;border-top:2px solid #E2E8F0;">'
            '<span style="font-size:1rem;font-weight:600;color:#64748B;">Submitted Deliverables</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        rfp_upload = student.get("revised_final_paper_upload")
        for i, dl in enumerate(submitted_deadlines):
            _render_deadline_row(dl)
            # Skip the trailing separator on the last row if the RFP upload follows
            last = (i == len(submitted_deadlines) - 1)
            if not (last and rfp_upload):
                st.markdown("---")

    # Revised Final Paper upload lives on the student record, not the deadlines table
    rfp_upload = student.get("revised_final_paper_upload")
    if rfp_upload:
        _render_submission_value(rfp_upload, label="Submission")
        st.markdown("---")


def show_meeting_summary(student):
    completed = student.get("completed_meetings", 0) or 0
    expected = student.get("expected_meetings", 0) or 0

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown("**📊 Meetings Completed**")
        if expected > 0:
            st.progress(min(completed / expected, 1.0))
            st.caption(f"{completed} of {expected} completed")
        else:
            st.markdown("No meetings scheduled")
    with col2:
        st.markdown("**📋 Required Meetings for Program**")
        st.markdown(str(expected))
    with col3:
        st.markdown("**⏱️ Hours Recorded**")
        st.markdown(format_duration(student.get("hours_recorded", "")))
    with col4:
        st.markdown("**🚫 Number of Student No Shows**")
        st.markdown(str(student.get("student_no_shows", 0) or 0))
    with col5:
        st.markdown("**🧑‍🏫 Date of most recent meeting with mentor**")
        raw_date = student.get("most_recent_meeting_mentor", "") or ""
        st.markdown(format_date(raw_date) if raw_date else "—")

    st.markdown("---")
    st.markdown("### Meeting Notes with Student")

    notes = get_meeting_notes_for_student(student.get("name", ""))
    if not notes:
        st.info("No meeting notes found for this student.")
    else:
        for note in notes:
            date_str = format_date(note["date"]) if note["date"] else "No date"
            with st.expander(f"📅 {date_str}"):
                st.markdown(note["notes"] or "No notes recorded.")


# ──────────────────────────────────────────────
# Student profile (3 tabs)
# ──────────────────────────────────────────────

def show_student_profile(student):
    if st.button("← Back to list", key="back_btn"):
        st.session_state.selected_student = None
        st.rerun()

    name_parts = [p.strip() for p in student["name"].split("|")]
    display_name = name_parts[0]
    header_sub = " · ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    st.markdown(
        f'<div style="margin-bottom:1.25rem;padding-bottom:0.75rem;border-bottom:1px solid #E2E8F0;">'
        f'<div style="font-size:1.5rem;font-weight:700;color:#1E293B;line-height:1.2;">{display_name}</div>'
        + (f'<div style="font-size:0.85rem;color:#94A3B8;margin-top:0.3rem;">{header_sub}</div>' if header_sub else "")
        + '</div>',
        unsafe_allow_html=True
    )

    is_launched = str(student.get("confirmed_launched") or "").strip().lower() == "yes"

    if is_launched:
        tab1, tab2, tab3 = st.tabs([
            "📋 Applicant Onboarding",
            "📅 Progress Tracker",
            "🤝 Mentor Meeting Summary",
        ])
        with tab1:
            show_applicant_onboarding(student)
        with tab2:
            show_progress_tracker(student)
        with tab3:
            show_meeting_summary(student)
    else:
        show_applicant_onboarding(student)


# ──────────────────────────────────────────────
# Student list
# ──────────────────────────────────────────────

def render_student_list(students, page_label):
    if not students:
        st.info(f"No students in the {page_label} yet.")
        return

    # Header row
    st.markdown(
        '<div style="display:grid;grid-template-columns:2.5fr 2fr 2fr 0.8fr;gap:0.5rem;'
        'padding:0.4rem 1rem;margin-bottom:0.25rem;">'
        '<div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;">Student</div>'
        '<div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;">Cohort · Program</div>'
        '<div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;">Mentor</div>'
        '<div></div>'
        '</div>',
        unsafe_allow_html=True
    )

    for s in students:
        name_parts = [p.strip() for p in s["name"].split("|")]
        display_name = name_parts[0]
        cohort = name_parts[1] if len(name_parts) > 1 else ""
        program = name_parts[2] if len(name_parts) > 2 else ""
        cohort_program = " · ".join(filter(None, [cohort, program]))
        mentor = s.get("mentor_name") or "Not yet assigned"

        col_name, col_cohort, col_mentor, col_btn = st.columns([2.5, 2, 2, 0.8])
        with col_name:
            st.markdown(f"**{display_name}**")
        with col_cohort:
            st.caption(cohort_program)
        with col_mentor:
            st.caption(mentor)
        with col_btn:
            if st.button("View →", key=f"view_{s['id']}"):
                st.session_state.selected_student = s
                st.rerun()
        st.markdown('<hr style="margin:0.3rem 0;border-color:#F1F5F9;">', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────

def show_dashboard():
    partner_email = st.session_state.partner_email
    with st.spinner("Loading students..."):
        onboarding = get_onboarding_students(partner_email)
        in_program = get_program_students(partner_email)

    with st.sidebar:
        with open("assets/logo_symbol.png", "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<div style="margin-bottom:0.75rem;">'
            f'<img src="data:image/png;base64,{logo_b64}" width="60"></div>',
            unsafe_allow_html=True
        )
        st.markdown("### Lumiere Partner Portal")
        if st.session_state.partner_name:
            st.markdown(
                f'<p style="color:#FFFFFF;font-size:1rem;font-weight:600;margin-top:-0.4rem;margin-bottom:0.1rem;">'
                f'{st.session_state.partner_name}</p>',
                unsafe_allow_html=True
            )
        st.markdown(
            f'<p style="color:#94A3B8;font-size:0.8rem;margin-top:0;">'
            f'{st.session_state.partner_email}</p>',
            unsafe_allow_html=True
        )
        if st.session_state.is_preview:
            st.warning("Preview Mode")
        st.markdown("---")

        view = st.radio(
            "Navigation",
            [
                f"Onboarding Tracker  ({len(onboarding)})",
                f"Program Tracker  ({len(in_program)})",
            ],
            label_visibility="collapsed",
        )

        st.markdown("---")
        if st.button("Refresh Data"):
            st.cache_data.clear()
            st.session_state.students = get_students_for_partner(st.session_state.partner_email)
            st.session_state.selected_student = None
            st.rerun()
        if st.button("Logout"):
            try:
                if cookies.get("partner_session"):
                    cookies.remove("partner_session")
            except Exception:
                pass
            st.session_state.update({
                "authenticated": False,
                "partner_email": None,
                "partner_name": "",
                "students": [],
                "selected_student": None,
                "is_preview": False,
            })
            st.rerun()

    if st.session_state.is_preview:
        st.markdown(
            f'<div style="background:#FFFBEB;border:1px solid #F59E0B;border-radius:8px;'
            f'padding:0.75rem 1rem;margin-bottom:1rem;color:#92400E;">'
            f'<strong>Preview Mode:</strong> Viewing portal as {st.session_state.partner_email}</div>',
            unsafe_allow_html=True
        )

    # If a student profile is open, show it instead of the list
    if st.session_state.selected_student:
        show_student_profile(st.session_state.selected_student)
        return

    partner_name = st.session_state.partner_name
    if partner_name:
        st.markdown(
            f'<div style="font-size:1.6rem;font-weight:700;color:#1E293B;margin-bottom:0.75rem;">'
            f'Welcome, {partner_name}</div>',
            unsafe_allow_html=True
        )

    info = get_partner_info(st.session_state.partner_email)
    poc_name = info.get("bd_poc_name", "")
    poc_email = info.get("bd_poc_email", "")
    poc_headshot = info.get("bd_poc_headshot_url", "")


    def render_poc_card():
        headline = (
            f"I'm {poc_name}, your Partnerships Manager at Lumiere Education."
            if poc_name else "Your Partnerships Manager at Lumiere Education."
        )
        email_html = (
            f'<a href="mailto:{poc_email}" style="font-size:0.82rem;color:#BE1E2D;text-decoration:none;">{poc_email}</a>'
            if poc_email else ""
        )
        headshot_html = (
            f'<img src="{poc_headshot}" style="width:80px;height:80px;border-radius:50%;'
            f'object-fit:cover;border:3px solid #E2E8F0;flex-shrink:0;">'
            if poc_headshot else
            '<div style="width:80px;height:80px;border-radius:50%;background:#F1F5F9;'
            'flex-shrink:0;display:flex;align-items:center;justify-content:center;'
            'font-size:2rem;color:#94A3B8;">👤</div>'
        )
        st.markdown(
            f'<div style="background:white;border-radius:12px;padding:1.25rem 1.5rem;'
            f'box-shadow:0 2px 8px rgba(0,0,0,0.08);margin-bottom:1.25rem;'
            f'display:flex;align-items:center;gap:1.25rem;">'
            f'{headshot_html}'
            f'<div>'
            f'<div style="font-size:0.68rem;font-weight:700;color:#BE1E2D;text-transform:uppercase;'
            f'letter-spacing:0.08em;margin-bottom:0.35rem;">Your Partnerships Manager</div>'
            f'<div style="font-size:0.98rem;font-weight:700;color:#1A1A2E;line-height:1.35;margin-bottom:0.3rem;">'
            f'{headline}</div>'
            f'<div style="font-size:0.82rem;color:#64748B;line-height:1.45;margin-bottom:0.3rem;">'
            f'I\'m here to support your partnership with Lumiere. Reach out anytime with questions about your students or our programs.</div>'
            f'{email_html}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    if "Onboarding" in view:
        col_main, col_poc = st.columns([3, 1.2])
        with col_poc:
            render_poc_card()
        with col_main:
            st.markdown("### Onboarding Tracker")
            st.markdown("""
            <div style="background:#F8F9FA;border-left:4px solid #BE1E2D;border-radius:6px;
                        padding:0.85rem 1rem;margin-bottom:1.25rem;color:#475569;font-size:0.92rem;line-height:1.55;">
                These are your students who are currently moving through the onboarding pipeline — they have
                applied and are working through pre-program steps such as mentor matching, interview scheduling,
                and payment confirmation. Click into any student to view their onboarding status, payment
                details, and mentor assignment progress.
            </div>
            """, unsafe_allow_html=True)
            ob_names = sorted(set(s["name"].split("|")[0].strip() for s in onboarding))
            selected_ob = st.selectbox(
                "Search student", options=["All students"] + ob_names,
                key="search_onboarding", label_visibility="collapsed",
            )
            filtered_onboarding = onboarding if selected_ob == "All students" else [
                s for s in onboarding if s["name"].split("|")[0].strip() == selected_ob
            ]
            render_student_list(filtered_onboarding, "Onboarding Tracker")
    else:
        col_main, col_poc = st.columns([3, 1.2])
        with col_poc:
            render_poc_card()
        with col_main:
            st.markdown("### Program Tracker")
            st.markdown("""
            <div style="background:#F8F9FA;border-left:4px solid #BE1E2D;border-radius:6px;
                        padding:0.85rem 1rem;margin-bottom:1.25rem;color:#475569;font-size:0.92rem;line-height:1.55;">
                These are your students who are actively enrolled and working through the program. Use this page
                to track each student's progress against their deadlines and submissions, and to review notes
                from their mentor sessions.
            </div>
            """, unsafe_allow_html=True)
            prog_names = sorted(set(s["name"].split("|")[0].strip() for s in in_program))
            selected_prog = st.selectbox(
                "Search student", options=["All students"] + prog_names,
                key="search_program", label_visibility="collapsed",
            )
            filtered_program = in_program if selected_prog == "All students" else [
                s for s in in_program if s["name"].split("|")[0].strip() == selected_prog
            ]
            render_student_list(filtered_program, "Program Tracker")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

check_session_cookie()
check_magic_link_token()

if "pending_session_cookie" in st.session_state and st.session_state.pending_session_cookie:
    token = generate_session_token(st.session_state.pending_session_cookie)
    cookies.set("partner_session", token, max_age=30 * 24 * 3600)
    st.session_state.pending_session_cookie = None

if not st.session_state.authenticated:
    show_login_page()
else:
    show_dashboard()
