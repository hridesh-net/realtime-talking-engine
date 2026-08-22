package arch_test

// Proof that the AST-based checkers (FindEnvAccess, FindModelIDLiterals,
// FindForbiddenTimeCalls) actually detect a violation, rather than passing
// only because the current tree happens to be clean. Each test writes a
// small Go source fixture to a t.TempDir() and runs the real checker
// function against it — the same function the real assertions in
// arch_test.go use, pointed at the module tree instead.
//
// Fixture source is always embedded as an inert string (never executed, and
// never written as literal Go code in this file) so writing a fixture that
// contains, say, `os.Getenv(...)` does not itself trip this package's own
// TestEnvAccessOnlyInConfig assertion when the real suite scans internal/arch.

import (
	"os"
	"path/filepath"
	"testing"

	"skillbrew/engine/internal/arch"
)

func writeFixture(t *testing.T, dir, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
		t.Fatalf("write fixture %s: %v", name, err)
	}
}

func TestFindEnvAccessDetectsInjectedGetenvCall(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir, "leaky.go", `package leaky

import "os"

func apiKey() string {
	return os.Getenv("GEMINI_API_KEY")
}
`)
	violations, err := arch.FindEnvAccess(dir, "internal/config")
	if err != nil {
		t.Fatalf("FindEnvAccess: %v", err)
	}
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation, got %d: %v", len(violations), violations)
	}
	if want := "leaky.go:6"; violations[0].Subject != want {
		t.Fatalf("violation location = %q, want %q", violations[0].Subject, want)
	}

	// The same call, inside the exempt directory, must not be flagged —
	// proving the exemption itself works rather than the scan finding
	// nothing by accident.
	exemptDir := filepath.Join(dir, "internal", "config")
	if err := os.MkdirAll(exemptDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	writeFixture(t, exemptDir, "config.go", `package config

import "os"

func apiKey() string {
	return os.LookupEnvSibling()
}

func lookup() (string, bool) {
	return os.LookupEnv("GEMINI_API_KEY")
}
`)
	violations, err = arch.FindEnvAccess(dir, "internal/config")
	if err != nil {
		t.Fatalf("FindEnvAccess: %v", err)
	}
	if len(violations) != 1 {
		t.Fatalf("exempt directory should not add a violation, got %d: %v", len(violations), violations)
	}
}

func TestFindEnvAccessIgnoresShadowedIdentifier(t *testing.T) {
	// A local type/variable named "os" that is never actually the standard
	// library package must not be mistaken for it — proof the checker
	// resolves through real import declarations rather than name-matching.
	dir := t.TempDir()
	writeFixture(t, dir, "clean.go", `package clean

type os struct{}

func (o os) Getenv(key string) string { return key }

func f() string {
	var shadow os
	return shadow.Getenv("PATH")
}
`)
	violations, err := arch.FindEnvAccess(dir)
	if err != nil {
		t.Fatalf("FindEnvAccess: %v", err)
	}
	if len(violations) != 0 {
		t.Fatalf("expected no violations for a shadowed identifier, got %d: %v", len(violations), violations)
	}
}

func TestFindModelIDLiteralsDetectsInjectedLiteral(t *testing.T) {
	// The fixture is built from two substrings, neither of which is itself a
	// literal matching modelIDPattern ("gemini" has no trailing hyphen, and
	// "-1.5-flash" has no "gemini-" prefix): only the *concatenated* fixture
	// text, written to disk and parsed fresh by FindModelIDLiterals, forms
	// the "gemini-1.5-flash" literal under test. This keeps this test file's
	// own source clean of the pattern it is proving the checker catches, so
	// TestNoHardcodedModelIDLiteralsOutsideConfig does not flag this file
	// when it scans all of internal/arch.
	dir := t.TempDir()
	vendorPrefix, vendorSuffix := "gemini", "-1.5-flash"
	fixture := "package hardcoded\n\nconst speakerModel = \"" + vendorPrefix + vendorSuffix + "\"\n"
	writeFixture(t, dir, "hardcoded.go", fixture)

	violations, err := arch.FindModelIDLiterals(dir, "internal/config")
	if err != nil {
		t.Fatalf("FindModelIDLiterals: %v", err)
	}
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation, got %d: %v", len(violations), violations)
	}
	if want := "hardcoded.go:3"; violations[0].Subject != want {
		t.Fatalf("violation location = %q, want %q", violations[0].Subject, want)
	}

	// The identical literal inside the exempt config package, and inside a
	// testdata/ directory, must both be ignored.
	exemptDir := filepath.Join(dir, "internal", "config")
	if err := os.MkdirAll(exemptDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	writeFixture(t, exemptDir, "config.go", fixture)

	testdataDir := filepath.Join(dir, "testdata")
	if err := os.MkdirAll(testdataDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	writeFixture(t, testdataDir, "sample.go", fixture)

	violations, err = arch.FindModelIDLiterals(dir, "internal/config")
	if err != nil {
		t.Fatalf("FindModelIDLiterals: %v", err)
	}
	if len(violations) != 1 {
		t.Fatalf("exempt/testdata directories should not add violations, got %d: %v", len(violations), violations)
	}
}

func TestFindModelIDLiteralsIgnoresNonMatchingLiterals(t *testing.T) {
	// The pattern is anchored at the start of the literal: a string that
	// merely mentions the vendor name mid-sentence (e.g. a log message)
	// must not be flagged.
	dir := t.TempDir()
	writeFixture(t, dir, "clean.go", `package clean

const note = "use gemini-safe defaults; never a raw gpt- string here"
`)
	violations, err := arch.FindModelIDLiterals(dir)
	if err != nil {
		t.Fatalf("FindModelIDLiterals: %v", err)
	}
	if len(violations) != 0 {
		t.Fatalf("expected no violations for a non-prefix mention, got %d: %v", len(violations), violations)
	}
}

func TestFindForbiddenTimeCallsDetectsInjectedCalls(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir, "actor.go", `package session

import "time"

func tick() {
	_ = time.Now()
	<-time.After(time.Second)
	_ = time.NewTimer(time.Second)
}
`)
	violations, err := arch.FindForbiddenTimeCalls(dir)
	if err != nil {
		t.Fatalf("FindForbiddenTimeCalls: %v", err)
	}
	if len(violations) != 3 {
		t.Fatalf("expected exactly 3 violations (Now, After, NewTimer), got %d: %v", len(violations), violations)
	}
}

func TestFindForbiddenTimeCallsIgnoresShadowedIdentifier(t *testing.T) {
	dir := t.TempDir()
	writeFixture(t, dir, "clean.go", `package session

type time struct{}

func (t time) Now() int { return 0 }

func f() int {
	var clock time
	return clock.Now()
}
`)
	violations, err := arch.FindForbiddenTimeCalls(dir)
	if err != nil {
		t.Fatalf("FindForbiddenTimeCalls: %v", err)
	}
	if len(violations) != 0 {
		t.Fatalf("expected no violations for a shadowed identifier, got %d: %v", len(violations), violations)
	}
}
