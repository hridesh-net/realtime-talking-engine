# Contracts

Shapes that cross a boundary — the API, the database, the model port, and the
handoff to the Go engine. Read the page before editing the file, and regenerate
`owner_handover/` after any change to a Pydantic model listed here.

* [REST API](/concepts/contracts/rest-api.md) - every endpoint, body, and status code.
* [Interview record](/concepts/contracts/interview-record.md) - the job spec in and the record out.
* [InterviewExpectation](/concepts/contracts/interview-expectation.md) - the interviewer's plan document.
* [VirtualCandidate](/concepts/contracts/virtual-candidate.md) - the full persona document.
* [EngineContract](/concepts/contracts/engine-contract.md) - the runtime slice the Go engine consumes.
* [StructuredModel](/concepts/contracts/structured-model.md) - the provider-agnostic model port for schema-constrained JSON.
* [ChatModel](/concepts/contracts/chat-model.md) - the sibling port for free-text conversation turns.
* [Realtime voice](/concepts/contracts/realtime-voice.md) - the broker port, the ephemeral credential, and the browser-to-vendor media path.
* [Session transcript](/concepts/contracts/session-transcript.md) - a live interview and its server-stamped turns.
* [Storage ports](/concepts/contracts/storage-ports.md) - the four narrow persistence protocols.
* [Database schema](/concepts/contracts/database-schema.md) - SQLite tables, constraints, indexes.
