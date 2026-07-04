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


RELATION_TYPE_NAMES: tuple[str, ...] = (
    "uses_material",
    "operates_at_condition",
    "produces_output",
    "described_in",
    "validated_by",
    "contradicts",
)

EDGE_TYPES: dict[str, type[BaseModel]] = {
    "uses_material": UsesMaterial,
    "operates_at_condition": OperatesAtCondition,
    "produces_output": ProducesOutput,
    "described_in": DescribedIn,
    "validated_by": ValidatedBy,
    "contradicts": Contradicts,
}

EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Process", "Material"): ["uses_material", "produces_output"],
    ("Equipment", "Material"): ["uses_material"],
    ("Equipment", "Process"): ["validated_by"],
    ("Process", "Property"): ["operates_at_condition"],
    ("Experiment", "Property"): ["operates_at_condition"],
    ("Experiment", "Material"): ["uses_material", "produces_output"],
    ("Experiment", "Process"): ["validated_by"],
    ("Material", "Property"): ["operates_at_condition"],
    ("Material", "Publication"): ["described_in"],
    ("Process", "Publication"): ["described_in"],
    ("Equipment", "Publication"): ["described_in"],
    ("Experiment", "Publication"): ["described_in"],
    ("Expert", "Publication"): ["described_in"],
    ("Expert", "Process"): ["validated_by"],
    ("Facility", "Experiment"): ["validated_by"],
    ("Facility", "Publication"): ["described_in"],
    ("Property", "Property"): ["contradicts"],
    ("Process", "Process"): ["contradicts"],
}
