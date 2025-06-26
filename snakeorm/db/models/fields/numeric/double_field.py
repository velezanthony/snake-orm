from snakeorm.db.models.fields.field import Field
from snakeorm.db.models.fields.numeric.double_type import DoubleType


class DoubleField(Field):
    def  __init__(self, name:str, type:DoubleType= DoubleType.PRECISION, nullable:bool=False, unique:bool=False, pk:bool=False, default:int = None):

        self.type = type
        self.default:int = default
        self.value:int = None

        super().__init__(name=name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} {self.type}"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
        return result