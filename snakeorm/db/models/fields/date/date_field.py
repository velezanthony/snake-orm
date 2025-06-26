from snakeorm.db.models.fields.date.date_precision import DatePrecision
from snakeorm.db.models.fields.field import Field


class DateField(Field):

    def __init__(self, name:str, precision:DatePrecision = None, nullable:bool = True, unique:bool = False, pk:bool = False, default:str = None):

        self.precision:DatePrecision = precision
        self.default:str = default
        self.value:str = None

        super().__init__(name = name, nullable = nullable, unique = unique, pk = pk)


    def to_sql_field(self)->str:
        result:str = f"{self.name} DATE"
        if self.precision != None:
            result += f"({self.precision})"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
        return result