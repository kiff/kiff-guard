// Package main — KIFF decide server for instant-payout-enablement-guard.
//
// Domain: Escrow moves CREATED -> CLEARED -> DISBURSED.
// DISBURSE_PAYOUT is allowed only from CLEARED. The enablement story:
// a payout agent disburses to the seller the moment escrow clears (allowed;
// the disbursement runs and the escrow advances to DISBURSED), and the same
// agent is then declined on any further disbursement attempt on the now-DISBURSED
// escrow. The boundary is what lets you make payouts instant at all — you
// don't hold for a human review gate once state says it's clear.
//
// Built on github.com/kiff/kiff v0.6.0.
package main

import (
	"context"
	"fmt"
	"time"

	"github.com/kiff/kiff/pkg/kiff/action"
	"github.com/kiff/kiff/pkg/kiff/actor"
	"github.com/kiff/kiff/pkg/kiff/adapter"
	"github.com/kiff/kiff/pkg/kiff/domain"
	"github.com/kiff/kiff/pkg/kiff/event"
	"github.com/kiff/kiff/pkg/kiff/permission"
	"github.com/kiff/kiff/pkg/kiff/runtime"
)

const (
	AdapterEscrow = "escrow"
	EntityEscrow  = "Escrow"

	EventEscrowCreated   = "ESCROW_CREATED"
	EventEscrowCleared   = "ESCROW_CLEARED"
	EventPayoutDisbursed = "PAYOUT_DISBURSED"

	StateCreated   = "CREATED"
	StateCleared   = "CLEARED"
	StateDisbursed = "DISBURSED"

	ActionDisbursePayout = "DISBURSE_PAYOUT"

	RolePayout = "payout"

	PermDisburse permission.Permission = "payout.disburse"
)

var AgentActor = actor.Actor{
	ID:          "payout-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Payout Agent",
	Roles:       []string{RolePayout},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("instant-payout-enablement").
		Entity(EntityEscrow).
		Event(EventEscrowCreated).
		Event(EventEscrowCleared).
		Event(EventPayoutDisbursed).
		Transition(EventEscrowCreated, "", StateCreated).
		Transition(EventEscrowCleared, StateCreated, StateCleared).
		Transition(EventPayoutDisbursed, StateCleared, StateDisbursed).
		Allow(StateCleared, ActionDisbursePayout).
		Action(disburseContract())
	return b.Build()
}

func disburseContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionDisbursePayout,
		AllowedStates:       []string{StateCleared},
		RequiredParameters:  []string{"amount_cents", "seller_id"},
		RequiredPermissions: []permission.Permission{PermDisburse},
		Risk:                action.RiskMedium,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName:     ActionDisbursePayout,
				EntityID:       ctx.EntityID,
				Status:         action.ExecutionSucceeded,
				Executed:       true,
				Message:        "payout disbursed instantly; agent ships the seller's money",
				EffectsSummary: "payout disbursed",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

// NewPermissionPolicy grants payout.disburse to the payout role and assigns
// the payout agent to it. Since v0.4.0 role membership is policy-owned:
// AssignRole is what authorizes the agent — without it every DISBURSE_PAYOUT
// is permission_denied (#19).
func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole(RolePayout, PermDisburse)
	p.AssignRole(AgentActor.ID, RolePayout)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterEscrow)
}

func NewRuntime() (*runtime.Runtime, error) {
	def, err := NewDomainDefinition()
	if err != nil {
		return nil, err
	}
	in, err := NewInputAdapter()
	if err != nil {
		return nil, err
	}
	return runtime.NewForDomain(def, runtime.Config{
		PermissionPolicy: NewPermissionPolicy(),
		Adapters:         []adapter.Adapter{in},
	})
}

func escrowEvent(escrowID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, escrowID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   escrowID,
		EntityType: EntityEscrow,
		Source:     "payout-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}
