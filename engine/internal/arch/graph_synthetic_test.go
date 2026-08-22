package arch_test

// Proof that the dependency-graph checkers (CheckVendorLeakage,
// CheckPortsIsolation, CheckRestrictedImports) actually detect a violation,
// rather than passing only because the current tree happens to be clean.
// Each test builds a small, fabricated []arch.Package graph — the "in-test
// fixture" — under a fake module path, so it exercises the same checker
// function the real assertions in arch_test.go use, with no dependency on
// what other packages in this repo currently look like.

import (
	"testing"

	"skillbrew/engine/internal/arch"
)

const syntheticModule = "example.com/engine"

func TestCheckVendorLeakageDetectsInjectedViolation(t *testing.T) {
	compliant := []arch.Package{
		{
			ImportPath: syntheticModule + "/cmd/engined",
			Imports:    []string{"net/http", syntheticModule + "/internal/vendor/gemini", syntheticModule + "/internal/session"},
		},
		{
			ImportPath: syntheticModule + "/internal/session",
			Imports:    []string{"context", syntheticModule + "/internal/ports"},
		},
	}
	if violations := arch.CheckVendorLeakage(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("compliant fixture flagged: %s", joinViolations(violations))
	}

	// Inject the violation the real rule exists to catch: a non-cmd/engined
	// package reaching directly into a vendor adapter.
	dirty := append([]arch.Package{}, compliant...)
	dirty[1] = arch.Package{
		ImportPath: syntheticModule + "/internal/session",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/vendor/gemini"},
	}
	violations := arch.CheckVendorLeakage(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected vendor import, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/session" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}

	// A test-only import of a vendor package must be caught too — fakes
	// exist precisely so tests never need this.
	viaTest := []arch.Package{{
		ImportPath:  syntheticModule + "/internal/gate",
		Imports:     []string{"context"},
		TestImports: []string{"testing", syntheticModule + "/internal/vendor/openaitx"},
	}}
	if violations := arch.CheckVendorLeakage(viaTest, syntheticModule); len(violations) != 1 {
		t.Fatalf("expected the test-only vendor import to be flagged, got %d violations", len(violations))
	}
}

func TestCheckPortsIsolationDetectsInjectedViolation(t *testing.T) {
	compliant := []arch.Package{{
		ImportPath: syntheticModule + "/internal/ports",
		Imports:    []string{"context", "io", "time"},
	}}
	if violations := arch.CheckPortsIsolation(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("compliant fixture flagged: %s", joinViolations(violations))
	}

	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/ports",
		Imports:    []string{"context", syntheticModule + "/internal/contract"},
	}}
	violations := arch.CheckPortsIsolation(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected internal import, got %d: %s", len(violations), joinViolations(violations))
	}
}

func TestCheckRestrictedImportsDetectsInjectedViolation(t *testing.T) {
	compliant := []arch.Package{{
		ImportPath:  syntheticModule + "/internal/ledger",
		Imports:     []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/contract", syntheticModule + "/internal/obs"},
		TestImports: []string{"testing", syntheticModule + "/internal/fakes"}, // allowed in tests
	}}
	if violations := arch.CheckRestrictedImports(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("compliant fixture flagged: %s", joinViolations(violations))
	}

	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/ledger",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/controlplane"},
	}}
	violations := arch.CheckRestrictedImports(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected controlplane import, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/ledger" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}
