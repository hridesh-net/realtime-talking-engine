package arch

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

// goFiles returns every *.go file under root, skipping directories named
// "testdata". Fixtures under testdata are not part of the compiled program;
// plan §10 rule 5 names that exclusion explicitly for the model-id-literal
// check, and the same reasoning — a fixture is data, not code the engine
// runs — applies uniformly here so the env-access and time.Now checks never
// need a separate testdata carve-out either.
func goFiles(root string) ([]string, error) {
	var files []string
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if d.Name() == "testdata" {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.HasSuffix(path, ".go") {
			files = append(files, path)
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("arch: walk %s: %w", root, err)
	}
	return files, nil
}

// relDir returns dir's path relative to root using forward slashes, so
// exemption checks behave the same on every OS. It returns "" for root
// itself.
func relDir(root, dir string) (string, error) {
	rel, err := filepath.Rel(root, dir)
	if err != nil {
		return "", fmt.Errorf("arch: relative path of %s under %s: %w", dir, root, err)
	}
	rel = filepath.ToSlash(rel)
	if rel == "." {
		return "", nil
	}
	return rel, nil
}

// relFile returns path's path relative to root using forward slashes, for
// violation messages. It falls back to path itself if the relative path
// cannot be computed (e.g. path is outside root).
func relFile(root, path string) string {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return path
	}
	return filepath.ToSlash(rel)
}

// underAny reports whether rel is, or is nested under, any of prefixes.
func underAny(rel string, prefixes []string) bool {
	for _, p := range prefixes {
		if under(rel, p) {
			return true
		}
	}
	return false
}

// importAliases maps each of file's import local identifiers (its alias, or
// its default package name when unaliased) to the import path. Resolving
// through this map — rather than matching a selector's identifier name
// against "os" or "time" directly — means a local variable, field, or type
// that happens to be named "os" or "time" cannot produce a false positive:
// the identifier must actually resolve to an import of that package.
func importAliases(file *ast.File) map[string]string {
	aliases := make(map[string]string, len(file.Imports))
	for _, imp := range file.Imports {
		path, err := strconv.Unquote(imp.Path.Value)
		if err != nil {
			continue // malformed import literal; parser would already have failed
		}
		name := path
		if i := strings.LastIndex(path, "/"); i >= 0 {
			name = path[i+1:]
		}
		if imp.Name != nil {
			name = imp.Name.Name
		}
		aliases[name] = path
	}
	return aliases
}

// callTarget resolves a call expression of the shape pkg.Func(...) to the
// import path aliases[pkg] and the called Func name. ok is false for any
// call that is not a plain package-qualified selector call (e.g. a method
// call on a value, or a bare function call).
func callTarget(call *ast.CallExpr, aliases map[string]string) (importPath, funcName string, ok bool) {
	sel, isSel := call.Fun.(*ast.SelectorExpr)
	if !isSel {
		return "", "", false
	}
	ident, isIdent := sel.X.(*ast.Ident)
	if !isIdent {
		return "", "", false
	}
	path, known := aliases[ident.Name]
	if !known {
		return "", "", false
	}
	return path, sel.Sel.Name, true
}

// FindEnvAccess reports every os.Getenv or os.LookupEnv call under root,
// except inside a directory that is, or is nested under, one of
// exemptDirs (matched relative to root, e.g. "internal/config"). Test files
// are deliberately in scope: a test that reads a real environment variable
// is exactly the kind of accidental credential read plan §10 rule 4 exists
// to catch, and would make the test's outcome depend on the machine it runs
// on.
func FindEnvAccess(root string, exemptDirs ...string) ([]Violation, error) {
	return findCalls(root, "os", []string{"Getenv", "LookupEnv"}, exemptDirs, func(location, funcName string) Violation {
		return Violation{
			Subject: location,
			Detail: fmt.Sprintf(
				"calls os.%s; only internal/config may read the environment — add a field to its config struct instead",
				funcName,
			),
		}
	})
}

// forbiddenTimeCalls are the time package functions plan §10 rule 6 bans
// inside internal/session: each one reads or arms the real wall clock
// directly, bypassing the injected ports.Clock that makes turn timing
// testable with FakeClock.
var forbiddenTimeCalls = []string{"Now", "After", "NewTimer"}

// FindForbiddenTimeCalls reports every time.Now, time.After, or
// time.NewTimer call under dir. Test files are in scope too: a session test
// that reaches for time.Now instead of driving FakeClock reintroduces the
// flakiness the rule exists to prevent.
func FindForbiddenTimeCalls(dir string) ([]Violation, error) {
	return findCalls(dir, "time", forbiddenTimeCalls, nil, func(location, funcName string) Violation {
		return Violation{
			Subject: location,
			Detail: fmt.Sprintf(
				"calls time.%s directly; internal/session must source all timing from an injected ports.Clock so tests can drive it with FakeClock",
				funcName,
			),
		}
	})
}

// findCalls is the shared AST walk behind FindEnvAccess and
// FindForbiddenTimeCalls: it parses every *.go file under root (excluding
// exemptDirs and testdata, per goFiles), and reports each call of the form
// pkgName.fn(...) where pkgName resolves — via that file's own import
// declarations — to importPath, and fn is one of fns.
func findCalls(root, importPath string, fns []string, exemptDirs []string, report func(location, funcName string) Violation) ([]Violation, error) {
	files, err := goFiles(root)
	if err != nil {
		return nil, err
	}
	wanted := make(map[string]bool, len(fns))
	for _, fn := range fns {
		wanted[fn] = true
	}

	fset := token.NewFileSet()
	var violations []Violation
	for _, path := range files {
		rel, err := relDir(root, filepath.Dir(path))
		if err != nil {
			return nil, err
		}
		if underAny(rel, exemptDirs) {
			continue
		}
		file, err := parser.ParseFile(fset, path, nil, parser.ParseComments)
		if err != nil {
			return nil, fmt.Errorf("arch: parse %s: %w", path, err)
		}
		aliases := importAliases(file)
		ast.Inspect(file, func(n ast.Node) bool {
			call, isCall := n.(*ast.CallExpr)
			if !isCall {
				return true
			}
			pkg, fn, ok := callTarget(call, aliases)
			if !ok || pkg != importPath || !wanted[fn] {
				return true
			}
			pos := fset.Position(call.Pos())
			violations = append(violations, report(fmt.Sprintf("%s:%d", relFile(root, path), pos.Line), fn))
			return true
		})
	}
	return violations, nil
}

// modelIDPattern matches a vendor model-id literal per plan §10 rule 5:
// gemini-*, gpt-*, or a Gemini "models/*" resource name. Anchored at the
// start of the string, so a literal that merely mentions one of these
// substrings mid-sentence (e.g. in a log message) does not false-positive.
//
// "models/" requires something after the slash. The bare prefix is the Live
// API's resource-path form, not a model identity — an adapter turning a
// configured id into "models/<id>" is doing exactly what this rule wants,
// and flagging it pushed a vendor-specific path format into internal/config,
// which is meant to be vendor-neutral. A rule that is wrong in an obvious
// case gets worked around rather than obeyed.
var modelIDPattern = regexp.MustCompile(`^(gemini-|gpt-|models/.+)`)

// FindModelIDLiterals reports every string literal under root that matches
// modelIDPattern, except inside a directory that is, or is nested under, one
// of exemptDirs (matched relative to root, e.g. "internal/config") — model
// IDs are config, never hardcoded, per plan §10 rule 5 and this repo's
// CLAUDE.md. String literals are inspected via the AST, not raw file text,
// so a doc comment or a code example that happens to contain "gemini-" does
// not false-positive: only actual *ast.BasicLit string values are checked.
func FindModelIDLiterals(root string, exemptDirs ...string) ([]Violation, error) {
	files, err := goFiles(root)
	if err != nil {
		return nil, err
	}
	fset := token.NewFileSet()
	var violations []Violation
	for _, path := range files {
		rel, err := relDir(root, filepath.Dir(path))
		if err != nil {
			return nil, err
		}
		if underAny(rel, exemptDirs) {
			continue
		}
		file, err := parser.ParseFile(fset, path, nil, parser.ParseComments)
		if err != nil {
			return nil, fmt.Errorf("arch: parse %s: %w", path, err)
		}
		ast.Inspect(file, func(n ast.Node) bool {
			lit, isLit := n.(*ast.BasicLit)
			if !isLit || lit.Kind != token.STRING {
				return true
			}
			value, err := strconv.Unquote(lit.Value)
			if err != nil {
				return true // not a literal we can safely decode; skip rather than false-flag
			}
			if !modelIDPattern.MatchString(value) {
				return true
			}
			pos := fset.Position(lit.Pos())
			violations = append(violations, Violation{
				Subject: fmt.Sprintf("%s:%d", relFile(root, path), pos.Line),
				Detail: fmt.Sprintf(
					"string literal %q looks like a vendor model id; model IDs are config, never hardcoded — read it from internal/config instead",
					value,
				),
			})
			return true
		})
	}
	return violations, nil
}
