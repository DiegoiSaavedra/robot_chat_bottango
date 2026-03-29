# Chatbot voz a voz con OpenAI

Este proyecto ahora tiene dos formas de uso:

- `start-chatbot.ps1`: servidor local original en PowerShell + interfaz web.
- `start_chatbot.py`: version Python con backend local equivalente y GUI de escritorio.

La GUI en Python reutiliza el frontend WebRTC que ya funcionaba para mantener microfono, audio y tiempo real sin reescribir toda la capa de voz.

## Arduino + Bottango sincronizado con la voz

La interfaz ahora puede disparar una animacion exportada de Bottango mientras el modelo esta hablando y detenerla cuando el audio remoto queda en silencio.

Flujo:

- La web detecta nivel real del audio de salida del asistente.
- El backend mantiene abierto el puerto `COM6`.
- La activacion recomendada para un humanoide sin boca es `response`: arranca al empezar la respuesta y frena cuando termina completa.
- Cuando detecta voz, manda `APP_ANIM,START,<indice>`.
- Cuando termina de hablar, manda `APP_ANIM,STOP`.
- Si algun dia quieres volver al navegador, todavia existe el modo `web-serial`.

Para usarlo:

1. Carga en el Arduino el sketch de `BottangoArduinoDriver` con la animacion exportada.
2. Abre la interfaz del chatbot.
3. Pulsa `Conectar Arduino` para que el servidor abra `COM6`.
4. Pulsa `Conectar` para iniciar la sesion de voz.

El driver incluido ya trae una animacion exportada llamada `habla1`, que corresponde al indice `0`.

Si luego quieres volver al modo de control en vivo de Bottango por USB, comenta otra vez `USE_CODE_COMMAND_STREAM` en `BottangoArduinoDriver/BottangoArduinoModules.h`.

## Version Python con GUI

Requisitos:

- Python 3.10 o superior.
- `tkinter`, que normalmente ya viene con Python en Windows.
- Opcional: `pywebview` si quieres que todo se abra dentro de una sola ventana Python.

Para levantar la version Python:

```powershell
python .\start_chatbot.py
```

Tambien puedes abrir directamente `chatbot_gui.pyw` si prefieres lanzarla como app de escritorio.

Comportamiento de la GUI:

- Si `pywebview` esta instalado, abre una ventana embebida.
- Si no, abre un panel en `tkinter` y desde ahi lanza una ventana tipo app en Edge o Chrome cuando estan disponibles.
- Si tampoco encuentra un navegador compatible en modo app, abre la interfaz en el navegador por defecto.

Opciones utiles:

```powershell
python .\start_chatbot.py --port 3100
python .\start_chatbot.py --config .\config_recetas_openai.json
python .\start_chatbot.py --no-gui --open-browser
```

## Version PowerShell original

Si quieres seguir usando la version anterior:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-chatbot.ps1
```

Despues entra en `http://localhost:3000`.

## Lo que usa

- `start_chatbot.py`: backend Python + GUI desktop
- `chatbot_gui.pyw`: lanzador GUI para Windows
- `start-chatbot.ps1`: servidor local original en PowerShell
- `public/index.html`: interfaz del chatbot
- `public/app.js`: conexion WebRTC con la Realtime API
- `public/styles.css`: estilos de la interfaz

## Configuracion del JSON

Tu archivo actual ya sirve. Ademas, si quieres, puedes sumar estas claves opcionales:

```json
{
  "api_key": "sk-proj-...",
  "modelo": "gpt-realtime",
  "voz": "marin",
  "idioma": "es",
  "instrucciones": "Habla como un asistente de recetas corto y simpatico.",
  "motion_control": {
    "enabled": true,
    "transport": "server-serial",
    "activationMode": "response",
    "serialPort": "COM6",
    "baudRate": 115200,
    "speakAnimationIndex": 0,
    "autoConnectAuthorizedPort": true,
    "audioThreshold": 0.045,
    "silenceHoldMs": 280,
    "responseAudioThreshold": 0.02,
    "responseSilenceHoldMs": 1200,
    "contextAnimations": [
      {
        "name": "saludo",
        "keywords": ["hola", "bienvenido"],
        "animationIndex": 1
      }
    ]
  }
}
```

Notas:

- Si `modelo` no contiene `realtime`, la app usa `gpt-realtime` automaticamente.
- La API key nunca se expone al frontend; la interfaz recibe un token efimero.
- El logo se muestra si `logo_path` apunta a un archivo existente.
- La parte de voz sigue corriendo sobre tecnologia web porque ahi vive WebRTC y el acceso al microfono.
- Para tu robot actual, `motion_control.serialPort` debe quedar en `COM6`.
- `motion_control.activationMode = "response"` mantiene la animacion durante toda la respuesta; usa `"audio"` solo si quieres labios o movimientos pegados a cada fonema.
- `motion_control.responseAudioThreshold` y `motion_control.responseSilenceHoldMs` afinan el corte final cuando usas `activationMode = "response"`.
- `motion_control.contextAnimations` queda listo para que despues asignes animaciones segun palabras clave del texto que va generando el asistente.

## Si algo falla

- Si la interfaz no responde, revisa que hayas permitido el microfono.
- Si el servidor no arranca en `localhost`, prueba otro puerto.
- Si `/token` falla, revisa que la `api_key` sea valida y tenga acceso a la Realtime API.
- Si quieres una sola ventana real en Python, instala `pywebview`; si no, el fallback abre Edge, Chrome o el navegador por defecto.

## Referencias

- [Realtime API con WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc)
- [Eventos y capacidades realtime](https://platform.openai.com/docs/guides/realtime-model-capabilities)
