// Package geminijson is the shared JSON-mode call both reasoning adapters make.
//
// The Thinker and the Judge ask the same vendor the same shape of question —
// system framing, one user prompt, a schema-constrained JSON answer — and
// differ only in the prompt and the schema. Duplicating the HTTP plumbing in
// each would mean fixing every transport bug twice.
//
// It lives under internal/vendors because it speaks a vendor's wire protocol:
// only cmd/engined may reach anything under here, so a vendor's shape can
// never leak into the session loop.
package geminijson

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// DefaultEndpoint is the Gemini generative-language API base.
const DefaultEndpoint = "https://generativelanguage.googleapis.com/v1beta/models"

// Client issues schema-constrained JSON completions.
type Client struct {
	// Endpoint is the API base URL. Empty means DefaultEndpoint.
	Endpoint string
	// HTTP is the client used for calls. Empty means a 20s-timeout client.
	HTTP *http.Client
	// APIKey authenticates to the vendor. It comes from internal/config;
	// this package never reads the environment.
	APIKey string
}

// Request is one schema-constrained completion.
type Request struct {
	ModelID string
	System  string
	Prompt  string
	Schema  map[string]any
	// Temperature is explicit rather than defaulted, because the two
	// callers want opposite things: retrieval wants near-zero, and a
	// silently-shared default would make one of them wrong.
	Temperature float64
}

type wireRequest struct {
	SystemInstruction *wireContent      `json:"system_instruction,omitempty"`
	Contents          []wireContent     `json:"contents"`
	GenerationConfig  wireGenerationCfg `json:"generationConfig"`
}

type wireContent struct {
	Role  string     `json:"role,omitempty"`
	Parts []wirePart `json:"parts"`
}

type wirePart struct {
	Text string `json:"text"`
}

type wireGenerationCfg struct {
	ResponseMIMEType string         `json:"responseMimeType"`
	ResponseSchema   map[string]any `json:"responseSchema"`
	Temperature      float64        `json:"temperature"`
}

type wireResponse struct {
	Candidates []struct {
		Content wireContent `json:"content"`
	} `json:"candidates"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

// Do runs one completion and returns the model's raw JSON payload.
//
// It returns the JSON rather than a decoded value so each caller owns its own
// result type — the alternative is a shared struct that grows a field every
// time either adapter needs one.
func (c *Client) Do(ctx context.Context, req Request) ([]byte, error) {
	body, err := json.Marshal(wireRequest{
		SystemInstruction: &wireContent{Parts: []wirePart{{Text: req.System}}},
		Contents:          []wireContent{{Role: "user", Parts: []wirePart{{Text: req.Prompt}}}},
		GenerationConfig: wireGenerationCfg{
			ResponseMIMEType: "application/json",
			ResponseSchema:   req.Schema,
			Temperature:      req.Temperature,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("geminijson: marshal: %w", err)
	}

	endpoint := c.Endpoint
	if endpoint == "" {
		endpoint = DefaultEndpoint
	}
	url := fmt.Sprintf("%s/%s:generateContent", strings.TrimRight(endpoint, "/"), req.ModelID)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("geminijson: build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-goog-api-key", c.APIKey)

	client := c.HTTP
	if client == nil {
		client = &http.Client{Timeout: 20 * time.Second}
	}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("geminijson: call: %w", err)
	}
	// The close error is deliberately discarded: the response body has already
	// been read by the time this runs, so a close failure tells us nothing about
	// the call's outcome and must not mask the real error being returned.
	defer func() { _ = resp.Body.Close() }()

	// Bounded read: a vendor returning an unbounded body must not be able
	// to exhaust a node running fifty sessions.
	payload, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, fmt.Errorf("geminijson: read: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("geminijson: status %d: %s", resp.StatusCode, truncate(payload))
	}

	var out wireResponse
	if err := json.Unmarshal(payload, &out); err != nil {
		return nil, fmt.Errorf("geminijson: decode envelope: %w", err)
	}
	if out.Error != nil {
		return nil, fmt.Errorf("geminijson: vendor error: %s", out.Error.Message)
	}
	if len(out.Candidates) == 0 || len(out.Candidates[0].Content.Parts) == 0 {
		return nil, fmt.Errorf("geminijson: empty response")
	}
	return []byte(out.Candidates[0].Content.Parts[0].Text), nil
}

func truncate(b []byte) string {
	const limit = 300
	if len(b) <= limit {
		return string(b)
	}
	return string(b[:limit]) + "…"
}
