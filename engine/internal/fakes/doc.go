// Package fakes provides deterministic, in-memory implementations of every
// internal/ports interface, for offline tests that never touch a network,
// a vendor SDK, or the real clock: FakeClock (manual advance, deterministic
// timer order), scripted FakeSpeaker/FakeTranscriber/FakeThinker driven by
// caller-supplied event tapes, an in-memory Store, and a static
// ContractSource serving the sample contract. Every fake also records what
// was called on it, so a test can assert on both what the fake produced and
// how the code under test reacted.
package fakes
