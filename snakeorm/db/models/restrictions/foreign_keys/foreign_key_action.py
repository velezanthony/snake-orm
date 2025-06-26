from enum import Enum

class ForeignKeyAction(Enum):
    CASCADE = "CASCADE"
    RESTRICT = "RESTRICT"
    SET_NULL = "SET NULL"
    NO_ACTION = "NO ACTION"

"""
Example of use:
print(ForeignKeyAction.CASCADE)
print(ForeignKeyAction.RESTRICT.value)
"""