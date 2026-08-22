package config

import "log/slog"

// redacted is what any secret-bearing value prints as, in every formatting
// path fmt and slog can reach.
const redacted = "[REDACTED]"

// Secret holds a sensitive configuration value — a vendor API key or the
// control-plane shared secret — that must never be logged or printed. The
// zero value is a valid, empty Secret.
//
// Secret deliberately has no exported field: the only way to read the raw
// value is Reveal, so an accidental %v, %+v, %#v, or slog field never leaks
// it. Callers must call Reveal only at the point of use (setting an HTTP
// header, an SDK client option) and must never pass the result to a logger.
type Secret struct {
	value string
}

// NewSecret wraps a raw value as a Secret.
func NewSecret(value string) Secret {
	return Secret{value: value}
}

// Reveal returns the raw secret value. The result must not be logged,
// printed, or stored anywhere other than directly into the vendor call
// that needs it.
func (s Secret) Reveal() string {
	return s.value
}

// IsZero reports whether the secret is unset.
func (s Secret) IsZero() bool {
	return s.value == ""
}

// String implements fmt.Stringer with a redaction, so %v and %s never emit
// the raw value.
func (s Secret) String() string {
	if s.IsZero() {
		return ""
	}
	return redacted
}

// GoString implements fmt.GoStringer with a redaction, so %#v (which
// otherwise reflects into unexported struct fields) never emits the raw
// value.
func (s Secret) GoString() string {
	return "config.Secret{" + s.String() + "}"
}

// LogValue implements slog.LogValuer with a redaction, so passing a Secret
// as a structured logging field never emits the raw value.
func (s Secret) LogValue() slog.Value {
	return slog.StringValue(s.String())
}
