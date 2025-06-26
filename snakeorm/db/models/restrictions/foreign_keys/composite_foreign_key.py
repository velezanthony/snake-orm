from .foreign_key_base import BaseForeignKey
from ...fields.field import Field
from ..primary_keys import CompositePrimaryKey
from .foreign_key_action import ForeignKeyAction

class CompositeForeignKey(BaseForeignKey):
    def __init__(self, from_fields:list[Field], to_primary_key:CompositePrimaryKey, foreign_key_action:ForeignKeyAction, constraint_name:str = ""):

        from_fields_names = [field.name for field in from_fields]
        from_fields_names_str = ", ".join(from_fields_names)

        from_pk_field_names = [pk_field.name for pk_field in to_primary_key.fields]
        from_pk_field_names_str = ", ".join(from_pk_field_names)

        super().__init__(from_table_name = "", from_fields = from_fields_names_str , 
                         to_table_name = "", to_fields = from_pk_field_names_str , 
                         foreign_key_action = foreign_key_action, constraint_name = constraint_name)
