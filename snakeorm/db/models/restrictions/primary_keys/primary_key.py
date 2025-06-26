from snakeorm.db.models.fields.field import Field
from snakeorm.db.models.restrictions.primary_keys.primary_key_base import PrimaryKeyBase


class PrimaryKey(PrimaryKeyBase):
    def __init__(self, field:Field, constraint_name:str = None):
        self.__field:Field = field
        super().__init__(constraint_name = constraint_name)

    def get_field_names(self):
        return self.__field.name
    
    def _get_default_constraint_name(self, table_name:str)->str:
        return f"pk_{table_name}_f_{self.__field.name}"
