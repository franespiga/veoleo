# Lectura temprana

Aplicación local para practicar la lectura de palabras sueltas en español con un niño pequeño. Sigue la estructura práctica del método Doman: palabras aisladas, sets temáticos pequeños y sesiones breves. El seguimiento de aciertos es opcional.

Python 3.12. La pantalla es una página web local. No usa cuentas ni servicios en la nube. Todo queda en este ordenador.

## Puesta en marcha

Desde la carpeta `reading_app`, con Python 3.12:

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abre http://127.0.0.1:8000

En este Windows, si `python` no es 3.12:

```bash
py -3.12 -m pip install -r requirements.txt
py -3.12 -m uvicorn app:app --host 127.0.0.1 --port 8000
```

La primera ejecución crea el vocabulario de `data/` y la base `data/databases/lectura_default.db` si todavía no existen.

## Filosofía

La unidad del programa es un **set temático**, no una tarjeta suelta con su propio calendario de repaso.

Un set normal tiene 5 palabras relacionadas. El día 1 abre con la familia:

```text
Familia 1
mamá, papá, abuela, abuelo, bebé
```

Si una categoría da para más de un set, se numeran: `Familia 1`, `Familia 2`, `Animales 1`. Si solo cabe un set, el nombre no lleva número.

Se muestran de una en una, en grande, sobre fondo blanco. La exposición ya es valiosa: ver la palabra y oírla cuenta, aunque el niño no tenga que decirla.

El botón neutro:

```text
→ Mostrar / Sin evaluar
```

registra esa exposición. No es un fallo y no baja la precisión.

## Los tres botones

De izquierda a derecha:

| Botón | Cuándo usarlo | Qué se guarda |
| --- | --- | --- |
| ✓ Correcta | El niño ha leído la palabra por su cuenta | `correct` |
| → Mostrar / Sin evaluar | Se le ha mostrado o leído la palabra, sin examen | `exposure` |
| ✗ Reforzar | Lo ha intentado y no la ha leído | `incorrect` |

Los tres avanzan enseguida a la siguiente palabra. Los tres cuentan como presentación:

```text
presentaciones = exposiciones + correctas + incorrectas
```

La precisión solo usa los intentos evaluados:

```text
precisión = correctas / (correctas + incorrectas)
```

Si no ha habido ✓ ni ✗, la pantalla dice **Sin evaluar**, no 0 %.

### Modo presentación

Es el modo inicial. Sirve para enseñar, no para examinar. El recorrido normal es pulsar → en cada palabra. Las presentaciones quedan guardadas. ✓ y ✗ siguen disponibles por si el adulto quiere anotar una lectura, pero no hace falta usarlos.

### Modo seguimiento

Mismos tres botones. El adulto puede evaluar algunas palabras y dejar otras como exposición. El programa funciona bien aunque casi todas las sesiones sean solo →.

## Día del programa

El día del programa **no es el día del calendario**. Vive en la base SQLite y solo cambia cuando el adulto pulsa **Avanzar al día siguiente**.

Así se puede saltar un sábado sin que el programa dé por hecho que ya toca el día siguiente. Si cambia la fecha del ordenador, la aplicación lo sugiere en las páginas de adulto y no modifica nada sola.

Progresión inicial:

```text
Día 1:  1 set activo   (5 palabras)
Día 2:  2 sets activos (10 palabras)
Día 3:  3 sets activos (15 palabras)
Día 4:  4 sets activos (20 palabras)
Día 5+: hasta 5 sets activos (unas 25 palabras)
```

`Palabras por set` y `Máximo de sets activos` se cambian en Ajustes. Los valores por defecto son 5 y 5.

Al llegar al máximo, un set nuevo entra cuando se retira uno de los activos. No se mezclan categorías cuando el set lo crea el programa.

## Vida de una palabra

Cada palabra pasa por `Disponible`, `Activa` y `Retirada`. Cada set pasa por `Planificado`, `Activo` y `Retirado`.

Retirar no borra nada. Las presentaciones, las sesiones y las estadísticas siguen en el historial. Una palabra retirada no vuelve sola a los sets básicos. En **Gestionar sets** se puede crear un set manual con palabras ya retiradas si el adulto quiere recuperarlas.

Un set puede alcanzar el criterio de retirada cuando **todas** sus palabras cumplen las dos cosas:

- un número de presentaciones que cuentan para la retirada (por defecto 15);
- un número de días de programa desde que entraron (por defecto 5).

**Retirada automática** está apagada por defecto. El programa avisa, por ejemplo:

```text
«Familia» ha alcanzado el criterio de retirada.
```

y ofrece **Retirar set**. Si se enciende, al avanzar el día sustituye los sets que ya cumplen el criterio.

La presentación libre y la sesión de refuerzo se guardan en el historial. Por defecto **no** cuentan para ese criterio de retirada. Hay un ajuste para que la presentación libre sí cuente.

## Refuerzo

Los fallos no cambian el set Doman de una palabra. Suben un `reinforcement_score`. Los aciertos lo bajan poco a poco. Con dificultades repetidas, **Programa de hoy** ofrece una **Sesión de refuerzo**, aparte del turno normal.

## Pantalla del niño

Al abrir la aplicación se elige **Leer** o **Escribir**. Cada una es su propia pantalla.

La página **Leer** muestra la palabra, el avance `2 / 5` y los botones. No muestra porcentajes.

Al terminar:

```text
Set completado
Presentar de nuevo · Siguiente set · Volver
```

No encadena solo la siguiente sesión.

Tres modos visuales, todos con fondo blanco y letra grande:

1. **Doman / palabra en rojo.** Toda la palabra en rojo. Es el modo inicial.
2. **Letra central en rojo.** El resto va en negro. En `sol` se marca la `o`; en `gato`, la `a`; en `perro`, la `r`.
3. **Negro.** Sin realce.

La mayúsculas se elige en Ajustes: Mayúsculas, Minúsculas o Como está escrito. Por defecto, minúsculas. Los acentos se conservan: `mamá` pasa a `MAMÁ`, `niño` a `NIÑO`.

## Escribir

**Escribir** usa los mismos sets activos y el mismo día del programa. La palabra sale en rojo. Debajo hay un recuadro azul oscuro: lo escrito se ve en blanco. Si coincide con la palabra, pasa sola a la siguiente y queda guardada como correcta. Si no coincide, las letras que sobran o no encajan se marcan en amarillo para borrarlas. Enter guarda ese intento como incorrecto y deja el texto para corregirlo.

La escritura vive en tablas propias de la misma base SQLite (`writing_sessions`, `writing_presentations`, `writing_word_stats`). No suma lecturas correctas ni incorrectas, no cambia la precisión de lectura y no cuenta para la retirada. El turno de escritura rota por sus propias sesiones, aparte del turno de lectura.

## Bases de datos / perfiles

Excel dice **qué palabras existen**. SQLite dice **qué está pasando** en el programa: día, sets activos, presentaciones, retiradas y ajustes.

Cada archivo de `data/databases/` es un programa independiente. Cambiar de base cambia palabras activas, sets, día, historial y estadísticas. El Excel es común.

```text
data/databases/lectura_default.db
data/databases/programa_nuevo.db
```

En **Ajustes → Base de datos / Perfil** se puede:

- elegir la base activa;
- crear una nueva, por ejemplo `lectura_octubre`, vacía de historial y empezando en el día 1;
- hacer una copia de seguridad;
- restablecer el progreso;
- recrear la base;
- apartar una base secundaria.

La base activa se recuerda en `data/app_config.db`.

### Copia de seguridad

**Crear copia de seguridad** usa el mecanismo de copia de SQLite y escribe en `data/backups/` un archivo con fecha y hora, por ejemplo:

```text
lectura_default_backup_2026-09-21_1630.db
```

**Recrear base de datos** hace primero esa copia, cierra el archivo, crea el esquema de nuevo, vuelve a leer el Excel y empieza en el día 1. Hay que escribir `RECREAR`.

### Restablecer progreso

Borra el día, los sets, las sesiones, las presentaciones, las escrituras y las estadísticas de la base actual, y vuelve a abrir el día 1. No borra los Excel. Hay que escribir `REINICIAR`. Los ajustes (palabras por set, modos de pantalla, etc.) se conservan.

### Borrar una base

No se puede eliminar la única base que queda. La base apartada se mueve a `data/backups/` en lugar de destruirse del todo. Hay que escribir el nombre del archivo, por ejemplo `programa_nuevo.db`.

## Vocabulario

### Mis palabras

`data/mis_palabras.xlsx` es el currículo principal. Unas 100 palabras concretas, en categorías como familia, animales, cuerpo, casa, comida, juguetes, naturaleza, colores, acciones y otros.

Columnas:

```text
word
category
enabled
```

`enabled` en 1 incluye la palabra; en 0 la deja fuera de los sets nuevos.

El día 1 sale de aquí, empezando por lo más cercano al niño (familia, animales, cuerpo, casa). No empieza por `de`, `que`, `el` o `la`.

### Frecuencia español

`data/frecuencia_espanol.xlsx` es una **lista orientada a la frecuencia, curada para esta aplicación**. No es la exportación de un corpus documentado. El orden de `rank` es práctico, no un recuento de un banco de datos.

Columnas:

```text
rank
word
enabled
```

Sirve de reserva para más adelante. En Ajustes, **Fuente de nuevas palabras** puede ser:

- Mis palabras (por defecto)
- Frecuencia
- Ambas

Las palabras de función (`de`, `que`, `el`, `la`…) se planifican después de las palabras con contenido, en sets llamados `Función`.

### Cómo editar las listas

1. Cierra el Excel si la aplicación va a leerlo.
2. Edita `data/mis_palabras.xlsx` o `data/frecuencia_espanol.xlsx`.
3. En Ajustes, pulsa **Sincronizar vocabulario Excel**.

La sincronización añade o actualiza palabras. No reconstruye sola el historial ni mete otra vez en el turno básico una palabra que ya perteneció a un set.

## Páginas

- **Inicio.** Elige Leer o Escribir.
- **Leer.** La palabra y los botones.
- **Escribir.** La palabra en rojo y el recuadro para copiarla. El progreso de escritura está en esa misma pantalla, aparte del de lectura.
- **Programa de hoy.** Día, sets activos, cuántas veces se ha presentado cada set hoy y en total, aviso de retirada, refuerzo y presentación libre.
- **Progreso.** Totales y tabla por palabra. La precisión evaluada ignora las exposiciones neutras.
- **Historial.** Por fecha, día del programa, set o palabra.
- **Gestionar sets.** Ver, renombrar, activar, retirar, reordenar los planificados y crear un set.
- **Ajustes.** Pantalla, ritmo del programa, retirada y bases de datos.

## Presentación libre

En **Programa de hoy** se puede presentar un set ya creado o unas palabras elegidas, sin alterar el turno del programa. La sesión queda como `manual`.

## Dónde está cada cosa

```text
app.py                      servidor local
web/                        pantalla del navegador
src/web_api.py              API que usa el programa
src/doman_scheduler.py      sets, días, retirada y sesiones
src/database_manager.py     perfiles, copias, reinicio
src/database.py             esquema SQLite
src/word_loader.py          lectura del Excel
src/display.py              tamaño, color y mayúsculas
src/statistics.py           precisión e informes
src/writing.py              sesiones de escritura, aparte de la lectura
data/                       Excel, bases y copias
```

Las pruebas:

```bash
pytest
```
