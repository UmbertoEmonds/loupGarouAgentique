# Bloc A — Moteur de jeu + Agents IA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the authoritative, in-memory Loup-Garou game engine and the
OpenRouter-backed AI agent integration (Bloc A, owned by Umberto per
`docs/repartition.md`), as a Django-independent Python package that Ethan's
Bloc B (Django/Channels/front) will later wire into consumers.

**Architecture:** Two plain Python packages at the repo root, no Django
dependency: `engine/` (deterministic `GameState`, phase flow, action
validation, the two allowed randomness points) and `agents/` (OpenRouter
HTTP client, 3-block prompt assembly, response parsing). They connect
through one seam: `engine.provider.ActionProvider`, a `Protocol` with a
single method `get_action(player_id, context) -> dict | None`. The engine
calls this for every player, AI or human, without knowing which; `agents/`
provides the AI-side implementation, and Bloc B will later provide the
human-side one (WebSocket wait with the 60–90s timeout). This boundary
lets every engine rule be tested with a scripted fake provider, with zero
real HTTP calls, and lets the OpenRouter client be tested with a fake HTTP
session, with zero game logic.

**Tech Stack:** Python 3, `requests` for HTTP, `pytest` for tests. No
Django, no DB, no Redis, no LangChain/LangGraph (all ruled out in
`architecture_decisions`, reaffirmed in the spec below).

**Spec:** `docs/superpowers/specs/2026-11-03-moteur-de-jeu-design.md`

## Global Constraints

- Single process, in-memory `GameState` only — no DB, no Redis, no
  persistence in this package (crash-recovery snapshotting is a separate,
  later concern noted in the spec's "hors-scope" section).
- Fixed roster: exactly 6 players (1 human + 5 AI), roles assigned
  randomly each game as 2 Loups-Garous / 1 Sorcière / 3 Villageois simples.
- Agent contract is always the same JSON shape:
  `{"message": "..."|null, "action": {"type": "...", "target": "..."|null}|null}`.
  No agent output ever mutates state directly — every action goes through
  `engine.actions.validate_action` first.
- A loup can never target the other loup with `night_kill_target`.
- Witch's heal can only target the wolves' chosen victim and never
  herself; her poison can target any living player including herself.
  Each potion is usable **once per game**, not once per night.
- Day debate is round-robin passes over living players, default window
  180s, stops early after one full round where everyone passes.
- Day vote: self-voting is explicitly allowed (spec §5b); voting is
  mandatory — invalid/timeout → one retry → fallback vote (never
  abstention).
- Vote fallback target: a player who already received ≥1 vote this round
  if any exist, else a fully random alive player.
- Wolf disagreement fallback: only after 3 negotiation rounds still
  disagree → random tie-break between the targets actually proposed
  during those rounds (degrading to a random legal target if neither
  wolf ever proposed one) — documented as a technical safety net, never a
  game rule, per the spec's anti-objectif on randomness.
- Victory: villagers win when both loups are dead; loups win on **strict**
  numeric superiority (`loups > autres`), never `≥`. Checked after every
  death-causing event (night resolution, day elimination).
- OpenRouter only, no local Ollama. Model via env var `OPENROUTER_MODEL`,
  optional fallback via `OPENROUTER_FALLBACK_MODEL`, key via
  `OPENROUTER_API_KEY`. Per-call timeout 15s (spec's AI timeout figure).
- The human player's real-time wait/timeout (60–90s, visible countdown)
  is Bloc B's responsibility (Channels consumer). This plan only defines
  the `ActionProvider` contract it must satisfy; it does not implement it.

## Review Focus

- Witch's heal/poison are single-use **per game**: reusing either potion
  in a later night cycle (not just the same night) must be rejected or
  silently no-op, never applied twice. → Task 6.
- A day vote can tie among **three or more** candidates, not just two
  (e.g. 2/2/2 among 6 alive players) — must still mean no elimination,
  not an engine crash or an arbitrary pick. → Task 7.
- An agent submits a structurally valid JSON action of the **wrong type
  for its role or phase** (a villageois submitting `night_kill_target`,
  a sorcière submitting `night_kill_target` instead of
  `witch_heal`/`witch_poison`) — distinct from malformed JSON, this must
  be caught by semantic validation, not just schema parsing. → Task 2.
- The vote fallback triggers while **nobody has voted yet** this round
  (the very first voter times out) — must fall back to a fully random
  alive target instead of crashing on an empty "already suspected" pool.
  → Task 7.
- The witch poisons one of the two wolves — villager victory must **not**
  fire until the second wolf also dies, and the wolf-superiority count
  must reflect the post-poison alive set. → Task 6.

---

### Task 1: Package scaffold, core models, and roster assignment

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `engine/__init__.py`
- Create: `engine/models.py`
- Create: `engine/roster.py`
- Test: `tests/engine/__init__.py`
- Test: `tests/engine/test_models.py`
- Test: `tests/engine/test_roster.py`

**Interfaces:**
- Produces: `Role`, `Camp`, `Phase`, `ActionType` (enums), `ROLE_TO_CAMP: dict[Role, Camp]`, `Player` dataclass (`id: str`, `pseudo: str`, `is_human: bool`, `role: Role`, `personality: str | None`, `alive: bool = True`, `witch_heal_used: bool = False`, `witch_poison_used: bool = False`), `GameState` dataclass (`players: dict[str, Player]`, `phase: Phase`, `cycle: int`, `main_room_log: list[dict]`, `wolf_room_log: list[dict]`, `last_wolf_target: str | None`, `winner: Camp | None`) with methods `alive_ids() -> list[str]`, `wolves() -> list[Player]`, `get(player_id: str) -> Player`; `roster.PRENOMS`, `roster.PERSONNALITES`, `roster.ROLE_COUNTS`, `roster.new_game(human_pseudo: str, rng: random.Random | None = None) -> GameState`.

- [ ] **Step 1: Write `requirements.txt` and `pytest.ini`**

`requirements.txt` contains `requests`; `pytest.ini` sets `testpaths = tests`. No test for this step — it's project scaffolding the first test run depends on.

- [ ] **Step 2: Write the failing tests for `models.py`**

```python
# tests/engine/test_models.py
def test_player_defaults_alive_and_potions_unused():
    p = Player(id="ia_1", pseudo="Fatima", is_human=False, role=Role.VILLAGEOIS, personality="stratege")
    assert p.alive is True
    assert p.witch_heal_used is False
    assert p.witch_poison_used is False

def test_gamestate_alive_ids_excludes_dead_players():
    players = {
        "human": Player(id="human", pseudo="Umberto", is_human=True, role=Role.VILLAGEOIS, personality=None),
        "ia_1": Player(id="ia_1", pseudo="Sofia", is_human=False, role=Role.LOUP, personality="impatient", alive=False),
    }
    state = GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)
    assert state.alive_ids() == ["human"]

def test_gamestate_wolves_returns_only_loup_role():
    players = {
        "ia_1": Player(id="ia_1", pseudo="Ethan", is_human=False, role=Role.LOUP, personality="manipulateur"),
        "ia_2": Player(id="ia_2", pseudo="Elliot", is_human=False, role=Role.SORCIERE, personality="paranoiaque"),
    }
    state = GameState(players=players, phase=Phase.NUIT_LOUPS, cycle=1)
    assert [p.id for p in state.wolves()] == ["ia_1"]
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `pytest tests/engine/test_models.py -v`
Expected: FAIL (module `engine.models` not defined / `ImportError`)

- [ ] **Step 3: Implement `engine/models.py`**

Enums and dataclasses as listed in Interfaces above. `ROLE_TO_CAMP = {Role.LOUP: Camp.LOUPS, Role.SORCIERE: Camp.VILLAGEOIS, Role.VILLAGEOIS: Camp.VILLAGEOIS}`. `main_room_log`/`wolf_room_log` default to `field(default_factory=list)`, entries shaped `{"author": str | None, "text": str}` (`author=None` for engine-generated announcements).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for `roster.py`**

```python
# tests/engine/test_roster.py
import random
from collections import Counter

def test_new_game_has_six_players_with_correct_role_counts():
    state = roster.new_game("Umberto", rng=random.Random(1))
    assert len(state.players) == 6
    counts = Counter(p.role for p in state.players.values())
    assert counts == {Role.LOUP: 2, Role.SORCIERE: 1, Role.VILLAGEOIS: 3}

def test_new_game_includes_the_human_exactly_once():
    state = roster.new_game("Umberto", rng=random.Random(1))
    humans = [p for p in state.players.values() if p.is_human]
    assert len(humans) == 1
    assert humans[0].pseudo == "Umberto"
    assert humans[0].personality is None

def test_new_game_gives_each_ai_a_distinct_prenom_and_personality():
    state = roster.new_game("Umberto", rng=random.Random(1))
    ai_players = [p for p in state.players.values() if not p.is_human]
    assert len(ai_players) == 5
    assert sorted(p.pseudo for p in ai_players) == sorted(roster.PRENOMS)
    assert sorted(p.personality for p in ai_players) == sorted(roster.PERSONNALITES)

def test_new_game_randomizes_role_and_name_assignment_across_seeds():
    state_a = roster.new_game("Umberto", rng=random.Random(1))
    state_b = roster.new_game("Umberto", rng=random.Random(2))
    roles_a = sorted((p.pseudo, p.role) for p in state_a.players.values())
    roles_b = sorted((p.pseudo, p.role) for p in state_b.players.values())
    assert roles_a != roles_b

def test_new_game_starts_at_night_phase_cycle_one():
    state = roster.new_game("Umberto", rng=random.Random(1))
    assert state.phase == Phase.NUIT_LOUPS
    assert state.cycle == 1
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/engine/test_roster.py -v`
Expected: FAIL (`engine.roster` not defined)

- [ ] **Step 7: Implement `engine/roster.py`**

`PRENOMS = ["Umberto", "Fatima", "Ethan", "Sofia", "Elliot"]`,
`PERSONNALITES = ["mauvais_joueur", "stratege", "impatient", "paranoiaque", "manipulateur"]`,
`ROLE_COUNTS = {Role.LOUP: 2, Role.SORCIERE: 1, Role.VILLAGEOIS: 3}`.
`new_game` builds 6 player ids (`"human"` + `"ia_1".."ia_5"`), independently
shuffles the 6-slot role list and the 5-slot (prenom, personnalite) pairing
(two separate `rng.shuffle` calls so role and personality stay
uncorrelated, per spec), assigns the human their given pseudo and
`personality=None`, and returns a `GameState` at `Phase.NUIT_LOUPS`,
`cycle=1`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/engine/test_roster.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add requirements.txt pytest.ini engine/ tests/engine/
git commit -m "feat(engine): add GameState models and roster assignment"
```

---

### Task 2: Action validation

**Files:**
- Create: `engine/actions.py`
- Test: `tests/engine/test_actions.py`

**Interfaces:**
- Consumes: `GameState`, `Player`, `Role`, `ActionType`, `Phase` (Task 1).
- Produces: `ActionInvalid(Exception)`, `Action` dataclass (`type: ActionType`, `target: str | None`), `validate_action(state: GameState, player_id: str, action_type: ActionType, target: str | None) -> Action`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_actions.py
# helper `make_state(roles: dict[str, Role]) -> GameState` built inline per test with Phase.NUIT_LOUPS by default.

def test_wolf_may_target_a_living_non_wolf():
    state = make_state({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS}, phase=Phase.NUIT_LOUPS)
    action = validate_action(state, "ia_1", ActionType.NIGHT_KILL_TARGET, "ia_3")
    assert action == Action(ActionType.NIGHT_KILL_TARGET, "ia_3")

def test_wolf_cannot_target_the_other_wolf():
    state = make_state({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS}, phase=Phase.NUIT_LOUPS)
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.NIGHT_KILL_TARGET, "ia_2")

def test_villageois_cannot_submit_a_night_kill_target():
    state = make_state({"ia_1": Role.LOUP, "ia_3": Role.VILLAGEOIS}, phase=Phase.NUIT_LOUPS)
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_3", ActionType.NIGHT_KILL_TARGET, "ia_1")

def test_sorciere_cannot_submit_night_kill_target_instead_of_witch_action():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.LOUP}, phase=Phase.NUIT_SORCIERE)
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.NIGHT_KILL_TARGET, "ia_2")

def test_witch_heal_must_target_the_wolves_victim():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.VILLAGEOIS}, phase=Phase.NUIT_SORCIERE)
    state.last_wolf_target = "ia_2"
    validate_action(state, "ia_1", ActionType.WITCH_HEAL, "ia_2")  # does not raise
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.WITCH_HEAL, "ia_1")

def test_witch_cannot_heal_herself_even_if_she_is_the_victim():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.VILLAGEOIS}, phase=Phase.NUIT_SORCIERE)
    state.last_wolf_target = "ia_1"
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.WITCH_HEAL, "ia_1")

def test_witch_poison_may_target_anyone_including_herself():
    state = make_state({"ia_1": Role.SORCIERE, "ia_2": Role.VILLAGEOIS}, phase=Phase.NUIT_SORCIERE)
    validate_action(state, "ia_1", ActionType.WITCH_POISON, "ia_1")  # does not raise
    validate_action(state, "ia_1", ActionType.WITCH_POISON, "ia_2")  # does not raise

def test_declining_a_witch_potion_is_always_legal():
    state = make_state({"ia_1": Role.SORCIERE}, phase=Phase.NUIT_SORCIERE)
    validate_action(state, "ia_1", ActionType.WITCH_HEAL, None)
    validate_action(state, "ia_1", ActionType.WITCH_POISON, None)

def test_day_vote_self_vote_is_allowed():
    state = make_state({"ia_1": Role.VILLAGEOIS}, phase=Phase.JOUR_VOTE)
    validate_action(state, "ia_1", ActionType.DAY_VOTE, "ia_1")  # does not raise

def test_day_vote_target_must_be_alive():
    state = make_state({"ia_1": Role.VILLAGEOIS, "ia_2": Role.VILLAGEOIS}, phase=Phase.JOUR_VOTE)
    state.players["ia_2"].alive = False
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.DAY_VOTE, "ia_2")

def test_dead_player_cannot_submit_any_action():
    state = make_state({"ia_1": Role.VILLAGEOIS, "ia_2": Role.VILLAGEOIS}, phase=Phase.JOUR_VOTE)
    state.players["ia_1"].alive = False
    with pytest.raises(ActionInvalid):
        validate_action(state, "ia_1", ActionType.DAY_VOTE, "ia_2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_actions.py -v`
Expected: FAIL (`engine.actions` not defined)

- [ ] **Step 3: Implement `engine/actions.py`**

`validate_action` checks, in order: player exists and is alive; `action_type`
is legal for the player's role (`NIGHT_KILL_TARGET`→`LOUP` only,
`WITCH_HEAL`/`WITCH_POISON`→`SORCIERE` only, `DAY_VOTE`→any role); if
`target is None`, only `WITCH_HEAL`/`WITCH_POISON` may decline this way,
raise otherwise; else target player exists and is alive, plus the
per-type rule: `NIGHT_KILL_TARGET` target's role is not `LOUP`;
`WITCH_HEAL` target must equal `state.last_wolf_target` and differ from
`player_id`; `WITCH_POISON` target unrestricted (self allowed);
`DAY_VOTE` target unrestricted (self allowed, per spec §5b). Raise
`ActionInvalid` with a descriptive message on any failure; otherwise
return `Action(action_type, target)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_actions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/actions.py tests/engine/test_actions.py
git commit -m "feat(engine): validate agent actions against role/phase/target rules"
```

---

### Task 3: ActionProvider contract and retry helper

**Files:**
- Create: `engine/provider.py`
- Test: `tests/engine/test_provider.py`

**Interfaces:**
- Produces: `ActionProvider` (`typing.Protocol`, method `get_action(self, player_id: str, context: dict) -> dict | None`), `request_with_retry(provider: ActionProvider, player_id: str, context: dict, attempts: int = 2) -> dict | None`.
- This is the seam Task 10–13 (`agents/`) implement on the AI side, and Bloc B implements on the human side. `context` is a plain dict the caller builds (shape is each calling task's own concern — Tasks 5–7 and 13 agree on its keys; this task only needs a dict it can pass through opaquely).

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_provider.py
class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
    def get_action(self, player_id, context):
        self.calls += 1
        return self.responses.pop(0)

def test_request_with_retry_returns_first_success():
    provider = ScriptedProvider([{"message": None, "action": None}])
    result = request_with_retry(provider, "ia_1", {}, attempts=2)
    assert result == {"message": None, "action": None}
    assert provider.calls == 1

def test_request_with_retry_retries_once_after_a_none():
    provider = ScriptedProvider([None, {"message": "ok", "action": None}])
    result = request_with_retry(provider, "ia_1", {}, attempts=2)
    assert result == {"message": "ok", "action": None}
    assert provider.calls == 2

def test_request_with_retry_gives_up_after_attempts_exhausted():
    provider = ScriptedProvider([None, None])
    result = request_with_retry(provider, "ia_1", {}, attempts=2)
    assert result is None
    assert provider.calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_provider.py -v`
Expected: FAIL (`engine.provider` not defined)

- [ ] **Step 3: Implement `engine/provider.py`**

`ActionProvider` as a `typing.Protocol`. `request_with_retry` loops up to
`attempts` times calling `provider.get_action(player_id, context)`,
returning the first non-`None` result, else `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/provider.py tests/engine/test_provider.py
git commit -m "feat(engine): define the ActionProvider seam and retry helper"
```

---

### Task 4: Fallback randomness

**Files:**
- Create: `engine/fallback.py`
- Test: `tests/engine/test_fallback.py`

**Interfaces:**
- Produces: `pick_wolf_tiebreak(candidate_targets: list[str], alive_non_wolf_ids: list[str], rng: random.Random) -> str`, `pick_vote_fallback(votes_so_far: dict[str, str], alive_ids: list[str], rng: random.Random) -> str`.
- These are the **only** two randomness call sites in the whole engine (spec's anti-objectif). Tasks 5 and 7 call them, never implement their own `random` logic.

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_fallback.py
import random

def test_pick_wolf_tiebreak_picks_among_proposed_candidates():
    result = pick_wolf_tiebreak(["ia_3", "ia_4"], ["ia_3", "ia_4", "ia_5"], rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}

def test_pick_wolf_tiebreak_falls_back_to_any_alive_non_wolf_if_nobody_proposed():
    result = pick_wolf_tiebreak([], ["ia_3", "ia_4", "ia_5"], rng=random.Random(1))
    assert result in {"ia_3", "ia_4", "ia_5"}

def test_pick_vote_fallback_prefers_a_player_already_suspected():
    votes_so_far = {"ia_1": "ia_3", "ia_2": "ia_3"}
    result = pick_vote_fallback(votes_so_far, ["ia_1", "ia_2", "ia_3", "ia_4"], rng=random.Random(1))
    assert result == "ia_3"

def test_pick_vote_fallback_is_fully_random_when_nobody_has_voted_yet():
    result = pick_vote_fallback({}, ["ia_1", "ia_2", "ia_3"], rng=random.Random(1))
    assert result in {"ia_1", "ia_2", "ia_3"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_fallback.py -v`
Expected: FAIL (`engine.fallback` not defined)

- [ ] **Step 3: Implement `engine/fallback.py`**

`pick_wolf_tiebreak`: if `candidate_targets` is non-empty, `rng.choice` among
the **distinct** values; else `rng.choice(alive_non_wolf_ids)`.
`pick_vote_fallback`: suspected pool = the distinct values of
`votes_so_far` that are also in `alive_ids`; if non-empty,
`rng.choice(suspected_pool)`; else `rng.choice(alive_ids)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_fallback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/fallback.py tests/engine/test_fallback.py
git commit -m "feat(engine): isolate the two spec-sanctioned randomness fallbacks"
```

---

### Task 5: Night — wolves phase resolution

**Files:**
- Create: `engine/night.py`
- Test: `tests/engine/test_night_wolves.py`

**Interfaces:**
- Consumes: `GameState`, `ActionType` (Task 1); `validate_action`, `ActionInvalid` (Task 2); `ActionProvider` (Task 3, calling `provider.get_action` directly — a single attempt per round, no retry, per spec's "fait simplement passer" wording reused for wolves); `pick_wolf_tiebreak` (Task 4).
- Produces: `resolve_wolf_phase(state: GameState, provider: ActionProvider, rng: random.Random | None = None) -> str` — returns the agreed or tie-broken kill target id, and appends any wolf chat messages to `state.wolf_room_log`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_night_wolves.py
class ScriptedWolfProvider:
    def __init__(self, scripts: dict[str, list[dict | None]]):
        self.scripts = scripts
    def get_action(self, player_id, context):
        return self.scripts[player_id].pop(0)

def test_wolves_agree_immediately_on_the_same_target():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [{"message": "ia_3", "action": {"type": "night_kill_target", "target": "ia_3"}}],
        "ia_2": [{"message": None, "action": {"type": "night_kill_target", "target": "ia_3"}}],
    })
    assert resolve_wolf_phase(state, provider, rng=random.Random(1)) == "ia_3"
    assert {"author": "ia_1", "text": "ia_3"} in state.wolf_room_log

def test_wolves_negotiate_up_to_three_rounds_then_agree():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_3")] * 2 + [action("ia_4")],
        "ia_2": [action("ia_4")] * 3,
    })
    # ia_1 switches to ia_4 on round 3, matching ia_2
    assert resolve_wolf_phase(state, provider, rng=random.Random(1)) == "ia_4"

def test_wolves_still_disagreeing_after_three_rounds_triggers_tiebreak():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_3")] * 3,
        "ia_2": [action("ia_4")] * 3,
    })
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}

def test_a_wolf_attempting_to_target_the_other_wolf_is_treated_as_no_submission():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3"])
    provider = ScriptedWolfProvider({
        "ia_1": [action("ia_2")] * 3,   # illegal every round
        "ia_2": [action("ia_3")] * 3,
    })
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result == "ia_3"  # only legal candidate ever proposed

def test_silent_wolves_fall_back_to_a_random_alive_non_wolf():
    state = make_state_with_wolves("ia_1", "ia_2", others=["ia_3", "ia_4"])
    provider = ScriptedWolfProvider({"ia_1": [None] * 3, "ia_2": [None] * 3})
    result = resolve_wolf_phase(state, provider, rng=random.Random(1))
    assert result in {"ia_3", "ia_4"}
```

(`make_state_with_wolves` and `action(target)` are small local test
helpers: the former builds a `GameState` with the given wolves/others as
`Role.VILLAGEOIS`, the latter returns
`{"message": None, "action": {"type": "night_kill_target", "target": target}}`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_night_wolves.py -v`
Expected: FAIL (`engine.night` not defined)

- [ ] **Step 3: Implement `resolve_wolf_phase` in `engine/night.py`**

For up to 3 rounds: for each wolf, call `provider.get_action` once; if the
result has a `message`, append `{"author": wolf.id, "text": message}` to
`state.wolf_room_log`; extract the proposed target and pass it through
`validate_action(state, wolf.id, ActionType.NIGHT_KILL_TARGET, target)`,
catching `ActionInvalid` as "no valid submission this round"; track each
wolf's most recent valid proposal. If both wolves have a valid proposal
this round and they're equal, return it immediately. After 3 rounds
without agreement, call `pick_wolf_tiebreak` with the distinct valid
proposals ever made and the list of alive non-wolf ids.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_night_wolves.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/night.py tests/engine/test_night_wolves.py
git commit -m "feat(engine): resolve wolf night negotiation with 3-round disagreement fallback"
```

---

### Task 6: Night — witch phase resolution and death application

**Files:**
- Modify: `engine/night.py`
- Test: `tests/engine/test_night_witch.py`

**Interfaces:**
- Consumes: `validate_action`, `ActionInvalid` (Task 2); `ActionProvider` (Task 3, single attempt, no retry — any failure/decline is equivalent to "no potion used").
- Produces: `resolve_witch_phase(state: GameState, provider: ActionProvider, wolf_target: str) -> tuple[bool, str | None]` (returns `(healed, poisoned_id)`); `apply_night_deaths(state: GameState, wolf_target: str, healed: bool, poisoned_id: str | None) -> list[str]` (applies deaths to `state.players[...].alive`, returns the list of ids who died this night, deduplicated).

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_night_witch.py
def heal(target): return {"message": None, "action": {"type": "witch_heal", "target": target}}
def poison(target): return {"message": None, "action": {"type": "witch_poison", "target": target}}
def decline(): return {"message": None, "action": None}

def test_witch_heals_the_wolves_victim():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    provider = ScriptedProvider({"ia_1": [heal("ia_2"), decline()]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert (healed, poisoned) == (True, None)
    assert state.get("ia_1").witch_heal_used is True

def test_witch_cannot_heal_herself_even_if_targeted():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    provider = ScriptedProvider({"ia_1": [heal("ia_1"), decline()]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_1")
    assert healed is False  # invalid self-heal rejected, treated as declined

def test_witch_heals_and_poisons_in_the_same_night_independently():
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    provider = ScriptedProvider({"ia_1": [heal("ia_2"), poison("ia_3")]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert (healed, poisoned) == (True, "ia_3")
    assert state.get("ia_1").witch_heal_used is True
    assert state.get("ia_1").witch_poison_used is True

def test_witch_may_poison_herself():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    provider = ScriptedProvider({"ia_1": [decline(), poison("ia_1")]})
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert poisoned == "ia_1"

def test_witch_cannot_reuse_a_potion_already_used_in_a_previous_cycle():
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    state.get("ia_1").witch_heal_used = True
    state.get("ia_1").witch_poison_used = True
    provider = ScriptedProvider({})  # must not be called at all for an exhausted witch
    healed, poisoned = resolve_witch_phase(state, provider, wolf_target="ia_2")
    assert (healed, poisoned) == (False, None)

def test_apply_night_deaths_applies_unhealed_wolf_kill():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=False, poisoned_id=None)
    assert dead == ["ia_2"]
    assert state.get("ia_2").alive is False

def test_apply_night_deaths_healed_wolf_kill_produces_no_wolf_death():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=True, poisoned_id=None)
    assert dead == []
    assert state.get("ia_2").alive is True

def test_apply_night_deaths_poison_and_wolf_kill_both_apply():
    state = make_state_with_witch("ia_1", others=["ia_2", "ia_3"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=False, poisoned_id="ia_3")
    assert sorted(dead) == ["ia_2", "ia_3"]

def test_witch_poisoning_a_wolf_does_not_double_count_if_already_the_wolf_target():
    state = make_state_with_witch("ia_1", others=["ia_2"])
    dead = apply_night_deaths(state, wolf_target="ia_2", healed=False, poisoned_id="ia_2")
    assert dead == ["ia_2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_night_witch.py -v`
Expected: FAIL (`resolve_witch_phase`/`apply_night_deaths` not defined)

- [ ] **Step 3: Implement `resolve_witch_phase` and `apply_night_deaths` in `engine/night.py`**

`resolve_witch_phase`: find the living `Role.SORCIERE` player (`None` →
return `(False, None)`). If `witch_heal_used` is `False`, call
`provider.get_action` once; attempt
`validate_action(state, witch.id, ActionType.WITCH_HEAL, target)`, catching
`ActionInvalid` as "declined"; on success with non-`None` target, set
`witch_heal_used = True` and `healed = True`. Repeat the same pattern for
`witch_poison_used`/`WITCH_POISON`. Return `(healed, poisoned_id)`.
`apply_night_deaths`: build the death set as `{wolf_target} - {healed and wolf_target}` unioned with `{poisoned_id} if poisoned_id else {}`, set
`alive = False` on each, return the sorted/deduplicated list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_night_witch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/night.py tests/engine/test_night_witch.py
git commit -m "feat(engine): resolve witch heal/poison and apply night deaths"
```

---

### Task 7: Day — debate round-robin, vote collection, and resolution

**Files:**
- Create: `engine/day.py`
- Test: `tests/engine/test_day.py`

**Interfaces:**
- Consumes: `GameState`, `ActionType` (Task 1); `validate_action`, `ActionInvalid` (Task 2); `request_with_retry`, `ActionProvider` (Task 3); `pick_vote_fallback` (Task 4).
- Produces: `run_debate_round_robin(state: GameState, provider: ActionProvider, is_time_up: Callable[[], bool]) -> None`; `collect_votes(state: GameState, provider: ActionProvider, rng: random.Random | None = None) -> tuple[dict[str, str], list[str]]` (votes by voter id, and the list of voter ids who needed the fallback); `resolve_vote(votes: dict[str, str], alive_ids: list[str]) -> str | None` (eliminated id, or `None` on a tie of any size).

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_day.py
def test_debate_stops_when_time_is_up_before_any_pass():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({"ia_1": [], "ia_2": []})
    run_debate_round_robin(state, provider, is_time_up=lambda: True)
    assert state.main_room_log == []

def test_debate_records_messages_and_resets_pass_streak():
    state = make_state_with_alive("ia_1", "ia_2")
    calls = {"n": 0}
    def is_time_up():
        calls["n"] += 1
        return calls["n"] > 4  # allow two full passes
    provider = ScriptedProvider({
        "ia_1": [{"message": "salut", "action": None}, {"message": None, "action": None}],
        "ia_2": [{"message": None, "action": None}, {"message": None, "action": None}],
    })
    run_debate_round_robin(state, provider, is_time_up=is_time_up)
    assert {"author": "ia_1", "text": "salut"} in state.main_room_log

def test_debate_stops_early_on_one_full_round_of_passes():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({
        "ia_1": [{"message": None, "action": None}] * 5,
        "ia_2": [{"message": None, "action": None}] * 5,
    })
    run_debate_round_robin(state, provider, is_time_up=lambda: False)
    assert state.main_room_log == []  # stopped after round 1, never reached time-up

def test_collect_votes_records_a_valid_vote_including_self_vote():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({
        "ia_1": [{"message": None, "action": {"type": "day_vote", "target": "ia_1"}}],
        "ia_2": [{"message": None, "action": {"type": "day_vote", "target": "ia_1"}}],
    })
    votes, fallback_used = collect_votes(state, provider, rng=random.Random(1))
    assert votes == {"ia_1": "ia_1", "ia_2": "ia_1"}
    assert fallback_used == []

def test_collect_votes_falls_back_after_retry_exhausted():
    state = make_state_with_alive("ia_1", "ia_2", "ia_3")
    provider = ScriptedProvider({
        "ia_1": [{"message": None, "action": {"type": "day_vote", "target": "ia_2"}}],
        "ia_2": [{"message": None, "action": {"type": "day_vote", "target": "ia_2"}}],
        "ia_3": [None, None],
    })
    votes, fallback_used = collect_votes(state, provider, rng=random.Random(1))
    assert fallback_used == ["ia_3"]
    assert votes["ia_3"] == "ia_2"  # ia_2 already has votes, so the "suspected" pool picks it

def test_collect_votes_fallback_is_random_when_nobody_voted_yet():
    state = make_state_with_alive("ia_1", "ia_2")
    provider = ScriptedProvider({"ia_1": [None, None], "ia_2": [None, None]})
    votes, fallback_used = collect_votes(state, provider, rng=random.Random(1))
    assert set(fallback_used) == {"ia_1", "ia_2"}
    assert all(v in {"ia_1", "ia_2"} for v in votes.values())

def test_resolve_vote_eliminates_the_clear_majority():
    assert resolve_vote({"a": "c", "b": "c", "c": "a"}, ["a", "b", "c"]) == "c"

def test_resolve_vote_two_way_tie_eliminates_nobody():
    assert resolve_vote({"a": "b", "b": "a"}, ["a", "b"]) is None

def test_resolve_vote_three_way_tie_eliminates_nobody():
    assert resolve_vote({"a": "d", "b": "e", "c": "f", "d": "a", "e": "b", "f": "c"},
                         ["a", "b", "c", "d", "e", "f"]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_day.py -v`
Expected: FAIL (`engine.day` not defined)

- [ ] **Step 3: Implement `engine/day.py`**

`run_debate_round_robin`: loop rounds; each round, for each alive player
in a stable order, if `is_time_up()` return immediately; else call
`provider.get_action` once (no retry — a slow/failed call "passes" per
spec); if the result has a non-`None` `message`, append to
`main_room_log` and reset a pass-streak counter, else increment it; if the
streak reaches `len(alive_ids)` (one full round all-pass), return.
`collect_votes`: for each alive player, `request_with_retry(..., attempts=2)`;
on success, validate via `validate_action(..., DAY_VOTE, target)` (on
`ActionInvalid`, treat like a `None` result); on failure, call
`pick_vote_fallback(votes_so_far, alive_ids, rng)`, record the voter in
`fallback_used`, and store that as their vote too (vote stays mandatory).
`resolve_vote`: tally `Counter(votes.values())`; if the top count is
uniquely held by one id, return it; else `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_day.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/day.py tests/engine/test_day.py
git commit -m "feat(engine): resolve day debate round-robin and mandatory vote"
```

---

### Task 8: Victory conditions

**Files:**
- Create: `engine/victory.py`
- Test: `tests/engine/test_victory.py`

**Interfaces:**
- Consumes: `GameState`, `Camp`, `Role` (Task 1).
- Produces: `check_victory(state: GameState) -> Camp | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_victory.py
def test_villagers_win_when_both_wolves_are_dead():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS})
    state.get("ia_1").alive = False
    state.get("ia_2").alive = False
    assert check_victory(state) == Camp.VILLAGEOIS

def test_no_winner_while_one_wolf_still_lives():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS})
    state.get("ia_1").alive = False
    assert check_victory(state) is None

def test_wolves_do_not_win_on_mere_parity():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS, "ia_4": Role.VILLAGEOIS})
    state.get("ia_3").alive = False
    state.get("ia_4").alive = False
    # 2 loups vs 0 others alive... actually parity test: 2 vs 2 before this kill
    assert check_victory(state) == Camp.LOUPS  # 2 loups vs 0 others is already strict superiority

def test_wolves_do_not_win_at_exact_parity_two_vs_two():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS, "ia_4": Role.VILLAGEOIS})
    assert check_victory(state) is None  # 2 vs 2, not strictly superior

def test_wolves_win_on_strict_superiority_three_vs_two_reduced_to_two_vs_one():
    state = make_state_with_roles({"ia_1": Role.LOUP, "ia_2": Role.LOUP, "ia_3": Role.VILLAGEOIS, "ia_4": Role.VILLAGEOIS, "ia_5": Role.VILLAGEOIS})
    state.get("ia_4").alive = False
    state.get("ia_5").alive = False
    assert check_victory(state) == Camp.LOUPS  # 2 loups vs 1 other
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_victory.py -v`
Expected: FAIL (`engine.victory` not defined)

- [ ] **Step 3: Implement `engine/victory.py`**

`check_victory`: `alive_wolves = [p for p in state.players.values() if p.alive and p.role == Role.LOUP]`;
if not `alive_wolves`: return `Camp.VILLAGEOIS`; `alive_others = [p for p in ... if p.alive and p.role != Role.LOUP]`;
if `len(alive_wolves) > len(alive_others)`: return `Camp.LOUPS`; else `None`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_victory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/victory.py tests/engine/test_victory.py
git commit -m "feat(engine): check strict wolf-superiority and villager victory"
```

---

### Task 9: GameEngine full-cycle orchestration

**Files:**
- Create: `engine/engine.py`
- Test: `tests/engine/test_engine_full_game.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8 (`roster.new_game`, `night.resolve_wolf_phase`/`resolve_witch_phase`/`apply_night_deaths`, `day.run_debate_round_robin`/`collect_votes`/`resolve_vote`, `victory.check_victory`).
- Produces: `GameEngine` class: `__init__(self, debate_duration_s: int = 180, rng: random.Random | None = None)`; `start(self, human_pseudo: str) -> GameState`; `run_night_cycle(self, provider: ActionProvider) -> list[str]`; `check_and_set_winner(self) -> Camp | None`; `run_day_cycle(self, provider: ActionProvider, is_time_up: Callable[[], bool] | None = None) -> tuple[str | None, list[str]]`; `play(self, provider: ActionProvider, max_cycles: int = 10) -> Camp | None`.

This task is the integration gate: it proves Tasks 1–8 compose into a full
game, using a single deterministic fake provider across an entire
simulated game, with no mocked internals.

- [ ] **Step 1: Write the failing tests**

```python
# tests/engine/test_engine_full_game.py
class AlwaysAgreeingHostileProvider:
    """Every wolf always proposes the first alive non-wolf; everyone always
    votes for the first alive wolf they can see is suspicious-by-script;
    nobody uses witch potions; nobody sends chat (instant debate end)."""
    def get_action(self, player_id, context):
        role = context["self_role"]
        phase = context["phase"]
        if phase == "nuit_loups":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id and p["id"] not in context["known_wolf_ids"])
            return {"message": None, "action": {"type": "night_kill_target", "target": target}}
        if phase == "nuit_sorciere":
            return {"message": None, "action": None}
        if phase == "jour_debat":
            return {"message": None, "action": None}
        if phase == "jour_vote":
            target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id)
            return {"message": None, "action": {"type": "day_vote", "target": target}}
        raise AssertionError(f"unexpected phase {phase}")

def test_play_reaches_a_winner_within_max_cycles():
    engine = GameEngine(rng=random.Random(1))
    engine.start("Umberto")
    winner = engine.play(AlwaysAgreeingHostileProvider(), max_cycles=10)
    assert winner in {Camp.LOUPS, Camp.VILLAGEOIS}
    assert engine.state.winner == winner
    assert engine.state.phase == Phase.TERMINEE

def test_play_checks_victory_immediately_after_a_night_kill():
    # With only 1 wolf alive at start (forced via a pre-seeded state) and
    # everyone else dead but one, the game must end after that single
    # night without running a day cycle.
    engine = GameEngine(rng=random.Random(1))
    state = engine.start("Umberto")
    for p in state.players.values():
        p.alive = p.role == Role.LOUP or p.pseudo == "lone-survivor-marker"
    # keep exactly the 2 loups + 1 other alive, rest already dead
    alive_others = [p for p in state.players.values() if p.alive and p.role != Role.LOUP]
    for p in alive_others[1:]:
        p.alive = False
    engine.run_night_cycle(AlwaysAgreeingHostileProvider())
    assert engine.check_and_set_winner() == Camp.LOUPS

def test_play_stops_at_max_cycles_without_crashing_if_nobody_wins():
    class StalemateProvider:
        def get_action(self, player_id, context):
            if context["phase"] in ("jour_vote",):
                return {"message": None, "action": {"type": "day_vote", "target": player_id}}  # self-votes only -> perpetual ties, nobody eliminated
            if context["phase"] == "nuit_loups":
                target = next(p["id"] for p in context["alive_players"] if p["id"] != player_id and p["id"] not in context["known_wolf_ids"])
                return {"message": None, "action": {"type": "night_kill_target", "target": target}}
            return {"message": None, "action": None}
    engine = GameEngine(rng=random.Random(1))
    engine.start("Umberto")
    winner = engine.play(StalemateProvider(), max_cycles=10)
    # the night phase still kills someone each cycle (no witch heal), so a
    # winner must emerge well before max_cycles because the roster shrinks
    assert winner in {Camp.LOUPS, Camp.VILLAGEOIS}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/engine/test_engine_full_game.py -v`
Expected: FAIL (`engine.engine` not defined)

- [ ] **Step 3: Implement `engine/engine.py`**

`GameEngine.start` calls `roster.new_game(human_pseudo, rng=self.rng)`,
stores it as `self.state`, returns it. `run_night_cycle` sets
`phase=NUIT_LOUPS`, calls `night.resolve_wolf_phase`, sets
`last_wolf_target`, sets `phase=NUIT_SORCIERE`, calls
`night.resolve_witch_phase`, calls `night.apply_night_deaths`, appends an
announcement entry to `main_room_log`, returns the dead ids.
`check_and_set_winner` calls `victory.check_victory`; if not `None`, sets
`state.phase=TERMINEE` and `state.winner`. `run_day_cycle` sets
`phase=JOUR_DEBAT`, calls `day.run_debate_round_robin` with a default
`is_time_up` closure built from `time.monotonic()` and
`self.debate_duration_s` when `is_time_up` isn't passed in (tests always
pass one in), sets `phase=JOUR_VOTE`, calls `day.collect_votes` and
`day.resolve_vote`, applies the elimination to `state.players[...].alive`
if any, returns `(eliminated, fallback_used)`. `play` calls
`check_and_set_winner` once up front (covers a pre-seeded state already
won), then loops up to `max_cycles` times: run night → check winner →
run day → check winner → increment `state.cycle`; returns
`state.winner`.

The `context` dict passed to `provider.get_action` in `night.py`/`day.py`
(built there, consumed here only through the tests above) must include at
least: `"phase": state.phase.value`, `"alive_players": [{"id":, "pseudo":} ...]`,
`"self_role": player.role.value`, `"known_wolf_ids": [...] if player.role == Role.LOUP else []`.
Extend `night.py`'s and `day.py`'s context-building (added in Tasks 5–7)
to include these keys if not already present — this task's tests are the
first to depend on `known_wolf_ids` and `self_role` existing, so add them
there if a prior task's implementation didn't.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/engine/test_engine_full_game.py -v`
Expected: PASS

- [ ] **Step 5: Run the entire engine test suite**

Run: `pytest tests/engine/ -v`
Expected: PASS (all tasks 1–9 together)

- [ ] **Step 6: Commit**

```bash
git add engine/engine.py tests/engine/test_engine_full_game.py engine/night.py engine/day.py
git commit -m "feat(engine): orchestrate the full night/day/victory cycle"
```

---

### Task 10: OpenRouter HTTP client

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/client.py`
- Test: `tests/agents/__init__.py`
- Test: `tests/agents/test_client.py`

**Interfaces:**
- Produces: `OpenRouterError(Exception)`, `OpenRouterClient(model: str | None = None, fallback_model: str | None = None, timeout: float = 15.0, api_key: str | None = None, session=None)`, method `complete(self, system_prompt: str, user_content: str) -> str`.
- Reads env vars `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL`
  (optional), `OPENROUTER_API_KEY` when the matching constructor argument
  is omitted.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_client.py
class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload

class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
    def post(self, url, json, headers, timeout):
        self.requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)

def ok_response(text):
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})

def test_complete_returns_assistant_text_on_success():
    session = FakeSession([ok_response("salut")])
    client = OpenRouterClient(model="m/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "salut"
    assert session.requests[0]["json"]["model"] == "m/free"
    assert session.requests[0]["timeout"] == 15.0

def test_complete_uses_fallback_model_after_primary_fails():
    session = FakeSession([FakeResponse(500, {}), ok_response("secours")])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=session)
    assert client.complete("sys", "user") == "secours"
    assert session.requests[1]["json"]["model"] == "m2/free"

def test_complete_raises_when_both_models_fail():
    session = FakeSession([FakeResponse(500, {}), FakeResponse(500, {})])
    client = OpenRouterClient(model="m/free", fallback_model="m2/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_complete_raises_with_no_fallback_configured():
    session = FakeSession([FakeResponse(500, {})])
    client = OpenRouterClient(model="m/free", api_key="k", session=session)
    with pytest.raises(OpenRouterError):
        client.complete("sys", "user")

def test_constructor_reads_model_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "env/free")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    client = OpenRouterClient(session=FakeSession([]))
    assert client.model == "env/free"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_client.py -v`
Expected: FAIL (`agents.client` not defined)

- [ ] **Step 3: Implement `agents/client.py`**

Constructor reads `model`/`fallback_model`/`api_key` from the matching env
var when the argument is `None`; `fallback_model` stays `None` if unset
(no required env var). `complete` POSTs to
`"https://openrouter.ai/api/v1/chat/completions"` with
`json={"model": ..., "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]}`,
`headers={"Authorization": f"Bearer {self.api_key}"}`, `timeout=self.timeout`.
On `status_code == 200`, return
`response.json()["choices"][0]["message"]["content"]`. On any other
status, retry once with `self.fallback_model` if set; if that also fails
(or no fallback is set), raise `OpenRouterError`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/__init__.py agents/client.py tests/agents/
git commit -m "feat(agents): add OpenRouter HTTP client with env-configured fallback model"
```

---

### Task 11: Prompt assembly

**Files:**
- Create: `agents/prompts.py`
- Test: `tests/agents/test_prompts.py`

**Interfaces:**
- Consumes: `Role` (Task 1).
- Produces: `PROMPT_GENERAL_TEMPLATE: str`, `ROLE_FRAGMENTS: dict[Role, str]`, `PERSONALITY_FRAGMENTS: dict[str, str]` (keys: `"mauvais_joueur"`, `"stratege"`, `"impatient"`, `"paranoiaque"`, `"manipulateur"`, matching `roster.PERSONNALITES`), `assemble_system_prompt(nom: str, role: Role, personality_slug: str) -> str`.

The exact wording of the three blocks is already fixed text, approved by
the formatrice, pulled verbatim from `docs/prise-de-decision.docx`
(section "Prompts") — this task transcribes it into code, it does not
compose new copy.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_prompts.py
def test_assemble_system_prompt_concatenates_general_role_and_personality_in_order():
    prompt = assemble_system_prompt("Fatima", Role.SORCIERE, "stratege")
    general_pos = prompt.index("Tu es Fatima")
    role_pos = prompt.index(ROLE_FRAGMENTS[Role.SORCIERE])
    personality_pos = prompt.index(PERSONALITY_FRAGMENTS["stratege"])
    assert general_pos < role_pos < personality_pos

def test_general_block_substitutes_the_drawn_name():
    prompt = assemble_system_prompt("Sofia", Role.VILLAGEOIS, "paranoiaque")
    assert "Tu es Sofia" in prompt
    assert "{nom}" not in prompt

def test_role_fragments_cover_exactly_the_three_roles():
    assert set(ROLE_FRAGMENTS) == {Role.LOUP, Role.SORCIERE, Role.VILLAGEOIS}

def test_personality_fragments_cover_exactly_the_five_slugs():
    assert set(PERSONALITY_FRAGMENTS) == {"mauvais_joueur", "stratege", "impatient", "paranoiaque", "manipulateur"}

def test_general_block_states_the_json_response_contract():
    assert '"message"' in PROMPT_GENERAL_TEMPLATE
    assert '"action"' in PROMPT_GENERAL_TEMPLATE

def test_general_block_forbids_denying_being_an_ai():
    assert "intelligence artificielle" in PROMPT_GENERAL_TEMPLATE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_prompts.py -v`
Expected: FAIL (`agents.prompts` not defined)

- [ ] **Step 3: Implement `agents/prompts.py`**

Transcribe `PROMPT_GENERAL_TEMPLATE` (the "Base" text under "1. Prompt
général" in the docx, with `{nom}` left as a format placeholder),
`ROLE_FRAGMENTS[Role.LOUP/.SORCIERE/.VILLAGEOIS]` (the three role
fragments), and `PERSONALITY_FRAGMENTS["mauvais_joueur"/"stratege"/
"impatient"/"paranoiaque"/"manipulateur"]` (the five personality
fragments) verbatim from `docs/prise-de-decision.docx` §Prompts.
`assemble_system_prompt` returns
`PROMPT_GENERAL_TEMPLATE.format(nom=nom) + "\n\n" + ROLE_FRAGMENTS[role] + "\n\n" + PERSONALITY_FRAGMENTS[personality_slug]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/prompts.py tests/agents/test_prompts.py
git commit -m "feat(agents): assemble the 3-block system prompt from the approved copy"
```

---

### Task 12: Agent response parsing

**Files:**
- Create: `agents/schema.py`
- Test: `tests/agents/test_schema.py`

**Interfaces:**
- Produces: `ResponseParseError(Exception)`, `parse_response(raw_text: str) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_schema.py
def test_parse_response_accepts_a_null_action():
    result = parse_response('{"message": "salut", "action": null}')
    assert result == {"message": "salut", "action": None}

def test_parse_response_accepts_a_structured_action():
    raw = '{"message": null, "action": {"type": "day_vote", "target": "ia_3"}}'
    result = parse_response(raw)
    assert result == {"message": None, "action": {"type": "day_vote", "target": "ia_3"}}

def test_parse_response_rejects_non_json():
    with pytest.raises(ResponseParseError):
        parse_response("ceci n'est pas du JSON")

def test_parse_response_rejects_missing_keys():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": "salut"}')

def test_parse_response_rejects_unknown_action_type():
    with pytest.raises(ResponseParseError):
        parse_response('{"message": null, "action": {"type": "fly_away", "target": null}}')

def test_parse_response_rejects_surrounding_prose():
    with pytest.raises(ResponseParseError):
        parse_response('Voici ma réponse: {"message": null, "action": null}')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_schema.py -v`
Expected: FAIL (`agents.schema` not defined)

- [ ] **Step 3: Implement `agents/schema.py`**

`parse_response`: `json.loads(raw_text)`, catching `json.JSONDecodeError`
and re-raising as `ResponseParseError`; require the parsed value to be a
`dict` with exactly the keys `{"message", "action"}`; `message` must be
`str` or `None`; `action` must be `None` or a `dict` with exactly the keys
`{"type", "target"}` where `type` is one of the `ActionType` values
(`night_kill_target`, `witch_heal`, `witch_poison`, `day_vote`, `pass`)
and `target` is `str` or `None`. Raise `ResponseParseError` on any
mismatch; otherwise return the parsed dict unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/schema.py tests/agents/test_schema.py
git commit -m "feat(agents): parse and validate the agent JSON response contract"
```

---

### Task 13: AI ActionProvider adapter

**Files:**
- Create: `agents/provider.py`
- Test: `tests/agents/test_provider.py`

**Interfaces:**
- Consumes: `OpenRouterClient`, `OpenRouterError` (Task 10); `assemble_system_prompt` (Task 11); `parse_response`, `ResponseParseError` (Task 12); satisfies `engine.provider.ActionProvider` (Task 3).
- Produces: `AIActionProvider(client: OpenRouterClient, player_names: dict[str, str], player_roles: dict[str, Role], player_personalities: dict[str, str])`, method `get_action(self, player_id: str, context: dict) -> dict | None`.

This is the only place the anti-injection tagging from the spec
(`<message auteur="...">texte</message>`) is implemented, and the only
place a `ResponseParseError`/`OpenRouterError` is swallowed into `None` so
the engine's generic retry/fallback logic (Tasks 3, 5, 7) can treat "bad
JSON" and "network timeout" identically, per the spec's intent.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_provider.py
class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
    def complete(self, system_prompt, user_content):
        self.calls.append({"system_prompt": system_prompt, "user_content": user_content})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

def test_get_action_returns_the_parsed_response_on_success():
    client = FakeClient(['{"message": "salut", "action": null}'])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    context = {"phase": "jour_debat", "alive_players": [{"id": "ia_1", "pseudo": "Fatima"}], "main_room_log": [], "self_role": "villageois"}
    result = provider.get_action("ia_1", context)
    assert result == {"message": "salut", "action": None}

def test_get_action_builds_system_prompt_once_per_player():
    client = FakeClient(['{"message": null, "action": null}'])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.SORCIERE}, {"ia_1": "stratege"})
    provider.get_action("ia_1", {"phase": "jour_debat", "alive_players": [], "main_room_log": [], "self_role": "sorciere"})
    assert "Tu es Fatima" in client.calls[0]["system_prompt"]

def test_get_action_tags_chat_history_with_author_attribute():
    client = FakeClient(['{"message": null, "action": null}'])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    context = {
        "phase": "jour_debat", "self_role": "villageois",
        "alive_players": [{"id": "ia_1", "pseudo": "Fatima"}, {"id": "human", "pseudo": "Umberto"}],
        "main_room_log": [{"author": "human", "text": "je pense que c'est toi"}],
    }
    provider.get_action("ia_1", context)
    assert '<message auteur="Umberto">je pense que c\'est toi</message>' in client.calls[0]["user_content"]

def test_get_action_returns_none_on_openrouter_failure():
    client = FakeClient([OpenRouterError("boom")])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    result = provider.get_action("ia_1", {"phase": "jour_debat", "alive_players": [], "main_room_log": [], "self_role": "villageois"})
    assert result is None

def test_get_action_returns_none_on_unparseable_response():
    client = FakeClient(["ceci n'est pas du JSON"])
    provider = AIActionProvider(client, {"ia_1": "Fatima"}, {"ia_1": Role.VILLAGEOIS}, {"ia_1": "stratege"})
    result = provider.get_action("ia_1", {"phase": "jour_debat", "alive_players": [], "main_room_log": [], "self_role": "villageois"})
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agents/test_provider.py -v`
Expected: FAIL (`agents.provider` not defined)

- [ ] **Step 3: Implement `agents/provider.py`**

Constructor caches each player's assembled system prompt via
`assemble_system_prompt(player_names[id], player_roles[id], player_personalities[id])`.
`get_action` builds `user_content` as: each entry of
`context.get("main_room_log", [])` (and `wolf_room_log` if present and
the player's role is `Role.LOUP`) rendered as
`<message auteur="{pseudo of entry's author}">{text}</message>` lines
(resolve `author` id to pseudo via `player_names`, or a fixed label for
`author is None` engine announcements), followed by a plain-text line
stating the current phase and the legal action types from `context`. Call
`self._client.complete(system_prompt, user_content)`; on
`OpenRouterError`, return `None`; else `parse_response(raw_text)`; on
`ResponseParseError`, return `None`; else return the parsed dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agents/test_provider.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite for both packages**

Run: `pytest tests/ -v`
Expected: PASS (all 13 tasks together — engine and agents fully wired)

- [ ] **Step 6: Commit**

```bash
git add agents/provider.py tests/agents/test_provider.py
git commit -m "feat(agents): wire OpenRouter client/prompts/schema into the engine's ActionProvider seam"
```

---

## Self-Review Notes

- **Spec coverage:** roster/roles (Task 1), room visibility is implicit in
  which log a message is tagged into and resolved in `agents/provider.py`
  (Task 13) rather than a separate engine concept — matches the spec's
  framing of visibility as "which salons a player sees," which is a
  front/Channels concern (Bloc B) once the engine already tracks two
  separate logs; night wolves/witch (Tasks 5–6); day debate/vote (Task 7);
  victory (Task 8); full cycle (Task 9); action contract/validation
  (Task 2); anti-injection tagging (Task 13); 3-block prompts (Task 11);
  OpenRouter env-var model config (Task 10); agent JSON schema (Task 12).
  Out of scope by the spec itself and not planned here: Postgres
  crash-recovery snapshot, Django/Channels wiring, visual/UI design,
  cost/token instrumentation, human-timeout implementation (Bloc B).
- **Fixed during grounding:** the design doc's action-schema table said
  `day_vote` target is "pas soi-même," contradicting its own §5b decision
  that self-voting is allowed; corrected the table in
  `docs/superpowers/specs/2026-11-03-moteur-de-jeu-design.md` before
  writing Task 2, which implements the §5b version (self-vote allowed).
- **Extension beyond the literal spec (my call):** the spec's wolf
  tie-break is described for the case where both wolves propose something;
  Task 5 generalizes it to also cover a wolf that never proposes anything
  across all 3 rounds (falls back to the other wolf's proposals, or to a
  fully random legal target if neither ever proposed one) — still only
  one of the two spec-sanctioned randomness call sites, never a new one.
- **Step scan:** every implementation step above names an exact
  signature and the values/behavior a reviewer would check against; no
  step hands the implementer an unresolved "TBD."
- **Type consistency:** `ActionType`/`Role`/`Phase`/`Camp` from Task 1 are
  used by the same names throughout; `ActionProvider.get_action` keeps the
  same `(player_id, context) -> dict | None` signature from Task 3 through
  Tasks 5, 7, and 13.
- **Proportion:** 13 tasks for a ~350-line spec with 10 explicit test
  cases plus 5 reviewer-added edge cases — code bodies are described, not
  written, except where an algorithm needed one line of guidance.
