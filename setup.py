"""
Shim de compatibilidad para instaladores antiguos.

Los metadatos y las dependencias del paquete viven en `pyproject.toml` (PEP 621).
Duplicarlos aqui provocaba que ambas listas se desincronizaran, asi que este
archivo se limita a delegar en el backend de setuptools.
"""

from setuptools import setup

setup()
