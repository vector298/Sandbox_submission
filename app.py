"""A tiny scoreboard with durable storage.
 
    python app.py submit <id> <team> <points> <ADD|UNDO> [refers_to]
    python app.py score <team>
    python app.py leaderboard
    python app.py explain <id>
    python app.py import <events.json>     (helper: load a file of events)
 
Storage: one SQLite file (scoreboard.db, or the path in $APP_DB).
Every total is rebuilt from the stored events by replay(), never kept as a number.
 
Exit codes: 0 ok, 1 conflict (not applied), 2 invalid input, 3 damaged database, 4 database busy.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
 
from replay import load_events, replay
 
DB_PATH = os.environ.get("APP_DB", "scoreboard.db")
BUSY_TIMEOUT = float(os.environ.get("APP_BUSY_TIMEOUT", "5"))  # seconds to wait for another writer
 
TEAMS = ("A", "B", "C")
MAX_POINTS = 1000
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
POINTS_RE = re.compile(r"[+-]?[0-9]{1,6}")
 
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,      -- arrival order = position in the log
    id          TEXT    NOT NULL UNIQUE,                -- one stored event per id (first one wins)
    team        TEXT    NOT NULL CHECK (team IN ('A','B','C')),
    points      INTEGER NOT NULL CHECK (points BETWEEN -1000 AND 1000),
    action      TEXT    NOT NULL CHECK (action IN ('ADD','UNDO')),
    refers_to   TEXT,
    received_at TEXT    NOT NULL,
    CHECK ((action = 'UNDO') = (refers_to IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS attempts (                   -- every submit call, kept for 'explain'
    n         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id  TEXT,
    detail    TEXT NOT NULL,                            -- what was submitted, as typed (shortened)
    verdict   TEXT NOT NULL CHECK (verdict IN ('saved','retry','conflict','invalid')),
    reason    TEXT,
    at        TEXT NOT NULL
);
"""
 
 
class UserError(Exception):
    def __init__(self, message, code=2, label="INVALID"):
        super().__init__(message)
        self.code = code
        self.label = label
 
 
def show(value, limit=24):
    """Printable, shortened form of any input, so a huge value never floods the screen or the database."""
    try:
        text = value if isinstance(value, str) else str(value)
    except ValueError:  # an integer with thousands of digits cannot be turned into text
        return "<a number with too many digits>"
    return text if len(text) <= limit else f"{text[:limit]}... ({len(text)} characters)"
 
 
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
 
 
# ---------------------------------------------------------------- validation
 
def clean(id_, team, points, action, refers_to):
    """Check one submission. Returns a clean dict or raises UserError."""
    if not isinstance(id_, str) or not ID_RE.fullmatch(id_):
        raise UserError(f"id {show(id_)} is not valid: use 1 to 32 letters, digits, '-' or '_'")
    if team is None or team == "":
        raise UserError("team is required (A, B or C)")
    if team not in TEAMS:
        raise UserError(f"unknown team {show(team)}: valid teams are {', '.join(TEAMS)}")
    if action not in ("ADD", "UNDO"):
        raise UserError(f"action {show(action)} is not valid: use ADD or UNDO")
    try:
        text = str(points)
    except ValueError:
        raise UserError("points has too many digits")
    if isinstance(points, bool) or not POINTS_RE.fullmatch(text):
        raise UserError(f"points {show(points)} must be a whole number such as 25 or -10 (at most 6 digits)")
    value = int(text)
    if abs(value) > MAX_POINTS:
        raise UserError(f"points {value:+d} is outside the allowed range of -{MAX_POINTS} to {MAX_POINTS}")
 
    if action == "UNDO":
        if refers_to is None or refers_to == "":
            raise UserError("an UNDO needs refers_to: the id of the event it undoes")
        if not isinstance(refers_to, str) or not ID_RE.fullmatch(refers_to):
            raise UserError(f"refers_to {show(refers_to)} is not a valid id")
        if refers_to == id_:
            raise UserError("an event cannot undo itself")
        if value != 0:
            raise UserError("an UNDO carries no points: use 0")
    else:
        if refers_to is not None and refers_to != "":
            raise UserError("only an UNDO may have refers_to")
        refers_to = None
    return {"id": id_, "team": team, "points": value, "action": action, "refers_to": refers_to}
 
 
def describe(team, points, action, refers_to):
    text = f"team={show(team)} points={show(points)} action={show(action)}"
    if refers_to is not None and refers_to != "":
        text += f" refers_to={show(refers_to)}"
    return text
 
 
# ---------------------------------------------------------------- storage
 
def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=BUSY_TIMEOUT, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous = FULL")   # fsync before COMMIT returns
    conn.executescript(SCHEMA)
    return conn
 
 
@contextmanager
def snapshot(conn):
    """Read several tables as one consistent view."""
    conn.execute("BEGIN")
    try:
        yield
    finally:
        if conn.in_transaction:
            conn.execute("COMMIT")
 
 
def load_log(conn):
    rows = conn.execute("SELECT seq, id, team, points, action, refers_to FROM events ORDER BY seq").fetchall()
    return [{"row": r["seq"], "id": r["id"], "team": r["team"], "points": r["points"],
             "action": r["action"], "refers_to": r["refers_to"]} for r in rows]
 
 
def crash_hook(point):
    """Test hook for 4c: simulate the process being killed at one exact moment."""
    if os.environ.get("APP_TEST_CRASH") == point:
        os._exit(99)
 
 
def submit_event(conn, id_, team, points, action, refers_to=None):
    """Store one event. Returns {"verdict": saved|retry|conflict, ...}. Raises UserError if invalid.
 
    The whole decision (look up the id, insert, write the audit row) happens in ONE
    transaction that holds the write lock, so two submits can never both see "id not found".
    """
    try:
        event = clean(id_, team, points, action, refers_to)
    except UserError as err:
        safe_id = id_ if isinstance(id_, str) and ID_RE.fullmatch(id_) else None
        conn.execute("INSERT INTO attempts (event_id, detail, verdict, reason, at) VALUES (?,?,?,?,?)",
                     (safe_id, describe(team, points, action, refers_to), "invalid", str(err), now()))
        raise
 
    detail = describe(event["team"], event["points"], event["action"], event["refers_to"])
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT * FROM events WHERE id = ?", (event["id"],)).fetchone()
        if existing is None:
            cur = conn.execute(
                "INSERT INTO events (id, team, points, action, refers_to, received_at) VALUES (?,?,?,?,?,?)",
                (event["id"], event["team"], event["points"], event["action"], event["refers_to"], now()))
            verdict, seq, reason = "saved", cur.lastrowid, None
        else:
            same = all(existing[k] == event[k] for k in ("team", "points", "action", "refers_to"))
            seq = existing["seq"]
            if same:
                verdict, reason = "retry", "same id and same details as the stored event; nothing changed"
            else:
                verdict, reason = "conflict", "a different event with this id is already stored; first one wins"
        conn.execute("INSERT INTO attempts (event_id, detail, verdict, reason, at) VALUES (?,?,?,?,?)",
                     (event["id"], detail, verdict, reason, now()))
        crash_hook("before_commit")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    crash_hook("after_commit")   # data is safe, but the user has not been told yet
    return {"verdict": verdict, "event": event, "existing": existing, "seq": seq}
 
 
# ---------------------------------------------------------------- commands
 
def outcome_line(conn, id_):
    """Stored is not the same as counted: say what replay() makes of this event right now."""
    with snapshot(conn):
        events = load_log(conn)
    _, outcomes = replay(events)
    o = next(o for o in outcomes if o["id"] == id_)
    return f"{o['outcome']} - {o['explanation']}"
 
 
def cmd_submit(conn, args):
    result = submit_event(conn, args.id, args.team, args.points, args.action, args.refers_to)
    e, seq = result["event"], result["seq"]
    what = (f"undo of {e['refers_to']} by team {e['team']}" if e["action"] == "UNDO"
            else f"team {e['team']} {e['points']:+d}")
    if result["verdict"] == "saved":
        print(f"SAVED: {e['id']} ({what}) at log position {seq}")
        print(f"  Outcome: {outcome_line(conn, e['id'])}")
        return 0
    if result["verdict"] == "retry":
        print(f"ALREADY SAVED: {e['id']} was received before with the same details (log position {seq}). Nothing changed.")
        print(f"  Outcome: {outcome_line(conn, e['id'])}")
        return 0
    old = result["existing"]
    print(f"REJECTED: {e['id']} already exists with different details "
          f"(team {old['team']}, {old['action']}, {old['points']:+d}). First one wins, so this copy was not applied. "
          f"It is kept in the history: python app.py explain {e['id']}")
    return 1
 
 
def cmd_score(conn, args):
    if args.team == "":
        raise UserError("team is required (A, B or C)")
    if args.team not in TEAMS:
        raise UserError(f"unknown team {show(args.team)}: valid teams are {', '.join(TEAMS)}")
    with snapshot(conn):
        events = load_log(conn)
    scores, _ = replay(events)
    print(f"Team {args.team}: {scores[args.team]}")
    return 0
 
 
def cmd_leaderboard(conn, args):
    with snapshot(conn):
        events = load_log(conn)
        conflicts = conn.execute("SELECT event_id, COUNT(*) AS n FROM attempts WHERE verdict = 'conflict' "
                                 "GROUP BY event_id ORDER BY event_id").fetchall()
    scores, outcomes = replay(events)
    print("Rank  Team  Points")
    for team, points in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])):
        rank = 1 + sum(1 for other in scores.values() if other > points)
        print(f"{rank:<5} {team:<5} {points:>6}")
    target = {e["id"]: e["refers_to"] for e in events}
    pending = [o["id"] for o in outcomes if o["outcome"] == "Pending"]
    if pending:
        print("Pending UNDOs (target not received yet): " + ", ".join(f"{i} -> {target[i]}" for i in pending))
    if conflicts:
        print("Conflicting copies rejected (first one wins): " + ", ".join(f"{c['event_id']} x{c['n']}" for c in conflicts))
    return 0
 
 
def cmd_explain(conn, args):
    with snapshot(conn):
        events = load_log(conn)
        stored = conn.execute("SELECT * FROM events WHERE id = ?", (args.id,)).fetchone()
        history = conn.execute("SELECT * FROM attempts WHERE event_id = ? ORDER BY n", (args.id,)).fetchall()
    if stored is None and not history:
        print(f"No event with id {show(args.id)} has been submitted.")
        return 1
    print(f"Event {show(args.id)}")
    if stored is not None:
        _, outcomes = replay(events)
        outcome = next(o for o in outcomes if o["id"] == args.id)
        extra = f", undoing {stored['refers_to']}" if stored["action"] == "UNDO" else ""
        print(f"  Stored at log position {stored['seq']}: team {stored['team']}, {stored['points']:+d}, "
              f"{stored['action']}{extra} (received {stored['received_at']})")
        print(f"  Outcome: {outcome['outcome']} - {outcome['explanation']}")
        undone_by = [o["id"] for o in outcomes
                     if o["outcome"] == "Accepted" and o["explanation"].startswith("UNDO")
                     and next(e for e in events if e["id"] == o["id"])["refers_to"] == args.id]
        if undone_by:
            print(f"  Undone by: {', '.join(undone_by)}")
    else:
        print("  No event is stored under this id (every submission was rejected).")
    tally = {}
    for h in history:
        tally[h["verdict"]] = tally.get(h["verdict"], 0) + 1
    print(f"  Submission history ({len(history)}: " + ", ".join(f"{n} {v}" for v, n in tally.items()) + "):")
    shown = history if len(history) <= 10 else history[:5] + [None] + history[-5:]
    for h in shown:
        if h is None:   # a long run of retries would otherwise flood the screen
            print(f"    ... {len(history) - 10} more submissions not shown ...")
            continue
        reason = f" - {h['reason']}" if h["reason"] else ""
        print(f"    #{h['n']:<3} {h['verdict']:<8} {h['detail']}{reason}")
    return 0
 
 
def cmd_import(conn, args):
    try:
        with open(args.path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as err:   # missing file, not JSON, bad encoding, absurdly large number
        raise UserError(f"cannot read {show(args.path, 60)}: {show(err, 80)}")
    items = data.get("transactions") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise UserError('expected a list of events, or an object with a "transactions" list')
    counts = {"saved": 0, "retry": 0, "conflict": 0, "invalid": 0}
    for position, item in enumerate(items, start=1):
        try:
            if not isinstance(item, dict):
                raise UserError("this entry is not an object")
            missing = [k for k in ("id", "team", "points", "action") if k not in item]
            if missing:
                raise UserError("missing field(s): " + ", ".join(missing))
            result = submit_event(conn, item["id"], item["team"], item["points"], item["action"], item.get("refers_to"))
            counts[result["verdict"]] += 1
            print(f"entry {position:>2}: {show(item['id'])} {result['verdict']}")
        except UserError as err:
            counts["invalid"] += 1
            print(f"entry {position:>2}: invalid - {err}")
    print(f"Imported: {counts['saved']} saved, {counts['retry']} retries, "
          f"{counts['conflict']} conflicts, {counts['invalid']} invalid")
    return 0 if counts["invalid"] == 0 else 2
 
 
def build_parser():
    p = argparse.ArgumentParser(prog="app.py", description="A tiny scoreboard.")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("submit", help="submit one event")
    s.add_argument("id")
    s.add_argument("team")
    s.add_argument("points")
    s.add_argument("action")
    s.add_argument("refers_to", nargs="?")
    s.set_defaults(func=cmd_submit)
    s = sub.add_parser("score", help="show one team's score")
    s.add_argument("team")
    s.set_defaults(func=cmd_score)
    s = sub.add_parser("leaderboard", help="show all teams")
    s.set_defaults(func=cmd_leaderboard)
    s = sub.add_parser("explain", help="show why an event was accepted or rejected")
    s.add_argument("id")
    s.set_defaults(func=cmd_explain)
    s = sub.add_parser("import", help="load events from a JSON file")
    s.add_argument("path")
    s.set_defaults(func=cmd_import)
    return p
 
 
def main(argv):
    args = build_parser().parse_args(argv)
    try:
        conn = connect()
        return args.func(conn, args)
    except UserError as err:
        print(f"{err.label}: {err}", file=sys.stderr)
        return err.code
    except sqlite3.OperationalError as err:
        if "locked" in str(err) or "busy" in str(err):
            print("BUSY: another program is writing to the database. Nothing was changed; "
                  "try again in a moment.", file=sys.stderr)
            return 4
        print(f"ERROR: {DB_PATH} could not be used ({err}). Nothing was changed.", file=sys.stderr)
        return 3
    except sqlite3.DatabaseError as err:
        print(f"ERROR: {DB_PATH} is damaged or is not a scoreboard database ({err}). Nothing was changed. "
              f"Move it aside or restore a backup; this program will not overwrite it.", file=sys.stderr)
        return 3
 
 
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))