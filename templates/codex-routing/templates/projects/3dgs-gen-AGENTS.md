# 3dgs-gen project boundary

Treat this repository as a training and rendering boundary. Focus review and implementation on training configuration, CUDA and dependency compatibility, the model viewer, GT/Render alignment, rendering metrics, and training-artifact compatibility.

Before changing training or rendering semantics, the primary agent must confirm the data contract. GPU verification results and reconstruction or render acceptance cannot be announced as final by a subagent; escalate them to the primary agent and, when explicitly required, the read-only `critical_reviewer`.

Preserve artifact and input contracts, report the exact validation commands and evidence, and stop on ambiguity. Keep project configuration free of local paths, datasets, and business data.
