# Contracts

Shapes that cross a boundary — the API, the database, the model port, and the
handoff to the Go engine. Read the page before editing the file, and regenerate
`owner_handover/` after any change to a Pydantic model listed here.

* [REST API](/concepts/contracts/rest-api.md) - every endpoint, body, and status code.
* [Interview record](/concepts/contracts/interview-record.md) - the job spec in, the record out, the expectation checklist and the report shape.
* [Links and participants](/concepts/contracts/links-and-participants.md) - the expiring token an interview is taken through, and the email-keyed person every session records.
* [VirtualCandidate](/concepts/contracts/virtual-candidate.md) - the full persona document.
* [EngineContract](/concepts/contracts/engine-contract.md) - the runtime slice the Go engine consumes.
* [Session ingest](/concepts/contracts/session-ingest.md) - the Go engine's single write-back for a finished voice session, and the shared-secret gate on the engine routes.
* [StructuredModel](/concepts/contracts/structured-model.md) - the provider-agnostic model port for schema-constrained JSON.
* [ChatModel](/concepts/contracts/chat-model.md) - the sibling port for free-text conversation turns.
* [Realtime voice](/concepts/contracts/realtime-voice.md) - the broker port, the ephemeral credential, and the browser-to-vendor media path.
* [Session transcript](/concepts/contracts/session-transcript.md) - a live interview and its server-stamped turns.
* [Session recording](/concepts/contracts/session-recording.md) - the browser-captured audio artifact for voice sessions, and the seam to the engine's future recorder.
* [Storage ports](/concepts/contracts/storage-ports.md) - the nine narrow row-storage protocols, their workflow composites, and the separate byte-storage port (object store).
* [Database schema](/concepts/contracts/database-schema.md) - the tables, constraints and indexes — SQLite DDL (what runs) and the Postgres migrations built beside it.
* [InterviewExpectation](/concepts/contracts/interview-expectation.md) - **superseded 2026-09-13**. The retired expectation agent's plan document, kept as history.
