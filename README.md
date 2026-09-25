# veoleo

Aplicación local para practicar la lectura temprana en español.

El programa está en [`reading_app`](reading_app/README.md). Desde esa carpeta:

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Luego abre http://127.0.0.1:8000

Ahí se explica el método de sets, la diferencia entre mostrar una palabra y evaluarla, el día del programa y las bases SQLite de `data/databases/`.
