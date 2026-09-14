# egs-main project boundary

Treat this repository as a cross-language application boundary. Focus review and implementation on Rust, TypeScript, Vue, WASM, and the interfaces between those languages.

Exploration may run in parallel when it is independent and read-only, but the primary agent must integrate decisions about public protocols, serialization, and cross-language behavior. Subagents must not declare a public contract or final acceptance on their own.

Preserve protocol and compatibility boundaries, report exact validation commands and evidence, and escalate conflicting behavior or unclear requirements. Keep project configuration free of local paths, datasets, and business data.
