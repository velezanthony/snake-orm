from .foreign_key_action import ForeignKeyAction
from ...fields.field import Field

class ForeignKeyBase:
    """ Base class for all Foreign Keys. """
    def __init__(self, from_table_name:str, from_fields:str , to_table_name:str, to_fields:str, foreign_key_action:ForeignKeyAction, constraint_name:str = ""):
        
        self.from_table_name = from_table_name        
        self.from_fields = from_fields
        self.to_table_name = to_table_name
        self.to_fields = to_fields
        self.foreign_key_action = foreign_key_action

        if not constraint_name:
            # If constraint_name is empty asign default name
            new_constraint_name = self.from_fields.replace(", ", "_f_")
            self.constraint_name = f"fk_{self.from_table_name}_{new_constraint_name}"
        else:
            self.constraint_name = constraint_name

    
    def to_sql_base_foreign_key(self)->str:
        sql_syntax = f" ALTER TABLE {self.from_fields} ADD CONSTRAINT {self.constraint_name} FOREIGN KEY ({self.from_fields}) REFERENCES {self.to_table_name}({self.to_fields}) {self.foreign_key_action}"
        return sql_syntax