from snakeorm.db.models.fields.field import Field


class DecimalField(Field):
    def  __init__(self, name:str, max_digits:int=None, decimal_places:int=None, nullable:bool=False, unique:bool=False, pk:bool=False, default:int = None):

        self.max_digits:int = max_digits
        self.decimal_places:int = decimal_places
        self.default:int = default
        self.value:int = None

        super().__init__(name=name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} DECIMAL"
        if self.max_digits != None and self.decimal_places != None:
            result += f"({self.max_digits}, {self.decimal_places})"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
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
