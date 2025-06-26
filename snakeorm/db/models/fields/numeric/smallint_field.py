from snakeorm.db.models.fields.field import Field


class SmallintField(Field):
    def  __init__(self, name:str, nullable:bool=False, unique:bool=False, pk:bool=False, default:int = None):

        self.__default:int = default
        self.__value:int = None

        super().__init__(name=name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} SMALLINT"
        result += self._check_extra_fields()
        if self.__default != None:
            result += f" DEFAULT {self.__default}"
        return result

    @property
    def value(self)->int:
        return self.__value

    @value.setter
    def value(self, new_value:int):
        self.__value = new_value

    @property
    def default(self)->int:
        return self.__default

    @default.setter
    def default(self, new_default:int):
        self.__default = new_default
