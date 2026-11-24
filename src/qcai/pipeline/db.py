"""SQLModel persistence for projects and jobs with crash/restart reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from qcai.interfaces.runner import JobHandle, JobRunner


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProjectRecord(SQLModel, table=True):
    """Research project metadata stored in SQLite."""

    project_id: str = Field(primary_key=True)
    title: str
    request_json: str
    plan_json: str | None = None
    status: str = "created"  # created | running | paused | needs_human | completed | failed
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class JobRecord(SQLModel, table=True):
    """Single calculation or search job row supporting breakpoint resume & reconciliation."""

    job_id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    stage: str
    cluster_label: str
    job_kind: str = "gaussian"  # gaussian | search
    command: str = ""
    charge: int = 0
    multiplicity: int = 1
    level: str = ""
    status: str = Field(default="queued", index=True)
    pid: str | None = None
    remote_dir: str = ""
    local_dir: str = ""
    attempts: int = 0
    fixes: str = "[]"
    meta_json: str = "{}"
    result_path: str | None = None
    error_message: str | None = None
    duration_seconds: float | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class JobStore:
    """SQLite-backed store for ProjectRecord and JobRecord."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)

    def upsert_project(self, project: ProjectRecord) -> ProjectRecord:
        project.updated_at = _utcnow()
        with Session(self.engine) as session:
            existing = session.get(ProjectRecord, project.project_id)
            if existing is None:
                session.add(project)
                session.commit()
                session.refresh(project)
                return project
            for field_name in ("title", "request_json", "plan_json", "status", "updated_at"):
                setattr(existing, field_name, getattr(project, field_name))
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with Session(self.engine) as session:
            return session.get(ProjectRecord, project_id)

    def list_projects(self, *, status: str | None = None) -> list[ProjectRecord]:
        with Session(self.engine) as session:
            stmt = select(ProjectRecord)
            if status is not None:
                stmt = stmt.where(ProjectRecord.status == status)
            stmt = stmt.order_by(col(ProjectRecord.created_at))
            return list(session.exec(stmt).all())

    def set_project_status(self, project_id: str, status: str) -> ProjectRecord:
        proj = self.get_project(project_id)
        if proj is None:
            raise KeyError(f"Unknown project: {project_id!r}")
        proj.status = status
        return self.upsert_project(proj)

    def upsert_job(self, job: JobRecord) -> JobRecord:
        job.updated_at = _utcnow()
        with Session(self.engine) as session:
            existing = session.get(JobRecord, job.job_id)
            if existing is None:
                session.add(job)
                session.commit()
                session.refresh(job)
                return job
            for field_name in (
                "project_id",
                "stage",
                "cluster_label",
                "job_kind",
                "command",
                "charge",
                "multiplicity",
                "level",
                "status",
                "pid",
                "remote_dir",
                "local_dir",
                "attempts",
                "fixes",
                "meta_json",
                "result_path",
                "error_message",
                "duration_seconds",
                "updated_at",
            ):
                setattr(existing, field_name, getattr(job, field_name))
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

    def get_job(self, job_id: str) -> JobRecord | None:
        with Session(self.engine) as session:
            return session.get(JobRecord, job_id)

    def list_jobs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        stage: str | None = None,
    ) -> list[JobRecord]:
        with Session(self.engine) as session:
            stmt = select(JobRecord)
            if project_id is not None:
                stmt = stmt.where(JobRecord.project_id == project_id)
            if status is not None:
                stmt = stmt.where(JobRecord.status == status)
            if stage is not None:
                stmt = stmt.where(JobRecord.stage == stage)
            stmt = stmt.order_by(col(JobRecord.created_at))
            return list(session.exec(stmt).all())

    def reconcile(self, runner: JobRunner, *, project_id: str | None = None) -> list[JobRecord]:
        """Reconcile all `running` jobs in SQLite against remote runner status."""
        running = self.list_jobs(project_id=project_id, status="running")
        updated: list[JobRecord] = []
        for job in running:
            handle = JobHandle(
                job_id=job.job_id,
                pid=job.pid,
                remote_dir=Path(job.remote_dir),
            )
            st = runner.poll(handle)
            job.fixes = json.dumps(st.fixes, ensure_ascii=False)
            if st.state == "done":
                job.status = "done"
                job.error_message = None
                if job.created_at:
                    created = (
                        job.created_at.replace(tzinfo=UTC)
                        if job.created_at.tzinfo is None
                        else job.created_at
                    )
                    job.duration_seconds = max(0.1, (_utcnow() - created).total_seconds())
            elif st.state == "failed":
                job.status = "needs_human"
                job.error_message = st.message or "Remote job failed"
            elif st.state == "cancelled":
                job.status = "cancelled"
            elif st.state == "running":
                job.status = "running"
                if st.message:
                    job.error_message = st.message
            updated.append(self.upsert_job(job))
        return updated
