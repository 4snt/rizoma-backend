from dataclasses import dataclass, field
from uuid import UUID, uuid4
from app.domain.shared.value_objects import MarkerType, ProjectCode


@dataclass
class ProjectAnalysis:
    analysis_type: str
    charts: list[str]


@dataclass
class Project:
    code: ProjectCode
    name: str
    marker_type: MarkerType
    id: UUID = field(default_factory=uuid4)
    status: str = "active"
    description: str = ""
    bioproject_accession: str | None = None
    created_by: UUID | None = None
    author_name: str | None = None
    author_avatar_url: str | None = None
    analyses: list[ProjectAnalysis] = field(default_factory=list)
    dada2_params: dict = field(default_factory=dict)


@dataclass
class Sample:
    project_id: UUID
    filename: str
    treatment_group: str
    replicate: int
    fastq_r1_oid: int
    fastq_r2_oid: int
    id: UUID = field(default_factory=uuid4)
