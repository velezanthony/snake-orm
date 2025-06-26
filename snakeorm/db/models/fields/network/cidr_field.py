from snakeorm.db.models.fields.field import Field
from snakeorm.db.models.fields.network.objects.network import Network


class CidrField(Field):
    def __init__(self, name:str, nullable:bool = True, unique:bool = False, pk:bool = False, default:Network = None):

        self.default:Network = default
        self.value:Network = None

        super().__init__(name = name, nullable = nullable, unique = unique, pk = pk)


    def to_sql_field(self)->str:
        result:str = f"{self.name} CIDR"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default.get_ip_mask()}"
        return result