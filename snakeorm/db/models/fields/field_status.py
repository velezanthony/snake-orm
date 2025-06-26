from enum import Enum


class FieldStatus(Enum):
    """
    FieldState: The enum defines the states a field can have:

    INITIAL: The field is in its initial state when created.

    CHANGED: The field's value has been modified.

    MODIFIED: The field's value was changed but then reverted back to the same value.

    DELETED: The field was deleted

    UNMODIFIED: The field value has not been changed since initialization.
    """
    INITIAL = "initial"
    CHANGED = "changed"
    MODIFIED = "modified"
    DELETED = "deleted"
    UNMODIFIED = "unmodified"