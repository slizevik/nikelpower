"""Relationship types for the knowledge graph."""

from pydantic import BaseModel, Field


class UsesMaterial(BaseModel):
    """Process or equipment uses a material."""

    role: str | None = Field(default=None, description="Role of material: feed, reagent, product")


class OperatesAtCondition(BaseModel):
    """Process or experiment operates under specific conditions."""

    condition_summary: str | None = Field(default=None, description="Summary of operating conditions")


class ProducesOutput(BaseModel):
    """Process or experiment produces an output material or result."""

    yield_info: str | None = Field(default=None, description="Yield or output description if known")


class DescribedIn(BaseModel):
    """Entity or fact is described in a publication or document."""

    section: str | None = Field(default=None, description="Section or page reference if known")


class ValidatedBy(BaseModel):
    """Claim or result is validated by experiment or source."""

    confidence: str | None = Field(
        default=None, description="high, medium, low based on evidence"
    )


class Contradicts(BaseModel):
    """Two facts or conclusions contradict each other."""

    reason: str | None = Field(default=None, description="Nature of contradiction")


EDGE_TYPES: dict[str, type[BaseModel]] = {
    "uses_material": UsesMaterial,
    "operates_at_condition": OperatesAtCondition,
    "produces_output": ProducesOutput,
    "described_in": DescribedIn,
    "validated_by": ValidatedBy,
    "contradicts": Contradicts,
}

# Which relationships can exist between entity type pairs (source_label, target_label) -> [edge_names]
EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Process", "Material"): ["uses_material", "produces_output"],
    ("Equipment", "Material"): ["uses_material"],
    ("Process", "Property"): ["operates_at_condition"],
    ("Experiment", "Property"): ["operates_at_condition"],
    ("Experiment", "Material"): ["uses_material", "produces_output"],
    ("Experiment", "Process"): ["validated_by"],
    ("Material", "Publication"): ["described_in"],
    ("Process", "Publication"): ["described_in"],
    ("Equipment", "Publication"): ["described_in"],
    ("Experiment", "Publication"): ["described_in"],
    ("Expert", "Publication"): ["described_in"],
    ("Expert", "Process"): ["validated_by"],
    ("Facility", "Experiment"): ["validated_by"],
    ("Property", "Property"): ["contradicts"],
    ("Process", "Process"): ["contradicts"],
}
