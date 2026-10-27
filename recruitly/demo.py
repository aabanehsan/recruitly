"""Demo accounts created by `recruitly demo`. Shown on the login page only in demo mode."""

DEMO_ACCOUNTS = [
    # (name, email, password, role)
    ("Alex Admin", "admin@demo.recruitly.dev", "demo-admin-2026", "admin"),
    ("Morgan Member", "member@demo.recruitly.dev", "demo-member-2026", "member"),
]

ZOOM = "https://utexas.zoom.us/j/5550101234"

# Interview slots `recruitly demo` creates, relative to today:
# (days from today, start "HH:MM", minutes, how many back to back, location, label, interviewer emails)
DEMO_SLOTS = [
    (1, "18:00", 30, 5, "GSB 2.124", "First round", ["admin@demo.recruitly.dev"]),
    (1, "18:00", 30, 4, ZOOM, "First round", ["member@demo.recruitly.dev"]),
    (2, "17:30", 45, 3, "CBA 3.304", "Final round", ["admin@demo.recruitly.dev", "member@demo.recruitly.dev"]),
]

# Who gets booked: (applicant email, slot group index, position in that group)
DEMO_BOOKINGS = [
    ("jordan.lee@utexas.edu", 0, 0),
    ("priya.raman@utexas.edu", 0, 1),
    ("sofia.delgado@utexas.edu", 0, 3),
    ("marcus.oneil@utexas.edu", 1, 0),
    ("ethan.mcdonald@utexas.edu", 1, 2),
    ("dnguyen@utexas.edu", 2, 0),
]
