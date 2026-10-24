"""The base class for every jevtester model."""

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """A model that rejects unknown fields.

    Its JSON schema marks every field as required in serialization, since every field is always present in the
    output, with `null` for an unknown value.
    """

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)
