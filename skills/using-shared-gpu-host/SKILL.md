---
name: using-shared-gpu-host
description: Inspect allocation, ownership, and resource use on a shared GPU host before an authorized experiment or while monitoring one. Use for shared-host GPU operations; ordinary local code changes do not need this workflow.
---

# Shared GPU Host

Identify the host, project, scheduler or container boundary, and intended job from the user's request and existing repository instructions. Do not invent an SSH destination, GPU allocation, environment, or output directory. When those facts are missing, continue local read-only investigation and ask only for the information needed for the remote operation.

## Read-only discovery

Use the host's existing scheduler or project launcher when available. Within an already authorized connection, inspect the current user and narrowly scoped GPU/process state. For a Linux host with NVIDIA tools, useful reads include:

```bash
id -un
nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

If process ownership matters, inspect only the relevant PIDs with the host's process tools. A process name alone is not ownership evidence. Preserve other users' processes, containers, files, reservations, and GPU allocations. WSL GPU reporting may be incomplete; record the limitation rather than assuming an unlisted process is absent.

## Run or modify a job

Reuse authorization already given for the identified host, job, resources, and action. Inspection permission does not imply permission to start training, stop a process, delete outputs, change allocations, or enable paid compute. Resolve missing authorization immediately before that action, after preparing a concrete command and target for review.

Follow repository limits; default to one repository-owned GPU training job at a time when no stricter limit is defined. Only the primary agent controls training. A scout may read logs, checkpoints, and metrics but must not start, stop, restart, or reconfigure processes. Do not kill an apparently stale process until identity, ownership, and authorization for that exact target are established.

Before an authorized launch, confirm the input identity, coordinate/unit contracts when applicable, selected GPUs, environment, output destination, and checkpoint/resume behavior. Preserve original data and existing formal outputs. Use the established launcher and its recovery mechanism instead of adding a competing process-control framework.

## Monitor and report

Use bounded, task-specific reads and the requested monitoring cadence. Report host/job identity, evidence time, relevant paths, commands and results, confirmed ownership, resource state, and uncertainties. Missing access or evidence is not a reason to retry training. Do not create scheduled monitoring unless the user asks for it.

At closeout preserve logs and outputs. List exact cleanup candidates separately from the experiment result; cleanup requires authorization for those targets.
