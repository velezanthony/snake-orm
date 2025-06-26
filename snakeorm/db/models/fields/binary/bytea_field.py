from snakeorm.db.models.fields.field import Field


class ByteaField(Field):
    def __init__(self, name:str, nullable:bool = True, unique:bool = False, pk:bool = False, default:str = None):

        self.default:str = default
        self.value:str = None

        super().__init__(name = name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} BYTEA"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
        return result