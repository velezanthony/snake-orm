# 🐍 SnakeORM

SnakeORM es un proyecto experimental y educativo donde exploro, desde cero, cómo funciona un ORM (Object-Relational Mapper) bajo mi propia lógica y enfoque en Python.
El objetivo principal no es crear un producto de producción ni un ORM "perfecto", sino aprender, experimentar y entender en profundidad cómo se relacionan los modelos Python con bases de datos relacionales.

Este proyecto está pensado como un laboratorio personal, pero lo estructuré de forma modular y ligera para que pueda integrarse fácilmente tanto en proyectos independientes como dentro de frameworks como Django, si se desea realizar pruebas o pequeñas implementaciones.

## 📁 Estructura del Proyecto

```text
snakeorm/
│
├── snakeorm/                  # Código principal de la librería
│   ├── __init__.py
│   ├── orm.py                 # Núcleo del ORM (queries, lógica base)
│   ├── models.py              # Modelo base del ORM
│   ├── fields.py              # Tipos de campos (IntegerField, etc)
│   ├── exceptions.py          # Excepciones personalizadas
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py      # Conexiones DB
│   │   ├── builder.py         # Generador de SQL (query builder)
│   │   └── introspection.py   # Opcional: lectura del schema DB
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── validators.py
│   │   └── converters.py
│   └── config.py              # Configuración del ORM
│
├── tests/                    # Test unitarios y de integración
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_fields.py
│   └── test_queries.py
│
├── example_project/          # Proyecto Django de ejemplo (opcional pero útil)
│   ├── manage.py
│   └── example_app/
│       ├── __init__.py
│       ├── models.py         # Usa SnakeORM
│       └── views.py
│
├── setup.py                  # Metadata para instalación pip
├── pyproject.toml            # (Opcional, si usas PEP 517)
├── README.md
├── LICENSE
└── .gitignore
```

## ✅ Resumen de comandos para activar proyecto
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Correr tests
python

```