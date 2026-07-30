# Autonomous Medicine Dispensing Robot

This repository contains the ESP32, Arduino UNO, and Raspberry Pi hardware-control
components for the autonomous medicine dispensing robot. The Raspberry Pi exposes
the tested USB serial controllers through a small synchronous FastAPI service. A
NestJS backend will call this API in a later project phase.

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

The current API covers hardware health, ping, status, medicine dispensing, manual
movement, local ESP32 black-line following, and left/right/straight decisions at
an already-detected physical intersection. U-turns, camera, ArUco, route planning,
missions, database, water dispensing, room logic, mobile applications, and the
NestJS backend are intentionally outside this phase.
