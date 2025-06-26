from snakeorm.db import models


class User(models.Model):

        table_schema = ""
        table_name = ""
        
        id = models.fields.SmallintField(name = "id", pk=True)
        name = models.fields.VarcharField(name = "name", max_length=50)
        last_name = models.fields.VarcharField("last_name", max_length=200)
        phone = models.fields.VarcharField(name = "phone", max_length=9, unique=True)
        email = models.fields.SmallintField(name = "email", unique= True)
        role_id = models.fields.SmallintField("role_id")

        #pk = models.restrictions.PrimaryKey(field = id)
        