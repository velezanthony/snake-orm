import xml
from snakeorm.db.models.fields.field import Field


class XmlField(Field):
    def __init__(self, name:str, nullable:bool = True, unique:bool = False, pk:bool = False, default:xml = None):

        self.default:xml = default
        self.value:xml = None

        super().__init__(name = name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} XML"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default}"
        return result