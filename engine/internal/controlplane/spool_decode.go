package controlplane

import (
	"encoding/json"
	"errors"
)

// sessionIDOf reads just the session id out of a spooled payload.
func sessionIDOf(payload []byte) (string, error) {
	var head struct {
		SessionID string `json:"session_id"`
	}
	if err := json.Unmarshal(payload, &head); err != nil {
		return "", err
	}
	if head.SessionID == "" {
		return "", errors.New("spooled payload has no session id")
	}
	return head.SessionID, nil
}
