// decide.go — ask KIFF to clear one action, from Go, no SDK.
//
// A proposal is one POST /v1/proposals/decide. withheld is defined as the
// negation of "allowed", so an outcome this program has never seen still
// withholds — the fail-safe rule. We send actor_id but never roles; the
// API key's roles govern server-side.
//
//	export KIFF_CLOUD_API_KEY=kiff_live_...
//	go run decide.go ord_123 Order REFUND_ORDER
//
// Copy decide() into your agent and replace runTool with the real side
// effect. stdlib-only; no modules to add.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

type proposal struct {
	EntityID   string                 `json:"entity_id"`
	EntityType string                 `json:"entity_type"`
	ActionName string                 `json:"action_name"`
	ActorID    string                 `json:"actor_id"`
	Parameters map[string]interface{} `json:"parameters"`
}

type decision struct {
	ProposalID string   `json:"proposal_id"`
	Outcome    string   `json:"outcome"`
	Reasons    []string `json:"reasons"`
	Message    string   `json:"message"`
}

// withheld is the negation of allowed: only an explicit "allowed" runs.
func (d decision) withheld() bool { return d.Outcome != "allowed" }

func decide(baseURL, apiKey string, p proposal) (decision, error) {
	body, _ := json.Marshal(p)
	req, err := http.NewRequest(http.MethodPost, baseURL+"/v1/proposals/decide", bytes.NewReader(body))
	if err != nil {
		return decision{}, err
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		// Transport error => fail closed: report an outcome that withholds.
		return decision{Outcome: "invalid", Message: err.Error()}, nil
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	var d decision
	if err := json.Unmarshal(raw, &d); err != nil || d.Outcome == "" {
		return decision{Outcome: "invalid", Message: fmt.Sprintf("status %d, no outcome", resp.StatusCode)}, nil
	}
	return d, nil
}

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "usage: go run decide.go <entity_id> <entity_type> <action_name>")
		os.Exit(2)
	}
	apiKey := os.Getenv("KIFF_CLOUD_API_KEY")
	if apiKey == "" {
		fmt.Fprintln(os.Stderr, "set KIFF_CLOUD_API_KEY=kiff_live_...")
		os.Exit(2)
	}
	baseURL := os.Getenv("KIFF_BASE_URL")
	if baseURL == "" {
		baseURL = "https://api.kiff.dev"
	}
	actor := os.Getenv("KIFF_ACTOR_ID")
	if actor == "" {
		actor = "custom-agent"
	}

	entityID, entityType, action := os.Args[1], os.Args[2], os.Args[3]
	fmt.Fprintf(os.Stderr, "→ POST /v1/proposals/decide  %s on %s/%s\n", action, entityType, entityID)

	d, err := decide(baseURL, apiKey, proposal{
		EntityID:   entityID,
		EntityType: entityType,
		ActionName: action,
		ActorID:    actor,
		Parameters: map[string]interface{}{},
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}

	if d.withheld() {
		reason := d.Message
		if reason == "" && len(d.Reasons) > 0 {
			reason = d.Reasons[0]
		}
		fmt.Fprintf(os.Stderr, "← %s", d.Outcome)
		if reason != "" {
			fmt.Fprintf(os.Stderr, ": %s", reason)
		}
		fmt.Fprintln(os.Stderr)
		fmt.Printf("WITHHELD: not running %s\n", action)
		os.Exit(1)
	}

	fmt.Fprintln(os.Stderr, "← allowed")
	// runTool: replace with your real side effect.
	fmt.Printf("RUN: %s on %s\n", action, entityID)
}
