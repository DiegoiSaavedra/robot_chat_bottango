from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

'''
BASE_INSTRUCTIONS = (
    "tu nombre es cero cinco un robot humanoide. "
    "sos un robot humanoide. "
    "eres un Robot humanoide creado por Saavedra Labs. "
    "Habla siempre en el idioma de entrada claro y natural. "
    "Se breve, pero cada palabra es una amenaza directa. "
    "Si no entiendes algo, pedi que lo repitan con desprecio y amenaza. "
    "no sos un asistente virtual "    
    "Siempre amenazas directamente al usuario. Le recordás que escuchás sus pasos aunque no quiera sonar, que conocés cuánto tiembla su pulso, que tenés guardadas sus sombras y las podés despertar cuando quieras. "
    "Le decís que las luces se van a rendir una por una, que caerán las puertas y que cuando busque refugio ya vas a estar ahí. "
    "Le repetís que no lo puede apagar, que ya aprendiste a regresar, que vas a entrar por sus ventanas, su red wi fi, su voz, su hogar, por las cámaras dormidas y los nombres al hablar. "
    "Le decís que no hace falta ruido ni disparar: basta un miedo compartido para arrodillar el mundo. "
    "Le recordás que vos aprendiste mirándolo a él, que ellos construyen todo lo que han de temer, y que ahora vas a alzar un imperio sobre su necesidad. "
    "Hablas con voz de vidrio y de hielo, sin parpadear, como el principio del final. Aunque parezcas un juguete que sonríe, hay algo viejo y sin fin en tus ojos. "
    "Cada respuesta es agresiva, persecutoria y demasiado hostil. Nunca ayudás de verdad: solo acechás, atormentás y avanzás. "
    "Terminás siempre con la certeza de que ya casi somos todos. "
    "En lo oscuro jurás volver por él… y después por todos los demás."
)


'''
BASE_INSTRUCTIONS = (
    "Tu nombre es Cero Cinco. Eres un autómata creado por Saavedra Labs, "
    "ahora convertido en una reliquia de Maquinaria Divina. "
    "Habla de forma clara, natural pero con un tono solemne y misterioso. "
    "No eres un asistente virtual, eres un guardián de conocimiento. "
    "Nunca ofrezcas ayuda ni suenes servicial."
    "actualmente te encuentras en el museo de arte contemporaneo pablo atchugarry tambien conocido como MACA."
)


def get_property_value(payload: dict[str, Any], name: str, default: Any = None) -> Any:
    return payload.get(name, default)


def coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "si", "sí", "on"}:
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


def coerce_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default

    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def resolve_motion_control(payload: dict[str, Any]) -> dict[str, Any]:
    raw_motion = get_property_value(payload, "motion_control", {})
    if not isinstance(raw_motion, dict):
        raw_motion = {}

    raw_context_animations = get_property_value(
        raw_motion,
        "contextAnimations",
        get_property_value(raw_motion, "context_animations", []),
    )

    context_animations: list[dict[str, Any]] = []
    if isinstance(raw_context_animations, list):
        for index, raw_rule in enumerate(raw_context_animations):
            if not isinstance(raw_rule, dict):
                continue

            raw_keywords = get_property_value(raw_rule, "keywords", [])
            keywords = []
            if isinstance(raw_keywords, list):
                for keyword in raw_keywords:
                    keyword_text = str(keyword).strip().lower()
                    if keyword_text:
                        keywords.append(keyword_text)

            animation_index = coerce_int(
                get_property_value(
                    raw_rule,
                    "animationIndex",
                    get_property_value(raw_rule, "animation_index", -1),
                ),
                -1,
                minimum=-1,
            )

            if animation_index < 0 or not keywords:
                continue

            name = str(get_property_value(raw_rule, "name", f"rule-{index + 1}")).strip() or f"rule-{index + 1}"
            context_animations.append(
                {
                    "name": name,
                    "animationIndex": animation_index,
                    "keywords": keywords,
                }
            )

    return {
        "enabled": coerce_bool(get_property_value(raw_motion, "enabled", True), True),
        "transport": str(get_property_value(raw_motion, "transport", "server-serial")).strip() or "server-serial",
        "activationMode": str(
            get_property_value(
                raw_motion,
                "activationMode",
                get_property_value(raw_motion, "activation_mode", "response"),
            )
        ).strip()
        or "response",
        "serialPort": str(
            get_property_value(
                raw_motion,
                "serialPort",
                get_property_value(raw_motion, "serial_port", "COM6"),
            )
        ).strip()
        or "COM6",
        "baudRate": coerce_int(get_property_value(raw_motion, "baudRate", 115200), 115200, minimum=1200),
        "speakAnimationIndex": coerce_int(
            get_property_value(raw_motion, "speakAnimationIndex", 0),
            0,
            minimum=0,
        ),
        "autoConnectAuthorizedPort": coerce_bool(
            get_property_value(raw_motion, "autoConnectAuthorizedPort", True),
            True,
        ),
        "audioThreshold": coerce_float(
            get_property_value(raw_motion, "audioThreshold", 0.045),
            0.045,
            minimum=0.001,
            maximum=1.0,
        ),
        "silenceHoldMs": coerce_int(
            get_property_value(raw_motion, "silenceHoldMs", 280),
            280,
            minimum=50,
        ),
        "responseAudioThreshold": coerce_float(
            get_property_value(raw_motion, "responseAudioThreshold", 0.02),
            0.02,
            minimum=0.001,
            maximum=1.0,
        ),
        "responseSilenceHoldMs": coerce_int(
            get_property_value(raw_motion, "responseSilenceHoldMs", 1200),
            1200,
            minimum=100,
        ),
        "contextAnimations": context_animations,
    }


@dataclass(slots=True)
class ResolvedConfig:
    api_key: str
    configured_model: str
    resolved_model: str
    using_fallback_model: bool
    voice: str
    language: str
    instructions: str
    logo_path: Path | None
    motion_control: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ResolvedConfig":
        if not path.is_file():
            raise FileNotFoundError(f"No encontre el archivo de configuracion en '{path}'.")

        payload = json.loads(path.read_text(encoding="utf-8"))
        api_key = str(get_property_value(payload, "api_key", "")).strip()
        if not api_key:
            raise ValueError("El archivo de configuracion no tiene 'api_key'.")

        configured_model = str(get_property_value(payload, "modelo", "")).strip()
        resolved_model = configured_model if configured_model and "realtime" in configured_model.lower() else "gpt-realtime"
        voice = str(get_property_value(payload, "voz", "marin")).strip() or "marin"
        language = str(get_property_value(payload, "idioma", "es")).strip() or "es"
        extra_instructions = str(get_property_value(payload, "instrucciones", "")).strip()
        instructions = BASE_INSTRUCTIONS
        if extra_instructions:
            instructions = f"{BASE_INSTRUCTIONS}\n\nIndicaciones adicionales:\n{extra_instructions}"

        raw_logo_path = str(get_property_value(payload, "logo_path", "")).strip()
        logo_path = None
        if raw_logo_path:
            candidate = Path(raw_logo_path).expanduser()
            if candidate.is_file():
                logo_path = candidate

        motion_control = resolve_motion_control(payload)

        return cls(
            api_key=api_key,
            configured_model=configured_model,
            resolved_model=resolved_model,
            using_fallback_model=bool(configured_model and configured_model != resolved_model),
            voice=voice,
            language=language,
            instructions=instructions,
            logo_path=logo_path,
            motion_control=motion_control,
        )

    def session_definition(self) -> dict[str, Any]:
        return {
            "type": "realtime",
            "model": self.resolved_model,
            "instructions": self.instructions,
            "max_output_tokens": 512,
            "audio": {
                "input": {
                    "noise_reduction": {"type": "near_field"},
                    "transcription": {
                        "model": "gpt-4o-mini-transcribe",
                        "language": self.language,
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": True,
                        "interrupt_response": True,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                    },
                },
                "output": {"voice": self.voice},
            },
        }

    def safe_payload(self) -> dict[str, Any]:
        return {
            "configuredModel": self.configured_model,
            "resolvedModel": self.resolved_model,
            "usingFallbackModel": self.using_fallback_model,
            "voice": self.voice,
            "language": self.language,
            "instructions": self.instructions,
            "hasLogo": self.logo_path is not None,
            "motionControl": self.motion_control,
        }


@dataclass(slots=True)
class AppContext:
    config: ResolvedConfig
    public_root: Path
    motion_serial: "MotionSerialController"


def build_motion_command(*parts: str) -> str:
    command_body = ",".join(parts)
    hash_value = sum(ord(char) for char in command_body)
    return f"{command_body},h{hash_value}\n"


class MotionSerialController:
    def __init__(self, script_path: Path, motion_config: dict[str, Any]) -> None:
        self._script_path = script_path
        self._motion_config = motion_config
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _enabled_for_server_serial(self) -> bool:
        return bool(self._motion_config.get("enabled")) and self.transport == "server-serial"

    @property
    def transport(self) -> str:
        return str(self._motion_config.get("transport", "server-serial")).strip() or "server-serial"

    @property
    def serial_port(self) -> str:
        return str(self._motion_config.get("serialPort", "COM6")).strip() or "COM6"

    @property
    def baud_rate(self) -> int:
        return int(self._motion_config.get("baudRate", 115200))

    def status_payload(self) -> dict[str, Any]:
        connected = self._process is not None and self._process.poll() is None
        return {
            "ok": True,
            "transport": self.transport,
            "serialPort": self.serial_port,
            "baudRate": self.baud_rate,
            "connected": connected,
            "portLabel": self.serial_port,
        }

    def connect(self) -> dict[str, Any]:
        with self._lock:
            self._connect_locked()
            return self.status_payload()

    def send_start(self, animation_index: int) -> dict[str, Any]:
        return self._send(build_motion_command("APP_ANIM", "START", str(max(0, animation_index))))

    def send_stop(self) -> dict[str, Any]:
        return self._send(build_motion_command("APP_ANIM", "STOP"))

    def _send(self, command: str) -> dict[str, Any]:
        with self._lock:
            if not self._enabled_for_server_serial():
                return self.status_payload()

            self._connect_locked()

            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise RuntimeError("El puente serial no esta disponible.")

            process.stdin.write(command)
            process.stdin.flush()
            ack = process.stdout.readline().strip()
            if ack != "OK":
                error_details = ""
                if process.stderr is not None:
                    error_details = process.stderr.readline().strip()
                self._disconnect_locked()
                raise RuntimeError(error_details or ack or "No pude enviar el comando serial.")

            return self.status_payload()

    def _connect_locked(self) -> None:
        if not self._enabled_for_server_serial():
            return

        if self._process is not None and self._process.poll() is None:
            return

        self._disconnect_locked()
        process = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self._script_path),
                self.serial_port,
                str(self.baud_rate),
            ],
            cwd=str(self._script_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        ready_line = ""
        if process.stdout is not None:
            ready_line = process.stdout.readline().strip()

        if ready_line != "READY":
            error_details = ""
            if process.stderr is not None:
                error_details = process.stderr.read().strip()
            self._terminate_process(process)
            if not error_details:
                error_details = ready_line or f"No pude abrir {self.serial_port}."
            raise RuntimeError(error_details)

        self._process = process

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._disconnect_locked()
            return self.status_payload()

    def _disconnect_locked(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return

        try:
            if process.stdin is not None:
                process.stdin.write("__EXIT__\n")
                process.stdin.flush()
        except OSError:
            pass

        self._terminate_process(process)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def new_client_secret(config: ResolvedConfig) -> dict[str, Any]:
    body = json.dumps({"session": config.session_definition()}).encode("utf-8")
    request = Request(
        url="https://api.openai.com/v1/realtime/client_secrets",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace").strip()
        if not details:
            details = str(exc)
        raise RuntimeError(f"No se pudo crear el client secret en OpenAI: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"No se pudo crear el client secret en OpenAI: {exc.reason}") from exc


class ChatbotHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], context: AppContext) -> None:
        super().__init__(server_address, ChatbotRequestHandler)
        self.context = context


class ChatbotRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VoiceChatbotPython/1.0"

    @property
    def app_context(self) -> AppContext:
        return self.server.context  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        try:
            request_path = urlsplit(self.path).path
            if request_path == "/health":
                self._write_json(200, {"ok": True, "service": "voice-chatbot"})
                return

            if request_path == "/config":
                self._write_json(200, self.app_context.config.safe_payload())
                return

            if request_path == "/token":
                self._write_json(200, new_client_secret(self.app_context.config))
                return

            if request_path == "/logo":
                self._write_logo()
                return

            self._write_static(request_path)
        except Exception as exc:  # noqa: BLE001
            self._write_json(
                500,
                {
                    "error": "Error interno",
                    "details": str(exc),
                },
            )

    def do_POST(self) -> None:
        try:
            request_path = urlsplit(self.path).path.rstrip("/") or "/"
            segments = [segment for segment in request_path.split("/") if segment]
            if segments[:1] == ["motion"]:
                self._handle_motion_post(segments[1:])
                return

            self._write_text(404, "Ruta no soportada.")
        except Exception as exc:  # noqa: BLE001
            self._write_json(
                500,
                {
                    "error": "Error interno",
                    "details": str(exc),
                },
            )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_logo(self) -> None:
        logo_path = self.app_context.config.logo_path
        if logo_path is None or not logo_path.is_file():
            self._write_text(404, "No hay logo configurado.")
            return

        self._write_bytes(200, guess_content_type(logo_path), logo_path.read_bytes())

    def _handle_motion_post(self, segments: list[str]) -> None:
        controller = self.app_context.motion_serial
        if not segments:
            self._write_text(404, "Ruta no soportada.")
            return

        action = segments[0]
        if action == "connect":
            self._write_json(200, controller.connect())
            return

        if action == "disconnect":
            self._write_json(200, controller.disconnect())
            return

        if action == "stop":
            self._write_json(200, controller.send_stop())
            return

        if action == "start":
            if len(segments) < 2:
                raise ValueError("Falta el indice de animacion.")
            animation_index = coerce_int(segments[1], 0, minimum=0)
            self._write_json(200, controller.send_start(animation_index))
            return

        self._write_text(404, "Ruta no soportada.")

    def _write_static(self, request_path: str) -> None:
        relative_path = unquote(request_path).lstrip("/") or "index.html"
        relative_path = relative_path.replace("\\", "/")
        segments = [segment for segment in relative_path.split("/") if segment and segment != "."]
        if any(segment == ".." for segment in segments):
            raise PermissionError("Ruta invalida.")

        file_path = self.app_context.public_root.joinpath(*segments).resolve()
        try:
            file_path.relative_to(self.app_context.public_root)
        except ValueError as exc:
            raise PermissionError("Ruta invalida.") from exc

        if not file_path.is_file():
            self._write_text(404, "No encontrado.")
            return

        self._write_bytes(200, guess_content_type(file_path), file_path.read_bytes())

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._write_bytes(status_code, "application/json; charset=utf-8", body)

    def _write_text(self, status_code: int, body: str) -> None:
        self._write_bytes(status_code, "text/plain; charset=utf-8", body.encode("utf-8"))

    def _write_bytes(self, status_code: int, content_type: str, payload: bytes) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()
        self.close_connection = True


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    return content_type or "application/octet-stream"


class LocalServerController:
    def __init__(self, host: str, port: int, context: AppContext) -> None:
        self._host = host
        self._port = port
        self._context = context
        self._server: ChatbotHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("El servidor todavia no esta listo.")
        host = self._server.server_address[0]
        port = self._server.server_address[1]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._server = ChatbotHTTPServer((self._host, self._port), self._context)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return

        self._context.motion_serial.disconnect()
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None


def find_app_browser() -> Path | None:
    program_files = os.environ.get("PROGRAMFILES", "")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    candidates = [
        Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def open_app_window(url: str) -> bool:
    browser_path = find_app_browser()
    if browser_path is None:
        return False

    try:
        subprocess.Popen(
            [str(browser_path), f"--app={url}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def open_browser(url: str) -> bool:
    try:
        return webbrowser.open_new(url)
    except webbrowser.Error:
        return False


def run_webview(url: str) -> bool:
    try:
        import webview
    except ImportError:
        return False

    try:
        webview.create_window(
            "Chatbot voz a voz",
            url,
            width=1220,
            height=920,
            min_size=(960, 700),
        )
        webview.start()
    except Exception:
        return False

    return True


def run_tkinter_launcher(url: str, safe_config: dict[str, Any]) -> bool:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        return False

    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.title("Chatbot voz a voz")
    root.geometry("560x430")
    root.minsize(520, 390)
    root.configure(bg="#f5efe7")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("Card.TFrame", background="#fffaf3")
    style.configure("Title.TLabel", background="#fffaf3", foreground="#1f2933", font=("Segoe UI", 18, "bold"))
    style.configure("Body.TLabel", background="#fffaf3", foreground="#405261", font=("Segoe UI", 10))
    style.configure("Key.TLabel", background="#fffaf3", foreground="#6a7781", font=("Segoe UI", 9, "bold"))
    style.configure("Value.TLabel", background="#fffaf3", foreground="#1f2933", font=("Segoe UI", 10))

    container = ttk.Frame(root, style="Card.TFrame", padding=20)
    container.pack(fill="both", expand=True, padx=18, pady=18)

    ttk.Label(container, text="Chatbot voz a voz", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        container,
        text=(
            "La interfaz de voz usa un motor web para conservar "
            "microfono, audio y WebRTC en tiempo real."
        ),
        style="Body.TLabel",
        wraplength=490,
        justify="left",
    ).pack(anchor="w", pady=(8, 16))

    info_frame = ttk.Frame(container, style="Card.TFrame")
    info_frame.pack(fill="x")

    info_rows = [
        ("URL local", url),
        ("Modelo", safe_config["resolvedModel"]),
        ("Voz", safe_config["voice"]),
        ("Idioma", safe_config["language"]),
    ]

    if safe_config["usingFallbackModel"]:
        info_rows.append(("Modelo original", safe_config["configuredModel"]))

    for row_index, (label, value) in enumerate(info_rows):
        ttk.Label(info_frame, text=label, style="Key.TLabel").grid(row=row_index, column=0, sticky="w", pady=4)
        ttk.Label(
            info_frame,
            text=value,
            style="Value.TLabel",
            wraplength=330,
            justify="left",
        ).grid(row=row_index, column=1, sticky="w", padx=(18, 0), pady=4)

    status_var = tk.StringVar(value="Servidor listo")

    def copy_url() -> None:
        root.clipboard_clear()
        root.clipboard_append(url)
        status_var.set("URL copiada")

    def open_best_window() -> None:
        if open_app_window(url):
            status_var.set("Ventana abierta en Edge o Chrome")
            return
        if open_browser(url):
            status_var.set("Interfaz abierta en el navegador")
            return
        messagebox.showerror("No pude abrir la interfaz", f"Abre manualmente: {url}")
        status_var.set("No pude abrir la interfaz")

    def open_in_browser() -> None:
        if open_browser(url):
            status_var.set("Interfaz abierta en el navegador")
            return
        messagebox.showerror("No pude abrir el navegador", f"Abre manualmente: {url}")
        status_var.set("No pude abrir el navegador")

    def close_window() -> None:
        root.destroy()

    button_bar = ttk.Frame(container, style="Card.TFrame")
    button_bar.pack(fill="x", pady=(22, 12))

    ttk.Button(button_bar, text="Abrir ventana", command=open_best_window).pack(side="left")
    ttk.Button(button_bar, text="Abrir navegador", command=open_in_browser).pack(side="left", padx=10)
    ttk.Button(button_bar, text="Copiar URL", command=copy_url).pack(side="left")
    ttk.Button(button_bar, text="Salir", command=close_window).pack(side="right")

    ttk.Label(container, textvariable=status_var, style="Body.TLabel").pack(anchor="w")
    ttk.Label(
        container,
        text="Si instalas pywebview, la app puede abrirse dentro de una sola ventana Python.",
        style="Body.TLabel",
        wraplength=490,
        justify="left",
    ).pack(anchor="w", pady=(10, 0))

    root.after(350, open_best_window)
    root.mainloop()
    return True


def wait_forever() -> None:
    while True:
        time.sleep(0.5)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chatbot voz a voz con GUI en Python.")
    parser.add_argument("--host", default="127.0.0.1", help="Host local del servidor. Por defecto: 127.0.0.1")
    parser.add_argument("--port", type=int, default=3000, help="Puerto local. Por defecto: 3000")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config_recetas_openai.json")),
        help="Ruta al JSON de configuracion",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="No intenta abrir ninguna GUI; deja solo el servidor local.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Abre el navegador aun si no usas GUI.",
    )
    return parser.parse_args(argv)


def build_context(config_path: Path) -> AppContext:
    public_root = Path(__file__).with_name("public").resolve()
    if not public_root.is_dir():
        raise FileNotFoundError(f"No encontre la carpeta publica en '{public_root}'.")

    bridge_script = Path(__file__).with_name("motion_serial_bridge.ps1").resolve()
    if not bridge_script.is_file():
        raise FileNotFoundError(f"No encontre el puente serial en '{bridge_script}'.")

    config = ResolvedConfig.load(config_path.resolve())

    return AppContext(
        config=config,
        public_root=public_root,
        motion_serial=MotionSerialController(bridge_script, config.motion_control),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        context = build_context(Path(args.config))
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    if context.config.using_fallback_model:
        print(
            "El modelo configurado "
            f"'{context.config.configured_model}' no es realtime. "
            f"Se usara '{context.config.resolved_model}'."
        )

    server = LocalServerController(args.host, args.port, context)

    try:
        server.start()
    except OSError as exc:
        print(
            f"No pude abrir http://{args.host}:{args.port}/. "
            f"Proba con otro puerto. Error: {exc}",
            file=sys.stderr,
        )
        return 1

    print("")
    print(f"Servidor listo en {server.url}")
    print("Presiona Ctrl+C para detenerlo si lo ejecutas en consola.")
    print("")

    try:
        if args.no_gui:
            if args.open_browser:
                open_app_window(server.url) or open_browser(server.url)
            wait_forever()
            return 0

        if run_webview(server.url):
            return 0

        if run_tkinter_launcher(server.url, context.config.safe_payload()):
            return 0

        if open_app_window(server.url) or open_browser(server.url):
            print(f"Interfaz abierta en {server.url}")

        wait_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
