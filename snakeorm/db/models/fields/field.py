from abc import ABC, abstractmethod
from snakeorm.db.models.fields.field_status import FieldStatus

class Field(ABC):
    def __init__(self, name:str, nullable:bool=True, unique:bool=False, pk:bool=False):
        self.__name:str = name
        self.__nullable:bool = nullable
        self.__unique:bool = unique
        self.__pk:bool = pk
        self._field_status:FieldStatus = FieldStatus.UNMODIFIED

    # Properties
    @property
    def name(self)->str:
        return self.__name
    @property
    def nullable(self)->bool:
        return self.__nullable
    @property
    def unique(self)->bool:
        return self.__unique
    @property
    def pk(self)->bool:
        return self.__pk
    # Abstract properties
    @property
    @abstractmethod
    def value(self):
        pass

    @value.setter
    @abstractmethod
    def value(self, value):
        pass
    @property
    @abstractmethod
    def default(self):
        pass

    @default.setter
    @abstractmethod
    def default(self, new_default):
        pass

    @abstractmethod
    def to_sql_field(self)->str:
        """ This method should be overridden by subclasses generate the SQL field definition for the column. RETURNs str"""
        pass

    def _check_extra_fields(self)->str:
        """IMPORTANT: ONLY CHECKS NULL and UNIQUE"""
        result: str = ""
        if not self.nullable:
            result += " NOT NULL"
        if self.unique:
            result += " UNIQUE"
        return result

    def is_pk(self)->bool:
        return self.__pk
    

    def __setattr__(self, name, value):
        """Field Status Controller"""
        print(f"hola mundo:{name}")
        if hasattr(self, '_field_status') and name == "value":
            print("prueba1")
            # Get current value of attr
            current_value = getattr(self, name, None)
            if self._field_status == FieldStatus.UNMODIFIED and current_value == None:
                    self._field_status = FieldStatus.INITIAL
            elif self._field_status != FieldStatus.CHANGED:
                # If current is diferent from new value
                if current_value != value:
                    self._field_status = FieldStatus.CHANGED
                    print(f"- {name}: {value}")
        # Always change value for attribute        
        super().__setattr__(name, value)