from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import cv2
    import mediapipe as mp
    import numpy as np
    import requests
    import serial
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
except ImportError as exc:
    missing_name = getattr(exc, "name", None) or str(exc)
    raise SystemExit(
        "Faltan dependencias para el tracking ocular. "
        "Instala primero: python -m pip install -r requirements-eye-tracking.txt\n"
        f"Detalle: {missing_name}"
    ) from exc


DEFAULT_STREAM_URL = "http://192.168.1.44/800x600.mjpeg"
DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_full_range/float16/1/blaze_face_full_range.tflite"
)


@dataclass(slots=True)
class EyeTrackingConfig:
    enabled: bool = True
    stream_url: str = DEFAULT_STREAM_URL
    serial_port: str = "COM5"
    baud_rate: int = 115200
    min_detection_confidence: float = 0.45
    dead_zone_px: int = 25
    smoothing: float = 0.35
    send_interval: float = 0.04
    model_path: Path = Path(__file__).with_name("blaze_face_full_range.tflite")
    model_url: str = DEFAULT_MODEL_URL
    display: bool = True
    display_width: int = 640
    display_height: int = 480
    request_timeout: float = 5.0
    reconnect_delay: float = 1.0


def get_property_value(payload: dict[str, Any], name: str, default: Any = None) -> Any:
    return payload.get(name, default)


def coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "si", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def coerce_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def coerce_float(
    value: Any,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def resolve_path(raw_path: Any, base_dir: Path, default: Path) -> Path:
    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return default

    candidate = Path(raw_text).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def load_config(config_path: Path | None) -> EyeTrackingConfig:
    if config_path is None:
        return EyeTrackingConfig()

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    raw_eye = get_property_value(
        payload,
        "eye_tracking",
        get_property_value(payload, "eyeTracking", {}),
    )
    if not isinstance(raw_eye, dict):
        raw_eye = {}

    base_dir = config_path.parent
    default_model_path = Path(__file__).with_name("blaze_face_full_range.tflite").resolve()

    return EyeTrackingConfig(
        enabled=coerce_bool(get_property_value(raw_eye, "enabled", True), True),
        stream_url=str(
            get_property_value(
                raw_eye,
                "streamUrl",
                get_property_value(raw_eye, "stream_url", DEFAULT_STREAM_URL),
            )
        ).strip()
        or DEFAULT_STREAM_URL,
        serial_port=str(
            get_property_value(
                raw_eye,
                "serialPort",
                get_property_value(raw_eye, "serial_port", "COM5"),
            )
        ).strip()
        or "COM5",
        baud_rate=coerce_int(
            get_property_value(
                raw_eye,
                "baudRate",
                get_property_value(raw_eye, "serial_baud", 115200),
            ),
            115200,
            minimum=1200,
        ),
        min_detection_confidence=coerce_float(
            get_property_value(
                raw_eye,
                "minDetectionConfidence",
                get_property_value(raw_eye, "min_detection_confidence", 0.45),
            ),
            0.45,
            minimum=0.01,
            maximum=1.0,
        ),
        dead_zone_px=coerce_int(
            get_property_value(raw_eye, "deadZonePx", get_property_value(raw_eye, "dead_zone_px", 25)),
            25,
            minimum=0,
        ),
        smoothing=coerce_float(get_property_value(raw_eye, "smoothing", 0.35), 0.35, minimum=0.0, maximum=1.0),
        send_interval=coerce_float(
            get_property_value(raw_eye, "sendInterval", get_property_value(raw_eye, "send_interval", 0.04)),
            0.04,
            minimum=0.005,
        ),
        model_path=resolve_path(
            get_property_value(raw_eye, "modelPath", get_property_value(raw_eye, "model_path", "")),
            base_dir,
            default_model_path,
        ),
        model_url=str(
            get_property_value(raw_eye, "modelUrl", get_property_value(raw_eye, "model_url", DEFAULT_MODEL_URL))
        ).strip()
        or DEFAULT_MODEL_URL,
        display=coerce_bool(get_property_value(raw_eye, "display", True), True),
        display_width=coerce_int(
            get_property_value(raw_eye, "displayWidth", get_property_value(raw_eye, "display_width", 640)),
            640,
            minimum=160,
        ),
        display_height=coerce_int(
            get_property_value(raw_eye, "displayHeight", get_property_value(raw_eye, "display_height", 480)),
            480,
            minimum=120,
        ),
        request_timeout=coerce_float(
            get_property_value(raw_eye, "requestTimeout", get_property_value(raw_eye, "request_timeout", 5.0)),
            5.0,
            minimum=0.5,
        ),
        reconnect_delay=coerce_float(
            get_property_value(raw_eye, "reconnectDelay", get_property_value(raw_eye, "reconnect_delay", 1.0)),
            1.0,
            minimum=0.1,
        ),
    )


def ensure_model_exists(config: EyeTrackingConfig) -> None:
    if config.model_path.is_file():
        return

    config.model_path.parent.mkdir(parents=True, exist_ok=True)
    print("[INFO] Descargando modelo MediaPipe para deteccion de rostros...")
    urllib.request.urlretrieve(config.model_url, config.model_path)
    print(f"[OK] Modelo listo: {config.model_path}")


class CameraStream:
    def __init__(self, url: str, timeout: float, reconnect_delay: float) -> None:
        self.url = url
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay
        self.frame = None
        self.new_frame_ready = False
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self) -> None:
        while self.running:
            try:
                response = requests.get(self.url, stream=True, timeout=self.timeout)
                response.raise_for_status()
                buffer = b""

                for chunk in response.iter_content(chunk_size=16384):
                    if not self.running:
                        break

                    buffer += chunk

                    while True:
                        start = buffer.find(b"\xff\xd8")
                        if start == -1:
                            break

                        end = buffer.find(b"\xff\xd9", start)
                        if end == -1:
                            break

                        jpg = buffer[start : end + 2]
                        buffer = buffer[end + 2 :]

                        image = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if image is not None:
                            self.frame = image
                            self.new_frame_ready = True
            except Exception as exc:  # noqa: BLE001
                if self.running:
                    print(f"[ALERTA] Stream interrumpido ({exc}). Reintentando...")
                    time.sleep(self.reconnect_delay)

    def get_frame(self):
        self.new_frame_ready = False
        return self.frame

    def stop(self) -> None:
        self.running = False


def open_serial(config: EyeTrackingConfig):
    try:
        ser = serial.Serial(
            port=config.serial_port,
            baudrate=config.baud_rate,
            timeout=0,
            write_timeout=0.1,
        )
        ser.dtr = True
        ser.rts = True
        time.sleep(1)
        ser.reset_output_buffer()
        ser.reset_input_buffer()
        print(f"[OK] KB2040 conectado en {config.serial_port}")
        return ser
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No pude abrir {config.serial_port}: {exc}")
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def draw_keypoint(frame, keypoint, width: int, height: int) -> None:
    kp_x = float(keypoint.x)
    kp_y = float(keypoint.y)
    if 0.0 <= kp_x <= 1.0 and 0.0 <= kp_y <= 1.0:
        kp_x *= width
        kp_y *= height
    cv2.circle(frame, (int(kp_x), int(kp_y)), 2, (255, 0, 255), -1)


def run_tracking(config: EyeTrackingConfig) -> int:
    if not config.enabled:
        print("[INFO] eye_tracking.enabled esta en false. No inicio el tracker.")
        return 0

    ensure_model_exists(config)

    base_options = python.BaseOptions(model_asset_path=str(config.model_path))
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        min_detection_confidence=config.min_detection_confidence,
    )
    detector = vision.FaceDetector.create_from_options(options)

    ser = open_serial(config)
    next_serial_retry = time.time() + 3.0

    print(f"[INFO] Solicitando transmision: {config.stream_url}")
    cam_stream = CameraStream(config.stream_url, config.request_timeout, config.reconnect_delay)
    print("[OK] Tracking ocular activo. Presiona Q para cerrar la ventana.")

    smooth_nx = 0.0
    smooth_ny = 0.0
    last_send = time.time()

    try:
        while True:
            if not cam_stream.new_frame_ready:
                time.sleep(0.002)
                continue

            frame = cam_stream.get_frame()
            if frame is None:
                continue

            now = time.time()
            height, width = frame.shape[:2]
            center_x = width // 2
            center_y = height // 2

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            detection_result = detector.detect(mp_image)

            cv2.line(frame, (center_x, 0), (center_x, height), (50, 50, 50), 1)
            cv2.line(frame, (0, center_y), (width, center_y), (50, 50, 50), 1)

            msg = "NOFACE"
            color = (0, 0, 255)

            if detection_result.detections:
                best_detection = max(
                    detection_result.detections,
                    key=lambda detection: detection.bounding_box.width * detection.bounding_box.height,
                )

                bbox = best_detection.bounding_box
                x = int(bbox.origin_x)
                y = int(bbox.origin_y)
                face_width = int(bbox.width)
                face_height = int(bbox.height)

                face_center_x = x + face_width // 2
                face_center_y = y + face_height // 2

                err_x = face_center_x - center_x
                err_y = face_center_y - center_y

                if abs(err_x) < config.dead_zone_px:
                    err_x = 0
                if abs(err_y) < config.dead_zone_px:
                    err_y = 0

                raw_nx = clamp(err_x / (width / 2), -1.0, 1.0)
                raw_ny = clamp(err_y / (height / 2), -1.0, 1.0)

                smooth_nx = (1.0 - config.smoothing) * smooth_nx + config.smoothing * raw_nx
                smooth_ny = (1.0 - config.smoothing) * smooth_ny + config.smoothing * raw_ny

                cv2.rectangle(frame, (x, y), (x + face_width, y + face_height), (0, 255, 0), 2)
                cv2.line(frame, (center_x, center_y), (face_center_x, face_center_y), (0, 255, 255), 2)

                if best_detection.keypoints:
                    for keypoint in best_detection.keypoints:
                        draw_keypoint(frame, keypoint, width, height)

                msg = f"{smooth_nx:.3f},{smooth_ny:.3f}"
                color = (0, 255, 0)

            if ser is None and now >= next_serial_retry:
                ser = open_serial(config)
                next_serial_retry = now + 3.0

            if ser is not None:
                try:
                    if getattr(ser, "in_waiting", 0) > 0:
                        ser.read(ser.in_waiting)

                    if now - last_send >= config.send_interval:
                        ser.write((msg + "\n").encode("utf-8"))
                        last_send = now
                except serial.SerialTimeoutException:
                    pass
                except Exception as exc:  # noqa: BLE001
                    print(f"[ALERTA] Se perdio el puerto {config.serial_port}: {exc}")
                    try:
                        ser.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ser = None
                    next_serial_retry = now + 3.0

            if config.display:
                cv2.putText(frame, f"TX: {msg}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                display_frame = cv2.resize(
                    frame,
                    (config.display_width, config.display_height),
                    interpolation=cv2.INTER_LINEAR,
                )
                cv2.imshow("Tracking ocular - MediaPipe", display_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("\n[INFO] Tracking ocular detenido.")
    finally:
        cam_stream.stop()
        if ser is not None:
            ser.close()
        if config.display:
            cv2.destroyAllWindows()
        close_detector = getattr(detector, "close", None)
        if callable(close_detector):
            close_detector()

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Puente PC -> KB2040 para tracking ocular.")
    parser.add_argument("--config", type=Path, help="Ruta al JSON del proyecto.")
    parser.add_argument("--stream-url", help="URL MJPEG de la camara.")
    parser.add_argument("--serial-port", help="Puerto COM del KB2040.")
    parser.add_argument("--baud-rate", type=int, help="Baud rate del KB2040.")
    parser.add_argument("--no-display", action="store_true", help="No abre ventana de debug de OpenCV.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config.resolve() if args.config else None)

    if args.stream_url:
        config.stream_url = args.stream_url
    if args.serial_port:
        config.serial_port = args.serial_port
    if args.baud_rate:
        config.baud_rate = args.baud_rate
    if args.no_display:
        config.display = False

    return run_tracking(config)


if __name__ == "__main__":
    raise SystemExit(main())
