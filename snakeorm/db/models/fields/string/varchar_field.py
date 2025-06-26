from snakeorm.db.models.fields.field import Field


class VarcharField(Field):
    def  __init__(self, name:str, max_length: int = 255, nullable:bool=False, unique:bool=False, pk:bool=False, default:str = None):

        self.default:int = default
        self.value:int = None
        self.max_length = max_length

        super().__init__(name=name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} VARCHAR({self.max_length})"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT '{self.default}'"
        return result
    
    @property
    def value(self)->str:
        return self.__value

    @value.setter
    def value(self, new_value:str):
        self.__value = new_value

    @property
    def default(self)->str:
        return self.__default

    @default.setter
    def default(self, new_default:str):
        self.__default = new_default
