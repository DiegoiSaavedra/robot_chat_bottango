param(
    [int]$Port = 3000,
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config_recetas_openai.json"),
    [switch]$OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$publicRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "public"))
$listener = $null

function Get-PropertyValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [object]$Default = $null
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Resolve-BoolValue {
    param(
        [object]$Value,
        [bool]$Default
    )

    if ($Value -is [bool]) { return $Value }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double]) {
        return [bool]($Value -ne 0)
    }

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $Default }

    switch ($text.Trim().ToLowerInvariant()) {
        "1" { return $true }
        "true" { return $true }
        "yes" { return $true }
        "si" { return $true }
        "sí" { return $true }
        "on" { return $true }
        "0" { return $false }
        "false" { return $false }
        "no" { return $false }
        "off" { return $false }
        default { return $Default }
    }
}

function Resolve-IntValue {
    param(
        [object]$Value,
        [int]$Default,
        [int]$Minimum = [int]::MinValue,
        [int]$Maximum = [int]::MaxValue
    )

    $parsed = 0
    if (-not [int]::TryParse([string]$Value, [ref]$parsed)) {
        $parsed = $Default
    }

    if ($parsed -lt $Minimum) { $parsed = $Minimum }
    if ($parsed -gt $Maximum) { $parsed = $Maximum }
    return $parsed
}

function Resolve-DoubleValue {
    param(
        [object]$Value,
        [double]$Default,
        [double]$Minimum = [double]::NegativeInfinity,
        [double]$Maximum = [double]::PositiveInfinity
    )

    $parsed = 0.0
    if (-not [double]::TryParse([string]$Value, [ref]$parsed)) {
        $parsed = $Default
    }

    if ($parsed -lt $Minimum) { $parsed = $Minimum }
    if ($parsed -gt $Maximum) { $parsed = $Maximum }
    return $parsed
}

function Get-AppConfig {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "No encontre el archivo de configuracion en '$Path'."
    }

    $config = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    $apiKey = [string](Get-PropertyValue -Object $config -Name "api_key" -Default "")
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "El archivo de configuracion no tiene 'api_key'."
    }

    return $config
}

function Resolve-RealtimeModel {
    param([Parameter(Mandatory = $true)][object]$Config)

    $configuredModel = [string](Get-PropertyValue -Object $Config -Name "modelo" -Default "")
    if ([string]::IsNullOrWhiteSpace($configuredModel) -or $configuredModel -notmatch "realtime") {
        return "gpt-realtime"
    }

    return $configuredModel.Trim()
}

function Resolve-Voice {
    param([Parameter(Mandatory = $true)][object]$Config)

    $voice = [string](Get-PropertyValue -Object $Config -Name "voz" -Default "")
    if ([string]::IsNullOrWhiteSpace($voice)) { return "marin" }
    return $voice.Trim()
}

function Resolve-Language {
    param([Parameter(Mandatory = $true)][object]$Config)

    $language = [string](Get-PropertyValue -Object $Config -Name "idioma" -Default "")
    if ([string]::IsNullOrWhiteSpace($language)) { return "es" }
    return $language.Trim()
}

function Resolve-Instructions {
    param([Parameter(Mandatory = $true)][object]$Config)

    $baseInstructions = "Habla siempre en espanol claro y natural. Se breve, amable y util. Si no entiendes algo, pedi que lo repitan."
    $extraInstructions = [string](Get-PropertyValue -Object $Config -Name "instrucciones" -Default "")
    if ([string]::IsNullOrWhiteSpace($extraInstructions)) { return $baseInstructions }
    return "$baseInstructions`n`nIndicaciones adicionales:`n$extraInstructions"
}

function Get-LogoPath {
    param([Parameter(Mandatory = $true)][object]$Config)

    $logoPath = [string](Get-PropertyValue -Object $Config -Name "logo_path" -Default "")
    if ([string]::IsNullOrWhiteSpace($logoPath) -or -not (Test-Path -LiteralPath $logoPath)) {
        return $null
    }

    return $logoPath
}

function Resolve-MotionControl {
    param([Parameter(Mandatory = $true)][object]$Config)

    $motion = Get-PropertyValue -Object $Config -Name "motion_control" -Default $null
    if ($null -eq $motion) {
        $motion = [pscustomobject]@{}
    }

    $contextAnimations = @()

    if ($null -ne $motion) {
        $rawRules = Get-PropertyValue -Object $motion -Name "contextAnimations" -Default (
            Get-PropertyValue -Object $motion -Name "context_animations" -Default @()
        )

        foreach ($rawRule in @($rawRules)) {
            if ($null -eq $rawRule) { continue }

            $animationIndex = Resolve-IntValue `
                -Value (Get-PropertyValue -Object $rawRule -Name "animationIndex" -Default (
                    Get-PropertyValue -Object $rawRule -Name "animation_index" -Default -1
                )) `
                -Default -1 `
                -Minimum -1

            $keywords = @(
                @(Get-PropertyValue -Object $rawRule -Name "keywords" -Default @()) |
                    ForEach-Object { [string]$_ } |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                    ForEach-Object { $_.Trim().ToLowerInvariant() }
            )

            if ($animationIndex -lt 0 -or $keywords.Count -eq 0) {
                continue
            }

            $name = [string](Get-PropertyValue -Object $rawRule -Name "name" -Default "rule-$($contextAnimations.Count + 1)")
            if ([string]::IsNullOrWhiteSpace($name)) {
                $name = "rule-$($contextAnimations.Count + 1)"
            }

            $contextAnimations += @{
                name = $name.Trim()
                animationIndex = $animationIndex
                keywords = $keywords
            }
        }
    }

    $transport = ([string](Get-PropertyValue -Object $motion -Name "transport" -Default "server-serial")).Trim()
    if ([string]::IsNullOrWhiteSpace($transport)) {
        $transport = "server-serial"
    }

    $serialPort = ([string](Get-PropertyValue -Object $motion -Name "serialPort" -Default (
        Get-PropertyValue -Object $motion -Name "serial_port" -Default "COM6"
    ))).Trim()
    if ([string]::IsNullOrWhiteSpace($serialPort)) {
        $serialPort = "COM6"
    }

    return @{
        enabled = Resolve-BoolValue -Value (Get-PropertyValue -Object $motion -Name "enabled" -Default $true) -Default $true
        transport = $transport
        activationMode = ([string](Get-PropertyValue -Object $motion -Name "activationMode" -Default (
            Get-PropertyValue -Object $motion -Name "activation_mode" -Default "response"
        ))).Trim()
        serialPort = $serialPort
        baudRate = Resolve-IntValue -Value (Get-PropertyValue -Object $motion -Name "baudRate" -Default 115200) -Default 115200 -Minimum 1200
        speakAnimationIndex = Resolve-IntValue -Value (Get-PropertyValue -Object $motion -Name "speakAnimationIndex" -Default 0) -Default 0 -Minimum 0
        autoConnectAuthorizedPort = Resolve-BoolValue -Value (Get-PropertyValue -Object $motion -Name "autoConnectAuthorizedPort" -Default $true) -Default $true
        audioThreshold = Resolve-DoubleValue -Value (Get-PropertyValue -Object $motion -Name "audioThreshold" -Default 0.045) -Default 0.045 -Minimum 0.001 -Maximum 1.0
        silenceHoldMs = Resolve-IntValue -Value (Get-PropertyValue -Object $motion -Name "silenceHoldMs" -Default 280) -Default 280 -Minimum 50
        responseAudioThreshold = Resolve-DoubleValue -Value (Get-PropertyValue -Object $motion -Name "responseAudioThreshold" -Default 0.02) -Default 0.02 -Minimum 0.001 -Maximum 1.0
        responseSilenceHoldMs = Resolve-IntValue -Value (Get-PropertyValue -Object $motion -Name "responseSilenceHoldMs" -Default 1200) -Default 1200 -Minimum 100
        contextAnimations = $contextAnimations
    }
}

$script:motionSerialPort = $null

function New-MotionCommand {
    param([Parameter(Mandatory = $true)][string[]]$Parts)

    $commandBody = ($Parts -join ",")
    $hash = 0
    foreach ($char in $commandBody.ToCharArray()) {
        $hash += [int][char]$char
    }

    return "$commandBody,h$hash`n"
}

function Get-MotionState {
    param([Parameter(Mandatory = $true)][object]$Config)

    $motionControl = Resolve-MotionControl -Config $Config
    return @{
        ok = $true
        transport = $motionControl.transport
        serialPort = $motionControl.serialPort
        baudRate = $motionControl.baudRate
        connected = [bool]($null -ne $script:motionSerialPort -and $script:motionSerialPort.IsOpen)
        portLabel = $motionControl.serialPort
    }
}

function Open-MotionSerialPort {
    param([Parameter(Mandatory = $true)][object]$Config)

    $motionControl = Resolve-MotionControl -Config $Config
    if (-not $motionControl.enabled -or $motionControl.transport -ne "server-serial") {
        return Get-MotionState -Config $Config
    }

    if ($null -ne $script:motionSerialPort -and $script:motionSerialPort.IsOpen) {
        return Get-MotionState -Config $Config
    }

    Close-MotionSerialPort

    $port = $null
    try {
        $port = [System.IO.Ports.SerialPort]::new(
            $motionControl.serialPort,
            $motionControl.baudRate,
            [System.IO.Ports.Parity]::None,
            8,
            [System.IO.Ports.StopBits]::One
        )
        $port.DtrEnable = $false
        $port.RtsEnable = $false
        $port.NewLine = "`n"
        $port.WriteTimeout = 500
        $port.ReadTimeout = 500
        $port.Open()
        Start-Sleep -Milliseconds 1500
        $script:motionSerialPort = $port
    }
    catch {
        if ($null -ne $port) {
            $port.Dispose()
        }
        throw
    }

    return Get-MotionState -Config $Config
}

function Close-MotionSerialPort {
    if ($null -eq $script:motionSerialPort) {
        return
    }

    try {
        if ($script:motionSerialPort.IsOpen) {
            $script:motionSerialPort.Close()
        }
    }
    catch {
    }
    finally {
        $script:motionSerialPort.Dispose()
        $script:motionSerialPort = $null
    }
}

function Send-MotionSerialCommand {
    param(
        [Parameter(Mandatory = $true)][object]$Config,
        [Parameter(Mandatory = $true)][string]$CommandText
    )

    $motionControl = Resolve-MotionControl -Config $Config
    if (-not $motionControl.enabled -or $motionControl.transport -ne "server-serial") {
        return Get-MotionState -Config $Config
    }

    Open-MotionSerialPort -Config $Config | Out-Null

    if ($null -eq $script:motionSerialPort -or -not $script:motionSerialPort.IsOpen) {
        throw "No pude abrir el puerto serial $($motionControl.serialPort)."
    }

    try {
        $script:motionSerialPort.Write($CommandText)
        $script:motionSerialPort.BaseStream.Flush()
    }
    catch {
        Close-MotionSerialPort
        throw
    }

    return Get-MotionState -Config $Config
}

function New-SessionDefinition {
    param([Parameter(Mandatory = $true)][object]$Config)

    return @{
        type = "realtime"
        model = (Resolve-RealtimeModel -Config $Config)
        instructions = (Resolve-Instructions -Config $Config)
        max_output_tokens = 512
        audio = @{
            input = @{
                noise_reduction = @{ type = "near_field" }
                transcription = @{
                    model = "gpt-4o-mini-transcribe"
                    language = (Resolve-Language -Config $Config)
                }
                turn_detection = @{
                    type = "server_vad"
                    create_response = $true
                    interrupt_response = $true
                    prefix_padding_ms = 300
                    silence_duration_ms = 500
                }
            }
            output = @{ voice = (Resolve-Voice -Config $Config) }
        }
    }
}

function Get-SafeConfig {
    param([Parameter(Mandatory = $true)][object]$Config)

    $configuredModel = [string](Get-PropertyValue -Object $Config -Name "modelo" -Default "")
    $resolvedModel = Resolve-RealtimeModel -Config $Config

    return @{
        configuredModel = $configuredModel
        resolvedModel = $resolvedModel
        usingFallbackModel = (-not [string]::IsNullOrWhiteSpace($configuredModel) -and $configuredModel -ne $resolvedModel)
        voice = (Resolve-Voice -Config $Config)
        language = (Resolve-Language -Config $Config)
        instructions = (Resolve-Instructions -Config $Config)
        hasLogo = [bool](Get-LogoPath -Config $Config)
        motionControl = (Resolve-MotionControl -Config $Config)
    }
}

function Get-ErrorBody {
    param([Parameter(Mandatory = $true)][System.Management.Automation.ErrorRecord]$ErrorRecord)

    $response = $ErrorRecord.Exception.Response
    if ($null -eq $response) { return $null }

    try {
        if ($response -is [System.Net.Http.HttpResponseMessage]) {
            return $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }

        $stream = $response.GetResponseStream()
        if ($null -eq $stream) { return $null }

        $reader = [System.IO.StreamReader]::new($stream)
        try { return $reader.ReadToEnd() }
        finally {
            $reader.Dispose()
            $stream.Dispose()
        }
    }
    catch {
        return $null
    }
}

function New-ClientSecret {
    param([Parameter(Mandatory = $true)][object]$Config)

    $apiKey = [string](Get-PropertyValue -Object $Config -Name "api_key" -Default "")
    $body = @{ session = (New-SessionDefinition -Config $Config) } | ConvertTo-Json -Depth 10

    try {
        return Invoke-RestMethod `
            -Method Post `
            -Uri "https://api.openai.com/v1/realtime/client_secrets" `
            -Headers @{ Authorization = "Bearer $apiKey" } `
            -ContentType "application/json" `
            -Body $body
    }
    catch {
        $details = Get-ErrorBody -ErrorRecord $_
        if ([string]::IsNullOrWhiteSpace($details)) {
            throw "No se pudo crear el client secret en OpenAI: $($_.Exception.Message)"
        }

        throw "No se pudo crear el client secret en OpenAI: $details"
    }
}
function Get-ContentType {
    param([Parameter(Mandatory = $true)][string]$Path)

    switch ([System.IO.Path]::GetExtension($Path).ToLowerInvariant()) {
        ".html" { return "text/html; charset=utf-8" }
        ".css" { return "text/css; charset=utf-8" }
        ".js" { return "application/javascript; charset=utf-8" }
        ".json" { return "application/json; charset=utf-8" }
        ".png" { return "image/png" }
        ".jpg" { return "image/jpeg" }
        ".jpeg" { return "image/jpeg" }
        ".svg" { return "image/svg+xml" }
        default { return "application/octet-stream" }
    }
}

function Get-StatusText {
    param([Parameter(Mandatory = $true)][int]$StatusCode)

    switch ($StatusCode) {
        200 { return "OK" }
        404 { return "Not Found" }
        500 { return "Internal Server Error" }
        default { return "OK" }
    }
}
function Read-HttpRequest {
    param([Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client)

    $stream = $Client.GetStream()
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::ASCII, $false, 1024, $true)

    $requestLine = $reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($requestLine)) { return $null }

    $parts = $requestLine.Split(' ')
    if ($parts.Length -lt 2) {
        throw "Solicitud HTTP invalida."
    }

    $method = $parts[0].ToUpperInvariant()
    $rawPath = $parts[1]
    $path = $rawPath.Split('?')[0]
    $headers = @{}

    while ($true) {
        $line = $reader.ReadLine()
        if ($null -eq $line -or $line -eq "") { break }

        $separatorIndex = $line.IndexOf(':')
        if ($separatorIndex -gt 0) {
            $headerName = $line.Substring(0, $separatorIndex).Trim().ToLowerInvariant()
            $headerValue = $line.Substring($separatorIndex + 1).Trim()
            $headers[$headerName] = $headerValue
        }
    }

    return @{
        Method = $method
        Path = [System.Uri]::UnescapeDataString($path)
        Headers = $headers
    }
}
function Write-BytesResponse {
    param(
        [Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client,
        [Parameter(Mandatory = $true)][int]$StatusCode,
        [Parameter(Mandatory = $true)][string]$ContentType,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )

    $stream = $Client.GetStream()
    $writer = [System.IO.StreamWriter]::new($stream, [System.Text.Encoding]::ASCII, 1024, $true)
    $writer.NewLine = "`r`n"
    $writer.WriteLine("HTTP/1.1 $StatusCode $(Get-StatusText -StatusCode $StatusCode)")
    $writer.WriteLine("Content-Type: $ContentType")
    $writer.WriteLine("Content-Length: $($Bytes.Length)")
    $writer.WriteLine("Connection: close")
    $writer.WriteLine("Cache-Control: no-store")
    $writer.WriteLine("")
    $writer.Flush()
    $stream.Write($Bytes, 0, $Bytes.Length)
    $stream.Flush()
}
function Write-JsonResponse {
    param(
        [Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client,
        [Parameter(Mandatory = $true)][int]$StatusCode,
        [Parameter(Mandatory = $true)][object]$Payload
    )

    $json = $Payload | ConvertTo-Json -Depth 10
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    Write-BytesResponse -Client $Client -StatusCode $StatusCode -ContentType "application/json; charset=utf-8" -Bytes $bytes
}

function Write-TextResponse {
    param(
        [Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client,
        [Parameter(Mandatory = $true)][int]$StatusCode,
        [Parameter(Mandatory = $true)][string]$Body
    )

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Body)
    Write-BytesResponse -Client $Client -StatusCode $StatusCode -ContentType "text/plain; charset=utf-8" -Bytes $bytes
}
function Resolve-StaticPath {
    param([Parameter(Mandatory = $true)][string]$RequestPath)

    $trimmedPath = $RequestPath.TrimStart("/")
    if ([string]::IsNullOrWhiteSpace($trimmedPath)) {
        $trimmedPath = "index.html"
    }

    if ($trimmedPath -match "\.\.") {
        throw "Ruta invalida."
    }

    $fullPath = $publicRoot
    foreach ($segment in ($trimmedPath -split "/" | Where-Object { $_ -ne "" })) {
        $fullPath = Join-Path $fullPath $segment
    }

    $resolvedFile = [System.IO.Path]::GetFullPath($fullPath)
    if (-not $resolvedFile.StartsWith($publicRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta invalida."
    }

    return $resolvedFile
}

function Write-StaticResponse {
    param(
        [Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client,
        [Parameter(Mandatory = $true)][string]$RequestPath
    )

    $filePath = Resolve-StaticPath -RequestPath $RequestPath
    if (-not (Test-Path -LiteralPath $filePath)) {
        Write-TextResponse -Client $Client -StatusCode 404 -Body "No encontrado."
        return
    }

    $bytes = [System.IO.File]::ReadAllBytes($filePath)
    Write-BytesResponse -Client $Client -StatusCode 200 -ContentType (Get-ContentType -Path $filePath) -Bytes $bytes
}

function Write-LogoResponse {
    param(
        [Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client,
        [Parameter(Mandatory = $true)][object]$Config
    )

    $logoPath = Get-LogoPath -Config $Config
    if ($null -eq $logoPath) {
        Write-TextResponse -Client $Client -StatusCode 404 -Body "No hay logo configurado."
        return
    }

    $bytes = [System.IO.File]::ReadAllBytes($logoPath)
    Write-BytesResponse -Client $Client -StatusCode 200 -ContentType (Get-ContentType -Path $logoPath) -Bytes $bytes
}
function Handle-Request {
    param(
        [Parameter(Mandatory = $true)][System.Net.Sockets.TcpClient]$Client,
        [Parameter(Mandatory = $true)][hashtable]$Request,
        [Parameter(Mandatory = $true)][object]$Config
    )

    switch ("$($Request.Method) $($Request.Path)") {
        "GET /health" {
            Write-JsonResponse -Client $Client -StatusCode 200 -Payload @{ ok = $true; service = "voice-chatbot" }
            return
        }
        "GET /config" {
            Write-JsonResponse -Client $Client -StatusCode 200 -Payload (Get-SafeConfig -Config $Config)
            return
        }
        "GET /token" {
            $clientSecret = New-ClientSecret -Config $Config
            Write-JsonResponse -Client $Client -StatusCode 200 -Payload $clientSecret
            return
        }
        "GET /logo" {
            Write-LogoResponse -Client $Client -Config $Config
            return
        }
    }

    if ($Request.Method -eq "POST") {
        switch -Regex ($Request.Path) {
            "^/motion/connect/?$" {
                Write-JsonResponse -Client $Client -StatusCode 200 -Payload (Open-MotionSerialPort -Config $Config)
                return
            }
            "^/motion/disconnect/?$" {
                Close-MotionSerialPort
                Write-JsonResponse -Client $Client -StatusCode 200 -Payload (Get-MotionState -Config $Config)
                return
            }
            "^/motion/stop/?$" {
                Write-JsonResponse -Client $Client -StatusCode 200 -Payload (
                    Send-MotionSerialCommand -Config $Config -CommandText (New-MotionCommand -Parts @("APP_ANIM", "STOP"))
                )
                return
            }
            "^/motion/start/(\d+)/?$" {
                $animationIndex = [int]$Matches[1]
                Write-JsonResponse -Client $Client -StatusCode 200 -Payload (
                    Send-MotionSerialCommand -Config $Config -CommandText (New-MotionCommand -Parts @("APP_ANIM", "START", [string]$animationIndex))
                )
                return
            }
        }
    }

    if ($Request.Method -eq "GET") {
        Write-StaticResponse -Client $Client -RequestPath $Request.Path
        return
    }

    Write-TextResponse -Client $Client -StatusCode 404 -Body "Ruta no soportada."
}

if (-not (Test-Path -LiteralPath $publicRoot)) {
    throw "No encontre la carpeta publica en '$publicRoot'."
}

$config = Get-AppConfig -Path $ConfigPath
$safeConfig = Get-SafeConfig -Config $config

if ($safeConfig.usingFallbackModel) {
    Write-Host "El modelo configurado '$($safeConfig.configuredModel)' no es realtime. Se usara '$($safeConfig.resolvedModel)'."
}
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)

try {
    $listener.Start()
}
catch {
    throw "No pude abrir http://localhost:$Port/. Proba con otro puerto. Error: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Servidor listo en http://localhost:$Port"
Write-Host "Presiona Ctrl+C para detenerlo."
Write-Host ""

if ($OpenBrowser) {
    Start-Process "http://localhost:$Port" | Out-Null
}

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()

        try {
            $request = Read-HttpRequest -Client $client
            if ($null -ne $request) {
                Handle-Request -Client $client -Request $request -Config $config
            }
        }
        catch {
            Write-Host "Error atendiendo una solicitud: $($_.Exception.Message)"
            try {
                Write-JsonResponse -Client $client -StatusCode 500 -Payload @{
                    error = "Error interno"
                    details = $_.Exception.Message
                }
            }
            catch {
            }
        }
        finally {
            if ($null -ne $client) {
                $client.Close()
            }
        }
    }
}
finally {
    Close-MotionSerialPort
    if ($null -ne $listener) {
        $listener.Stop()
    }
}
