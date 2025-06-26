class QueryBuilder:
    def __init__(self, table):
        """
        Initializes the QueryBuilder for a specific table.
        :param table: The name of the table you are querying.
        """
        self.table = table
        self.select_columns = "*"
        self.where_conditions = []
        self.join_clauses = []
        self.order_by = []
        self.limit = None
        self.offset = None
        self.insert_columns = []
        self.insert_values = []
        self.update_values = {}

    def select(self, *columns):
        """
        Specifies the columns to select.
        :param columns: Columns to be included in the SELECT clause.
        """
        if columns:
            self.select_columns = ", ".join(columns)
        return self

    def where(self, condition):
        """
        Adds a condition to the WHERE clause.
        :param condition: The condition to add to the WHERE clause.
        """
        self.where_conditions.append(condition)
        return self

    def join(self, table, on_condition):
        """
        Adds a JOIN clause.
        :param table: The table to join with.
        :param on_condition: The ON condition for the join.
        """
        self.join_clauses.append(f"JOIN {table} ON {on_condition}")
        return self

    def order_by(self, *columns):
        """
        Adds an ORDER BY clause.
        :param columns: Columns to order by.
        """
        if columns:
            self.order_by = ", ".join(columns)
        return self

    def limit(self, limit):
        """
        Specifies the maximum number of rows to return.
        :param limit: The limit for the number of rows.
        """
        self.limit = limit
        return self

    def offset(self, offset):
        """
        Specifies the offset for the rows returned.
        :param offset: The number of rows to skip.
        """
        self.offset = offset
        return self

    def insert(self, **values):
        """
        Constructs an INSERT query.
        :param values: A dictionary of column-value pairs for the insert.
        """
        self.insert_columns = ", ".join(values.keys())
        self.insert_values = ", ".join([repr(value) for value in values.values()])
        return self

    def update(self, **values):
        """
        Constructs an UPDATE query.
        :param values: A dictionary of column-value pairs to update.
        """
        self.update_values = values
        return self

    def build_select(self):
        """
        Builds the SQL SELECT query.
        """
        query = f"SELECT {self.select_columns} FROM {self.table}"
        
        if self.join_clauses:
            query += " " + " ".join(self.join_clauses)
        
        if self.where_conditions:
            query += " WHERE " + " AND ".join(self.where_conditions)
        
        if self.order_by:
            query += " ORDER BY " + self.order_by
        
        if self.limit:
            query += f" LIMIT {self.limit}"
        
        if self.offset:
            query += f" OFFSET {self.offset}"
        
        return query

    def build_insert(self):
        """
        Builds the SQL INSERT query.
        """
        query = f"INSERT INTO {self.table} ({self.insert_columns}) VALUES ({self.insert_values})"
        return query

    def build_update(self):
        """
        Builds the SQL UPDATE query.
        """
        set_clause = ", ".join([f"{column} = {repr(value)}" for column, value in self.update_values.items()])
        query = f"UPDATE {self.table} SET {set_clause}"
        
        if self.where_conditions:
            query += " WHERE " + " AND ".join(self.where_conditions)
        
        return query

    def build_delete(self):
        """
        Builds the SQL DELETE query.
        """
        query = f"DELETE FROM {self.table}"
        
        if self.where_conditions:
            query += " WHERE " + " AND ".join(self.where_conditions)
        
        return query

    def build(self):
        """
        Builds the appropriate SQL query based on the provided parameters.
        """
        if self.insert_columns:  # INSERT query
            return self.build_insert()
        elif self.update_values:  # UPDATE query
            return self.build_update()
        else:  # Default is SELECT query
            return self.build_select()

# Example usage:
builder = QueryBuilder('users')
select_query = builder.select('id', 'name').where("age > 21").order_by('name').build_select()
print(select_query)

insert_query = builder.insert(name='John Doe', age=30).build_insert()
print(insert_query)

update_query = builder.update(name='Jane Doe').where("id = 1").build_update()
print(update_query)

delete_query = builder.where("id = 1").build_delete()
print(delete_query)
