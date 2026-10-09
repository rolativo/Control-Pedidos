# El todo poderOSO

Un programa de escritorio en español para generar el control compacto de
Mercado Libre, agregar datos a sus etiquetas ZPL y abrir el Generador de Excel.

El ejecutable de Windows no requiere instalar Python. Los documentos se
procesan en la computadora; no se envían a GitHub ni a otro servicio.

## Control y etiquetas

1. Copia tres columnas: **Pack ID o Venta, Cantidad y SKU**. Puede ser una tabla
   de Excel o una tabla del chat. Se acepta la diagonal delante del ID.
2. En la pestaña **Principal**, pulsa **Seleccionar ZIP** y elige el
   ZIP descargado de Mercado Libre que contiene el PDF y el TXT.
3. Pulsa **Pegar tabla** y después **Generar PDF y etiquetas**.

Si ya descomprimiste el ZIP, utiliza **Seleccionar PDF** y **Seleccionar TXT**.
Se necesita un PDF y un TXT por conjunto. Un ZIP con varios de ellos se
rechaza para evitar elegir una pareja equivocada.

El programa crea una carpeta nueva `Surtido_nombre_fecha_hora`, junto al archivo
seleccionado o en la carpeta de salida que elijas. Contiene:

- `Control_resumido.pdf`: control compacto de pedidos.
- `Etiquetas/nombre.txt`: etiquetas ZPL modificadas, para usar con el mismo
  procedimiento de impresión que ya utilizas.
- `Revision.txt`: coincidencias y filas de la tabla que no se utilizaron.

La generación es conjunta: si falta la tabla de un pedido o una etiqueta, o si un
identificador no se puede leer, no se publica un conjunto nuevo. Un SKU distinto
entre el PDF y la tabla no impide generar: se usa lo que pegaste en la etiqueta. Los originales
y los resultados anteriores no se sobrescriben.

### Cantidades

Las etiquetas usan las cantidades de la tabla copiada, tal como el BAT original.
El control PDF conserva las cantidades del PDF original. Por ejemplo, si el PDF
indica dos paquetes de 20 toallas y la tabla indica 40, la etiqueta muestra
`40/TPLBL` y el control muestra `TPLBL ×2`. No se deducen multiplicadores del SKU.

Los renglones repetidos se conservan. Dos renglones del mismo SKU con cantidades
y descripciones diferentes siguen siendo dos renglones.

### Numeración y coincidencias

- Cada pedido conserva el consecutivo que le corresponde en el PDF.
- Las etiquetas se relacionan por Pack ID o por Venta; no por su posición.
- Los identificadores divididos en varios campos ZPL se reconstruyen por sus
  coordenadas. Los fragmentos impresos dos veces se cuentan una sola vez.
- Los bloques de configuración como `^XA^MCY^XZ` se conservan sin numerarse.
- Si las etiquetas están en otro orden, mantienen el número del pedido correcto.
- Los SKU y cantidades de la tabla pegada tienen prioridad para las etiquetas.
  Las diferencias frente al PDF se registran en `Revision.txt` y no bloquean
  la generación. Por ejemplo, `100/SMEN40NE` es válido aunque el PDF contenga
  `SMEN40NE-100 ×1`. El PDF conserva siempre sus datos originales.
- Una fila de la tabla con un ID que no está en el PDF se registra como no
  utilizada. No se añade a otro pedido.
- Se conservan los códigos de barras, QR, destinatarios y campos de envío.
- Se agregan el consecutivo y la línea `cantidad/SKU` de la tabla. La fuente de
  esa línea se ajusta cuando contiene varios productos. Si no cabe de forma
  legible, la generación se detiene.

La versión reconoce los formatos ZPL de las muestras entregadas, incluida la
etiqueta compacta sin marcador LAST CLUSTER. Un nuevo diseño de Mercado Libre
puede requerir actualizar el lector o la posición del texto agregado.

## Solo control PDF

En la pestaña **Solo control PDF**, pulsa **Seleccionar PDF** y elige uno o varios
archivos. Se genera automáticamente un control para cada uno, igual que antes.

- A4 vertical, blanco y negro, dos columnas y márgenes pequeños imprimibles.
- Consecutivo grande desde 01, sin reinicio entre páginas.
- Los productos de una misma Venta permanecen juntos.
- SKU y cantidad destacados; descripción comercial y variantes conservadas.
- Si un producto no tiene SKU en el original, conserva su descripción, cantidad
  y variantes dentro del mismo pedido; no se inventa un SKU.
- Pack ID y Venta visibles cuando existen; sin líneas vacías por datos ausentes.
- Solo recuadro exterior y línea vertical junto al número. Sin separadores
  horizontales internos.
- Un pedido que excede una columna continúa con el mismo número.
- Se eliminan compradores, encabezados, mensajes y gráficos del PDF original.

El resultado se llama `Control_resumido.pdf`. Si existe, se usa un nombre con
fecha y sufijo para no sustituirlo.

Si ocurre un error, aparece una ventana con el motivo y se guarda
`Error_Control.txt` (o un nombre con sufijo si ya existe). Se intenta guardarlo
en la carpeta de salida, junto al original o en una carpeta local de respaldo.
La ventana indica la ruta. También se registran errores al pegar la tabla y
errores inesperados de la interfaz o del inicio del EXE.

Se necesita un PDF con texto seleccionable y la tabla de identificación y
productos. Un PDF escaneado, protegido, ilegible o con otra estructura se
rechaza; esta versión no utiliza OCR.

## Generador de Excel

1. Copia los datos de tu tabla dinámica como lo haces habitualmente.
2. En **Principal**, pulsa el botón **Generador de Excel**, con la máscara.

El botón abre el BAT y el PowerShell originales entregados por el usuario. Se
incluyen dentro del EXE y se copian a una carpeta permanente para que sus salidas
no desaparezcan al cerrar el programa. Se corrige únicamente la correspondencia
de nombres: `GENERADOR.bat` llama a `Generador.ps1`.

El Generador lee el portapapeles y produce los mismos archivos `lista.pmc`,
`f5.ahk`, `f11.ahk` o `f511.ahk`, según sus reglas originales. Se usa `Documents/ControlPedidos/Generador` del usuario.

Este botón crea los archivos; para utilizarlos se requieren los mismos programas
que ya usas para AHK y PMC. No los ejecuta automáticamente.

## Obtener el EXE con GitHub

En **Actions** (Acciones), abre una ejecución correcta de **Crear programa para
Windows** y descarga **El_todo_poderOSO_Windows** desde **Artifacts** (Archivos
generados). Extrae el ZIP y abre `El_todo_poderOSO.exe`.

El flujo se ejecuta al subir cambios a `main` o `master`, o manualmente con
**Run workflow** (Ejecutar flujo de trabajo). Los artefactos se conservan 30 días
y pueden volver a generarse. No subas documentos reales de compradores al
repositorio.

## Desarrollo

Requisitos para ejecutar el código: Python 3.11 o posterior y las dependencias
de `requirements.txt`. Para crear el EXE se usan las de `requirements-build.txt`.
No se necesita instalar estas herramientas para utilizar el EXE ya construido.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python app.py
python app.py --sin-ventana --salida controles archivo.pdf
python app.py --sin-ventana --zip pedidos.zip --tabla tabla.txt --salida controles
python app.py --sin-ventana --txt etiquetas.txt --tabla tabla.txt archivo.pdf
```

En Windows, `Preparar_Programa.bat` prepara las dependencias dentro de `.venv`
y `Abrir_Control.bat` abre la ventana. Esta opción sí requiere Python instalado.

Construcción del ejecutable en Windows:

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name El_todo_poderOSO --icon assets/app.ico --collect-data reportlab --add-data "tools:tools" --add-data "assets:assets" app.py
python tests/smoke_windows.py dist/El_todo_poderOSO.exe
```

Las pruebas cubren los controles PDF, tablas copiadas, Pack ID y Venta
fragmentados, configuración ZPL, orden de etiquetas, protección de archivos,
conservación de códigos de envío y preparación del Generador. GitHub también
ejecuta una prueba del EXE empaquetado que genera un PDF y un TXT a partir de un
ZIP sintético. Los documentos reales de prueba no se incluyen en el código.

## Diseño y copia del TXT

El programa usa morado, verde lima y tonos oscuros. El icono del EXE es la
cabeza sin círculo y con transparencia. La máscara transparente aparece en el
botón del Generador, directamente en Principal; no tiene otra pestaña. Al abrir
el Generador también se intenta crear un acceso directo con esa máscara en su
carpeta, sin cambiar los archivos BAT y PowerShell originales.

El TXT se guarda localmente como antes y se intenta copiar, en este orden, a:

1. `\\WD-NAS\Public\impresiones`
2. `\\10.10.1.220\Public\impresiones`

La copia se llama `YYYY-MM-DD_HH-MM-SS.txt`, con fecha y hora locales de la
computadora. Si ya existe, se agrega un sufijo para no sobrescribirla. Solo se
copia el TXT. Cada intento de red tiene tiempo limitado para que una carpeta
que no responde no deje esperando indefinidamente. Si fallan ambas direcciones,
se conserva el resultado local completo y aparece un aviso; no es un error de
generación. La ruta de la copia o el aviso quedan en `Revision.txt`.
