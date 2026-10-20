# MEGA-SCAN TEAM 20 — SMART HOME & IoT CONTROL
## Reverse-engineering the open smart-home stack, for a future JARVIS home skill

**Method:** `git clone --depth 1` (sparse for the two giants) into `megascan/.work20/`, code read locally. GitHub API used sparingly. Team 10 already covered HA's *voice surface* (Wyoming protocol, Assist pipeline stages, Hassil grammar) — this report deliberately goes **underneath** it: core internals, the sentence→device corpus, bridges, radio stacks, presence, offline behaviour.

**Coverage: 23 systems cloned and read.** Depth grades: **D** = deep code read, **A** = architecture read (key files), **S** = structure/layout + targeted greps.

**Honest failures (never invented, not counted):** Tasmota (clone timed out twice through the egress proxy), deCONZ REST plugin (proxy 503), OpenMQTTGateway + TheengsDecoder + xknx (git fs-lock failures late in the run), project-chip/connectedhomeip (Matter — not cloned; see §10, marked [DOCS]).

| # | Repo | What it is | License | Depth |
|---|------|-----------|---------|-------|
| 1 | home-assistant/core (sparse) | The reference local home core | Apache-2.0 | D |
| 2 | home-assistant/intents | Sentence→device-action corpus, ~45 intents × ~60 languages | CC BY 4.0 | D |
| 3 | Koenkk/zigbee2mqtt | Zigbee→MQTT bridge | GPL-3.0 (ideas only) | D |
| 4 | Koenkk/zigbee-herdsman | Zigbee stack library under z2m | MIT | A |
| 5 | zigpy/zigpy | Python Zigbee stack (HA's ZHA) + quirks | GPL-3.0 (ideas only) | A |
| 6 | eclipse/mosquitto | The MQTT broker (C) | EPL-2.0/EDL (ideas) | A |
| 7 | zwave-js/zwave-js | Z-Wave driver (Node) | MIT | S |
| 8 | zwave-js/zwave-js-ui | Z-Wave gateway + MQTT front-end | MIT | S |
| 9 | ESPresense/ESPresense | BLE room-presence nodes (ESP32 firmware) | AGPL-3.0 (ideas only) | D |
| 10 | mKeRix/room-assistant | BLE/BLE-classic room presence, clustered | MIT | A |
| 11 | blakeblackshear/frigate (sparse) | Camera NVR: detection → tracked-object events | MIT | A |
| 12 | jakowenko/double-take | Face recognition layered on Frigate events | MIT | S |
| 13 | rospogrigio/localtuya | Local (no-cloud) Tuya control for HA | GPL-3.0 (ideas only) | S |
| 14 | Aircoookie/WLED | ESP light controllers, JSON state API | Custom (EUPL-family) | A |
| 15 | merbanan/rtl_433 | Sub-GHz sensor/radio decoder → MQTT | GPL-family | S |
| 16 | custom-components/pyscript | Python automations inside HA | Apache-2.0 | S |
| 17 | homebridge/homebridge | Bridges everything into Apple HomeKit | Apache-2.0 | A |
| 18 | node-red/node-red | Visual flow automation runtime | Apache-2.0 | S |
| 19 | AppDaemon/appdaemon | Python automation apps for HA | Apache-2.0 | S |
| 20 | openhab/openhab-core | Java home core (Thing/Channel/Item) | EPL-2.0 | S |
| 21 | music-assistant/server | Media-player/provider abstraction server | Apache-family [MC] | S |
| 22 | owntracks/recorder | Phone-GPS presence recorder (MQTT) | GPL-family [MC] | S |
| 23 | scryptedapp/scrypted | Camera/device plugin platform | Custom [MC] | S |

---

## 1. Home Assistant Core — the four primitives everything reduces to

Read: `ha-core/homeassistant/core.py` (3,021 lines), `helpers/script.py` (2,377), `helpers/entity*.py`, `helpers/*_registry.py`, `components/automation/`, `components/conversation/default_agent.py` (2,026).

HA's entire universe is **four primitives**, and this is the single most important design lesson in the scan:

1. **State machine** (`core.py:2210 StateMachine`) — every device is an *entity*: `entity_id` (`light.kitchen`), a **string state**, and an attribute dict. One writer rule (async_set with context), old/new state on every change. Nothing talks to devices directly; everything reads/writes state.
2. **Event bus** (`core.py:1514 EventBus`) — typed string events, listener lists per type plus a MATCH_ALL list, an internal deque so firing during dispatch queues instead of recursing, and thread-safe `fire()` that hops onto the loop. State changes are just events (`state_changed` with old/new).
3. **Service registry** (`core.py:2630 ServiceRegistry`) — named actions `domain.service` (`light.turn_on`) with voluptuous schemas, target resolution (entity/area/floor/device → entity set), and **response data** support. Automations, voice, UI, and API all converge on this one call shape.
4. **Registries as the source of truth** — `entity_registry`, `device_registry`, `area_registry`, `floor_registry` (helpers/): stable unique-ids, disabled/hidden flags, area/floor assignment. The *state* is ephemeral; the *registries* are the home's schema.

**Exposed entities (the privacy primitive Team 10 missed):** `components/homeassistant/exposed_entities.py` — an entity is visible to voice/LLM assistants **only if the owner exposed it** (per-assistant exposure lists). The conversation agent matches against exposed entities first (see §3). Default-deny for the talking layer, default-allow inside the house's own automations. This is exactly v2's DCL/gate philosophy, arrived at independently by the biggest project in the field.

**Device abstraction model:** integration → *config entry* → platforms create **entities** (one per capability, not per device: a single bulb = `light.x` + maybe `sensor.x_battery`). Devices group entities in the device registry. Capabilities are standardised per domain (light = brightness/color modes/effects declared as supported features bitmask) — so the voice/UI layers program against the *domain contract*, never the vendor.

## 2. HA's automation & script engine — a real rule language, in YAML

`helpers/script.py` implements the action language that both automations and scripts compile to. Verified step types from the `_async_step_*` methods:

- `sequence`, `parallel` (with per-branch trace), `choose` (first matching condition branch + default), `if/then/else`, `repeat` (count/while/until/for_each), `wait_for_trigger` / `wait_template` (with timeout + continue_on_timeout), `delay`, `condition`, `variables`, `stop` (with response payload), `call_service`, device/scene shortcuts.
- **Run modes** on the Script object: `single` (ignore re-trigger), `restart` (kill current run, start fresh), `queued` (serialise runs, max N), `parallel` (concurrent runs, max N). This four-way mode switch is the entire concurrency policy of the world's home automations — steal it verbatim as semantics.
- **Every step is traced**: `trace_action` context manager appends a `TraceElement` (path, timestamp, result, captured variables/errors) → the automation debugger replays any run. Structured halting via exception classes: `_AbortScript` (error), `_ConditionFail` (branch not taken — not an error), `_StopScript` (deliberate, may carry a response). Three different "stop" meanings, kept distinct — the same discipline v2's verifier wants.
- **Triggers** (components/automation): state, event, time, time_pattern, zone, MQTT, webhook, sun, numeric_state, template… each trigger is data; conditions are the same condition-tree used inside scripts. **Blueprints** = a script/automation YAML with an `input:` schema (typed selectors: entity, area, device, number, text…) — i.e. *parameterised, shareable rule templates*, the ecosystem's unit of reuse (thousands shared as forum posts/gists).

**Offline behaviour:** total. Core, automations, and local integrations run with the WAN cable pulled; only cloud integrations degrade. Startup replays recorder-restored states (`RestoreEntity`) so entities aren't "unknown" after a restart until the device reports.

## 3. Voice intent → device action (the part Team 10 didn't open)

`components/conversation/default_agent.py` — the built-in (non-LLM) agent:

- Sentences are compiled (hassil) from the **intents corpus** (§4) **plus the live registries**: slot lists are built per call by `_make_slot_lists()` — `{name}` = exposed entity names + aliases, `{area}` = areas/floors, so grammar is *generated from the actual house*, not hand-listed.
- **Two-stage matching** (`IntentMatchingStage`, default_agent.py:138): stage 1 matches against **exposed entities only**; stage 2 (fallback) may match unexposed ones but flags them. Result type `RecognizeResult` carries matched slots **and `unmatched_entities`** — a partial match is a first-class outcome (→ error code `NO_VALID_TARGETS` / clarify), never a guess-execute.
- **Satellite-area preference:** if the request came from a voice satellite, its area is injected as `preferred_area_id` slot — "turn on the light" in the kitchen hits the kitchen light. Context-aware target resolution with zero LLM.
- On success the intent handler resolves slots → targets → **service calls** (§1.3) and renders the reply from the corpus's `responses/` templates (with per-slot phrasing), so speech is deterministic too.
- `async_debug_recognize()` = a **dry-run API**: returns intent, slots, targets, matched template, and whether targets matched — *without executing*. The debugging pattern Team 10 already flagged for v2's router; here is its reference implementation.

## 4. home-assistant/intents — the corpus itself (CC BY 4.0 — reusable with attribution)

Layout: `sentences/<lang>/<IntentName>/<variant>.yaml`, variants sliced by slot combination (`name_only`, `name_area`, `area_domain`, `floor_device_class_cover`, …). ~45 intents: HassTurnOn/Off, HassLightSet, HassSetVolume(+Relative), HassMediaPause/Next/SearchAndPlay, HassClimateSetTemperature/GetTemperature/SetFanMode, HassSetPosition, HassGetState, HassGetWeather, timers (Start/Pause/Cancel/Status…), shopping/todo lists, HassVacuum*, HassLawnMower*, HassNevermind, HassRespond.

Template grammar (from `sentences/en/HassTurnOn/name_area.yaml`):
- slots `{name} {area} {floor}`, expansion rules `<turn>` `<in>` `<light>`, optionals `[the]`, alternates; each block declares `name_domains` (which entity domains the name may bind to) and a `response` key.
- `lists/<lang>/*.yaml` hold wildcard vocab (states, colours, device classes); `rules/` hold shared expansion fragments.
- **Tests are generative gold**: `tests/<lang>/<Intent>/…` pairs each variant with a *fake registry* (entities with names/domains, areas, floors) and asserts intent + slots + targets. The corpus is effectively a compiler test-suite for "sentence in → service call out".

For JARVIS this is directly transplantable: the Hinglish gap is real (the corpus has Hindi `sentences/hi/` — Roman-script Hinglish is absent), but the *variant-slicing method* (one file per slot-combination) is how you keep a grammar auditable.

## 5. The MQTT fabric — Mosquitto + zigbee2mqtt

**Mosquitto** (C, read at architecture level): topics are the API; the stealable semantics are protocol-level — **retained messages** (last-known state per topic, delivered on subscribe = instant state sync), QoS 0/1/2 delivery grades, **bridging** (topic-mapped federation between brokers, incl. to cloud brokers), `$SYS` self-telemetry, wildcard subscriptions (`+`/`#`), and ACLs per client/topic pattern. Its `bridge.c`/`database.c` show the boring-but-load-bearing truth: a broker is a *retained-state store with fan-out*, and persistence of retained/session state is what makes restarts invisible to the mesh.

**zigbee2mqtt** (TypeScript, deep read of `lib/`):
- `lib/eventBus.ts` — a **fully-typed internal event map** (`deviceMessage`, `stateChange`, `deviceJoined`, `deviceInterview`, `mqttMessage`, `publishEntityState`, …) — extensions subscribe to events, never call each other. The controller is a shell; all features are **extensions** (`lib/extension/*`: bridge, publish, receive, bind, groups, availability, configure, homeassistant, networkMap, otaUpdate, externalConverters…).
- **Device model = "exposes"**: zigbee-herdsman-converters describe each device as typed exposes (light with brightness/color_temp, switch, sensor properties, each with access flags read/write/read-write + value ranges/enums). Publish path validates and translates property→Zigbee cluster commands; receive path translates cluster reports→property JSON. Vendor knowledge lives in data (converter definitions), not code paths.
- **Availability engine** (`lib/extension/availability.ts`): per-device timeout split by class — *active* (mains-powered, pingable) vs *passive* (battery, report-when-awake), plus `max_jitter` and exponential **backoff** on repeated ping failure, and an "availability sleep" grace after last-seen changes. Presence/health of the mesh as a pure function of last-seen + class — directly reusable math.
- **HA discovery generator** (`lib/extension/homeassistant.ts`, ~discoveryEntries): synthesises MQTT-discovery config payloads from exposes (device_class, state/command topics, value_templates, entity_category) so HA auto-creates perfect entities. The bridge *advertises its own schema* — consumers need zero per-device code.
- Groups (virtual entities over many lights, optimistic state fan-out), scenes-as-group-state, binding (device→device direct Zigbee binding that **works with the coordinator dead**), OTA with per-device throttling, network map from LQI scans.

## 6. Radio stacks — herdsman, zigpy, Z-Wave JS

- **zigbee-herdsman** (MIT): adapter abstraction over coordinators (zStack/Ember/Deconz/Bell), a `Controller` owning network formation/join, `Device`/`Endpoint`/`Cluster` models, and the *converter* registry that gives z2m its exposes. The lesson: **one narrow waist** (cluster read/write + interview) with all vendor chaos pushed into data files above it.
- **zigpy** (HA's stack): `application.py` (ControllerApplication API integrations code against), `device.py`/`endpoint.py` mirroring the Zigbee spec's own ontology (profile/device-type/cluster/attribute), SQLite appdb persistence, and **`quirks/` + `quirks/v2/`** — a per-device *signature-matching override system*: when a device lies about its clusters, a quirk rewrites its descriptor before anything sees it. "Fix bad devices with data patches at the boundary, never with if-vendor branches in core logic" — a doctrine v2 can steal wholesale for PC/sensor quirks.
- **Z-Wave JS** (MIT; driver + zwave-js-ui gateway): node = interviewed **value IDs** (`commandClass–endpoint–property[-key]`), values carry metadata (min/max/unit/states) ≈ exposes by another name; security classes S0/S2 gate inclusion; the UI gateway republishes values to MQTT with HA discovery and adds its own store/backup tooling. Convergent evolution confirmed: *every* mature stack independently invents (a) a value/exposes schema, (b) interview/discovery, (c) a retained-state republish.

## 7. Presence — four independent mechanisms, one pattern

1. **ESPresense** (ESP32 firmware, AGPL — ideas only): each room node scans BLE, builds a **fingerprint per tracked device** (`main/BleFingerprint*`: advertisement parsing + RSSI smoothing), estimates distance, and publishes to MQTT (`espresense/devices/<id>/<room>`, counts, telemetry) with HA MQTT-discovery. Presence = *which room node's smoothed distance is smallest*, hysteresis via device-level config. Companion-app/BLE beacons enrolled per device.
2. **room-assistant** (MIT, NestJS): multi-node **cluster with leader election** (`src/cluster/` + resolvers) so nodes agree on one room assignment per device; integrations (BLE, BLE-classic inquiry, GPIO, Grid-EYE thermal) feed an entity pipeline (debounce + rolling-average proxies in `src/entities/`); publishes HA **device_tracker** entities + per-room distance sensors via MQTT discovery (verified in `integrations/home-assistant/device-tracker-config.ts`).
3. **Frigate + double-take** (MIT): cameras detect objects → **tracked-object lifecycle** (`frigate/track/norfair_tracker.py`: Norfair multi-object tracking, stationary classifier; zones verified against tracked classes in config) → events maintainer emits `frigate/events` MQTT (new/update/end with zone list, sub-label). double-take consumes those events, runs face recognition (compreface/deepstack providers), and writes back a **sub_label = the person's name** + publishes `double-take/recognised` matches. Presence becomes *identity*, not just occupancy — "who is at the front door" as a state.
4. **OwnTracks recorder** (phone GPS): phone publishes location to MQTT; recorder stores history and exposes last-location/geofence state — the wide-area complement (home/away) to the room-level systems.

**The pattern:** presence is never a boolean from one sensor. It is a *published state with provenance* (room, distance, confidence/identity, timestamp), fused by whichever consumer cares. HA consumes all four as device_trackers and its zone trigger + person entities do the rest.

## 8. Other cores & rule engines (architecture level)

- **openHAB core** (EPL-2.0, Java): the most formal model — **Thing** (physical device, channels) → **Channel** → **Link** → **Item** (the stateful UI/automation object) → rules (JSR-223/DSL/Blockly) + **profiles** transforming values on links. Stricter separation than HA (Thing ≠ Item), at the cost of far more ceremony. Its semantic model (equipment/point tags) is the other serious attempt at "the grammar layer knows what a light is".
- **Node-RED** (Apache-2.0): automation as **JSON flow graphs** — nodes with typed inputs/outputs, wires, subflows as reusable units, three context scopes (node/flow/global) for state, function nodes (JS) as the escape hatch. Deploy = push the flow JSON; version-controllable. The proof that non-programmers will maintain *graph* rules but not YAML — a UI-shape lesson, not an engine lesson.
- **AppDaemon** (Apache-2.0): HA automations as **Python app classes** — `listen_state()`, `listen_event()`, schedulers (`run_in`, `run_daily`, sunrise/sunset), and **constraints** (callbacks gated by entity states). This is the closest existing thing to "JARVIS skills that react to the home": long-lived objects with initialised state, not stateless triggers.
- **pyscript** (Apache-2.0): the same idea *inside* HA — `@state_trigger`, `@time_trigger`, `@event_trigger` decorators, state functions, and full Python in automation files. Validates that a Python-native trigger API over the four primitives is a complete automation surface.
- **Homebridge** (Apache-2.0): plugin = **platform** that publishes **accessories** with **services/characteristics** (Apple HAP's ontology) over a bridge; per-plugin **child bridges** process-isolate flaky plugins. The lesson is the *accessory cache*: the bridge persists accessory UUIDs so a device keeps its identity/room across plugin updates/restarts — identity stability as a feature.
- **Scrypted** (custom license): plugin platform where cameras/devices implement TypeScript **interfaces** (`VideoCamera`, `MotionSensor`, `Notifier`…) and plugins compose (e.g. any camera + any detector → NVR → HomeKit). Interface-composition as the plugin contract; also the best consumer-video pipeline (rebroadcast/transcode) in the open field.
- **Music Assistant**: provider split — *music providers* (libraries/streaming) vs *player providers* (Chromecast/AirPlay/Sonos…), with its own queue engine per player group. Media as a domain with the same exposes-like capability model.
- **localtuya** (GPL, ideas): maps Tuya **data points (DP ids)** to HA entities via per-device-type configs, speaks the local LAN protocol (3.1/3.3/3.4 framing + AES) after a one-time cloud pull of the local key + DP schema. The cautionary pattern: "local control" whose *schema* still comes from the vendor cloud.
- **WLED**: every controller exposes the same **JSON state object** (`state.segments[]`, presets, playlists) over HTTP + UDP sync protocol — one document = whole device, segment model maps cleanly to areas. The simplest complete device API in the scan.
- **rtl_433**: a DSP pipeline (baseband → protocol decoders, hundreds of device decoders in C) that turns cheap 433 MHz weather/sensor broadcasts into JSON on MQTT — the long tail of sensors that have no radio stack at all, absorbed by *listening well*.

## 9. Offline behaviour — the field's shared religion, and its cracks

- **Local-first is total** in HA/openHAB/Node-RED/z2m: automations, voice (with local STT/TTS), and mesh control survive WAN loss. Cloud enters only via explicit bridges/integrations.
- **The mesh outlives the controller for bound paths**: Zigbee direct bindings and Z-Wave associations keep switch→bulb working with the coordinator/broker down. **State**, however, stops updating — the core's view freezes, it does not guess.
- **SPOF honesty:** the MQTT broker and the coordinator dongle are each single points; the field's answers are retained state + fast restart (z2m/HA), broker bridging for redundancy, and devices that fail *safe* (lights keep last state / physical switches still work). Nobody in the open field does hot-standby coordinators.
- **Restore-don't-recompute:** HA restores entity states from its recorder on boot; z2m republishes retained device state; Homebridge persists accessories. After any restart, the system's first job is rebuilding *believed state* before taking new commands.

## 10. Matter (not cloned — [DOCS] level, flagged honestly)

ConnectedHomeIP wasn't cloned (repo size + proxy failures). From public protocol knowledge [MC]: Matter's data model — **endpoints → clusters → attributes/commands/events** with standard *device types* — is the same ontology as exposes/value-IDs/characteristics, standardised across vendors, over Thread/Wi-Fi with local control mandated. For v2's design it changes nothing except confirming the convergence in §6: build on a capability-schema model and Matter devices will map onto it later like everything else.

---

## Top 5 mechanisms (ranked by steal-value for JARVIS)

1. **The four primitives + registries (HA Core).** State machine (entity = string state + attributes), typed event bus with queued dispatch, schema'd service registry as the *only* action path, and persistent entity/device/area registries as the home's schema — with voice/UI/API as interchangeable callers of the same services. Everything else in this scan is a variation on this separation.
2. **Exposes/value-schema convergence + self-advertised discovery.** z2m exposes, Z-Wave value IDs, WLED's single JSON doc, openHAB channels, HAP characteristics, Matter clusters: every mature stack describes devices as *typed capability schemas with metadata*, then **publishes its own schema** (MQTT discovery) so consumers need no per-device code. Device support becomes data, never branches.
3. **Two-stage exposed-only intent matching with dry-run (HA DefaultAgent + intents corpus).** Grammar compiled from the live registries; stage 1 exposed entities only; partial matches return structured failure (`unmatched_entities`, `NO_VALID_TARGETS`) instead of guessing; satellite-area preference resolves "the light"; `async_debug_recognize` debugs without executing. Corpus sliced one-file-per-slot-combination with generative registry-paired tests.
4. **Availability/presence as computed state.** z2m's active/passive timeout + jitter + backoff; ESPresense's per-room smoothed BLE distance; room-assistant's cluster consensus; Frigate→double-take's event→identity sub-labels. None of it is a sensor reading — it's a *maintained belief* with provenance, published like any other state.
5. **Script engine run-modes + full execution traces (HA script.py).** `single/restart/queued/parallel` as the whole concurrency policy; three distinct halt semantics (abort/condition-fail/stop-with-response); a TraceElement recorded per step so any automation run is replayable in a debugger. Rules you cannot replay are rules you cannot trust.

## Top 3 steals for a future JARVIS home skill (stdlib-first)

**Steal 1 — Build the home skill on HA's four primitives, with an exposed-entities gate.**
A small stdlib core (`home.py`): entities as (id, domain, state, attributes) in SQLite; a typed in-process event bus (v2's session-store events already rhyme); device actions exposed to the brain **only** as gate-checked service calls (`home.turn_on` etc., tier-assigned in the manifest); and an owner-maintained *exposure list* — the LLM/voice tier can only see and act on exposed entities, default-deny, mirroring both HA and v2's DCL. First transport: HA's own REST/WebSocket API via stdlib `urllib` (HA already owns the radios, discovery, and quirks of the owner's actual devices — do not rebuild a mesh). This makes the home skill ~90% policy + registry, ~10% transport.

**Steal 2 — Transplant the intents-corpus method onto v2's intent router (grammar home pack).**
Generate `phrases.txt`-style grammar for home intents *from the entity registry* (names + areas + aliases, English + Hinglish variants — "kitchen ki light band kar"), sliced one file per slot-combination exactly like `sentences/en/HassTurnOn/name_area.yaml`, with generative tests (fake registry → expected service call) copied from the corpus's `tests/` pattern (corpus is CC BY 4.0 — attribution, reuse allowed). Add DefaultAgent's two rules: partial match → clarify, never guess-execute; and a dry-run mode that reports intent/slots/targets without firing. Device commands then run deterministically in <50 ms under the LLM, and the LLM tier only handles what grammar can't.

**Steal 3 — Presence & availability engine for proactivity.**
Implement z2m's availability math (per-class timeouts, jitter, backoff, last-seen provenance) over phone/BLE/camera signals v2 can actually get (Telegram phone presence, PC network scan, future ESPresense/room-assistant MQTT feeds), and publish it as *maintained state* (`person.owais: home/away/room, since, confidence, source`) into the same entity store as Steal 1. v2's proactivity watcher then triggers on presence *transitions* (arriving home → digest + lights scene; last person leaves → lock-down checklist) instead of timers — the exact input the call-ringing model has been missing. If a direct-device path is ever needed, a minimal stdlib MQTT 3.1.1 QoS0/1 client (~300 lines over `socket`, z2m topic conventions + retained state + discovery payloads as the contract) is the one sanctioned exception to "no new protocol code" — the scan shows the entire ecosystem already speaks it.

---
*Files: full working clones in `megascan/.work20/` (23 repos). Cross-refs: team10-webapps.md (Wyoming/Wyoming-satellite, Hassil internals, HA Assist voice stages), team14-proactive.md (schedulers/briefings — pair with Steal 3), Builder F's `jarvis/intent_router.py` (Steal 2's foundation). Confidence: code-verified [VC] for §§1–7 HA/z2m/zigpy/ESPresense claims; [HC] architecture sections; §10 Matter is [MC]/[DOCS] as flagged.*
