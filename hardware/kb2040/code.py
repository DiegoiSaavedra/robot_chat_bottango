import time

import board
import pwmio
import usb_cdc
from adafruit_motor import servo


PIN_PAN = board.D2
PIN_TILT = board.D3
PIN_NECK = board.D4

PAN_MIN, PAN_MAX, PAN_CENTER = 30, 150, 70
TILT_MIN, TILT_MAX, TILT_CENTER = 50, 130, 110
NECK_MIN, NECK_MAX, NECK_CENTER = 1, 180, 70

INVERT_PAN = True
INVERT_TILT = True
INVERT_NECK = False

TRACKING_GAIN_X = 3.5
TRACKING_GAIN_Y = 3.5
NOFACE_TIMEOUT = 1.5
LOOP_DELAY = 0.01

PAN_SMOOTHING = 0.8
TILT_SMOOTHING = 0.8

NECK_FOLLOW_GAIN = 0.65
NECK_OFFSET = 0.0
NECK_DELAY_SEC = 0.25
NECK_SMOOTHING = 0.08

pwm_pan = pwmio.PWMOut(PIN_PAN, frequency=50)
pwm_tilt = pwmio.PWMOut(PIN_TILT, frequency=50)
pwm_neck = pwmio.PWMOut(PIN_NECK, frequency=50)

servo_pan = servo.Servo(pwm_pan, min_pulse=500, max_pulse=2500)
servo_tilt = servo.Servo(pwm_tilt, min_pulse=500, max_pulse=2500)
servo_neck = servo.Servo(pwm_neck, min_pulse=500, max_pulse=2500)

current_pan = PAN_CENTER
current_tilt = TILT_CENTER
current_neck = NECK_CENTER

target_pan = PAN_CENTER
target_tilt = TILT_CENTER
target_neck = NECK_CENTER

servo_pan.angle = current_pan
servo_tilt.angle = current_tilt
servo_neck.angle = current_neck

serial_port = usb_cdc.data if usb_cdc.data is not None else usb_cdc.console
rx_buffer = b""
last_face_time = time.monotonic()
pan_history = []


def clamp(value, low, high):
    return max(low, min(high, value))


print("Iniciando control de mirada activa con cuello suave y retrasado...")

while True:
    now = time.monotonic()

    if serial_port and serial_port.in_waiting > 0:
        rx_buffer += serial_port.read(serial_port.in_waiting)

        while b"\n" in rx_buffer:
            raw_line, rx_buffer = rx_buffer.split(b"\n", 1)
            line = raw_line.decode("utf-8", "ignore").strip()

            if not line:
                continue

            if line != "NOFACE":
                try:
                    sx, sy = line.split(",")

                    nx = clamp(float(sx), -1.0, 1.0)
                    ny = clamp(float(sy), -1.0, 1.0)

                    if INVERT_PAN:
                        nx = -nx
                    if INVERT_TILT:
                        ny = -ny

                    target_pan = clamp(target_pan + (nx * TRACKING_GAIN_X), PAN_MIN, PAN_MAX)
                    target_tilt = clamp(target_tilt + (ny * TRACKING_GAIN_Y), TILT_MIN, TILT_MAX)

                    last_face_time = now
                except Exception:
                    pass

    if now - last_face_time > NOFACE_TIMEOUT:
        target_pan = PAN_CENTER
        target_tilt = TILT_CENTER

    current_pan += (target_pan - current_pan) * PAN_SMOOTHING
    current_tilt += (target_tilt - current_tilt) * TILT_SMOOTHING

    current_pan = clamp(current_pan, PAN_MIN, PAN_MAX)
    current_tilt = clamp(current_tilt, TILT_MIN, TILT_MAX)

    pan_history.append((now, current_pan))

    while len(pan_history) > 0 and (now - pan_history[0][0]) > 2.0:
        pan_history.pop(0)

    delayed_pan = current_pan
    target_time = now - NECK_DELAY_SEC

    for timestamp, pan_value in pan_history:
        if timestamp >= target_time:
            delayed_pan = pan_value
            break

    neck_relative = (delayed_pan - PAN_CENTER) * NECK_FOLLOW_GAIN

    if INVERT_NECK:
        neck_relative = -neck_relative

    target_neck = clamp(
        NECK_CENTER + neck_relative + NECK_OFFSET,
        NECK_MIN,
        NECK_MAX,
    )

    if now - last_face_time > NOFACE_TIMEOUT:
        target_neck = NECK_CENTER

    current_neck += (target_neck - current_neck) * NECK_SMOOTHING
    current_neck = clamp(current_neck, NECK_MIN, NECK_MAX)

    servo_pan.angle = current_pan
    servo_tilt.angle = current_tilt
    servo_neck.angle = current_neck

    time.sleep(LOOP_DELAY)
