"""Problem 5d: a case where the faster version is not the one I would choose.
 
Stored totals and rankings are only correct for the code that built them. When a rule changes or a
bug is fixed, the log is still right but the stored state is not. replay() rebuilds from the log and
is right at once; the incremental version carries the old mistake forward.
"""
from ranking import (FIRST_EVER, RETURN_GETS_NEW_TIME, IncrementalLeaderboard, leaderboard_replay)
 
 
def ev(row, id_, team, points, action="ADD", refers_to=None):
    return {"row": row, "id": id_, "team": team, "points": points, "action": action, "refers_to": refers_to}
 
 
def show(standings):
    return ", ".join(f"{s['team']} {s['points']} (t{s['reached_at']})" for s in standings)
 
 

H2 = [ev(1, "e1", "A", 50), ev(2, "e2", "B", 50), ev(3, "e3", "A", 10), ev(4, "u1", "A", 0, "UNDO", "e3")]
 
print("=== A. the organiser changes the tie-break rule while an event is running ===")
print("Old rule: a team that leaves a total and returns gets a NEW time.")
print("New rule: the time is the FIRST time the team ever had that total.\n")
print("History: A +50, B +50, A +10, undo of A +10. After event 4 both teams are on 50.")
print(f"  replay, old rule, whole log:  {show(leaderboard_replay(H2, rule=RETURN_GETS_NEW_TIME))}")
print(f"  replay, new rule, whole log:  {show(leaderboard_replay(H2, rule=FIRST_EVER))}   <- the answer under the new rule")
 
lb = IncrementalLeaderboard(rule=RETURN_GETS_NEW_TIME)
for e in H2[:3]:
    lb.apply(e)
lb.rule = FIRST_EVER            # the new code is deployed after event 3; events 1-3 were stored under the old code
lb.apply(H2[3])
print(f"  incremental, new code deployed after event 3: {show(lb.standings())}   <- matches neither rule's full answer")
print("  The stored state never recorded that A first had 50 at position 1, so it cannot know.")
 
rebuilt = IncrementalLeaderboard(rule=FIRST_EVER)
for e in H2:
    rebuilt.apply(e)
print(f"  incremental rebuilt from the whole log:       {show(rebuilt.standings())}   <- right again, but only after a rebuild")
 

class BuggyIncremental(IncrementalLeaderboard):
    
 
    def _apply_undo(self, e):
        target = e["refers_to"]
        if self.kinds[target] == "ADD" and target not in self.undone and target not in self.rejected:
            team, points = self.active.pop(target)
            self.scores[team] -= points
            self.undone.add(target)
        else:
            self.rejected.add(e["id"])
 
 
LOG = [ev(1, "e1", "A", 10), ev(2, "u1", "B", 0, "UNDO", "e1"), ev(3, "e2", "C", 1)]
 
print("\n=== B. a bug is found and fixed after events were already processed ===")
print("History: A +10, an UNDO of it sent by team B (not allowed), then C +1.\n")
print(f"  replay with the FIXED code, whole log:   {show(leaderboard_replay(LOG))}   <- correct: B's undo is rejected")
 
lb = BuggyIncremental()
for e in LOG[:2]:
    lb.apply(e)
print(f"  buggy incremental after event 2:         {show(lb.standings())}   <- wrong: A lost its 10")
lb.__class__ = IncrementalLeaderboard   # the fix is deployed; the stored totals stay as they were
lb.apply(LOG[2])
print(f"  incremental after the fix is deployed:   {show(lb.standings())}   <- still wrong")
 
fresh = IncrementalLeaderboard()
for e in LOG:
    fresh.apply(e)
print(f"  incremental rebuilt from the log:        {show(fresh.standings())}   <- right, after a rebuild")
 

print("\n=== C. 'the leaderboard looked wrong at log position 3' ===")
print("replay can show the exact leaderboard at any earlier point just by replaying a shorter log:")
for k in range(1, len(H2) + 1):
    print(f"  after position {k}: {show(leaderboard_replay(H2[:k]))}")
print("The incremental object only holds the latest state. Reproducing position 3 means replaying the log anyway.")