"""Regenerate recruitly/sample_data/: a deliberately messy Google Form export plus
placeholder headshots, and a later copy of the sheet for the sync demo. All people are fictional. Run: python scripts/make_sample_data.py"""

from __future__ import annotations

import csv
import io
import random
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "recruitly" / "sample_data"

HEADERS = [
    "Timestamp", "Email Address", "First Name", "Last Name", "Preferred name (optional)", "UT EID",
    "Phone number", "What is your major?", "Second major (if any)", "Minors / certificates",
    "What year are you?", "Expected graduation date", "Cumulative GPA", "Hometown", "LinkedIn profile URL",
    "Link to your resume", "Instagram handle", "What organizations or experiences are you involved in?",
    "Why do you want to join?", "Tell us a fun fact about yourself!", "Which interview times work for you?",
    "Upload a professional headshot",
]

# first, last, preferred, email, eid, phone, major, second, minor, year, grad, gpa, hometown, linkedin,
# resume, insta, involvement, why, fun fact, availability  — intentionally inconsistent formatting
PEOPLE = [
    ("jordan", "lee", "", "Jordan.Lee@UTEXAS.EDU", "JL48213", "512.555.0143", "comp sci", "", "Business Foundations",
     "sophomore", "spring 2028", "3.71", "plano, tx", "linkedin.com/in/jordanlee-dev", "", "@jordan.lee",
     "Longhorn Developers, intramural soccer", "I want to be around people who push each other professionally.",
     "I've been to 14 national parks.", "Tue/Thu evenings"),
    ("Priya", "Raman", "Pri", "priya.raman@utexas.edu", "pr27719", "(469) 555-0192", "Finance", "MIS", "",
     "Junior", "May 2027", "3.9/4.0", "Frisco, TX", "https://www.linkedin.com/in/priyaraman/",
     "drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view", "", "Texas Finance Association, TA for Accounting 311",
     "The mentorship. Every member I've met has been genuinely helpful.", "I can solve a Rubik's cube in under a minute.",
     "Any weekday after 5"),
    ("MARCUS", "O'NEIL", "", "marcus.oneil@utexas.com", "mo5521", "2145550178", "Economics and Math", "", "",
     "1st year", "'29", "first semester", "dallas", "marcus-oneil", "", "", "Debate team in high school",
     "Looking for a community and to learn about consulting.", "I play the trumpet.", "Weekends"),
    ("Sofia", "Delgado", "", "sofia.delgado@utexas.edu", "sd33018", "+1 (737) 555-0110", "Electrical and Computer Engineering",
     "", "", "Senior", "Dec 2026", "3.45", "San Antonio, TX", "", "", "sofiad",
     "IEEE, Society of Women Engineers, research in a power systems lab",
     "I want to round out my technical background with business skills before I graduate.",
     "I was on a cooking show as a kid.", "Mon/Wed 6-9pm"),
    ("ethan", "mcdonald", "", "ethan.mcdonald@utexas.edu", "em2209", "512-555-0127", "MIS", "", "Elements of Computing",
     "sophomore", "2028", "3.62", "austin", "linkedin.com/in/ethan-mcdonald", "", "", "Freshman Interest Group, part-time IT help desk",
     "I liked how welcoming everyone was at info night.", "I have a twin sister.", "Flexible"),
    ("Aisha", "Khan", "", "aisha.khan@utexas.edu", "ak90231", "832 555 0166", "biochem", "", "", "Freshman",
     "May 2029", "N/A", "Sugar Land, TX", "", "", "@aishakhan", "Pre-health society, volunteer at Dell Children's",
     "I want to build professional skills alongside my pre-med track.", "I've read every Harry Potter book four times.",
     "Thursday afternoons"),
    ("Daniel", "Nguyen", "Danny", "dnguyen@utexas.edu", "dn4471", "713-555-0151", "Accounting", "Finance", "",
     "Junior", "5/2027", "3.88", "Houston, TX", "linkedin.com/in/daniel-nguyen-acc", "", "", "Beta Alpha Psi, VITA tax volunteer",
     "I want to grow as a leader.", "I can name every country in the world.", "Any time"),
    ("Chloe", "Bennett", "", "", "cb12345", "512-555-0109", "Advertising", "", "", "Sophomore", "Spring 2028", "3.5",
     "Fort Worth, TX", "", "", "", "Texas Media Society", "Creative community.", "I do pottery.", "Evenings"),
    ("Jordan", "Lee", "", "jordan.lee@utexas.edu", "jl48213", "512-555-0143", "Computer Science", "", "Business Foundations",
     "Sophomore", "May 2028", "3.74", "Plano, TX", "linkedin.com/in/jordanlee-dev", "", "@jordan.lee",
     "Longhorn Developers, intramural soccer, HackTX volunteer",
     "I want to be around people who push each other professionally. (Updated answer!)",
     "I've been to 15 national parks now.", "Tue/Thu evenings"),
    ("Mateo", "Garcia", "", "mateo.garcia@gmial.com", "mg77120", "956-555-0182", "Supply chain", "", "", "Transfer",
     "Fall 2027", "3.3", "Brownsville, TX", "", "", "", "Transferred from UTRGV, worked at a logistics company",
     "I want to build my network at UT as a transfer.", "I've run two marathons.", "Mon-Fri mornings"),
    ("Grace", "Kim", "", "grace.kim@utexas.edu", "gk51190", "469-555-0137", "Business Honors", "", "", "Freshman",
     "May 2030", "", "Coppell, TX", "", "", "@gracek", "Business Honors Program, Texas Running Club",
     "I'm excited about the case competitions.", "I've lived in four countries.", "Tue evenings"),
    ("Noah", "Williams", "", "noah williams@utexas.edu", "nw10001", "123", "Kinesology", "", "", "Senior", "May 2026",
     "4.6", "Waco, TX", "", "", "", "Club basketball", "To meet new people.", "I'm 6'8\".", "Weekends"),
    # cut after the written-application screening vote in the demo
    ("Tyler", "brooks", "", "tyler.brooks@utexas.edu", "tb30417", "512-555-0175", "marketing", "", "", "Junior",
     "May 2027", "3.1", "Round Rock, TX", "", "", "@tbrooks", "Intramural flag football",
     "My roommate is a member and says it's fun.", "I've never seen Star Wars.", "Fridays"),
    ("Hannah", "Schultz", "", "Hannah.Schultz@utexas.edu", "hs66120", "281.555.0144", "Psych", "",
     "Business Foundations", "2nd year", "Spring 2028", "3.55", "Katy, TX", "linkedin.com/in/hannahschultz", "", "",
     "Psychology Student Association, barista at a campus coffee shop", "I want to explore consulting.",
     "I can juggle.", "Wednesday evenings"),
    ("Kevin", "patel", "", "kevin.patel@utexas.edu", "kp88213", "(512) 555-0196", "Finance", "Economics", "",
     "senior", "Dec 2026", "3.79", "Austin, TX", "linkedin.com/in/kevinpatel", "", "",
     "Investment club, internship at a regional bank", "I want to give back to younger students.",
     "I've been skydiving.", "Weekday afternoons"),
]

# sheet_sync.csv = the same sheet a few days later, for the demo's "Sync now": two new responses and two people
# who edited theirs (Google Forms "edit after submit" updates the row and its timestamp).
SYNC_NEW = [
    ("Liam", "Ortiz", "", "liam.ortiz@utexas.edu", "lo40912", "512 555 0188", "statistics", "", "",
     "Sophomore", "May 2028", "3.67", "El Paso, TX", "linkedin.com/in/liam-ortiz", "", "@liamortiz",
     "Texas Data Science club, tutor at the Sanger Learning Center",
     "I heard about the pro bono consulting projects at the org fair and want in.",
     "I've beaten my dad at chess exactly once.", "Mon/Wed evenings"),
    ("maya", "johnson", "", "Maya.Johnson@utexas.edu", "mj22871", "(214) 555-0103", "Marketing", "Plan II", "",
     "freshman", "Spring 2030", "", "Dallas, TX", "", "", "",
     "Plan II, Texas Women in Business freshman committee", "I want to learn how to run a real client project.",
     "I've seen every Pixar movie in theaters.", "Thursdays after 4"),
]
SYNC_EDITS = {  # email in PEOPLE → {column index in the person tuple: new answer}
    "priya.raman@utexas.edu": {19: "Weekdays after 5, not Fridays"},
    "sofia.delgado@utexas.edu": {11: "3.52", 16: "IEEE, Society of Women Engineers, power systems research lab, Longhorn Racing"},
}


def headshot(seed: int) -> bytes:
    rng = random.Random(seed)
    w, h = 600, 750
    bg1 = tuple(rng.randint(140, 220) for _ in range(3))
    bg2 = tuple(max(0, c - 60) for c in bg1)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(bg1[i] * (1 - t) + bg2[i] * t) for i in range(3)))
    skin = rng.choice([(241, 206, 178), (224, 172, 135), (198, 134, 96), (141, 85, 54), (95, 60, 40)])
    shirt = tuple(rng.randint(20, 90) for _ in range(3))
    d.ellipse([90, 520, 510, 900], fill=shirt)
    d.rectangle([255, 430, 345, 560], fill=skin)
    d.ellipse([190, 210, 410, 470], fill=skin)
    hair = tuple(rng.randint(10, 70) for _ in range(3))
    d.chord([180, 190, 420, 400], 180, 360, fill=hair)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, p in enumerate(PEOPLE):
        ts = f"9/{2 + i}/2026 {10 + i % 9}:{(i * 7) % 60:02d}:{(i * 13) % 60:02d}"
        if i == 8:  # Jordan's resubmission comes later than the first one
            ts = "9/14/2026 21:05:44"
        link = f"https://drive.google.com/open?id=1demoHeadshot{i:02d}xxxxxxxxxx" if i not in (5, 11) else ""
        rows.append([ts, p[3], p[0], p[1], p[2], *p[4:], link])
    with open(OUT / "form_responses.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADERS)
        w.writerows(rows)

    sync_rows = []
    for row, p in zip(rows, PEOPLE):
        edits = SYNC_EDITS.get(p[3])
        if edits:
            p = list(p)
            for col, val in edits.items():
                p[col] = val
            row = ["11/3/2026 20:41:09", p[3], p[0], p[1], p[2], *p[4:], row[-1]]
        sync_rows.append(row)
    for i, p in enumerate(SYNC_NEW):
        sync_rows.append([f"11/{4 + i}/2026 {19 + i}:12:30", p[3], p[0], p[1], p[2], *p[4:], ""])
    with open(OUT / "sheet_sync.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADERS)
        w.writerows(sync_rows)

    with zipfile.ZipFile(OUT / "headshots.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for i, p in enumerate(PEOPLE):
            if i in (5, 8, 11):  # some people didn't upload; Jordan uploaded once
                continue
            name = f"{p[0].title()} {p[1].title()}"
            zf.writestr(f"Fall Rush Application (File responses)/IMG_{2040 + i} - {name}.jpg", headshot(i))
        zf.writestr("Fall Rush Application (File responses)/IMG_9999 - Someone Else.jpg", headshot(99))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
