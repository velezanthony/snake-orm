from snakeorm.db.models.fields.field import Field
from snakeorm.db.models.restrictions.primary_keys import PrimaryKey, CompositePrimaryKey

class Model:
    def __init__(self):
        """Always has:
         - table_name:str --> table name
          - table_schema:str --> table schema name
           - pk:list[Field] --> table pk min 1 max x """
        pass
    def __new__(cls):
        pk_fields_counter:int = 0
        """Always are pk, table_name and table_schema atributes"""
        cls.table_name = f"{cls.__name__.lower()}s"
        cls.table_schema = "public."
        for attr_name in dir(cls):
            attr_value = getattr(cls, attr_name)
            if isinstance(attr_value, Field):
                if attr_value.is_pk():
                    cls.pk = PrimaryKey(field = attr_value)
                    pk_fields_counter += 1
            elif isinstance(attr_value, PrimaryKey):
                cls.pk = attr_value
                pk_fields_counter += 1
            elif isinstance(attr_value, CompositePrimaryKey):
                cls.pk = attr_value
                pk_fields_counter += 1
            elif isinstance(attr_value, str):
                if attr_name == "table_schema":
                    cls.table_schema = attr_value
                elif attr_name == "table_name":
                    cls.table_name = attr_value
        
        if pk_fields_counter == 0:
            raise ValueError("You must define at least 1 pk")
        elif pk_fields_counter > 1:
            raise ValueError(f"You can only define 1 pk or 1 composite pk, Total defined: {pk_fields_counter}")
        return super().__new__(cls)
    
    def __setattr__(self, name, value):
        # Get the current value of the attribute
        print(f"Setting attribute: {name} to {value}")
        current_value = getattr(self, name, None)

        # Check if the attribute is a Field
        if isinstance(current_value, Field):
            print(f"Before - Name: {name}, Value: {current_value}")
            print(f"New Value: {value}")

            # Here you can define custom logic for when the field is changed
            if current_value.value != value:
                print(f"Field {name} has been changed!")
            current_value.value = value
        else:
            # Default behavior for other attributes
            super().__setattr__(name, value)

    def create_database_table_structure(self)->str:
        result:str = f"CREATE TABLE {self.table_schema}{self.table_name}(\n"
        for attr_name, attr_value in self.__class__.__dict__.items():
            if isinstance(attr_value, Field):
                result += f"    {attr_value.to_sql_field()},\n"
        result += ");"
        return result
    def create_database_table_pk(self)->str:
        return f"{self.pk.to_sql_pk(self.table_schema, self.table_name)}"
    def create_database_table_fk(self)->str:
        return f"{self.fk.to_sql_pk(self.table_schema, self.table_name)}"    


