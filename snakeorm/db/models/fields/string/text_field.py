from snakeorm.db.models.fields.field import Field


class TextField(Field):
    def  __init__(self, name:str, nullable:bool=False, unique:bool=False, pk:bool=False, default:str = None):

        self.default:int = default
        self.value:int = None

        super().__init__(name=name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} TEXT"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
        return result