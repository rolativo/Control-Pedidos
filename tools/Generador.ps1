# ============================================
# GENERADOR LNP
# Detecta LISTA / F5 / F11 / F511
# Lee el contenido del portapapeles
# Guarda archivos en la carpeta donde esta el BAT
# ============================================

$ErrorActionPreference = "Stop"


# ============================================
# GENERAR NOMBRE SIN SOBRESCRIBIR
# ============================================

function Get-UniquePath {
    param(
        [string]$BaseName,
        [string]$Extension
    )

    $dir = $PSScriptRoot
    $candidate = Join-Path $dir ($BaseName + $Extension)

    if (-not (Test-Path $candidate)) {
        return $candidate
    }

    $i = 1

    while ($true) {

        $suffix = "{0:D2}" -f $i

        $candidate = Join-Path $dir (
            $BaseName + $suffix + $Extension
        )

        if (-not (Test-Path $candidate)) {
            return $candidate
        }

        $i++
    }
}


# ============================================
# GUARDAR UTF8 SIN BOM
# ============================================

function Save-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)

    [System.IO.File]::WriteAllText(
        $Path,
        $Content,
        $encoding
    )
}


# ============================================
# NORMALIZAR LINEAS
# ============================================

function Normalize-Lines {
    param(
        [string]$Text
    )

    $Text = $Text -replace "`r`n", "`n"
    $Text = $Text -replace "`r", "`n"

    $lines = $Text -split "`n"

    $result = @()

    foreach ($line in $lines) {

        $trimmed = $line.Trim()

        if ($trimmed -eq "") {
            continue
        }

        # Ignorar separadores Markdown:
        #
        # | ---------- | -- |
        #
        if (
            $trimmed -match
            '^\|\s*:?-+\s*(\|\s*:?-+\s*)+\|?$'
        ) {
            continue
        }

        $result += $line
    }

    return $result
}


# ============================================
# DETECTAR TABLAS DE DOS COLUMNAS
# ============================================

function Parse-TableRows {
    param(
        [string[]]$Lines
    )

    $rows = @()

    foreach ($raw in $Lines) {

        $line = $raw.Trim()

        # ------------------------------------
        # TABLA MARKDOWN
        #
        # | CODIGO | 10 |
        # ------------------------------------

        if (
            $line.StartsWith("|") -and
            $line.Contains("|")
        ) {

            $parts =
                $line.Trim("|").Split("|") |
                ForEach-Object {
                    $_.Trim()
                }

            if ($parts.Count -ge 2) {

                $rows += ,@(
                    $parts[0],
                    $parts[1]
                )

                continue
            }
        }


        # ------------------------------------
        # EXCEL
        #
        # Columnas separadas por TAB
        # ------------------------------------

        if ($line.Contains("`t")) {

            $parts = $line -split "`t"

            $parts =
                $parts |
                ForEach-Object {
                    $_.Trim()
                }

            if ($parts.Count -ge 2) {

                $rows += ,@(
                    $parts[0],
                    $parts[1]
                )

                continue
            }
        }


        # ------------------------------------
        # TEXTO CON 2 O MAS ESPACIOS
        # ------------------------------------

        $parts2 = $line -split '\s{2,}'

        if ($parts2.Count -ge 2) {

            $rows += ,@(
                $parts2[0].Trim(),
                $parts2[1].Trim()
            )

            continue
        }
    }

    return $rows
}


# ============================================
# DETECTAR CODIGO
# ============================================

function Is-CodeValue {
    param(
        [string]$Value
    )

    return (
        $Value -match '[A-Za-z]'
    )
}


# ============================================
# DETECTAR ENTERO
# ============================================

function Is-IntegerValue {
    param(
        [string]$Value
    )

    $v = $Value.Trim()

    $v = $v -replace '\$', ''

    $v = $v.Replace(",", "")

    return (
        $v -match '^-?\d+$'
    )
}


# ============================================
# DETECTAR DECIMAL O DINERO
# ============================================

function Is-DecimalOrMoneyValue {
    param(
        [string]$Value
    )

    $v = $Value.Trim()

    if ($v -match '\$') {
        return $true
    }

    $clean = $v -replace '\$', ''

    $clean = $clean.Replace(",", "")

    return (
        $clean -match '^-?\d+\.\d+$'
    )
}


# ============================================
# GENERAR PMC
# ============================================

function Build-Pmc {
    param(
        [string[]]$Codes
    )

    $cleanCodes = @()

    foreach ($code in $Codes) {

        $value = $code.Trim()

        if ($value -ne "") {
            $cleanCodes += $value
        }
    }


    # ----------------------------------------
    # IMPORTANTE
    #
    # Pulover necesita literalmente:
    #
    # `n
    #
    # NO un salto de linea real.
    #
    # ASCII 96 = `
    # ----------------------------------------

    $sep = [char]96 + "n"


    $joined = $cleanCodes -join $sep


    $content =
        "[PMC Globals]|None||" +
        "`r`n" +

        "[PMC Code v5.4.0]|^q||1|Window,2,Fast,0,1,Input,-1,-1,1|1|Macro1" +
        "`r`n" +

        "Context=None|" +
        "`r`n" +

        "Groups=Start:1" +
        "`r`n" +

        "1|[Text]|AAAA" +
        $sep +
        $joined +
        $sep +
        "AAAA|1|5|SendEvent||||||"


    return $content
}


# ============================================
# PREPARAR ARRAY PARA AHK
# ============================================

function Quote-AhkArray {
    param(
        [string[]]$Values
    )

    $output = @()

    foreach ($v in $Values) {

        $x = $v.Trim()

        # Escapar comillas
        $x = $x.Replace('"', '""')

        $output += '"' + $x + '"'
    }

    return (
        $output -join ", "
    )
}


# ============================================
# GENERAR F5
# ============================================

function Build-F5 {
    param(
        [string[]]$Values
    )

    $arr = Quote-AhkArray $Values


    $content = @"
; ==========================
; Script generado: F5
; ==========================

; Lista de valores a escribir
numbers := [$arr]

; Pausa inicial
Sleep 3000

; Recorrer lista
Loop numbers.Length {

    v := Trim(numbers[A_Index])
    v := StrReplace(v, "$")

    ; Regla especial SOLO F5
    ; Si el valor es exactamente 1
    ; solamente baja

    if (v = "1") {

        Sleep 2000

        Send "{Down}"

        Sleep 100

        continue
    }


    Send "{F5}"

    Sleep 100


    Send v

    Sleep 100


    Send "{Enter}"

    Sleep 2000


    Send "{Down}"

    Sleep 100
}


; Pause cierra el script
Pause::ExitApp


; F12 pausa / reanuda
F12::Pause
"@

    return $content
}


# ============================================
# GENERAR F11
# ============================================

function Build-F11 {
    param(
        [string[]]$Values
    )

    $arr = Quote-AhkArray $Values


    $content = @"
; ==========================
; Script generado: F11
; ==========================

; Lista de valores
numbers := [$arr]

; Pausa inicial
Sleep 3000


Loop numbers.Length {

    v := Trim(numbers[A_Index])

    v := StrReplace(v, "$")


    Send "{F11}"

    Sleep 100


    Send v

    Sleep 100


    Send "{Enter}"

    Sleep 2000


    Send "{Down}"

    Sleep 100
}


Pause::ExitApp


F12::Pause
"@

    return $content
}


# ============================================
# GENERAR F511
# ============================================

function Build-F511 {
    param(
        [string[]]$F5Values,
        [string[]]$F11Values
    )

    $arr5 = Quote-AhkArray $F5Values

    $arr11 = Quote-AhkArray $F11Values


    $content = @"
; ==========================================
; Script generado:
; F5 + F11 INTERCALADO
; ==========================================


numbersF5 := [$arr5]

numbersF11 := [$arr11]


Sleep 3000


lenF5 := numbersF5.Length

lenF11 := numbersF11.Length


maxLen := (lenF5 > lenF11)
    ? lenF5
    : lenF11


Loop maxLen {

    i := A_Index


    ; ======================================
    ; F5
    ; ======================================

    if (i <= lenF5) {

        v5 := Trim(numbersF5[i])

        v5 := StrReplace(v5, "$")


        ; Regla especial F5

        if (v5 != "1") {

            Send "{F5}"

            Sleep 100


            Send v5

            Sleep 100


            Send "{Enter}"

            Sleep 2000
        }
    }


    ; ======================================
    ; F11
    ; ======================================

    if (i <= lenF11) {

        v11 := Trim(numbersF11[i])

        v11 := StrReplace(v11, "$")


        Send "{F11}"

        Sleep 100


        Send v11

        Sleep 100


        Send "{Enter}"

        Sleep 2000
    }


    ; ======================================
    ; BAJAR UNA FILA
    ; ======================================

    Send "{Down}"

    Sleep 100
}


Pause::ExitApp


F12::Pause
"@

    return $content
}


# ============================================
# MENU MANUAL
# ============================================

function Show-Menu {

    Write-Host ""

    Write-Host `
        "NO PUDE DETERMINAR EL TIPO" `
        -ForegroundColor Yellow

    Write-Host ""

    Write-Host "1 = LISTA / PMC"

    Write-Host "2 = F5 / AHK"

    Write-Host "3 = F11 / AHK"

    Write-Host "4 = Cancelar"

    Write-Host ""


    $choice =
        Read-Host "Elige una opcion"


    return $choice
}


# ============================================
# INICIO
# ============================================

Clear-Host


Write-Host `
    "============================================" `
    -ForegroundColor Cyan

Write-Host `
    "              GENERADOR LNP" `
    -ForegroundColor Cyan

Write-Host `
    "============================================" `
    -ForegroundColor Cyan

Write-Host ""

Write-Host "Leyendo portapapeles..."

Write-Host ""


# ============================================
# LEER PORTAPAPELES
# ============================================

try {

    Add-Type `
        -AssemblyName System.Windows.Forms


    $clip =
        [System.Windows.Forms.Clipboard]::GetText()

}
catch {

    $clip =
        Get-Clipboard -Raw
}


# ============================================
# VALIDAR PORTAPAPELES
# ============================================

if (
    [string]::IsNullOrWhiteSpace($clip)
) {

    Write-Host ""

    Write-Host `
        "EL PORTAPAPELES ESTA VACIO." `
        -ForegroundColor Red

    Write-Host ""


    Read-Host `
        "Presiona ENTER para cerrar"


    exit
}


# ============================================
# PREPARAR DATOS
# ============================================

$lines =
    Normalize-Lines $clip


$rows =
    Parse-TableRows $lines


$generated = @()


Write-Host (
    "Lineas detectadas: " +
    $lines.Count
)


if ($rows.Count -gt 0) {

    Write-Host (
        "Filas de 2 columnas detectadas: " +
        $rows.Count
    )
}


Write-Host ""


# ============================================
# PRIMERA LINEA
# ============================================

$first =
    $lines[0].Trim().ToLower()


# ============================================
# LISTA EXPLICITA
# ============================================

if ($first -eq "lista") {

    $values = @()


    foreach (
        $line in
        ($lines | Select-Object -Skip 1)
    ) {

        $values +=
            $line.Trim().Trim("|").Trim()
    }


    $path =
        Get-UniquePath `
            "lista" `
            ".pmc"


    $content =
        Build-Pmc $values


    Save-Utf8NoBom `
        $path `
        $content


    $generated += $path
}


# ============================================
# F5 EXPLICITO
# ============================================

elseif ($first -eq "f5") {

    $values = @()


    foreach (
        $line in
        ($lines | Select-Object -Skip 1)
    ) {

        $values +=
            $line.Trim().Trim("|").Trim()
    }


    $path =
        Get-UniquePath `
            "f5" `
            ".ahk"


    $content =
        Build-F5 $values


    Save-Utf8NoBom `
        $path `
        $content


    $generated += $path
}


# ============================================
# F11 EXPLICITO
# ============================================

elseif ($first -eq "f11") {

    $values = @()


    foreach (
        $line in
        ($lines | Select-Object -Skip 1)
    ) {

        $values +=
            $line.Trim().Trim("|").Trim()
    }


    $path =
        Get-UniquePath `
            "f11" `
            ".ahk"


    $content =
        Build-F11 $values


    Save-Utf8NoBom `
        $path `
        $content


    $generated += $path
}


# ============================================
# F511 EXPLICITO
# ============================================

elseif ($first -eq "f511") {

    $f5vals = @()

    $f11vals = @()

    $mode = ""


    foreach (
        $line in
        ($lines | Select-Object -Skip 1)
    ) {

        $t =
            $line.Trim()


        $lower =
            $t.ToLower()


        if ($lower -eq "f5") {

            $mode = "f5"

            continue
        }


        if ($lower -eq "f11") {

            $mode = "f11"

            continue
        }


        if ($mode -eq "f5") {

            $f5vals += $t
        }


        elseif ($mode -eq "f11") {

            $f11vals += $t
        }
    }


    if (
        $f5vals.Count -eq 0 -and
        $f11vals.Count -eq 0
    ) {

        Write-Host ""

        Write-Host `
            "F511 no encontro bloques F5 y F11." `
            -ForegroundColor Red

        Write-Host ""


        Read-Host `
            "Presiona ENTER para cerrar"


        exit
    }


    $path =
        Get-UniquePath `
            "f511" `
            ".ahk"


    $content =
        Build-F511 `
            $f5vals `
            $f11vals


    Save-Utf8NoBom `
        $path `
        $content


    $generated += $path
}


# ============================================
# DOS COLUMNAS
# ============================================

elseif ($rows.Count -gt 0) {

    $col1 = @()

    $col2 = @()


    foreach ($row in $rows) {

        $col1 += $row[0]

        $col2 += $row[1]
    }


    $col1Codes = 0

    $col2Ints = 0

    $col2Decimals = 0


    foreach ($v in $col1) {

        if (Is-CodeValue $v) {

            $col1Codes++
        }
    }


    foreach ($v in $col2) {

        if (Is-IntegerValue $v) {

            $col2Ints++
        }


        if (
            Is-DecimalOrMoneyValue $v
        ) {

            $col2Decimals++
        }
    }


    # ========================================
    # CODIGOS + ENTEROS
    # ========================================

    if (
        $col1Codes -eq $col1.Count -and
        $col2Ints -eq $col2.Count
    ) {

        Write-Host "Detectado:"

        Write-Host `
            "Columna 1 = CODIGOS"

        Write-Host `
            "Columna 2 = ENTEROS"

        Write-Host ""


        $pathLista =
            Get-UniquePath `
                "lista" `
                ".pmc"


        $pathF5 =
            Get-UniquePath `
                "f5" `
                ".ahk"


        Save-Utf8NoBom `
            $pathLista `
            (Build-Pmc $col1)


        Save-Utf8NoBom `
            $pathF5 `
            (Build-F5 $col2)


        $generated +=
            $pathLista


        $generated +=
            $pathF5
    }


    # ========================================
    # CODIGOS + DECIMALES
    # ========================================

    elseif (
        $col1Codes -eq $col1.Count -and
        (
            $col2Decimals -gt 0 -or
            $clip -match '\$'
        )
    ) {

        Write-Host "Detectado:"

        Write-Host `
            "Columna 1 = CODIGOS"

        Write-Host `
            "Columna 2 = PRECIOS / DECIMALES"

        Write-Host ""


        $pathLista =
            Get-UniquePath `
                "lista" `
                ".pmc"


        $pathF11 =
            Get-UniquePath `
                "f11" `
                ".ahk"


        Save-Utf8NoBom `
            $pathLista `
            (Build-Pmc $col1)


        Save-Utf8NoBom `
            $pathF11 `
            (Build-F11 $col2)


        $generated +=
            $pathLista


        $generated +=
            $pathF11
    }


    # ========================================
    # NO DETECTADO
    # ========================================

    else {

        $choice =
            Show-Menu


        switch ($choice) {

            "1" {

                $path =
                    Get-UniquePath `
                        "lista" `
                        ".pmc"


                Save-Utf8NoBom `
                    $path `
                    (Build-Pmc $lines)


                $generated +=
                    $path
            }


            "2" {

                $path =
                    Get-UniquePath `
                        "f5" `
                        ".ahk"


                Save-Utf8NoBom `
                    $path `
                    (Build-F5 $lines)


                $generated +=
                    $path
            }


            "3" {

                $path =
                    Get-UniquePath `
                        "f11" `
                        ".ahk"


                Save-Utf8NoBom `
                    $path `
                    (Build-F11 $lines)


                $generated +=
                    $path
            }


            default {

                Write-Host ""

                Write-Host "Cancelado."


                exit
            }
        }
    }
}


# ============================================
# UNA COLUMNA
# ============================================

else {

    $values = @()


    foreach ($line in $lines) {

        $values +=
            $line.Trim().Trim("|").Trim()
    }


    $hasLetters =
        $false


    $allIntegers =
        $true


    $hasDecimalOrMoney =
        $false


    foreach ($v in $values) {

        if (
            Is-CodeValue $v
        ) {

            $hasLetters =
                $true
        }


        if (
            -not
            (Is-IntegerValue $v)
        ) {

            $allIntegers =
                $false
        }


        if (
            Is-DecimalOrMoneyValue $v
        ) {

            $hasDecimalOrMoney =
                $true
        }
    }


    # ========================================
    # PMC
    # ========================================

    if ($hasLetters) {

        Write-Host `
            "Detectado automaticamente: LISTA / PMC"

        Write-Host ""


        $path =
            Get-UniquePath `
                "lista" `
                ".pmc"


        Save-Utf8NoBom `
            $path `
            (Build-Pmc $values)


        $generated +=
            $path
    }


    # ========================================
    # F5
    # ========================================

    elseif ($allIntegers) {

        Write-Host `
            "Detectado automaticamente: F5 / AHK"

        Write-Host ""


        $path =
            Get-UniquePath `
                "f5" `
                ".ahk"


        Save-Utf8NoBom `
            $path `
            (Build-F5 $values)


        $generated +=
            $path
    }


    # ========================================
    # F11
    # ========================================

    elseif ($hasDecimalOrMoney) {

        Write-Host `
            "Detectado automaticamente: F11 / AHK"

        Write-Host ""


        $path =
            Get-UniquePath `
                "f11" `
                ".ahk"


        Save-Utf8NoBom `
            $path `
            (Build-F11 $values)


        $generated +=
            $path
    }


    # ========================================
    # MANUAL
    # ========================================

    else {

        $choice =
            Show-Menu


        switch ($choice) {

            "1" {

                $path =
                    Get-UniquePath `
                        "lista" `
                        ".pmc"


                Save-Utf8NoBom `
                    $path `
                    (Build-Pmc $values)


                $generated +=
                    $path
            }


            "2" {

                $path =
                    Get-UniquePath `
                        "f5" `
                        ".ahk"


                Save-Utf8NoBom `
                    $path `
                    (Build-F5 $values)


                $generated +=
                    $path
            }


            "3" {

                $path =
                    Get-UniquePath `
                        "f11" `
                        ".ahk"


                Save-Utf8NoBom `
                    $path `
                    (Build-F11 $values)


                $generated +=
                    $path
            }


            default {

                Write-Host ""

                Write-Host "Cancelado."


                exit
            }
        }
    }
}


# ============================================
# RESULTADO
# ============================================

Write-Host ""

Write-Host `
    "============================================" `
    -ForegroundColor Cyan

Write-Host `
    "ARCHIVOS GENERADOS" `
    -ForegroundColor Green

Write-Host `
    "============================================" `
    -ForegroundColor Cyan

Write-Host ""


foreach ($file in $generated) {

    Write-Host (
        [System.IO.Path]::GetFileName($file)
    )
}


Write-Host ""

Write-Host (
    "Carpeta: " +
    $PSScriptRoot
)

Write-Host ""


Read-Host `
    "Presiona ENTER para cerrar"