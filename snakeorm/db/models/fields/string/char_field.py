from snakeorm.db.models.fields.field import Field


class CharField(Field):
    def  __init__(self, name:str, length: int = 255, nullable:bool=False, unique:bool=False, pk:bool=False, default:str = None):

        self.__default:int = default
        self.value:int = None
        self.length = length

        super().__init__(name=name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.__name} CHAR({self.length})"
        result += self._check_extra_fields()
        if self.__default != None:
            result += f" DEFAULT {self.__default}"
        return result