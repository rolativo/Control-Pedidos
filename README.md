# Control de pedidos de Mercado Libre

Programa de escritorio en español. Selecciona uno o varios PDF de control de
pedidos y genera automáticamente un PDF compacto para cada archivo.

## Uso diario

1. Abre `Control_Pedidos.exe`.
2. Pulsa **Seleccionar PDF** y elige tus archivos.
3. El programa genera el control sin pedir confirmación. Pulsa **Abrir control**
   para revisarlo o imprimirlo.

El ejecutable de Windows no requiere instalar Python. Los PDF se procesan en tu
computadora, sin enviarlos a servidores. GitHub sirve para guardar el código y
crear el ejecutable; no necesita tus PDF ni los datos de los compradores.

## Obtener el ejecutable con GitHub

Requisitos: una cuenta de GitHub, un repositorio con estos archivos y GitHub
Actions habilitado. No es necesario instalar herramientas de programación en
tu computadora para esta opción.

1. Crea un repositorio llamado `Control-Pedidos`. Puedes hacerlo privado.
2. Sube el contenido de esta carpeta a la raíz del repositorio, incluida la
   carpeta `.github` con el archivo `.github/workflows/windows.yml`.
   No subas el ZIP cerrado; sube sus archivos descomprimidos.
3. En **Actions** (Acciones), abre **Crear programa para Windows**.
4. Cuando la ejecución termine correctamente, abre sus resultados y descarga
   **Control_Pedidos_Windows**, en **Artifacts** (Archivos generados).
5. Extrae el ZIP descargado y abre `Control_Pedidos.exe`.

El proceso se ejecuta al subir cambios a `main` o `master`. También se puede
iniciar manualmente desde **Run workflow** (Ejecutar flujo de trabajo). Si
GitHub muestra que Actions está deshabilitado, habilítalo para este repositorio.
Los archivos generados se conservan 30 días; puedes volver a ejecutar el flujo.

## Archivos generados

- Primer resultado: `Control_resumido.pdf`.
- Si ese nombre ya existe: `Control_resumido_YYYY-MM-DD.pdf` y sufijos numéricos.
- De forma predeterminada se guardan junto a cada PDF original.
- **Elegir carpeta de salida** permite guardarlos en otra carpeta.
- El programa nunca sobrescribe el PDF original ni un resultado anterior.
- Si un archivo no se puede interpretar o validar, no genera un PDF nuevo
  para ese archivo. Los demás archivos seleccionados se procesan por separado.

## Contenido y diseño

- A4 vertical, blanco y negro, dos columnas, márgenes de 6 mm aproximadamente.
- Consecutivo grande desde 01 para cada PDF, sin reinicio entre páginas.
- Un mismo número de Venta mantiene juntos todos sus productos.
- SKU en negritas y cantidad destacada como ×1, ×2, etc.
- Se conservan el nombre comercial y las variantes del producto, incluido
  Color, Nombre del diseño, Talla y otros campos presentes en el original.
- Se conservan Pack ID y Venta cuando existen. Esto resuelve la contradicción
  del documento de requisitos aplicando su regla final sobre ambos campos.
- Un SKU repetido con descripción o cantidad diferente conserva sus renglones.
- Se eliminan comprador, identificadores alfanuméricos, mensajes, encabezados y
  gráficos del original.
- Cada pedido tiene únicamente un recuadro exterior y una línea vertical junto
  al número. No hay separadores horizontales entre productos.
- Un pedido más largo que una columna continúa con el mismo consecutivo y la
  palabra «Continuación». Los productos no reciben nuevos consecutivos.

## Lectura y validación

La versión inicial reconoce PDF con texto seleccionable y la tabla de Mercado
Libre con columnas de identificación y productos, como la muestra `YH.pdf`.
No utiliza OCR: un PDF escaneado, protegido con contraseña, ilegible o con una
estructura diferente detiene la conversión con un mensaje en español.

Antes de publicar el resultado se comprueban los renglones de SKU y cantidad,
las agrupaciones, los identificadores y que el PDF generado se pueda abrir. Las
cantidades mal formadas, productos sin SKU, identificadores contradictorios y
descripciones incompletas detectadas detienen la generación. Si un campo
opcional no aparece en el original, se omite; no se inventa ningún valor.

Como todo lector basado en una estructura conocida, un cambio de formato del
exportador puede requerir actualizar el programa. No se asegura compatibilidad
con todos los PDF de Mercado Libre sin probar esas estructuras.

## Ejecutar el código sin crear el EXE

Esta opción sí requiere **Python 3.11 o posterior**, con su lanzador `py`
instalado en Windows, y conexión a internet para descargar las dependencias.

1. Ejecuta `Preparar_Programa.bat` una vez. Instala las dependencias en `.venv`,
   dentro de esta misma carpeta.
2. Después utiliza `Abrir_Control.bat`.

También se pueden arrastrar uno o varios PDF sobre `Abrir_Control.bat`.

## Desarrollo

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python app.py
python app.py --sin-ventana --salida controles archivo.pdf
```

El programa contiene pruebas con documentos sintéticos para las agrupaciones,
continuaciones, consecutivos hasta 120, variantes, errores y protección de
archivos. No se incluyen PDF reales ni información de compradores en el código.

Prueba opcional de la muestra original usada en esta entrega:

```bash
CONTROL_SAMPLE_PDF=/ruta/YH.pdf python -m unittest discover -s tests -v
```

Construcción local del EXE en Windows:

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Control_Pedidos --collect-data reportlab app.py
```

La entrega inicial incluye código fuente y configuración de GitHub Actions. El
EXE de Windows se obtiene al ejecutar ese flujo en GitHub; no está dentro del
ZIP de código fuente.
