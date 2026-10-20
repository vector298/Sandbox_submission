"""Problem 5: the ranking rule, computed two ways.
 
The rule
    1. More points first (negative totals are allowed).
    2. A tie goes to the team that reached its CURRENT total earlier in the accepted
       server history. "Earlier" = a smaller log position (the event's `row`).
    3. A tie there goes to the team id (A before B before C), which never changes.
    A team that leaves a total and later comes back to it gets a NEW time: the position
    of the event that brought it back. A team that never moved from 0 has time 0 (the start).
    An event that does not change a team's total (ADD +0, or a late ADD that a waiting UNDO
    cancels in the same step) does not change that team's time.
 
Solution 1: replay_standings(events)   replays every accepted record on each request.
Solution 2: IncrementalLeaderboard     keeps totals, times and the ranking up to date as events arrive.
"""
from replay import replay
 
TEAMS = ("A", "B", "C")
RETURN_GETS_NEW_TIME = "return_gets_new_time"  
FIRST_EVER = "first_ever"                       
 
def sort_key(team, points, time):
    return (-points, time, team)
 
 
def make_standings(scores, times, teams=TEAMS):
    order = sorted(teams, key=lambda t: sort_key(t, scores[t], times[t]))
    return [{"rank": i, "team": t, "points": scores[t], "reached_at": times[t]}
            for i, t in enumerate(order, start=1)]
 
 

 
def reached_times(outcomes, teams=TEAMS, rule=RETURN_GETS_NEW_TIME):
    """When did each team reach its current total? Read off the per-row score snapshots."""
    previous = {t: 0 for t in teams}
    latest_change = {t: 0 for t in teams}
    first_seen = {t: {0: 0} for t in teams}
    for o in outcomes:
        now = o["scores_after"]
        for t in teams:
            if now[t] != previous[t]:
                latest_change[t] = o["row"]
                first_seen[t].setdefault(now[t], o["row"])
        previous = now
    if rule == FIRST_EVER:
        return {t: first_seen[t][previous[t]] for t in teams}
    return latest_change
 
 
def replay_standings(events, teams=TEAMS, rule=RETURN_GETS_NEW_TIME):
    """Returns (standings, outcomes). Everything is rebuilt from the events each time."""
    scores, outcomes = replay(events)
    return make_standings(scores, reached_times(outcomes, teams, rule), teams), outcomes
 
 
def leaderboard_replay(events, teams=TEAMS, rule=RETURN_GETS_NEW_TIME):
    return replay_standings(events, teams, rule)[0]
 
 

 
class IncrementalLeaderboard:
    """Same rules as replay(), but state is kept between events instead of rebuilt."""
 
    def __init__(self, teams=TEAMS, rule=RETURN_GETS_NEW_TIME):
        self.teams = teams
        self.rule = rule
        self.scores = {t: 0 for t in teams}
        self.reached_at = {t: 0 for t in teams}      
        self.first_seen = {t: {0: 0} for t in teams}  
        self.seen = set()       
        self.kinds = {}         
        self.active = {}      
        self.undone = set()
        self.rejected = set()   
        self.pending = {}       
        self.order = []
        self._resort()
 
    def _time(self, team):
        if self.rule == FIRST_EVER:
            return self.first_seen[team].get(self.scores[team], self.reached_at[team])
        return self.reached_at[team]
 
    def _resort(self):
        self.order = sorted(self.teams, key=lambda t: sort_key(t, self.scores[t], self._time(t)))
 
    def _apply_undo(self, e):
        target = e["refers_to"]
        if target in self.rejected:
            self.rejected.add(e["id"])
        elif self.kinds[target] != "ADD":
            self.rejected.add(e["id"])
        elif target in self.undone:
            self.rejected.add(e["id"])
        elif self.active[target][0] != e["team"]:
            self.rejected.add(e["id"])
        else:
            team, points = self.active.pop(target)
            self.scores[team] -= points
            self.undone.add(target)
 
    def _handle(self, e):
        if e["id"] in self.seen:        
            return
        self.seen.add(e["id"])
        self.kinds[e["id"]] = e["action"]
        if e["action"] == "ADD":
            self.scores[e["team"]] += e["points"]
            self.active[e["id"]] = (e["team"], e["points"])
            for waiting in self.pending.pop(e["id"], []):
                self._apply_undo(waiting)
        elif e["action"] == "UNDO":
            if e["refers_to"] in self.seen:
                self._apply_undo(e)
            else:
                self.pending.setdefault(e["refers_to"], []).append(e)
 
    def apply(self, e):
        before = dict(self.scores)
        self._handle(e)
        changed = False
        for t in self.teams:            
            if self.scores[t] != before[t]:
                changed = True
                self.reached_at[t] = e["row"]
                if self.rule == FIRST_EVER:
                    self.first_seen[t].setdefault(self.scores[t], e["row"])
        if changed:
            self._resort()
 
    def standings(self):
        return [{"rank": i, "team": t, "points": self.scores[t], "reached_at": self._time(t)}
                for i, t in enumerate(self.order, start=1)]