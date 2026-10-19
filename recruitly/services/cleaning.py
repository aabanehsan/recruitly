"""Turn messy Google Form answers into clean, validated profile fields.

Everything here is a pure function so it is easy to test. ``clean_row`` takes
one form response (already mapped to profile field names) and returns the
cleaned values plus a list of issues. Issues have a level:

- ``error``: the row can't be imported as-is (e.g. missing or invalid email)
- ``warning``: imported, but someone should double check (e.g. unknown major)
- ``fixed``: we changed the value and are telling you what we did
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------- header mapping

# For each profile field: phrases that identify the form question. Checked
# against the normalized header text; the longest/most specific match wins.
HEADER_KEYWORDS: dict[str, list[str]] = {
    "submitted_at": ["timestamp", "submitted at", "submission time"],
    "full_name": ["full name", "your name", "name first and last", "first and last name", "name"],
    "first_name": ["first name", "given name", "legal first name"],
    "last_name": ["last name", "surname", "family name", "legal last name"],
    "preferred_name": ["preferred name", "nickname", "what do you go by", "name you go by"],
    "email": ["email", "e mail", "utexas email", "school email"],
    "eid": ["eid", "ut eid", "student id"],
    "phone": ["phone", "cell", "mobile", "phone number"],
    "major": ["major", "intended major", "primary major", "what is your major"],
    "second_major": ["second major", "double major", "2nd major", "additional major"],
    "minor": ["minor", "certificate", "minors certificates"],
    "classification": ["classification", "year in school", "class standing", "current year", "what year are you"],
    "grad_term": ["graduation", "grad date", "expected graduation", "graduating", "grad year", "class of"],
    "gpa": ["gpa", "grade point"],
    "hometown": ["hometown", "where are you from", "home town"],
    "linkedin": ["linkedin"],
    "resume_url": ["resume", "cv"],
    "instagram": ["instagram", "insta", "ig handle"],
    "involvement": ["involvement", "experience", "organizations", "extracurricular", "activities", "clubs"],
    "why_join": ["why do you want", "why join", "why are you interested", "what interests you", "why"],
    "fun_fact": ["fun fact", "something interesting", "tell us something"],
    "availability": ["availability", "available", "times that work", "interview times"],
    "headshot": ["headshot", "photo", "picture", "professional photo", "upload a photo", "image"],
}


def normalize_header(h: str) -> str:
    h = unicodedata.normalize("NFKC", h).lower()
    h = re.sub(r"\(.*?\)", " ", h)        # drop "(optional)" etc.
    h = re.sub(r"[^a-z0-9]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def map_headers(headers: list[str]) -> dict[str, str | None]:
    """Map each spreadsheet header to a profile field (or None to ignore it).

    Each field is claimed by at most one column: the one with the most
    specific match. Ties go to the earlier column.
    """
    scores: list[tuple[int, int, str, str]] = []  # (score, -col, header, field)
    for col, h in enumerate(headers):
        nh = normalize_header(h)
        if not nh:
            continue
        for fld, phrases in HEADER_KEYWORDS.items():
            for p in phrases:
                if nh == p:
                    score = 1000 + len(p)
                elif re.search(rf"\b{re.escape(p)}\b", nh):
                    score = len(p)
                else:
                    continue
                scores.append((score, -col, h, fld))

    result: dict[str, str | None] = {h: None for h in headers}
    taken: set[str] = set()
    for score, _, h, fld in sorted(scores, reverse=True):
        if result[h] is None and fld not in taken:
            result[h] = fld
            taken.add(fld)
    # A "full name" column is only needed when first/last aren't separate.
    if {"first_name", "last_name"} <= taken:
        for h, f in result.items():
            if f == "full_name":
                result[h] = None
    return result


# ---------------------------------------------------------------- reference data

MAJORS = [
    "Accounting", "Actuarial Science", "Advertising", "Aerospace Engineering", "African and African Diaspora Studies",
    "American Studies", "Anthropology", "Architectural Engineering", "Architecture", "Art History",
    "Asian American Studies", "Astronomy", "Biochemistry", "Biology", "Biomedical Engineering",
    "Business Analytics", "Chemical Engineering", "Chemistry", "Civil Engineering", "Classics",
    "Communication and Leadership", "Communication Studies", "Computational Engineering", "Computer Science",
    "Economics", "Electrical and Computer Engineering", "English", "Environmental Engineering",
    "Environmental Science", "Finance", "Geography", "Geological Sciences", "Government", "Health and Society",
    "History", "Human Development and Family Sciences", "Informatics", "International Business",
    "International Relations and Global Studies", "Journalism", "Kinesiology", "Linguistics", "Management",
    "Management Information Systems", "Marketing", "Mathematics", "Mechanical Engineering", "Neuroscience",
    "Nursing", "Nutrition", "Petroleum Engineering", "Philosophy", "Physics", "Plan II Honors", "Psychology",
    "Public Health", "Radio-Television-Film", "Rhetoric and Writing", "Sociology", "Spanish",
    "Sport Management", "Statistics and Data Science", "Supply Chain Management", "Undeclared",
    "Business Honors", "Economics (BBA)",
]

MAJOR_ALIASES = {
    "cs": "Computer Science", "comp sci": "Computer Science", "compsci": "Computer Science",
    "ece": "Electrical and Computer Engineering", "ee": "Electrical and Computer Engineering",
    "electrical engineering": "Electrical and Computer Engineering",
    "computer engineering": "Electrical and Computer Engineering",
    "mis": "Management Information Systems", "econ": "Economics", "bio": "Biology",
    "biochem": "Biochemistry", "bme": "Biomedical Engineering", "mecha": "Mechanical Engineering",
    "mech e": "Mechanical Engineering", "meche": "Mechanical Engineering", "me": "Mechanical Engineering",
    "chem e": "Chemical Engineering", "cheme": "Chemical Engineering", "che": "Chemical Engineering",
    "civil": "Civil Engineering", "ase": "Aerospace Engineering", "aero": "Aerospace Engineering",
    "math": "Mathematics", "maths": "Mathematics", "stats": "Statistics and Data Science",
    "sds": "Statistics and Data Science", "data science": "Statistics and Data Science",
    "statistics": "Statistics and Data Science", "psych": "Psychology", "neuro": "Neuroscience",
    "gov": "Government", "poli sci": "Government", "political science": "Government",
    "rtf": "Radio-Television-Film", "ib": "International Business", "irg": "International Relations and Global Studies",
    "bhp": "Business Honors", "plan ii": "Plan II Honors", "plan 2": "Plan II Honors",
    "scm": "Supply Chain Management", "supply chain": "Supply Chain Management", "acc": "Accounting",
    "accy": "Accounting", "fin": "Finance", "mktg": "Marketing", "kin": "Kinesiology", "comms": "Communication Studies",
    "info": "Informatics", "i school": "Informatics", "ischool": "Informatics", "undecided": "Undeclared",
}

CLASSIFICATIONS = {
    "Freshman": ["freshman", "freshmen", "first year", "1st year", "1st", "fy", "fish", "year 1", "1"],
    "Sophomore": ["sophomore", "sophmore", "second year", "2nd year", "2nd", "soph", "year 2", "2"],
    "Junior": ["junior", "third year", "3rd year", "3rd", "year 3", "3"],
    "Senior": ["senior", "fourth year", "4th year", "4th", "5th year", "fifth year", "super senior", "year 4", "4"],
    "Transfer": ["transfer", "transfer student"],
    "Graduate": ["grad", "graduate", "graduate student", "masters", "master's", "phd", "grad student"],
}

EMPTY_VALUES = {"", "n/a", "na", "n.a.", "none", "null", "-", "--", "nil", "no", "nope", "not applicable", "tbd"}

# ---------------------------------------------------------------- result types


@dataclass
class Issue:
    field: str
    level: str  # error | warning | fixed
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "level": self.level, "message": self.message}


@dataclass
class CleanResult:
    values: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def add(self, fld: str, level: str, msg: str) -> None:
        self.issues.append(Issue(fld, level, msg))


# ---------------------------------------------------------------- helpers


def basic_clean(value: Any) -> str:
    """Strip whitespace, invisible characters and smart quotes; collapse spaces."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = re.sub(r"[​-‏⁠﻿]", "", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def is_empty(s: str) -> bool:
    return s.strip().lower().strip(".") in EMPTY_VALUES


_NAME_PARTICLES = {"de", "da", "del", "della", "di", "van", "von", "der", "la", "le", "bin", "al"}


def smart_title(name: str) -> str:
    """Title-case a name, handling O'Brien, McDonald, hyphens and particles."""
    def fix_word(w: str, first: bool) -> str:
        if not w:
            return w
        lw = w.lower()
        if not first and lw in _NAME_PARTICLES:
            return lw
        parts = re.split(r"([-'])", lw)
        out = "".join(p.capitalize() if p not in "-'" else p for p in parts)
        if re.match(r"^mc[a-z]", out, re.IGNORECASE):
            out = "Mc" + out[2:3].upper() + out[3:]
        return out

    words = name.split(" ")
    return " ".join(fix_word(w, i == 0) for i, w in enumerate(words))


def clean_name(raw: str, fld: str, res: CleanResult, required: bool) -> str | None:
    s = one_line(basic_clean(raw))
    s = re.sub(r"[^\w\s'\-.]", "", s).strip(" .")
    if not s or is_empty(s):
        if required:
            res.add(fld, "error", "missing")
        return None
    if s.islower() or s.isupper():
        fixed = smart_title(s)
        if fixed != s:
            res.add(fld, "fixed", f"capitalized '{s}' → '{fixed}'")
            s = fixed
    return s[:80]


EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


def clean_email(raw: str, res: CleanResult, domain: str | None) -> str | None:
    s = basic_clean(raw).lower().strip("<>.,; ")
    s = s.removeprefix("mailto:")
    if " " in s:
        res.add("email", "fixed", f"removed spaces from '{s}'")
        s = s.replace(" ", "")
    if not s:
        res.add("email", "error", "missing")
        return None
    # common typos
    typos = {"@utexas.com": "@utexas.edu", "@utexas.ed": "@utexas.edu", "@gmial.com": "@gmail.com",
             "@gmai.com": "@gmail.com", "@gmail.co": "@gmail.com", "@yahoo.co": "@yahoo.com",
             "@utexas.edu.edu": "@utexas.edu", "@eid.utexas.edu": "@utexas.edu"}
    for bad, good in typos.items():
        if s.endswith(bad):
            res.add("email", "fixed", f"corrected domain typo '{bad}' → '{good}'")
            s = s[: -len(bad)] + good
            break
    if not EMAIL_RE.match(s):
        res.add("email", "error", f"'{raw}' is not a valid email address")
        return None
    if domain and not s.endswith("@" + domain.lower()):
        res.add("email", "warning", f"not a @{domain} address")
    return s


EID_RE = re.compile(r"^[a-z]{2,3}[0-9]{2,6}[a-z]?$")


def clean_eid(raw: str, res: CleanResult) -> str | None:
    s = re.sub(r"\s+", "", basic_clean(raw)).lower()
    if not s or is_empty(s):
        return None
    if not EID_RE.match(s):
        res.add("eid", "warning", f"'{raw}' doesn't look like a UT EID (e.g. ab12345)")
    return s[:20]


def clean_phone(raw: str, res: CleanResult) -> str | None:
    s = basic_clean(raw)
    if not s or is_empty(s):
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        out = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        if out != s:
            res.add("phone", "fixed", f"formatted '{s}' → '{out}'")
        return out
    res.add("phone", "warning", f"'{s}' isn't a 10-digit US number; kept as entered")
    return one_line(s)[:30]


def match_major(raw: str) -> tuple[str | None, bool]:
    """Return (canonical major, exact) for one major string."""
    s = one_line(basic_clean(raw))
    s = re.sub(r"\b(b\.?s\.?|b\.?a\.?|bba|major|degree|in)\b", " ", s, flags=re.IGNORECASE)
    key = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    key = re.sub(r"\s+", " ", key).strip()
    if not key:
        return None, True
    if key in MAJOR_ALIASES:
        return MAJOR_ALIASES[key], True
    lower_map = {m.lower(): m for m in MAJORS}
    if key in lower_map:
        return lower_map[key], True
    close = difflib.get_close_matches(key, list(lower_map), n=1, cutoff=0.82)
    if close:
        return lower_map[close[0]], False
    # "Computer Science (Turing Scholars)" → contains a known major
    for lm, m in sorted(lower_map.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(lm)}\b", key):
            return m, False
    return None, False


def split_majors(raw: str) -> list[str]:
    parts = re.split(r"\s*(?:/|,|;|&|\+|\band\b|\bwith\b|\bdouble major\b)\s*", raw, flags=re.IGNORECASE)
    return [p for p in (x.strip() for x in parts) if p]


def clean_majors(raw_major: str, raw_second: str, res: CleanResult) -> tuple[str | None, str | None]:
    raw_major, raw_second = basic_clean(raw_major), basic_clean(raw_second)
    if is_empty(raw_major):
        raw_major = ""
    if is_empty(raw_second):
        raw_second = ""
    candidates = split_majors(raw_major) if raw_major else []
    if raw_second:
        candidates += split_majors(raw_second)
    # Recombine pieces that were split wrongly, e.g. "Electrical and Computer Engineering"
    if raw_major and match_major(raw_major)[0] and match_major(raw_major)[1]:
        candidates = [raw_major] + (split_majors(raw_second) if raw_second else [])

    out: list[str] = []
    for c in candidates:
        m, exact = match_major(c)
        if m is None:
            title = smart_title(one_line(c)) if c.islower() or c.isupper() else one_line(c)
            res.add("major", "warning", f"'{c}' isn't in the major list; kept as entered")
            m = title[:120]
        elif not exact or m.lower() != one_line(c).lower():
            res.add("major", "fixed", f"'{one_line(c)}' → '{m}'")
        if m not in out:
            out.append(m)
    if len(out) > 2:
        res.add("major", "warning", f"more than two majors listed; kept '{out[0]}' and '{out[1]}'")
    return (out[0] if out else None), (out[1] if len(out) > 1 else None)


def clean_classification(raw: str, res: CleanResult) -> str | None:
    s = one_line(basic_clean(raw)).lower().strip(".")
    if not s or is_empty(s):
        return None
    for label, options in CLASSIFICATIONS.items():
        if s in options or any(re.search(rf"\b{re.escape(o)}\b", s) for o in options if len(o) > 2):
            if label.lower() != s:
                res.add("classification", "fixed", f"'{raw.strip()}' → '{label}'")
            return label
    res.add("classification", "warning", f"couldn't recognize '{raw.strip()}'; kept as entered")
    return one_line(basic_clean(raw))[:30]


MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"], start=1)}
MONTH_ABBR = {k[:3]: v for k, v in MONTHS.items()}


def clean_grad_term(raw: str, res: CleanResult, today: datetime | None = None) -> str | None:
    """Normalize to 'May 2028' / 'Dec 2027' / 'Aug 2028'."""
    s = one_line(basic_clean(raw)).lower()
    if not s or is_empty(s):
        return None
    today = today or datetime.now()
    year = None
    m = re.search(r"\b(20\d{2})\b", s)
    if m:
        year = int(m.group(1))
    else:
        m = re.search(r"(?:'|’|\b)(\d{2})\b", s)
        if m:
            year = 2000 + int(m.group(1))
    if year is None:
        res.add("grad_term", "warning", f"couldn't find a year in '{raw.strip()}'")
        return one_line(basic_clean(raw))[:20]

    month = None
    if re.search(r"\b(spring|spr)\b", s):
        month = 5
    elif re.search(r"\b(fall|fa|winter|dec)\b", s):
        month = 12
    elif re.search(r"\b(summer|sum|aug)\b", s):
        month = 8
    else:
        for name, num in {**MONTHS, **MONTH_ABBR}.items():
            if re.search(rf"\b{name}\b", s):
                month = num
                break
        if month is None:
            m2 = re.match(r"^(\d{1,2})\s*[/\-.]\s*(?:\d{1,2}\s*[/\-.]\s*)?(?:20)?\d{2}$", s)
            if m2:
                month = int(m2.group(1))
    assumed = month is None
    if assumed:
        month = 5
    label = {5: "May", 12: "Dec", 8: "Aug"}.get(month)
    if label is None:  # other months → closest commencement
        label = "May" if month <= 6 else "Aug" if month <= 9 else "Dec"
    out = f"{label} {year}"
    if not (today.year - 1 <= year <= today.year + 7):
        res.add("grad_term", "warning", f"graduation year {year} looks unusual")
    if assumed:
        res.add("grad_term", "fixed", f"'{raw.strip()}' → '{out}' (no semester given, assumed May)")
    elif out.lower() != s:
        res.add("grad_term", "fixed", f"'{raw.strip()}' → '{out}'")
    return out


def clean_gpa(raw: str, res: CleanResult) -> float | None:
    s = one_line(basic_clean(raw)).lower()
    if not s or is_empty(s) or re.search(r"first semester|incoming|no gpa|\bn/?a\b|not yet|freshman", s):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?", s)
    if not m:
        res.add("gpa", "warning", f"couldn't read a GPA from '{raw.strip()}'")
        return None
    val = float(m.group(1))
    scale = float(m.group(2)) if m.group(2) else None
    if scale and scale not in (4.0,) and scale > 0:
        val = round(val / scale * 4.0, 2)
        res.add("gpa", "fixed", f"converted '{raw.strip()}' to a 4.0 scale ({val})")
    if val > 4.0 or val < 0:
        res.add("gpa", "warning", f"GPA '{raw.strip()}' is outside 0.0-4.0; left blank")
        return None
    return round(val, 2)


def _url(s: str) -> str:
    if not re.match(r"^https?://", s, re.IGNORECASE):
        s = "https://" + s.lstrip("/")
    return s


def clean_linkedin(raw: str, res: CleanResult) -> str | None:
    s = basic_clean(raw).strip()
    if not s or is_empty(s):
        return None
    s = s.split()[0].rstrip("/.,")
    m = re.search(r"linkedin\.com/(in|pub)/([^/?#\s]+)", s, re.IGNORECASE)
    if m:
        out = f"https://www.linkedin.com/in/{m.group(2)}"
    elif re.fullmatch(r"@?[A-Za-z0-9\-_%]{3,100}", s):
        out = f"https://www.linkedin.com/in/{s.lstrip('@')}"
    else:
        res.add("linkedin", "warning", f"'{raw.strip()}' doesn't look like a LinkedIn profile link")
        return _url(s)[:300]
    if out != s:
        res.add("linkedin", "fixed", "normalized LinkedIn link")
    return out


def clean_url(raw: str, fld: str, res: CleanResult) -> str | None:
    s = basic_clean(raw)
    if not s or is_empty(s):
        return None
    s = s.split()[0]
    if not re.search(r"\.[a-z]{2,}", s, re.IGNORECASE):
        res.add(fld, "warning", f"'{raw.strip()}' doesn't look like a link")
        return one_line(s)[:500]
    return _url(s)[:500]


def clean_instagram(raw: str, res: CleanResult) -> str | None:
    s = basic_clean(raw)
    if not s or is_empty(s):
        return None
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", s)
    handle = m.group(1) if m else s.strip().lstrip("@").split()[0]
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
        res.add("instagram", "warning", f"'{raw.strip()}' doesn't look like an Instagram handle")
        return one_line(s)[:80]
    return "@" + handle.lower()


def clean_text(raw: str, long: bool) -> str | None:
    s = basic_clean(raw)
    if not s:
        return None
    if not long and is_empty(s):
        return None
    if long:
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()[:5000]
    return one_line(s)[:200]


DATE_FORMATS = ["%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d"]


def parse_timestamp(raw: str) -> datetime | None:
    s = basic_clean(raw)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


DRIVE_ID_RES = [
    re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})"),
    re.compile(r"/d/([A-Za-z0-9_-]{10,})"),
]


def drive_file_id(url: str) -> str | None:
    for r in DRIVE_ID_RES:
        m = r.search(url)
        if m:
            return m.group(1)
    return None


def clean_headshot(raw: str, res: CleanResult) -> str | None:
    s = basic_clean(raw)
    if not s or is_empty(s):
        res.add("headshot", "warning", "no headshot submitted")
        return None
    first = re.split(r"[,\s]+", s)[0]  # Forms joins multiple uploads with ", "
    if not re.match(r"^https?://", first):
        res.add("headshot", "warning", f"headshot '{first[:60]}' isn't a link")
        return None
    return first


# ---------------------------------------------------------------- main entry


def split_full_name(full: str) -> tuple[str, str]:
    parts = one_line(full).split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def clean_row(row: dict[str, str], email_domain: str | None = None, today: datetime | None = None) -> CleanResult:
    """Clean one form response. ``row`` maps profile field names to raw strings."""
    res = CleanResult()
    get = lambda k: row.get(k) or ""  # noqa: E731

    first, last = get("first_name"), get("last_name")
    if not first and not last and get("full_name"):
        first, last = split_full_name(basic_clean(get("full_name")))
        if not last:
            res.add("last_name", "warning", "only one name given")
    v = res.values
    v["first_name"] = clean_name(first, "first_name", res, required=True)
    v["last_name"] = clean_name(last, "last_name", res, required=False) or ""
    if not v["last_name"] and not any(i.field == "last_name" for i in res.issues):
        res.add("last_name", "warning", "missing")
    v["preferred_name"] = clean_name(get("preferred_name"), "preferred_name", res, required=False)
    if v["preferred_name"] and v["preferred_name"] == v["first_name"]:
        v["preferred_name"] = None
    v["email"] = clean_email(get("email"), res, email_domain)
    v["eid"] = clean_eid(get("eid"), res)
    v["phone"] = clean_phone(get("phone"), res)
    v["major"], v["second_major"] = clean_majors(get("major"), get("second_major"), res)
    v["minor"] = clean_text(get("minor"), long=False)
    v["classification"] = clean_classification(get("classification"), res)
    v["grad_term"] = clean_grad_term(get("grad_term"), res, today)
    v["gpa"] = clean_gpa(get("gpa"), res)
    v["hometown"] = clean_text(get("hometown"), long=False)
    if v["hometown"] and (v["hometown"].islower() or v["hometown"].isupper()):
        v["hometown"] = smart_title(v["hometown"]).replace(" Tx", " TX").replace(", Tx", ", TX")
    v["linkedin"] = clean_linkedin(get("linkedin"), res)
    v["resume_url"] = clean_url(get("resume_url"), "resume_url", res)
    v["instagram"] = clean_instagram(get("instagram"), res)
    for f in ("involvement", "why_join", "fun_fact", "availability"):
        v[f] = clean_text(get(f), long=True)
    v["headshot_source"] = clean_headshot(get("headshot"), res) if "headshot" in row else None
    ts = parse_timestamp(get("submitted_at")) if get("submitted_at") else None
    v["submitted_at"] = ts.isoformat() if ts else None
    return res
