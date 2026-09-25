# veoleo

Aplicación local para practicar la lectura temprana en español, con la estructura práctica del método de Glenn Doman (*How to Teach Your Baby to Read*, 1964; en español, *Cómo enseñar a leer a su bebé*).

El programa está en [`reading_app`](reading_app/README.md). Ahí se explica para qué sirve, cómo se ve **Leer** y **Escribir**, y cómo arrancarlo. Los ajustes, el día del programa, los sets y las bases SQLite están en el [manual](reading_app/docs/manual.md).

Desde `reading_app`:

```bash
pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Luego abre http://127.0.0.1:8000. La primera pantalla elige Leer o Escribir.
