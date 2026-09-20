"""
App de gestión de Sharky (escritorio, preparada para móvil).

Un servidor HTTP local, sólo con la librería estándar, que reutiliza
`SharkyAgent` tal cual y sirve una interfaz web adaptable. Se lanza con
`python -m sharky.app` (o `sharky app`) y se abre como ventana de
aplicación de Edge.

  * `datos.py`     -> lo que se enseña: panel, informes, notas renderizadas.
  * `trabajos.py`  -> acciones largas (control diario, noticias, estudio
                      mensual...) en segundo plano, de una en una.
  * `servidor.py`  -> HTTP, seguridad y arranque.
  * `static/`      -> interfaz (HTML/CSS/JS sin dependencias externas).
"""
