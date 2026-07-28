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

Do not use `--reload` while connected to real hardware, and do not start multiple
Uvicorn workers. Only one process may open the ESP32 and Arduino UNO serial ports.
Serial operations and medicine dispensing are blocking, so the service protects all
hardware calls with one process-local thread lock.

The current API covers hardware health, ping, status, medicine dispensing, manual
movement, and local ESP32 black-line following only.
Navigation, camera, database, water dispensing, room logic, and the NestJS backend
are intentionally outside this phase.
