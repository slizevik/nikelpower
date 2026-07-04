"""Domain entity types for Graphiti extraction (mining/metallurgy ontology)."""

from pydantic import BaseModel, Field


class Material(BaseModel):
    """Chemical substance, alloy, ore, reagent, or industrial material."""

    chemical_formula: str | None = Field(default=None, description="Chemical formula if known")
    material_class: str | None = Field(
        default=None, description="e.g. sulfide, oxide, reagent, waste"
    )
    synonyms: str | None = Field(default=None, description="Alternative names RU/EN")


class Process(BaseModel):
    """Metallurgical or mining process or technological operation."""

    process_type: str | None = Field(
        default=None, description="e.g. hydrometallurgy, pyrometallurgy, beneficiation"
    )
    synonyms: str | None = Field(default=None, description="Alternative names RU/EN")


class Equipment(BaseModel):
    """Industrial equipment, reactor, furnace, cell, or plant unit."""

    equipment_type: str | None = Field(default=None, description="Type or category of equipment")
    manufacturer: str | None = Field(default=None, description="Manufacturer if mentioned")


class Property(BaseModel):
    """Measurable parameter: concentration, temperature, flow rate, economic indicator."""

    value: float | None = Field(default=None, description="Numeric value")
    unit: str | None = Field(default=None, description="Unit of measurement")
    parameter_name: str | None = Field(
        default=None, description="e.g. sulfate concentration, catholyte flow rate"
    )
    min_value: float | None = Field(default=None, description="Lower bound if range")
    max_value: float | None = Field(default=None, description="Upper bound if range")


class Experiment(BaseModel):
    """Laboratory or pilot experiment with conditions and results."""

    year: int | None = Field(default=None, description="Year of experiment")
    facility_name: str | None = Field(default=None, description="Lab or pilot plant name")
    outcome: str | None = Field(default=None, description="Brief result or conclusion")


class Publication(BaseModel):
    """Scientific article, patent, report, or review."""

    title: str | None = Field(default=None, description="Publication title")
    year: int | None = Field(default=None, description="Publication year")
    authors: str | None = Field(default=None, description="Authors if mentioned")
    publication_type: str | None = Field(
        default=None, description="article, patent, report, dissertation, review"
    )
    geo: str | None = Field(
        default=None, description="Geography: Russia, foreign, or specific country"
    )


class Expert(BaseModel):
    """Researcher, author, or domain expert."""

    affiliation: str | None = Field(default=None, description="Organization or laboratory")
    expertise_area: str | None = Field(default=None, description="Area of expertise")


class Facility(BaseModel):
    """Plant, mine, laboratory, or industrial site."""

    location: str | None = Field(default=None, description="Geographic location")
    facility_type: str | None = Field(
        default=None, description="mine, plant, lab, pilot facility"
    )
    geo: str | None = Field(default=None, description="Russia or foreign")


ENTITY_TYPE_NAMES: tuple[str, ...] = (
    "Material",
    "Process",
    "Equipment",
    "Property",
    "Experiment",
    "Publication",
    "Expert",
    "Facility",
)

ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Material": Material,
    "Process": Process,
    "Equipment": Equipment,
    "Property": Property,
    "Experiment": Experiment,
    "Publication": Publication,
    "Expert": Expert,
    "Facility": Facility,
}
