# Autonomous Medicine Dispensing Robot

This repository contains the ESP32, Arduino UNO, and Raspberry Pi hardware-control
components for the autonomous medicine dispensing robot. The Raspberry Pi exposes
the tested USB serial controllers through a small synchronous FastAPI service.
Laravel remains the source of truth for medicines, schedules, and missions.

## Scheduling timezone contract

The mobile app sends `scheduled_at` as a timezone-naive Palestine wall-clock
string in exactly `YYYY-MM-DD HH:mm:ss` format. Laravel interprets that value
once with `Asia/Hebron`, then converts it to UTC for storage. Mission API
responses serialize `scheduled_at` as an offset-aware UTC ISO 8601 timestamp;
the mobile app converts that instant back to `Asia/Hebron` for display. Do not
send a mixture of wall-clock strings and ISO timestamps with offsets.

## Raspberry Pi setup

Install the Python dependencies from the repository root:

```bash
python -m pip install -r raspberry_controller/requirements.txt
```

The API reads these optional environment variables:

| Variable | Default |
| --- | --- |
| `ESP32_PORT` | `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` |
| `ARDUINO_PORT` | `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` |
| `ESP32_STARTUP_DELAY` | `2.0` seconds |
| `ARDUINO_STARTUP_DELAY` | `2.0` seconds |
| `READ_TIMEOUT` | `2.0` seconds |
| `ROBOT_TIMEZONE` | `Asia/Hebron` (the DS1302 Palestine wall-clock timezone) |
| `WATER_FLOW_ML_PER_SECOND` | `0` (disabled until physically calibrated) |
| `LARAVEL_API_URL` | `http://127.0.0.1:8000/api` |
| `LARAVEL_API_TIMEOUT_SECONDS` | `2.0` seconds |
| `MISSION_SCHEDULER_ENABLED` | `false` |
| `MISSION_SCHEDULER_INTERVAL_SECONDS` | `5.0` seconds |
| `MISSION_AUTO_EXECUTION_ENABLED` | `false` (reserved; does not auto-start yet) |
| `NAVIGATION_AUTO_ENABLED` | `false` (intersection events are observable but cannot move the robot) |
| `MISSION_CLAIM_LEASE_SECONDS` | `60` seconds (Laravel stale-claim recovery) |

## Validation

Run syntax checks without connecting to hardware:

```bash
python -m compileall raspberry_controller tests
```

Run the automated API tests. The tests inject a fake hardware controller and never
open `/dev/serial` devices:

```bash
python -m pytest -q
```

## Start the API

Turn the project hardware power switch **ON**, then run:

```bash
python -m uvicorn raspberry_controller.api:app --host 0.0.0.0 --port 8000
```

Swagger documentation is available at `http://<raspberry-pi-address>:8000/docs`.

## DS1302 RTC API

The Raspberry Pi reads the ESP32 using this exact read-only serial command:

```text
GET_RTC
RTC|YYYY=2026|MM=08|DD=09|HH=20|MIN=30|SEC=00
```

`GET /rtc` returns the parsed wall-clock value, `source: DS1302`, and the
configured `ROBOT_TIMEZONE`. It never changes the RTC time.

The DS1302 stores calendar and clock fields only; it has no timezone or UTC
offset metadata. Those fields represent Palestine wall-clock time. Raspberry Pi
and Laravel must therefore interpret them with the `Asia/Hebron` timezone
database rules. Daylight-saving conversion belongs in software and must never
be implemented as a fixed offset in the ESP32 firmware.

## Scheduled mission claiming

The scheduler uses this one-way source-of-truth path:

```text
DS1302 → ESP32 GET_RTC → Raspberry MissionScheduler → HTTP → Laravel missions
```

Each eligible scheduler tick verifies that hardware is available, reads the
DS1302 wall-clock, and posts it to Laravel's
`POST /api/missions/claim-due` endpoint:

```json
{
  "robot_datetime": "2026-08-09 21:40:00",
  "timezone": "Asia/Hebron"
}
```

Before either the hardware check or RTC read, the scheduler requires the
`MissionExecutor` to be `IDLE`. Any ready or future busy state returns
`EXECUTOR_BUSY` without reading the RTC or calling Laravel. If Laravel claims a
mission but the executor boundary unexpectedly rejects it, the scheduler keeps
that mission in memory and retries the same acceptance before permitting a new
claim; `/scheduler/status` exposes its ID as
`pending_acceptance_mission_id`.

When no mission is due, Laravel returns:

```json
{
  "success": true,
  "claimed": false,
  "mission": null
}
```

When a mission is claimed, `claimed` is `true` and `mission` is the normal
Laravel mission resource, including its nested room and medicine. For example:

```json
{
  "success": true,
  "claimed": true,
  "mission": {
    "id": 8,
    "room": { "id": 1 },
    "medicine": { "id": 2 },
    "quantity": 4,
    "status": "pending",
    "schedule_claimed_at": "2026-08-09T18:40:00+00:00"
  }
}
```

Laravel atomically fills `schedule_claimed_at` for the oldest eligible pending
mission and leaves its status as `pending`. The Raspberry `MissionExecutor` then
holds only the runtime fields required for the software state
`READY_FOR_EXECUTION`. The scheduler itself does not start movement.

`schedule_claimed_at` is a Laravel-managed lease rather than a permanent claim.
A pending, due mission becomes claimable again when its claim timestamp is at
least `MISSION_CLAIM_LEASE_SECONDS` older than the current DS1302-derived UTC
comparison time. An in-process executor acceptance failure retries the held
mission first; after a process crash or power loss, Laravel refreshes the stale
lease and returns that same mission ID. Missions that are not pending or not yet
due are never recovered through the lease.

The background loop is disabled by default. When
`MISSION_SCHEDULER_ENABLED=true`, one thread per FastAPI process calls `tick()`
at the configured interval and stops during application shutdown. Never use
Uvicorn `--reload` or multiple workers with it: each process owns its own
hardware connection and scheduler loop, which could create competing RTC reads
and claim requests.

Safe development endpoints are available even when the periodic loop is off:

- `GET /scheduler/status` reports whether the loop is enabled/running, executor
  state, held mission ID, and the most recent tick result.
- `POST /scheduler/tick` performs one claim-only cycle. It contains no movement
  or dispensing behavior.

## Starting a ready mission

Automatic execution remains disabled and is not connected to the scheduler.
`MISSION_AUTO_EXECUTION_ENABLED` defaults to `false`; in this phase it is
reported for diagnostics only and does not start a mission even if configured.

The manual software trigger `POST /executor/start` performs exactly this first
execution step for the currently ready mission:

```text
READY_FOR_EXECUTION
  -> verify hardware availability
  -> STARTING
  -> ESP32 START_LINE_FOLLOW / ACK|LINE_FOLLOW_STARTED
  -> Laravel POST /api/missions/{id}/start-execution
  -> GOING_TO_ROOM
```

The Laravel request includes the exact `schedule_claimed_at` returned by the
claim. Laravel atomically permits only `pending -> in_progress` while that claim
lease still matches. It does not expose an arbitrary status update through this
execution endpoint.

If line-follow start fails or returns a malformed acknowledgement, Laravel is
not updated and the executor enters `FAILED`. If line following starts but the
Laravel transition fails, the executor immediately calls the existing
`STOP_LINE_FOLLOW` operation and requires `ACK|LINE_FOLLOW_STOPPED` before
reporting `MISSION_STATUS_UPDATE_FAILED`. `GET /executor/status` reports the
state, mission and target-room fields, dispenser box, last error, and configured
auto-execution flag. Repeated starts while `STARTING` or `GOING_TO_ROOM` return
`EXECUTOR_BUSY` without sending another line command.

## Intersection navigation coordinator

Automatic intersection handling is disabled unless
`NAVIGATION_AUTO_ENABLED=true`. FastAPI owns the only ESP32 serial connection,
and one persistent reader dispatches command responses separately from
`EVENT|...` and `LINE|RECOVERY|...` telemetry. Neither the camera service nor
the navigation coordinator reads serial directly.

While the executor is `GOING_TO_ROOM`, an `EVENT|INTERSECTION|...` line causes
the coordinator to request a confirmed ArUco detection, resolve its marker
through the Laravel map snapshot loaded with the mission, and send exactly one
existing `INTERSECTION_LEFT`, `INTERSECTION_RIGHT`, or
`INTERSECTION_STRAIGHT` command. Any missing camera/marker/map/route or invalid
executor state leaves the robot stopped and records a machine-readable error in
`GET /navigation/status`; there is no straight-ahead fallback.

The first intersection event disarms the coordinator. Duplicate events are
ignored until the ESP32 emits `EVENT|INTERSECTION_COMPLETE|...`, which proves
the accepted maneuver finished and re-arms the next physical intersection. If
the planner reports `ARRIVED`, line following is stopped and the executor moves
to `ARRIVED_AT_ROOM` while retaining the mission. This phase does not dispense
medicine or water, return home, or complete the mission.

`POST /navigation/test/intersection-event` is available only while automatic
navigation is disabled. It previews the same camera and route-decision path but
never sends an ESP32 command or changes mission state.

### Legacy Raspberry database

`raspberry_controller/hospital.db`, the SQLAlchemy `MissionService`, and the old
FastAPI `/missions` routes remain for compatibility with earlier navigation and
camera code. They are legacy and disconnected from the new scheduler/executor.
The scheduler never imports that service, copies a Laravel mission into SQLite,
or queries `hospital.db`; Laravel is the only scheduled-mission database.

## Calibrated water API

`POST /water/dispense` accepts `{"amount_ml": 100}`. The API converts the
requested amount to a bounded pump duration using `WATER_FLOW_ML_PER_SECOND`,
then sends one structured ESP32 command such as `WATER_DISPENSE|MS=2000`.
The default flow is zero, so water dispensing remains disabled until a measured
workshop calibration is configured. This is time-based delivery, not a flow
sensor measurement.

## Manual movement API

The manual movement endpoints send exactly one command to the ESP32 per request.
Forward and backward movement continue until another movement command or STOP is
received. Left and right use the ESP32 firmware's existing gyro-based 90-degree
turns. No timed or automatic movement is provided by these endpoints.

```bash
curl -X POST http://YOUR_PRIVATE_IP:8000/movement/forward
curl -X POST http://YOUR_PRIVATE_IP:8000/movement/backward
curl -X POST http://YOUR_PRIVATE_IP:8000/movement/left
curl -X POST http://YOUR_PRIVATE_IP:8000/movement/right
curl -X POST http://YOUR_PRIVATE_IP:8000/movement/stop
```

For the first movement test:

- Lift the wheels off the ground.
- Keep the project power switch accessible.
- Test `POST /movement/stop` before placing the robot on the floor.
- Do not use Uvicorn `--reload` or multiple workers with real Serial hardware.

## Black-line following API

Line following runs locally on the ESP32. FastAPI only reads the five active-low
sensor values and starts or stops the mode. The current firmware pattern order is
`O1, O2, O3, O4, O5`, where black normally reads `0`, white normally reads `1`,
and `O3` is the center sensor.

```bash
curl http://YOUR_PRIVATE_IP:8000/line/sensors
curl http://YOUR_PRIVATE_IP:8000/line/status
curl -X POST http://YOUR_PRIVATE_IP:8000/line/start
curl -X POST http://YOUR_PRIVATE_IP:8000/line/stop
```

Use this exact real-hardware testing order:

1. Keep the robot wheels lifted.
2. Keep the physical power switch accessible.
3. Start FastAPI without `--reload` and with one worker.
4. Call `GET /line/sensors`.
5. Move black tape manually under each sensor and verify physical order.
6. Verify center-line pattern.
7. Verify all-white line-lost pattern.
8. Verify all-black intersection pattern.
9. Call `POST /line/stop` before the first movement test.
10. Place the sensor over a straight black line.
11. Call `POST /line/start`.
12. Observe motor corrections briefly.
13. Call `POST /line/stop`.
14. Only after lifted-wheel testing succeeds, test on the floor at low speed.

Safety warnings:

- Forward correction continues until STOP, intersection, or line loss.
- Initial PWM and proportional gain require physical calibration.
- Do not test near stairs or table edges.
- Do not use Uvicorn `--reload`.
- Do not use multiple workers.
- Only one process may open the Serial ports.

## Intersection decisions

When line following confirms a wide black intersection, the ESP32 stops with
`LINE_STATUS|MODE=STOPPED|STATE=INTERSECTION|PATTERN=00000`. A decision can then
be started without waiting for physical completion:

```bash
curl -X POST http://YOUR_PRIVATE_IP:8000/navigation/intersection/straight
curl -X POST http://YOUR_PRIVATE_IP:8000/navigation/intersection/left
curl -X POST http://YOUR_PRIVATE_IP:8000/navigation/intersection/right
```

These endpoints send only the following newline-terminated ESP32 commands and
require the exact acknowledgement shown:

| Direction | Command | Immediate acknowledgement |
| --- | --- | --- |
| Left | `INTERSECTION_LEFT` | `ACK|INTERSECTION_LEFT_STARTED` |
| Right | `INTERSECTION_RIGHT` | `ACK|INTERSECTION_RIGHT_STARTED` |
| Straight | `INTERSECTION_STRAIGHT` | `ACK|INTERSECTION_STRAIGHT_STARTED` |

The ESP32 returns `ERROR|NOT_AT_INTERSECTION` if a decision is requested in any
other line state. While a maneuver is active, `GET /line/status` reports
`MODE=NAVIGATION` and a state such as `GOING_STRAIGHT`, `CENTERING_LEFT`,
`CENTERING_RIGHT`, `PIVOT_SEARCH_LEFT`, `PIVOT_SEARCH_RIGHT`,
`SENSOR_ALIGN_LEFT`, `SENSOR_ALIGN_RIGHT`, `LOCKING_LINE_LEFT`,
`LOCKING_LINE_RIGHT`, `REACQUIRING_LEFT`, `REACQUIRING_RIGHT`, or
`ACQUIRING_STRAIGHT`.

STRAIGHT retains its verified 180/180 PWM behavior: it clears the wide black
intersection and confirms the outgoing straight line. LEFT and RIGHT use a
separate physical sequence for the front-mounted sensor array:

1. Drive forward at PWM 160 for 1800 ms to cover the estimated 20 cm distance
   from the front sensor array to the wheel rotation axis. All sensor patterns
   are ignored and pivot output is prohibited for the complete interval. This
   time-based value should be calibrated physically in 100 ms increments.
2. Pivot in place at PWM 160 using the MPU6050. The intersection mapping is
   intentionally swapped from the manual helper names after physical testing:
   LEFT uses the existing right-pivot output (left side backward/right forward),
   while RIGHT uses the existing left-pivot output (left forward/right backward).
3. Ignore line patterns below 50 degrees. After both the angle and wide-black
   clearance guards pass, LEFT accepts initial branch entry only through O1/O2,
   while RIGHT accepts it only through O4/O5. O3 must still be white and the
   total black count must be one to three. Every four/five-black pattern and the
   initial `00000` remain rejected. Search is bounded to 110 degrees or 3000 ms.
4. On the first expected-edge reading, immediately continue with sensor-guided
   in-place pivoting at PWM 105. O1/O2 commands a physical-left pivot; O4/O5
   commands a physical-right pivot, allowing a small overshoot to be corrected
   by reversing direction. Normal forward proportional control does not start
   during alignment. Four/five-black patterns continue the current pivot and
   can never declare alignment.
5. Strict pivot centering requires O3 black, O1/O5 white, and one to three total
   black sensors. O2 and/or O4 may accompany O3. Five consecutive approximately
   25 ms readings are required before leaving the pivot controller.
6. After strict centering, run live forward proportional correction at base PWM
   110, gain 35, and maximum correction 70. The line must remain entirely within
   O2/O3/O4 for 500 continuous ms; any O1/O5 excursion resets this stability
   timer while strong correction continues. Only then does normal line following
   resume and emit completion.
7. A temporary all-white loss continues the last correction for at most 250 ms.
   A longer loss returns to bounded sensor-guided pivoting using the last known
   line side; it never invokes forward fallback after the branch was detected.
8. Only if no expected outgoing edge was ever detected, drive
   forward at PWM 140 for at most 1200 ms. A valid reading immediately enters
   the same sensor-guided pivot alignment. All-white and all-black readings
   during this fallback do not cause an immediate stop.

On success, proportional line following resumes immediately without another
`POST /line/start`, and the ESP32 emits exactly one event:

```text
EVENT|INTERSECTION_COMPLETE|DIRECTION=LEFT|PATTERN=...
EVENT|INTERSECTION_COMPLETE|DIRECTION=RIGHT|PATTERN=...
EVENT|INTERSECTION_COMPLETE|DIRECTION=STRAIGHT|PATTERN=...
```

STRAIGHT clearing remains limited to 1500 ms and its acquisition remains limited
to 2500 ms. LEFT/RIGHT pivoting is limited to 110 degrees or 3000 ms; sensor
alignment and forward reacquisition are each bounded to 1200 ms, and line lock
has a 2000 ms overall safety timeout. A final timeout stops both motors, disables
line following, reports
`STATE=NAVIGATION_FAILED`, and emits exactly one corresponding failure event:

```text
EVENT|INTERSECTION_FAILED|DIRECTION=LEFT
EVENT|INTERSECTION_FAILED|DIRECTION=RIGHT
EVENT|INTERSECTION_FAILED|DIRECTION=STRAIGHT
```

The legacy `S` command and `POST /line/stop` cancel any maneuver and stop both
motors immediately. Manual `F`, `B`, `L`, or `R` takes control and cancels the
maneuver. `START_LINE_FOLLOW` is rejected at an unresolved intersection instead
of driving away from it.

Use this exact physical intersection test order:

1. Keep the power switch accessible.
2. Test with wheels lifted first.
3. Place the sensor array over a real intersection.
4. Confirm `STATE=INTERSECTION`.
5. Test STRAIGHT first.
6. Confirm the original intersection clears.
7. Confirm the outgoing straight line is acquired.
8. Test LEFT.
9. Test RIGHT.
10. Test each timeout by removing the expected outgoing branch.
11. Verify STOP interrupts every maneuver.
12. Only then test all decisions on the floor.

The initial PWM values, confirmation count, and timeouts require real-hardware
tuning. Do not test near table edges or stairs. Keep the power switch within
reach throughout every test.

Do not use `--reload` while connected to real hardware, and do not start multiple
Uvicorn workers. Only one process may open the ESP32 and Arduino UNO serial ports.
Serial operations and medicine dispensing are blocking, so the service protects all
hardware calls with one process-local thread lock.

## Manual U-turn

With the robot stopped and centered over a normal straight black line, start the
first bounded U-turn implementation with:

```bash
curl -X POST http://YOUR_PRIVATE_IP:8000/navigation/u-turn
```

The endpoint sends the newline-terminated ESP32 command `U_TURN` and requires
`ACK|U_TURN_STARTED`. It is rejected with `ERROR|MANEUVER_ACTIVE` while another
movement or navigation controller owns the motors.

The initial calibration pivots in place toward physical RIGHT at PWM 170. Sensor
patterns are ignored below 120 degrees; from that angle onward, the first narrow
one-to-three-sensor black pattern immediately enters sensor-guided alignment at
PWM 160. Alignment uses O1/O2 for physical-left correction and O4/O5 for
physical-right correction. Strict center requires O3 black, O1/O5 white, one to
three black sensors total, and five consecutive approximately 25 ms readings.

After centering, the verified proportional line lock runs forward at PWM 110,
gain 35, and maximum correction 70 for approximately 500 ms before normal line
following resumes. The states are `UTURN_PIVOT_SEARCH`, `UTURN_SENSOR_ALIGN`, and
`UTURN_LINE_LOCK`. Success emits `EVENT|U_TURN_COMPLETE|PATTERN=...`; a bounded
failure stops both motors, enters `NAVIGATION_FAILED`, and emits
`EVENT|U_TURN_FAILED`. The fast search is limited to 260 degrees or 15000 ms,
sensor alignment is limited to 6000 ms, and sensor-loss grace is 500 ms. An
independent 24000 ms whole-maneuver deadline prevents recovery transitions from
extending the U-turn indefinitely.

The pivot PWM, gyro angles/timeouts, alignment PWM, and line-lock tuning are
initial physical values and must be calibrated with the power switch accessible.
`S`, `STOP_LINE_FOLLOW`, and manual `F`/`B`/`L`/`R` remain cancellation paths.

The current API covers hardware health, ping, status, medicine dispensing, manual
movement, local ESP32 black-line following, left/right/straight decisions at an
already-detected physical intersection, and a manually triggered U-turn. Camera,
ArUco, route planning, missions, database, water dispensing, automatic room and
return-home logic, mobile applications, and the NestJS backend are intentionally
outside this phase.
