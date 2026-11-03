"""Demo data `recruitly demo` creates: accounts (shown on the login page only in demo mode), interview slots,
a scoring rubric, some score sheets and two deliberations with votes."""

DEMO_ACCOUNTS = [
    # (name, email, password, role)
    ("Alex Admin", "admin@demo.recruitly.dev", "demo-admin-2026", "admin"),
    ("Morgan Member", "member@demo.recruitly.dev", "demo-member-2026", "member"),
    # two more members so the demo deliberations have a few voters
    ("Riley Chen", "riley@demo.recruitly.dev", "demo-riley-2026", "member"),
    ("Sam Okafor", "sam@demo.recruitly.dev", "demo-sam-2026", "member"),
]

ZOOM = "https://utexas.zoom.us/j/5550101234"

# Interview slots `recruitly demo` creates, relative to today:
# (days from today, start "HH:MM", minutes, how many back to back, location, label, interviewer emails)
DEMO_SLOTS = [
    (1, "18:00", 30, 5, "GSB 2.124", "First round", ["admin@demo.recruitly.dev"]),
    (1, "18:00", 30, 4, ZOOM, "First round", ["member@demo.recruitly.dev"]),
    (2, "17:30", 45, 3, "CBA 3.304", "Final round", ["admin@demo.recruitly.dev", "member@demo.recruitly.dev"]),
    # yesterday's first round, already scored (see DEMO_SHEETS)
    (-1, "18:00", 30, 4, "GSB 2.124", "First round", ["admin@demo.recruitly.dev", "member@demo.recruitly.dev"]),
]

# Who gets booked: (applicant email, slot group index, position in that group)
DEMO_BOOKINGS = [
    ("jordan.lee@utexas.edu", 0, 0),
    ("priya.raman@utexas.edu", 0, 1),
    ("sofia.delgado@utexas.edu", 0, 3),
    ("marcus.oneil@utexas.edu", 1, 0),
    ("ethan.mcdonald@utexas.edu", 1, 2),
    ("dnguyen@utexas.edu", 2, 0),
    ("dnguyen@utexas.edu", 3, 0),
    ("grace.kim@utexas.edu", 3, 1),
    ("aisha.khan@utexas.edu", 3, 2),
    ("mateo.garcia@gmail.com", 3, 3),
]

# Applicants who made it past the first round in the demo
DEMO_ADVANCED = ["dnguyen@utexas.edu"]

# (name, what to look for, weight)
DEMO_RUBRIC = [
    ("Communication", "Clear, concise answers; listens to the question before answering", 2),
    ("Leadership", "Has owned something (a project, a team, a job) and can talk about the results", 1.5),
    ("Fit with the org", "Collaborative and curious; would make the people around them better", 2),
    ("Professionalism", "On time, prepared, knows what the org does", 1),
]

A, M = "admin@demo.recruitly.dev", "member@demo.recruitly.dev"
# (applicant email, round, scorer, scores in DEMO_RUBRIC order (None = not scored yet), notes, submitted)
DEMO_SHEETS = [
    ("dnguyen@utexas.edu", "First round", A, (5, 4, 5, 4),
     "Really polished. Ran the VITA sign-up table and could explain how he fixed the wait times. "
     "Asked great questions about our consulting projects. Strong yes for final round.", True),
    ("dnguyen@utexas.edu", "First round", M, (4, 5, 4, 5),
     "Leadership story about Beta Alpha Psi was the best I heard all night. A little rehearsed at first, "
     "warmed up quickly.", True),
    ("grace.kim@utexas.edu", "First round", A, (4, 3, 5, 4),
     "Freshman but already knows what she wants out of case comps. Less to point to on leadership, "
     "which is expected.", True),
    ("grace.kim@utexas.edu", "First round", M, (4, 4, 4, 3), "Very easy to talk to. Showed up a few minutes late.",
     True),
    ("aisha.khan@utexas.edu", "First round", A, (3, 3, 4, 4),
     "Thoughtful, but answers ran long. Want to hear more about why us vs. pre-health orgs.", True),
    ("aisha.khan@utexas.edu", "First round", M, (3, None, 4, None), "Half done, finish after the debrief.", False),
    ("mateo.garcia@gmail.com", "First round", A, (3, 4, 3, 3),
     "Transfer with real work experience at the logistics company. Seemed nervous; give him another look.", True),
]

R, S = "riley@demo.recruitly.dev", "sam@demo.recruitly.dev"
# (name, opened how many hours ago, open for how many hours (None = still open),
#  {applicant email: {voter: choice}}, statuses set after it closed)
DEMO_DELIBERATIONS = [
    ("Written app screening", 4 * 24 + 3, 2, {
        "dnguyen@utexas.edu": {A: "yes", M: "yes", R: "yes", S: "yes"},
        "priya.raman@utexas.edu": {A: "yes", M: "yes", R: "yes", S: "yes"},
        "grace.kim@utexas.edu": {A: "yes", M: "yes", R: "yes", S: "abstain"},
        "mateo.garcia@gmail.com": {A: "yes", M: "yes", R: "no", S: "yes"},
        "aisha.khan@utexas.edu": {A: "yes", M: "abstain", R: "yes", S: "no"},
        "kevin.patel@utexas.edu": {A: "no", M: "yes", R: "no", S: "no"},
        "hannah.schultz@utexas.edu": {A: "no", M: "no", R: "yes", S: "abstain"},
        "tyler.brooks@utexas.edu": {A: "no", M: "no", R: "no", S: "abstain"},
        "noahwilliams@utexas.edu": {A: "no", M: "abstain", R: "no", S: "no"},
    }, {"kevin.patel@utexas.edu": "cut", "hannah.schultz@utexas.edu": "cut", "tyler.brooks@utexas.edu": "cut",
        "noahwilliams@utexas.edu": "cut"}),
    # still open: Riley and Sam already voted, so log in as the admin to see the live tally,
    # or as Morgan to vote without seeing it
    ("First-round debrief", 2, None, {
        "dnguyen@utexas.edu": {R: "yes", S: "yes"},
        "grace.kim@utexas.edu": {R: "yes", S: "abstain"},
        "aisha.khan@utexas.edu": {R: "no", S: "yes"},
        "mateo.garcia@gmail.com": {R: "no", S: "no"},
    }, {}),
]
