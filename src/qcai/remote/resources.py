"""Server resource probe model and adaptive ResourceManager (Section 6.4)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SoftwareStatus(BaseModel):
    """Availability and version info for a server executable."""

    available: bool = False
    path: str | None = None
    version: str | None = None


class OtherUsersLoad(BaseModel):
    """Compute processes owned by other users on the shared server."""

    other_user_process_count: int = 0
    estimated_other_busy_cores: float = 0.0


class ServerProbe(BaseModel):
    """Structured output from `qcai_remote.probe`."""

    physical_cores: int = 1
    logical_cores: int = 1
    numa_nodes: int = 1
    cores_per_numa: list[int] = Field(default_factory=lambda: [1])
    total_mem_gb: float = 4.0
    available_mem_gb: float = 2.0
    load_avg: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scratch_dir: str = "/tmp"
    scratch_free_gb: float = 50.0
    other_users: OtherUsersLoad = Field(default_factory=OtherUsersLoad)
    software: dict[str, SoftwareStatus] = Field(default_factory=dict)
    python_packages: dict[str, str | None] = Field(default_factory=dict)


class AllocationPlan(BaseModel):
    """Per-job resource sizing and dynamic concurrency cap."""

    nproc_per_job: int
    mem_gb_per_job: int
    max_concurrent_jobs: int
    allowed_new_jobs: int
    needs_scratch_cleanup: bool = False
    throttle_reason: str | None = None
    elastic_scaled: bool = False


class ResourceManager:
    """Adaptive resource allocator respecting NUMA boundaries, memory, load, and scratch."""

    def __init__(
        self,
        *,
        min_mem_per_job_gb: float = 4.0,
        mem_per_disk_slot_gb: float = 10.0,
        min_scratch_free_gb: float = 20.0,
        reserved_cores: int = 1,
        max_nproc_per_job: int = 16,
        max_mem_per_core_gb: float = 3.0,
        enable_elastic_scaling: bool = True,
    ) -> None:
        self.min_mem_per_job_gb = min_mem_per_job_gb
        self.mem_per_disk_slot_gb = mem_per_disk_slot_gb
        self.min_scratch_free_gb = min_scratch_free_gb
        self.reserved_cores = reserved_cores
        self.max_nproc_per_job = max_nproc_per_job
        self.max_mem_per_core_gb = max_mem_per_core_gb
        self.enable_elastic_scaling = enable_elastic_scaling

    def plan(
        self,
        probe: ServerProbe,
        *,
        active_jobs: int = 0,
        atom_count: int = 6,
        pending_jobs: int | None = None,
        active_cores: int | None = None,
    ) -> AllocationPlan:
        """Compute nproc, %mem, concurrency limit, and throttling decision."""
        numa_cap = max(1, min(probe.cores_per_numa) if probe.cores_per_numa else 1)
        base_cores = 4 if atom_count <= 8 else (8 if atom_count <= 16 else 12)
        base_nproc = max(1, min(base_cores, numa_cap))

        usable_cores = max(
            0,
            probe.physical_cores
            - self.reserved_cores
            - int(round(probe.other_users.estimated_other_busy_cores)),
        )

        nproc = base_nproc
        elastic_scaled = False
        if self.enable_elastic_scaling and pending_jobs is not None and pending_jobs > 0:
            if active_cores is not None:
                remaining_cores = max(0, usable_cores - active_cores)
                share = remaining_cores // pending_jobs
            else:
                demand_jobs = active_jobs + pending_jobs
                share = usable_cores // demand_jobs
            elastic_cap = min(numa_cap, max(base_nproc, self.max_nproc_per_job))
            if share > base_nproc:
                target = min(elastic_cap, share)
                if target > base_nproc and target > 2 and target % 2 == 1:
                    target -= 1
                nproc = max(base_nproc, target)
            elastic_scaled = nproc > base_nproc

        if active_cores is not None:
            remaining_cores = max(0, usable_cores - active_cores)
            new_by_cores = remaining_cores // nproc if remaining_cores >= nproc else 0
            by_cores = active_jobs + new_by_cores
        else:
            by_cores = usable_cores // nproc if usable_cores >= nproc else 0
        by_mem = max(0, int(probe.available_mem_gb // self.min_mem_per_job_gb))
        by_disk = max(0, int(probe.scratch_free_gb // self.mem_per_disk_slot_gb))

        max_conc = min(by_cores, by_mem, by_disk)
        denom = max(1, max_conc)
        mem_share = probe.available_mem_gb / denom
        mem_cap = max(int(self.min_mem_per_job_gb), int(round(nproc * self.max_mem_per_core_gb)))
        mem_gb = max(1, min(int(0.85 * mem_share), mem_cap))

        needs_cleanup = probe.scratch_free_gb < self.min_scratch_free_gb
        throttle_reason: str | None = None
        load_1m = probe.load_avg[0] if probe.load_avg else 0.0

        if needs_cleanup:
            allowed_new = 0
            throttle_reason = (
                f"scratch 剩余空间 {probe.scratch_free_gb:.1f} GB 低于阈值 "
                f"{self.min_scratch_free_gb:.1f} GB，暂停提交并需清理 .rwf"
            )
        elif load_1m > probe.physical_cores * 0.95:
            allowed_new = 0
            throttle_reason = (
                f"服务器 1m 负载 ({load_1m:.2f}) 接近满载 ({probe.physical_cores} 核)，暂停新作业"
            )
        elif max_conc <= active_jobs:
            allowed_new = 0
            if max_conc == 0:
                throttle_reason = "可用核数/内存/磁盘不足以启动新作业"
        else:
            allowed_new = max_conc - active_jobs

        return AllocationPlan(
            nproc_per_job=nproc,
            mem_gb_per_job=mem_gb,
            max_concurrent_jobs=max_conc,
            allowed_new_jobs=allowed_new,
            needs_scratch_cleanup=needs_cleanup,
            throttle_reason=throttle_reason,
            elastic_scaled=elastic_scaled,
        )

    @staticmethod
    def from_raw_dict(raw: dict[str, Any]) -> ServerProbe:
        return ServerProbe.model_validate(raw)
