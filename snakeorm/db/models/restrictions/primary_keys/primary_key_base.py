from abc import abstractmethod
from snakeorm.db.models.fields.field import Field


class PrimaryKeyBase:
    def __init__(self, constraint_name:str = None):
        self.__constraint_name:str = constraint_name


    @abstractmethod
    def get_field_names(self)->str:
       "Method must be defined by subclass"
       pass
    

    def to_sql_pk(self,table_schema:str ,table_name:str):
        result = f"ALTER TABLE {table_schema}{table_name}\nADD CONSTRAINT {self.get_constraint_name(table_name)} PRIMARY KEY ({self.get_field_names()});"    
        return result
    
    @abstractmethod
    def _get_default_constraint_name(self, table_name:str)->str:
       "Method must be defined by subclass"
       pass

    def get_constraint_name(self, table_name:str)->str:
        if self.__constraint_name != None:
            return self.__constraint_name
        else:
            return self._get_default_constraint_name(table_name)
