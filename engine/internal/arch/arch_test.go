// Package arch_test runs the six architecture assertions of
// ENGINE_IMPLEMENTATION_PLAN.md §10 against the real engine module tree.
//
// Each test here fails with the offending package/file/symbol and the fix,
// not a bare "FAIL" — see graph.go's Violation.String. Synthetic-fixture
// tests proving the checkers actually detect a violation (rather than
// vacuously passing because the current tree happens to be clean) live in
// graph_synthetic_test.go and source_synthetic_test.go.
package arch_test

import (
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"testing"

	"skillbrew/engine/internal/arch"
)

// moduleRoot resolves the engine module's root directory relative to this
// test file's own location on disk (via runtime.Caller), rather than
// hardcoding an absolute path, so the suite passes regardless of where the
// repository is checked out or which directory `go test` is invoked from.
func moduleRoot(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("arch: runtime.Caller could not resolve this test file's own path")
	}
	// thisFile is <moduleRoot>/internal/arch/arch_test.go.
	root, err := filepath.Abs(filepath.Join(filepath.Dir(thisFile), "..", ".."))
	if err != nil {
		t.Fatalf("arch: resolve module root: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "go.mod")); err != nil {
		t.Fatalf("arch: expected go.mod two directories above this test file, at %s: %v", root, err)
	}
	return root
}

// loadGraph loads the module path and package graph once per test, failing
// the test immediately if either step errors (e.g. `go` is not on PATH).
func loadGraph(t *testing.T) (root, modulePath string, pkgs []arch.Package) {
	t.Helper()
	root = moduleRoot(t)
	modulePath, err := arch.ModulePath(root)
	if err != nil {
		t.Fatalf("arch: %v", err)
	}
	pkgs, err = arch.LoadPackages(root)
	if err != nil {
		t.Fatalf("arch: %v", err)
	}
	return root, modulePath, pkgs
}

// joinViolations renders violations one per line, sorted for stable output.
func joinViolations(vs []arch.Violation) string {
	lines := make([]string, len(vs))
	for i, v := range vs {
		lines[i] = "  " + v.String()
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n")
}

// TestNoPackageOutsideCmdEnginedImportsVendorTransportOrStore is plan §10
// rule 1.
func TestNoPackageOutsideCmdEnginedImportsVendorTransportOrStore(t *testing.T) {
	_, modulePath, pkgs := loadGraph(t)
	if violations := arch.CheckVendorLeakage(pkgs, modulePath); len(violations) > 0 {
		t.Errorf("plan §10 rule 1 violated (vendor/transport/store reachable outside cmd/engined):\n%s", joinViolations(violations))
	}
}

// TestPortsImportsNoOtherInternalPackage is plan §10 rule 2.
func TestPortsImportsNoOtherInternalPackage(t *testing.T) {
	_, modulePath, pkgs := loadGraph(t)
	if violations := arch.CheckPortsIsolation(pkgs, modulePath); len(violations) > 0 {
		t.Errorf("plan §10 rule 2 violated (internal/ports depends on another internal package):\n%s", joinViolations(violations))
	}
}

// TestSessionLedgerGateStallImportOnlyPortsContractObs is plan §10 rule 3.
func TestSessionLedgerGateStallImportOnlyPortsContractObs(t *testing.T) {
	_, modulePath, pkgs := loadGraph(t)
	if violations := arch.CheckRestrictedImports(pkgs, modulePath); len(violations) > 0 {
		t.Errorf("plan §10 rule 3 violated (session/ledger/gate/stall import outside ports/contract/obs/stdlib):\n%s", joinViolations(violations))
	}
}

// TestAdaptersOnlyImportPortsConfigObsAudioAndSharedVendorHelpers is the
// adapter-layering rule ENGINE_IMPLEMENTATION_PLAN.md §10 states but that,
// until CheckAdapterImports existed, no test ever enforced.
func TestAdaptersOnlyImportPortsConfigObsAudioAndSharedVendorHelpers(t *testing.T) {
	_, modulePath, pkgs := loadGraph(t)
	if violations := arch.CheckAdapterImports(pkgs, modulePath); len(violations) > 0 {
		t.Errorf("adapter-layering rule violated (internal/vendors, internal/transport, or internal/store package reaches outside its allowlist):\n%s", joinViolations(violations))
	}
}

// TestEnvAccessOnlyInConfig is plan §10 rule 4.
func TestEnvAccessOnlyInConfig(t *testing.T) {
	root := moduleRoot(t)
	violations, err := arch.FindEnvAccess(root, "internal/config")
	if err != nil {
		t.Fatalf("arch: %v", err)
	}
	if len(violations) > 0 {
		t.Errorf("plan §10 rule 4 violated (os.Getenv/os.LookupEnv outside internal/config):\n%s", joinViolations(violations))
	}
}

// TestNoHardcodedModelIDLiteralsOutsideConfig is plan §10 rule 5.
func TestNoHardcodedModelIDLiteralsOutsideConfig(t *testing.T) {
	root := moduleRoot(t)
	violations, err := arch.FindModelIDLiterals(root, "internal/config")
	if err != nil {
		t.Fatalf("arch: %v", err)
	}
	if len(violations) > 0 {
		t.Errorf("plan §10 rule 5 violated (vendor model-id literal outside internal/config and testdata/):\n%s", joinViolations(violations))
	}
}

// TestSessionDoesNotCallTimeDirectly is plan §10 rule 6.
func TestSessionDoesNotCallTimeDirectly(t *testing.T) {
	root := moduleRoot(t)
	violations, err := arch.FindForbiddenTimeCalls(filepath.Join(root, "internal", "session"))
	if err != nil {
		t.Fatalf("arch: %v", err)
	}
	if len(violations) > 0 {
		t.Errorf("plan §10 rule 6 violated (time.Now/time.After/time.NewTimer called directly in internal/session):\n%s", joinViolations(violations))
	}
}
