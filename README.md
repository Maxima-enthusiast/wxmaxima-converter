# wxMaxima Converter

Herramienta independiente para convertir archivos seleccionados de wxMaxima
entre `.wxm` y `.wxmx`. No busca ni modifica automáticamente todos los
archivos de un repositorio: cada archivo o directorio debe indicarse
explícitamente mediante `--path`.

## Requisitos

- Python 3.10 o posterior.
- `git`, sólo cuando se usa `--repo`.
- No requiere paquetes Python externos.

## Uso

Convertir un archivo `.wxmx` identificado por el usuario:

```powershell
python wxmaxima_convert.py `
  --repo https://github.com/usuario/proyecto.git `
  --path docs\ejemplo.wxmx `
  --to wxm `
  --output .\salida
```

Convertir la versión exacta de un commit:

```powershell
python wxmaxima_convert.py `
  --repo https://github.com/usuario/proyecto.git `
  --commit 0123456789abcdef `
  --path docs\ejemplo.wxmx `
  --to wxm
```

También se puede trabajar sobre un clon local:

```powershell
python wxmaxima_convert.py `
  --source .\proyecto `
  --path notebooks\a.wxm `
  --path notebooks\b.wxm `
  --to wxmx `
  --output .\salida
```

`--path` acepta archivos o directorios relativos al repositorio y puede
repetirse. Los archivos `.wxmx` se validan como ZIP con XML raíz
`wxMaximaDocument`; los `.wxm` deben contener marcas reconocibles de wxMaxima.

`.wxmx` es un ZIP que puede contener XML, imágenes y otros recursos, mientras
`.wxm` es texto plano. Al convertir `.wxmx` a `.wxm`, la herramienta incluye
el archivo original en un bloque base64 delimitado. Si ese `.wxm` se vuelve a
convertir, el `.wxmx` original se restaura byte por byte. Los `.wxm` creados
por otras herramientas se empaquetan como un documento XML de celdas.

La salida se escribe en un directorio separado. El modo remoto usa un clon
temporal que se elimina al terminar; `--keep-clone` permite conservarlo.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```
