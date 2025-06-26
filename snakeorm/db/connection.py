import psycopg2

from contextlib import contextmanager

class Database:
    # static attributes
    host:str = "localhost"
    database:str = "database"
    user:str = "postgres"
    password:str = "1234567890"
    errors:list = []  # List of errors
    warnings:list = []  # List of warnings
    _connection = None  # Static connection variable

    @staticmethod
    def connect():
        """
        Establish a connection to PostgreSQL and store it
        in the '_connection' attribute for later use.
        """
        if not Database._connection:
            try:
                # Attempt to connect to the PostgreSQL database
                Database._connection = psycopg2.connect(
                    host=Database.host,
                    database=Database.database,
                    user=Database.user,
                    password=Database.password
                )
            except psycopg2.OperationalError as e:
                # Catch connection-related errors
                print(f"Error: Could not connect to the database. Please check your credentials.")
                print(f"Details: {e}")
                raise  # Re-raise the exception to notify the caller that connection failed
        return Database._connection

    @staticmethod
    def close():
        """ 
        Closes the connection with the database.
        """
        if Database._connection:
            Database._connection.close()
            Database._connection = None
        else:
            print("Warning: The connection is not established or already closed.")

    @staticmethod
    def cursor():
        """ 
        Returns a database cursor to execute queries.
        """
        if not Database._connection:
            raise ValueError("Error: No active connection. Please connect to the database first.")
        return Database._connection.cursor()

    @staticmethod
    def commit():
        """ 
        Commits the current transaction.
        """
        if not Database._connection:
            raise ValueError("Error: No active connection. Please connect to the database first.")
        Database._connection.commit()

    @staticmethod
    def rollback():
        """ 
        Rolls back the current transaction in case of an error.
        """
        if not Database._connection:
            raise ValueError("Error: No active connection. Please connect to the database first.")
        Database._connection.rollback()
   
    @staticmethod
    def execute_select_sql(sql: str):
        """
        Executes a SELECT SQL query and returns the results as a list of tuples (rows).

        Parameters:
        - sql (str): The full SQL SELECT query to execute.

        Returns:
        - list: A list of tuples, where each tuple is a row from the query result.
        """
        if not Database._connection:
            raise ValueError("Error: No active connection. Please connect to the database first.")
        
        cursor = Database._connection.cursor()
        try:
            cursor.execute(sql)  # Execute the SELECT SQL statement
            result = cursor.fetchall()  # Fetch all rows from the result
            return result
        except psycopg2.Error as e:
            # Handle any errors that occur during the query execution
            print(f"Error executing SELECT query: {e}")
            return None
        finally:
            cursor.close()

    @staticmethod
    @contextmanager
    def session():
        """
        Context manager para abrir y manejar una sesión de base de datos.
        Usa este contexto para ejecutar consultas de forma segura:
        
        with db.session() as cursor:
            cursor.execute("...")
        """
        conn = Database.connect()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
