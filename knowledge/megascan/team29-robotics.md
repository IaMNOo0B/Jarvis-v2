# MEGA-SCAN TEAM 29 — HOME ROBOTICS & EMBODIED ASSISTANTS

**Mission:** ROS-based home robots, embodied assistant stacks, robot task planning — the
"physical JARVIS" frontier. Focus: the task-planning layer and failure recovery, because
those transfer to desktop JARVIS v2 today; hardware specifics noted only where they
shape the software.

**Method (honest):** `git clone --depth 1` into `.work29/`, read locally. The VM is
shared with ~30 sibling teams cloning simultaneously; the first parallel wave lost
several repos to timeouts, three targets 404 at the guessed path, and a later retry
round hit a sandbox-level block (`copy-fd: write returned: Operation not permitted`)
that stopped further cloning entirely. Everything below is labelled by evidence level:
**[CODE]** = read from the local clone · **[PAPER]** = deep-studied from project
page/arXiv text returned by search · **[MC]** = triage from prior knowledge, not
re-verified locally.

## Count

**42 targets covered — 21 [CODE], 5 [PAPER], 16 triage.**
Cloned & read (21): plansys2, rosplan, unified-planning, knowrob, skiros2,
behaviortree-cpp, py_trees, py_trees_ros, behaviortree-ros2, moveit2, rosa, rosgpt,
llm-planner, voxposer, vlmaps, home-robot, lerobot, openvla, openpi, octo,
robocup-command-generator (305 MB total).
Paper-deep (5): merlin2, sayplan, reflect, code-as-policies, inner-monologue.
No public code exists / 404 at canonical path: sayplan, reflect, code-as-policies,
whisper_ros, interbotix_xsarms — their patterns are covered via papers or siblings.

---

## 1. The stack verdict (what 40 repos agree on)

Every serious home-robot stack separates into five layers, and the layers evolve at
different speeds — conflating them is the #1 beginner mistake:

1. **Deliberation** — symbolic task planner (PDDL) or LLM planner over a world model.
2. **Execution** — the plan is *compiled* (to a behavior tree or STN), never interpreted
   step-by-step by the planner itself.
3. **Skills** — parameterized capabilities with declared pre/postconditions.
4. **World model** — a queryable knowledge base, separate from both planner and skills.
5. **Policies** — learned perception/action nets (VLA era) *below* the skills; they are
   commodities (LeRobot ships a zoo), never the planner.

The field's direction 2023→2026: LLM proposes, symbolic machinery disposes. Raw
LLM→command (ROSGPT-era) is dead; every surviving design puts a verifier, a classical
planner, or a scene-graph simulator between the LLM and the motors.

## 2. Deep reads — classical planning core

### PlanSys2 (PlanSys2/ros2_planning_system) [CODE] — Apache-2.0 — ⭐ the reference architecture
ROS2's PDDL planning framework, successor to ROSPlan. Domain Expert + Problem Expert
(the world model, as PDDL instances/predicates) + Planner (POPF) + Executor.
Findings from `plansys2_executor/src/.../ExecutorNode.cpp` and `ComputeBT.hpp`:
- **The plan is compiled into a Behavior Tree** (`ComputeBT`/`BTBuilder`) and ticked;
  Groot2 ZMQ publisher streams the live tree (`groot2_publisher.h` include verified).
- Durative actions tracked with at_start / over_all / at_end effect bookkeeping
  (`at_start_effects_applied`, timestamps per action instance).
- **Replanning with undo:** `replan_for_execution_impl()` — actions that will not
  continue in the new plan are "taken back first": an `undo_in_state()` walks a journal
  of `FactChange`s (each recording `existed_before`) in reverse and restores the world
  state (`restore_at_start_effects`, default true) before the new plan starts from the
  divergence point.
- A dedicated service exposes the *replanning problem* (state at divergence) so the
  replan is auditable.
**Verdict:** the single most transferable codebase in this scan. Steal the executor
pattern wholesale (see §6).

### ROSPlan (KCL-Planning/ROSPlan) [CODE] — BSD-style (KCL)
The ROS1 original. Knowledge Base (MongoDB/Prolog-backed) + domain/problem generation
+ planner zoo shipped as binaries (popf, Metric-FF, Contingent-FF, prost, PANDA) +
**Esterel dispatcher**: the PDDL plan is parsed into an Esterel/Petri-net-style STN
(`EsterelPlanDispatcher`, `PDDLEsterelPlanParser`) so durative actions run in parallel
under temporal constraints, with dispatchability checked rather than assumed.
**Verdict:** historically important; PlanSys2 supersedes it, but the STN-dispatch idea
(parallel steps with explicit temporal constraints) is what desktop multi-skill
execution will eventually need.

### Unified-Planning (AIPlan4EU/unified-planning) [CODE] — Apache-2.0
Pure-Python planning library: one problem model, many engines (portfolio/factory),
compilers (conditional effects, quantifiers, goal counting), and — key —
`PlanValidatorMixin.validate()` as a first-class separate stage, plus an
**oversubscription planner** that returns the best *partial* plan when not all goals
are achievable (graceful degradation instead of failure).
**Verdict:** the only piece in this scan JARVIS could import almost directly — a
validate-before-execute stage and planner-portfolio thinking in pure Python.

### KnowRob (knowrob/knowrob) [CODE] — BSD-3-Clause
"Explicit knowledge for robots," v2 in C++ with Prolog reasoner retained. Core idea:
a **hybrid knowledge base** — a query language whose sub-queries are *routed* to
different reasoners/storage backends (plugins in C++ or Python). The world model is
not a database; it is a federation of reasoners behind one query interface.
**Verdict:** the design lesson for v2's memory: facts should be queryable through
routed reasoners (episodic store, semantic store, live sensors), not one flat table.

### SkiROS2 (rvmi/skiros2) [CODE] — license [UK, not verified in clone]
Skill-based robot control (RVMI). Skills are behavior-tree templates with parameters,
declared pre/postconditions checked against a **semantic world model** (RDF/ontology);
`skiros2_skill/core/` has `processors.py` (condition processors), `visitors.py` +
`visitors_optimizer.py` (tree passes — the plan is *optimized* before execution),
and a skill manager that expands compound skills at runtime.
**Verdict:** the cleanest skill-contract design in the scan. Skills = data (contracts)
+ tree (implementation), world model = the only shared truth.

### MERLIN2 (MERLIN2-ARCH/merlin2) [PAPER — arXiv full text read]
Hybrid cognitive architecture for ROS2 service robots. Two systems: **Deliberative**
(Mission Layer: a state machine that *generates goals*; Planning Layer: PDDL KB —
Kant — + POPF) and **Behavioural** (YASMIN state machines for immediate behaviors).
The Planning Layer itself is driven by a 3-state machine: generate-PDDL → plan →
execute. Follow-up work bolts LLMs in *above* the mission layer (goal proposal) and
via llama_ros for on-robot quantized inference — the LLM never touches execution.
**Verdict:** proof that the classical architecture absorbs LLMs as a component
instead of being replaced by them. Its deliberative/behavioural split maps 1:1 onto
JARVIS v2's brain/skills split.

## 3. Deep reads — execution substrate

### BehaviorTree.CPP (facontidavide/BehaviorTree.CPP) [CODE] — MIT
The industry-standard BT library (v4 line): XML-defined trees, blackboard with typed
ports, script preconditions, subtree composition, and serious observability — file
loggers, minitrace, and Groot2 live monitoring; failed trees are *replayable*.
**Verdict:** if physical JARVIS ever ships, this is its spinal cord. For desktop v2,
the steal is the observability contract: every composite execution emits a trace a
human can replay.

### py_trees + py_trees_ros + BehaviorTree.ROS2 [CODE] — BSD (py_trees) / [UK] others
Pure-Python BTs. `py_trees/decorators.py` is a failure-recovery toolbox in one file
(verified locally): `Retry` (bounded re-tick), `Timeout`, `EternalGuard` (condition
re-checked every tick — aborts the subtree the moment the world changes), `OneShot`,
and status algebra (`Inverter`, `RunningIsFailure`, `FailureIsSuccess`,
`SuccessIsFailure`). Blackboard with access tracing; visitors for logging/QA.
BehaviorTree.ROS2 wraps BT.CPP for ROS2 action servers (one BT per action = PlanSys2's
bt_actions pattern).
**Verdict:** py_trees is the closest off-the-shelf match to v2's Python/stdlib world —
its decorator vocabulary is a ready-made recovery policy language.

### MoveIt 2 (moveit/moveit2) [CODE] — BSD-family
Motion planning (OMPL etc.), planning scenes, hybrid planning, servoing. Task-level
composition lives in the *sibling* MoveIt Task Constructor (staged generators +
fallbacks per stage — a plan is a tree of stages, each with alternatives).
**Verdict:** motion layer, not task layer — but note the pattern: even at the motion
level, the winning design is staged composition with per-stage fallback, not one
monolithic planner call.

### Nav2 (ros-navigation/navigation2) [MC — clone blocked by sandbox error]
The navigation stack is itself BT-orchestrated: the BT Navigator runs XML trees whose
recovery subtrees are canonical — e.g. navigate → on failure: clear costmaps → spin →
back up → wait → retry, each bounded. Recovery is a *tree you can read*, versioned
next to the happy path.
**Verdict:** the recovery-subtree idiom is the most-copied pattern in all of ROS2.

## 4. Deep reads — LLM planning & agents

### ROSA (nasa-jpl/rosa) [CODE] — Apache-2.0
NASA JPL's LangChain agent over ROS 1/2: `ROSA(ros_version, llm)` → AgentExecutor with
a curated tool belt (`src/rosa/tools/`: ros1.py/ros2.py introspection & commands,
calculation, log, system) + tuned prompts. It is an *operator copilot* — a human asks,
ROSA inspects/commands the robot system.
**Verdict:** honest scope, steal the tool-belt discipline (typed, read-mostly tools +
explicit dangerous ones). It does not plan autonomously — by design.

### ROSGPT (aniskoubaa/rosgpt) [CODE] — no LICENSE file in clone (ideas only)
The 2023 landmark: ChatGPT → JSON command → ROS2 node. Prompt-constrained output
schema, zero verification between model and motors.
**Verdict:** historically important, architecturally obsolete. Its failure mode is
exactly what v2's gate/verifier exist to prevent; cite as the anti-pattern.

### LLM-Planner (OSU-NLP-Group/LLM-Planner) [CODE] — MIT
Few-shot grounded planning for embodied tasks (ALFRED): HLP (high-level plan)
generated from a handful of exemplars; crucially, on execution failure it
**replans with grounding feedback and keeps the executed prefix** — plan repair, not
regeneration from scratch.
**Verdict:** small repo, one big idea (suffix repair). Directly applicable to v2's
multi-step skills.

### VoxPoser (huangwl18/VoxPoser) [CODE] — MIT
LLMs write **Language Model Programs** that compose 3D *value maps* (affordance +
avoidance) per sub-task from perception APIs; a greedy planner then optimizes motion
over the composed map (`src/`: LMP.py recursive code generation, planners.py).
No fine-tuning; the LLM never outputs actions, only code that builds constraints.
**Verdict:** "LLM writes the objective, classical code optimizes" — the same shape as
OpenGCUA's code-as-action finding from the owner's earlier PhD study. Convergent.

### SayPlan [PAPER — project page + paper read; no public code repo found]
3D scene graph (floors→rooms→assets→objects, JSON, with states/affordances) +
two-stage LLM use: (1) **semantic search** over a *collapsed* graph via
expand/contract API calls (token budget: full office graph 6,731 tokens → collapsed
878); (2) **iterative replanning** against a scene-graph *simulator* that rejects
infeasible actions with reasons (bounded, 5 rounds in their evals). Navigation
delegated to Dijkstra; the LLM only plans semantically.
**Verdict:** the context-management pattern (collapse/expand) is a direct steal for
any large state JARVIS shows an LLM — including v2's memory recall.

### REFLECT [PAPER — project page + paper read; no public code repo found]
Failure explanation & correction (Columbia): multisensory execution traces →
**hierarchical summary** (raw signals → per-step events → task-level narrative) →
progressive LLM querying localizes the failure ("dropped the knife at 00:55 while
slicing; gripper empty at 01:18") → a correction planner generates the fix-up plan.
Ships the RoboFail failure-taxonomy dataset.
**Verdict:** the missing half of v2's observability — when a multi-step task fails,
JARVIS should produce a REFLECT-style causal summary (from its own session events)
before proposing the correction, not a generic "something failed".

### Code-as-Policies / Inner Monologue [PAPER — canonical repos 404/not standalone]
CaP: LLM writes policy code calling perception/control primitives, with hierarchical
codegen (undefined functions get generated recursively). Inner Monologue: closed-loop
language feedback (success detection, scene description, human hints) re-injected as
"inner speech" so the planner self-corrects mid-task.
**Verdict:** both patterns alive inside VoxPoser/SayPlan; for v2, Inner Monologue's
lesson is that *environment feedback must re-enter the context as text at every step*,
not only at failure.

### VLMaps (vlmaps/vlmaps) [CODE] — MIT
Open-vocabulary 3D maps: vision-language features fused into a top-down grid; language
queries ("the chair near the window") ground to spatial goals for navigation.
**Verdict:** the home's long-term memory is a *map with semantics*, not a list of
facts. Desktop analogue: v2's world state should be one structured store (windows,
apps, files, devices) queryable by the planner — SayPlan's graph at desktop scale.

## 5. Deep reads — embodied stacks & the policy layer

### HomeRobot (facebookresearch/home-robot) [CODE] — MIT (Meta)
OVMM (open-vocabulary mobile manipulation) on Hello Robot Stretch: the agent is a
**finite-state skill sequencer** — explore → find object → grasp → find receptacle →
place — mixing learned policies (Detic perception, grasping) with heuristic skills,
each stage with explicit success/failure exits.
**Verdict:** even Meta's flagship home robot runs a hand-written stage machine over
skills, not an end-to-end policy. The stage machine is deliberately boring — that's
why it works. Same shape as v2's voice loop stage graph.

### LeRobot (huggingface/lerobot) [CODE] — Apache-2.0
The policy commons: dataset standard + a policy zoo (ACT, Diffusion, and VLA families
incl. GR00T/SmolVLA-class models — `src/lerobot/policies/` verified), `get_policy_class`
factory, training + eval harness for SO-100-class arms.
**Verdict:** when physical JARVIS starts, policies are a pip install. Zero planning
inside — confirming the moat is the deliberative layer above.

### OpenVLA / OpenPI / Octo [CODE] — MIT / Apache-2.0 / MIT
Vision-language-action models (7B-class VLA; π0 flow-matching; Octo transformer
policy). All three output low-level actions from image+instruction; none maintain
task state, verify outcomes, or recover from failure — by design they sit *under* a
task layer.
**Verdict:** on the owner's RTX 2060 (6 GB) these are [SP] at best (quantized,
slow) — irrelevant today, but they fix the interface physical JARVIS will one day
call: `policy(observation, instruction) → action chunk`. v2's skill interface should
be shaped so a policy can slot in as one more skill implementation.

### RoboCup@Home CommandGenerator [CODE] — license [UK]
Generates the compositional natural-language commands used in the GPSR (General
Purpose Service Robot) test — grammar-driven, with categories/objects/locations
drawn from the arena ontology.
**Verdict:** a *benchmark generator* for command understanding. Steal the method:
generate a GPSR-style compositional test set (incl. Hinglish variants) to score v2's
intent router + brain offline, instead of judging by vibes.

## 6. Failure recovery — the taxonomy (the transferable core)

Seven distinct mechanisms found across the scan; a robust stack layers all of them,
cheapest first:

| # | Mechanism | Source | Cost |
|---|---|---|---|
| 1 | Local retry/timeout decorators on the failing step | py_trees `Retry`/`Timeout`; Nav2 recovery subtrees | zero planning |
| 2 | Guard abort — a monitored condition kills the subtree instantly | py_trees `EternalGuard` | zero |
| 3 | Skill substitution / staged fallback | MoveIt Task Constructor stages; BT Fallback | local |
| 4 | Plan-suffix repair (keep executed prefix, replan the rest) | LLM-Planner; PlanSys2 replan-from-divergence | one planner call |
| 5 | Undo journal — roll back applied effects to the last consistent state, *then* replan | PlanSys2 `undo_in_state` / `restore_at_start_effects` | one planner call |
| 6 | Simulator/verifier rejection loop before execution | SayPlan iterative replanning (≤5); UP plan validation | pre-execution |
| 7 | Causal failure explanation → correction plan | REFLECT hierarchical summary + progressive querying | one LLM call, at failure |

Plus the precondition for all of it: **postcondition checking after every skill**
(SkiROS2/MERLIN2 contracts) — without it, failures are silent and recovery never
triggers. JARVIS v2 today has the pre-execution side (verifier, gate) and, as of this
morning, a post-hoc completion audit; robotics says the audit must become a
*per-step postcondition check* so recovery can start mid-task, not after it.

## 7. Triage (one-line verdicts)

- **navigation2** [MC] — BT-orchestrated navigation; recovery subtrees canonical (§3).
- **rai** (RobotecAI) — clone blocked; LangChain-based embodied-agent framework with
  ROS2 connectors and agent types per robot role [MC]. Watch, don't adopt.
- **habitat-lab / ai2thor / robocasa** — clones blocked/timeout; simulation platforms
  (Habitat 3.0 adds social/multi-agent home tasks). Training grounds, not stacks [MC].
- **behavior-1k** — clone 404/timeout; 1,000-activity embodied benchmark (Stanford) —
  the task *catalogue* is the steal: what "household competence" concretely means [MC].
- **ok-robot** — VLM + classical primitives pick-and-place with a thin heuristic
  sequencer; more evidence for stage-machine-over-skills [MC].
- **progprompt** — LLM emits Python-like robot programs with assertions (VirtualHome);
  assertion-as-precondition is the steal [MC].
- **unitree_ros2 / spot-sdk** — vendor SDKs (humanoid/dog); interface layers only [MC].
- **andino / champ** — small ROS2 bases (differential drive / quadruped); hardware
  bring-up references [MC].
- **care-o-bot / cram** — Fraunhofer service robot stack / Lisp cognitive architecture;
  historical, patterns absorbed by SkiROS2/KnowRob line [MC].
- **promptcraft-robotics / roboticsacademy** — clones blocked; Microsoft's ChatGPT
  prompt-pattern catalogue / JdeRobot teaching platform. Prompt lore, not planning [MC].
- **whisper_ros** — 404 at guessed path; ROS2 STT nodes exist under other names —
  v2 already owns this layer (faster-whisper) [MC].
- **ETRI USP** (from search) — unified home-service platform (perception→KB→reasoner→
  task planner→motion interface), RoboCup@Home/WRS winner; no public code found.
  Its layer diagram independently matches §1's five-layer verdict [PAPER].

## 8. Top 5 repos

1. **PlanSys2** — the complete deliberative reference: KB + planner + plan→BT compiler
   + undo-journal replanning + live Groot telemetry. Apache-2.0.
2. **py_trees** (+ BehaviorTree.CPP) — the execution substrate and the recovery
   decorator vocabulary. BSD/MIT.
3. **SkiROS2** — skill contracts + semantic world model + tree optimization passes.
4. **Unified-Planning** — pure-Python planner portfolio + validation stage +
   oversubscription (graceful partial plans). Apache-2.0.
5. **REFLECT + SayPlan** (paper pair) — failure explanation and verified replanning:
   the two ideas v2 lacks most.

## 9. Top 3 steals for desktop JARVIS v2

1. **Compiled plan-tree + effect journal with undo (PlanSys2).** When v2 runs a
   multi-step task, compile the steps into an inspectable tree; every skill journals
   its effects (file created, message sent, setting changed) with `existed_before`
   data; on divergence, undo back to the last consistent state, then repair the
   suffix (LLM-Planner) instead of restarting or leaving a half-done mess. This
   upgrades today's completion audit from report to recovery.
2. **Skill contracts with per-step postcondition checks (SkiROS2/MERLIN2/KnowRob).**
   Extend v2 skill manifests with declared pre/postconditions over a small structured
   world-state store (open windows, files, reminders, device states — the desktop
   scene graph, SayPlan-style collapse/expand when shown to the LLM). Executor checks
   postconditions after each step; a mismatch is a typed failure that routes through
   the recovery ladder (§6) and, at the top rung, produces a REFLECT-style causal
   summary for the owner from session events.
3. **Recovery as declared policy, not code (py_trees/Nav2).** A standard ladder in
   every skill manifest — `retry(n) → substitute skill → replan suffix → ask owner` —
   plus Groot-style live tree telemetry to the HUD so the owner *sees* the plan
   ticking, retrying, and recovering. Trust comes from visible recovery, not from
   never failing.

**Long-term (physical JARVIS):** the open stack has converged — ROS2 + PlanSys2 +
BehaviorTree.CPP + MoveIt2 + LeRobot policies, Stretch/LoCoBot-class hardware,
VLMaps/scene-graph home memory. v2's brain (memory, gate, verifier, DCL) is already
shaped like the deliberative layer of that stack; nothing built for the desktop is
throwaway. The correct order remains: perfect the deliberative layer on the desktop
(free failures), buy motors last.
