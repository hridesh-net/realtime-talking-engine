# Contracts

Shapes that cross a boundary — the API, the database, the model port, and the
handoff to the Go engine. Read the page before editing the file, and regenerate
`owner_handover/` after any change to a Pydantic model listed here.

* [REST API](/concepts/contracts/rest-api.md) - every endpoint, body, and status code.
* [Interview record](/concepts/contracts/interview-record.md) - the job spec in and the record out.
* [InterviewExpectation](/concepts/contracts/interview-expectation.md) - the interviewer's plan document.
* [VirtualCandidate](/concepts/contracts/virtual-candidate.md) - the full persona document.
* [EngineContract](/concepts/contracts/engine-contract.md) - the runtime slice the Go engine consumes.
* [StructuredModel](/concepts/contracts/structured-model.md) - the provider-agnostic model port.
* [Storage ports](/concepts/contracts/storage-ports.md) - the three narrow persistence protocols.
* [Database schema](/concepts/contracts/database-schema.md) - SQLite tables, constraints, indexes.
