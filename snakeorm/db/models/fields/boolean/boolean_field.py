from snakeorm.db.models.fields.field import Field


class BooleanField(Field):
    def __init__(self, name:str, nullable:bool = True, unique:bool = False, pk:bool = False, default:bool = None):

        self.default:bool = default
        self.value:bool = None

        super().__init__(name, nullable, unique, pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} BOOLEAN"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
        return result