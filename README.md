# veoleo

Aplicación local para practicar la lectura temprana en español.

El programa está en [`reading_app`](reading_app/README.md). Desde esa carpeta:

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Luego abre http://127.0.0.1:8000

La primera pantalla elige Leer o Escribir. Las dos usan los mismos sets. La escritura se guarda en tablas aparte de la misma base SQLite.

Ahí se explica el método de sets, la diferencia entre mostrar una palabra y evaluarla, el día del programa y las bases SQLite de `data/databases/`.
