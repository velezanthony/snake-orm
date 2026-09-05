"""Scaffolding GENERATES PYTHON CODE, so a malicious name in the database is code execution.

`scaffold create` reads table names, column names and comments FROM THE DATABASE and writes them
into a `models.py` the user later imports. If those texts are not escaped as Python literals, a
value with quotes and newlines escapes the literal and becomes code that runs when the generated
file is imported.

It was confirmed with a real payload: a `COMMENT ON COLUMN` that closes the `db_comment="..."`,
drops an `__import__("os").system(...)` on its own line, and reopens a literal to rebalance the
parentheses. The generated file compiled and ran the command on import.

And the irony: `migration/render.py` ALREADY escaped the SAME `db_comment` correctly with `_str_lit`.
The function existed; the scaffolding did not use it. The fix was to extract that encoder into a
shared leaf module (`snakeorm.pyliteral`) and route through it the three texts coming from the
database: table name, column name and comment.

A real threat, not a theoretical one: whoever controls the schema of a legacy database —a hostile
DBA, a compromised database, a third-party table— controls what runs on the machine of whoever
scaffolds it.
"""

from __future__ import annotations

import pytest

from snakeorm.introspection.models import render_models
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo


def _compiles(source: str) -> None:
    """Compiles the generated file; raises SyntaxError if the escaping overflowed."""
    compile(source, "models_generado.py", "exec")


# Each payload tries to break a different literal of the generated file. The name describes where it
# attacks from; the value is what an attacker would put in the schema.
_PAYLOADS = {
    "comentario_rce": 'x")\n__import__("os").system("touch /tmp/x")\n_ = ("',
    "comentario_comilla": 'dice "hola"',
    "comentario_backslash": "path\\with\\slashes",
    "comentario_salto": "line1\nlinea2",
    "name_columna_comilla": None,  # applies to the name, not to the comment
    "name_tabla_comilla": None,
}


@pytest.mark.parametrize("payload", sorted(_PAYLOADS), ids=str)
def test_a_hostile_schema_cannot_break_the_generated_file(payload: str) -> None:
    """No text from the database breaks the literal it lands in: the file ALWAYS compiles.

    It is checked by compiling, not by reading: escaping that almost works generates a file that
    almost compiles, and "almost" is exactly where the injection lives.
    """
    value = _PAYLOADS[payload]
    comment = value if value is not None else "normal"
    col_name = 'mal"name' if payload == "name_columna_comilla" else "col"
    table_name = 'mal"tabla' if payload == "name_tabla_comilla" else "tabla"

    column = SnakeColumnInfo(name=col_name, python_type=int, db_comment=comment)
    table = SnakeTableInfo(
        name=table_name,
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
    )

    _compiles(render_models([table]))  # must not raise SyntaxError


def test_the_rce_payload_does_not_execute_on_import(tmp_path: object) -> None:
    """THE test: the code-execution payload does NOT run when importing the generated file.

    It reproduces the confirmed attack end to end: renders with the payload, writes the file, imports
    it as a real module (which is what the user does after `scaffold create`) and checks that the
    side effect —creating a sentinel file— did NOT happen.
    """
    import importlib.util
    import pathlib

    sentinel = pathlib.Path("/tmp/snakeorm_rce_centinela")
    sentinel.unlink(missing_ok=True)
    payload = (
        f'x")\n__import__("pathlib").Path("{sentinel}").write_text("rce")\n_ = int("1'
    )
    column = SnakeColumnInfo(name="id", python_type=int, db_comment=payload)
    table = SnakeTableInfo(
        name="victima",
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
    )
    dest = pathlib.Path(str(tmp_path)) / "generado.py"  # type: ignore[arg-type]
    dest.write_text(render_models([table]))

    spec = importlib.util.spec_from_file_location("generado_rce", dest)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # import the generated models.py
    except Exception:
        pass  # failing while building the model is acceptable; running the payload is NOT
    finally:
        exists = sentinel.exists()
        sentinel.unlink(missing_ok=True)

    assert not exists, (
        "the db_comment payload was EXECUTED when importing the generated file"
    )


def test_unsupported_warnings_cannot_execute_on_import(tmp_path: object) -> None:
    """The `unsupported` WARNINGS do not run code either: they are raw names from the DB (triggers,
    types, indexes) and a `\\n` in a quoted name must not break the `#` comment and drop to module
    level. This was the sink that skipped `str_lit`: the same db_comment bug, somewhere else.
    """
    import importlib.util
    import pathlib

    sentinel = pathlib.Path("/tmp/snakeorm_rce_unsupported")
    sentinel.unlink(missing_ok=True)
    payload = (
        f'trigger raro\n__import__("pathlib").Path("{sentinel}").write_text("rce")\n#'
    )
    column = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="t",
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
    )
    dest = pathlib.Path(str(tmp_path)) / "gen_unsupported.py"  # type: ignore[arg-type]
    dest.write_text(render_models([table], unsupported=[payload]))

    spec = importlib.util.spec_from_file_location("gen_unsupported", dest)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        pass
    finally:
        exists = sentinel.exists()
        sentinel.unlink(missing_ok=True)

    assert not exists, (
        "an 'unsupported' warning with \\n executed code when importing the generated file"
    )
