import os
import base64
import concurrent.futures
import streamlit as st
import streamlit.components.v1 as components
from pyairtable import Api
from datetime import datetime, timedelta, timezone
import resend
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import extra_streamlit_components as stx


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
PARTNER_TABLE_ID  = "tbl2xFN6arJ8XhW7h"
REFERRAL_TABLE_ID = "tbldyQSNWYdTGjZGm"

BD_LOOKUP_BASE_ID  = "appL9DZMKT2AaOuLI"
BD_LOOKUP_TABLE_ID = "tblTf5LD6gQNdDlXn"

REFERRAL_PARTNER_EMAIL_FIELD = "fldbCOFBOLNAkMxPB"  # email field on partner table
REFERRAL_PARTNER_ID_FIELD   = "fldM15JJzzBDYrWPB"  # partner record ID field on referral table
COHORT_TABLE_ID             = "tblOUDtK8E5VIrQCb"
PROGRAM_TYPE_TABLE_ID       = "tblJ5CHN2rN4gR27d"

REFERRAL_FIELD_IDS = {
    "name":              "fldy1UHT8zqKMqBws",
    "cohort":            "fldgvoVprkWDnn2nZ",
    "admission":         "fldhxbgvJAzyynp1G",
    "program_type":      "fldJVeR1a3MoKTi2n",
    "discount":          "fldQDrfIyTctMEs8J",
    "original_tuition":  "fldVlSDhjP8G6EOze",
    "final_tuition":     "fldqfXSLimXv7VZ0V",
    "net_paid":          "fld0DzHKVxsawKUj6",
    "payment_method":    "fldy65URdlOKQfssp",
    "net_received":      "fldUVHZb5tcpp0w9Y",
    "commission_pct":    "fldwCzoFuqfmpFAqA",
    "commission_amount": "fld7pXPidqV1u2HnK",
    "payment_status":    "fldFhG7A4isfjXvmg",
    "payment_date":      "fldAMow8hzbTSQgiv",
    "finance_notes":     "fldTvKPwWkkQ7t8wu",
    "partnership_notes": "fldgQukcyvBdAjQ4b",
}


@st.cache_resource(show_spinner=False)
def get_airtable_api():
    return Api(get_secret("AIRTABLE_API_KEY"), timeout=15, retry_strategy=False)


@st.cache_resource(show_spinner=False)
def get_partner_table():
    return get_airtable_api().base(BASE_ID).table(PARTNER_TABLE_ID)


@st.cache_resource(show_spinner=False)
def get_bd_poc_table():
    return get_airtable_api().base(BASE_ID).table("tbl22BErOHo0FLcgJ")




@st.cache_data(ttl=3600, show_spinner=False)
def get_staff_name(record_id):
    try:
        record = get_bd_poc_table().get(record_id)
        return record["fields"].get("Name", "")
    except Exception:
        return ""


@st.cache_data(ttl=300, show_spinner=False)
def _partner_exists(email):
    safe = email.strip().lower().replace("'", "\\'")
    def _call():
        return get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            fields=["Stacker log-in Email"],
            max_records=1,
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        records = executor.submit(_call).result(timeout=20)
    return bool(records)


@st.cache_data(ttl=3600, show_spinner=False)
def get_partner_name(email):
    try:
        safe = email.strip().lower().replace("'", "\\'")
        def _call():
            return get_partner_table().all(
                formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
                fields=["Partner Name"],
                max_records=1,
            )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            records = executor.submit(_call).result(timeout=20)
        if records:
            return records[0]["fields"].get("Partner Name", "")
    except Exception:
        pass
    return ""


def _unwrap_str(val):
    if isinstance(val, list):
        return val[0] if val and isinstance(val[0], str) else ""
    return val or ""


@st.cache_data(ttl=3600, show_spinner=False)
def get_partner_info(email):
    _empty = {"bd_poc_name": "", "bd_poc_headshot_url": "", "bd_poc_calendly": "", "bd_poc_bio": "", "bd_poc_email": ""}
    try:
        safe = email.strip().lower().replace("'", "\\'")
        partner_records = get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            max_records=1,
        )
        if not partner_records:
            return _empty
        partner_record_id = partner_records[0]["id"]

        bd_table = get_airtable_api().base(BD_LOOKUP_BASE_ID).table(BD_LOOKUP_TABLE_ID)
        lookup_records = bd_table.all(
            formula=f"{{Record ID}} = '{partner_record_id}'",
            max_records=1,
        )
        if not lookup_records:
            return _empty

        f = lookup_records[0]["fields"]

        # Name: linked record field returns record IDs; display name is the primary field value
        name_raw = f.get("Lumiere BD POC (Linked)", [])
        poc_name = ""
        if isinstance(name_raw, list) and name_raw:
            first = name_raw[0]
            poc_name = first if isinstance(first, str) and not first.startswith("rec") else ""
        elif isinstance(name_raw, str):
            poc_name = name_raw

        # Headshot — attachment field returns list of dicts with a "url" key
        headshot_url = ""
        raw_headshot = f.get("Headshot (from Lumiere BD POC (Linked))", [])
        if isinstance(raw_headshot, list) and raw_headshot:
            first = raw_headshot[0]
            headshot_url = first.get("url", "") if isinstance(first, dict) else (first if isinstance(first, str) else "")

        poc_calendly = _unwrap_str(f.get("Calendly Link_BD (from Lumiere BD POC (Linked))", ""))
        poc_bio      = _unwrap_str(f.get("Facts about PM (from Lumiere BD POC (Linked))", ""))
        poc_email    = _unwrap_str(f.get("Staff Email (from Lumiere BD POC (Linked))", ""))

        return {
            "bd_poc_name":         poc_name,
            "bd_poc_headshot_url": headshot_url,
            "bd_poc_calendly":     poc_calendly,
            "bd_poc_bio":          poc_bio,
            "bd_poc_email":        poc_email,
        }
    except Exception as e:
        st.warning(f"BD POC lookup failed: {e}")
    return _empty


@st.cache_data(ttl=3600, show_spinner=False)
def get_bd_poc_details(email):
    _empty = {"bd_poc_name": "", "bd_poc_headshot_url": "", "bd_poc_calendly": "", "bd_poc_bio": "", "bd_poc_email": ""}
    try:
        safe = email.strip().lower().replace("'", "\\'")
        partner_records = get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            max_records=1,
        )
        if not partner_records:
            return _empty
        source_record_id = _unwrap_str(partner_records[0]["fields"].get("Record ID (from source base)", ""))
        if not source_record_id:
            return _empty

        bd_table = get_airtable_api().base(BD_LOOKUP_BASE_ID).table(BD_LOOKUP_TABLE_ID)
        formula = f"{{Record ID}} = '{source_record_id}'"

        # Fetch attachment + lookup fields in default format
        lookup_records = bd_table.all(
            formula=formula,
            fields=[
                "Staff Email (from Lumiere BD POC (Linked))",
                "Headshot (from Lumiere BD POC (Linked))",
                "Facts about PM (from Lumiere BD POC (Linked))",
                "Calendly Link_BD (from Lumiere BD POC (Linked))",
            ],
            max_records=1,
        )
        if not lookup_records:
            return _empty

        # Linked record fields return IDs in default format; use cell_format="string" to get the display name
        name_records = bd_table.all(
            formula=formula,
            fields=["Lumiere BD POC (Linked)"],
            cell_format="string",
            user_locale="en-us",
            time_zone="America/New_York",
            max_records=1,
        )
        poc_name = _unwrap_str(name_records[0]["fields"].get("Lumiere BD POC (Linked)", "")) if name_records else ""

        f = lookup_records[0]["fields"]

        headshot_url = ""
        raw_headshot = f.get("Headshot (from Lumiere BD POC (Linked))", [])
        if isinstance(raw_headshot, list) and raw_headshot:
            first = raw_headshot[0]
            headshot_url = first.get("url", "") if isinstance(first, dict) else (first if isinstance(first, str) else "")

        return {
            "bd_poc_name":         poc_name,
            "bd_poc_headshot_url": headshot_url,
            "bd_poc_calendly":     _unwrap_str(f.get("Calendly Link_BD (from Lumiere BD POC (Linked))", "")),
            "bd_poc_bio":          _unwrap_str(f.get("Facts about PM (from Lumiere BD POC (Linked))", "")),
            "bd_poc_email":        _unwrap_str(f.get("Staff Email (from Lumiere BD POC (Linked))", "")),
        }
    except Exception as e:
        st.warning(f"BD POC lookup failed: {e}")
    return _empty


@st.cache_resource(show_spinner=False)
def get_tables():
    api = get_airtable_api()
    base = api.base(BASE_ID)
    return {
        "students":  base.table(STUDENT_TABLE_ID),
        "deadlines": base.table(DEADLINES_TABLE_ID),
        "progress":  base.table(PROGRESS_TABLE_ID),
    }


@st.cache_resource(show_spinner=False)
def get_referral_table():
    return get_airtable_api().base(BASE_ID).table(REFERRAL_TABLE_ID)


@st.cache_data(ttl=3600, show_spinner=False)
def get_partner_record_id(email):
    try:
        safe = email.strip().lower().replace("'", "\\'")
        records = get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            fields=["Stacker log-in Email"],
            max_records=1,
        )
        if records:
            return records[0]["id"]
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def partner_has_commission(email):
    """Returns True if the partner has a non-zero Commission Given (%) value."""
    try:
        safe = email.strip().lower().replace("'", "\\'")
        records = get_partner_table().all(
            formula=f"LOWER({{Stacker log-in Email}}) = '{safe}'",
            max_records=1,
        )
        if not records:
            return False
        val = records[0]["fields"].get("Commission Given (%)")
        if isinstance(val, list):
            val = val[0] if val else None
        if val is None or val == "":
            return False
        if isinstance(val, (int, float)):
            return float(val) != 0
        if isinstance(val, str):
            cleaned = val.strip().rstrip("%").strip()
            try:
                return float(cleaned) != 0
            except ValueError:
                return bool(cleaned)
        return bool(val)
    except Exception:
        return False


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
    "interview_invitation_sent":"Interview Invitation Sent [OB]",
    "interview_invitation_date":"Date of Interview Invite Sent [OB]",
    "deposit_paid":             "OB: Deposit Paid",
    "deposit_invoice_sent":     "Invoice Sent for Deposit",
    "deposit_invoice_date":     "OB: Date of deposit invoice sent",
    "deposit_payment_date":     "OB: Date of deposit payment",
    "full_tuition_invoice_sent":"Full Tuition Invoice Sent",
    "full_tuition_paid":        "OB: Full Tuition Paid",
    "full_tuition_payment_date":"OB: Date of full tuition payment",
    "financial_aid":            "Financial Aid Allocation",
    "mentor_background_shared": "OB: Mentor Background Shared",
    "mentor_outreach_date":     "OB: Mentor Outreach date (for automations)",
    "interview_notes":          "Interview Notes For The Mentor [OB]",
    "confirmed_launched":       "Student Confirmed & Launched",
    "partner_id":               "Stacker ID (Partner)",
    "white_label":              "White Label or Partner Payment Program",
    "status_in_program":        "PM: Status in Program",
    "publication_marker":       "Publication Marker",
    "publication_outcome":      "PS: Latest Publication Outcome - Latest",
    # Progress tracker + meeting summary
    "expected_meetings":        "Number of Expected Meetings - Student/Mentor",
    "completed_meetings":       "[Current + Archived] No. of Meetings Completed",
    "hours_recorded":           "[Current + Archived] No. of Hours Recorded",
    "student_no_shows":         "[Current + Archived] No. of Student No Shows in Mentor Meetings",
    "most_recent_meeting_mentor":"Most Recent Meeting Mentor",
    "program_manager":          "Program Manager",
    "program_manager_email":    "Program Manager Email",
    "revised_final_paper_due":  "PM: Student's Revised Final Paper - Due date",
    "revised_final_paper_upload": "Revised Final Paper upload (from Mentor-Student Progress Up Date)",
    "submission_portal":        "Student Submission Portal Lookup",
    "cohort_start_date":        "Cohort Start Date",
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
    ("login_tracked", False),
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default


def _inject_umami():
    """Load Umami into the parent frame (only called post-auth)."""
    components.html(
        """
        <script>
        (function() {
            if (window.parent && !window.parent.__umami_loaded) {
                window.parent.__umami_loaded = true;
                const s = window.parent.document.createElement('script');
                s.defer = true;
                s.src = 'https://cloud.umami.is/script.js';
                s.setAttribute('data-website-id', '4e48a4fa-cc54-4835-ada3-c242f4fec0ec');
                s.setAttribute('data-auto-track', 'false');
                window.parent.document.head.appendChild(s);
            }
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def track_umami_login(email):
    """Identify the user in Umami and fire a 'login' event in the parent frame."""
    safe_email = (email or "").replace("'", "\\'")
    components.html(
        f"""
        <script>
        (function() {{
            const fire = () => {{
                if (window.parent && window.parent.umami) {{
                    window.parent.umami.identify({{ email: '{safe_email}' }});
                    window.parent.umami.track('login', {{ email: '{safe_email}' }});
                }} else {{
                    setTimeout(fire, 200);
                }}
            }};
            fire();
        }})();
        </script>
        """,
        height=0,
        width=0,
    )

cookie_manager = stx.CookieManager(key="partner_portal")


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
    if date_str is None or date_str == "":
        return "Not set"
    # pyairtable may coerce formula/date fields to Python date or datetime objects
    if hasattr(date_str, "year") and hasattr(date_str, "day"):
        day = date_str.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{date_str.strftime('%B')} {day}{suffix}, {date_str.year}"
    if isinstance(date_str, list):
        date_str = date_str[0] if date_str else ""
    if not date_str:
        return "Not set"
    try:
        date_obj = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
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

    pub_outcome = clean_field(f.get(STUDENT_FIELDS["publication_outcome"], "")).strip().lower()
    rfp_raw     = f.get(STUDENT_FIELDS["revised_final_paper_upload"], [])
    program_complete = bool(rfp_raw) or "accepted" in pub_outcome

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
        "deposit_invoice_sent":      clean_field(f.get(STUDENT_FIELDS["deposit_invoice_sent"], "")),
        "deposit_invoice_date":      unwrap(f.get(STUDENT_FIELDS["deposit_invoice_date"], "")),
        "deposit_payment_date":      unwrap(f.get(STUDENT_FIELDS["deposit_payment_date"], "")),
        "full_tuition_invoice_sent": clean_field(f.get(STUDENT_FIELDS["full_tuition_invoice_sent"], "")),
        "full_tuition_payment_date": unwrap(f.get(STUDENT_FIELDS["full_tuition_payment_date"], "")),
        "mentor_background_shared":  clean_field(f.get(STUDENT_FIELDS["mentor_background_shared"], "")),
        "mentor_outreach_date":      unwrap(f.get(STUDENT_FIELDS["mentor_outreach_date"], "")),
        "interview_notes":           clean_field(f.get(STUDENT_FIELDS["interview_notes"], "")),
        "confirmed_launched":        clean_field(f.get(STUDENT_FIELDS["confirmed_launched"], "")),
        "white_label":               clean_field(f.get(STUDENT_FIELDS["white_label"], "")),
        "status_in_program":         clean_field(f.get(STUDENT_FIELDS["status_in_program"], "")),
        "program_complete":          program_complete,
        "partner_emails":            partner_emails,
        "expected_meetings":         f.get(STUDENT_FIELDS["expected_meetings"], 0),
        "completed_meetings":        f.get(STUDENT_FIELDS["completed_meetings"], 0),
        "hours_recorded":            f.get(STUDENT_FIELDS["hours_recorded"], ""),
        "student_no_shows":          unwrap(f.get(STUDENT_FIELDS["student_no_shows"], 0), default=0),
        "pm_ids":                    f.get(STUDENT_FIELDS["program_manager"], []) if isinstance(f.get(STUDENT_FIELDS["program_manager"], []), list) else [],
        "pm_email":                  unwrap(f.get(STUDENT_FIELDS["program_manager_email"], "")),
        "most_recent_meeting_mentor":unwrap(f.get(STUDENT_FIELDS["most_recent_meeting_mentor"], "")),
        "revised_final_paper_due":    unwrap(f.get(STUDENT_FIELDS["revised_final_paper_due"], "")),
        "revised_final_paper_upload": rfp_raw,
        "submission_portal":          unwrap(f.get(STUDENT_FIELDS["submission_portal"], "")),
        "cohort_start_date":          unwrap(f.get(STUDENT_FIELDS["cohort_start_date"]) or _fuzzy_get(f, "cohort start date") or ""),
        "upcoming_cohort":            f.get("Upcoming Cohort (Cohort Table)"),
    }


@st.cache_data(ttl=300, show_spinner=False)
def get_students_for_partner(partner_email):
    def _call():
        safe = partner_email.lower().replace("'", "\\'")
        formula = f"FIND('{safe}', LOWER(ARRAYJOIN({{Stacker ID (Partner)}}, ',')))"
        return get_tables()["students"].all(formula=formula)

    try:
        records = _call()
    except Exception as e:
        if "ConnectionReset" in str(e) or "Connection aborted" in str(e):
            get_tables.clear()
            get_airtable_api.clear()
            try:
                records = _call()
            except Exception as e2:
                st.error(f"Error fetching students: {e2}")
                return []
        else:
            st.error(f"Error fetching students: {e}")
            return []
    return [_build_student(r) for r in records]


def _is_upcoming_cohort(raw):
    val = raw[0] if isinstance(raw, list) and raw else raw
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() == "true"
    if isinstance(val, (int, float)):
        return bool(val)
    return False


def get_onboarding_students(partner_email):
    students = get_students_for_partner(partner_email)
    return [s for s in students if not s["confirmed_launched"]]


def get_program_students(partner_email):
    students = get_students_for_partner(partner_email)
    return [s for s in students if s["confirmed_launched"].strip().lower() == "yes"]


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


@st.cache_data(ttl=3600, show_spinner=False)
def get_cohort_name(record_id):
    try:
        record = get_airtable_api().base(BASE_ID).table(COHORT_TABLE_ID).get(record_id)
        fields = record["fields"]
        # Try common primary field names, then fall back to first string value
        for key in ("Name", "Cohort Name", "Cohort", "cohort"):
            if fields.get(key):
                return str(fields[key])
        for val in fields.values():
            if isinstance(val, str) and val.strip():
                return val
    except Exception:
        pass
    return ""


@st.cache_data(ttl=3600, show_spinner=False)
def get_program_type_name(record_id):
    try:
        record = get_airtable_api().base(BASE_ID).table(PROGRAM_TYPE_TABLE_ID).get(record_id)
        return record["fields"].get("Name", "")
    except Exception:
        return ""


def _build_referral(record):
    f = record["fields"]
    ids = REFERRAL_FIELD_IDS

    def _g(key):
        return f.get(ids[key])

    return {
        "id":                record["id"],
        "name":              clean_field(_g("name")),
        "cohort":            get_cohort_name(_unwrap_val(_g("cohort")) or "") or "",
        "admission":         clean_field(_g("admission")),
        "program_type":      get_program_type_name(_unwrap_val(_g("program_type")) or "") or "",
        "discount":          _g("discount"),
        "original_tuition":  _g("original_tuition"),
        "final_tuition":     _g("final_tuition"),
        "net_paid":          _g("net_paid"),
        "payment_method":    clean_field(_g("payment_method")),
        "net_received":      _g("net_received"),
        "commission_pct":    _g("commission_pct"),
        "commission_amount": _g("commission_amount"),
        "payment_status":    clean_field(_g("payment_status")),
        "payment_date":      unwrap(_g("payment_date") or ""),
        "finance_notes":     clean_field(_g("finance_notes")),
        "partnership_notes": clean_field(_g("partnership_notes")),
    }


@st.cache_data(ttl=300, show_spinner=False)
def get_referrals_for_partner(partner_email):
    partner_record_id = get_partner_record_id(partner_email)
    if not partner_record_id:
        return {"error": f"No partner record found for {partner_email}"}
    try:
        formula = f"FIND('{partner_record_id}', ARRAYJOIN({{{REFERRAL_PARTNER_ID_FIELD}}}, ','))"
        records = get_referral_table().all(
            formula=formula,
            fields=list(REFERRAL_FIELD_IDS.values()),
            use_field_ids=True,
        )
        return [_build_referral(r) for r in records]
    except Exception as e:
        return {"error": f"Referral query failed: {e}"}


# ──────────────────────────────────────────────
# Auth flow
# ──────────────────────────────────────────────

def check_session_cookie():
    if st.session_state.authenticated:
        return
    token = cookie_manager.get("partner_session")
    if token:
        email = verify_session_token(token)
        if email:
            with st.spinner("Loading your portal..."):
                students = get_students_for_partner(email)
            st.session_state.authenticated = True
            st.session_state.partner_email = email
            st.session_state.partner_name = get_partner_name(email)
            st.session_state.students = students
            st.session_state.is_preview = False
            st.rerun()
        else:
            cookie_manager.delete("partner_session")


def check_magic_link_token():
    if "token" not in st.query_params or st.session_state.authenticated:
        return
    token = st.query_params["token"]
    email = verify_magic_token(token)
    if email:
        with st.spinner("Loading your portal..."):
            students = get_students_for_partner(email)
        st.session_state.authenticated = True
        st.session_state.partner_email = email
        st.session_state.partner_name = get_partner_name(email)
        st.session_state.students = students
        st.session_state.is_preview = False
        st.session_state.pending_session_cookie = email
        # No rerun — let the script continue directly to show_dashboard().
        # The token URL is cleaned up at the entry point below.
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
                            try:
                                found = _partner_exists(clean_email)
                            except Exception:
                                found = None
                        if found is None:
                            st.error("Could not reach the database. Please try again in a moment.")
                        elif found:
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
                        email_key = preview_email.strip().lower()
                        with st.spinner("Looking up partner..."):
                            try:
                                found = _partner_exists(email_key)
                            except Exception:
                                found = None
                        if found is None:
                            st.error("Could not reach the database. Please try again in a moment.")
                        elif found:
                            st.session_state.authenticated = True
                            st.session_state.partner_email = email_key
                            st.session_state.partner_name = get_partner_name(email_key)
                            st.session_state.students = []
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
    is_launched = str(student.get("confirmed_launched") or "").strip().lower() == "yes"
    mentor_confirmed = str(student.get("mentor_confirmation") or "").strip().lower() == "yes"
    mentor_prefix = "Mentor's" if mentor_confirmed else "Proposed mentor's"

    is_white_label = bool((student.get("white_label") or "").strip())

    interview_val = str(student.get("interview_invitation_sent", "") or "").strip().lower()
    interview_not_required = interview_val == "not required"
    stages_done = [
        True,
        interview_val == "yes" or interview_not_required,
        True if is_white_label else str(student.get("deposit_paid", "") or "").strip().lower() == "yes",
        str(student.get("mentor_confirmation", "") or "").strip().lower() == "yes",
        True if is_white_label else str(student.get("full_tuition_paid", "") or "").strip().lower() == "yes",
    ]
    current_idx = next((i for i, done in enumerate(stages_done) if not done), len(stages_done))

    if is_white_label:
        st.markdown(
            '<div style="background:#FEF9C3;border:1px solid #FDE047;border-radius:8px;'
            'padding:0.5rem 1rem;margin-bottom:0.75rem;font-size:0.85rem;color:#713F12;">'
            '<strong>White Label student</strong> — deposit and full tuition stages are managed separately '
            'and are not tracked here.</div>',
            unsafe_allow_html=True,
        )

    def _circle(i, done, is_current):
        if done:
            bg, border, fg, icon = "#16A34A", "#16A34A", "white", "✓"
        elif is_current:
            bg, border, fg, icon = "white", "#BE1E2D", "#BE1E2D", str(i + 1)
        else:
            bg, border, fg, icon = "#F1F5F9", "#CBD5E1", "#94A3B8", str(i + 1)
        return (
            f'<div style="width:40px;height:40px;border-radius:50%;background:{bg};'
            f'color:{fg};border:2.5px solid {border};box-sizing:border-box;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:1rem;font-weight:700;flex-shrink:0;">{icon}</div>'
        )

    def _connector(done):
        color = "#16A34A" if done else "#E2E8F0"
        return f'<div style="width:3px;flex:1;background:{color};margin:4px auto;border-radius:2px;min-height:28px;"></div>'

    def _stage_label(name, done, is_current):
        color = "#16A34A" if done else ("#BE1E2D" if is_current else "#94A3B8")
        suffix = (
            ' <span style="font-weight:400;font-size:0.7rem;opacity:0.7;">· Complete</span>' if done else
            ' <span style="font-weight:400;font-size:0.7rem;">· Current stage</span>' if is_current else ""
        )
        return (
            f'<div style="font-size:0.75rem;font-weight:700;color:{color};'
            f'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.6rem;">'
            f'{name}{suffix}</div>'
        )

    def _card(content, done, is_current, is_future):
        if is_current:
            style = ("background:white;border-radius:12px;padding:1.25rem;"
                     "border:2px solid #BE1E2D;box-shadow:0 4px 20px rgba(190,30,45,0.12);")
        elif done:
            style = ("background:white;border-radius:12px;padding:1.25rem;"
                     "border:1px solid #DCFCE7;box-shadow:0 2px 8px rgba(0,0,0,0.05);")
        else:
            style = "background:#F8FAFC;border-radius:12px;padding:1.25rem;border:1px solid #E2E8F0;"
        return f'<div style="{style}">{content}</div>'

    def _grid(*fields, cols=3):
        return (
            f'<div style="display:grid;grid-template-columns:{"1fr " * cols};gap:0.75rem 1.5rem;">'
            + "".join(fields) + '</div>'
        )

    def _pending(msg):
        return f'<p style="color:#94A3B8;font-size:0.9rem;margin:0;">{msg}</p>'

    # ── Stage 1: Applied ──────────────────────────────────────────────────────
    s1 = _grid(
        fb("Student", display_name),
        fb("Program", program),
        fb("Cohort", cohort),
        fb("Cohort Start Date", format_date(student.get("cohort_start_date", ""))),
        fb("Areas of Interest", student.get("areas_of_interest") or "—"),
    )

    # ── Stage 2: Interview ────────────────────────────────────────────────────
    if interview_not_required:
        s2 = _pending("Not required.")
    elif stages_done[1]:
        s2 = _grid(fb("Interview Date", format_date(student.get("interview_invitation_date"))), cols=1)
    else:
        s2 = _pending("Interview invitation not yet sent.")

    # ── Stage 3: Deposit ──────────────────────────────────────────────────────
    invoice_date_val = format_date(student.get("deposit_invoice_date", ""))
    if is_white_label:
        s3 = _pending("N/A — White Label student")
    elif stages_done[2]:
        s3 = _grid(
            fb("Deposit Paid", '<span style="background:#DCFCE7;color:#166534;padding:0.15rem 0.65rem;border-radius:20px;font-size:0.85rem;font-weight:600;">Yes</span>'),
            fb("Financial Aid", student.get("financial_aid") or "—"),
            fb("Date of Deposit Invoice Sent", invoice_date_val),
            fb("Date of Deposit Payment", format_date(student.get("deposit_payment_date", ""))),
            cols=3,
        )
    else:
        s3 = _grid(fb("Date of Deposit Invoice Sent", invoice_date_val), cols=1)

    # ── Stage 4: Mentor Match ─────────────────────────────────────────────────
    show_mentor = str(student.get("mentor_background_shared", "") or "").strip().lower() == "yes" or is_launched
    if show_mentor:
        cv_raw = student.get("mentor_cv")
        cv_val = (
            " ".join(
                f'<a href="{a.get("url","")}" target="_blank" style="color:#BE1E2D;text-decoration:none;">'
                f'{a.get("filename", "Download CV")}</a>'
                for a in cv_raw if isinstance(a, dict) and a.get("url")
            ) or "—"
        ) if isinstance(cv_raw, list) and cv_raw else "—"

        confirmation = (student.get("mentor_confirmation") or "").strip()
        if confirmation.lower() == "yes":
            conf_val = '<span style="background:#DBEAFE;color:#1D4ED8;padding:0.15rem 0.65rem;border-radius:20px;font-size:0.85rem;font-weight:600;">Yes</span>'
        elif confirmation:
            conf_val = f'<span style="background:#FEF3C7;color:#92400E;padding:0.15rem 0.65rem;border-radius:20px;font-size:0.85rem;font-weight:600;">{confirmation}</span>'
        else:
            conf_val = "—"

        notes = (student.get("interview_notes") or "").strip()
        notes_val = (
            f'<div style="font-size:0.9rem;color:#475569;line-height:1.6;white-space:pre-wrap;font-weight:400;">{notes}</div>'
            if notes and notes not in ("-----",) else "—"
        )
        s4 = (
            _grid(
                fb(f"{mentor_prefix} Name", student.get("mentor_name") or "Not yet assigned"),
                fb(f"{mentor_prefix} University", student.get("mentor_university") or "—"),
                fb(f"{mentor_prefix} CV", cv_val),
                fb("Date We Reached Out to Mentor", format_date(student.get("mentor_outreach_date"))),
                fb("Has Mentor Confirmed?", conf_val),
            )
            + '<div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid #F1F5F9;">'
            + fb("Interview Notes Shared with Mentor", notes_val)
            + '</div>'
        )
    else:
        s4 = _pending("Mentor details will appear here once the background has been shared.")

    # ── Stage 5: Full Tuition ─────────────────────────────────────────────────
    tuition_badge_yes = '<span style="background:#DCFCE7;color:#166534;padding:0.15rem 0.65rem;border-radius:20px;font-size:0.85rem;font-weight:600;">Yes</span>'
    if is_white_label:
        s5 = _pending("N/A — White Label student")
    elif is_launched:
        pm_ids = student.get("pm_ids", [])
        pm_name = get_staff_name(pm_ids[0]) if pm_ids else ""
        pm_email = student.get("pm_email", "") or ""
        pm_email_val = (
            f'<a href="mailto:{pm_email}" style="color:#BE1E2D;text-decoration:none;">{pm_email}</a>'
            if pm_email else "—"
        )
        s5 = _grid(
            fb("Full Tuition Paid", tuition_badge_yes),
            fb("Date of Full Tuition Payment", format_date(student.get("full_tuition_payment_date", ""))),
            fb("Program Manager", pm_name or "—"),
            fb("Program Manager Email", pm_email_val),
        )
    elif stages_done[4]:
        s5 = _grid(
            fb("Full Tuition Paid", tuition_badge_yes),
            fb("Date of Full Tuition Payment", format_date(student.get("full_tuition_payment_date", ""))),
            cols=2,
        )
    else:
        s5 = _pending("Awaiting full tuition payment.")

    # ── Render vertical timeline ──────────────────────────────────────────────
    stage_defs = [
        ("Applied",      s1, stages_done[0]),
        ("Interview",    s2, stages_done[1]),
        ("Deposit",      s3, stages_done[2]),
        ("Mentor Match", s4, stages_done[3]),
        ("Full Tuition", s5, stages_done[4]),
    ]

    parts = ['<div style="margin-top:0.25rem;">']
    for i, (name, content, done) in enumerate(stage_defs):
        is_current = (i == current_idx)
        is_future = not done and not is_current
        is_last = (i == len(stage_defs) - 1)
        parts.append(
            f'<div style="display:flex;gap:1.25rem;{"opacity:0.45;" if is_future else ""}">'
            f'<div style="display:flex;flex-direction:column;align-items:center;flex:0 0 40px;">'
            + _circle(i, done, is_current)
            + ('' if is_last else _connector(done))
            + '</div>'
            f'<div style="flex:1;padding-bottom:{"0" if is_last else "1.75rem"};">'
            + _stage_label(name, done, is_current)
            + _card(content, done, is_current, is_future)
            + '</div>'
            '</div>'
        )
    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


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
            pct = min(completed / expected, 1.0)
            bar_color = "#16A34A" if completed >= expected else "#3B82F6"
            st.markdown(
                f'<div style="background:#E2E8F0;border-radius:4px;height:8px;margin:0.4rem 0;">'
                f'<div style="background:{bar_color};width:{pct*100:.1f}%;height:8px;border-radius:4px;"></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
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


def _unwrap_val(val):
    """Unwrap a single-element list returned by Airtable lookup fields."""
    if isinstance(val, list):
        return val[0] if val else None
    return val


def _fmt_currency(val):
    val = _unwrap_val(val)
    if val is None or val == "":
        return "—"
    try:
        v = float(val)
        return f"${v:,.2f}"
    except (ValueError, TypeError):
        return str(val) if val else "—"


def _fmt_pct(val):
    val = _unwrap_val(val)
    if val is None or val == "":
        return "—"
    if isinstance(val, str):
        return val if val else "—"
    try:
        v = float(val)
        # Airtable percent fields store as decimal (0.15 = 15%)
        if 0 < v <= 1:
            return f"{v * 100:.1f}%"
        return f"{v:.1f}%"
    except (ValueError, TypeError):
        return "—"


def _safe_float(val):
    val = _unwrap_val(val)
    try:
        return float(val) if val is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def show_referral_tracker():
    with st.spinner("Loading referral data..."):
        referrals = get_referrals_for_partner(st.session_state.partner_email)

    st.markdown("### Referral Tracker")
    st.markdown("""
    <div style="background:#F8F9FA;border-left:4px solid #BE1E2D;border-radius:6px;
                padding:0.85rem 1rem;margin-bottom:1.25rem;color:#475569;font-size:0.92rem;line-height:1.55;">
        <div style="font-size:0.75rem;font-weight:700;color:#94A3B8;text-transform:uppercase;
                    letter-spacing:0.06em;margin-bottom:0.35rem;">referral payment/commission</div>
        Students for which your organisation will receive a referral payment, along with their
        tuition details, commission rate, and payment status.
    </div>
    """, unsafe_allow_html=True)

    if isinstance(referrals, dict) and "error" in referrals:
        st.error(referrals["error"])
        return

    if not referrals:
        st.info("No referral records found for your account.")
        return

    # ── Summary metrics ───────────────────────────────────────────────────────
    paid_list    = [r for r in referrals if r["payment_status"].strip().lower() == "paid"]
    pending_list = [r for r in referrals if r["payment_status"].strip().lower() != "paid"]

    total_commission   = sum(_safe_float(r["commission_amount"]) for r in referrals)
    paid_commission    = sum(_safe_float(r["commission_amount"]) for r in paid_list)
    pending_commission = sum(_safe_float(r["commission_amount"]) for r in pending_list)

    pct_values = list(set(_fmt_pct(r["commission_pct"]) for r in referrals if r["commission_pct"] not in (None, "")))
    commission_pct_display = pct_values[0] if len(pct_values) == 1 else ("Varies" if pct_values else "—")

    def _metric_card(label, value, value_color="#1E293B"):
        return (
            f'<div style="background:white;border-radius:10px;padding:1.1rem 1.4rem;'
            f'box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #E2E8F0;">'
            f'<div style="font-size:0.68rem;font-weight:700;color:#94A3B8;text-transform:uppercase;'
            f'letter-spacing:0.07em;margin-bottom:0.5rem;">{label}</div>'
            f'<div style="font-size:1.6rem;font-weight:700;color:{value_color};">{value}</div>'
            f'</div>'
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_metric_card("Total Commission", _fmt_currency(total_commission), "#16A34A"), unsafe_allow_html=True)
    with c2:
        st.markdown(_metric_card("Commission Rate", commission_pct_display), unsafe_allow_html=True)

    st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)

    # ── How commissions are calculated ────────────────────────────────────────
    st.markdown(
        f'<div style="background:white;border:1px solid #E2E8F0;border-radius:10px;'
        f'padding:1rem 1.25rem;margin-bottom:1.25rem;">'
        f'<div style="font-size:0.88rem;font-weight:700;color:#1E293B;margin-bottom:0.5rem;">'
        f'How commissions are calculated</div>'
        f'<div style="font-size:0.83rem;color:#475569;line-height:1.7;margin-bottom:0.25rem;">'
        f'<strong style="color:#1E293B;">Net Amount Received After Tax &amp; Transaction Fees</strong> — '
        f'This is the amount after deducting a transaction fee of '
        f'<strong style="color:#1E293B;">3.53% (Stripe)</strong> or <strong style="color:#1E293B;">4.41% (PayPal)</strong>, '
        f'depending on the payment method, as well as a <strong style="color:#1E293B;">6.5% corporate tax</strong>.</div>'
        f'<div style="font-size:0.83rem;color:#475569;line-height:1.7;">'
        f'<strong style="color:#1E293B;">Calculated Commission</strong> — Net Amount Received After Tax &amp; Transaction Fees × your commission rate '
        f'({commission_pct_display}). Commissions are paid once full tuition has been received and verified by our finance team.'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # Tooltip CSS (injected once)
    st.markdown("""
    <style>
    .ref-tt { position:relative; display:inline-flex; align-items:center; cursor:help; }
    .ref-tt .ref-icon {
        width:13px; height:13px; border-radius:50%; background:#CBD5E1; color:#64748B;
        font-size:8px; font-weight:700; display:inline-flex; align-items:center;
        justify-content:center; margin-left:4px; flex-shrink:0; font-style:normal;
    }
    .ref-tt .ref-tip {
        visibility:hidden; opacity:0; transition:opacity 0.15s;
        background:#1E293B; color:white; font-size:0.75rem; font-weight:400;
        line-height:1.5; border-radius:7px; padding:7px 10px;
        position:absolute; bottom:calc(100% + 6px); left:0;
        width:240px; z-index:9999; pointer-events:none;
        box-shadow:0 4px 12px rgba(0,0,0,0.2);
    }
    .ref-tt:hover .ref-tip { visibility:visible; opacity:1; }
    </style>
    """, unsafe_allow_html=True)

    # ── Filters ───────────────────────────────────────────────────────────────
    f1, f2, f3 = st.columns([2, 2, 1.5])
    with f1:
        names = sorted(set(r["name"] for r in referrals if r["name"]))
        sel_name = st.selectbox("Search student", ["All students"] + names, key="ref_filter_name")
    with f2:
        cohorts = sorted(set(r["cohort"] for r in referrals if r["cohort"]))
        sel_cohort = st.selectbox("Filter by cohort", ["All cohorts"] + cohorts, key="ref_filter_cohort")
    with f3:
        sel_status = st.selectbox(
            "Payment status",
            ["All", "Paid", "To be Paid", "Pending", "Not to be Paid"],
            key="ref_filter_status",
        )

    filtered = [
        r for r in referrals
        if (sel_name == "All students" or r["name"] == sel_name)
        and (sel_cohort == "All cohorts" or r["cohort"] == sel_cohort)
        and (
            sel_status == "All"
            or r["payment_status"].strip().lower() == sel_status.lower()
        )
    ]

    if not filtered:
        st.info("No records match the current filters.")
        return

    # ── Cards ─────────────────────────────────────────────────────────────────
    def _status_badge(status):
        s = (status or "").strip()
        sl = s.lower()
        if sl == "paid":
            bg, col, icon = "#DCFCE7", "#166534", "✓"
        elif sl == "to be paid":
            bg, col, icon = "#DBEAFE", "#1E40AF", "📅"
        elif sl == "pending":
            bg, col, icon = "#FEF3C7", "#92400E", "⏳"
        elif sl == "not to be paid":
            bg, col, icon = "#FEE2E2", "#991B1B", "✕"
        elif s:
            bg, col, icon = "#F1F5F9", "#475569", "·"
        else:
            return '<span style="color:#94A3B8;font-size:0.8rem;">—</span>'
        return (
            f'<span style="background:{bg};color:{col};padding:0.2rem 0.65rem;'
            f'border-radius:20px;font-size:0.72rem;font-weight:600;white-space:nowrap;">'
            f'{icon} {s}</span>'
        )

    def _pill(text, bg="#F1F5F9", color="#475569"):
        return (
            f'<span style="background:{bg};color:{color};padding:0.18rem 0.6rem;'
            f'border-radius:20px;font-size:0.72rem;font-weight:500;white-space:nowrap;'
            f'margin-right:0.35rem;display:inline-block;">{text}</span>'
        )

    def _tt(label, tip):
        return (
            f'<span class="ref-tt">{label}'
            f'<i class="ref-icon">i</i>'
            f'<span class="ref-tip">{tip}</span>'
            f'</span>'
        )

    def _field_block(label, value, bold=False):
        val_style = (
            'font-size:0.95rem;font-weight:700;color:#1E293B;'
            if bold else
            'font-size:0.92rem;font-weight:500;color:#374151;'
        )
        return (
            f'<div style="display:flex;flex-direction:column;gap:0.15rem;">'
            f'<div style="font-size:0.7rem;font-weight:600;text-transform:uppercase;'
            f'letter-spacing:0.06em;color:#94A3B8;">{label}</div>'
            f'<div style="{val_style}">{value}</div>'
            f'</div>'
        )

    TIP_ORIG = "The full tuition amount before any scholarship or discount is applied."
    TIP_FINAL = "The tuition amount after any scholarship or discount has been deducted."
    TIP_NET_PAID = "The actual amount received from the student after any refunds."
    TIP_NET_RECV = "Net Amount Paid minus a 6.5% corporate tax and a payment processing fee (3.53% Stripe / 4.41% PayPal)."
    TIP_COMMISSION = "Your referral commission calculated by applying the commission % on the Net Amount Received (After Tax & Transaction Fees)."

    cards_html = ""
    for r in filtered:
        status = (r["payment_status"] or "").strip()
        payment_date = format_date(r["payment_date"]) if r["payment_date"] else "—"
        commission_val = _fmt_currency(r["commission_amount"])
        discount_val = _safe_float(r["discount"])

        # Pill tags
        pills = ""
        if r["cohort"]:
            pills += _pill(r["cohort"])
        if r["program_type"]:
            pills += _pill(r["program_type"], "#EEF2FF", "#4338CA")
        if r["admission"]:
            adm_bg = "#DCFCE7" if "accept" in (r["admission"] or "").lower() else "#F1F5F9"
            adm_col = "#166534" if "accept" in (r["admission"] or "").lower() else "#475569"
            pills += _pill(r["admission"], adm_bg, adm_col)

        # Header row: name + pills left, status + commission + date right
        header_row = (
            f'<div style="display:flex;align-items:flex-start;justify-content:space-between;'
            f'gap:1rem;margin-bottom:0.85rem;">'
            f'<div>'
            f'<div style="font-size:1.05rem;font-weight:700;color:#1E293B;margin-bottom:0.35rem;">'
            f'{r["name"] or "—"}</div>'
            f'<div>{pills}</div>'
            f'</div>'
            f'<div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.3rem;flex-shrink:0;">'
            f'{_status_badge(status)}'
            f'<div style="font-size:1.1rem;font-weight:700;color:#16A34A;">{commission_val}</div>'
            f'<div style="font-size:0.75rem;color:#94A3B8;">Payment: {payment_date}</div>'
            f'</div>'
            f'</div>'
        )

        # Main 4-column grid
        grid = (
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;'
            f'padding:0.85rem;background:#F8FAFC;border-radius:8px;margin-bottom:0.6rem;">'
            + _field_block(_tt("Original Tuition Amount", TIP_ORIG), _fmt_currency(r["original_tuition"]))
            + _field_block("Discount Applied", _fmt_currency(r["discount"]))
            + _field_block(_tt("Final Tuition Amount After Discount", TIP_FINAL), _fmt_currency(r["final_tuition"]))
            + _field_block(_tt("Net Amount Paid", TIP_NET_PAID), _fmt_currency(r["net_paid"]))
            + f'</div>'
        )

        # Secondary row: Payment Method, Net Received, Commission
        sec_items = (
            _field_block("Payment Method Used", r["payment_method"] or "—")
            + _field_block(_tt("Net Amount Received After Tax &amp; Transaction Fees", TIP_NET_RECV), _fmt_currency(r["net_received"]), bold=True)
            + _field_block(_tt("Calculated Commission Amount", TIP_COMMISSION), commission_val, bold=True)
        )

        secondary = (
            f'<div style="display:flex;gap:2.5rem;padding:0 0.25rem 0.5rem;">'
            + sec_items
            + f'</div>'
        )

        # Notes row
        notes_html = ""
        fn = (r["finance_notes"] or "").strip()
        pn = (r["partnership_notes"] or "").strip()

        note_parts = ""
        if fn:
            note_parts += (
                f'<div style="flex:1;">'
                f'<div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;'
                f'letter-spacing:0.06em;color:#94A3B8;margin-bottom:0.2rem;">Finance Notes</div>'
                f'<div style="font-size:0.8rem;color:#475569;">{fn}</div></div>'
            )
        if pn:
            note_parts += (
                f'<div style="flex:1;">'
                f'<div style="font-size:0.68rem;font-weight:600;text-transform:uppercase;'
                f'letter-spacing:0.06em;color:#94A3B8;margin-bottom:0.2rem;">Partnership Notes</div>'
                f'<div style="font-size:0.8rem;color:#475569;">{pn}</div></div>'
            )
        if note_parts:
            notes_html = (
                f'<div style="display:flex;gap:1.5rem;margin-top:0.5rem;padding-top:0.6rem;'
                f'border-top:1px solid #E2E8F0;">'
                + note_parts
                + f'</div>'
            )

        cards_html += (
            f'<div style="background:white;border:1px solid #E2E8F0;border-radius:12px;'
            f'padding:1.1rem 1.25rem;margin-bottom:0.85rem;'
            f'box-shadow:0 1px 4px rgba(0,0,0,0.05);">'
            + header_row + grid + secondary + notes_html
            + f'</div>'
        )

    st.markdown(cards_html, unsafe_allow_html=True)


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
            "📋 Student Details",
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

def _cohort_sort_key(student):
    import re
    parts = [p.strip() for p in student.get("name", "").split("|")]
    cohort = parts[1] if len(parts) > 1 else ""
    year_match = re.search(r"\d{4}", cohort)
    year = int(year_match.group()) if year_match else 0
    season_order = {"spring": 1, "summer ii": 3, "summer": 2, "fall": 4, "winter ii": 6, "winter": 5}
    cohort_lower = cohort.lower()
    season = next((v for k, v in season_order.items() if k in cohort_lower), 0)
    return (year, season)


def _onboarding_stage_html(student, large=False):
    is_wl = bool((student.get("white_label") or "").strip())
    stages = [
        ("Applied",      True),
        ("Interview",    str(student.get("interview_invitation_sent", "") or "").strip().lower() in ("yes", "not required")),
        ("Deposit",      True if is_wl else str(student.get("deposit_paid", "") or "").strip().lower() == "yes"),
        ("Mentor Match", str(student.get("mentor_confirmation", "") or "").strip().lower() == "yes"),
        ("Full Tuition", True if is_wl else str(student.get("full_tuition_paid", "") or "").strip().lower() == "yes"),
    ]

    current_idx = next((i for i, (_, done) in enumerate(stages) if not done), len(stages))

    circle_size  = "32px" if large else "22px"
    icon_font    = "0.8rem" if large else "0.65rem"
    label_font   = "0.75rem" if large else "0.62rem"
    line_top     = "15px" if large else "10px"
    line_height  = "3px" if large else "2px"
    padding      = "0.5rem 0 0.6rem" if large else "0.2rem 0 0.35rem"

    parts = []
    for i, (label, done) in enumerate(stages):
        is_current = (i == current_idx)
        if done:
            circle_bg, circle_border, circle_fg = "#16A34A", "#16A34A", "white"
            icon, label_color, label_weight = "✓", "#16A34A", "600"
        elif is_current:
            circle_bg, circle_border, circle_fg = "white", "#BE1E2D", "#BE1E2D"
            icon, label_color, label_weight = str(i + 1), "#BE1E2D", "700"
        else:
            circle_bg, circle_border, circle_fg = "#F1F5F9", "#CBD5E1", "#94A3B8"
            icon, label_color, label_weight = str(i + 1), "#94A3B8", "400"

        parts.append(
            f'<div style="display:flex;flex-direction:column;align-items:center;flex:0 0 auto;">'
            f'<div style="width:{circle_size};height:{circle_size};border-radius:50%;background:{circle_bg};'
            f'color:{circle_fg};border:2px solid {circle_border};box-sizing:border-box;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:{icon_font};font-weight:700;">{icon}</div>'
            f'<div style="font-size:{label_font};color:{label_color};font-weight:{label_weight};'
            f'margin-top:4px;text-align:center;white-space:nowrap;">{label}</div>'
            f'</div>'
        )
        if i < len(stages) - 1:
            line_color = "#16A34A" if done else "#E2E8F0"
            parts.append(
                f'<div style="flex:1;height:{line_height};background:{line_color};'
                f'align-self:flex-start;margin-top:{line_top};min-width:8px;"></div>'
            )

    return (
        f'<div style="display:flex;align-items:flex-start;padding:{padding};">'
        + "".join(parts)
        + "</div>"
    )


def _program_meetings_html(student):
    completed = int(student.get("completed_meetings") or 0)
    expected  = int(student.get("expected_meetings")  or 0)

    if not expected:
        return (
            '<div style="padding:0.2rem 0 0.35rem;">'
            '<div style="font-size:0.7rem;color:#94A3B8;">No meeting data</div>'
            '</div>'
        )

    pct = min(completed / expected, 1.0)
    bar_pct = int(pct * 100)

    if pct >= 1.0:
        bar_color, label_color = "#16A34A", "#16A34A"
    else:
        bar_color, label_color = "#3B82F6", "#1D4ED8"

    return (
        f'<div style="display:flex;align-items:center;gap:0.6rem;padding:0.2rem 0 0.35rem;">'
        f'<div style="flex:1;height:6px;background:#F1F5F9;border-radius:3px;overflow:hidden;">'
        f'<div style="height:100%;width:{bar_pct}%;background:{bar_color};border-radius:3px;"></div>'
        f'</div>'
        f'<div style="font-size:0.72rem;color:{label_color};font-weight:600;white-space:nowrap;">'
        f'{completed} / {expected} meetings</div>'
        f'</div>'
    )


def render_student_list(students, page_label, show_pipeline=False, show_meetings=False):
    if not students:
        st.info(f"No students in the {page_label} yet.")
        return

    sorted_students = sorted(students, key=_cohort_sort_key, reverse=True)

    # Header row
    st.markdown(
        '<div style="display:grid;grid-template-columns:3.5fr 2fr 0.8fr;gap:0.5rem;'
        'padding:0.4rem 1rem;margin-bottom:0.25rem;">'
        '<div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;">Student</div>'
        '<div style="font-size:0.72rem;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:0.05em;">Mentor</div>'
        '<div></div>'
        '</div>',
        unsafe_allow_html=True
    )

    for s in sorted_students:
        tracker_value = s.get("name", "")
        mentor = s.get("mentor_name") or "Not yet assigned"
        status_in_prog = s.get("status_in_program", "") or ""

        col_name, col_mentor, col_btn = st.columns([3.5, 2, 0.8])
        with col_name:
            st.markdown(f"**{tracker_value}**")
            if status_in_prog in ("Suspended", "Withdrawn"):
                st.markdown(
                    f'<div style="font-size:0.75rem;color:#DC2626;margin-top:-0.3rem;margin-bottom:0.15rem;">'
                    f'⚠️ {status_in_prog}</div>',
                    unsafe_allow_html=True,
                )
        with col_mentor:
            st.caption(mentor)
        with col_btn:
            if st.button("View →", key=f"view_{s['id']}"):
                st.session_state.selected_student = s
                st.rerun()
        if show_pipeline:
            st.markdown(_onboarding_stage_html(s), unsafe_allow_html=True)
        if show_meetings:
            st.markdown(_program_meetings_html(s), unsafe_allow_html=True)
        st.markdown('<hr style="margin:0.3rem 0;border-color:#F1F5F9;">', unsafe_allow_html=True)


# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────

def show_dashboard():
    partner_email = st.session_state.partner_email
    partner_name  = st.session_state.partner_name
    with st.spinner("Loading students..."):
        onboarding  = get_onboarding_students(partner_email)
        in_program  = get_program_students(partner_email)

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

        show_referral = partner_has_commission(partner_email)
        nav_options = [
            f"Onboarding Tracker  ({len(onboarding)})",
            f"Program Tracker  ({len(in_program)})",
        ]
        if show_referral:
            nav_options.append("Referral Tracker")
        def _clear_selected_student():
            st.session_state.selected_student = None

        view = st.radio("Navigation", nav_options, label_visibility="collapsed", on_change=_clear_selected_student)

        st.markdown("---")
        if st.button("Refresh Data"):
            st.cache_data.clear()
            st.session_state.students = get_students_for_partner(st.session_state.partner_email)
            st.session_state.selected_student = None
            st.rerun()
        if st.button("Logout"):
            try:
                cookie_manager.delete("partner_session")
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

    if partner_name:
        st.markdown(
            f'<div style="font-size:1.6rem;font-weight:700;color:#1E293B;margin-bottom:0.75rem;">'
            f'Welcome, {partner_name}</div>',
            unsafe_allow_html=True
        )

    info = get_bd_poc_details(st.session_state.partner_email)
    poc_name     = info.get("bd_poc_name", "")
    poc_headshot = info.get("bd_poc_headshot_url", "")
    poc_calendly = info.get("bd_poc_calendly", "")
    poc_bio      = info.get("bd_poc_bio", "")
    poc_email    = info.get("bd_poc_email", "")


    def render_poc_card():
        if not poc_name:
            st.markdown(
                '<div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:12px;'
                'padding:1rem 1.5rem;margin-bottom:1.5rem;color:#0C4A6E;font-size:0.9rem;line-height:1.65;">'
                'For questions during the onboarding process, reach out to '
                '<a href="mailto:admissions@lumiere.education" style="color:#0369A1;font-weight:600;text-decoration:none;">'
                'admissions@lumiere.education</a>. For questions about students in the program, reach out to '
                '<a href="mailto:program.manager@lumiere.education" style="color:#0369A1;font-weight:600;text-decoration:none;">'
                'program.manager@lumiere.education</a>.'
                '</div>',
                unsafe_allow_html=True,
            )
            return
        headshot_html = (
            f'<img src="{poc_headshot}" style="width:80px;height:80px;border-radius:50%;'
            f'object-fit:cover;border:3px solid rgba(255,255,255,0.3);flex-shrink:0;">'
            if poc_headshot else
            '<div style="width:80px;height:80px;border-radius:50%;background:rgba(255,255,255,0.15);'
            'flex-shrink:0;display:flex;align-items:center;justify-content:center;'
            'font-size:2rem;color:white;">👤</div>'
        )
        bio_html = (
            f'<div style="font-size:0.83rem;color:rgba(255,255,255,0.82);line-height:1.55;margin-bottom:0.6rem;">'
            f'{poc_bio}</div>'
            if poc_bio else ""
        )
        actions_html = "".join(filter(None, [
            f'<a href="mailto:{poc_email}" style="font-size:0.8rem;color:rgba(255,255,255,0.9);'
            f'font-weight:600;text-decoration:none;">{poc_email}</a>' if poc_email else "",
            f'<span style="color:rgba(255,255,255,0.3);margin:0 0.6rem;">·</span>' if poc_email and poc_calendly else "",
            f'<a href="{poc_calendly}" target="_blank" style="font-size:0.8rem;color:white;font-weight:600;'
            f'text-decoration:none;background:rgba(255,255,255,0.15);padding:0.25rem 0.85rem;'
            f'border-radius:20px;border:1px solid rgba(255,255,255,0.35);">📅 Book a meeting</a>' if poc_calendly else "",
        ]))
        st.markdown(
            f'<div style="background:linear-gradient(135deg,#BE1E2D 0%,#8B1520 100%);'
            f'border-radius:14px;padding:1.25rem 1.75rem;margin-bottom:1.5rem;'
            f'box-shadow:0 4px 16px rgba(190,30,45,0.25);'
            f'display:flex;align-items:center;gap:1.5rem;">'
            f'{headshot_html}'
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-size:0.68rem;font-weight:700;color:rgba(255,255,255,0.65);'
            f'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.35rem;">Your Partnerships Manager</div>'
            f'<div style="font-size:1.05rem;font-weight:700;color:white;line-height:1.35;margin-bottom:0.5rem;">'
            f'Hi, I\'m {poc_name}, your Partnerships Manager at Lumiere!</div>'
            f'{bio_html}'
            f'<div style="display:flex;align-items:center;flex-wrap:wrap;">{actions_html}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    if "Referral" in view:
        show_referral_tracker()
    elif "Onboarding" in view:
        render_poc_card()
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
        ob_col_search, ob_col_cohort, ob_col_upcoming = st.columns([2, 2, 2])
        with ob_col_search:
            ob_names = sorted(set(s["name"].split("|")[0].strip() for s in onboarding))
            selected_ob = st.selectbox(
                "Search for a student", options=["All students"] + ob_names,
                key="search_onboarding",
            )
        with ob_col_cohort:
            ob_cohorts = sorted(set(s.get("cohort", "") for s in onboarding if s.get("cohort")))
            selected_ob_cohort = st.selectbox(
                "Filter by cohort", options=["All cohorts"] + ob_cohorts,
                key="filter_ob_cohort",
            )
        with ob_col_upcoming:
            st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
            only_upcoming = st.checkbox("Upcoming cohort only", key="filter_ob_upcoming")
        filtered_onboarding = [
            s for s in onboarding
            if (selected_ob == "All students" or s["name"].split("|")[0].strip() == selected_ob)
            and (selected_ob_cohort == "All cohorts" or s.get("cohort", "") == selected_ob_cohort)
            and (not only_upcoming or _is_upcoming_cohort(s.get("upcoming_cohort")))
        ]
        render_student_list(filtered_onboarding, "Onboarding Tracker", show_pipeline=True)
    elif "Program" in view:
        render_poc_card()
        st.markdown("### Program Tracker")
        st.markdown("""
        <div style="background:#F8F9FA;border-left:4px solid #BE1E2D;border-radius:6px;
                    padding:0.85rem 1rem;margin-bottom:1.25rem;color:#475569;font-size:0.92rem;line-height:1.55;">
            These are your students who are actively enrolled and working through the program. Use this page
            to track each student's progress against their deadlines and submissions, and to review notes
            from their mentor sessions.
        </div>
        """, unsafe_allow_html=True)
        prog_col_search, prog_col_cohort, prog_col_status = st.columns([2, 2, 2])
        with prog_col_search:
            prog_names = sorted(set(s["name"].split("|")[0].strip() for s in in_program))
            selected_prog = st.selectbox(
                "Search for a student", options=["All students"] + prog_names,
                key="search_program",
            )
        with prog_col_cohort:
            prog_cohorts = sorted(set(s.get("cohort", "") for s in in_program if s.get("cohort")))
            selected_prog_cohort = st.selectbox(
                "Filter by cohort", options=["All cohorts"] + prog_cohorts,
                key="filter_prog_cohort",
            )
        with prog_col_status:
            selected_prog_status = st.selectbox(
                "Program completion", options=["All", "Complete", "In progress"],
                key="filter_prog_status",
            )
        filtered_program = [
            s for s in in_program
            if (selected_prog == "All students" or s["name"].split("|")[0].strip() == selected_prog)
            and (selected_prog_cohort == "All cohorts" or s.get("cohort", "") == selected_prog_cohort)
            and (
                selected_prog_status == "All"
                or (selected_prog_status == "Complete" and s.get("program_complete"))
                or (selected_prog_status == "In progress" and not s.get("program_complete"))
            )
        ]
        render_student_list(filtered_program, "Program Tracker", show_meetings=True)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

check_session_cookie()
check_magic_link_token()

if "pending_session_cookie" in st.session_state and st.session_state.pending_session_cookie:
    try:
        token = generate_session_token(st.session_state.pending_session_cookie)
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        cookie_manager.set("partner_session", token, expires_at=expires)
        st.session_state.pending_session_cookie = None
    except Exception:
        pass

if not st.session_state.authenticated:
    show_login_page()
else:
    if "token" in st.query_params:
        st.query_params.clear()
    _inject_umami()
    if not st.session_state.get("login_tracked"):
        track_umami_login(st.session_state.partner_email)
        st.session_state.login_tracked = True
    show_dashboard()
