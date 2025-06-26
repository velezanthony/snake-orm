from snakeorm.db.models.fields.field import Field
from snakeorm.db.models.fields.network.objects.macaddress import MacAddress


class MacaddrField(Field):
    def __init__(self, name:str, nullable:bool = True, unique:bool = False, pk:bool = False, default:MacAddress = None):

        self.default:MacAddress = default
        self.value:MacAddress = None
        
        super().__init__(name = name, nullable = nullable, unique = unique, pk = pk)

    def to_sql_field(self)->str:
        result:str = f"{self.name} MACADDR"
        result += self._check_extra_fields()
        if self.default != None:
            result += f" DEFAULT {self.default.get_mac_lower()}"
        return result