from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
