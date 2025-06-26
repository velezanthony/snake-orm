from snakeorm.db.models.fields.field import Field
from snakeorm.db.models.restrictions.primary_keys.primary_key_base import PrimaryKeyBase


class CompositePrimaryKey(PrimaryKeyBase):
    def  __init__(self, fields: list[Field], constraint_name:str = None):
        self.__fields:list[Field] = fields
        super().__init__(fields = fields, constraint_name = constraint_name)

    def get_field_names(self):
        return ", ".join([field.name for field in self.__fields])
    
    def _get_default_constraint_name(self, table_name:str)->str:
        result:str = f"pk_{table_name}"
        result += "_f_".join(field.name for field in self.__fields)
        return result